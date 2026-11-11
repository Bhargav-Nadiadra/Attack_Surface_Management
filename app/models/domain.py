from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import Enum, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.enums import ScanStatus

if TYPE_CHECKING:
    from app.models.asset import Asset
    from app.models.scan import Scan
    from app.models.user import User


class Domain(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "domains"

    name: Mapped[str] = mapped_column(String(253), unique=True, nullable=False)
    status: Mapped[ScanStatus] = mapped_column(
        Enum(ScanStatus, name="scan_status"), nullable=False, default=ScanStatus.PENDING
    )
    created_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)

    creator: Mapped[User] = relationship()
    scans: Mapped[list[Scan]] = relationship(
        back_populates="domain", cascade="all, delete-orphan", passive_deletes=True
    )
    assets: Mapped[list[Asset]] = relationship(
        back_populates="domain", cascade="all, delete-orphan", passive_deletes=True
    )

    def __repr__(self) -> str:
        return f"<Domain {self.name} ({self.status})>"
