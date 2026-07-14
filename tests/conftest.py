import os

os.environ["APP_ENV"] = "test"
os.environ["APP_NAME"] = "Pertinho API Teste"
os.environ["DATABASE_URL"] = os.getenv(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://usuario:senha@127.0.0.1:5433/banco_teste",
)
