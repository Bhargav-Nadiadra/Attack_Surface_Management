import uuid
from datetime import UTC, datetime, timedelta

import pytest

from app.models import RecordType, ScanStatus


@pytest.fixture
def inventory(make_domain, make_scan, make_asset):
    old = datetime.now(UTC) - timedelta(days=2)
    new = datetime.now(UTC) - timedelta(days=1)

    first = make_domain(with_scan=False)
    first_old = make_scan(first, created_at=old, completed_at=old)
    first_new = make_scan(first, created_at=new, completed_at=new)
    make_asset(first_old, RecordType.A, "10.0.0.1")
    make_asset(first_new, RecordType.A, "10.0.0.2")
    make_asset(first_new, RecordType.NS, "ns1.first.net")
    make_asset(first_new, RecordType.MX, "10 mail.first.net")

    second = make_domain(with_scan=False)
    second_scan = make_scan(second, created_at=new, completed_at=new)
    make_asset(second_scan, RecordType.A, "10.0.1.1")
    make_asset(second_scan, RecordType.AAAA, "2001:db8::1")

    failed = make_domain(with_scan=False, status=ScanStatus.FAILED)
    make_scan(failed, ScanStatus.FAILED)

    return {"first": first, "first_new": first_new, "second": second, "failed": failed}


def _list(client, headers, **params):
    response = client.get("/assets", headers=headers, params=params)
    assert response.status_code == 200, response.text
    return response.json()


def test_filter_by_domain(client, viewer_headers, inventory) -> None:
    body = _list(client, viewer_headers, domain_id=str(inventory["first"].id))
    assert body["total"] == 4
    assert {item["domain"] for item in body["items"]} == {inventory["first"].name}
    item = body["items"][0]
    assert set(item) == {"id", "domain", "domain_id", "scan_id", "type", "value", "created_at"}


def test_filter_by_domain_and_type(client, viewer_headers, inventory) -> None:
    body = _list(client, viewer_headers, domain_id=str(inventory["first"].id), type="A")
    assert body["total"] == 2
    assert sorted(item["value"] for item in body["items"]) == ["10.0.0.1", "10.0.0.2"]
    assert {item["type"] for item in body["items"]} == {"A"}


def test_filter_by_type_across_domains(client, viewer_headers, inventory) -> None:
    body = _list(client, viewer_headers, type="AAAA", limit=100)
    values = {(item["domain"], item["value"]) for item in body["items"]}
    assert (inventory["second"].name, "2001:db8::1") in values
    assert {item["type"] for item in body["items"]} == {"AAAA"}


def test_latest_only(client, viewer_headers, inventory) -> None:
    body = _list(client, viewer_headers, domain_id=str(inventory["first"].id), latest_only=True)
    assert body["total"] == 3
    assert {item["scan_id"] for item in body["items"]} == {str(inventory["first_new"].id)}


def test_domain_without_assets(client, viewer_headers, inventory) -> None:
    assert _list(client, viewer_headers, domain_id=str(inventory["failed"].id))["total"] == 0
    assert _list(client, viewer_headers, domain_id=str(uuid.uuid4()))["total"] == 0


def test_pagination(client, viewer_headers, inventory) -> None:
    domain_id = str(inventory["first"].id)
    first = _list(client, viewer_headers, domain_id=domain_id, limit=3)
    second = _list(client, viewer_headers, domain_id=domain_id, limit=3, page=2)
    assert (first["total"], len(first["items"]), len(second["items"])) == (4, 3, 1)
    assert not {i["id"] for i in first["items"]} & {i["id"] for i in second["items"]}


@pytest.mark.parametrize(
    "params",
    [{"type": "TXT"}, {"type": "a"}, {"domain_id": "abc"}, {"limit": 500}, {"latest_only": "x"}],
)
def test_invalid_query_is_400(client, viewer_headers, params) -> None:
    response = client.get("/assets", headers=viewer_headers, params=params)
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "validation_error"
