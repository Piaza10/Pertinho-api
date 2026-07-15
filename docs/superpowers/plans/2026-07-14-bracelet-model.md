# Modelo físico de Bracelet - Plano de implementação

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Criar o modelo físico `Bracelet` e a migration `0003`, com token público aleatório, estados restritos e integridade de vínculo validada no PostgreSQL.

**Architecture:** `Bracelet` herdará da `Base` declarativa compartilhada e manterá uma relação ORM opcional e unidirecional com `Child`. O modelo gerará UUID e token na aplicação, enquanto constraints do PostgreSQL garantirão status válidos, coerência entre estado, vínculo e datas, unicidade e integridade referencial.

**Tech Stack:** Python 3.12, `StrEnum`, `secrets`, SQLAlchemy 2 assíncrono, PostgreSQL 17, asyncpg, Alembic, pytest e Ruff.

## Restrições globais

- `BraceletStatus` deve conter exatamente `ESTOQUE`, `ATIVA`, `DESVINCULADA` e `PERDIDA`.
- O status deve ser persistido como `VARCHAR` com `CHECK`, nunca como enum nativo do PostgreSQL.
- O padrão de status no modelo e no banco deve ser `ESTOQUE`.
- `public_token` deve ser gerado pela aplicação com `secrets.token_urlsafe(32)`, possuir 43 caracteres, ser único e não nulo.
- `id` deve ser gerado pela aplicação com `uuid.uuid4`, sem `server_default`.
- `child_id` deve ser opcional, único e referenciar `children.id`, sem `CASCADE` e sem `SET NULL`.
- A constraint cruzada deve aceitar somente as quatro combinações de estado, vínculo e datas aprovadas na especificação.
- `Bracelet.child` deve ser opcional e unidirecional, sem cascade e sem coleção reversa em `Child`.
- Não adicionar endpoints, schemas Pydantic, repositórios, serviços, transições de domínio, triggers, eventos ORM, outras entidades ou dados pessoais.
- Não adicionar `created_at` nem `updated_at`.
- Testes de integração devem usar `TEST_DATABASE_URL` e ser ignorados quando ela não estiver definida.

---

### Tarefa 1: Enum e mapeamento ORM de Bracelet

**Arquivos:**
- Criar: `tests/test_bracelet_model.py`
- Modificar: `tests/test_database.py`
- Criar: `app/models/bracelet.py`
- Modificar: `app/models/__init__.py`

**Interfaces:**
- Consome: `app.database.Base` e `app.models.child.Child`.
- Produz: `app.models.BraceletStatus`, `app.models.Bracelet` e `app.models.bracelet.gerar_token_publico() -> str`.

- [x] **Passo 1: Escrever os testes unitários que falham**

Criar `tests/test_bracelet_model.py`:

```python
from sqlalchemy import DateTime, Enum, String, Uuid, inspect


def test_bracelet_status_possui_somente_estados_aprovados() -> None:
    from app.models import BraceletStatus

    assert [(status.name, status.value) for status in BraceletStatus] == [
        ("ESTOQUE", "ESTOQUE"),
        ("ATIVA", "ATIVA"),
        ("DESVINCULADA", "DESVINCULADA"),
        ("PERDIDA", "PERDIDA"),
    ]


def test_bracelet_mapeia_colunas_e_defaults_aprovados() -> None:
    from app.models import Bracelet, BraceletStatus

    colunas = inspect(Bracelet).columns

    assert Bracelet.__tablename__ == "bracelets"
    assert list(colunas.keys()) == [
        "id",
        "public_token",
        "status",
        "child_id",
        "activated_at",
        "revoked_at",
    ]

    assert isinstance(colunas.id.type, Uuid)
    assert colunas.id.primary_key
    assert not colunas.id.nullable
    assert colunas.id.default is not None
    assert colunas.id.default.is_callable
    assert colunas.id.server_default is None

    assert isinstance(colunas.public_token.type, String)
    assert colunas.public_token.type.length == 43
    assert not colunas.public_token.nullable
    assert colunas.public_token.unique
    assert colunas.public_token.default is not None
    assert colunas.public_token.default.is_callable
    assert colunas.public_token.server_default is None

    assert isinstance(colunas.status.type, Enum)
    assert not colunas.status.type.native_enum
    assert colunas.status.type.create_constraint
    assert colunas.status.type.enums == [status.value for status in BraceletStatus]
    assert not colunas.status.nullable
    assert colunas.status.default is not None
    assert colunas.status.server_default is not None
    assert colunas.status.server_default.arg == BraceletStatus.ESTOQUE.value

    assert isinstance(colunas.child_id.type, Uuid)
    assert colunas.child_id.nullable
    assert colunas.child_id.unique
    assert colunas.child_id.foreign_keys

    assert isinstance(colunas.activated_at.type, DateTime)
    assert colunas.activated_at.type.timezone
    assert colunas.activated_at.nullable
    assert isinstance(colunas.revoked_at.type, DateTime)
    assert colunas.revoked_at.type.timezone
    assert colunas.revoked_at.nullable


def test_bracelet_relaciona_child_sem_cascade_ou_relacao_reversa() -> None:
    from app.models import Bracelet, Child

    relacionamento = inspect(Bracelet).relationships.child

    assert relacionamento.mapper.class_ is Child
    assert not relacionamento.uselist
    assert relacionamento.back_populates is None
    assert set(relacionamento.cascade) == {"merge", "save-update"}
    assert "bracelets" not in inspect(Child).relationships


def test_bracelet_declara_constraints_de_estado_e_coerencia() -> None:
    from app.models import Bracelet

    nomes = {constraint.name for constraint in Bracelet.__table__.constraints}

    assert "bracelet_status" in nomes
    assert "ck_bracelets_estado_coerente" in nomes
```

Em `tests/test_database.py`, substituir o teste de metadata pela forma definitiva:

```python
def test_base_declarativa_registra_somente_children_e_bracelets() -> None:
    from sqlalchemy.orm import DeclarativeBase

    from app.database import Base
    from app.models import Bracelet, Child

    assert issubclass(Base, DeclarativeBase)
    assert Base.metadata.tables == {
        "children": Child.__table__,
        "bracelets": Bracelet.__table__,
    }
```

- [x] **Passo 2: Executar os testes e confirmar a falha**

```bash
poetry run python -m pytest \
  tests/test_bracelet_model.py \
  tests/test_database.py::test_base_declarativa_registra_somente_children_e_bracelets \
  -v
```

Resultado esperado: falha de importação porque `Bracelet` e `BraceletStatus` ainda não existem em `app.models`.

- [x] **Passo 3: Implementar o modelo mínimo**

Criar `app/models/bracelet.py`:

```python
from datetime import datetime
from enum import StrEnum
from secrets import token_urlsafe
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, DateTime, Enum, ForeignKey, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.child import Child


class BraceletStatus(StrEnum):
    ESTOQUE = "ESTOQUE"
    ATIVA = "ATIVA"
    DESVINCULADA = "DESVINCULADA"
    PERDIDA = "PERDIDA"


def gerar_token_publico() -> str:
    return token_urlsafe(32)


class Bracelet(Base):
    __tablename__ = "bracelets"
    __table_args__ = (
        CheckConstraint(
            "(status = 'ESTOQUE' AND child_id IS NULL "
            "AND activated_at IS NULL AND revoked_at IS NULL) OR "
            "(status = 'ATIVA' AND child_id IS NOT NULL "
            "AND activated_at IS NOT NULL AND revoked_at IS NULL) OR "
            "(status IN ('DESVINCULADA', 'PERDIDA') AND child_id IS NULL "
            "AND activated_at IS NOT NULL AND revoked_at IS NOT NULL)",
            name="ck_bracelets_estado_coerente",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    public_token: Mapped[str] = mapped_column(
        String(43),
        unique=True,
        default=gerar_token_publico,
    )
    status: Mapped[BraceletStatus] = mapped_column(
        Enum(
            BraceletStatus,
            name="bracelet_status",
            native_enum=False,
            create_constraint=True,
            validate_strings=True,
        ),
        default=BraceletStatus.ESTOQUE,
        server_default=BraceletStatus.ESTOQUE.value,
    )
    child_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("children.id"),
        unique=True,
    )
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    child: Mapped[Child | None] = relationship()
```

Substituir `app/models/__init__.py` por:

```python
from app.models.bracelet import Bracelet, BraceletStatus
from app.models.child import Child

__all__ = ["Bracelet", "BraceletStatus", "Child"]
```

- [x] **Passo 4: Executar os testes e confirmar sucesso**

```bash
poetry run python -m pytest \
  tests/test_bracelet_model.py \
  tests/test_database.py::test_base_declarativa_registra_somente_children_e_bracelets \
  -v
```

Resultado esperado: `5 passed`.

- [x] **Passo 5: Executar Ruff no recorte**

```bash
poetry run ruff check \
  app/models \
  tests/test_bracelet_model.py \
  tests/test_database.py
```

Resultado esperado: `All checks passed!`.

- [x] **Passo 6: Criar commit do ciclo**

```bash
git add \
  app/models/__init__.py \
  app/models/bracelet.py \
  tests/test_bracelet_model.py \
  tests/test_database.py
git commit -m "add Bracelet model"
```

---

### Tarefa 2: Migration 0003 e schema real

**Arquivos:**
- Modificar: `tests/test_migrations.py`
- Modificar: `alembic/env.py`
- Criar: `alembic/versions/0003_cria_bracelets.py`

**Interfaces:**
- Consome: `app.models.Bracelet`, `app.models.Child` e revisão Alembic `0002`.
- Produz: revisão `0003`, que cria `bracelets` no upgrade e remove somente `bracelets` no downgrade.

- [x] **Passo 1: Alterar o teste de migration para exigir a revisão 0003**

Em `tests/test_migrations.py`, ajustar os imports:

```python
from sqlalchemy import DateTime, String, Uuid, inspect

from app.database import engine, session_factory
from app.models import Child
```

Renomear `obter_revisao_colunas_e_pk` para `obter_schema_children` e manter seu corpo atual. Adicionar a função abaixo após ela:

```python
async def obter_schema_bracelets() -> tuple[
    str | None,
    list[dict[str, object]],
    dict[str, object],
    list[dict[str, object]],
    list[dict[str, object]],
    list[dict[str, object]],
]:
    try:
        async with engine.connect() as conexao:
            def inspecionar(conexao_sincrona):
                inspetor = inspect(conexao_sincrona)
                revisao = MigrationContext.configure(
                    conexao_sincrona,
                ).get_current_revision()
                return (
                    revisao,
                    inspetor.get_columns("bracelets"),
                    inspetor.get_pk_constraint("bracelets"),
                    inspetor.get_unique_constraints("bracelets"),
                    inspetor.get_foreign_keys("bracelets"),
                    inspetor.get_check_constraints("bracelets"),
                )

            return await conexao.run_sync(inspecionar)
    finally:
        await engine.dispose()
```

Substituir `children_existe` por uma função genérica:

```python
async def tabela_existe(nome: str) -> bool:
    try:
        async with engine.connect() as conexao:
            return await conexao.run_sync(
                lambda conexao_sincrona: inspect(conexao_sincrona).has_table(
                    nome,
                ),
            )
    finally:
        await engine.dispose()
```

Atualizar o teste existente de `children` para usar o novo nome do helper e exigir que o head seja `0003`:

```python
@requer_banco_de_teste
def test_alembic_preserva_children_com_somente_id() -> None:
    revisao_atual, colunas, chave_primaria = asyncio.run(
        obter_schema_children(),
    )

    assert revisao_atual == "0003"
    assert [coluna["name"] for coluna in colunas] == ["id"]
    assert chave_primaria["constrained_columns"] == ["id"]
    assert not colunas[0]["nullable"]
    assert colunas[0]["default"] is None
```

Adicionar o teste do schema de `bracelets`:

```python
@requer_banco_de_teste
def test_alembic_aplica_0003_com_schema_de_bracelets() -> None:
    (
        revisao_atual,
        colunas,
        chave_primaria,
        unicidades,
        chaves_estrangeiras,
        checks,
    ) = asyncio.run(obter_schema_bracelets())

    colunas_por_nome = {coluna["name"]: coluna for coluna in colunas}
    nomes_unicidades = {constraint["name"] for constraint in unicidades}
    checks_por_nome = {constraint["name"]: constraint["sqltext"] for constraint in checks}

    assert revisao_atual == "0003"
    assert list(colunas_por_nome) == [
        "id",
        "public_token",
        "status",
        "child_id",
        "activated_at",
        "revoked_at",
    ]
    assert isinstance(colunas_por_nome["id"]["type"], Uuid)
    assert chave_primaria["constrained_columns"] == ["id"]
    assert isinstance(colunas_por_nome["public_token"]["type"], String)
    assert colunas_por_nome["public_token"]["type"].length == 43
    assert not colunas_por_nome["public_token"]["nullable"]
    assert "uq_bracelets_public_token" in nomes_unicidades
    assert "uq_bracelets_child_id" in nomes_unicidades
    assert "ESTOQUE" in colunas_por_nome["status"]["default"]
    assert isinstance(colunas_por_nome["activated_at"]["type"], DateTime)
    assert colunas_por_nome["activated_at"]["type"].timezone
    assert isinstance(colunas_por_nome["revoked_at"]["type"], DateTime)
    assert colunas_por_nome["revoked_at"]["type"].timezone
    assert len(chaves_estrangeiras) == 1
    chave_estrangeira = chaves_estrangeiras[0]
    assert chave_estrangeira["name"] == "fk_bracelets_child_id_children"
    assert chave_estrangeira["constrained_columns"] == ["child_id"]
    assert chave_estrangeira["referred_table"] == "children"
    assert chave_estrangeira["referred_columns"] == ["id"]
    assert chave_estrangeira["options"] == {}
    assert set(checks_por_nome) == {
        "bracelet_status",
        "ck_bracelets_estado_coerente",
    }
    check_status = checks_por_nome["bracelet_status"]
    assert all(
        status in check_status
        for status in ("ESTOQUE", "ATIVA", "DESVINCULADA", "PERDIDA")
    )
    check_estado = checks_por_nome["ck_bracelets_estado_coerente"]
    assert all(
        trecho in check_estado
        for trecho in (
            "status",
            "child_id",
            "activated_at",
            "revoked_at",
            "ESTOQUE",
            "ATIVA",
            "DESVINCULADA",
            "PERDIDA",
            "IS NULL",
            "IS NOT NULL",
        )
    )
```

Substituir o teste de downgrade por:

```python
@requer_banco_de_teste
def test_downgrade_0003_remove_somente_bracelets(
    configuracao_alembic: Config,
) -> None:
    command.downgrade(configuracao_alembic, "0002")

    try:
        bracelets_existe = asyncio.run(tabela_existe("bracelets"))
        children_existe = asyncio.run(tabela_existe("children"))
    finally:
        command.upgrade(configuracao_alembic, "head")
        bracelets_restaurada = asyncio.run(tabela_existe("bracelets"))
        children_restaurada = asyncio.run(tabela_existe("children"))

    assert not bracelets_existe
    assert children_existe
    assert bracelets_restaurada
    assert children_restaurada
```

- [x] **Passo 2: Executar os testes e confirmar a falha**

```bash
set -a
source .env
set +a
TEST_DATABASE_URL="$DATABASE_URL" poetry run python -m pytest \
  tests/test_migrations.py \
  -v
```

Resultado esperado: falha porque o head ainda é `0002` e a tabela `bracelets` não existe.

- [x] **Passo 3: Registrar a metadata completa no Alembic**

Em `alembic/env.py`, substituir:

```python
from app.models import Child
```

por:

```python
from app.models import Bracelet
```

Substituir:

```python
target_metadata = Child.metadata
```

por:

```python
target_metadata = Bracelet.metadata
```

`Bracelet.metadata` é a metadata da `Base` compartilhada e contém `children` e `bracelets`; o import também garante o registro dos dois modelos.

- [x] **Passo 4: Criar a migration 0003**

Criar `alembic/versions/0003_cria_bracelets.py`:

```python
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | Sequence[str] | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "bracelets",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("public_token", sa.String(length=43), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "ESTOQUE",
                "ATIVA",
                "DESVINCULADA",
                "PERDIDA",
                name="bracelet_status",
                native_enum=False,
                create_constraint=True,
            ),
            server_default="ESTOQUE",
            nullable=False,
        ),
        sa.Column("child_id", sa.Uuid(), nullable=True),
        sa.Column(
            "activated_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "revoked_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.CheckConstraint(
            "(status = 'ESTOQUE' AND child_id IS NULL "
            "AND activated_at IS NULL AND revoked_at IS NULL) OR "
            "(status = 'ATIVA' AND child_id IS NOT NULL "
            "AND activated_at IS NOT NULL AND revoked_at IS NULL) OR "
            "(status IN ('DESVINCULADA', 'PERDIDA') AND child_id IS NULL "
            "AND activated_at IS NOT NULL AND revoked_at IS NOT NULL)",
            name="ck_bracelets_estado_coerente",
        ),
        sa.ForeignKeyConstraint(
            ["child_id"],
            ["children.id"],
            name="fk_bracelets_child_id_children",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_bracelets"),
        sa.UniqueConstraint(
            "child_id",
            name="uq_bracelets_child_id",
        ),
        sa.UniqueConstraint(
            "public_token",
            name="uq_bracelets_public_token",
        ),
    )


def downgrade() -> None:
    op.drop_table("bracelets")
```

- [x] **Passo 5: Executar os testes e confirmar sucesso**

```bash
set -a
source .env
set +a
TEST_DATABASE_URL="$DATABASE_URL" poetry run python -m pytest \
  tests/test_migrations.py \
  -v
```

Resultado esperado: `4 passed`.

- [x] **Passo 6: Confirmar a revisão aplicada**

```bash
set -a
source .env
set +a
poetry run alembic current
```

Resultado esperado: `0003 (head)`.

- [x] **Passo 7: Executar Ruff no recorte**

```bash
poetry run ruff check \
  alembic/env.py \
  alembic/versions/0003_cria_bracelets.py \
  tests/test_migrations.py
```

Resultado esperado: `All checks passed!`.

- [x] **Passo 8: Criar commit do ciclo**

```bash
git add \
  alembic/env.py \
  alembic/versions/0003_cria_bracelets.py \
  tests/test_migrations.py
git commit -m "add bracelets migration"
```

---

### Tarefa 3: Testes de aceitação dos defaults e constraints no PostgreSQL

**Arquivos:**
- Criar: `tests/test_bracelet_database.py`

**Interfaces:**
- Consome: `Bracelet`, `BraceletStatus`, `Child`, `engine`, `session_factory` e schema Alembic `0003`.
- Produz: cobertura de aceitação para defaults, token, unicidades, FK, status e coerência de estado, sem alterar código de produção.

- [x] **Passo 1: Escrever os testes de integração**

Criar `tests/test_bracelet_database.py`:

```python
import asyncio
import os
import re
from collections.abc import Iterator
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.database import engine, session_factory
from app.models import Bracelet, BraceletStatus, Child

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


async def criar_bracelets_em_estoque() -> tuple[Bracelet, Bracelet]:
    try:
        async with session_factory() as sessao:
            primeira = Bracelet()
            segunda = Bracelet()
            sessao.add_all([primeira, segunda])
            await sessao.flush()
            sessao.expunge_all()
            await sessao.rollback()
            return primeira, segunda
    finally:
        await engine.dispose()


async def confirmar_erro_de_integridade(*objetos: object) -> None:
    try:
        async with session_factory() as sessao:
            sessao.add_all(objetos)
            with pytest.raises(IntegrityError):
                await sessao.flush()
            await sessao.rollback()
    finally:
        await engine.dispose()


async def confirmar_erro_em_sql(comando: str, parametros: dict[str, object]) -> None:
    try:
        async with engine.connect() as conexao:
            with pytest.raises(IntegrityError):
                await conexao.execute(text(comando), parametros)
            await conexao.rollback()
    finally:
        await engine.dispose()


@requer_banco_de_teste
def test_bracelet_gera_uuid_token_distinto_e_status_estoque() -> None:
    primeira, segunda = asyncio.run(criar_bracelets_em_estoque())

    assert isinstance(primeira.id, UUID)
    assert isinstance(segunda.id, UUID)
    assert primeira.id != segunda.id
    assert len(primeira.public_token) == 43
    assert len(segunda.public_token) == 43
    assert primeira.public_token != segunda.public_token
    assert re.fullmatch(r"[A-Za-z0-9_-]{43}", primeira.public_token)
    assert re.fullmatch(r"[A-Za-z0-9_-]{43}", segunda.public_token)
    assert primeira.status is BraceletStatus.ESTOQUE
    assert segunda.status is BraceletStatus.ESTOQUE


@requer_banco_de_teste
def test_banco_rejeita_public_token_repetido() -> None:
    token = "a" * 43

    asyncio.run(
        confirmar_erro_de_integridade(
            Bracelet(public_token=token),
            Bracelet(public_token=token),
        ),
    )


@requer_banco_de_teste
def test_banco_rejeita_duas_pulseiras_vinculadas_a_mesma_crianca() -> None:
    child = Child()
    instante = datetime.now(UTC)

    asyncio.run(
        confirmar_erro_de_integridade(
            child,
            Bracelet(
                status=BraceletStatus.ATIVA,
                child=child,
                activated_at=instante,
            ),
            Bracelet(
                status=BraceletStatus.ATIVA,
                child=child,
                activated_at=instante,
            ),
        ),
    )


@requer_banco_de_teste
def test_banco_rejeita_child_inexistente() -> None:
    asyncio.run(
        confirmar_erro_de_integridade(
            Bracelet(
                status=BraceletStatus.ATIVA,
                child_id=uuid4(),
                activated_at=datetime.now(UTC),
            ),
        ),
    )


@requer_banco_de_teste
@pytest.mark.parametrize(
    ("status", "child_id", "activated_at", "revoked_at"),
    [
        ("ESTOQUE", None, datetime.now(UTC), None),
        ("ATIVA", None, datetime.now(UTC), None),
        ("DESVINCULADA", None, datetime.now(UTC), None),
        ("PERDIDA", None, datetime.now(UTC), None),
    ],
)
def test_banco_rejeita_combinacoes_incoerentes(
    status: str,
    child_id: UUID | None,
    activated_at: datetime | None,
    revoked_at: datetime | None,
) -> None:
    asyncio.run(
        confirmar_erro_em_sql(
            """
            INSERT INTO bracelets (
                id,
                public_token,
                status,
                child_id,
                activated_at,
                revoked_at
            ) VALUES (
                :id,
                :public_token,
                :status,
                :child_id,
                :activated_at,
                :revoked_at
            )
            """,
            {
                "id": uuid4(),
                "public_token": uuid4().hex + "abcdefghijk",
                "status": status,
                "child_id": child_id,
                "activated_at": activated_at,
                "revoked_at": revoked_at,
            },
        ),
    )


@requer_banco_de_teste
def test_banco_rejeita_status_fora_do_enum() -> None:
    asyncio.run(
        confirmar_erro_em_sql(
            """
            INSERT INTO bracelets (id, public_token, status)
            VALUES (:id, :public_token, :status)
            """,
            {
                "id": uuid4(),
                "public_token": uuid4().hex + "abcdefghijk",
                "status": "INVALIDA",
            },
        ),
    )
```

- [x] **Passo 2: Executar os testes e confirmar sucesso**

Estes testes de aceitação são escritos depois da migration porque não introduzem
novo comportamento. Cada decisão de produção já foi exigida antes da
implementação pelos testes vermelhos das tarefas 1 e 2; aqui se confirma que as
constraints inspecionadas também funcionam diante de inserções reais.

```bash
set -a
source .env
set +a
TEST_DATABASE_URL="$DATABASE_URL" poetry run python -m pytest \
  tests/test_bracelet_database.py \
  -v
```

Resultado esperado: `9 passed` — quatro casos do teste parametrizado contam separadamente.

- [x] **Passo 3: Executar Ruff no novo teste**

```bash
poetry run ruff check tests/test_bracelet_database.py
```

Resultado esperado: `All checks passed!`.

- [x] **Passo 4: Criar commit do ciclo**

```bash
git add tests/test_bracelet_database.py
git commit -m "test Bracelet database constraints"
```

---

### Tarefa 4: Documentação e verificação final

**Arquivos:**
- Modificar: `docs/PROJECT_CONTEXT.md`

**Interfaces:**
- Consome: implementação concluída de `Bracelet` e revisão Alembic `0003`.
- Produz: estado atual do projeto documentado sem antecipar operações de domínio.

- [x] **Passo 1: Atualizar somente o estado implementado**

Em `docs/PROJECT_CONTEXT.md`, após o item da migration `0002`, adicionar:

```markdown
- Modelo físico `Bracelet` criado com UUID, token público aleatório, os quatro
  estados aprovados, vínculo opcional e unidirecional com `Child` e datas de
  ativação/revogação.
- Migration `0003` cria `bracelets` com constraints de status, coerência de
  estado, unicidade e chave estrangeira, e suporta downgrade para `0002` sem
  alterar `children`.
- Defaults e constraints de `Bracelet` validados no PostgreSQL local por testes
  de integração condicionados a `TEST_DATABASE_URL`.
```

Substituir a seção `## Próximo recorte` por:

```markdown
## Próximo recorte

O modelo físico de `Bracelet` está concluído. As operações de ativação,
desvinculação e perda ainda não foram implementadas e exigem novo recorte
técnico aprovado. Qualquer nova entidade, campo, endpoint ou serviço também
deve ser apresentado e aprovado separadamente.
```

- [x] **Passo 2: Executar a suíte completa com PostgreSQL**

```bash
set -a
source .env
set +a
TEST_DATABASE_URL="$DATABASE_URL" poetry run python -m pytest -v
```

Resultado esperado: todos os testes passam, sem skips de integração e sem warnings inesperados.

- [x] **Passo 3: Executar Ruff em todo o projeto**

```bash
poetry run ruff check .
```

Resultado esperado: `All checks passed!`.

- [x] **Passo 4: Confirmar a revisão final do banco**

```bash
set -a
source .env
set +a
poetry run alembic current
```

Resultado esperado: `0003 (head)`.

- [x] **Passo 5: Revisar escopo e alterações**

```bash
git status --short
git diff --check
git diff --stat HEAD
```

Resultado esperado: somente arquivos do modelo, migration, testes e contexto de `Bracelet`; `git diff --check` não produz saída.

- [x] **Passo 6: Criar commit da documentação**

```bash
git add docs/PROJECT_CONTEXT.md
git commit -m "document Bracelet model"
```

- [x] **Passo 7: Apresentar o resultado e parar**

Informar:

- arquivos criados e alterados;
- quantidade de testes aprovados;
- resultado do Ruff;
- revisão Alembic atual;
- confirmação de que endpoints, serviços, transições, outras entidades e dados pessoais não foram adicionados.

Parar e aguardar aprovação explícita antes de qualquer nova tarefa.
