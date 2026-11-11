from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Enum, ForeignKey, Index, Text, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, CreatedAtMixin, UUIDPrimaryKeyMixin
from app.models.enums import ScanStatus

if TYPE_CHECKING:
    from app.models.asset import Asset
    from app.models.domain import Domain
    from app.models.user import User


class Scan(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "scans"
    __table_args__ = (
        Index(
            "uq_scans_one_active_per_domain",
            "domain_id",
            unique=True,
            postgresql_where=text("status IN ('PENDING', 'RUNNING')"),
        ),
        Index("ix_scans_status_created_at", "status", "created_at"),
    )

    domain_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("domains.id", ondelete="CASCADE"), nullable=False, index=True
    )
    status: Mapped[ScanStatus] = mapped_column(
        Enum(ScanStatus, name="scan_status"), nullable=False, default=ScanStatus.PENDING
    )
    triggered_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_message: Mapped[str | None] = mapped_column(Text)

    domain: Mapped[Domain] = relationship(back_populates="scans")
    triggered_by_user: Mapped[User | None] = relationship()
    assets: Mapped[list[Asset]] = relationship(
        back_populates="scan", cascade="all, delete-orphan", passive_deletes=True
    )

    def __repr__(self) -> str:
        return f"<Scan {self.id} ({self.status})>"
