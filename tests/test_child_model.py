from sqlalchemy import Uuid, inspect


def test_child_mapeia_somente_id_uuid() -> None:
    from app.models import Child

    colunas = inspect(Child).columns

    assert Child.__tablename__ == "children"
    assert list(colunas.keys()) == ["id"]
    assert isinstance(colunas.id.type, Uuid)
    assert colunas.id.primary_key
    assert not colunas.id.nullable
    assert colunas.id.default is not None
    assert colunas.id.default.is_callable
    assert colunas.id.server_default is None
