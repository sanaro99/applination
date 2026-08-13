#!/bin/sh
# Container entrypoint: migrate, then serve.
#
# Running migrations here (rather than from the app at import time) keeps a
# single writer: if the container is ever scaled, only one instance should be
# applying DDL, and `alembic upgrade head` is safe to run repeatedly because it
# is a no-op once the database is at head.
set -eu

echo "entrypoint: applying database migrations"
python -m alembic upgrade head

echo "entrypoint: starting uvicorn"
exec uvicorn server.app:app --host 0.0.0.0 --port "${PORT:-8000}"
