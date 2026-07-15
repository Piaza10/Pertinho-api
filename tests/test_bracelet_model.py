from sqlalchemy import DateTime, Enum, String, Uuid, inspect


def test_bracelet_status_possui_somente_estados_aprovados() -> None:
    from app.models import BraceletStatus

    assert [(status.name, status.value) for status in BraceletStatus] == [
        ("ESTOQUE", "ESTOQUE"),
        ("ATIVA", "ATIVA"),
        ("DESVINCULADA", "DESVINCULADA"),
        ("PERDIDA", "PERDIDA"),
    ]


def test_bracelet_mapeia_colunas_e_defaults_aprovados() -> None:
    from app.models import Bracelet, BraceletStatus

    colunas = inspect(Bracelet).columns

    assert Bracelet.__tablename__ == "bracelets"
    assert list(colunas.keys()) == [
        "id",
        "public_token",
        "status",
        "child_id",
        "activated_at",
        "revoked_at",
    ]

    assert isinstance(colunas.id.type, Uuid)
    assert colunas.id.primary_key
    assert not colunas.id.nullable
    assert colunas.id.default is not None
    assert colunas.id.default.is_callable
    assert colunas.id.server_default is None

    assert isinstance(colunas.public_token.type, String)
    assert colunas.public_token.type.length == 43
    assert not colunas.public_token.nullable
    assert colunas.public_token.unique
    assert colunas.public_token.default is not None
    assert colunas.public_token.default.is_callable
    assert colunas.public_token.server_default is None

    assert isinstance(colunas.status.type, Enum)
    assert not colunas.status.type.native_enum
    assert colunas.status.type.create_constraint
    assert colunas.status.type.enums == [
        status.value for status in BraceletStatus
    ]
    assert not colunas.status.nullable
    assert colunas.status.default is not None
    assert colunas.status.server_default is not None
    assert colunas.status.server_default.arg == BraceletStatus.ESTOQUE.value

    assert isinstance(colunas.child_id.type, Uuid)
    assert colunas.child_id.nullable
    assert colunas.child_id.unique
    assert colunas.child_id.foreign_keys

    assert isinstance(colunas.activated_at.type, DateTime)
    assert colunas.activated_at.type.timezone
    assert colunas.activated_at.nullable
    assert isinstance(colunas.revoked_at.type, DateTime)
    assert colunas.revoked_at.type.timezone
    assert colunas.revoked_at.nullable


def test_bracelet_relaciona_child_sem_cascade_ou_relacao_reversa() -> None:
    from app.models import Bracelet, Child

    relacionamento = inspect(Bracelet).relationships.child

    assert relacionamento.mapper.class_ is Child
    assert not relacionamento.uselist
    assert relacionamento.back_populates is None
    assert set(relacionamento.cascade) == {"merge", "save-update"}
    assert "bracelets" not in inspect(Child).relationships


def test_bracelet_declara_constraints_de_estado_e_coerencia() -> None:
    from app.models import Bracelet

    nomes = {constraint.name for constraint in Bracelet.__table__.constraints}

    assert "bracelet_status" in nomes
    assert "ck_bracelets_estado_coerente" in nomes
