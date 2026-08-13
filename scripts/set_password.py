"""Set (or reset) a user's password from the console.

The migration that adopts an existing single-tenant install creates the owner
account with an unusable password hash and points here, so that no default
credential is ever committed to the repository or printed into a log.

    python scripts/set_password.py owner@example.com

Also useful for a genuine forgotten password: there is no email-based reset flow,
and for an owner-operated install a console reset is the honest mechanism.

Changing a password revokes every existing session for that user.
"""
from __future__ import annotations

import argparse
import getpass
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from sqlmodel import select  # noqa: E402

from server.auth import (  # noqa: E402
    MIN_PASSWORD_LENGTH,
    hash_password,
    normalize_email,
    revoke_all_sessions,
)
from server.db import User, session  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("email", help="the account's email address")
    ap.add_argument(
        "--password",
        help="skip the interactive prompt (avoid: this lands in shell history)",
    )
    ap.add_argument(
        "--list",
        action="store_true",
        help="list accounts and exit, without changing anything",
    )
    args = ap.parse_args()

    with session() as s:
        if args.list:
            # noscope: administrative CLI listing accounts; not a tenant table.
            for u in s.exec(select(User).order_by(User.id)).all():
                flag = " (owner)" if u.is_owner else ""
                state = " [disabled]" if u.disabled else ""
                print(f"  {u.id}\t{u.email}{flag}{state}")
            return 0

        email = normalize_email(args.email)
        # noscope: administrative CLI resolving the target account by email.
        user = s.exec(select(User).where(User.email == email)).first()
        if user is None:
            print(f"no account with email {email!r}", file=sys.stderr)
            print("run with --list to see the accounts that exist", file=sys.stderr)
            return 1

        password = args.password
        if not password:
            password = getpass.getpass(f"New password for {email}: ")
            if password != getpass.getpass("Repeat: "):
                print("passwords did not match", file=sys.stderr)
                return 1
        if len(password) < MIN_PASSWORD_LENGTH:
            print(
                f"password must be at least {MIN_PASSWORD_LENGTH} characters",
                file=sys.stderr,
            )
            return 1

        user.password_hash = hash_password(password)
        s.add(user)
        s.commit()
        revoked = revoke_all_sessions(s, user.id)  # type: ignore[arg-type]

    print(f"password set for {email}")
    if revoked:
        print(f"revoked {revoked} existing session(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
