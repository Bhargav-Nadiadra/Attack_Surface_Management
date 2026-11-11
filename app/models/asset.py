from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import Enum, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, CreatedAtMixin, UUIDPrimaryKeyMixin
from app.models.enums import RecordType

if TYPE_CHECKING:
    from app.models.domain import Domain
    from app.models.scan import Scan


class Asset(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "assets"
    __table_args__ = (
        Index("ix_assets_domain_id_type", "domain_id", "type"),
        UniqueConstraint("scan_id", "type", "value"),
    )

    scan_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("scans.id", ondelete="CASCADE"), nullable=False, index=True
    )
    domain_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("domains.id", ondelete="CASCADE"), nullable=False
    )
    type: Mapped[RecordType] = mapped_column(Enum(RecordType, name="record_type"), nullable=False)
    value: Mapped[str] = mapped_column(String(512), nullable=False)

    scan: Mapped[Scan] = relationship(back_populates="assets")
    domain: Mapped[Domain] = relationship(back_populates="assets")

    def __repr__(self) -> str:
        return f"<Asset {self.type} {self.value}>"
