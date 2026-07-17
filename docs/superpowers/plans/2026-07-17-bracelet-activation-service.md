# Bracelet Activation Service Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implementar a ativação transacional e concorrente de uma `Bracelet`
em `ESTOQUE` para uma `Child`, sem criar camada HTTP ou alterar o schema.

**Architecture:** Um serviço assíncrono recebe uma `AsyncSession` limpa e os
UUIDs internos, controla uma transação, carrega `Child` e `Bracelet`, aplica a
regra de domínio e executa `flush`. Bloqueios pessimistas no PostgreSQL
serializam ativações para a mesma criança, enquanto exceções neutras preservam
privacidade e distinguem conflitos esperados de falhas técnicas.

**Tech Stack:** Python >= 3.12, SQLAlchemy assíncrono, asyncpg, PostgreSQL 17,
pytest, pytest-asyncio, Poetry, Alembic e Ruff.

## Global Constraints

- Seguir TDD: escrever o teste, confirmar a falha, implementar o mínimo e
  confirmar o sucesso.
- O serviço recebe uma `AsyncSession` sem transação ativa, controla
  `begin/commit/rollback` e não fecha a sessão do chamador.
- O instante de ativação é gerado pelo serviço em UTC e nunca recebido como
  argumento.
- Mensagens de erro não podem conter UUIDs, tokens públicos ou dados pessoais.
- Não criar endpoints, schemas Pydantic, migrations, entidades, autenticação,
  eventos, Redis, Celery ou serviços para outras transições.
- Não alterar `app/models/bracelet.py`, `app/models/child.py`, `app/main.py`,
  `app/database.py` ou qualquer arquivo em `alembic/`.
- Testes de integração usam `TEST_DATABASE_URL` e o PostgreSQL local em
  `127.0.0.1:5433`.

---

## Mapa de arquivos

- Criar `app/services/bracelet_activation.py`: exceções de aplicação e caso
  de uso transacional de ativação.
- Criar `tests/test_bracelet_activation_service.py`: testes PostgreSQL de
  sucesso, erros, rollback, privacidade e concorrência.
- Modificar `docs/PROJECT_CONTEXT.md`: registrar apenas o comportamento depois
  que estiver implementado e verificado.
- Modificar este plano: marcar os passos executados.

### Task 1: Ativação transacional e recurso ausente

**Files:**
- Create: `app/services/bracelet_activation.py`
- Create: `tests/test_bracelet_activation_service.py`

**Interfaces:**
- Consumes: `AsyncSession`, `Child`, `Bracelet` e
  `Bracelet.ativar(child: Child, instante: datetime) -> None`.
- Produces:
  `async def ativar_bracelet(sessao: AsyncSession, bracelet_id: UUID, child_id: UUID) -> Bracelet`
  e `RecursoAtivacaoNaoEncontrado`.

- [ ] **Step 1: Criar os testes de ativação válida e recurso ausente**

Criar `tests/test_bracelet_activation_service.py`:

```python
import asyncio
import os
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

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
```

- [ ] **Step 2: Executar os testes e confirmar RED**

```bash
set -a
source .env
set +a
TEST_DATABASE_URL="$DATABASE_URL" poetry run python -m pytest \
  tests/test_bracelet_activation_service.py -v
```

Resultado esperado: falha na coleta com `ModuleNotFoundError` para
`app.services`, pois o serviço ainda não existe.

- [ ] **Step 3: Implementar o serviço transacional mínimo**

Criar `app/services/bracelet_activation.py`:

```python
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Bracelet, Child


class RecursoAtivacaoNaoEncontrado(LookupError):
    def __init__(self) -> None:
        super().__init__("Recurso de ativação não encontrado")


async def ativar_bracelet(
    sessao: AsyncSession,
    bracelet_id: UUID,
    child_id: UUID,
) -> Bracelet:
    async with sessao.begin():
        child = await sessao.scalar(
            select(Child).where(Child.id == child_id),
        )
        bracelet = await sessao.scalar(
            select(Bracelet).where(Bracelet.id == bracelet_id),
        )

        if child is None or bracelet is None:
            raise RecursoAtivacaoNaoEncontrado

        bracelet.ativar(child, datetime.now(UTC))
        await sessao.flush()

    return bracelet
```

- [ ] **Step 4: Executar testes focados e confirmar GREEN**

```bash
set -a
source .env
set +a
TEST_DATABASE_URL="$DATABASE_URL" poetry run python -m pytest \
  tests/test_bracelet_activation_service.py -v
poetry run ruff check \
  app/services/bracelet_activation.py \
  tests/test_bracelet_activation_service.py
```

Resultado esperado: `3 passed` e `All checks passed!`.

- [ ] **Step 5: Criar commit da ativação básica**

```bash
git add \
  app/services/bracelet_activation.py \
  tests/test_bracelet_activation_service.py
git commit -m "add transactional Bracelet activation service"
```

### Task 2: Conflito, transição inválida e rollback

**Files:**
- Modify: `app/services/bracelet_activation.py`
- Modify: `tests/test_bracelet_activation_service.py`

**Interfaces:**
- Consumes: `ativar_bracelet(...)`, `RecursoAtivacaoNaoEncontrado` e
  `TransicaoBraceletInvalida`.
- Produces: `ConflitoAtivacaoBracelet` e verificação de vínculo existente
  antes da mutação de domínio.

- [ ] **Step 1: Importar os erros e adicionar testes de conflito e rollback**

Em `tests/test_bracelet_activation_service.py`, substituir os imports de
modelo e serviço por:

```python
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
```

Adicionar ao final do arquivo:

```python
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
```

- [ ] **Step 2: Executar os novos testes e confirmar RED**

```bash
set -a
source .env
set +a
TEST_DATABASE_URL="$DATABASE_URL" poetry run python -m pytest \
  tests/test_bracelet_activation_service.py::test_rejeita_child_ja_vinculada_sem_mutacao_parcial \
  tests/test_bracelet_activation_service.py::test_preserva_erro_de_dominio_e_faz_rollback \
  -v
```

Resultado esperado: falha na coleta porque
`ConflitoAtivacaoBracelet` ainda não existe.

- [ ] **Step 3: Adicionar o conflito e a consulta preventiva**

Substituir `app/services/bracelet_activation.py` por:

```python
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Bracelet, Child


class RecursoAtivacaoNaoEncontrado(LookupError):
    def __init__(self) -> None:
        super().__init__("Recurso de ativação não encontrado")


class ConflitoAtivacaoBracelet(ValueError):
    def __init__(self) -> None:
        super().__init__("Criança já possui pulseira vinculada")


async def ativar_bracelet(
    sessao: AsyncSession,
    bracelet_id: UUID,
    child_id: UUID,
) -> Bracelet:
    async with sessao.begin():
        child = await sessao.scalar(
            select(Child).where(Child.id == child_id),
        )
        bracelet = await sessao.scalar(
            select(Bracelet).where(Bracelet.id == bracelet_id),
        )

        if child is None or bracelet is None:
            raise RecursoAtivacaoNaoEncontrado

        outra_bracelet_id = await sessao.scalar(
            select(Bracelet.id).where(
                Bracelet.child_id == child_id,
                Bracelet.id != bracelet_id,
            ),
        )
        if outra_bracelet_id is not None:
            raise ConflitoAtivacaoBracelet

        bracelet.ativar(child, datetime.now(UTC))
        await sessao.flush()

    return bracelet
```

- [ ] **Step 4: Executar o arquivo focado e Ruff**

```bash
set -a
source .env
set +a
TEST_DATABASE_URL="$DATABASE_URL" poetry run python -m pytest \
  tests/test_bracelet_activation_service.py -v
poetry run ruff check \
  app/services/bracelet_activation.py \
  tests/test_bracelet_activation_service.py
```

Resultado esperado: `5 passed` e `All checks passed!`.

- [ ] **Step 5: Criar commit dos erros transacionais**

```bash
git add \
  app/services/bracelet_activation.py \
  tests/test_bracelet_activation_service.py
git commit -m "validate Bracelet activation service errors"
```

### Task 3: Serialização de ativações concorrentes

**Files:**
- Modify: `app/services/bracelet_activation.py`
- Modify: `tests/test_bracelet_activation_service.py`

**Interfaces:**
- Consumes: `ativar_bracelet(...)`, `ConflitoAtivacaoBracelet` e as constraints
  existentes de `Bracelet.child_id`.
- Produces: bloqueio pessimista de `Child` seguido por `Bracelet`, ambos com
  `SELECT ... FOR UPDATE`.

- [ ] **Step 1: Adicionar provas reais de bloqueio e concorrência**

No topo de `tests/test_bracelet_activation_service.py`, substituir o import
do SQLAlchemy por:

```python
from sqlalchemy import delete, event, select, text
from sqlalchemy.ext.asyncio import AsyncSession
```

Adicionar ao final de `tests/test_bracelet_activation_service.py`:

```python
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
        if tarefa is not None and not tarefa.done():
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
```

- [ ] **Step 2: Executar a prova de bloqueio e confirmar RED determinístico**

```bash
set -a
source .env
set +a
TEST_DATABASE_URL="$DATABASE_URL" poetry run python -m pytest \
  tests/test_bracelet_activation_service.py::test_ativacao_aguarda_bloqueio_pessimista_da_child \
  tests/test_bracelet_activation_service.py::test_bloqueia_child_antes_de_bracelet \
  -v
```

Resultado esperado: `2 failed`. Sem `FOR UPDATE` na consulta de `Child`, a
tarefa termina antes de aparecer como espera por lock no PostgreSQL. A captura
do SQL real também comprova que as consultas ainda não contêm `FOR UPDATE` na
ordem `Child` seguida por `Bracelet`. O teste concorrente permanece como
aceitação funcional, mas não é usado isoladamente como evidência RED porque
seu escalonamento não determina a janela entre consulta e `flush`.

- [ ] **Step 3: Adicionar os bloqueios na ordem aprovada**

Em `app/services/bracelet_activation.py`, substituir somente as duas consultas
iniciais por:

```python
        child = await sessao.scalar(
            select(Child)
            .where(Child.id == child_id)
            .with_for_update(),
        )
        bracelet = await sessao.scalar(
            select(Bracelet)
            .where(Bracelet.id == bracelet_id)
            .with_for_update(),
        )
```

Manter a consulta de vínculo existente depois desses dois bloqueios e antes de
`bracelet.ativar(...)`.

- [ ] **Step 4: Repetir concorrência e executar todos os testes do serviço**

```bash
set -a
source .env
set +a
for tentativa in 1 2 3 4 5; do
  TEST_DATABASE_URL="$DATABASE_URL" poetry run python -m pytest \
    tests/test_bracelet_activation_service.py::test_serializa_duas_ativacoes_para_a_mesma_child \
    -q || exit 1
done
TEST_DATABASE_URL="$DATABASE_URL" poetry run python -m pytest \
  tests/test_bracelet_activation_service.py -v
poetry run ruff check \
  app/services/bracelet_activation.py \
  tests/test_bracelet_activation_service.py
```

Resultado esperado: cinco repetições com `1 passed`, arquivo focado com
`8 passed` e Ruff com `All checks passed!`.

- [ ] **Step 5: Criar commit da concorrência**

```bash
git add \
  app/services/bracelet_activation.py \
  tests/test_bracelet_activation_service.py
git commit -m "serialize concurrent Bracelet activations"
```

### Task 4: Documentação e verificação final

**Files:**
- Modify: `docs/PROJECT_CONTEXT.md`
- Modify: `docs/superpowers/plans/2026-07-17-bracelet-activation-service.md`

**Interfaces:**
- Consumes: comportamento implementado e verificado nas Tasks 1 a 3.
- Produces: estado atual documentado sem declarar endpoint, autorização ou
  outras transições como implementadas.

- [ ] **Step 1: Atualizar somente o estado implementado**

Em `docs/PROJECT_CONTEXT.md`, depois das transições de domínio implementadas,
adicionar:

```markdown
- Serviço de aplicação para ativação de `Bracelet` implementado com controle
  transacional, instante UTC interno, bloqueio pessimista e rollback
  automático.
- Ativações concorrentes para a mesma criança são serializadas no PostgreSQL;
  recursos ausentes e conflitos usam exceções neutras sem identificadores ou
  dados pessoais.
```

Substituir `## Próximo recorte` por:

```markdown
## Próximo recorte

O serviço transacional de ativação de `Bracelet` está concluído. Os casos de
uso de desvinculação e perda, assim como endpoints, schemas e autorização,
ainda não foram implementados e exigem novo recorte técnico aprovado.
```

- [ ] **Step 2: Marcar o plano como executado sem alterar sua instrução histórica**

Marcar como concluídos todos os checkboxes de passos deste plano. Preservar
esta frase em linguagem natural, sem substituir exemplos literais dentro de
texto ou blocos de código.

- [ ] **Step 3: Executar a suíte completa com PostgreSQL**

```bash
set -a
source .env
set +a
TEST_DATABASE_URL="$DATABASE_URL" poetry run python -m pytest -v
```

Resultado esperado: `70 passed`, sem skips e sem warnings inesperados.

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
poetry run alembic check
poetry run alembic current
```

Resultado esperado: `No new upgrade operations detected.` e `0003 (head)`.

- [ ] **Step 6: Revisar escopo e estado Git**

```bash
git diff --check
git status --short
git diff --stat 804ea79..HEAD
git diff --name-only 804ea79..HEAD
```

Resultado esperado: somente o serviço, seus testes, o contexto e este plano;
nenhuma migration, camada HTTP, schema ou modelo alterado.

- [ ] **Step 7: Criar commit documental**

```bash
git add \
  docs/PROJECT_CONTEXT.md \
  docs/superpowers/plans/2026-07-17-bracelet-activation-service.md
git commit -m "document Bracelet activation service"
```

- [ ] **Step 8: Apresentar o resultado e parar**

Informar arquivos alterados, testes, Ruff, Alembic, revisão independente e
confirmação de que nenhuma migration, endpoint, schema, entidade ou serviço de
outra transição foi criado. Parar e aguardar aprovação explícita para o próximo
recorte.
