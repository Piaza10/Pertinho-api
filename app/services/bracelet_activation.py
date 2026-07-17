from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Bracelet, Child


class RecursoAtivacaoNaoEncontrado(LookupError):
    def __init__(self) -> None:
        super().__init__("Recurso de ativação não encontrado")


async def ativar_bracelet(
    sessao: AsyncSession,
    bracelet_id: UUID,
    child_id: UUID,
) -> Bracelet:
    async with sessao.begin():
        child = await sessao.scalar(
            select(Child).where(Child.id == child_id),
        )
        bracelet = await sessao.scalar(
            select(Bracelet).where(Bracelet.id == bracelet_id),
        )

        if child is None or bracelet is None:
            raise RecursoAtivacaoNaoEncontrado

        bracelet.ativar(child, datetime.now(UTC))
        await sessao.flush()

    return bracelet
