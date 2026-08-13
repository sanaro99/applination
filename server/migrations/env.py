"""Alembic environment.

The URL comes from ``server.db.database_url()`` rather than alembic.ini so that
migrations, the API, and the CLI can never disagree about which database they
are pointed at.
"""
from __future__ import annotations

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool
from sqlmodel import SQLModel

# Importing server.db registers every model on SQLModel.metadata. Without this
# import autogenerate sees an empty schema and cheerfully drops every table.
from server import db as _db  # noqa: F401
from server.db import database_url

config = context.config

# fileConfig() reconfigures logging process-wide and, by default, disables every
# logger that already exists. That is fine for the `alembic` CLI, which owns the
# process — but when migrations are invoked programmatically (the test suite,
# or anything embedding this) it silently tears down the caller's logging.
# Skip it when the caller opts out, and never disable their loggers.
if config.config_file_name is not None and config.attributes.get(
    "configure_logger", True
):
    fileConfig(config.config_file_name, disable_existing_loggers=False)

# A programmatic caller (the test suite) may set the URL on the Config object
# before invoking alembic; that wins. Otherwise fall back to the app's own
# resolution so the CLI and the server can never disagree. The %-escape is
# because ConfigParser interpolates this value.
if not config.get_main_option("sqlalchemy.url", None):
    config.set_main_option("sqlalchemy.url", database_url().replace("%", "%%"))

target_metadata = SQLModel.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            # compare_type catches a column whose Python type changed but whose
            # name did not — the failure mode autogenerate is otherwise blind to.
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
