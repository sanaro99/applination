"""Restore the shared demo account to its committed fixture.

Run nightly from cron (see docs/DEPLOY-SEATTLE.md). The demo is deliberately
fully writable so it behaves like real software rather than a screenshot; this
is what undoes the consequences.

    python scripts/seed_demo.py           # wipe and re-seed
    python scripts/seed_demo.py --create  # create the account only, no wipe
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from server.demo import (  # noqa: E402
    DEMO_EMAIL,
    demo_enabled,
    ensure_demo_user,
    seed_demo,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Restore the shared demo account to its committed fixture."
    )
    parser.add_argument(
        "--create",
        action="store_true",
        help="only ensure the account exists; do not wipe or re-seed it",
    )
    args = parser.parse_args()
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s"
    )

    if not demo_enabled():
        print(
            "demo is disabled: DEMO_ENABLED=0, or demo_data/config.yaml is missing",
            file=sys.stderr,
        )
        return 1

    user_id = ensure_demo_user() if args.create else seed_demo()
    print(f"demo account {DEMO_EMAIL} ready (id={user_id})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
