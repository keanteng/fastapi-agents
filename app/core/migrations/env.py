"""Alembic environment.

Migrations use the SQLAlchemy URL from ``settings.database_url`` with the
async driver swapped to a sync one (asyncpg -> psycopg2) so alembic's sync
runner works. To autogenerate::

    uv run alembic revision --autogenerate -m "describe change"

To apply::

    uv run alembic upgrade head
"""

from __future__ import annotations

import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import engine_from_config, make_url, pool

from app.core.config import settings
from app.core.db import Base

# Import every slice's models module here so ``Base.metadata`` includes them.
from app.features.memory import models as _memory_models  # noqa: F401

# Ensure the project root is importable when alembic runs from any cwd.
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

config_ini = Path(__file__).resolve().parent.parent.parent.parent / "alembic.ini"
fileConfig(str(config_ini))

config = context.config


def _sync_url(url: str) -> str:
    """Replace the async driver with psycopg2 for alembic's sync runner."""
    parsed = make_url(url)
    if parsed.drivername == "postgresql+asyncpg":
        return parsed.set(drivername="postgresql+psycopg2").render_as_string(
            hide_password=False
        )
    return url


config.set_main_option("sqlalchemy.url", _sync_url(settings.database_url))

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
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
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
