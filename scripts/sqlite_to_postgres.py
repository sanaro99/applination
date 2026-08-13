"""One-time copy of the legacy SQLite database into Postgres.

Run this once, during the Postgres cutover, after `alembic upgrade head` has
created the schema on the target.

    python scripts/sqlite_to_postgres.py --sqlite data/app.db --dry-run
    python scripts/sqlite_to_postgres.py --sqlite data/app.db

The target URL comes from DATABASE_URL (same resolution the app uses). Primary
keys are preserved so every folder path, foreign key, and bookmarked URL that
references an id keeps working; sequences are then fast-forwarded past the
highest id so new inserts do not collide.

Refuses to touch a target that already holds rows unless --force is given.
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from sqlalchemy import Boolean, DateTime, Integer, inspect, select, text  # noqa: E402
from sqlmodel import SQLModel  # noqa: E402

from server import db as _db  # noqa: F401,E402  (registers the models)
from server.db import engine  # noqa: E402

# Parents before children. rankedjob references both run and application;
# savedanswer references both chatmessage and application.
TABLE_ORDER = [
    "setting",
    "run",
    "application",
    "rankedjob",
    "chatsession",
    "chatmessage",
    "savedanswer",
]


def _parse_datetime(value):
    """SQLite has no date type — these arrive as ISO-8601 strings."""
    if isinstance(value, datetime) or value is None:
        return value
    text_value = str(value).strip()
    if not text_value:
        return None
    try:
        return datetime.fromisoformat(text_value)
    except ValueError:
        # SQLAlchemy's SQLite driver writes "YYYY-MM-DD HH:MM:SS.ffffff"; older
        # rows may lack the fractional part. fromisoformat handles both on 3.11+,
        # so reaching here means genuinely unexpected data.
        for fmt in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
            try:
                return datetime.strptime(text_value, fmt)
            except ValueError:
                continue
        raise


def _coerce(value, column):
    """SQLite is dynamically typed; Postgres is not. Convert per target column."""
    if value is None:
        return None
    if isinstance(column.type, Boolean):
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "t", "yes"}
        return bool(value)
    if isinstance(column.type, DateTime):
        return _parse_datetime(value)
    return value


def _target_row_counts() -> dict[str, int]:
    counts: dict[str, int] = {}
    with engine.connect() as conn:
        for name in TABLE_ORDER:
            table = SQLModel.metadata.tables[name]
            counts[name] = conn.execute(
                select(text("count(*)")).select_from(table)
            ).scalar_one()
    return counts


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--sqlite", default=str(ROOT / "data" / "app.db"),
                    help="path to the legacy SQLite database")
    ap.add_argument("--dry-run", action="store_true",
                    help="report what would be copied, write nothing")
    ap.add_argument("--force", action="store_true",
                    help="copy even though the target already has rows")
    args = ap.parse_args()

    src_path = Path(args.sqlite)
    if not src_path.exists():
        print(f"error: no SQLite database at {src_path}", file=sys.stderr)
        return 1

    target = engine.url.render_as_string(hide_password=True)
    print(f"source: {src_path}")
    print(f"target: {target}\n")

    # The schema must already exist — this script copies data, it does not
    # create tables. Failing here means `alembic upgrade head` has not been run.
    missing = set(TABLE_ORDER) - set(inspect(engine).get_table_names())
    if missing:
        print(f"error: target is missing tables {sorted(missing)}; "
              "run `alembic upgrade head` first", file=sys.stderr)
        return 1

    existing = _target_row_counts()
    occupied = {t: n for t, n in existing.items() if n}
    if occupied and not args.force:
        print(f"error: target already holds rows {occupied}; refusing to copy. "
              "Use --force only if you intend to append.", file=sys.stderr)
        return 1

    src = sqlite3.connect(f"file:{src_path}?mode=ro", uri=True)
    src.row_factory = sqlite3.Row
    src_tables = {
        r[0] for r in src.execute(
            "select name from sqlite_master where type='table'"
        )
    }

    totals: dict[str, int] = {}
    with engine.begin() as conn:
        for name in TABLE_ORDER:
            table = SQLModel.metadata.tables[name]
            if name not in src_tables:
                print(f"{name:14} skipped (absent from source)")
                totals[name] = 0
                continue

            # Only copy columns present on both sides. A column the source lacks
            # takes its server default; a column the source has but the model
            # dropped is intentionally left behind.
            src_cols = {r[1] for r in src.execute(f'PRAGMA table_info("{name}")')}
            cols = [c for c in table.columns if c.name in src_cols]
            col_names = [c.name for c in cols]

            quoted = ", ".join(f'"{c}"' for c in col_names)
            rows = src.execute(f'SELECT {quoted} FROM "{name}"').fetchall()
            payload = [
                {c.name: _coerce(row[c.name], c) for c in cols} for row in rows
            ]
            totals[name] = len(payload)

            if args.dry_run:
                print(f"{name:14} would copy {len(payload):>5} rows "
                      f"({len(col_names)} columns)")
                continue

            if payload:
                conn.execute(table.insert(), payload)
            print(f"{name:14} copied {len(payload):>5} rows")

        # Sequences are a Postgres concept. The dialect guard exists so the
        # script can be exercised end-to-end against a scratch SQLite target
        # (which assigns ids from max(rowid) and needs no fixup).
        if not args.dry_run and conn.dialect.name == "postgresql":
            # Preserved primary keys leave every sequence at 1, so the next
            # insert would collide with row #1. Fast-forward past the max id.
            for name in TABLE_ORDER:
                pk = list(SQLModel.metadata.tables[name].primary_key.columns)
                # Only integer PKs sit behind a sequence — setting's is a text
                # key. Test with isinstance rather than `.python_type`, which
                # raises NotImplementedError on SQLModel's AutoString.
                if len(pk) != 1 or not isinstance(pk[0].type, Integer):
                    continue
                col = pk[0].name
                conn.execute(text(
                    f"SELECT setval(pg_get_serial_sequence('{name}', '{col}'),"
                    f" COALESCE((SELECT MAX({col}) FROM {name}), 0) + 1, false)"
                ))
            print("\nsequences fast-forwarded past the copied ids")

    src.close()
    print(f"\n{'would copy' if args.dry_run else 'copied'} "
          f"{sum(totals.values())} rows total")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
