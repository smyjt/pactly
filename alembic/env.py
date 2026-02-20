import os
import sys
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

# Make sure the project root is on sys.path so we can import app.*
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

# Import all models so Alembic can see them for autogenerate
from app.models import Base  # noqa: E402

config = context.config

# Load database URL from environment (DATABASE_URL_SYNC uses the sync psycopg2 driver,
# not asyncpg, because Alembic's CLI is synchronous)
database_url = os.getenv(
    "DATABASE_URL_SYNC",
    "postgresql://pactly:pactly@localhost:5432/pactly",
)
config.set_main_option("sqlalchemy.url", database_url)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# This is what tells Alembic which tables to create/track
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Generate SQL scripts without connecting to DB (useful for review)."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Apply migrations directly to the running database."""
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
