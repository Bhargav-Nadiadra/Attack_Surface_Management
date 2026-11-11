import logging
import uuid

import pytest
from sqlalchemy import event
from sqlalchemy.orm import Session

from app.models import ScanStatus
from app.services import scan_dispatcher
from app.services.scan_dispatcher import CeleryScanDispatcher
from app.workers.celery_app import RUN_DISCOVERY_TASK
from tests.conftest import unique


@pytest.fixture
def timeline(db: Session, dispatcher) -> list[str]:
    events: list[str] = []
    event.listen(db, "after_commit", lambda _: events.append("commit"))
    original = dispatcher.dispatch

    def recording_dispatch(scan_id: uuid.UUID) -> bool:
        events.append("dispatch")
        return original(scan_id)

    dispatcher.dispatch = recording_dispatch
    return events


def test_domain_create_enqueues_once_after_commit(client, admin_headers, timeline) -> None:
    response = client.post("/domains", headers=admin_headers, json={"domain": f"{unique()}.com"})
    assert response.status_code == 201
    assert timeline.count("dispatch") == 1
    assert timeline[-2:] == ["commit", "dispatch"]


def test_manual_trigger_enqueues_once_after_commit(
    client, admin_headers, make_domain, timeline
) -> None:
    domain = make_domain(status=ScanStatus.FAILED)
    response = client.post(f"/domains/{domain.id}/scan", headers=admin_headers)
    assert response.status_code == 202
    assert timeline.count("dispatch") == 1
    assert timeline[-2:] == ["commit", "dispatch"]


def test_enqueue_failure_still_accepts_request(
    client, admin_headers, make_domain, dispatcher
) -> None:
    dispatcher.succeed = False
    domain = make_domain(status=ScanStatus.COMPLETED)

    created = client.post("/domains", headers=admin_headers, json={"domain": f"{unique()}.com"})
    triggered = client.post(f"/domains/{domain.id}/scan", headers=admin_headers)

    assert created.status_code == 201
    assert triggered.status_code == 202
    assert triggered.json()["status"] == "PENDING"


def test_celery_dispatcher_sends_named_task(monkeypatch) -> None:
    calls = []
    monkeypatch.setattr(
        scan_dispatcher.celery_app,
        "send_task",
        lambda *args, **kwargs: calls.append((args, kwargs)),
    )
    scan_id = uuid.uuid4()

    assert CeleryScanDispatcher().dispatch(scan_id) is True
    assert calls == [((RUN_DISCOVERY_TASK,), {"args": [str(scan_id)], "ignore_result": True})]


def test_celery_dispatcher_swallows_broker_errors(monkeypatch, caplog) -> None:
    def broken(*_, **__):
        raise ConnectionError("redis down")

    monkeypatch.setattr(scan_dispatcher.celery_app, "send_task", broken)

    with caplog.at_level(logging.ERROR, logger="app.scans"):
        assert CeleryScanDispatcher().dispatch(uuid.uuid4()) is False
    assert any(record.getMessage() == "scan.enqueue_failed" for record in caplog.records)
