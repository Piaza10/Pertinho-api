from fastapi import FastAPI

from app.config import Settings

configuracoes = Settings()
app = FastAPI(title=configuracoes.app_name)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
