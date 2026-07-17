import asyncio
import os
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import delete

from app.database import engine, session_factory
from app.models import Bracelet, BraceletStatus, Child
from app.services.bracelet_activation import (
    RecursoAtivacaoNaoEncontrado,
    ativar_bracelet,
)

BANCO_DE_TESTE_CONFIGURADO = os.getenv("TEST_DATABASE_URL") is not None
requer_banco_de_teste = pytest.mark.skipif(
    not BANCO_DE_TESTE_CONFIGURADO,
    reason="TEST_DATABASE_URL não configurada",
)


@pytest.fixture(scope="module", autouse=True)
def aplicar_migrations() -> Iterator[None]:
    if BANCO_DE_TESTE_CONFIGURADO:
        command.upgrade(Config("alembic.ini"), "head")

    yield


async def limpar_tabelas() -> None:
    async with session_factory.begin() as sessao:
        await sessao.execute(delete(Bracelet))
        await sessao.execute(delete(Child))


async def executar_ativacao_valida() -> None:
    try:
        await limpar_tabelas()
        async with session_factory.begin() as sessao:
            child = Child()
            bracelet = Bracelet()
            sessao.add_all([child, bracelet])
            await sessao.flush()
            child_id = child.id
            bracelet_id = bracelet.id

        inicio = datetime.now(UTC)
        async with session_factory() as sessao:
            resultado = await ativar_bracelet(
                sessao,
                bracelet_id,
                child_id,
            )
        fim = datetime.now(UTC)

        async with session_factory() as sessao:
            persistida = await sessao.get(Bracelet, bracelet_id)

        assert resultado.id == bracelet_id
        assert resultado.status is BraceletStatus.ATIVA
        assert resultado.child_id == child_id
        assert resultado.revoked_at is None
        assert resultado.activated_at is not None
        assert resultado.activated_at.utcoffset() == timedelta(0)
        assert inicio <= resultado.activated_at <= fim
        assert persistida is not None
        assert persistida.status is BraceletStatus.ATIVA
        assert persistida.child_id == child_id
        assert persistida.activated_at == resultado.activated_at
    finally:
        await limpar_tabelas()
        await engine.dispose()


async def executar_recurso_ausente(recurso_ausente: str) -> None:
    try:
        await limpar_tabelas()
        async with session_factory.begin() as sessao:
            child = None if recurso_ausente == "child" else Child()
            bracelet = (
                None if recurso_ausente == "bracelet" else Bracelet()
            )
            objetos = [
                objeto for objeto in (child, bracelet) if objeto is not None
            ]
            sessao.add_all(objetos)
            await sessao.flush()
            child_id = child.id if child is not None else uuid4()
            bracelet_id = bracelet.id if bracelet is not None else uuid4()

        async with session_factory() as sessao:
            with pytest.raises(RecursoAtivacaoNaoEncontrado) as erro:
                await ativar_bracelet(sessao, bracelet_id, child_id)

        assert str(erro.value) == "Recurso de ativação não encontrado"
        assert str(child_id) not in str(erro.value)
        assert str(bracelet_id) not in str(erro.value)

        if bracelet is not None:
            async with session_factory() as sessao:
                persistida = await sessao.get(Bracelet, bracelet_id)
            assert persistida is not None
            assert persistida.status is BraceletStatus.ESTOQUE
            assert persistida.child_id is None
            assert persistida.activated_at is None
    finally:
        await limpar_tabelas()
        await engine.dispose()


@requer_banco_de_teste
def test_ativa_bracelet_em_transacao_com_instante_utc_do_servico() -> None:
    asyncio.run(executar_ativacao_valida())


@requer_banco_de_teste
@pytest.mark.parametrize("recurso_ausente", ["bracelet", "child"])
def test_recurso_ausente_usa_erro_neutro_e_rollback(
    recurso_ausente: str,
) -> None:
    asyncio.run(executar_recurso_ausente(recurso_ausente))
