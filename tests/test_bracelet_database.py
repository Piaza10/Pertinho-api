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


async def confirmar_erro_em_sql(
    comando: str,
    parametros: dict[str, object],
) -> None:
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
