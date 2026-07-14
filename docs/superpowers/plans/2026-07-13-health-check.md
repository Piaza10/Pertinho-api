# Plano de Implementação do Health Check

> **Para agentes:** SUB-SKILL OBRIGATÓRIA: use `superpowers:executing-plans` para executar este plano passo a passo.

**Objetivo:** Criar o primeiro endpoint da API Pertinho com TDD.

**Arquitetura:** Uma instância mínima de `FastAPI` em `app/main.py` expõe
`GET /health`. Um teste de integração leve usa `httpx.AsyncClient` com
`ASGITransport` para validar o status HTTP e o corpo JSON.

**Stack:** Python 3.12+, FastAPI, pytest, pytest-asyncio e HTTPX.

## Restrições globais

- Não implementar banco de dados.
- Não implementar autenticação.
- Não implementar endpoints de negócio.
- Manter nomes de testes em português.

---

### Tarefa 1: Endpoint de saúde

**Arquivos:**

- Criar: `tests/test_health.py`
- Criar: `app/main.py`

**Interfaces:**

- Produz: aplicação ASGI `app.main:app`
- Produz: `GET /health` com HTTP `200` e `{"status": "ok"}`

- [x] **Passo 1: escrever o teste que falha**

```python
import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app


@pytest.mark.asyncio
async def test_deve_retornar_status_ok_ao_consultar_health() -> None:
    transporte = ASGITransport(app=app)

    async with AsyncClient(
        transport=transporte,
        base_url="http://teste",
    ) as cliente:
        resposta = await cliente.get("/health")

    assert resposta.status_code == 200
    assert resposta.json() == {"status": "ok"}
```

- [x] **Passo 2: confirmar a falha**

Executar: `poetry run python -m pytest tests/test_health.py -v`

Resultado esperado: erro de importação porque `app.main` ainda não existe.

- [x] **Passo 3: escrever a implementação mínima**

```python
from fastapi import FastAPI

app = FastAPI()


@app.get("/health")
async def verificar_saude() -> dict[str, str]:
    return {"status": "ok"}
```

- [x] **Passo 4: confirmar o sucesso**

Executar: `poetry run python -m pytest tests/test_health.py -v`

Resultado esperado: um teste aprovado.

- [x] **Passo 5: verificar qualidade**

Executar: `poetry run python -m pytest -v` e
`poetry run ruff check app tests`.

Resultado esperado: toda a suíte aprovada e nenhuma violação do Ruff.

Não há passo de commit porque o workspace não está inicializado como
repositório Git.
