from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from app.models import (
    Bracelet,
    BraceletStatus,
    Child,
    TransicaoBraceletInvalida,
)

ATIVACAO = datetime(2026, 1, 15, 12, tzinfo=UTC)
REVOGACAO = ATIVACAO + timedelta(hours=1)


def obter_estado(bracelet: Bracelet) -> tuple[object, ...]:
    return (
        bracelet.status,
        bracelet.child,
        bracelet.child_id,
        bracelet.activated_at,
        bracelet.revoked_at,
    )


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


@pytest.mark.parametrize(
    ("metodo", "origem", "destino"),
    [
        ("ativar", BraceletStatus.ATIVA, BraceletStatus.ATIVA),
        ("ativar", BraceletStatus.DESVINCULADA, BraceletStatus.ATIVA),
        ("ativar", BraceletStatus.PERDIDA, BraceletStatus.ATIVA),
        ("desvincular", BraceletStatus.ESTOQUE, BraceletStatus.DESVINCULADA),
        (
            "desvincular",
            BraceletStatus.DESVINCULADA,
            BraceletStatus.DESVINCULADA,
        ),
        ("desvincular", BraceletStatus.PERDIDA, BraceletStatus.DESVINCULADA),
        ("marcar_como_perdida", BraceletStatus.ESTOQUE, BraceletStatus.PERDIDA),
        (
            "marcar_como_perdida",
            BraceletStatus.DESVINCULADA,
            BraceletStatus.PERDIDA,
        ),
        ("marcar_como_perdida", BraceletStatus.PERDIDA, BraceletStatus.PERDIDA),
    ],
)
def test_rejeita_transicao_de_estado_nao_autorizada_sem_mutar(
    metodo: str,
    origem: BraceletStatus,
    destino: BraceletStatus,
) -> None:
    child = Child(id=uuid4())
    bracelet = Bracelet(
        public_token="token-que-nao-pode-aparecer-no-erro",
        status=origem,
        child=child,
        child_id=child.id,
        activated_at=ATIVACAO,
    )
    estado_anterior = obter_estado(bracelet)

    with pytest.raises(TransicaoBraceletInvalida) as erro:
        if metodo == "ativar":
            bracelet.ativar(None, datetime(2026, 1, 15, 12))  # type: ignore[arg-type]
        else:
            getattr(bracelet, metodo)(datetime(2026, 1, 15, 12))

    assert erro.value.origem is origem
    assert erro.value.destino is destino
    assert origem.value in str(erro.value)
    assert destino.value in str(erro.value)
    assert bracelet.public_token not in str(erro.value)
    assert str(child.id) not in str(erro.value)
    assert obter_estado(bracelet) == estado_anterior


@pytest.mark.parametrize("child_invalido", [None, object()])
def test_ativar_rejeita_child_invalido_sem_mutar(child_invalido: object) -> None:
    bracelet = Bracelet(status=BraceletStatus.ESTOQUE)
    estado_anterior = obter_estado(bracelet)

    with pytest.raises(TypeError, match="child deve ser uma instância de Child"):
        bracelet.ativar(child_invalido, ATIVACAO)  # type: ignore[arg-type]

    assert obter_estado(bracelet) == estado_anterior
