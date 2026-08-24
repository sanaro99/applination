"""Check that provider console links still resolve.

Deliberately NOT a unit test: it makes real network calls, and network flake
must never break the build. Run it manually or on a schedule. A clean run is
what licenses bumping ``verified_on`` in server/provider_setup.py.

    python scripts/check_provider_links.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from server.provider_setup import PROVIDERS  # noqa: E402


def main() -> int:
    failures = 0
    with httpx.Client(follow_redirects=True, timeout=20.0) as client:
        for entry in PROVIDERS:
            url = entry["console_url"]
            try:
                resp = client.get(url)
            except Exception as exc:  # noqa: BLE001
                print(f"FAIL {entry['id']:12} {url} -> {exc}")
                failures += 1
                continue
            landed = str(resp.url)
            status = "OK  " if resp.status_code < 400 else "FAIL"
            if resp.status_code >= 400:
                failures += 1
            note = "" if landed == url else f"  (redirected to {landed})"
            print(f"{status} {entry['id']:12} {resp.status_code} {url}{note}")
    print()
    if failures:
        print(f"{failures} link(s) need attention. Do not bump verified_on.")
    else:
        print("All links resolved. Re-read the pages before bumping verified_on:")
        print("a 200 proves the URL lives, not that the steps still match.")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
