import asyncio
import os
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from time import monotonic
from typing import Any
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import delete, event, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import engine, session_factory
from app.models import (
    Bracelet,
    BraceletStatus,
    Child,
    TransicaoBraceletInvalida,
)
from app.services.bracelet_loss import (
    ConflitoPerdaBracelet,
    RecursoPerdaNaoEncontrado,
    marcar_bracelet_como_perdida,
)

BANCO_DE_TESTE_CONFIGURADO = os.getenv("TEST_DATABASE_URL") is not None
requer_banco_de_teste = pytest.mark.skipif(
    not BANCO_DE_TESTE_CONFIGURADO,
    reason="TEST_DATABASE_URL não configurada",
)
ATIVACAO = datetime(2026, 1, 15, 12, tzinfo=UTC)
REVOGACAO_EXISTENTE = ATIVACAO + timedelta(hours=1)


@pytest.fixture(scope="module", autouse=True)
def aplicar_migrations() -> Iterator[None]:
    if BANCO_DE_TESTE_CONFIGURADO:
        command.upgrade(Config("alembic.ini"), "head")
    yield


async def limpar_tabelas() -> None:
    async with session_factory.begin() as sessao:
        await sessao.execute(delete(Bracelet))
        await sessao.execute(delete(Child))


async def executar_perda_valida() -> None:
    try:
        await limpar_tabelas()
        async with session_factory.begin() as sessao:
            child = Child()
            bracelet = Bracelet(
                status=BraceletStatus.ATIVA,
                child=child,
                activated_at=ATIVACAO,
            )
            sessao.add_all([child, bracelet])
            await sessao.flush()
            bracelet_id = bracelet.id

        inicio = datetime.now(UTC)
        async with session_factory() as sessao:
            resultado = await marcar_bracelet_como_perdida(
                sessao,
                bracelet_id,
            )
        fim = datetime.now(UTC)

        async with session_factory() as sessao:
            persistida = await sessao.get(Bracelet, bracelet_id)

        assert resultado.status is BraceletStatus.PERDIDA
        assert resultado.child_id is None
        assert resultado.activated_at == ATIVACAO
        assert resultado.revoked_at is not None
        assert resultado.revoked_at.utcoffset() == timedelta(0)
        assert inicio <= resultado.revoked_at <= fim
        assert persistida is not None
        assert persistida.status is BraceletStatus.PERDIDA
        assert persistida.child_id is None
        assert persistida.activated_at == ATIVACAO
        assert persistida.revoked_at == resultado.revoked_at
    finally:
        await limpar_tabelas()
        await engine.dispose()


async def executar_recurso_ausente() -> None:
    bracelet_id = uuid4()
    try:
        await limpar_tabelas()
        async with session_factory() as sessao:
            with pytest.raises(RecursoPerdaNaoEncontrado) as erro:
                await marcar_bracelet_como_perdida(sessao, bracelet_id)

        assert str(erro.value) == "Recurso de perda não encontrado"
        assert str(bracelet_id) not in str(erro.value)
    finally:
        await limpar_tabelas()
        await engine.dispose()


async def executar_estado_invalido(status: BraceletStatus) -> None:
    try:
        await limpar_tabelas()
        async with session_factory.begin() as sessao:
            if status is BraceletStatus.ESTOQUE:
                bracelet = Bracelet()
            else:
                bracelet = Bracelet(
                    status=status,
                    activated_at=ATIVACAO,
                    revoked_at=REVOGACAO_EXISTENTE,
                )
            sessao.add(bracelet)
            await sessao.flush()
            bracelet_id = bracelet.id

        async with session_factory() as sessao:
            with pytest.raises(TransicaoBraceletInvalida) as erro:
                await marcar_bracelet_como_perdida(sessao, bracelet_id)

        assert str(bracelet_id) not in str(erro.value)
        async with session_factory() as sessao:
            persistida = await sessao.get(Bracelet, bracelet_id)

        assert persistida is not None
        assert persistida.status is status
        assert persistida.child_id is None
        if status is BraceletStatus.ESTOQUE:
            assert persistida.activated_at is None
            assert persistida.revoked_at is None
        else:
            assert persistida.activated_at == ATIVACAO
            assert persistida.revoked_at == REVOGACAO_EXISTENTE
    finally:
        await limpar_tabelas()
        await engine.dispose()


@requer_banco_de_teste
def test_marca_bracelet_como_perdida_em_transacao() -> None:
    asyncio.run(executar_perda_valida())


@requer_banco_de_teste
def test_recurso_ausente_usa_erro_neutro() -> None:
    asyncio.run(executar_recurso_ausente())


@requer_banco_de_teste
@pytest.mark.parametrize(
    "status",
    [
        BraceletStatus.ESTOQUE,
        BraceletStatus.DESVINCULADA,
        BraceletStatus.PERDIDA,
    ],
)
def test_preserva_transicao_invalida_e_estado_persistido(
    status: BraceletStatus,
) -> None:
    asyncio.run(executar_estado_invalido(status))


async def executar_prova_da_ordem_dos_locks() -> None:
    consultas_com_lock: list[str] = []

    def registrar_consulta(
        _conexao: object,
        _cursor: object,
        statement: str,
        _parametros: object,
        _contexto: object,
        _executemany: bool,
    ) -> None:
        normalizada = " ".join(statement.split())
        if "FOR UPDATE" in normalizada:
            consultas_com_lock.append(normalizada)

    try:
        await limpar_tabelas()
        async with session_factory.begin() as sessao:
            child = Child()
            bracelet = Bracelet(
                status=BraceletStatus.ATIVA,
                child=child,
                activated_at=ATIVACAO,
            )
            sessao.add_all([child, bracelet])
            await sessao.flush()
            bracelet_id = bracelet.id

        event.listen(
            engine.sync_engine,
            "before_cursor_execute",
            registrar_consulta,
        )
        try:
            async with session_factory() as sessao:
                await marcar_bracelet_como_perdida(sessao, bracelet_id)
        finally:
            event.remove(
                engine.sync_engine,
                "before_cursor_execute",
                registrar_consulta,
            )

        assert len(consultas_com_lock) == 2
        assert "FROM children" in consultas_com_lock[0]
        assert "FROM bracelets" in consultas_com_lock[1]
    finally:
        await limpar_tabelas()
        await engine.dispose()


async def executar_perdas_concorrentes() -> None:
    tarefas: list[asyncio.Task[str]] = []
    leituras_sem_lock = 0
    duas_leituras_sem_lock = asyncio.Event()

    class SessaoComBarreira:
        def __init__(self, sessao: Any) -> None:
            self._sessao = sessao

        def begin(self) -> Any:
            return self._sessao.begin()

        async def execute(self, statement: Any) -> Any:
            return await self._sessao.execute(statement)

        async def scalar(self, statement: Any) -> Any:
            nonlocal leituras_sem_lock

            resultado = await self._sessao.scalar(statement)
            consulta = " ".join(str(statement).split())
            if (
                "FROM bracelets" in consulta
                and "FOR UPDATE" not in consulta
            ):
                leituras_sem_lock += 1
                if leituras_sem_lock == 2:
                    duas_leituras_sem_lock.set()
                await duas_leituras_sem_lock.wait()
            return resultado

        async def flush(self) -> None:
            await self._sessao.flush()

    try:
        await limpar_tabelas()
        async with session_factory.begin() as sessao:
            child = Child()
            bracelet = Bracelet(
                status=BraceletStatus.ATIVA,
                child=child,
                activated_at=ATIVACAO,
            )
            sessao.add_all([child, bracelet])
            await sessao.flush()
            bracelet_id = bracelet.id

        async def tentar_perda() -> str:
            async with session_factory() as sessao:
                try:
                    await marcar_bracelet_como_perdida(
                        SessaoComBarreira(sessao),
                        bracelet_id,
                    )
                except TransicaoBraceletInvalida:
                    return "invalida"
                return "perdida"

        tarefas = [
            asyncio.create_task(tentar_perda()),
            asyncio.create_task(tentar_perda()),
        ]
        resultados = await asyncio.gather(*tarefas)

        assert resultados.count("perdida") == 1
        assert resultados.count("invalida") == 1

        async with session_factory() as sessao:
            persistida = await sessao.get(Bracelet, bracelet_id)
        assert persistida is not None
        assert persistida.status is BraceletStatus.PERDIDA
        assert persistida.child_id is None
        assert persistida.activated_at == ATIVACAO
        assert persistida.revoked_at is not None
    finally:
        for tarefa in tarefas:
            if not tarefa.done():
                tarefa.cancel()
        if tarefas:
            await asyncio.gather(*tarefas, return_exceptions=True)
        await limpar_tabelas()
        await engine.dispose()


@requer_banco_de_teste
def test_bloqueia_child_antes_de_bracelet() -> None:
    asyncio.run(executar_prova_da_ordem_dos_locks())


@requer_banco_de_teste
def test_serializa_duas_perdas_da_mesma_bracelet() -> None:
    asyncio.run(executar_perdas_concorrentes())


async def aguardar_espera_por_lock(
    backend_pid: int,
    tarefa: asyncio.Task[Bracelet],
) -> bool:
    limite = monotonic() + 5
    while monotonic() < limite:
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


async def executar_mudanca_concorrente_de_vinculo() -> None:
    tarefa: asyncio.Task[Bracelet] | None = None
    try:
        await limpar_tabelas()
        async with session_factory.begin() as sessao:
            child_inicial = Child()
            child_nova = Child()
            bracelet = Bracelet(
                status=BraceletStatus.ATIVA,
                child=child_inicial,
                activated_at=ATIVACAO,
            )
            sessao.add_all([child_inicial, child_nova, bracelet])
            await sessao.flush()
            child_inicial_id = child_inicial.id
            child_nova_id = child_nova.id
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
                        .where(Child.id == child_inicial_id)
                        .with_for_update(),
                    )
                    tarefa = asyncio.create_task(
                        marcar_bracelet_como_perdida(
                            servico,
                            bracelet_id,
                        ),
                    )
                    assert await aguardar_espera_por_lock(
                        backend_pid,
                        tarefa,
                    )
                    async with session_factory.begin() as mutadora:
                        await mutadora.execute(
                            update(Bracelet)
                            .where(Bracelet.id == bracelet_id)
                            .values(child_id=child_nova_id),
                        )

                with pytest.raises(ConflitoPerdaBracelet) as erro:
                    await tarefa

        assert str(child_inicial_id) not in str(erro.value)
        assert str(child_nova_id) not in str(erro.value)
        assert str(bracelet_id) not in str(erro.value)
        async with session_factory() as sessao:
            persistida = await sessao.get(Bracelet, bracelet_id)
        assert persistida is not None
        assert persistida.status is BraceletStatus.ATIVA
        assert persistida.child_id == child_nova_id
        assert persistida.activated_at == ATIVACAO
        assert persistida.revoked_at is None
    finally:
        if tarefa is not None:
            if not tarefa.done():
                tarefa.cancel()
            await asyncio.gather(tarefa, return_exceptions=True)
        await limpar_tabelas()
        await engine.dispose()


@requer_banco_de_teste
def test_rejeita_mudanca_concorrente_do_vinculo() -> None:
    asyncio.run(executar_mudanca_concorrente_de_vinculo())
