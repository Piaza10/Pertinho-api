from datetime import UTC, datetime, timedelta
from uuid import uuid4

from app.models import Bracelet, BraceletStatus, Child

ATIVACAO = datetime(2026, 1, 15, 12, tzinfo=UTC)
REVOGACAO = ATIVACAO + timedelta(hours=1)


def criar_bracelet_ativa() -> tuple[Bracelet, Child]:
    child = Child(id=uuid4())
    bracelet = Bracelet(
        status=BraceletStatus.ATIVA,
        child=child,
        child_id=child.id,
        activated_at=ATIVACAO,
    )
    return bracelet, child


def test_ativar_vincula_child_e_registra_instante() -> None:
    child = Child(id=uuid4())
    bracelet = Bracelet(status=BraceletStatus.ESTOQUE)

    resultado = bracelet.ativar(child, ATIVACAO)

    assert resultado is None
    assert bracelet.status is BraceletStatus.ATIVA
    assert bracelet.child is child
    assert bracelet.activated_at == ATIVACAO
    assert bracelet.revoked_at is None


def test_desvincular_remove_vinculo_e_preserva_ativacao() -> None:
    bracelet, _ = criar_bracelet_ativa()

    resultado = bracelet.desvincular(REVOGACAO)

    assert resultado is None
    assert bracelet.status is BraceletStatus.DESVINCULADA
    assert bracelet.child is None
    assert bracelet.child_id is None
    assert bracelet.activated_at == ATIVACAO
    assert bracelet.revoked_at == REVOGACAO


def test_marcar_como_perdida_remove_vinculo_e_preserva_ativacao() -> None:
    bracelet, _ = criar_bracelet_ativa()

    resultado = bracelet.marcar_como_perdida(REVOGACAO)

    assert resultado is None
    assert bracelet.status is BraceletStatus.PERDIDA
    assert bracelet.child is None
    assert bracelet.child_id is None
    assert bracelet.activated_at == ATIVACAO
    assert bracelet.revoked_at == REVOGACAO
