from sqlalchemy.exc import OperationalError

from app.core.database import get_db
from app.main import app


class _UnreachableSession:
    def execute(self, *_, **__):
        raise OperationalError("SELECT 1", {}, ConnectionRefusedError("connection refused"))


def test_health_ok(client) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "connected"}


def test_health_reports_unreachable_database(client) -> None:
    app.dependency_overrides[get_db] = lambda: _UnreachableSession()

    response = client.get("/health")

    assert response.status_code == 503
    assert response.json() == {"status": "degraded", "database": "unreachable"}
