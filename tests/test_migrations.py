import asyncio
import os
from collections.abc import Iterator
from uuid import UUID

import pytest
from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from sqlalchemy import inspect

from app.database import engine, session_factory
from app.models import Child

BANCO_DE_TESTE_CONFIGURADO = os.getenv("TEST_DATABASE_URL") is not None
requer_banco_de_teste = pytest.mark.skipif(
    not BANCO_DE_TESTE_CONFIGURADO,
    reason="TEST_DATABASE_URL não configurada",
)


@pytest.fixture(scope="module")
def configuracao_alembic() -> Config:
    return Config("alembic.ini")


@pytest.fixture(scope="module", autouse=True)
def aplicar_migrations(configuracao_alembic: Config) -> Iterator[None]:
    if BANCO_DE_TESTE_CONFIGURADO:
        command.upgrade(configuracao_alembic, "head")

    yield


async def obter_revisao_colunas_e_pk() -> tuple[
    str | None,
    list[dict[str, object]],
    dict[str, object],
]:
    try:
        async with engine.connect() as conexao:
            revisao = await conexao.run_sync(
                lambda conexao_sincrona: MigrationContext.configure(
                    conexao_sincrona,
                ).get_current_revision(),
            )
            colunas = await conexao.run_sync(
                lambda conexao_sincrona: inspect(conexao_sincrona).get_columns(
                    "children",
                ),
            )
            chave_primaria = await conexao.run_sync(
                lambda conexao_sincrona: inspect(
                    conexao_sincrona,
                ).get_pk_constraint("children"),
            )
            return revisao, colunas, chave_primaria
    finally:
        await engine.dispose()


async def children_existe() -> bool:
    try:
        async with engine.connect() as conexao:
            return await conexao.run_sync(
                lambda conexao_sincrona: inspect(conexao_sincrona).has_table(
                    "children",
                ),
            )
    finally:
        await engine.dispose()


async def inserir_child_sem_id() -> UUID:
    try:
        async with session_factory() as sessao:
            child = Child()
            sessao.add(child)
            await sessao.flush()
            child_id = child.id
            await sessao.rollback()
            return child_id
    finally:
        await engine.dispose()


@requer_banco_de_teste
def test_alembic_aplica_0002_com_somente_id() -> None:
    revisao_atual, colunas, chave_primaria = asyncio.run(
        obter_revisao_colunas_e_pk(),
    )

    assert revisao_atual == "0002"
    assert [coluna["name"] for coluna in colunas] == ["id"]
    assert chave_primaria["constrained_columns"] == ["id"]
    assert not colunas[0]["nullable"]
    assert colunas[0]["default"] is None


@requer_banco_de_teste
def test_child_gera_uuid_ao_inserir() -> None:
    child_id = asyncio.run(inserir_child_sem_id())

    assert isinstance(child_id, UUID)


@requer_banco_de_teste
def test_downgrade_0002_remove_children(
    configuracao_alembic: Config,
) -> None:
    command.downgrade(configuracao_alembic, "0001")

    try:
        tabela_existe = asyncio.run(children_existe())
    finally:
        command.upgrade(configuracao_alembic, "head")
        tabela_restaurada = asyncio.run(children_existe())

    assert not tabela_existe
    assert tabela_restaurada
