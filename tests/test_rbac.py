import pytest

from app.core.permissions import ROLE_PERMISSIONS, Permission
from app.models import UserRole
from tests.conftest import auth_headers, unique

ADMIN, ANALYST, VIEWER = UserRole.ADMIN, UserRole.ANALYST, UserRole.VIEWER

MATRIX = [
    ("POST", "/auth/register", {ADMIN: 201, ANALYST: 403, VIEWER: 403}),
    ("GET", "/domains", {ADMIN: 200, ANALYST: 200, VIEWER: 200}),
    ("POST", "/domains", {ADMIN: 201, ANALYST: 201, VIEWER: 403}),
    ("GET", "/domains/{id}", {ADMIN: 200, ANALYST: 200, VIEWER: 200}),
    ("DELETE", "/domains/{id}", {ADMIN: 204, ANALYST: 403, VIEWER: 403}),
    ("POST", "/domains/{id}/scan", {ADMIN: 202, ANALYST: 202, VIEWER: 403}),
    ("GET", "/domains/{id}/scans", {ADMIN: 200, ANALYST: 200, VIEWER: 200}),
    ("GET", "/assets", {ADMIN: 200, ANALYST: 200, VIEWER: 200}),
]

CASES = [
    pytest.param(method, path, role, expected, id=f"{method} {path} as {role.value}")
    for method, path, expectations in MATRIX
    for role, expected in expectations.items()
]


def _body(method: str, path: str) -> dict | None:
    if path == "/auth/register":
        return {
            "email": f"{unique('rbac')}@example.com",
            "password": "Str0ng!Pass",
            "full_name": "RBAC User",
            "role": "VIEWER",
        }
    if method == "POST" and path == "/domains":
        return {"domain": f"{unique('rbac')}.com"}
    return None


@pytest.mark.parametrize(("method", "path", "role", "expected"), CASES)
def test_rbac_matrix(client, make_user, make_domain, method, path, role, expected) -> None:
    user = make_user(role)
    domain = make_domain()

    response = client.request(
        method,
        path.format(id=domain.id),
        headers=auth_headers(user),
        json=_body(method, path),
    )

    assert response.status_code == expected, response.text
    if expected == 403:
        assert response.json()["error"]["code"] == "permission_denied"


@pytest.mark.parametrize(("method", "path"), [(m, p) for m, p, _ in MATRIX])
def test_protected_endpoints_require_token(client, make_domain, method, path) -> None:
    domain = make_domain()
    response = client.request(method, path.format(id=domain.id), json=_body(method, path))
    assert response.status_code == 401


def test_public_endpoints_need_no_token(client) -> None:
    assert client.get("/health").status_code == 200
    login = client.post("/auth/login", json={"email": "x@example.com", "password": "Wr0ng!pass"})
    assert login.status_code == 401
    assert login.json()["error"]["code"] == "invalid_credentials"


def test_permission_map_matches_spec() -> None:
    everyone = {ADMIN, ANALYST, VIEWER}
    expected = {
        Permission.USER_REGISTER: {ADMIN},
        Permission.DOMAIN_READ: everyone,
        Permission.DOMAIN_CREATE: {ADMIN, ANALYST},
        Permission.DOMAIN_DELETE: {ADMIN},
        Permission.SCAN_TRIGGER: {ADMIN, ANALYST},
        Permission.SCAN_READ: everyone,
        Permission.ASSET_READ: everyone,
    }
    assert expected == ROLE_PERMISSIONS
