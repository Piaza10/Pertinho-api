import asyncio
import os
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import delete, select

from app.database import engine, session_factory
from app.models import (
    Bracelet,
    BraceletStatus,
    Child,
    TransicaoBraceletInvalida,
)
from app.services.bracelet_replacement import (
    BraceletsTrocaIguais,
    RecursoTrocaNaoEncontrado,
    trocar_bracelet,
)

BANCO_DE_TESTE_CONFIGURADO = os.getenv("TEST_DATABASE_URL") is not None
requer_banco_de_teste = pytest.mark.skipif(
    not BANCO_DE_TESTE_CONFIGURADO,
    reason="TEST_DATABASE_URL não configurada",
)
ATIVACAO_ANTERIOR = datetime(2026, 1, 15, 12, tzinfo=UTC)
REVOGACAO_EXISTENTE = ATIVACAO_ANTERIOR + timedelta(hours=1)


@pytest.fixture(scope="module", autouse=True)
def aplicar_migrations() -> Iterator[None]:
    if BANCO_DE_TESTE_CONFIGURADO:
        command.upgrade(Config("alembic.ini"), "head")
    yield


async def limpar_tabelas() -> None:
    async with session_factory.begin() as sessao:
        await sessao.execute(delete(Bracelet))
        await sessao.execute(delete(Child))


async def criar_troca_valida() -> tuple[UUID, UUID, UUID, str, str]:
    async with session_factory.begin() as sessao:
        child = Child()
        anterior = Bracelet(
            status=BraceletStatus.ATIVA,
            child=child,
            activated_at=ATIVACAO_ANTERIOR,
        )
        nova = Bracelet()
        sessao.add_all([child, anterior, nova])
        await sessao.flush()
        return (
            child.id,
            anterior.id,
            nova.id,
            anterior.public_token,
            nova.public_token,
        )


async def executar_troca_valida() -> None:
    try:
        await limpar_tabelas()
        (
            child_id,
            anterior_id,
            nova_id,
            anterior_token,
            nova_token,
        ) = await criar_troca_valida()

        inicio = datetime.now(UTC)
        async with session_factory() as sessao:
            anterior, nova = await trocar_bracelet(
                sessao,
                anterior_id,
                nova_id,
            )
            sessao_reutilizavel = await sessao.scalar(select(Bracelet.id))
        fim = datetime.now(UTC)

        assert sessao_reutilizavel is not None
        assert anterior.id == anterior_id
        assert anterior.public_token == anterior_token
        assert anterior.status is BraceletStatus.DESVINCULADA
        assert anterior.child_id is None
        assert anterior.activated_at == ATIVACAO_ANTERIOR
        assert anterior.revoked_at is not None
        assert inicio <= anterior.revoked_at <= fim
        assert anterior.revoked_at.utcoffset() == timedelta(0)
        assert nova.id == nova_id
        assert nova.public_token == nova_token
        assert nova.status is BraceletStatus.ATIVA
        assert nova.child_id == child_id
        assert nova.activated_at == anterior.revoked_at
        assert nova.revoked_at is None

        async with session_factory() as sessao:
            anterior_persistida = await sessao.get(Bracelet, anterior_id)
            nova_persistida = await sessao.get(Bracelet, nova_id)

        assert anterior_persistida is not None
        assert anterior_persistida.public_token == anterior_token
        assert anterior_persistida.status is BraceletStatus.DESVINCULADA
        assert anterior_persistida.child_id is None
        assert anterior_persistida.activated_at == ATIVACAO_ANTERIOR
        assert anterior_persistida.revoked_at == anterior.revoked_at
        assert nova_persistida is not None
        assert nova_persistida.public_token == nova_token
        assert nova_persistida.status is BraceletStatus.ATIVA
        assert nova_persistida.child_id == child_id
        assert nova_persistida.activated_at == anterior.revoked_at
        assert nova_persistida.revoked_at is None
    finally:
        await limpar_tabelas()
        await engine.dispose()


async def executar_ids_iguais() -> None:
    bracelet_id = uuid4()
    try:
        await limpar_tabelas()
        async with session_factory() as sessao:
            with pytest.raises(BraceletsTrocaIguais) as erro:
                await trocar_bracelet(sessao, bracelet_id, bracelet_id)
            assert sessao.in_transaction() is False
            assert await sessao.scalar(select(1)) == 1

        assert str(erro.value) == "As pulseiras da troca devem ser distintas"
        assert str(bracelet_id) not in str(erro.value)
    finally:
        await limpar_tabelas()
        await engine.dispose()


async def executar_recurso_ausente(recurso: str) -> None:
    try:
        await limpar_tabelas()
        if recurso == "anterior":
            anterior_id = uuid4()
            child_id = None
            async with session_factory.begin() as sessao:
                nova = Bracelet()
                sessao.add(nova)
                await sessao.flush()
                nova_id = nova.id
        else:
            child_id, anterior_id, _, _, _ = await criar_troca_valida()
            nova_id = uuid4()

        async with session_factory() as sessao:
            with pytest.raises(RecursoTrocaNaoEncontrado) as erro:
                await trocar_bracelet(sessao, anterior_id, nova_id)
            assert await sessao.scalar(select(1)) == 1

        mensagem = str(erro.value)
        assert mensagem == "Recurso de troca não encontrado"
        assert str(anterior_id) not in mensagem
        assert str(nova_id) not in mensagem

        async with session_factory() as sessao:
            if recurso == "anterior":
                nova_persistida = await sessao.get(Bracelet, nova_id)
                assert nova_persistida is not None
                assert nova_persistida.status is BraceletStatus.ESTOQUE
            else:
                anterior_persistida = await sessao.get(
                    Bracelet,
                    anterior_id,
                )
                assert anterior_persistida is not None
                assert anterior_persistida.status is BraceletStatus.ATIVA
                assert anterior_persistida.child_id == child_id
    finally:
        await limpar_tabelas()
        await engine.dispose()


def parametros_estado_final(
    status: BraceletStatus,
) -> dict[str, object]:
    if status is BraceletStatus.ESTOQUE:
        return {"status": status}
    return {
        "status": status,
        "activated_at": ATIVACAO_ANTERIOR,
        "revoked_at": REVOGACAO_EXISTENTE,
    }


async def executar_estado_anterior_invalido(
    status: BraceletStatus,
) -> None:
    try:
        await limpar_tabelas()
        async with session_factory.begin() as sessao:
            anterior = Bracelet(**parametros_estado_final(status))
            nova = Bracelet()
            sessao.add_all([anterior, nova])
            await sessao.flush()
            anterior_id = anterior.id
            nova_id = nova.id
            anterior_token = anterior.public_token
            nova_token = nova.public_token

        async with session_factory() as sessao:
            with pytest.raises(TransicaoBraceletInvalida) as erro:
                await trocar_bracelet(sessao, anterior_id, nova_id)
            assert await sessao.scalar(select(1)) == 1

        assert erro.value.origem is status
        assert erro.value.destino is BraceletStatus.DESVINCULADA
        assert str(anterior_id) not in str(erro.value)
        assert str(nova_id) not in str(erro.value)
        assert anterior_token not in str(erro.value)
        assert nova_token not in str(erro.value)

        async with session_factory() as sessao:
            anterior_persistida = await sessao.get(Bracelet, anterior_id)
            nova_persistida = await sessao.get(Bracelet, nova_id)
        assert anterior_persistida is not None
        assert anterior_persistida.status is status
        assert nova_persistida is not None
        assert nova_persistida.status is BraceletStatus.ESTOQUE
    finally:
        await limpar_tabelas()
        await engine.dispose()


async def executar_estado_novo_invalido(status: BraceletStatus) -> None:
    try:
        await limpar_tabelas()
        async with session_factory.begin() as sessao:
            child_anterior = Child()
            anterior = Bracelet(
                status=BraceletStatus.ATIVA,
                child=child_anterior,
                activated_at=ATIVACAO_ANTERIOR,
            )
            if status is BraceletStatus.ATIVA:
                child_nova = Child()
                nova = Bracelet(
                    status=status,
                    child=child_nova,
                    activated_at=ATIVACAO_ANTERIOR,
                )
                sessao.add(child_nova)
            else:
                nova = Bracelet(**parametros_estado_final(status))
            sessao.add_all([child_anterior, anterior, nova])
            await sessao.flush()
            child_anterior_id = child_anterior.id
            anterior_id = anterior.id
            nova_id = nova.id
            anterior_token = anterior.public_token
            nova_token = nova.public_token

        async with session_factory() as sessao:
            with pytest.raises(TransicaoBraceletInvalida) as erro:
                await trocar_bracelet(sessao, anterior_id, nova_id)
            assert await sessao.scalar(select(1)) == 1

        assert erro.value.origem is status
        assert erro.value.destino is BraceletStatus.ATIVA
        assert str(anterior_id) not in str(erro.value)
        assert str(nova_id) not in str(erro.value)
        assert anterior_token not in str(erro.value)
        assert nova_token not in str(erro.value)

        async with session_factory() as sessao:
            anterior_persistida = await sessao.get(Bracelet, anterior_id)
            nova_persistida = await sessao.get(Bracelet, nova_id)
        assert anterior_persistida is not None
        assert anterior_persistida.status is BraceletStatus.ATIVA
        assert anterior_persistida.child_id == child_anterior_id
        assert anterior_persistida.revoked_at is None
        assert nova_persistida is not None
        assert nova_persistida.status is status
    finally:
        await limpar_tabelas()
        await engine.dispose()


@requer_banco_de_teste
def test_troca_bracelets_em_transacao_com_mesmo_instante_utc() -> None:
    asyncio.run(executar_troca_valida())


@requer_banco_de_teste
def test_rejeita_ids_iguais_antes_da_transacao() -> None:
    asyncio.run(executar_ids_iguais())


@requer_banco_de_teste
@pytest.mark.parametrize("recurso", ["anterior", "nova"])
def test_recurso_ausente_usa_erro_neutro_e_rollback(recurso: str) -> None:
    asyncio.run(executar_recurso_ausente(recurso))


@requer_banco_de_teste
@pytest.mark.parametrize(
    "status",
    [
        BraceletStatus.ESTOQUE,
        BraceletStatus.DESVINCULADA,
        BraceletStatus.PERDIDA,
    ],
)
def test_rejeita_estado_invalido_da_bracelet_anterior(
    status: BraceletStatus,
) -> None:
    asyncio.run(executar_estado_anterior_invalido(status))


@requer_banco_de_teste
@pytest.mark.parametrize(
    "status",
    [
        BraceletStatus.ATIVA,
        BraceletStatus.DESVINCULADA,
        BraceletStatus.PERDIDA,
    ],
)
def test_reverte_desvinculacao_quando_nova_bracelet_e_invalida(
    status: BraceletStatus,
) -> None:
    asyncio.run(executar_estado_novo_invalido(status))
