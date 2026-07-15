# Transições de domínio de Bracelet - Plano de implementação

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implementar as transições de domínio de `Bracelet`, com validação de estado e tempo, atomicidade em memória e persistência compatível com as constraints existentes.

**Architecture:** Os métodos ficarão na entidade ORM `Bracelet` e alterarão somente o objeto em memória. Exceções tipadas representarão estado ou instante inválido; sessão, transação e tratamento de `IntegrityError` permanecerão fora da entidade.

**Tech Stack:** Python 3.12, SQLAlchemy 2 assíncrono, PostgreSQL 17, asyncpg, Alembic, pytest e Ruff.

## Restrições globais

- Aceitar somente `ESTOQUE → ATIVA`, `ATIVA → DESVINCULADA` e `ATIVA → PERDIDA`.
- Exigir `datetime` com `tzinfo` e `utcoffset()` diferentes de `None`.
- Rejeitar revogação anterior a `activated_at`; instante igual deve ser aceito.
- Executar todas as validações antes da primeira mutação.
- Validar primeiro o estado, depois argumentos obrigatórios e por último o tempo.
- `TransicaoBraceletInvalida` pode expor somente os estados de origem e destino.
- `InstanteBraceletInvalido` não pode expor UUID, token ou dados pessoais.
- Os métodos não podem acessar sessão, executar `flush`, `commit` ou capturar `IntegrityError`.
- Não criar migration, endpoint, schema Pydantic, serviço, repositório ou nova entidade.
- Testes de integração devem usar `TEST_DATABASE_URL` e ser ignorados quando ela não estiver definida.

---

### Tarefa 1: Transições válidas em memória

**Arquivos:**
- Criar: `tests/test_bracelet_transitions.py`
- Modificar: `app/models/bracelet.py`

**Interfaces:**
- Consome: `Bracelet`, `BraceletStatus` e `Child`.
- Produz: `Bracelet.ativar(child: Child, instante: datetime) -> None`, `Bracelet.desvincular(instante: datetime) -> None` e `Bracelet.marcar_como_perdida(instante: datetime) -> None`.

- [ ] **Passo 1: Escrever os testes das três transições válidas**

Criar `tests/test_bracelet_transitions.py`:

```python
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from app.models import Bracelet, BraceletStatus, Child

ATIVACAO = datetime(2026, 1, 15, 12, tzinfo=UTC)
REVOGACAO = ATIVACAO + timedelta(hours=1)


def criar_bracelet_ativa() -> tuple[Bracelet, Child]:
    child = Child(id=uuid4())
    bracelet = Bracelet(
        status=BraceletStatus.ATIVA,
        child=child,
        child_id=child.id,
        activated_at=ATIVACAO,
    )
    return bracelet, child


def test_ativar_vincula_child_e_registra_instante() -> None:
    child = Child(id=uuid4())
    bracelet = Bracelet(status=BraceletStatus.ESTOQUE)

    resultado = bracelet.ativar(child, ATIVACAO)

    assert resultado is None
    assert bracelet.status is BraceletStatus.ATIVA
    assert bracelet.child is child
    assert bracelet.activated_at == ATIVACAO
    assert bracelet.revoked_at is None


def test_desvincular_remove_vinculo_e_preserva_ativacao() -> None:
    bracelet, _ = criar_bracelet_ativa()

    resultado = bracelet.desvincular(REVOGACAO)

    assert resultado is None
    assert bracelet.status is BraceletStatus.DESVINCULADA
    assert bracelet.child is None
    assert bracelet.child_id is None
    assert bracelet.activated_at == ATIVACAO
    assert bracelet.revoked_at == REVOGACAO


def test_marcar_como_perdida_remove_vinculo_e_preserva_ativacao() -> None:
    bracelet, _ = criar_bracelet_ativa()

    resultado = bracelet.marcar_como_perdida(REVOGACAO)

    assert resultado is None
    assert bracelet.status is BraceletStatus.PERDIDA
    assert bracelet.child is None
    assert bracelet.child_id is None
    assert bracelet.activated_at == ATIVACAO
    assert bracelet.revoked_at == REVOGACAO
```

- [ ] **Passo 2: Executar os testes e confirmar RED**

```bash
poetry run python -m pytest tests/test_bracelet_transitions.py -v
```

Resultado esperado: `3 failed` com `AttributeError`, pois os métodos ainda não existem.

- [ ] **Passo 3: Implementar somente os caminhos válidos**

Adicionar ao final da classe `Bracelet` em `app/models/bracelet.py`:

```python
    def ativar(self, child: Child, instante: datetime) -> None:
        self.status = BraceletStatus.ATIVA
        self.child = child
        self.activated_at = instante
        self.revoked_at = None

    def desvincular(self, instante: datetime) -> None:
        self.status = BraceletStatus.DESVINCULADA
        self.child = None
        self.child_id = None
        self.revoked_at = instante

    def marcar_como_perdida(self, instante: datetime) -> None:
        self.status = BraceletStatus.PERDIDA
        self.child = None
        self.child_id = None
        self.revoked_at = instante
```

- [ ] **Passo 4: Executar os testes e confirmar GREEN**

```bash
poetry run python -m pytest tests/test_bracelet_transitions.py -v
```

Resultado esperado: `3 passed`.

- [ ] **Passo 5: Executar Ruff no recorte**

```bash
poetry run ruff check app/models/bracelet.py tests/test_bracelet_transitions.py
```

Resultado esperado: `All checks passed!`.

- [ ] **Passo 6: Criar commit do ciclo**

```bash
git add app/models/bracelet.py tests/test_bracelet_transitions.py
git commit -m "add valid Bracelet transitions"
```

---

### Tarefa 2: Estados e vínculo inválidos

**Arquivos:**
- Modificar: `tests/test_bracelet_transitions.py`
- Modificar: `app/models/bracelet.py`
- Modificar: `app/models/__init__.py`

**Interfaces:**
- Consome: os três métodos criados na Tarefa 1.
- Produz: `TransicaoBraceletInvalida(origem: BraceletStatus, destino: BraceletStatus)` e validação de `Child` antes de mutações.

- [ ] **Passo 1: Escrever os testes de estado, ordem e atomicidade**

Adicionar os imports abaixo em `tests/test_bracelet_transitions.py`:

```python
import pytest

from app.models import (
    Bracelet,
    BraceletStatus,
    Child,
    TransicaoBraceletInvalida,
)
```

Substituir o import existente de `app.models` por esse bloco e adicionar:

```python
def obter_estado(bracelet: Bracelet) -> tuple[object, ...]:
    return (
        bracelet.status,
        bracelet.child,
        bracelet.child_id,
        bracelet.activated_at,
        bracelet.revoked_at,
    )


@pytest.mark.parametrize(
    ("metodo", "origem", "destino"),
    [
        ("ativar", BraceletStatus.ATIVA, BraceletStatus.ATIVA),
        ("ativar", BraceletStatus.DESVINCULADA, BraceletStatus.ATIVA),
        ("ativar", BraceletStatus.PERDIDA, BraceletStatus.ATIVA),
        ("desvincular", BraceletStatus.ESTOQUE, BraceletStatus.DESVINCULADA),
        (
            "desvincular",
            BraceletStatus.DESVINCULADA,
            BraceletStatus.DESVINCULADA,
        ),
        ("desvincular", BraceletStatus.PERDIDA, BraceletStatus.DESVINCULADA),
        ("marcar_como_perdida", BraceletStatus.ESTOQUE, BraceletStatus.PERDIDA),
        (
            "marcar_como_perdida",
            BraceletStatus.DESVINCULADA,
            BraceletStatus.PERDIDA,
        ),
        ("marcar_como_perdida", BraceletStatus.PERDIDA, BraceletStatus.PERDIDA),
    ],
)
def test_rejeita_transicao_de_estado_nao_autorizada_sem_mutar(
    metodo: str,
    origem: BraceletStatus,
    destino: BraceletStatus,
) -> None:
    child = Child(id=uuid4())
    bracelet = Bracelet(
        public_token="token-que-nao-pode-aparecer-no-erro",
        status=origem,
        child=child,
        child_id=child.id,
        activated_at=ATIVACAO,
    )
    estado_anterior = obter_estado(bracelet)

    with pytest.raises(TransicaoBraceletInvalida) as erro:
        if metodo == "ativar":
            bracelet.ativar(None, datetime(2026, 1, 15, 12))  # type: ignore[arg-type]
        else:
            getattr(bracelet, metodo)(datetime(2026, 1, 15, 12))

    assert erro.value.origem is origem
    assert erro.value.destino is destino
    assert origem.value in str(erro.value)
    assert destino.value in str(erro.value)
    assert bracelet.public_token not in str(erro.value)
    assert str(child.id) not in str(erro.value)
    assert obter_estado(bracelet) == estado_anterior


@pytest.mark.parametrize("child_invalido", [None, object()])
def test_ativar_rejeita_child_invalido_sem_mutar(child_invalido: object) -> None:
    bracelet = Bracelet(status=BraceletStatus.ESTOQUE)
    estado_anterior = obter_estado(bracelet)

    with pytest.raises(TypeError, match="child deve ser uma instância de Child"):
        bracelet.ativar(child_invalido, ATIVACAO)  # type: ignore[arg-type]

    assert obter_estado(bracelet) == estado_anterior
```

- [ ] **Passo 2: Executar os novos testes e confirmar RED**

```bash
poetry run python -m pytest \
  tests/test_bracelet_transitions.py::test_rejeita_transicao_de_estado_nao_autorizada_sem_mutar \
  tests/test_bracelet_transitions.py::test_ativar_rejeita_child_invalido_sem_mutar \
  -v
```

Resultado esperado: erro de importação porque `TransicaoBraceletInvalida` ainda não existe.

- [ ] **Passo 3: Criar a exceção e validar antes de mutar**

Em `app/models/bracelet.py`, adicionar após `BraceletStatus`:

```python
class TransicaoBraceletInvalida(ValueError):
    def __init__(
        self,
        origem: BraceletStatus,
        destino: BraceletStatus,
    ) -> None:
        self.origem = origem
        self.destino = destino
        super().__init__(
            f"Transição de {origem.value} para {destino.value} não permitida",
        )
```

Adicionar à classe `Bracelet`:

```python
    def _validar_transicao(
        self,
        origem_esperada: BraceletStatus,
        destino: BraceletStatus,
    ) -> None:
        if self.status is not origem_esperada:
            raise TransicaoBraceletInvalida(self.status, destino)
```

Substituir os três métodos por:

```python
    def ativar(self, child: Child, instante: datetime) -> None:
        self._validar_transicao(
            BraceletStatus.ESTOQUE,
            BraceletStatus.ATIVA,
        )
        if not isinstance(child, Child):
            raise TypeError("child deve ser uma instância de Child")

        self.status = BraceletStatus.ATIVA
        self.child = child
        self.activated_at = instante
        self.revoked_at = None

    def desvincular(self, instante: datetime) -> None:
        self._validar_transicao(
            BraceletStatus.ATIVA,
            BraceletStatus.DESVINCULADA,
        )

        self.status = BraceletStatus.DESVINCULADA
        self.child = None
        self.child_id = None
        self.revoked_at = instante

    def marcar_como_perdida(self, instante: datetime) -> None:
        self._validar_transicao(
            BraceletStatus.ATIVA,
            BraceletStatus.PERDIDA,
        )

        self.status = BraceletStatus.PERDIDA
        self.child = None
        self.child_id = None
        self.revoked_at = instante
```

Substituir `app/models/__init__.py` por:

```python
from app.models.bracelet import (
    Bracelet,
    BraceletStatus,
    TransicaoBraceletInvalida,
)
from app.models.child import Child

__all__ = [
    "Bracelet",
    "BraceletStatus",
    "Child",
    "TransicaoBraceletInvalida",
]
```

- [ ] **Passo 4: Executar todos os testes unitários de transição**

```bash
poetry run python -m pytest tests/test_bracelet_transitions.py -v
```

Resultado esperado: `14 passed` — nove casos de estados inválidos e dois casos de `child` inválido contam separadamente.

- [ ] **Passo 5: Executar Ruff no recorte**

```bash
poetry run ruff check \
  app/models/bracelet.py \
  app/models/__init__.py \
  tests/test_bracelet_transitions.py
```

Resultado esperado: `All checks passed!`.

- [ ] **Passo 6: Criar commit do ciclo**

```bash
git add app/models tests/test_bracelet_transitions.py
git commit -m "validate Bracelet state transitions"
```

---

### Tarefa 3: Validação temporal

**Arquivos:**
- Modificar: `tests/test_bracelet_transitions.py`
- Modificar: `app/models/bracelet.py`
- Modificar: `app/models/__init__.py`

**Interfaces:**
- Consome: transições e validação de estado da Tarefa 2.
- Produz: `InstanteBraceletInvalido` e validação de fuso, presença e ordem temporal.

- [ ] **Passo 1: Escrever os testes temporais e de atomicidade**

Adicionar `InstanteBraceletInvalido` ao import de `app.models` e adicionar:

```python
def test_ativar_rejeita_instante_sem_fuso_sem_mutar() -> None:
    child = Child(id=uuid4())
    bracelet = Bracelet(status=BraceletStatus.ESTOQUE)
    estado_anterior = obter_estado(bracelet)

    with pytest.raises(
        InstanteBraceletInvalido,
        match="instante deve possuir fuso horário",
    ) as erro:
        bracelet.ativar(child, datetime(2026, 1, 15, 12))

    assert str(child.id) not in str(erro.value)
    assert obter_estado(bracelet) == estado_anterior


@pytest.mark.parametrize("metodo", ["desvincular", "marcar_como_perdida"])
def test_revogacao_rejeita_instante_sem_fuso_sem_mutar(metodo: str) -> None:
    bracelet, _ = criar_bracelet_ativa()
    estado_anterior = obter_estado(bracelet)

    with pytest.raises(
        InstanteBraceletInvalido,
        match="instante deve possuir fuso horário",
    ):
        getattr(bracelet, metodo)(datetime(2026, 1, 15, 13))

    assert obter_estado(bracelet) == estado_anterior


@pytest.mark.parametrize("metodo", ["desvincular", "marcar_como_perdida"])
def test_revogacao_rejeita_ausencia_de_ativacao_sem_mutar(metodo: str) -> None:
    child = Child(id=uuid4())
    bracelet = Bracelet(
        status=BraceletStatus.ATIVA,
        child=child,
        child_id=child.id,
        activated_at=None,
    )
    estado_anterior = obter_estado(bracelet)

    with pytest.raises(
        InstanteBraceletInvalido,
        match="pulseira ATIVA deve possuir activated_at",
    ):
        getattr(bracelet, metodo)(REVOGACAO)

    assert obter_estado(bracelet) == estado_anterior


@pytest.mark.parametrize("metodo", ["desvincular", "marcar_como_perdida"])
def test_revogacao_rejeita_instante_anterior_a_ativacao_sem_mutar(
    metodo: str,
) -> None:
    bracelet, _ = criar_bracelet_ativa()
    estado_anterior = obter_estado(bracelet)

    with pytest.raises(
        InstanteBraceletInvalido,
        match="revogação não pode ser anterior à ativação",
    ):
        getattr(bracelet, metodo)(ATIVACAO - timedelta(seconds=1))

    assert obter_estado(bracelet) == estado_anterior


@pytest.mark.parametrize(
    ("metodo", "status_esperado"),
    [
        ("desvincular", BraceletStatus.DESVINCULADA),
        ("marcar_como_perdida", BraceletStatus.PERDIDA),
    ],
)
def test_revogacao_aceita_instante_igual_a_ativacao(
    metodo: str,
    status_esperado: BraceletStatus,
) -> None:
    bracelet, _ = criar_bracelet_ativa()

    getattr(bracelet, metodo)(ATIVACAO)

    assert bracelet.status is status_esperado
    assert bracelet.revoked_at == ATIVACAO
```

- [ ] **Passo 2: Executar os testes temporais e confirmar RED**

```bash
poetry run python -m pytest \
  tests/test_bracelet_transitions.py::test_ativar_rejeita_instante_sem_fuso_sem_mutar \
  tests/test_bracelet_transitions.py::test_revogacao_rejeita_instante_sem_fuso_sem_mutar \
  tests/test_bracelet_transitions.py::test_revogacao_rejeita_ausencia_de_ativacao_sem_mutar \
  tests/test_bracelet_transitions.py::test_revogacao_rejeita_instante_anterior_a_ativacao_sem_mutar \
  -v
```

Resultado esperado: erro de importação porque `InstanteBraceletInvalido` ainda não existe.

- [ ] **Passo 3: Implementar as validações temporais**

Em `app/models/bracelet.py`, adicionar após `TransicaoBraceletInvalida`:

```python
class InstanteBraceletInvalido(ValueError):
    pass


def _validar_instante_com_fuso(instante: datetime) -> None:
    if instante.tzinfo is None or instante.utcoffset() is None:
        raise InstanteBraceletInvalido(
            "O instante deve possuir fuso horário",
        )


def _validar_instante_de_revogacao(
    activated_at: datetime | None,
    instante: datetime,
) -> None:
    _validar_instante_com_fuso(instante)
    if activated_at is None:
        raise InstanteBraceletInvalido(
            "Uma pulseira ATIVA deve possuir activated_at",
        )
    if instante < activated_at:
        raise InstanteBraceletInvalido(
            "A revogação não pode ser anterior à ativação",
        )
```

Em `ativar`, adicionar depois da validação de `child` e antes das atribuições:

```python
        _validar_instante_com_fuso(instante)
```

Em `desvincular` e `marcar_como_perdida`, adicionar depois da validação de estado e antes das atribuições:

```python
        _validar_instante_de_revogacao(self.activated_at, instante)
```

Substituir `app/models/__init__.py` por:

```python
from app.models.bracelet import (
    Bracelet,
    BraceletStatus,
    InstanteBraceletInvalido,
    TransicaoBraceletInvalida,
)
from app.models.child import Child

__all__ = [
    "Bracelet",
    "BraceletStatus",
    "Child",
    "InstanteBraceletInvalido",
    "TransicaoBraceletInvalida",
]
```

- [ ] **Passo 4: Executar todos os testes de transição e confirmar GREEN**

```bash
poetry run python -m pytest tests/test_bracelet_transitions.py -v
```

Resultado esperado: `23 passed`.

- [ ] **Passo 5: Executar Ruff no recorte**

```bash
poetry run ruff check \
  app/models/bracelet.py \
  app/models/__init__.py \
  tests/test_bracelet_transitions.py
```

Resultado esperado: `All checks passed!`.

- [ ] **Passo 6: Criar commit do ciclo**

```bash
git add app/models tests/test_bracelet_transitions.py
git commit -m "validate Bracelet transition timestamps"
```

---

### Tarefa 4: Persistência das transições no PostgreSQL

**Arquivos:**
- Modificar: `tests/test_bracelet_database.py`

**Interfaces:**
- Consome: os três métodos finais de `Bracelet`, `session_factory` e schema `0003`.
- Produz: cobertura de integração para `flush` de `ATIVA`, `DESVINCULADA` e `PERDIDA`.

- [ ] **Passo 1: Escrever o teste de persistência real**

Em `tests/test_bracelet_database.py`, substituir o import de `datetime` por:

```python
from datetime import UTC, datetime, timedelta
```

Adicionar depois dos marcadores de banco:

```python
ATIVACAO = datetime(2026, 1, 15, 12, tzinfo=UTC)
REVOGACAO = ATIVACAO + timedelta(hours=1)
```

Adicionar o helper:

```python
async def persistir_transicao(
    status_final: BraceletStatus,
) -> tuple[BraceletStatus, UUID | None, datetime, datetime | None, UUID]:
    try:
        async with session_factory() as sessao:
            child = Child()
            bracelet = Bracelet()
            sessao.add_all([child, bracelet])
            await sessao.flush()

            bracelet.ativar(child, ATIVACAO)
            await sessao.flush()

            if status_final is BraceletStatus.DESVINCULADA:
                bracelet.desvincular(REVOGACAO)
                await sessao.flush()
            elif status_final is BraceletStatus.PERDIDA:
                bracelet.marcar_como_perdida(REVOGACAO)
                await sessao.flush()

            resultado = (
                bracelet.status,
                bracelet.child_id,
                bracelet.activated_at,
                bracelet.revoked_at,
                child.id,
            )
            await sessao.rollback()
            return resultado
    finally:
        await engine.dispose()
```

Adicionar o teste:

```python
@requer_banco_de_teste
@pytest.mark.parametrize(
    "status_final",
    [
        BraceletStatus.ATIVA,
        BraceletStatus.DESVINCULADA,
        BraceletStatus.PERDIDA,
    ],
)
def test_metodos_de_transicao_produzem_estado_persistivel(
    status_final: BraceletStatus,
) -> None:
    status, child_id, activated_at, revoked_at, id_child = asyncio.run(
        persistir_transicao(status_final),
    )

    assert status is status_final
    assert activated_at == ATIVACAO
    if status_final is BraceletStatus.ATIVA:
        assert child_id == id_child
        assert revoked_at is None
    else:
        assert child_id is None
        assert revoked_at == REVOGACAO
```

- [ ] **Passo 2: Executar o teste contra PostgreSQL**

```bash
set -a
source .env
set +a
TEST_DATABASE_URL="$DATABASE_URL" poetry run python -m pytest \
  tests/test_bracelet_database.py::test_metodos_de_transicao_produzem_estado_persistivel \
  -v
```

Resultado esperado: `3 passed`, um para cada estado resultante.

- [ ] **Passo 3: Executar todos os testes de Bracelet**

```bash
set -a
source .env
set +a
TEST_DATABASE_URL="$DATABASE_URL" poetry run python -m pytest \
  tests/test_bracelet_model.py \
  tests/test_bracelet_transitions.py \
  tests/test_bracelet_database.py \
  -v
```

Resultado esperado: todos os testes de `Bracelet` passam sem skips.

- [ ] **Passo 4: Executar Ruff no teste de integração**

```bash
poetry run ruff check tests/test_bracelet_database.py
```

Resultado esperado: `All checks passed!`.

- [ ] **Passo 5: Criar commit do ciclo**

```bash
git add tests/test_bracelet_database.py
git commit -m "test persisted Bracelet transitions"
```

---

### Tarefa 5: Documentação e verificação final

**Arquivos:**
- Modificar: `docs/PROJECT_CONTEXT.md`
- Modificar: `docs/superpowers/plans/2026-07-15-bracelet-transitions.md`

**Interfaces:**
- Consome: comportamento implementado e verificado nas tarefas anteriores.
- Produz: estado atual documentado sem antecipar serviços ou endpoints.

- [ ] **Passo 1: Atualizar somente o estado implementado**

Em `docs/PROJECT_CONTEXT.md`, após o item dos testes de integração de `Bracelet`, adicionar:

```markdown
- Transições de domínio `ESTOQUE → ATIVA`, `ATIVA → DESVINCULADA` e
  `ATIVA → PERDIDA` implementadas na entidade `Bracelet`, com validação de
  estado, fuso horário, ordem temporal e atomicidade em memória.
- Exceções tipadas de transição e instante inválido não expõem identificadores
  nem dados pessoais.
```

Substituir `## Próximo recorte` por:

```markdown
## Próximo recorte

As transições de domínio de `Bracelet` estão concluídas. A camada de aplicação
que controlará sessão, transação e tratamento de concorrência ainda não foi
implementada. Qualquer serviço, endpoint, schema ou nova entidade exige novo
recorte técnico aprovado.
```

- [ ] **Passo 2: Marcar o plano como executado**

Substituir mecanicamente todos os checkboxes `- [ ]` deste arquivo por `- [x]`.

- [ ] **Passo 3: Executar a suíte completa com PostgreSQL**

```bash
set -a
source .env
set +a
TEST_DATABASE_URL="$DATABASE_URL" poetry run python -m pytest -v
```

Resultado esperado: todos os testes passam, sem skips de integração e sem warnings inesperados.

- [ ] **Passo 4: Executar Ruff global**

```bash
poetry run ruff check .
```

Resultado esperado: `All checks passed!`.

- [ ] **Passo 5: Confirmar ausência de mudança no schema**

```bash
set -a
source .env
set +a
poetry run alembic check
poetry run alembic current
```

Resultado esperado: `No new upgrade operations detected.` e `0003 (head)`.

- [ ] **Passo 6: Revisar escopo e estado Git**

```bash
git diff --check
git status --short
git diff --stat HEAD
```

Resultado esperado: somente modelo, exportações, testes, contexto e plano das transições; nenhuma migration ou camada HTTP nova.

- [ ] **Passo 7: Criar commit documental**

```bash
git add \
  docs/PROJECT_CONTEXT.md \
  docs/superpowers/plans/2026-07-15-bracelet-transitions.md
git commit -m "document Bracelet state transitions"
```

- [ ] **Passo 8: Apresentar o resultado e parar**

Informar os arquivos alterados, quantidade de testes, resultado do Ruff,
resultado de `alembic check`, revisão atual e confirmação de que nenhuma
migration, endpoint, serviço, schema ou nova entidade foi criada. Parar e
aguardar aprovação explícita antes do próximo recorte.
