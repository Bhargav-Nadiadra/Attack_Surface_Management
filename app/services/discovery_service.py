import logging
import time
import uuid

from billiard.exceptions import SoftTimeLimitExceeded
from sqlalchemy import func, update
from sqlalchemy.orm import Session

from app.models.asset import Asset
from app.models.domain import Domain
from app.models.enums import RecordType, ScanStatus
from app.models.scan import Scan
from app.workers.dns_resolver import DnsLookupError, DnsResolver, DomainNotFoundError

logger = logging.getLogger("app.worker")

RECORD_TYPES: tuple[RecordType, ...] = (RecordType.A, RecordType.AAAA, RecordType.NS, RecordType.MX)
MAX_ERROR_LENGTH = 1000


class ScanFailedError(Exception):
    pass


class DiscoveryService:
    def __init__(self, session: Session, resolver: DnsResolver) -> None:
        self.session = session
        self.resolver = resolver

    def run_scan(self, scan_id: uuid.UUID) -> ScanStatus | None:
        claimed = self._claim(scan_id)
        if claimed is None:
            logger.info("scan.skipped", extra={"scan_id": str(scan_id), "reason": "not_pending"})
            return None

        domain_id, domain_name = claimed
        log_ctx = {"scan_id": str(scan_id), "domain_id": str(domain_id), "domain": domain_name}
        logger.info("scan.started", extra=log_ctx)
        started = time.perf_counter()

        try:
            records = self._discover(domain_name, log_ctx)
            counts = self._complete(scan_id, domain_id, records)
        except ScanFailedError as exc:
            self._fail(scan_id, domain_id, str(exc), log_ctx)
            return ScanStatus.FAILED
        except SoftTimeLimitExceeded:
            self._fail(scan_id, domain_id, "Scan exceeded its time limit.", log_ctx)
            return ScanStatus.FAILED
        except Exception:
            logger.exception("scan.error", extra=log_ctx)
            self._fail(scan_id, domain_id, "Unexpected error during discovery.", log_ctx)
            return ScanStatus.FAILED

        if counts is None:
            logger.warning("scan.abandoned", extra={**log_ctx, "reason": "no_longer_running"})
            return None

        logger.info(
            "scan.completed",
            extra={
                **log_ctx,
                "asset_counts": counts,
                "total_assets": sum(counts.values()),
                "duration_ms": round((time.perf_counter() - started) * 1000, 2),
            },
        )
        return ScanStatus.COMPLETED

    def _claim(self, scan_id: uuid.UUID) -> tuple[uuid.UUID, str] | None:
        domain_id = self.session.scalar(
            update(Scan)
            .where(Scan.id == scan_id, Scan.status == ScanStatus.PENDING)
            .values(status=ScanStatus.RUNNING, started_at=func.now())
            .returning(Scan.domain_id)
        )
        if domain_id is None:
            self.session.rollback()
            return None

        domain_name = self.session.scalar(
            update(Domain)
            .where(Domain.id == domain_id)
            .values(status=ScanStatus.RUNNING)
            .returning(Domain.name)
        )
        self.session.commit()
        if domain_name is None:
            return None
        return domain_id, domain_name

    def _discover(self, domain_name: str, log_ctx: dict[str, str]) -> dict[RecordType, list[str]]:
        records: dict[RecordType, list[str]] = {}
        failures: list[str] = []

        for record_type in RECORD_TYPES:
            try:
                records[record_type] = self.resolver.resolve(domain_name, record_type)
            except DomainNotFoundError as exc:
                raise ScanFailedError(str(exc)) from exc
            except DnsLookupError as exc:
                failures.append(str(exc))
                logger.warning(
                    "scan.record_lookup_failed",
                    extra={**log_ctx, "record_type": record_type.value, "error": str(exc)},
                )

        if not records:
            raise ScanFailedError(
                "DNS resolution failed for every record type: " + " ".join(failures)
            )
        return records

    def _complete(
        self, scan_id: uuid.UUID, domain_id: uuid.UUID, records: dict[RecordType, list[str]]
    ) -> dict[str, int] | None:
        completed = self.session.scalar(
            update(Scan)
            .where(Scan.id == scan_id, Scan.status == ScanStatus.RUNNING)
            .values(status=ScanStatus.COMPLETED, completed_at=func.now())
            .returning(Scan.id)
        )
        if completed is None:
            self.session.rollback()
            return None

        self.session.add_all(
            Asset(scan_id=scan_id, domain_id=domain_id, type=record_type, value=value)
            for record_type, values in records.items()
            for value in values
        )
        self.session.execute(
            update(Domain).where(Domain.id == domain_id).values(status=ScanStatus.COMPLETED)
        )
        self.session.commit()
        return {record_type.value: len(values) for record_type, values in records.items()}

    def _fail(
        self, scan_id: uuid.UUID, domain_id: uuid.UUID, message: str, log_ctx: dict[str, str]
    ) -> None:
        self.session.rollback()
        try:
            failed = self.session.scalar(
                update(Scan)
                .where(Scan.id == scan_id, Scan.status == ScanStatus.RUNNING)
                .values(
                    status=ScanStatus.FAILED,
                    completed_at=func.now(),
                    error_message=message[:MAX_ERROR_LENGTH],
                )
                .returning(Scan.id)
            )
            if failed is not None:
                self.session.execute(
                    update(Domain).where(Domain.id == domain_id).values(status=ScanStatus.FAILED)
                )
            self.session.commit()
        except Exception:
            self.session.rollback()
            logger.exception("scan.fail_update_error", extra=log_ctx)
            return
        logger.warning("scan.failed", extra={**log_ctx, "error": message})
