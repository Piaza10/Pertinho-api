import asyncio
import os

import pytest
from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext

from app.database import Base, engine

BANCO_DE_TESTE_CONFIGURADO = os.getenv("TEST_DATABASE_URL") is not None


async def obter_revisao_atual() -> str | None:
    try:
        async with engine.connect() as conexao:
            return await conexao.run_sync(
                lambda conexao_sincrona: MigrationContext.configure(
                    conexao_sincrona,
                ).get_current_revision(),
            )
    finally:
        await engine.dispose()


@pytest.mark.skipif(
    not BANCO_DE_TESTE_CONFIGURADO,
    reason="TEST_DATABASE_URL não configurada",
)
def test_alembic_aplica_revisao_inicial_sem_tabelas_de_negocio() -> None:
    configuracao = Config("alembic.ini")

    command.upgrade(configuracao, "head")
    revisao_atual = asyncio.run(obter_revisao_atual())

    assert revisao_atual == "0001"
    assert not Base.metadata.tables
