import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.error_handlers import register_exception_handlers
from app.core.exceptions import ConflictError
from app.core.middleware import RequestLoggingMiddleware


@pytest.fixture
def error_client() -> TestClient:
    api = FastAPI()
    api.add_middleware(RequestLoggingMiddleware)
    register_exception_handlers(api)

    @api.get("/boom")
    def boom() -> None:
        raise RuntimeError("internal secret detail")

    @api.get("/conflict")
    def conflict() -> None:
        raise ConflictError("Already there.", code="dup")

    return TestClient(api, raise_server_exceptions=False)


def test_unhandled_error_hides_internals(error_client) -> None:
    response = error_client.get("/boom")
    assert response.status_code == 500
    assert response.json() == {
        "error": {
            "code": "internal_error",
            "message": "An unexpected error occurred.",
            "details": [],
        }
    }
    assert "secret" not in response.text
    assert response.headers["x-request-id"]


def test_app_error_shape(error_client) -> None:
    response = error_client.get("/conflict")
    assert response.status_code == 409
    assert response.json()["error"] == {"code": "dup", "message": "Already there.", "details": []}


def test_unknown_route_and_method(client) -> None:
    not_found = client.get("/does-not-exist")
    wrong_method = client.put("/health")
    assert not_found.status_code == 404
    assert not_found.json()["error"]["code"] == "not_found"
    assert wrong_method.status_code == 405
    assert wrong_method.json()["error"]["code"] == "method_not_allowed"


def test_request_id_is_generated(client) -> None:
    response = client.get("/health")
    assert len(response.headers["x-request-id"]) == 32


def test_valid_client_request_id_is_reused(client) -> None:
    response = client.get("/health", headers={"X-Request-ID": "trace-123"})
    assert response.headers["x-request-id"] == "trace-123"


def test_malformed_client_request_id_is_replaced(client) -> None:
    response = client.get("/health", headers={"X-Request-ID": "bad id <script>"})
    assert response.headers["x-request-id"] != "bad id <script>"
