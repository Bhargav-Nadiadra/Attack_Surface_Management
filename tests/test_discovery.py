import uuid
from contextlib import nullcontext
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import dns.exception
import dns.name
import dns.resolver
import pytest
from billiard.exceptions import SoftTimeLimitExceeded
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Asset, Domain, RecordType, Scan, ScanStatus
from app.services.discovery_service import DiscoveryService
from app.services.scan_sweeper import ScanSweeper
from app.workers import tasks
from app.workers.dns_resolver import (
    DnsLookupError,
    DnsPythonResolver,
    DomainNotFoundError,
)

A, AAAA, NS, MX = RecordType.A, RecordType.AAAA, RecordType.NS, RecordType.MX


class FakeResolver:
    def __init__(self, plan: dict) -> None:
        self.plan = plan
        self.calls: list[RecordType] = []

    def resolve(self, _domain: str, record_type: RecordType) -> list[str]:
        self.calls.append(record_type)
        result = self.plan.get(record_type, [])
        if isinstance(result, BaseException):
            raise result
        return result


@pytest.fixture
def pending(make_domain, db: Session):
    domain = make_domain(status=ScanStatus.PENDING)
    scan = db.scalar(select(Scan).where(Scan.domain_id == domain.id))
    return domain, scan


def _run(db: Session, scan_id: uuid.UUID, plan: dict) -> ScanStatus | None:
    return DiscoveryService(db, FakeResolver(plan)).run_scan(scan_id)


def _refresh(db: Session, domain: Domain, scan: Scan) -> tuple[Domain, Scan, list[Asset]]:
    db.expire_all()
    assets = db.scalars(select(Asset).where(Asset.scan_id == scan.id)).all()
    return db.get(Domain, domain.id), db.get(Scan, scan.id), assets


class TestRunScan:
    def test_completes_and_stores_assets(self, db, pending) -> None:
        domain, scan = pending
        plan = {
            A: ["1.1.1.1", "1.1.1.2"],
            AAAA: ["2606:4700::1"],
            NS: ["ns1.example.net"],
            MX: ["10 mail.example.com"],
        }

        assert _run(db, scan.id, plan) == ScanStatus.COMPLETED

        domain, scan, assets = _refresh(db, domain, scan)
        assert scan.status == domain.status == ScanStatus.COMPLETED
        assert scan.started_at is not None and scan.completed_at is not None
        assert scan.error_message is None
        assert {(a.type, a.value) for a in assets} == {
            (A, "1.1.1.1"),
            (A, "1.1.1.2"),
            (AAAA, "2606:4700::1"),
            (NS, "ns1.example.net"),
            (MX, "10 mail.example.com"),
        }
        assert all(a.domain_id == domain.id for a in assets)

    def test_queries_all_four_record_types(self, db, pending) -> None:
        resolver = FakeResolver({})
        DiscoveryService(db, resolver).run_scan(pending[1].id)
        assert resolver.calls == [A, AAAA, NS, MX]

    def test_one_type_timeout_still_completes(self, db, pending) -> None:
        domain, scan = pending
        plan = {A: ["1.1.1.1"], AAAA: DnsLookupError("AAAA lookup timed out after 5s.")}
        assert _run(db, scan.id, plan) == ScanStatus.COMPLETED
        _, scan, assets = _refresh(db, domain, scan)
        assert [a.value for a in assets] == ["1.1.1.1"]

    def test_all_types_failing_marks_failed(self, db, pending) -> None:
        domain, scan = pending
        plan = {rt: DnsLookupError(f"{rt.value} lookup timed out.") for rt in RecordType}
        assert _run(db, scan.id, plan) == ScanStatus.FAILED
        domain, scan, assets = _refresh(db, domain, scan)
        assert scan.status == domain.status == ScanStatus.FAILED
        assert scan.error_message.startswith("DNS resolution failed for every record type")
        assert assets == []

    def test_nxdomain_marks_failed(self, db, pending) -> None:
        domain, scan = pending
        plan = {A: DomainNotFoundError("Domain 'x' does not exist (NXDOMAIN).")}
        assert _run(db, scan.id, plan) == ScanStatus.FAILED
        domain, scan, _ = _refresh(db, domain, scan)
        assert scan.status == ScanStatus.FAILED
        assert "NXDOMAIN" in scan.error_message
        assert scan.completed_at is not None

    def test_unexpected_error_marks_failed_without_leaking(self, db, pending) -> None:
        domain, scan = pending
        assert _run(db, scan.id, {NS: RuntimeError("password=hunter2")}) == ScanStatus.FAILED
        domain, scan, _ = _refresh(db, domain, scan)
        assert scan.status == domain.status == ScanStatus.FAILED
        assert scan.error_message == "Unexpected error during discovery."

    def test_soft_time_limit_marks_failed(self, db, pending) -> None:
        domain, scan = pending
        assert _run(db, scan.id, {A: SoftTimeLimitExceeded()}) == ScanStatus.FAILED
        _, scan, _ = _refresh(db, domain, scan)
        assert scan.error_message == "Scan exceeded its time limit."

    @pytest.mark.parametrize(
        "status", [ScanStatus.RUNNING, ScanStatus.COMPLETED, ScanStatus.FAILED]
    )
    def test_skips_scan_that_is_not_pending(self, db, make_domain, status) -> None:
        domain = make_domain(status=status)
        scan = db.scalar(select(Scan).where(Scan.domain_id == domain.id))
        resolver = FakeResolver({A: ["9.9.9.9"]})

        assert DiscoveryService(db, resolver).run_scan(scan.id) is None
        assert resolver.calls == []
        _, scan, assets = _refresh(db, domain, scan)
        assert scan.status == status and assets == []

    def test_duplicate_delivery_is_noop(self, db, pending) -> None:
        domain, scan = pending
        _run(db, scan.id, {A: ["1.1.1.1"]})
        assert _run(db, scan.id, {A: ["2.2.2.2"]}) is None
        _, _, assets = _refresh(db, domain, scan)
        assert [a.value for a in assets] == ["1.1.1.1"]

    def test_unknown_scan_is_noop(self, db) -> None:
        assert _run(db, uuid.uuid4(), {}) is None

    def test_does_not_complete_scan_swept_mid_run(self, db, pending) -> None:
        domain, scan = pending

        class SweptDuringLookup(FakeResolver):
            def resolve(self, _domain: str, _record_type: RecordType) -> list[str]:
                db.get(Scan, scan.id).status = ScanStatus.FAILED
                db.commit()
                return ["1.1.1.1"]

        assert DiscoveryService(db, SweptDuringLookup({})).run_scan(scan.id) is None
        _, scan, assets = _refresh(db, domain, scan)
        assert scan.status == ScanStatus.FAILED
        assert assets == []


class TestSweeper:
    def _sweep(self, db, dispatcher):
        return ScanSweeper(
            db, dispatcher, stale_pending_minutes=2, stale_running_minutes=10
        ).sweep()

    def test_fails_stale_running_and_requeues_stale_pending(
        self, db, make_domain, make_scan, dispatcher
    ) -> None:
        old = datetime.now(UTC) - timedelta(minutes=30)
        stale_running = make_scan(
            make_domain(with_scan=False, status=ScanStatus.RUNNING),
            ScanStatus.RUNNING,
            started_at=old,
            created_at=old,
        )
        fresh_running = make_scan(
            make_domain(with_scan=False, status=ScanStatus.RUNNING),
            ScanStatus.RUNNING,
            started_at=datetime.now(UTC),
        )
        stale_pending = make_scan(
            make_domain(with_scan=False, status=ScanStatus.PENDING),
            ScanStatus.PENDING,
            created_at=old,
        )
        fresh_pending = make_scan(
            make_domain(with_scan=False, status=ScanStatus.PENDING), ScanStatus.PENDING
        )

        result = self._sweep(db, dispatcher)

        assert result.failed >= 1 and result.requeued >= 1
        db.expire_all()
        failed = db.get(Scan, stale_running.id)
        assert failed.status == ScanStatus.FAILED
        assert "did not finish within 10 minutes" in failed.error_message
        assert db.get(Domain, failed.domain_id).status == ScanStatus.FAILED
        assert db.get(Scan, fresh_running.id).status == ScanStatus.RUNNING
        assert stale_pending.id in dispatcher.sent
        assert fresh_pending.id not in dispatcher.sent


class TestCeleryTasks:
    def test_run_discovery_task_uses_service(self, db, pending, monkeypatch) -> None:
        domain, scan = pending
        monkeypatch.setattr(tasks, "SessionLocal", lambda: nullcontext(db))
        monkeypatch.setattr(tasks, "DnsPythonResolver", lambda _: FakeResolver({A: ["3.3.3.3"]}))

        assert tasks.run_discovery_scan.run(str(scan.id)) == "COMPLETED"
        _, scan, assets = _refresh(db, domain, scan)
        assert [a.value for a in assets] == ["3.3.3.3"]

    def test_run_discovery_task_rejects_bad_id(self) -> None:
        assert tasks.run_discovery_scan.run("not-a-uuid") is None

    def test_sweep_task(self, db, make_domain, make_scan, monkeypatch, dispatcher) -> None:
        old = datetime.now(UTC) - timedelta(hours=1)
        make_scan(
            make_domain(with_scan=False, status=ScanStatus.PENDING),
            ScanStatus.PENDING,
            created_at=old,
        )
        monkeypatch.setattr(tasks, "SessionLocal", lambda: nullcontext(db))
        monkeypatch.setattr(tasks, "CeleryScanDispatcher", lambda: dispatcher)

        result = tasks.sweep_stale_scans.run()

        assert result["requeued"] == len(dispatcher.sent) >= 1


class TestDnsPythonResolver:
    @pytest.fixture
    def resolver(self) -> DnsPythonResolver:
        return DnsPythonResolver(timeout_seconds=2)

    def _answer(self, monkeypatch, resolver, result) -> None:
        def fake_resolve(*_, **__):
            if isinstance(result, BaseException):
                raise result
            return result

        monkeypatch.setattr(resolver._resolver, "resolve", fake_resolve)

    def test_normalizes_records(self, monkeypatch, resolver) -> None:
        name = dns.name.from_text
        cases = {
            A: (
                [SimpleNamespace(address="1.2.3.4"), SimpleNamespace(address="1.2.3.4")],
                ["1.2.3.4"],
            ),
            AAAA: ([SimpleNamespace(address="::1")], ["::1"]),
            NS: ([SimpleNamespace(target=name("NS1.Example.NET."))], ["ns1.example.net"]),
            MX: (
                [
                    SimpleNamespace(preference=10, exchange=name("mail.example.com.")),
                    SimpleNamespace(preference=0, exchange=dns.name.root),
                ],
                ["10 mail.example.com"],
            ),
        }
        for record_type, (answer, expected) in cases.items():
            self._answer(monkeypatch, resolver, answer)
            assert resolver.resolve("example.com", record_type) == expected

    @pytest.mark.parametrize(
        ("error", "expected"),
        [
            (dns.resolver.NXDOMAIN(), DomainNotFoundError),
            (dns.exception.Timeout(), DnsLookupError),
            (dns.resolver.NoNameservers(), DnsLookupError),
            (dns.exception.DNSException("boom"), DnsLookupError),
        ],
    )
    def test_maps_errors(self, monkeypatch, resolver, error, expected) -> None:
        self._answer(monkeypatch, resolver, error)
        with pytest.raises(expected):
            resolver.resolve("example.com", A)

    def test_no_answer_is_empty(self, monkeypatch, resolver) -> None:
        self._answer(monkeypatch, resolver, dns.resolver.NoAnswer())
        assert resolver.resolve("example.com", AAAA) == []
