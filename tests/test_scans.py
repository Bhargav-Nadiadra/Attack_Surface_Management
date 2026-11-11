import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.orm import Session

from app.models import Domain, ScanStatus
from app.repositories.scan_repository import ScanRepository


class TestTriggerScan:
    def test_manual_trigger_returns_202(
        self, client, db: Session, analyst, analyst_headers, make_domain, dispatcher
    ) -> None:
        domain = make_domain(status=ScanStatus.COMPLETED)

        response = client.post(f"/domains/{domain.id}/scan", headers=analyst_headers)

        assert response.status_code == 202
        body = response.json()
        assert body["status"] == "PENDING"
        scan_id = uuid.UUID(body["scan_id"])
        assert dispatcher.sent == [scan_id]
        db.expire_all()
        assert db.get(Domain, domain.id).status == ScanStatus.PENDING

    @pytest.mark.parametrize("active", [ScanStatus.PENDING, ScanStatus.RUNNING])
    def test_conflict_when_scan_active(
        self, client, admin_headers, make_domain, dispatcher, active
    ) -> None:
        domain = make_domain(status=active)
        response = client.post(f"/domains/{domain.id}/scan", headers=admin_headers)
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "scan_in_progress"
        assert dispatcher.sent == []

    def test_database_index_blocks_race(
        self, client, admin_headers, make_domain, dispatcher, monkeypatch
    ) -> None:
        domain = make_domain(status=ScanStatus.RUNNING)
        monkeypatch.setattr(ScanRepository, "get_active_for_domain", lambda self, _: None)

        response = client.post(f"/domains/{domain.id}/scan", headers=admin_headers)

        assert response.status_code == 409
        assert response.json()["error"]["code"] == "scan_in_progress"
        assert dispatcher.sent == []

    def test_unknown_domain_is_404(self, client, admin_headers) -> None:
        response = client.post(f"/domains/{uuid.uuid4()}/scan", headers=admin_headers)
        assert response.status_code == 404

    def test_malformed_id_is_400(self, client, admin_headers) -> None:
        assert client.post("/domains/abc/scan", headers=admin_headers).status_code == 400


class TestScanHistory:
    @pytest.fixture
    def history(self, make_domain, make_scan, admin):
        domain = make_domain(with_scan=False, status=ScanStatus.PENDING)
        base = datetime.now(UTC) - timedelta(days=1)
        statuses = [
            ScanStatus.COMPLETED,
            ScanStatus.FAILED,
            ScanStatus.COMPLETED,
            ScanStatus.PENDING,
        ]
        scans = [
            make_scan(domain, status, created_at=base + timedelta(minutes=i), triggered_by=admin.id)
            for i, status in enumerate(statuses)
        ]
        return domain, scans

    def test_newest_first(self, client, viewer_headers, history) -> None:
        domain, scans = history
        body = client.get(f"/domains/{domain.id}/scans", headers=viewer_headers).json()

        assert body["total"] == 4
        assert [item["scan_id"] for item in body["items"]] == [str(s.id) for s in reversed(scans)]
        assert set(body["items"][0]) == {
            "scan_id",
            "status",
            "triggered_by",
            "created_at",
            "started_at",
            "completed_at",
            "error_message",
        }

    def test_pagination(self, client, viewer_headers, history) -> None:
        domain, scans = history
        body = client.get(
            f"/domains/{domain.id}/scans", headers=viewer_headers, params={"limit": 1, "page": 4}
        ).json()
        assert body["total"] == 4
        assert [item["scan_id"] for item in body["items"]] == [str(scans[0].id)]

    def test_unknown_domain_is_404(self, client, viewer_headers) -> None:
        response = client.get(f"/domains/{uuid.uuid4()}/scans", headers=viewer_headers)
        assert response.status_code == 404
