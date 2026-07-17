from datetime import datetime
from enum import StrEnum
from secrets import token_urlsafe
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, DateTime, Enum, ForeignKey, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.child import Child


class BraceletStatus(StrEnum):
    ESTOQUE = "ESTOQUE"
    ATIVA = "ATIVA"
    DESVINCULADA = "DESVINCULADA"
    PERDIDA = "PERDIDA"


class TransicaoBraceletInvalida(ValueError):
    def __init__(
        self,
        origem: BraceletStatus,
        destino: BraceletStatus,
    ) -> None:
        self.origem = origem
        self.destino = destino
        super().__init__(
            f"Transição de {origem.value} para {destino.value} não permitida",
        )


def gerar_token_publico() -> str:
    return token_urlsafe(32)


class Bracelet(Base):
    __tablename__ = "bracelets"
    __table_args__ = (
        CheckConstraint(
            "(status = 'ESTOQUE' AND child_id IS NULL "
            "AND activated_at IS NULL AND revoked_at IS NULL) OR "
            "(status = 'ATIVA' AND child_id IS NOT NULL "
            "AND activated_at IS NOT NULL AND revoked_at IS NULL) OR "
            "(status IN ('DESVINCULADA', 'PERDIDA') AND child_id IS NULL "
            "AND activated_at IS NOT NULL AND revoked_at IS NOT NULL)",
            name="ck_bracelets_estado_coerente",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    public_token: Mapped[str] = mapped_column(
        String(43),
        unique=True,
        default=gerar_token_publico,
    )
    status: Mapped[BraceletStatus] = mapped_column(
        Enum(
            BraceletStatus,
            name="bracelet_status",
            native_enum=False,
            create_constraint=True,
            validate_strings=True,
        ),
        default=BraceletStatus.ESTOQUE,
        server_default=BraceletStatus.ESTOQUE.value,
    )
    child_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("children.id"),
        unique=True,
    )
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    child: Mapped[Child | None] = relationship()

    def _validar_transicao(
        self,
        origem_esperada: BraceletStatus,
        destino: BraceletStatus,
    ) -> None:
        if self.status is not origem_esperada:
            raise TransicaoBraceletInvalida(self.status, destino)

    def ativar(self, child: Child, instante: datetime) -> None:
        self._validar_transicao(
            BraceletStatus.ESTOQUE,
            BraceletStatus.ATIVA,
        )
        if not isinstance(child, Child):
            raise TypeError("child deve ser uma instância de Child")

        self.status = BraceletStatus.ATIVA
        self.child = child
        self.activated_at = instante
        self.revoked_at = None

    def desvincular(self, instante: datetime) -> None:
        self._validar_transicao(
            BraceletStatus.ATIVA,
            BraceletStatus.DESVINCULADA,
        )

        self.status = BraceletStatus.DESVINCULADA
        self.child = None
        self.child_id = None
        self.revoked_at = instante

    def marcar_como_perdida(self, instante: datetime) -> None:
        self._validar_transicao(
            BraceletStatus.ATIVA,
            BraceletStatus.PERDIDA,
        )

        self.status = BraceletStatus.PERDIDA
        self.child = None
        self.child_id = None
        self.revoked_at = instante
