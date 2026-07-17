from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Bracelet, Child


class RecursoAtivacaoNaoEncontrado(LookupError):
    def __init__(self) -> None:
        super().__init__("Recurso de ativação não encontrado")


class ConflitoAtivacaoBracelet(ValueError):
    def __init__(self) -> None:
        super().__init__("Criança já possui pulseira vinculada")


async def ativar_bracelet(
    sessao: AsyncSession,
    bracelet_id: UUID,
    child_id: UUID,
) -> Bracelet:
    async with sessao.begin():
        child = await sessao.scalar(
            select(Child)
            .where(Child.id == child_id)
            .with_for_update(),
        )
        bracelet = await sessao.scalar(
            select(Bracelet)
            .where(Bracelet.id == bracelet_id)
            .with_for_update(),
        )

        if child is None or bracelet is None:
            raise RecursoAtivacaoNaoEncontrado

        outra_bracelet_id = await sessao.scalar(
            select(Bracelet.id).where(
                Bracelet.child_id == child_id,
                Bracelet.id != bracelet_id,
            ),
        )
        if outra_bracelet_id is not None:
            raise ConflitoAtivacaoBracelet

        bracelet.ativar(child, datetime.now(UTC))
        await sessao.flush()

    return bracelet
