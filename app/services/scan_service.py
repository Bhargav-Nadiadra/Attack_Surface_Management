import logging
import uuid
from collections.abc import Sequence

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.exceptions import ConflictError, NotFoundError
from app.models.domain import Domain
from app.models.enums import ScanStatus
from app.models.scan import Scan
from app.models.user import User
from app.repositories.domain_repository import DomainRepository
from app.repositories.scan_repository import ScanRepository
from app.services.scan_dispatcher import ScanDispatcher

logger = logging.getLogger("app.scans")


def scan_in_progress_error() -> ConflictError:
    return ConflictError(
        "A scan for this domain is already pending or running.", code="scan_in_progress"
    )


class ScanService:
    def __init__(self, session: Session, dispatcher: ScanDispatcher) -> None:
        self.session = session
        self.dispatcher = dispatcher
        self.domains = DomainRepository(session)
        self.scans = ScanRepository(session)

    def new_pending_scan(self, domain: Domain, triggered_by: uuid.UUID | None) -> Scan:
        scan = Scan(domain_id=domain.id, status=ScanStatus.PENDING, triggered_by=triggered_by)
        domain.status = ScanStatus.PENDING
        self.scans.add(scan)
        return scan

    def enqueue(self, scan: Scan) -> None:
        self.dispatcher.dispatch(scan.id)

    def trigger_scan(self, domain_id: uuid.UUID, user: User | None) -> Scan:
        domain = self._get_domain(domain_id)
        if self.scans.get_active_for_domain(domain.id):
            raise scan_in_progress_error()

        try:
            scan = self.new_pending_scan(domain, user.id if user else None)
            self.session.commit()
        except IntegrityError as exc:
            self.session.rollback()
            raise scan_in_progress_error() from exc

        logger.info(
            "scan.created",
            extra={
                "scan_id": str(scan.id),
                "domain_id": str(domain.id),
                "triggered_by": str(user.id) if user else None,
            },
        )
        self.enqueue(scan)
        return scan

    def list_for_domain(
        self, domain_id: uuid.UUID, *, offset: int, limit: int
    ) -> tuple[Sequence[Scan], int]:
        self._get_domain(domain_id)
        return self.scans.list_for_domain(domain_id, offset=offset, limit=limit)

    def _get_domain(self, domain_id: uuid.UUID) -> Domain:
        domain = self.domains.get(domain_id)
        if domain is None:
            raise NotFoundError("Domain not found.", code="domain_not_found")
        return domain
