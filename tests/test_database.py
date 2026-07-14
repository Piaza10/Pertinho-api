import os

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

BANCO_DE_TESTE_CONFIGURADO = os.getenv("TEST_DATABASE_URL") is not None
requer_banco_de_teste = pytest.mark.skipif(
    not BANCO_DE_TESTE_CONFIGURADO,
    reason="TEST_DATABASE_URL não configurada",
)


@requer_banco_de_teste
@pytest.mark.asyncio
async def test_engine_executa_select_1() -> None:
    try:
        from app.database import engine
    except ModuleNotFoundError:
        pytest.fail("app.database ainda não existe", pytrace=False)

    try:
        async with engine.connect() as conexao:
            resultado = await conexao.scalar(text("SELECT 1"))
    finally:
        await engine.dispose()

    assert resultado == 1


@requer_banco_de_teste
@pytest.mark.asyncio
async def test_get_session_fornece_sessao_funcional() -> None:
    try:
        from app.database import engine, get_session
    except ModuleNotFoundError:
        pytest.fail("app.database ainda não existe", pytrace=False)

    gerador = get_session()
    sessao = await anext(gerador)

    try:
        resultado = await sessao.scalar(text("SELECT 1"))
    finally:
        await gerador.aclose()
        await engine.dispose()

    assert isinstance(sessao, AsyncSession)
    assert resultado == 1


def test_base_declarativa_registra_somente_children() -> None:
    from sqlalchemy.orm import DeclarativeBase

    from app.database import Base
    from app.models import Child

    assert issubclass(Base, DeclarativeBase)
    assert Base.metadata.tables == {"children": Child.__table__}
