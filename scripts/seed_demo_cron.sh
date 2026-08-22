#!/usr/bin/env bash
# Nightly restore of the shared demo account.
#
# The demo is deliberately writable so it behaves like real software rather
# than a screenshot; this is what makes that safe. Runs inside the api
# container so it sees the same database and the same data/users volume the
# server does.
#
# Install from cron on the NAS -- see docs/DEPLOY-SEATTLE.md.
set -euo pipefail

# Resolved by name filter rather than a fixed container name, the same way
# every other operational command in DEPLOY-SEATTLE.md does: TrueNAS's
# "Install via YAML" apps do not give the container a predictable name.
CONTAINER="$(docker ps -qf name=applination-api | head -n1)"

if [ -z "$CONTAINER" ]; then
  echo "seed_demo_cron: no running applination-api container found" >&2
  exit 1
fi

docker exec "$CONTAINER" python scripts/seed_demo.py
