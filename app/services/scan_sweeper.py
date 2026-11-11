import logging
from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.models.domain import Domain
from app.models.enums import ScanStatus
from app.models.scan import Scan
from app.services.scan_dispatcher import ScanDispatcher

logger = logging.getLogger("app.worker")


@dataclass(frozen=True)
class SweepResult:
    requeued: int
    failed: int


class ScanSweeper:
    def __init__(
        self,
        session: Session,
        dispatcher: ScanDispatcher,
        *,
        stale_pending_minutes: int,
        stale_running_minutes: int,
    ) -> None:
        self.session = session
        self.dispatcher = dispatcher
        self.stale_pending = timedelta(minutes=stale_pending_minutes)
        self.stale_running = timedelta(minutes=stale_running_minutes)

    def sweep(self) -> SweepResult:
        failed = self._fail_stale_running()
        requeued = self._requeue_stale_pending()
        if failed or requeued:
            logger.info("scan.swept", extra={"requeued": requeued, "failed": failed})
        return SweepResult(requeued=requeued, failed=failed)

    def _fail_stale_running(self) -> int:
        minutes = int(self.stale_running.total_seconds() // 60)
        rows = self.session.execute(
            update(Scan)
            .where(
                Scan.status == ScanStatus.RUNNING,
                Scan.started_at < func.now() - self.stale_running,
            )
            .values(
                status=ScanStatus.FAILED,
                completed_at=func.now(),
                error_message=(
                    f"Scan did not finish within {minutes} minutes "
                    "(worker interrupted or timed out)."
                ),
            )
            .returning(Scan.id, Scan.domain_id)
        ).all()
        if rows:
            self.session.execute(
                update(Domain)
                .where(
                    Domain.id.in_([domain_id for _, domain_id in rows]),
                    Domain.status == ScanStatus.RUNNING,
                )
                .values(status=ScanStatus.FAILED)
            )
        self.session.commit()
        for scan_id, domain_id in rows:
            logger.warning(
                "scan.failed",
                extra={"scan_id": str(scan_id), "domain_id": str(domain_id), "reason": "stale"},
            )
        return len(rows)

    def _requeue_stale_pending(self) -> int:
        scan_ids = self.session.scalars(
            select(Scan.id)
            .where(
                Scan.status == ScanStatus.PENDING,
                Scan.created_at < func.now() - self.stale_pending,
            )
            .order_by(Scan.created_at)
        ).all()
        self.session.rollback()
        return sum(1 for scan_id in scan_ids if self.dispatcher.dispatch(scan_id))
