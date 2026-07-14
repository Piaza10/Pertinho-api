import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from app.config import Settings
from app.database import Base

config = context.config
config.set_main_option(
    "sqlalchemy.url",
    Settings().database_url.replace("%", "%%"),
)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

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


def executar_migrations(conexao: Connection) -> None:
    context.configure(connection=conexao, target_metadata=target_metadata)

    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    configuracao = config.get_section(config.config_ini_section, {})
    engine = async_engine_from_config(
        configuracao,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    async with engine.connect() as conexao:
        await conexao.run_sync(executar_migrations)

    await engine.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
