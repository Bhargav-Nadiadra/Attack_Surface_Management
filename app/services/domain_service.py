import logging
import uuid
from collections.abc import Sequence

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.exceptions import ConflictError, NotFoundError
from app.models.domain import Domain
from app.models.enums import ScanStatus
from app.models.user import User
from app.repositories.domain_repository import DomainRepository
from app.services.audit_service import AuditAction, record_audit
from app.services.scan_dispatcher import ScanDispatcher
from app.services.scan_service import ScanService

logger = logging.getLogger("app.domains")


class DomainService:
    def __init__(self, session: Session, dispatcher: ScanDispatcher) -> None:
        self.session = session
        self.dispatcher = dispatcher
        self.domains = DomainRepository(session)

    def create(self, name: str, user: User) -> Domain:
        if self.domains.get_by_name(name):
            raise self._duplicate(name)

        scans = ScanService(self.session, self.dispatcher)
        domain = Domain(name=name, status=ScanStatus.PENDING, created_by=user.id)
        try:
            self.domains.add(domain)
            scan = scans.new_pending_scan(domain, triggered_by=user.id)
            self.session.commit()
        except IntegrityError as exc:
            self.session.rollback()
            raise self._duplicate(name) from exc

        logger.info(
            "domain.created",
            extra={
                "domain_id": str(domain.id),
                "domain": domain.name,
                "scan_id": str(scan.id),
                "user_id": str(user.id),
            },
        )
        scans.enqueue(scan)
        return domain

    def get(self, domain_id: uuid.UUID) -> Domain:
        domain = self.domains.get(domain_id)
        if domain is None:
            raise NotFoundError("Domain not found.", code="domain_not_found")
        return domain

    def list(
        self, *, status: ScanStatus | None, search: str | None, offset: int, limit: int
    ) -> tuple[Sequence[Domain], int]:
        return self.domains.list(status=status, search=search, offset=offset, limit=limit)

    def delete(self, domain_id: uuid.UUID, user: User) -> None:
        domain = self.get(domain_id)
        record_audit(
            self.session,
            AuditAction.DOMAIN_DELETED,
            actor=user,
            target_type="domain",
            target_id=domain.id,
            details={"domain": domain.name},
        )
        self.domains.delete(domain)
        self.session.commit()
        logger.info(
            "domain.deleted",
            extra={"domain_id": str(domain_id), "domain": domain.name, "user_id": str(user.id)},
        )

    @staticmethod
    def _duplicate(name: str) -> ConflictError:
        return ConflictError(f"Domain '{name}' already exists.", code="domain_exists")
