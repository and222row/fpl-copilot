import asyncio
from logging.config import fileConfig
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import create_async_engine
from alembic import context
from app.database import Base
from app.config import settings

# Import all models so Alembic can see them in Base.metadata
import app.models  # noqa: F401

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata

# NOTE: we deliberately do NOT call config.set_main_option("sqlalchemy.url", ...).
# Alembic pushes that value through ConfigParser, which treats "%" as
# interpolation syntax and blows up on URL-encoded passwords. We read the URL
# straight from settings instead.
DB_URL = settings.database_url


def include_object(object, name, type_, reflected, compare_to):
    """
    Only manage tables we define ourselves.

    Supabase ships its own schemas/tables in the same database. Without this
    filter, autogenerate would emit DROP statements for anything it reflects
    that isn't in our metadata.
    """
    if type_ == "table" and reflected and name not in target_metadata.tables:
        return False
    return True


def run_migrations_offline() -> None:
    context.configure(
        url=DB_URL,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        include_object=include_object,
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        include_object=include_object,
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    # NullPool: migrations are one-shot, no need to keep connections around.
    connectable = create_async_engine(DB_URL, poolclass=None, echo=False)
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
