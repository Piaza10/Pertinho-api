# Bracelet Loss Service Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implementar o caso de uso transacional que marca uma `Bracelet`
ativa como `PERDIDA`, com revalidação sob lock e tratamento de concorrência.

**Architecture:** Um serviço assíncrono recebe uma `AsyncSession` limpa e o
UUID da pulseira. Ele faz uma pré-leitura somente de colunas, bloqueia
`Child → Bracelet`, relê e revalida a entidade, chama o domínio e executa
`flush` dentro da própria transação.

**Tech Stack:** Python >= 3.12, SQLAlchemy assíncrono, asyncpg, PostgreSQL 17,
pytest, pytest-asyncio, Poetry, Alembic e Ruff.

## Global Constraints

- Seguir TDD: teste primeiro, RED confirmado, implementação mínima e GREEN.
- Interface final:
  `marcar_bracelet_como_perdida(sessao: AsyncSession, bracelet_id: UUID) -> Bracelet`.
- A sessão chega sem transação ativa; o serviço controla a transação e
  não fecha a sessão do chamador.
- O instante de revogação é gerado internamente em UTC.
- A ordem de locks do caminho ativo é sempre `Child → Bracelet`.
- Mensagens de aplicação não contêm UUID, token ou dado pessoal.
- Não alterar modelos, migrations, banco, FastAPI, schemas, autenticação ou
  o serviço de ativação.
- Não criar desvinculação, troca planejada, eventos, Redis ou Celery.
- Testes usam PostgreSQL real por `TEST_DATABASE_URL`.

---

## Mapa de arquivos

- Criar `app/services/bracelet_loss.py`: caso de uso e exceções de aplicação.
- Criar `tests/test_bracelet_loss_service.py`: integração PostgreSQL,
  rollback, locks e concorrência.
- Modificar `docs/PROJECT_CONTEXT.md`: registrar somente o estado comprovado.
- Modificar este plano: marcar passos executados.

### Task 1: Perda válida, recurso ausente e estados inválidos

**Files:**
- Create: `app/services/bracelet_loss.py`
- Create: `tests/test_bracelet_loss_service.py`

**Interfaces:**
- Consumes: `Bracelet.marcar_como_perdida(instante: datetime) -> None`.
- Produces: `marcar_bracelet_como_perdida(...)` e
  `RecursoPerdaNaoEncontrado`.

- [x] **Step 1: Criar testes PostgreSQL que falham sem o serviço**

Criar `tests/test_bracelet_loss_service.py`:

```python
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
from app.services.bracelet_loss import (
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
```

- [x] **Step 2: Executar e confirmar RED**

```bash
set -a
source .env
set +a
TEST_DATABASE_URL="$DATABASE_URL" poetry run python -m pytest \
  tests/test_bracelet_loss_service.py -v
```

Resultado esperado: falha na coleta com `ModuleNotFoundError` para
`app.services.bracelet_loss`.

- [x] **Step 3: Implementar pré-leitura e transação mínimas**

Criar `app/services/bracelet_loss.py`:

```python
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Bracelet


class RecursoPerdaNaoEncontrado(LookupError):
    def __init__(self) -> None:
        super().__init__("Recurso de perda não encontrado")


async def marcar_bracelet_como_perdida(
    sessao: AsyncSession,
    bracelet_id: UUID,
) -> Bracelet:
    async with sessao.begin():
        pre_leitura = (
            await sessao.execute(
                select(Bracelet.status, Bracelet.child_id).where(
                    Bracelet.id == bracelet_id,
                ),
            )
        ).one_or_none()
        if pre_leitura is None:
            raise RecursoPerdaNaoEncontrado

        bracelet = await sessao.scalar(
            select(Bracelet).where(Bracelet.id == bracelet_id),
        )
        if bracelet is None:
            raise RecursoPerdaNaoEncontrado

        bracelet.marcar_como_perdida(datetime.now(UTC))
        await sessao.flush()

    return bracelet
```

- [x] **Step 4: Executar GREEN focado e Ruff**

```bash
set -a
source .env
set +a
TEST_DATABASE_URL="$DATABASE_URL" poetry run python -m pytest \
  tests/test_bracelet_loss_service.py -v
poetry run ruff check \
  app/services/bracelet_loss.py tests/test_bracelet_loss_service.py
```

Resultado esperado: `5 passed` e `All checks passed!`.

- [x] **Step 5: Criar commit**

```bash
git add app/services/bracelet_loss.py tests/test_bracelet_loss_service.py
git commit -m "add transactional Bracelet loss service"
```

### Task 2: Locks e perdas simultâneas

**Files:**
- Modify: `app/services/bracelet_loss.py`
- Modify: `tests/test_bracelet_loss_service.py`

**Interfaces:**
- Consumes: serviço e erro da Task 1.
- Produces: locks `Child → Bracelet` e serialização da mesma pulseira.

- [x] **Step 1: Adicionar teste da ordem SQL e concorrência**

Em `tests/test_bracelet_loss_service.py`, substituir o import SQLAlchemy por:

```python
from sqlalchemy import delete, event
```

Adicionar ao final:

```python
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

        inicio = asyncio.Event()

        async def tentar_perda() -> str:
            await inicio.wait()
            async with session_factory() as sessao:
                try:
                    await marcar_bracelet_como_perdida(
                        sessao,
                        bracelet_id,
                    )
                except TransicaoBraceletInvalida:
                    return "invalida"
                return "perdida"

        tarefas = [
            asyncio.create_task(tentar_perda()),
            asyncio.create_task(tentar_perda()),
        ]
        await asyncio.sleep(0)
        inicio.set()
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
```

- [x] **Step 2: Executar novos testes e confirmar RED**

```bash
set -a
source .env
set +a
TEST_DATABASE_URL="$DATABASE_URL" poetry run python -m pytest \
  tests/test_bracelet_loss_service.py::test_bloqueia_child_antes_de_bracelet \
  tests/test_bracelet_loss_service.py::test_serializa_duas_perdas_da_mesma_bracelet \
  -v
```

Resultado esperado: falhas por ausência dos dois `FOR UPDATE` e por duas
transações poderem concluir sem serialização.

- [x] **Step 3: Implementar locks na ordem aprovada**

Substituir `app/services/bracelet_loss.py` por:

```python
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Bracelet, Child


class RecursoPerdaNaoEncontrado(LookupError):
    def __init__(self) -> None:
        super().__init__("Recurso de perda não encontrado")


async def marcar_bracelet_como_perdida(
    sessao: AsyncSession,
    bracelet_id: UUID,
) -> Bracelet:
    async with sessao.begin():
        pre_leitura = (
            await sessao.execute(
                select(Bracelet.status, Bracelet.child_id).where(
                    Bracelet.id == bracelet_id,
                ),
            )
        ).one_or_none()
        if pre_leitura is None:
            raise RecursoPerdaNaoEncontrado

        _, child_id_inicial = pre_leitura
        if child_id_inicial is not None:
            child = await sessao.scalar(
                select(Child)
                .where(Child.id == child_id_inicial)
                .with_for_update(),
            )
            if child is None:
                raise RecursoPerdaNaoEncontrado

        bracelet = await sessao.scalar(
            select(Bracelet)
            .where(Bracelet.id == bracelet_id)
            .with_for_update(),
        )
        if bracelet is None:
            raise RecursoPerdaNaoEncontrado

        bracelet.marcar_como_perdida(datetime.now(UTC))
        await sessao.flush()

    return bracelet
```

- [x] **Step 4: Executar GREEN, repetições e Ruff**

```bash
set -a
source .env
set +a
for tentativa in 1 2 3 4 5; do
  TEST_DATABASE_URL="$DATABASE_URL" poetry run python -m pytest \
    tests/test_bracelet_loss_service.py::test_serializa_duas_perdas_da_mesma_bracelet \
    -q || exit 1
done
TEST_DATABASE_URL="$DATABASE_URL" poetry run python -m pytest \
  tests/test_bracelet_loss_service.py -v
poetry run ruff check \
  app/services/bracelet_loss.py tests/test_bracelet_loss_service.py
```

Resultado esperado: cinco repetições com `1 passed`, arquivo com `7 passed`
e Ruff limpo.

- [x] **Step 5: Criar commit**

```bash
git add app/services/bracelet_loss.py tests/test_bracelet_loss_service.py
git commit -m "serialize concurrent Bracelet losses"
```

### Task 3: Conflito por mudança concorrente do vínculo

**Files:**
- Modify: `app/services/bracelet_loss.py`
- Modify: `tests/test_bracelet_loss_service.py`

**Interfaces:**
- Consumes: pré-leitura e locks da Task 2.
- Produces: `ConflitoPerdaBracelet` e revalidação de `child_id`.

- [x] **Step 1: Adicionar teste concorrente determinístico**

Em `tests/test_bracelet_loss_service.py`, adicionar imports:

```python
from time import monotonic

from sqlalchemy import delete, event, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession
```

Adicionar `ConflitoPerdaBracelet` ao import do serviço e adicionar ao final:

```python
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
```

- [x] **Step 2: Executar e confirmar RED**

```bash
set -a
source .env
set +a
TEST_DATABASE_URL="$DATABASE_URL" poetry run python -m pytest \
  tests/test_bracelet_loss_service.py::test_rejeita_mudanca_concorrente_do_vinculo \
  -v
```

Resultado esperado: falha na coleta porque `ConflitoPerdaBracelet` ainda não
existe.

- [x] **Step 3: Implementar exceção e revalidação**

Em `app/services/bracelet_loss.py`, importar `BraceletStatus`, adicionar:

```python
class ConflitoPerdaBracelet(ValueError):
    def __init__(self) -> None:
        super().__init__("Vínculo da pulseira mudou durante a operação")
```

Depois de confirmar que `bracelet` existe e antes do método de domínio,
adicionar:

```python
        if (
            bracelet.status is BraceletStatus.ATIVA
            and bracelet.child_id != child_id_inicial
        ):
            raise ConflitoPerdaBracelet
```

- [x] **Step 4: Executar GREEN, arquivo focado e Ruff**

```bash
set -a
source .env
set +a
TEST_DATABASE_URL="$DATABASE_URL" poetry run python -m pytest \
  tests/test_bracelet_loss_service.py -v
poetry run ruff check \
  app/services/bracelet_loss.py tests/test_bracelet_loss_service.py
```

Resultado esperado: `8 passed` e Ruff limpo.

- [x] **Step 5: Criar commit**

```bash
git add app/services/bracelet_loss.py tests/test_bracelet_loss_service.py
git commit -m "reject concurrent Bracelet link changes"
```

### Task 4: Documentação e verificação final

**Files:**
- Modify: `docs/PROJECT_CONTEXT.md`
- Modify: `docs/superpowers/plans/2026-07-23-bracelet-loss-service.md`

**Interfaces:**
- Consumes: comportamento verificado nas Tasks 1 a 3.
- Produces: estado atual documentado sem antecipar troca ou HTTP.

- [x] **Step 1: Atualizar o estado implementado**

Depois dos itens do serviço de ativação em `docs/PROJECT_CONTEXT.md`, adicionar:

```markdown
- Serviço de aplicação para marcar `Bracelet` como perdida implementado com
  pré-leitura de colunas, revalidação sob locks `Child → Bracelet`, instante UTC
  interno e rollback automático.
- Perdas simultâneas e mudança concorrente de vínculo são tratadas com estado
  final consistente e exceções sem identificadores ou dados pessoais.
```

Substituir `## Próximo recorte` por:

```markdown
## Próximo recorte

Os serviços transacionais de ativação e perda de `Bracelet` estão concluídos.
A troca planejada, assim como endpoints, schemas e autorização, ainda não foi
implementada e exige novo recorte técnico aprovado.
```

- [x] **Step 2: Marcar somente os checkboxes de passos como concluídos**

Marcar os 23 checkboxes deste plano como concluídos, preservando exemplos e
texto histórico.

- [x] **Step 3: Executar suíte completa PostgreSQL**

```bash
set -a
source .env
set +a
TEST_DATABASE_URL="$DATABASE_URL" poetry run python -m pytest -v
```

Resultado esperado: `78 passed`, sem skips ou warnings inesperados.

- [x] **Step 4: Executar Ruff global**

```bash
poetry run ruff check .
```

Resultado esperado: `All checks passed!`.

- [x] **Step 5: Confirmar ausência de mudança no schema**

```bash
set -a
source .env
set +a
poetry run alembic check
poetry run alembic current
```

Resultado esperado: `No new upgrade operations detected.` e `0003 (head)`.

- [x] **Step 6: Revisar escopo e Git**

```bash
git diff --check
git status --short
git diff --name-only aac5bcb..HEAD
```

Resultado esperado: serviço, teste, contexto e plano; nenhuma migration,
entidade, endpoint, schema ou alteração no serviço de ativação.

- [x] **Step 7: Criar commit documental**

```bash
git add \
  docs/PROJECT_CONTEXT.md \
  docs/superpowers/plans/2026-07-23-bracelet-loss-service.md
git commit -m "document Bracelet loss service"
```

- [x] **Step 8: Apresentar e parar**

Informar arquivos, testes, Ruff, Alembic, revisão e limites de escopo. Parar e
aguardar aprovação explícita para a troca planejada ou qualquer outro recorte.
