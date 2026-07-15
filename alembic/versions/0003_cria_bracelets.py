from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | Sequence[str] | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "bracelets",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("public_token", sa.String(length=43), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "ESTOQUE",
                "ATIVA",
                "DESVINCULADA",
                "PERDIDA",
                name="bracelet_status",
                native_enum=False,
                create_constraint=True,
            ),
            server_default="ESTOQUE",
            nullable=False,
        ),
        sa.Column("child_id", sa.Uuid(), nullable=True),
        sa.Column(
            "activated_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "revoked_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.CheckConstraint(
            "(status = 'ESTOQUE' AND child_id IS NULL "
            "AND activated_at IS NULL AND revoked_at IS NULL) OR "
            "(status = 'ATIVA' AND child_id IS NOT NULL "
            "AND activated_at IS NOT NULL AND revoked_at IS NULL) OR "
            "(status IN ('DESVINCULADA', 'PERDIDA') AND child_id IS NULL "
            "AND activated_at IS NOT NULL AND revoked_at IS NOT NULL)",
            name="ck_bracelets_estado_coerente",
        ),
        sa.ForeignKeyConstraint(
            ["child_id"],
            ["children.id"],
            name="fk_bracelets_child_id_children",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_bracelets"),
        sa.UniqueConstraint(
            "child_id",
            name="uq_bracelets_child_id",
        ),
        sa.UniqueConstraint(
            "public_token",
            name="uq_bracelets_public_token",
        ),
    )


def downgrade() -> None:
    op.drop_table("bracelets")
