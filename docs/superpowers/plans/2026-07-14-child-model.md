# Modelo físico inicial de Child - Plano de implementação

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Criar `Child` e a tabela `children` exclusivamente com uma chave primária UUID gerada pela aplicação.

**Architecture:** `Child` herdará da `Base` compartilhada e ficará isolado em `app/models/child.py`. O pacote `app.models` exportará o modelo, e o Alembic carregará sua metadata para aplicar a revisão `0002`.

**Tech Stack:** Python 3.12, SQLAlchemy 2 assíncrono, PostgreSQL 17, asyncpg, Alembic, pytest e Ruff.

## Restrições globais

- `children` deve conter somente `id` UUID, chave primária e não nula.
- O UUID deve ser gerado na aplicação por `uuid.uuid4`, sem `server_default`.
- Não adicionar timestamps ou qualquer dado pessoal, identificável ou sensível.
- Não criar relacionamentos, schemas Pydantic, repositórios, serviços ou endpoints.
- Não criar outras entidades ou tabelas de negócio.
- Testes de integração devem usar `TEST_DATABASE_URL` e ser ignorados quando ela não estiver definida.

---

### Tarefa 1: Mapeamento mínimo de Child

**Arquivos:**
- Criar: `tests/test_child_model.py`
- Modificar: `tests/test_database.py`
- Criar: `app/models/__init__.py`
- Criar: `app/models/child.py`

**Interfaces:**
- Consome: `app.database.Base`.
- Produz: `app.models.Child`, mapeado para `children`, com `id: Mapped[UUID]`.

- [x] **Passo 1: Escrever os testes que falham**

Criar `tests/test_child_model.py`:

```python
from sqlalchemy import Uuid, inspect


def test_child_mapeia_somente_id_uuid() -> None:
    from app.models import Child

    colunas = inspect(Child).columns

    assert Child.__tablename__ == "children"
    assert list(colunas.keys()) == ["id"]
    assert isinstance(colunas.id.type, Uuid)
    assert colunas.id.primary_key
    assert not colunas.id.nullable
    assert colunas.id.default is not None
    assert colunas.id.default.is_callable
    assert colunas.id.server_default is None
```

Substituir o teste final de `tests/test_database.py` por:

```python
def test_base_declarativa_registra_somente_children() -> None:
    from sqlalchemy.orm import DeclarativeBase

    from app.database import Base
    from app.models import Child

    assert issubclass(Base, DeclarativeBase)
    assert Base.metadata.tables == {"children": Child.__table__}
```

- [x] **Passo 2: Executar os testes e confirmar a falha**

```bash
poetry run python -m pytest \
  tests/test_child_model.py \
  tests/test_database.py::test_base_declarativa_registra_somente_children -v
```

Resultado esperado: falha com `ModuleNotFoundError: No module named 'app.models'`.

- [x] **Passo 3: Implementar o modelo mínimo**

Criar `app/models/child.py`:

```python
from uuid import UUID, uuid4

from sqlalchemy import Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class Child(Base):
    __tablename__ = "children"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
```

Criar `app/models/__init__.py`:

```python
from app.models.child import Child

__all__ = ["Child"]
```

- [x] **Passo 4: Executar os testes e confirmar sucesso**

```bash
poetry run python -m pytest \
  tests/test_child_model.py \
  tests/test_database.py::test_base_declarativa_registra_somente_children -v
```

Resultado esperado: `2 passed`.

- [x] **Passo 5: Criar commit do ciclo**

```bash
git add app/models tests/test_child_model.py tests/test_database.py
git commit -m "add minimal Child model"
```

---

### Tarefa 2: Migration 0002 e schema real

**Arquivos:**
- Modificar: `tests/test_migrations.py`
- Modificar: `alembic/env.py`
- Criar: `alembic/versions/0002_cria_children.py`

**Interfaces:**
- Consome: `app.models.Child` e revisão Alembic `0001`.
- Produz: revisão `0002`, que cria e remove exclusivamente a tabela `children`.

- [x] **Passo 1: Alterar o teste de migration para exigir 0002**

Substituir `tests/test_migrations.py` por:

```python
import asyncio
import os
from collections.abc import Iterator
from uuid import UUID

import pytest
from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from sqlalchemy import inspect

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


async def obter_revisao_colunas_e_pk() -> tuple[
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


async def children_existe() -> bool:
    try:
        async with engine.connect() as conexao:
            return await conexao.run_sync(
                lambda conexao_sincrona: inspect(conexao_sincrona).has_table(
                    "children",
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
def test_alembic_aplica_0002_com_somente_id() -> None:
    revisao_atual, colunas, chave_primaria = asyncio.run(
        obter_revisao_colunas_e_pk(),
    )

    assert revisao_atual == "0002"
    assert [coluna["name"] for coluna in colunas] == ["id"]
    assert chave_primaria["constrained_columns"] == ["id"]
    assert not colunas[0]["nullable"]
    assert colunas[0]["default"] is None


@requer_banco_de_teste
def test_child_gera_uuid_ao_inserir() -> None:
    child_id = asyncio.run(inserir_child_sem_id())

    assert isinstance(child_id, UUID)


@requer_banco_de_teste
def test_downgrade_0002_remove_children(
    configuracao_alembic: Config,
) -> None:
    command.downgrade(configuracao_alembic, "0001")

    try:
        tabela_existe = asyncio.run(children_existe())
    finally:
        command.upgrade(configuracao_alembic, "head")
        tabela_restaurada = asyncio.run(children_existe())

    assert not tabela_existe
    assert tabela_restaurada
```

- [x] **Passo 2: Executar o teste e confirmar a falha**

```bash
set -a
source .env
set +a
TEST_DATABASE_URL="$DATABASE_URL" poetry run python -m pytest \
  tests/test_migrations.py -v
```

Resultado esperado: falha porque a revisão atual ainda é `0001` e `children` não existe.

- [x] **Passo 3: Registrar Child no ambiente Alembic**

Em `alembic/env.py`, substituir:

```python
from app.database import Base
```

por:

```python
from app.models import Child
```

Substituir:

```python
target_metadata = Base.metadata
```

por:

```python
target_metadata = Child.metadata
```

- [x] **Passo 4: Criar a migration 0002**

Criar `alembic/versions/0002_cria_children.py`:

```python
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | Sequence[str] | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "children",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("children")
```

- [x] **Passo 5: Executar os testes e confirmar sucesso**

```bash
set -a
source .env
set +a
TEST_DATABASE_URL="$DATABASE_URL" poetry run python -m pytest \
  tests/test_migrations.py -v
```

Resultado esperado: `3 passed`; a fixture restaura o banco em `0002 (head)`.

- [x] **Passo 6: Validar o estado operacional**

```bash
poetry run alembic upgrade head
poetry run alembic current
```

Resultado esperado: `0002 (head)`.

- [x] **Passo 7: Criar commit do ciclo**

```bash
git add alembic/env.py alembic/versions/0002_cria_children.py tests/test_migrations.py
git commit -m "add children migration"
```

---

### Tarefa 3: Documentação, verificação e publicação

**Arquivos:**
- Modificar: `docs/PROJECT_CONTEXT.md`
- Modificar: `docs/superpowers/plans/2026-07-14-child-model.md`

**Interfaces:**
- Consome: modelo e migration validados nas tarefas anteriores.
- Produz: contexto mestre fiel ao estado implementado.

- [x] **Passo 1: Atualizar o contexto mestre**

Adicionar a `Estado atual implementado` em `docs/PROJECT_CONTEXT.md`:

```markdown
- Modelo físico `Child` criado somente com `id: UUID`, sem dados pessoais ou
  timestamps.
- Migration `0002` cria exclusivamente a tabela `children` e suporta downgrade
  para `0001`.
```

Atualizar `Próximo recorte` para deixar qualquer nova entidade ou campo
dependente de novo desenho e aprovação.

- [x] **Passo 2: Marcar o plano como executado**

Substituir todos os marcadores `- [ ]` deste arquivo por `- [x]` depois que os
respectivos passos forem comprovados.

- [x] **Passo 3: Executar a verificação final completa**

```bash
set -a
source .env
set +a
TEST_DATABASE_URL="$DATABASE_URL" poetry run python -m pytest -v
poetry run ruff check .
poetry run alembic current
```

Resultado esperado: toda a suíte passa, Ruff sem ocorrências e `0002 (head)`.

- [x] **Passo 4: Auditar escopo e dados**

```bash
git diff --check
git diff --stat
git status -sb
rg -n "display_name|full_name|birth_date|photo|medical|address|created_at|updated_at" \
  app/models alembic/versions/0002_cria_children.py
```

Resultado esperado: nenhum dos campos proibidos aparece no modelo ou na
migration; o diff contém somente os arquivos previstos.

- [x] **Passo 5: Criar commit documental**

```bash
git add docs/PROJECT_CONTEXT.md docs/superpowers/plans/2026-07-14-child-model.md
git commit -m "document minimal Child model"
```

- [x] **Passo 6: Publicar na main**

```bash
git push origin main
```

Resultado esperado: `origin/main` aponta para o commit documental final.
