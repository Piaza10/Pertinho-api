# Bracelet Replacement Service Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implementar a troca atômica de uma `Bracelet` ativa por uma nova
`Bracelet` em estoque para a mesma `Child`.

**Architecture:** Um serviço assíncrono recebe uma `AsyncSession` limpa e os
UUIDs das duas pulseiras. Ele deriva a criança da pulseira anterior, controla
uma única transação, bloqueia `Child → Bracelets em ordem de UUID`, revalida o
vínculo e usa dois `flushes` para respeitar a unicidade de `child_id`.

**Tech Stack:** Python >= 3.12, SQLAlchemy assíncrono, asyncpg, PostgreSQL 17,
pytest, pytest-asyncio, Poetry, Alembic e Ruff.

## Global Constraints

- Seguir TDD: teste primeiro, RED confirmado, implementação mínima e GREEN.
- Interface final:
  `trocar_bracelet(sessao: AsyncSession, bracelet_anterior_id: UUID, bracelet_nova_id: UUID) -> tuple[Bracelet, Bracelet]`.
- O retorno mantém a ordem `(bracelet_anterior, bracelet_nova)`.
- A sessão chega sem transação ativa; o serviço controla a transação e não
  fecha a sessão.
- Os UUIDs devem ser diferentes e a validação ocorre antes da transação.
- A `Child` é derivada exclusivamente da pulseira anterior.
- Um único instante UTC é usado para desvinculação e ativação.
- O caminho válido bloqueia `Child → Bracelet menor UUID → Bracelet maior UUID`.
- A desvinculação e a ativação usam dois `flushes` dentro da mesma transação.
- Mensagens não contêm UUID, token público ou dado pessoal.
- Testes e Alembic usam exclusivamente o banco isolado `pertinho_test`.
- Não alterar modelos, migrations, FastAPI, schemas, autenticação, os serviços
  de ativação/perda ou qualquer endpoint.
- Não criar eventos, notificações, Redis, Celery ou dados adicionais de menores.

---

## Mapa de arquivos

- Criar `app/services/bracelet_replacement.py`: serviço e exceções de aplicação.
- Criar `tests/test_bracelet_replacement_service.py`: integração PostgreSQL,
  rollback, locks e concorrência.
- Modificar `docs/PROJECT_CONTEXT.md`: registrar somente o estado comprovado.
- Modificar este plano: marcar os passos concluídos.

### Task 1: Troca válida, recursos e estados inválidos

**Files:**
- Create: `app/services/bracelet_replacement.py`
- Create: `tests/test_bracelet_replacement_service.py`

**Interfaces:**
- Consumes: `Bracelet.desvincular(instante: datetime) -> None` e
  `Bracelet.ativar(child: Child, instante: datetime) -> None`.
- Produces:
  `trocar_bracelet(...)`, `RecursoTrocaNaoEncontrado` e
  `BraceletsTrocaIguais`.

- [ ] **Step 1: Criar os testes funcionais PostgreSQL**

Criar `tests/test_bracelet_replacement_service.py`:

```python
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
```

- [ ] **Step 2: Executar e confirmar RED**

```bash
set -a
source .env
set +a
DATABASE_URL_TESTE="${DATABASE_URL%/*}/pertinho_test"
TEST_DATABASE_URL="$DATABASE_URL_TESTE" poetry run python -m pytest \
  tests/test_bracelet_replacement_service.py -v
```

Resultado esperado: erro de coleta porque
`app.services.bracelet_replacement` ainda não existe. Depois de criar somente
um módulo vazio, a coleta deve falhar pelos símbolos ausentes, nunca por
conexão com `pertinho`.

- [ ] **Step 3: Implementar o serviço transacional sem locks**

Criar `app/services/bracelet_replacement.py`:

```python
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Bracelet, Child


class RecursoTrocaNaoEncontrado(LookupError):
    def __init__(self) -> None:
        super().__init__("Recurso de troca não encontrado")


class BraceletsTrocaIguais(ValueError):
    def __init__(self) -> None:
        super().__init__("As pulseiras da troca devem ser distintas")


async def trocar_bracelet(
    sessao: AsyncSession,
    bracelet_anterior_id: UUID,
    bracelet_nova_id: UUID,
) -> tuple[Bracelet, Bracelet]:
    if bracelet_anterior_id == bracelet_nova_id:
        raise BraceletsTrocaIguais

    async with sessao.begin():
        pre_leitura = (
            await sessao.execute(
                select(Bracelet.status, Bracelet.child_id).where(
                    Bracelet.id == bracelet_anterior_id,
                ),
            )
        ).one_or_none()
        if pre_leitura is None:
            raise RecursoTrocaNaoEncontrado

        _, child_id_inicial = pre_leitura
        child = None
        if child_id_inicial is not None:
            child = await sessao.scalar(
                select(Child).where(Child.id == child_id_inicial),
            )

        pulseiras: dict[UUID, Bracelet] = {}
        for bracelet_id in sorted(
            (bracelet_anterior_id, bracelet_nova_id),
        ):
            bracelet = await sessao.scalar(
                select(Bracelet).where(Bracelet.id == bracelet_id),
            )
            if bracelet is not None:
                pulseiras[bracelet_id] = bracelet

        if (
            len(pulseiras) != 2
            or (child_id_inicial is not None and child is None)
        ):
            raise RecursoTrocaNaoEncontrado

        anterior = pulseiras[bracelet_anterior_id]
        nova = pulseiras[bracelet_nova_id]
        instante = datetime.now(UTC)

        anterior.desvincular(instante)
        if child is None:
            raise RecursoTrocaNaoEncontrado
        await sessao.flush()

        nova.ativar(child, instante)
        await sessao.flush()

    return anterior, nova
```

- [ ] **Step 4: Executar GREEN focado e Ruff**

```bash
set -a
source .env
set +a
DATABASE_URL_TESTE="${DATABASE_URL%/*}/pertinho_test"
TEST_DATABASE_URL="$DATABASE_URL_TESTE" poetry run python -m pytest \
  tests/test_bracelet_replacement_service.py -v
poetry run ruff check \
  app/services/bracelet_replacement.py \
  tests/test_bracelet_replacement_service.py
```

Resultado esperado: `10 passed` e `All checks passed!`.

- [ ] **Step 5: Criar commit**

```bash
git add \
  app/services/bracelet_replacement.py \
  tests/test_bracelet_replacement_service.py
git commit -m "add transactional Bracelet replacement service"
```

### Task 2: Ordem de locks e trocas simultâneas

**Files:**
- Modify: `app/services/bracelet_replacement.py`
- Modify: `tests/test_bracelet_replacement_service.py`

**Interfaces:**
- Consumes:
  `trocar_bracelet(sessao, bracelet_anterior_id, bracelet_nova_id)`.
- Produces: locks determinísticos
  `Child → Bracelet menor → Bracelet maior`.

- [ ] **Step 1: Adicionar testes de locks e corrida determinística**

Alterar os imports de `tests/test_bracelet_replacement_service.py`:

```python
from typing import Any

from sqlalchemy import delete, event, select
from sqlalchemy.ext.asyncio import AsyncSession
```

Adicionar antes dos testes públicos:

```python
async def executar_prova_da_ordem_dos_locks() -> None:
    locks: list[tuple[str, object]] = []

    def registrar_lock(
        _conexao: object,
        _cursor: object,
        statement: str,
        parametros: object,
        _contexto: object,
        _executemany: bool,
    ) -> None:
        normalizada = " ".join(statement.split())
        if "FOR UPDATE" not in normalizada:
            return
        if isinstance(parametros, tuple) and parametros:
            primeiro_parametro: object = parametros[0]
        else:
            primeiro_parametro = parametros
        locks.append((normalizada, primeiro_parametro))

    anterior_id = UUID(int=2)
    nova_id = UUID(int=1)
    try:
        await limpar_tabelas()
        async with session_factory.begin() as sessao:
            child = Child()
            anterior = Bracelet(
                id=anterior_id,
                status=BraceletStatus.ATIVA,
                child=child,
                activated_at=ATIVACAO_ANTERIOR,
            )
            nova = Bracelet(id=nova_id)
            sessao.add_all([child, anterior, nova])

        event.listen(
            engine.sync_engine,
            "before_cursor_execute",
            registrar_lock,
        )
        try:
            async with session_factory() as sessao:
                await trocar_bracelet(sessao, anterior_id, nova_id)
        finally:
            event.remove(
                engine.sync_engine,
                "before_cursor_execute",
                registrar_lock,
            )

        assert len(locks) == 3
        assert "FROM children" in locks[0][0]
        assert "FROM bracelets" in locks[1][0]
        assert UUID(str(locks[1][1])) == nova_id
        assert "FROM bracelets" in locks[2][0]
        assert UUID(str(locks[2][1])) == anterior_id
    finally:
        await limpar_tabelas()
        await engine.dispose()


async def executar_trocas_concorrentes() -> None:
    tarefas: list[asyncio.Task[str]] = []
    duas_leituras_da_anterior = asyncio.Event()
    leituras_da_anterior = 0
    anterior_id = UUID(int=1)
    novas_ids = (UUID(int=2), UUID(int=3))

    class SessaoComBarreira:
        def __init__(self, sessao: AsyncSession) -> None:
            self._sessao = sessao

        def begin(self) -> Any:
            return self._sessao.begin()

        async def execute(self, statement: Any) -> Any:
            return await self._sessao.execute(statement)

        async def scalar(self, statement: Any) -> Any:
            nonlocal leituras_da_anterior
            resultado = await self._sessao.scalar(statement)
            sql = str(statement)
            if (
                "FROM bracelets" in sql
                and "FOR UPDATE" not in sql
                and leituras_da_anterior < 2
            ):
                leituras_da_anterior += 1
                if leituras_da_anterior == 2:
                    duas_leituras_da_anterior.set()
                async with asyncio.timeout(5):
                    await duas_leituras_da_anterior.wait()
            return resultado

        async def flush(self) -> None:
            await self._sessao.flush()

    try:
        await limpar_tabelas()
        async with session_factory.begin() as sessao:
            child = Child()
            anterior = Bracelet(
                id=anterior_id,
                status=BraceletStatus.ATIVA,
                child=child,
                activated_at=ATIVACAO_ANTERIOR,
            )
            novas = [Bracelet(id=bracelet_id) for bracelet_id in novas_ids]
            sessao.add_all([child, anterior, *novas])

        inicio = asyncio.Event()

        async def tentar_troca(nova_id: UUID) -> str:
            await inicio.wait()
            async with session_factory() as sessao:
                try:
                    await trocar_bracelet(
                        SessaoComBarreira(sessao),
                        anterior_id,
                        nova_id,
                    )
                except TransicaoBraceletInvalida:
                    return "rejeitada"
                return "trocada"

        tarefas = [
            asyncio.create_task(tentar_troca(nova_id))
            for nova_id in novas_ids
        ]
        inicio.set()
        async with asyncio.timeout(5):
            resultados = await asyncio.gather(*tarefas)

        assert resultados.count("trocada") == 1
        assert resultados.count("rejeitada") == 1

        async with session_factory() as sessao:
            anterior_persistida = await sessao.get(Bracelet, anterior_id)
            novas_persistidas = [
                await sessao.get(Bracelet, nova_id)
                for nova_id in novas_ids
            ]

        assert anterior_persistida is not None
        assert anterior_persistida.status is BraceletStatus.DESVINCULADA
        assert sum(
            bracelet is not None
            and bracelet.status is BraceletStatus.ATIVA
            for bracelet in novas_persistidas
        ) == 1
        assert sum(
            bracelet is not None
            and bracelet.status is BraceletStatus.ESTOQUE
            for bracelet in novas_persistidas
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
def test_bloqueia_child_e_bracelets_em_ordem_global() -> None:
    asyncio.run(executar_prova_da_ordem_dos_locks())


@requer_banco_de_teste
def test_serializa_duas_trocas_da_mesma_bracelet() -> None:
    asyncio.run(executar_trocas_concorrentes())
```

- [ ] **Step 2: Executar e confirmar RED**

```bash
set -a
source .env
set +a
DATABASE_URL_TESTE="${DATABASE_URL%/*}/pertinho_test"
TEST_DATABASE_URL="$DATABASE_URL_TESTE" poetry run python -m pytest \
  tests/test_bracelet_replacement_service.py::test_bloqueia_child_e_bracelets_em_ordem_global \
  tests/test_bracelet_replacement_service.py::test_serializa_duas_trocas_da_mesma_bracelet \
  -v
```

Resultado esperado:

- a prova SQL falha porque não há três consultas com `FOR UPDATE`;
- a corrida determinística falha porque as duas transações leem a pulseira
  anterior como `ATIVA` e a implementação ainda não as serializa.

Se o teste concorrente não produzir RED pelo motivo descrito, não implementar
locks ainda: corrigir a barreira até a falha ser determinística.

- [ ] **Step 3: Implementar locks na ordem global**

Substituir `app/services/bracelet_replacement.py` por:

```python
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Bracelet, Child


class RecursoTrocaNaoEncontrado(LookupError):
    def __init__(self) -> None:
        super().__init__("Recurso de troca não encontrado")


class BraceletsTrocaIguais(ValueError):
    def __init__(self) -> None:
        super().__init__("As pulseiras da troca devem ser distintas")


async def trocar_bracelet(
    sessao: AsyncSession,
    bracelet_anterior_id: UUID,
    bracelet_nova_id: UUID,
) -> tuple[Bracelet, Bracelet]:
    if bracelet_anterior_id == bracelet_nova_id:
        raise BraceletsTrocaIguais

    async with sessao.begin():
        pre_leitura = (
            await sessao.execute(
                select(Bracelet.status, Bracelet.child_id).where(
                    Bracelet.id == bracelet_anterior_id,
                ),
            )
        ).one_or_none()
        if pre_leitura is None:
            raise RecursoTrocaNaoEncontrado

        _, child_id_inicial = pre_leitura
        child = None
        if child_id_inicial is not None:
            child = await sessao.scalar(
                select(Child)
                .where(Child.id == child_id_inicial)
                .with_for_update(),
            )

        pulseiras: dict[UUID, Bracelet] = {}
        for bracelet_id in sorted(
            (bracelet_anterior_id, bracelet_nova_id),
        ):
            bracelet = await sessao.scalar(
                select(Bracelet)
                .where(Bracelet.id == bracelet_id)
                .with_for_update(),
            )
            if bracelet is not None:
                pulseiras[bracelet_id] = bracelet

        if (
            len(pulseiras) != 2
            or (child_id_inicial is not None and child is None)
        ):
            raise RecursoTrocaNaoEncontrado

        anterior = pulseiras[bracelet_anterior_id]
        nova = pulseiras[bracelet_nova_id]

        instante = datetime.now(UTC)
        anterior.desvincular(instante)
        if child is None:
            raise RecursoTrocaNaoEncontrado
        await sessao.flush()

        nova.ativar(child, instante)
        await sessao.flush()

    return anterior, nova
```

- [ ] **Step 4: Executar GREEN, repetições e Ruff**

```bash
set -a
source .env
set +a
DATABASE_URL_TESTE="${DATABASE_URL%/*}/pertinho_test"
TEST_DATABASE_URL="$DATABASE_URL_TESTE" poetry run python -m pytest \
  tests/test_bracelet_replacement_service.py::test_bloqueia_child_e_bracelets_em_ordem_global \
  tests/test_bracelet_replacement_service.py::test_serializa_duas_trocas_da_mesma_bracelet \
  -v
for tentativa in 1 2 3 4 5; do
  TEST_DATABASE_URL="$DATABASE_URL_TESTE" poetry run python -m pytest \
    tests/test_bracelet_replacement_service.py::test_serializa_duas_trocas_da_mesma_bracelet \
    -q || exit 1
done
TEST_DATABASE_URL="$DATABASE_URL_TESTE" poetry run python -m pytest \
  tests/test_bracelet_replacement_service.py -v
poetry run ruff check \
  app/services/bracelet_replacement.py \
  tests/test_bracelet_replacement_service.py
```

Resultado esperado: `2 passed`, cinco repetições verdes, `12 passed` no
arquivo e `All checks passed!`.

- [ ] **Step 5: Criar commit**

```bash
git add \
  app/services/bracelet_replacement.py \
  tests/test_bracelet_replacement_service.py
git commit -m "serialize concurrent Bracelet replacements"
```

### Task 3: Mudança concorrente do vínculo

**Files:**
- Modify: `app/services/bracelet_replacement.py`
- Modify: `tests/test_bracelet_replacement_service.py`

**Interfaces:**
- Consumes: ordem de locks da Task 2.
- Produces: `ConflitoTrocaBracelet`, revalidação do vínculo e prova
  PostgreSQL do rollback integral.

- [ ] **Step 1: Adicionar teste controlado de mudança de vínculo**

Alterar os imports SQLAlchemy do teste:

```python
from time import monotonic

from sqlalchemy import delete, event, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession
```

Adicionar `ConflitoTrocaBracelet` ao import do serviço:

```python
from app.services.bracelet_replacement import (
    BraceletsTrocaIguais,
    ConflitoTrocaBracelet,
    RecursoTrocaNaoEncontrado,
    trocar_bracelet,
)
```

Adicionar antes dos testes públicos:

```python
async def aguardar_espera_por_lock(
    backend_pid: int,
    tarefa: asyncio.Task[tuple[Bracelet, Bracelet]],
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
    tarefa: asyncio.Task[tuple[Bracelet, Bracelet]] | None = None
    try:
        await limpar_tabelas()
        async with session_factory.begin() as sessao:
            child_inicial = Child()
            child_nova = Child()
            anterior = Bracelet(
                status=BraceletStatus.ATIVA,
                child=child_inicial,
                activated_at=ATIVACAO_ANTERIOR,
            )
            nova = Bracelet()
            sessao.add_all([child_inicial, child_nova, anterior, nova])
            await sessao.flush()
            child_inicial_id = child_inicial.id
            child_nova_id = child_nova.id
            anterior_id = anterior.id
            nova_id = nova.id
            anterior_token = anterior.public_token
            nova_token = nova.public_token

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
                        trocar_bracelet(
                            servico,
                            anterior_id,
                            nova_id,
                        ),
                    )
                    async with asyncio.timeout(5):
                        assert await aguardar_espera_por_lock(
                            backend_pid,
                            tarefa,
                        )
                    async with session_factory.begin() as mutadora:
                        await mutadora.execute(
                            update(Bracelet)
                            .where(Bracelet.id == anterior_id)
                            .values(child_id=child_nova_id),
                        )

                with pytest.raises(ConflitoTrocaBracelet) as erro:
                    async with asyncio.timeout(5):
                        await tarefa

        mensagem = str(erro.value)
        assert mensagem == (
            "Vínculo da pulseira anterior mudou durante a operação"
        )
        assert str(child_inicial_id) not in mensagem
        assert str(child_nova_id) not in mensagem
        assert str(anterior_id) not in mensagem
        assert str(nova_id) not in mensagem
        assert anterior_token not in mensagem
        assert nova_token not in mensagem

        async with session_factory() as sessao:
            anterior_persistida = await sessao.get(Bracelet, anterior_id)
            nova_persistida = await sessao.get(Bracelet, nova_id)
        assert anterior_persistida is not None
        assert anterior_persistida.status is BraceletStatus.ATIVA
        assert anterior_persistida.child_id == child_nova_id
        assert anterior_persistida.activated_at == ATIVACAO_ANTERIOR
        assert anterior_persistida.revoked_at is None
        assert nova_persistida is not None
        assert nova_persistida.status is BraceletStatus.ESTOQUE
        assert nova_persistida.child_id is None
        assert nova_persistida.activated_at is None
        assert nova_persistida.revoked_at is None
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
```

- [ ] **Step 2: Executar e confirmar RED**

```bash
set -a
source .env
set +a
DATABASE_URL_TESTE="${DATABASE_URL%/*}/pertinho_test"
TEST_DATABASE_URL="$DATABASE_URL_TESTE" poetry run python -m pytest \
  tests/test_bracelet_replacement_service.py::test_rejeita_mudanca_concorrente_do_vinculo \
  -v
```

Resultado esperado: erro de coleta porque `ConflitoTrocaBracelet` ainda não
existe no serviço.

- [ ] **Step 3: Implementar exceção e revalidação mínimas**

Adicionar antes de `trocar_bracelet` em
`app/services/bracelet_replacement.py`:

```python
class ConflitoTrocaBracelet(ValueError):
    def __init__(self) -> None:
        super().__init__(
            "Vínculo da pulseira anterior mudou durante a operação",
        )
```

Adicionar depois da obtenção de `anterior` e `nova`, antes do instante e de
qualquer transição:

```python
if anterior.child_id != child_id_inicial:
    raise ConflitoTrocaBracelet
```

Não adicionar nova exceção, retry, log ou abstração.

- [ ] **Step 4: Executar GREEN, arquivo completo, suíte e Ruff**

```bash
set -a
source .env
set +a
DATABASE_URL_TESTE="${DATABASE_URL%/*}/pertinho_test"
TEST_DATABASE_URL="$DATABASE_URL_TESTE" poetry run python -m pytest \
  tests/test_bracelet_replacement_service.py::test_rejeita_mudanca_concorrente_do_vinculo \
  -v
TEST_DATABASE_URL="$DATABASE_URL_TESTE" poetry run python -m pytest \
  tests/test_bracelet_replacement_service.py -v
TEST_DATABASE_URL="$DATABASE_URL_TESTE" poetry run python -m pytest -q
poetry run ruff check .
```

Resultado esperado: `1 passed`, `13 passed`, `91 passed` e
`All checks passed!`.

- [ ] **Step 5: Criar commit**

```bash
git add \
  app/services/bracelet_replacement.py \
  tests/test_bracelet_replacement_service.py
git commit -m "verify concurrent Bracelet replacement link changes"
```

### Task 4: Documentação e verificação final

**Files:**
- Modify: `docs/PROJECT_CONTEXT.md`
- Modify: `docs/superpowers/plans/2026-07-23-bracelet-replacement-service.md`

**Interfaces:**
- Consumes: comportamento aprovado nas Tasks 1 a 3.
- Produces: estado atual documentado sem antecipar HTTP ou autorização.

- [ ] **Step 1: Atualizar o estado implementado**

Depois dos itens do serviço de perda em `docs/PROJECT_CONTEXT.md`, adicionar:

```markdown
- Serviço transacional de troca planejada de `Bracelet` implementado com
  instante UTC único, locks `Child → Bracelets por UUID`, dois `flushes` e
  rollback integral.
- Trocas simultâneas e mudanças concorrentes de vínculo são serializadas ou
  rejeitadas com estado final consistente e mensagens neutras.
```

Substituir `## Próximo recorte` por:

```markdown
## Próximo recorte

Os serviços transacionais internos de ativação, perda e troca planejada de
`Bracelet` estão concluídos. Endpoints, schemas e autorização ainda não foram
implementados e exigem novo recorte técnico aprovado.
```

- [ ] **Step 2: Marcar somente os checkboxes dos passos**

Marcar os 23 checkboxes deste plano como concluídos. Preservar exemplos,
resultados RED históricos e todo o restante do texto.

- [ ] **Step 3: Executar a suíte completa no banco isolado**

```bash
set -a
source .env
set +a
DATABASE_URL_TESTE="${DATABASE_URL%/*}/pertinho_test"
TEST_DATABASE_URL="$DATABASE_URL_TESTE" poetry run python -m pytest -v
```

Resultado esperado: `91 passed`, sem skips ou warnings inesperados.

- [ ] **Step 4: Executar Ruff global**

```bash
poetry run ruff check .
```

Resultado esperado: `All checks passed!`.

- [ ] **Step 5: Confirmar ausência de mudança no schema**

```bash
set -a
source .env
set +a
DATABASE_URL_TESTE="${DATABASE_URL%/*}/pertinho_test"
DATABASE_URL="$DATABASE_URL_TESTE" poetry run alembic check
DATABASE_URL="$DATABASE_URL_TESTE" poetry run alembic current
```

Resultado esperado: `No new upgrade operations detected.` e `0003 (head)`.

- [ ] **Step 6: Revisar escopo e Git**

```bash
git diff --check
git status --short
git diff --name-only 89c02b3..HEAD
```

Resultado esperado: serviço, teste, contexto e plano. Nenhum modelo,
migration, endpoint, schema ou serviço existente deve aparecer.

- [ ] **Step 7: Criar commit documental**

```bash
git add \
  docs/PROJECT_CONTEXT.md \
  docs/superpowers/plans/2026-07-23-bracelet-replacement-service.md
git commit -m "document Bracelet replacement service"
```

- [ ] **Step 8: Apresentar e parar**

Informar arquivos, commits, RED/GREEN, testes, Ruff, Alembic, revisão e limites
de escopo. Parar e aguardar aprovação explícita para qualquer endpoint,
schema ou autorização.
