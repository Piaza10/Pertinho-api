# Alembic assíncrono sem modelos - Plano de implementação

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Configurar uma base declarativa vazia e o Alembic assíncrono, comprovando que uma revisão inicial sem tabelas de negócio pode ser aplicada ao PostgreSQL local.

**Architecture:** A `Base` compartilhada ficará em `app/database.py`. O ambiente Alembic obterá `DATABASE_URL` por `Settings`, criará sua própria engine assíncrona e usará `Base.metadata` como alvo de migrations.

**Tech Stack:** Python 3.12, SQLAlchemy 2 assíncrono, asyncpg, Alembic, PostgreSQL 17, pytest, pytest-asyncio e Ruff.

## Restrições globais

- Não criar modelos ou tabelas de negócio.
- Não criar endpoints, repositórios, autenticação ou dados iniciais.
- Não escrever URL ou credenciais reais em `alembic.ini`.
- Usar o PostgreSQL local existente em `127.0.0.1:5433` sem remover volumes.
- A revisão inicial deve ter `upgrade` e `downgrade` vazios.
- Preservar a suíte atual e manter o Ruff sem ocorrências.

---

### Tarefa 1: Base declarativa compartilhada e vazia

**Arquivos:**
- Modificar: `tests/test_database.py`
- Modificar: `app/database.py`

**Interfaces:**
- Consome: infraestrutura de conexão existente em `app.database`.
- Produz: `app.database.Base`, subclasse de `sqlalchemy.orm.DeclarativeBase`, com `Base.metadata` inicialmente vazio.

- [x] **Passo 1: Escrever o teste que falha**

Adicionar ao final de `tests/test_database.py`:

```python
def test_base_declarativa_inicia_sem_tabelas() -> None:
    from sqlalchemy.orm import DeclarativeBase

    from app.database import Base

    assert issubclass(Base, DeclarativeBase)
    assert not Base.metadata.tables
```

- [x] **Passo 2: Executar o teste e confirmar a falha**

Executar:

```bash
poetry run python -m pytest \
  tests/test_database.py::test_base_declarativa_inicia_sem_tabelas -v
```

Resultado esperado: falha de importação porque `app.database` ainda não exporta `Base`.

- [x] **Passo 3: Implementar o mínimo necessário**

Adicionar o import em `app/database.py`:

```python
from sqlalchemy.orm import DeclarativeBase
```

Declarar a base antes da criação do engine:

```python
class Base(DeclarativeBase):
    pass
```

- [x] **Passo 4: Executar o teste e confirmar sucesso**

Executar:

```bash
poetry run python -m pytest \
  tests/test_database.py::test_base_declarativa_inicia_sem_tabelas -v
```

Resultado esperado: `1 passed`.

- [x] **Passo 5: Criar commit do ciclo**

```bash
git add app/database.py tests/test_database.py
git commit -m "add declarative database base"
```

---

### Tarefa 2: Ambiente Alembic assíncrono e revisão inicial

**Arquivos:**
- Criar: `tests/test_migrations.py`
- Criar: `alembic.ini`
- Criar: `alembic/env.py`
- Criar: `alembic/script.py.mako`
- Criar: `alembic/versions/0001_revisao_inicial.py`

**Interfaces:**
- Consome: `app.config.Settings`, `app.database.Base` e a variável obrigatória `DATABASE_URL`.
- Produz: configuração Alembic executável com `poetry run alembic upgrade head`, tendo `0001` como revisão inicial.

- [x] **Passo 1: Escrever o teste de integração que falha**

Criar `tests/test_migrations.py`:

```python
import asyncio

from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext

from app.database import Base, engine


async def obter_revisao_atual() -> str | None:
    try:
        async with engine.connect() as conexao:
            return await conexao.run_sync(
                lambda conexao_sincrona: MigrationContext.configure(
                    conexao_sincrona,
                ).get_current_revision(),
            )
    finally:
        await engine.dispose()


def test_alembic_aplica_revisao_inicial_sem_tabelas_de_negocio() -> None:
    configuracao = Config("alembic.ini")

    command.upgrade(configuracao, "head")
    revisao_atual = asyncio.run(obter_revisao_atual())

    assert revisao_atual == "0001"
    assert not Base.metadata.tables
```

- [x] **Passo 2: Executar o teste e confirmar a falha**

Executar:

```bash
poetry run python -m pytest tests/test_migrations.py -v
```

Resultado esperado: falha porque `alembic.ini` e o diretório de scripts ainda não existem.

- [x] **Passo 3: Gerar a estrutura assíncrona do Alembic**

Executar:

```bash
poetry run alembic init -t async alembic
```

Manter `alembic/script.py.mako` produzido pelo template oficial. Substituir o
conteúdo de `alembic/env.py` por:

```python
import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from app.config import Settings
from app.database import Base

config = context.config
config.set_main_option(
    "sqlalchemy.url",
    Settings().database_url.replace("%", "%%"),
)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def executar_migrations(conexao: Connection) -> None:
    context.configure(connection=conexao, target_metadata=target_metadata)

    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    configuracao = config.get_section(config.config_ini_section, {})
    engine = async_engine_from_config(
        configuracao,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    async with engine.connect() as conexao:
        await conexao.run_sync(executar_migrations)

    await engine.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
```

No `alembic.ini` gerado, remover a linha `sqlalchemy.url = ...`. A URL será
inserida exclusivamente por `Settings` em tempo de execução.

- [x] **Passo 4: Criar a revisão inicial vazia**

Criar `alembic/versions/0001_revisao_inicial.py`:

```python
from collections.abc import Sequence

revision: str = "0001"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
```

- [x] **Passo 5: Executar o teste e confirmar sucesso**

Executar:

```bash
poetry run python -m pytest tests/test_migrations.py -v
```

Resultado esperado: `1 passed`, revisão atual `0001` e metadata sem tabelas de negócio.

- [x] **Passo 6: Validar os comandos operacionais**

Executar:

```bash
poetry run alembic upgrade head
poetry run alembic current
```

Resultado esperado: `upgrade head` termina sem erro e `current` informa `0001 (head)`.

- [x] **Passo 7: Criar commit do ciclo**

```bash
git add alembic.ini alembic tests/test_migrations.py
git commit -m "configure async Alembic"
```

---

### Tarefa 3: Verificação e documentação do recorte

**Arquivos:**
- Modificar: `docs/PROJECT_CONTEXT.md`

**Interfaces:**
- Consome: resultado validado das tarefas 1 e 2.
- Produz: registro fiel do estado implementado e comandos de migration.

- [x] **Passo 1: Atualizar o estado do projeto**

Em `docs/PROJECT_CONTEXT.md`, registrar em `Estado atual implementado`:

```markdown
- Base declarativa compartilhada criada, ainda sem modelos ou tabelas de negócio.
- Alembic configurado para usar conexão assíncrona e `DATABASE_URL` via `Settings`.
- Revisão inicial vazia `0001` aplicada ao PostgreSQL local.
```

Em `Próximo recorte`, deixar explícito que qualquer modelagem física ainda
depende de novo escopo e aprovação.

- [x] **Passo 2: Executar a verificação final completa**

Executar:

```bash
poetry run python -m pytest -v
poetry run ruff check .
poetry run alembic current
```

Resultado esperado: toda a suíte passa, Ruff sem ocorrências e revisão `0001 (head)`.

- [x] **Passo 3: Conferir o escopo do diff**

```bash
git status -sb
git diff --check
git diff --stat
```

Resultado esperado: somente os arquivos descritos neste plano aparecem no diff e não há erros de espaços em branco.

- [x] **Passo 4: Criar commit da documentação**

```bash
git add docs/PROJECT_CONTEXT.md docs/superpowers/plans/2026-07-14-alembic-async.md
git commit -m "document async Alembic setup"
```

- [x] **Passo 5: Publicar a branch atualizada**

```bash
git push
```

Resultado esperado: o pull request rascunho existente recebe os novos commits.
