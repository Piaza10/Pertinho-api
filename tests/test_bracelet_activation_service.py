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
from app.models import (
    Bracelet,
    BraceletStatus,
    Child,
    TransicaoBraceletInvalida,
)
from app.services.bracelet_activation import (
    ConflitoAtivacaoBracelet,
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


async def executar_conflito_de_vinculo() -> None:
    try:
        await limpar_tabelas()
        async with session_factory.begin() as sessao:
            child = Child()
            vinculada = Bracelet(
                status=BraceletStatus.ATIVA,
                child=child,
                activated_at=datetime.now(UTC),
            )
            alvo = Bracelet()
            sessao.add_all([child, vinculada, alvo])
            await sessao.flush()
            child_id = child.id
            vinculada_id = vinculada.id
            alvo_id = alvo.id

        async with session_factory() as sessao:
            with pytest.raises(ConflitoAtivacaoBracelet) as erro:
                await ativar_bracelet(sessao, alvo_id, child_id)

        assert str(erro.value) == "Criança já possui pulseira vinculada"
        assert str(child_id) not in str(erro.value)
        assert str(vinculada_id) not in str(erro.value)
        assert str(alvo_id) not in str(erro.value)

        async with session_factory() as sessao:
            alvo_persistido = await sessao.get(Bracelet, alvo_id)
            vinculada_persistida = await sessao.get(
                Bracelet,
                vinculada_id,
            )

        assert alvo_persistido is not None
        assert alvo_persistido.status is BraceletStatus.ESTOQUE
        assert alvo_persistido.child_id is None
        assert alvo_persistido.activated_at is None
        assert vinculada_persistida is not None
        assert vinculada_persistida.status is BraceletStatus.ATIVA
        assert vinculada_persistida.child_id == child_id
    finally:
        await limpar_tabelas()
        await engine.dispose()


async def executar_transicao_invalida() -> None:
    ativacao = datetime.now(UTC)
    revogacao = ativacao + timedelta(minutes=1)
    try:
        await limpar_tabelas()
        async with session_factory.begin() as sessao:
            child = Child()
            bracelet = Bracelet(
                status=BraceletStatus.DESVINCULADA,
                activated_at=ativacao,
                revoked_at=revogacao,
            )
            sessao.add_all([child, bracelet])
            await sessao.flush()
            child_id = child.id
            bracelet_id = bracelet.id

        async with session_factory() as sessao:
            with pytest.raises(TransicaoBraceletInvalida):
                await ativar_bracelet(sessao, bracelet_id, child_id)

        async with session_factory() as sessao:
            persistida = await sessao.get(Bracelet, bracelet_id)

        assert persistida is not None
        assert persistida.status is BraceletStatus.DESVINCULADA
        assert persistida.child_id is None
        assert persistida.activated_at == ativacao
        assert persistida.revoked_at == revogacao
    finally:
        await limpar_tabelas()
        await engine.dispose()


@requer_banco_de_teste
def test_rejeita_child_ja_vinculada_sem_mutacao_parcial() -> None:
    asyncio.run(executar_conflito_de_vinculo())


@requer_banco_de_teste
def test_preserva_erro_de_dominio_e_faz_rollback() -> None:
    asyncio.run(executar_transicao_invalida())
