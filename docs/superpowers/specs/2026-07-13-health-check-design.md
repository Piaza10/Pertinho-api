# Desenho do health check

## Objetivo

Disponibilizar `GET /health` como o primeiro endpoint da API Pertinho para
confirmar que o processo HTTP está respondendo.

## Contrato

- Método e caminho: `GET /health`
- Resposta de sucesso: HTTP `200`
- Corpo JSON: `{"status": "ok"}`

## Estrutura

- `app/main.py` conterá a instância mínima de `FastAPI` e a rota.
- `tests/test_health.py` verificará o contrato com `httpx.AsyncClient` e
  `ASGITransport`, sem abrir uma conexão de rede real.

## Restrições

Este incremento não inclui banco de dados, autenticação, configurações ou
endpoints de negócio.
