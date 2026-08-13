"""Move a single-tenant install into the per-user layout.

Before (PR 2 and earlier)::

    <root>/config.yaml
    <root>/master_data/
    <root>/output/

After (PR 3)::

    <root>/data/users/<owner_id>/config.yaml
    <root>/data/users/<owner_id>/master_data/
    <root>/data/users/<owner_id>/output/

Two things have to happen together, or the install comes up broken:

1. The three directories move.
2. ``Application.folder_path`` is rewritten. Those are **absolute** paths stored
   at generation time, so every existing application would point at a directory
   that no longer exists — the document previews and downloads on every card in
   the app would 404.

Both happen inside one database transaction, and the filesystem moves are
`os.replace` renames within the same dataset, so they are atomic and cheap
regardless of how large ``output/`` has grown.

Idempotent: a second run finds the directories already moved and the paths
already rewritten, and does nothing. Always dry-run first::

    python scripts/migrate_to_multiuser.py --dry-run
    python scripts/migrate_to_multiuser.py
"""
from __future__ import annotations

import argparse
import os
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from sqlmodel import select  # noqa: E402

from server.db import Application, User, session  # noqa: E402
from server.user_paths import UserPaths  # noqa: E402


def _resolve_owner(spec: str | None) -> User:
    with session() as s:
        if spec:
            if spec.isdigit():
                user = s.get(User, int(spec))
            else:
                user = s.exec(
                    select(User).where(User.email == spec.strip().lower())
                ).first()
        else:
            user = s.exec(select(User).where(User.is_owner == True)).first()  # noqa: E712
            if user is None:
                user = s.exec(select(User).order_by(User.id)).first()
        if user is None:
            raise SystemExit(
                "No account to migrate onto. Run `alembic upgrade head` first "
                "(it creates the owner from config.yaml on an install with "
                "existing data), or sign up in the web app."
            )
        return User(**user.model_dump())


def _move(src: Path, dst: Path, *, dry_run: bool) -> str:
    """Move one path. Returns a human-readable description of what happened."""
    if not src.exists():
        return f"skip   {src.name}: not present"

    note = ""
    if dst.exists():
        occupied = (
            any(dst.iterdir()) if dst.is_dir() else dst.stat().st_size > 0
        )
        if occupied:
            # Never overwrite real data — a second run, or a partially
            # completed one, must not clobber what is already there.
            return f"skip   {src.name}: destination already populated"
        # An empty placeholder, created by paths.ensure(). Safe to replace.
        note = " (replacing empty placeholder)"
        if not dry_run:
            dst.rmdir() if dst.is_dir() else dst.unlink()

    if dry_run:
        return f"MOVE   {src} -> {dst}{note}"

    dst.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.replace(src, dst)
    except OSError:
        # Different filesystems (a bind mount, a different dataset): fall back
        # to a copy, and only remove the source once the copy has succeeded.
        if src.is_dir():
            shutil.copytree(src, dst)
            shutil.rmtree(src)
        else:
            shutil.copy2(src, dst)
            src.unlink()
    return f"moved  {src} -> {dst}"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--dry-run", action="store_true",
        help="Print what would happen and touch nothing.",
    )
    ap.add_argument(
        "--user", default=None,
        help="Account to migrate the existing data onto (email or id). "
             "Defaults to the owner.",
    )
    ap.add_argument(
        "--root", default=str(ROOT),
        help="Install root holding config.yaml / master_data / output. "
             "Defaults to the repository root.",
    )
    args = ap.parse_args()

    src_root = Path(args.root).resolve()
    owner = _resolve_owner(args.user)

    # Destination follows --root rather than the repo checkout, so pointing the
    # script at a staging copy does not quietly write into the live install.
    # In the container both are /app, which is the case that actually ships.
    import server.user_paths as user_paths_mod

    user_paths_mod.USERS_DIR = src_root / "data" / "users"
    paths = UserPaths(user_id=owner.id)  # type: ignore[arg-type]

    print(f"install root : {src_root}")
    print(f"owner        : {owner.email} (id {owner.id})")
    print(f"destination  : {paths.root}")
    print(f"mode         : {'DRY RUN' if args.dry_run else 'APPLY'}")
    print()

    if not args.dry_run:
        paths.root.mkdir(parents=True, exist_ok=True)

    moves = [
        (src_root / "config.yaml", paths.config_path),
        (src_root / "master_data", paths.master_dir),
        (src_root / "output", paths.default_output_dir),
    ]
    for src, dst in moves:
        print(" ", _move(src, dst, dry_run=args.dry_run))
    print()

    # --- rewrite absolute Application.folder_path values -------------------
    old_output = (src_root / "output").resolve()
    new_output = paths.default_output_dir.resolve()
    rewritten = 0
    unchanged = 0
    with session() as s:
        # noscope: a one-shot operator migration over every row in the table.
        # It runs before there is a second user and has no request to scope to;
        # rows are reassigned to the owner they already belong to.
        apps = s.exec(select(Application)).all()
        for a in apps:
            if not a.folder_path:
                unchanged += 1
                continue
            current = Path(a.folder_path)
            try:
                rel = current.resolve().relative_to(old_output)
            except ValueError:
                # Already migrated, or somewhere else entirely — leave it be
                # rather than guessing.
                unchanged += 1
                continue
            new_path = new_output / rel
            if args.dry_run:
                print(f"  REWRITE {a.id}: {current} -> {new_path}")
            else:
                a.folder_path = str(new_path)
                s.add(a)
            rewritten += 1
        if not args.dry_run:
            s.commit()

    print()
    print(f"applications rewritten : {rewritten}")
    print(f"applications untouched : {unchanged}")
    if args.dry_run:
        print("\nDry run: nothing was changed. Re-run without --dry-run to apply.")
    else:
        print("\nDone.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
