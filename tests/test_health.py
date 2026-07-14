import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app


def test_usa_app_name_como_titulo() -> None:
    assert app.title == "Pertinho API Teste"


@pytest.mark.asyncio
async def test_ok_health() -> None:
    transporte = ASGITransport(app=app)

    async with AsyncClient(
        transport=transporte,
        base_url="http://teste",
    ) as cliente:
        resposta = await cliente.get("/health")

    assert resposta.status_code == 200
    assert resposta.json() == {"status": "ok"}
