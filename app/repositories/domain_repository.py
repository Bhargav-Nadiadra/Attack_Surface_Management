import uuid
from collections.abc import Sequence

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.domain import Domain
from app.models.enums import ScanStatus


def _escape_like(term: str) -> str:
    return term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


class DomainRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get(self, domain_id: uuid.UUID) -> Domain | None:
        return self.session.get(Domain, domain_id)

    def get_by_name(self, name: str) -> Domain | None:
        return self.session.scalar(select(Domain).where(Domain.name == name))

    def add(self, domain: Domain) -> Domain:
        self.session.add(domain)
        self.session.flush()
        return domain

    def delete(self, domain: Domain) -> None:
        self.session.delete(domain)
        self.session.flush()

    def list(
        self,
        *,
        status: ScanStatus | None,
        search: str | None,
        offset: int,
        limit: int,
    ) -> tuple[Sequence[Domain], int]:
        query = select(Domain)
        if status is not None:
            query = query.where(Domain.status == status)
        if search:
            query = query.where(Domain.name.ilike(f"%{_escape_like(search)}%", escape="\\"))

        total = self.session.scalar(select(func.count()).select_from(query.subquery())) or 0
        items = self.session.scalars(
            query.order_by(Domain.created_at.desc(), Domain.id.desc()).offset(offset).limit(limit)
        ).all()
        return items, total
