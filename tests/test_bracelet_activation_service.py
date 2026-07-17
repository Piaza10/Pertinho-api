import asyncio
import os
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import delete, event, select, text
from sqlalchemy.ext.asyncio import AsyncSession

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


async def aguardar_espera_por_lock(
    backend_pid: int,
    tarefa: asyncio.Task[Bracelet],
) -> bool:
    for _ in range(100):
        if tarefa.done():
            return False
        async with session_factory() as monitor:
            esperando = await monitor.scalar(
                text(
                    "SELECT wait_event_type = 'Lock' "
                    "FROM pg_stat_activity WHERE pid = :pid",
                ),
                {"pid": backend_pid},
            )
        if esperando is True:
            return True
        await asyncio.sleep(0.01)
    return False


async def executar_prova_de_bloqueio_child() -> None:
    tarefa: asyncio.Task[Bracelet] | None = None
    try:
        await limpar_tabelas()
        async with session_factory.begin() as sessao:
            child = Child()
            bracelet = Bracelet()
            sessao.add_all([child, bracelet])
            await sessao.flush()
            child_id = child.id
            bracelet_id = bracelet.id

        async with (
            session_factory() as bloqueadora,
            engine.connect() as conexao_servico,
        ):
            backend_pid = await conexao_servico.scalar(
                text("SELECT pg_backend_pid()"),
            )
            assert backend_pid is not None
            await conexao_servico.rollback()

            async with AsyncSession(
                bind=conexao_servico,
                expire_on_commit=False,
            ) as servico:
                async with bloqueadora.begin():
                    await bloqueadora.scalar(
                        select(Child)
                        .where(Child.id == child_id)
                        .with_for_update(),
                    )

                    tarefa = asyncio.create_task(
                        ativar_bracelet(servico, bracelet_id, child_id),
                    )
                    esperou_pelo_lock = await aguardar_espera_por_lock(
                        backend_pid,
                        tarefa,
                    )

                resultado = await tarefa

        assert esperou_pelo_lock is True
        assert resultado.status is BraceletStatus.ATIVA
        assert resultado.child_id == child_id
    finally:
        if tarefa is not None:
            if not tarefa.done():
                tarefa.cancel()
            await asyncio.gather(tarefa, return_exceptions=True)
        await limpar_tabelas()
        await engine.dispose()


async def executar_prova_da_ordem_das_consultas() -> None:
    consultas: list[str] = []

    def registrar_consulta(
        _conexao: object,
        _cursor: object,
        statement: str,
        _parametros: object,
        _contexto: object,
        _executemany: bool,
    ) -> None:
        if statement.lstrip().startswith("SELECT"):
            consultas.append(" ".join(statement.split()))

    try:
        await limpar_tabelas()
        async with session_factory.begin() as sessao:
            child = Child()
            bracelet = Bracelet()
            sessao.add_all([child, bracelet])
            await sessao.flush()
            child_id = child.id
            bracelet_id = bracelet.id

        event.listen(
            engine.sync_engine,
            "before_cursor_execute",
            registrar_consulta,
        )
        try:
            async with session_factory() as sessao:
                await ativar_bracelet(sessao, bracelet_id, child_id)
        finally:
            event.remove(
                engine.sync_engine,
                "before_cursor_execute",
                registrar_consulta,
            )

        assert "FROM children" in consultas[0]
        assert "FOR UPDATE" in consultas[0]
        assert "FROM bracelets" in consultas[1]
        assert "FOR UPDATE" in consultas[1]
    finally:
        await limpar_tabelas()
        await engine.dispose()


async def executar_ativacoes_concorrentes() -> None:
    tarefas: list[asyncio.Task[str]] = []
    try:
        await limpar_tabelas()
        async with session_factory.begin() as sessao:
            child = Child()
            primeira = Bracelet()
            segunda = Bracelet()
            sessao.add_all([child, primeira, segunda])
            await sessao.flush()
            child_id = child.id
            bracelet_ids = (primeira.id, segunda.id)

        inicio = asyncio.Event()

        async def tentar_ativar(bracelet_id: UUID) -> str:
            await inicio.wait()
            async with session_factory() as sessao:
                try:
                    await ativar_bracelet(sessao, bracelet_id, child_id)
                except ConflitoAtivacaoBracelet:
                    return "conflito"
                return "ativada"

        tarefas = [
            asyncio.create_task(tentar_ativar(bracelet_id))
            for bracelet_id in bracelet_ids
        ]
        await asyncio.sleep(0)
        inicio.set()
        resultados = await asyncio.gather(*tarefas)

        assert resultados.count("ativada") == 1
        assert resultados.count("conflito") == 1

        async with session_factory() as sessao:
            pulseiras = [
                await sessao.get(Bracelet, bracelet_id)
                for bracelet_id in bracelet_ids
            ]

        assert all(bracelet is not None for bracelet in pulseiras)
        assert sum(
            bracelet.status is BraceletStatus.ATIVA
            for bracelet in pulseiras
            if bracelet is not None
        ) == 1
        assert sum(
            bracelet.status is BraceletStatus.ESTOQUE
            for bracelet in pulseiras
            if bracelet is not None
        ) == 1
        assert sum(
            bracelet.child_id == child_id
            for bracelet in pulseiras
            if bracelet is not None
        ) == 1
    finally:
        for tarefa in tarefas:
            if not tarefa.done():
                tarefa.cancel()
        if tarefas:
            await asyncio.gather(*tarefas, return_exceptions=True)
        await limpar_tabelas()
        await engine.dispose()


@requer_banco_de_teste
def test_ativacao_aguarda_bloqueio_pessimista_da_child() -> None:
    asyncio.run(executar_prova_de_bloqueio_child())


@requer_banco_de_teste
def test_bloqueia_child_antes_de_bracelet() -> None:
    asyncio.run(executar_prova_da_ordem_das_consultas())


@requer_banco_de_teste
def test_serializa_duas_ativacoes_para_a_mesma_child() -> None:
    asyncio.run(executar_ativacoes_concorrentes())
