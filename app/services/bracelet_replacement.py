from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Bracelet, Child


class RecursoTrocaNaoEncontrado(LookupError):
    def __init__(self) -> None:
        super().__init__("Recurso de troca não encontrado")


class BraceletsTrocaIguais(ValueError):
    def __init__(self) -> None:
        super().__init__("As pulseiras da troca devem ser distintas")


async def trocar_bracelet(
    sessao: AsyncSession,
    bracelet_anterior_id: UUID,
    bracelet_nova_id: UUID,
) -> tuple[Bracelet, Bracelet]:
    if bracelet_anterior_id == bracelet_nova_id:
        raise BraceletsTrocaIguais

    async with sessao.begin():
        pre_leitura = (
            await sessao.execute(
                select(Bracelet.status, Bracelet.child_id).where(
                    Bracelet.id == bracelet_anterior_id,
                ),
            )
        ).one_or_none()
        if pre_leitura is None:
            raise RecursoTrocaNaoEncontrado

        _, child_id_inicial = pre_leitura
        child = None
        if child_id_inicial is not None:
            child = await sessao.scalar(
                select(Child).where(Child.id == child_id_inicial),
            )

        pulseiras: dict[UUID, Bracelet] = {}
        for bracelet_id in sorted(
            (bracelet_anterior_id, bracelet_nova_id),
        ):
            bracelet = await sessao.scalar(
                select(Bracelet).where(Bracelet.id == bracelet_id),
            )
            if bracelet is not None:
                pulseiras[bracelet_id] = bracelet

        if (
            len(pulseiras) != 2
            or (child_id_inicial is not None and child is None)
        ):
            raise RecursoTrocaNaoEncontrado

        anterior = pulseiras[bracelet_anterior_id]
        nova = pulseiras[bracelet_nova_id]
        instante = datetime.now(UTC)

        anterior.desvincular(instante)
        if child is None:
            raise RecursoTrocaNaoEncontrado
        await sessao.flush()

        nova.ativar(child, instante)
        await sessao.flush()

    return anterior, nova
