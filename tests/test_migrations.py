import asyncio
import os
from collections.abc import Iterator
from uuid import UUID

import pytest
from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from sqlalchemy import DateTime, String, Uuid, inspect

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


async def obter_schema_children() -> tuple[
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


async def obter_schema_bracelets() -> tuple[
    str | None,
    list[dict[str, object]],
    dict[str, object],
    list[dict[str, object]],
    list[dict[str, object]],
    list[dict[str, object]],
]:
    try:
        async with engine.connect() as conexao:
            def inspecionar(conexao_sincrona):
                inspetor = inspect(conexao_sincrona)
                revisao = MigrationContext.configure(
                    conexao_sincrona,
                ).get_current_revision()
                return (
                    revisao,
                    inspetor.get_columns("bracelets"),
                    inspetor.get_pk_constraint("bracelets"),
                    inspetor.get_unique_constraints("bracelets"),
                    inspetor.get_foreign_keys("bracelets"),
                    inspetor.get_check_constraints("bracelets"),
                )

            return await conexao.run_sync(inspecionar)
    finally:
        await engine.dispose()


async def tabela_existe(nome: str) -> bool:
    try:
        async with engine.connect() as conexao:
            return await conexao.run_sync(
                lambda conexao_sincrona: inspect(conexao_sincrona).has_table(
                    nome,
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
def test_alembic_preserva_children_com_somente_id() -> None:
    revisao_atual, colunas, chave_primaria = asyncio.run(
        obter_schema_children(),
    )

    assert revisao_atual == "0003"
    assert [coluna["name"] for coluna in colunas] == ["id"]
    assert chave_primaria["constrained_columns"] == ["id"]
    assert not colunas[0]["nullable"]
    assert colunas[0]["default"] is None


@requer_banco_de_teste
def test_alembic_aplica_0003_com_schema_de_bracelets() -> None:
    (
        revisao_atual,
        colunas,
        chave_primaria,
        unicidades,
        chaves_estrangeiras,
        checks,
    ) = asyncio.run(obter_schema_bracelets())

    colunas_por_nome = {coluna["name"]: coluna for coluna in colunas}
    nomes_unicidades = {constraint["name"] for constraint in unicidades}
    checks_por_nome = {
        constraint["name"]: constraint["sqltext"] for constraint in checks
    }

    assert revisao_atual == "0003"
    assert list(colunas_por_nome) == [
        "id",
        "public_token",
        "status",
        "child_id",
        "activated_at",
        "revoked_at",
    ]
    assert isinstance(colunas_por_nome["id"]["type"], Uuid)
    assert chave_primaria["constrained_columns"] == ["id"]
    assert isinstance(colunas_por_nome["public_token"]["type"], String)
    assert colunas_por_nome["public_token"]["type"].length == 43
    assert not colunas_por_nome["public_token"]["nullable"]
    assert "uq_bracelets_public_token" in nomes_unicidades
    assert "uq_bracelets_child_id" in nomes_unicidades
    assert "ESTOQUE" in colunas_por_nome["status"]["default"]
    assert isinstance(colunas_por_nome["activated_at"]["type"], DateTime)
    assert colunas_por_nome["activated_at"]["type"].timezone
    assert isinstance(colunas_por_nome["revoked_at"]["type"], DateTime)
    assert colunas_por_nome["revoked_at"]["type"].timezone
    assert len(chaves_estrangeiras) == 1
    chave_estrangeira = chaves_estrangeiras[0]
    assert chave_estrangeira["name"] == "fk_bracelets_child_id_children"
    assert chave_estrangeira["constrained_columns"] == ["child_id"]
    assert chave_estrangeira["referred_table"] == "children"
    assert chave_estrangeira["referred_columns"] == ["id"]
    assert chave_estrangeira["options"] == {}
    assert set(checks_por_nome) == {
        "bracelet_status",
        "ck_bracelets_estado_coerente",
    }
    check_status = checks_por_nome["bracelet_status"]
    assert all(
        status in check_status
        for status in ("ESTOQUE", "ATIVA", "DESVINCULADA", "PERDIDA")
    )
    check_estado = checks_por_nome["ck_bracelets_estado_coerente"]
    assert all(
        trecho in check_estado
        for trecho in (
            "status",
            "child_id",
            "activated_at",
            "revoked_at",
            "ESTOQUE",
            "ATIVA",
            "DESVINCULADA",
            "PERDIDA",
            "IS NULL",
            "IS NOT NULL",
        )
    )


@requer_banco_de_teste
def test_child_gera_uuid_ao_inserir() -> None:
    child_id = asyncio.run(inserir_child_sem_id())

    assert isinstance(child_id, UUID)


@requer_banco_de_teste
def test_downgrade_0003_remove_somente_bracelets(
    configuracao_alembic: Config,
) -> None:
    command.downgrade(configuracao_alembic, "0002")

    try:
        bracelets_existe = asyncio.run(tabela_existe("bracelets"))
        children_existe = asyncio.run(tabela_existe("children"))
    finally:
        command.upgrade(configuracao_alembic, "head")
        bracelets_restaurada = asyncio.run(tabela_existe("bracelets"))
        children_restaurada = asyncio.run(tabela_existe("children"))

    assert not bracelets_existe
    assert children_existe
    assert bracelets_restaurada
    assert children_restaurada
