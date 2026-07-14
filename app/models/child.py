from uuid import UUID, uuid4

from sqlalchemy import Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class Child(Base):
    __tablename__ = "children"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
