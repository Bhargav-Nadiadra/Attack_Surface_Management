import uuid
from collections.abc import Sequence

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.enums import ScanStatus
from app.models.scan import Scan

ACTIVE_STATUSES = (ScanStatus.PENDING, ScanStatus.RUNNING)


class ScanRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def add(self, scan: Scan) -> Scan:
        self.session.add(scan)
        self.session.flush()
        return scan

    def get_active_for_domain(self, domain_id: uuid.UUID) -> Scan | None:
        return self.session.scalar(
            select(Scan).where(Scan.domain_id == domain_id, Scan.status.in_(ACTIVE_STATUSES))
        )

    def list_for_domain(
        self, domain_id: uuid.UUID, *, offset: int, limit: int
    ) -> tuple[Sequence[Scan], int]:
        total = (
            self.session.scalar(
                select(func.count()).select_from(Scan).where(Scan.domain_id == domain_id)
            )
            or 0
        )
        items = self.session.scalars(
            select(Scan)
            .where(Scan.domain_id == domain_id)
            .order_by(Scan.created_at.desc(), Scan.id.desc())
            .offset(offset)
            .limit(limit)
        ).all()
        return items, total
