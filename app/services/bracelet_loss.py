from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Bracelet, Child


class RecursoPerdaNaoEncontrado(LookupError):
    def __init__(self) -> None:
        super().__init__("Recurso de perda não encontrado")


async def marcar_bracelet_como_perdida(
    sessao: AsyncSession,
    bracelet_id: UUID,
) -> Bracelet:
    async with sessao.begin():
        pre_leitura = (
            await sessao.execute(
                select(Bracelet.status, Bracelet.child_id).where(
                    Bracelet.id == bracelet_id,
                ),
            )
        ).one_or_none()
        if pre_leitura is None:
            raise RecursoPerdaNaoEncontrado

        _, child_id_inicial = pre_leitura
        if child_id_inicial is not None:
            child = await sessao.scalar(
                select(Child)
                .where(Child.id == child_id_inicial)
                .with_for_update(),
            )
            if child is None:
                raise RecursoPerdaNaoEncontrado

        bracelet = await sessao.scalar(
            select(Bracelet)
            .where(Bracelet.id == bracelet_id)
            .with_for_update(),
        )
        if bracelet is None:
            raise RecursoPerdaNaoEncontrado

        bracelet.marcar_como_perdida(datetime.now(UTC))
        await sessao.flush()

    return bracelet
