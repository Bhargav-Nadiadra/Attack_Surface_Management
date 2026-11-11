import uuid

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Asset, Domain, RecordType, Scan, ScanStatus
from tests.conftest import unique


class TestCreateDomain:
    def test_creates_domain_with_pending_scan(
        self, client, db: Session, analyst, analyst_headers, dispatcher
    ) -> None:
        name = f"{unique('new')}.com"

        response = client.post("/domains", headers=analyst_headers, json={"domain": name})

        assert response.status_code == 201
        body = response.json()
        assert body["name"] == name
        assert body["status"] == "PENDING"

        scans = db.scalars(select(Scan).where(Scan.domain_id == uuid.UUID(body["id"]))).all()
        assert len(scans) == 1
        assert scans[0].status == ScanStatus.PENDING
        assert scans[0].triggered_by == analyst.id
        assert dispatcher.sent == [scans[0].id]

    def test_normalizes_case_and_trailing_dot(self, client, admin_headers) -> None:
        tag = unique("upper")
        response = client.post(
            "/domains", headers=admin_headers, json={"domain": f"  {tag.upper()}.COM. "}
        )
        assert response.status_code == 201
        assert response.json()["name"] == f"{tag}.com"

    def test_duplicate_is_rejected_case_insensitively(
        self, client, admin_headers, make_domain, dispatcher
    ) -> None:
        domain = make_domain()
        response = client.post(
            "/domains", headers=admin_headers, json={"domain": domain.name.upper()}
        )
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "domain_exists"
        assert dispatcher.sent == []

    @pytest.mark.parametrize(
        "value",
        ["https://example.com", "1.2.3.4", "-bad-.com", "localhost", "*.example.com", "a" * 300],
    )
    def test_invalid_fqdn_is_rejected(self, client, admin_headers, value) -> None:
        response = client.post("/domains", headers=admin_headers, json={"domain": value})
        assert response.status_code == 400
        assert response.json()["error"]["details"][0]["field"] == "body.domain"

    def test_missing_body_is_rejected(self, client, admin_headers) -> None:
        assert client.post("/domains", headers=admin_headers).status_code == 400


class TestGetDomain:
    def test_returns_domain(self, client, viewer_headers, make_domain) -> None:
        domain = make_domain()
        response = client.get(f"/domains/{domain.id}", headers=viewer_headers)
        assert response.status_code == 200
        assert response.json()["name"] == domain.name
        assert response.json()["status"] == "COMPLETED"

    def test_unknown_id_is_404(self, client, viewer_headers) -> None:
        response = client.get(f"/domains/{uuid.uuid4()}", headers=viewer_headers)
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "domain_not_found"

    def test_malformed_id_is_400(self, client, viewer_headers) -> None:
        assert client.get("/domains/not-a-uuid", headers=viewer_headers).status_code == 400


class TestDeleteDomain:
    def test_delete_cascades_to_scans_and_assets(
        self, client, db: Session, admin_headers, make_domain, make_scan, make_asset
    ) -> None:
        domain = make_domain()
        scan = make_scan(domain)
        make_asset(scan, RecordType.A, "1.2.3.4")

        response = client.delete(f"/domains/{domain.id}", headers=admin_headers)

        assert response.status_code == 204
        assert response.content == b""
        db.expire_all()
        assert db.get(Domain, domain.id) is None
        for model in (Scan, Asset):
            count = db.scalar(
                select(func.count()).select_from(model).where(model.domain_id == domain.id)
            )
            assert count == 0

    def test_unknown_id_is_404(self, client, admin_headers) -> None:
        assert client.delete(f"/domains/{uuid.uuid4()}", headers=admin_headers).status_code == 404


class TestListDomains:
    @pytest.fixture
    def tagged(self, make_domain):
        tag = unique("list")
        statuses = [
            ScanStatus.COMPLETED,
            ScanStatus.COMPLETED,
            ScanStatus.FAILED,
            ScanStatus.PENDING,
        ]
        domains = [make_domain(f"{tag}-{i}.com", status) for i, status in enumerate(statuses)]
        return tag, domains

    def test_search_and_total(self, client, viewer_headers, tagged) -> None:
        tag, domains = tagged
        body = client.get("/domains", headers=viewer_headers, params={"search": tag}).json()
        assert body["total"] == 4
        assert body["page"] == 1
        assert body["limit"] == 20
        assert {item["name"] for item in body["items"]} == {d.name for d in domains}

    def test_search_is_case_insensitive_partial(self, client, viewer_headers, tagged) -> None:
        tag, _ = tagged
        body = client.get(
            "/domains", headers=viewer_headers, params={"search": f"{tag.upper()}-2"}
        ).json()
        assert [item["name"] for item in body["items"]] == [f"{tag}-2.com"]

    @pytest.mark.parametrize("term", ["%", "_", "\\"])
    def test_search_treats_wildcards_literally(self, client, viewer_headers, term) -> None:
        body = client.get("/domains", headers=viewer_headers, params={"search": term}).json()
        assert body["total"] == 0

    def test_status_filter(self, client, viewer_headers, tagged) -> None:
        tag, _ = tagged
        body = client.get(
            "/domains", headers=viewer_headers, params={"search": tag, "status": "COMPLETED"}
        ).json()
        assert body["total"] == 2
        assert {item["status"] for item in body["items"]} == {"COMPLETED"}

    def test_pagination(self, client, viewer_headers, tagged) -> None:
        tag, _ = tagged
        params = {"search": tag, "limit": 3}
        first = client.get("/domains", headers=viewer_headers, params=params).json()
        second = client.get("/domains", headers=viewer_headers, params={**params, "page": 2}).json()
        beyond = client.get("/domains", headers=viewer_headers, params={**params, "page": 5}).json()

        assert (len(first["items"]), len(second["items"]), beyond["items"]) == (3, 1, [])
        assert first["total"] == second["total"] == beyond["total"] == 4
        ids = [i["id"] for i in first["items"]] + [i["id"] for i in second["items"]]
        assert len(set(ids)) == 4

    @pytest.mark.parametrize(
        "params",
        [{"limit": 101}, {"limit": 0}, {"page": 0}, {"page": "x"}, {"status": "DONE"}],
    )
    def test_invalid_query_is_400(self, client, viewer_headers, params) -> None:
        response = client.get("/domains", headers=viewer_headers, params=params)
        assert response.status_code == 400
