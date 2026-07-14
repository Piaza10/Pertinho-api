import os

os.environ["APP_ENV"] = "test"
os.environ["APP_NAME"] = "Pertinho API Teste"
os.environ["DATABASE_URL"] = (
    "postgresql+asyncpg://pertinho:pertinho_local_dev@127.0.0.1:5433/pertinho"
)
