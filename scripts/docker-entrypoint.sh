#!/bin/sh
# Container entrypoint: migrate, then serve.
#
# Running migrations here (rather than from the app at import time) keeps a
# single writer: if the container is ever scaled, only one instance should be
# applying DDL, and `alembic upgrade head` is safe to run repeatedly because it
# is a no-op once the database is at head.
set -eu

# Encryption key for stored provider keys and Gmail tokens. An explicit
# APPLINATION_SECRET_KEY always wins. Otherwise, when APPLINATION_SECRET_KEY_FILE
# is set (the root docker-compose.yml sets it), read the key from that file and
# create it on first start, so a one-command install never needs a manual key
# step. The file sits in the persistent data mount; back it up with the data,
# because without it stored keys cannot be decrypted.
if [ -z "${APPLINATION_SECRET_KEY:-}" ] && [ -n "${APPLINATION_SECRET_KEY_FILE:-}" ]; then
    key_file="$APPLINATION_SECRET_KEY_FILE"
    if [ ! -s "$key_file" ]; then
        echo "entrypoint: creating encryption key at $key_file"
        mkdir -p "$(dirname "$key_file")"
        (umask 077 && python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())" > "$key_file")
    fi
    APPLINATION_SECRET_KEY="$(tr -d '[:space:]' < "$key_file")"
    export APPLINATION_SECRET_KEY
fi

echo "entrypoint: applying database migrations"
python -m alembic upgrade head

echo "entrypoint: starting uvicorn"
exec uvicorn server.app:app --host 0.0.0.0 --port "${PORT:-8000}"
