import uuid
from collections.abc import Sequence

from sqlalchemy import Row, Select, func, select
from sqlalchemy.dialects.postgresql import distinct_on
from sqlalchemy.orm import Session

from app.models.asset import Asset
from app.models.domain import Domain
from app.models.enums import RecordType, ScanStatus
from app.models.scan import Scan


class AssetRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def list(
        self,
        *,
        domain_id: uuid.UUID | None,
        record_type: RecordType | None,
        latest_only: bool,
        offset: int,
        limit: int,
    ) -> tuple[Sequence[Row[tuple[Asset, str]]], int]:
        query: Select[tuple[Asset, str]] = select(Asset, Domain.name).join(
            Domain, Domain.id == Asset.domain_id
        )
        if domain_id is not None:
            query = query.where(Asset.domain_id == domain_id)
        if record_type is not None:
            query = query.where(Asset.type == record_type)
        if latest_only:
            query = query.where(Asset.scan_id.in_(self._latest_completed_scan_ids(domain_id)))

        total = self.session.scalar(select(func.count()).select_from(query.subquery())) or 0
        rows = self.session.execute(
            query.order_by(Asset.created_at.desc(), Domain.name, Asset.type, Asset.value)
            .offset(offset)
            .limit(limit)
        ).all()
        return rows, total

    @staticmethod
    def _latest_completed_scan_ids(domain_id: uuid.UUID | None) -> Select[tuple[uuid.UUID]]:
        latest = (
            select(Scan.id)
            .where(Scan.status == ScanStatus.COMPLETED)
            .ext(distinct_on(Scan.domain_id))
            .order_by(Scan.domain_id, Scan.completed_at.desc(), Scan.created_at.desc())
        )
        if domain_id is not None:
            latest = latest.where(Scan.domain_id == domain_id)
        return latest
