import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


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


def test_base_declarativa_inicia_sem_tabelas() -> None:
    from sqlalchemy.orm import DeclarativeBase

    from app.database import Base

    assert issubclass(Base, DeclarativeBase)
    assert not Base.metadata.tables
