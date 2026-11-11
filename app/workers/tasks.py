import logging
import uuid

from app.core.config import settings
from app.core.database import SessionLocal
from app.services.discovery_service import DiscoveryService
from app.services.scan_dispatcher import CeleryScanDispatcher
from app.services.scan_sweeper import ScanSweeper
from app.workers.celery_app import RUN_DISCOVERY_TASK, SWEEP_STALE_TASK, celery_app
from app.workers.dns_resolver import DnsPythonResolver

logger = logging.getLogger("app.worker")


@celery_app.task(
    name=RUN_DISCOVERY_TASK,
    acks_late=True,
    soft_time_limit=settings.SCAN_SOFT_TIME_LIMIT_SECONDS,
    time_limit=settings.SCAN_TIME_LIMIT_SECONDS,
)
def run_discovery_scan(scan_id: str) -> str | None:
    try:
        parsed_id = uuid.UUID(scan_id)
    except ValueError:
        logger.error("scan.invalid_id", extra={"scan_id": scan_id})
        return None

    with SessionLocal() as session:
        resolver = DnsPythonResolver(settings.DNS_TIMEOUT_SECONDS, settings.dns_nameservers)
        status = DiscoveryService(session, resolver).run_scan(parsed_id)
    return status.value if status else None


@celery_app.task(name=SWEEP_STALE_TASK)
def sweep_stale_scans() -> dict[str, int]:
    with SessionLocal() as session:
        result = ScanSweeper(
            session,
            CeleryScanDispatcher(),
            stale_pending_minutes=settings.STALE_PENDING_MINUTES,
            stale_running_minutes=settings.STALE_RUNNING_MINUTES,
        ).sweep()
    return {"requeued": result.requeued, "failed": result.failed}
