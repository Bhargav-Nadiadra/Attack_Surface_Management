import logging
import uuid
from typing import Protocol

from app.workers.celery_app import RUN_DISCOVERY_TASK, celery_app

logger = logging.getLogger("app.scans")


class ScanDispatcher(Protocol):
    def dispatch(self, scan_id: uuid.UUID) -> bool: ...


class CeleryScanDispatcher:
    def dispatch(self, scan_id: uuid.UUID) -> bool:
        try:
            celery_app.send_task(RUN_DISCOVERY_TASK, args=[str(scan_id)], ignore_result=True)
        except Exception:
            logger.exception("scan.enqueue_failed", extra={"scan_id": str(scan_id)})
            return False
        logger.info("scan.queued", extra={"scan_id": str(scan_id)})
        return True
