from pathlib import Path

import pytest
from pydantic import ValidationError

from app.config import Settings

DATABASE_URL_TESTE = (
    "postgresql+asyncpg://pertinho:pertinho_local_dev@127.0.0.1:5433/pertinho"
)


@pytest.fixture(autouse=True)
def isolar_variaveis_de_ambiente(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("APP_ENV", raising=False)
    monkeypatch.delenv("APP_NAME", raising=False)
    monkeypatch.setenv("DATABASE_URL", DATABASE_URL_TESTE)


@pytest.mark.parametrize(
    "app_env",
    ["development", "test", "production"],
)
def test_aceita_app_env_valido(
    monkeypatch: pytest.MonkeyPatch,
    app_env: str,
) -> None:
    monkeypatch.setenv("APP_ENV", app_env)

    configuracoes = Settings(_env_file=None)

    assert configuracoes.app_env == app_env


def test_exige_app_env() -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_rejeita_app_env_invalido(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_ENV", "staging")

    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_usa_app_name_padrao(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_ENV", "test")

    configuracoes = Settings(_env_file=None)

    assert configuracoes.app_name == "Pertinho API"


def test_aceita_app_name_do_ambiente(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("APP_NAME", "Pertinho API Teste")

    configuracoes = Settings(_env_file=None)

    assert configuracoes.app_name == "Pertinho API Teste"


def test_ignora_variaveis_extras_do_arquivo_env(tmp_path: Path) -> None:
    arquivo_env = tmp_path / ".env"
    arquivo_env.write_text(
        "APP_ENV=test\nPOSTGRES_DB=pertinho\n",
        encoding="utf-8",
    )

    configuracoes = Settings(_env_file=arquivo_env)

    assert configuracoes.app_env == "test"


def test_exige_database_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.delenv("DATABASE_URL")

    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_aceita_database_url_do_ambiente(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("APP_ENV", "test")

    configuracoes = Settings(_env_file=None)

    assert configuracoes.database_url == DATABASE_URL_TESTE
