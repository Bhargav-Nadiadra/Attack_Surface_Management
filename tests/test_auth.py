import uuid
from datetime import UTC, datetime, timedelta

import jwt
import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import create_access_token, verify_password
from app.models import User, UserRole
from app.repositories.user_repository import UserRepository
from app.services.auth_service import INVALID_CREDENTIALS, AuthService
from tests.conftest import DEFAULT_PASSWORD, auth_headers, unique


def _token(payload: dict, secret: str | None = None) -> str:
    return jwt.encode(
        payload,
        secret or settings.JWT_SECRET_KEY.get_secret_value(),
        algorithm=settings.JWT_ALGORITHM,
    )


def _register_body(**overrides: str) -> dict[str, str]:
    body = {
        "email": f"{unique('new')}@example.com",
        "password": DEFAULT_PASSWORD,
        "full_name": "New User",
        "role": "ANALYST",
    }
    body.update(overrides)
    return body


class TestLogin:
    def test_success_returns_bearer_token(self, client, make_user) -> None:
        user = make_user(UserRole.ANALYST)

        response = client.post(
            "/auth/login", json={"email": user.email.upper(), "password": DEFAULT_PASSWORD}
        )

        assert response.status_code == 200
        body = response.json()
        assert body["token_type"] == "bearer"
        assert body["expires_in"] == settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60
        claims = jwt.decode(
            body["access_token"],
            settings.JWT_SECRET_KEY.get_secret_value(),
            algorithms=[settings.JWT_ALGORITHM],
        )
        assert claims["sub"] == str(user.id)
        assert claims["role"] == "ANALYST"
        assert claims["type"] == "access"

    def test_wrong_password(self, client, make_user) -> None:
        user = make_user()
        response = client.post("/auth/login", json={"email": user.email, "password": "Wr0ng!Pass"})
        assert response.status_code == 401
        assert response.json()["error"] == {
            "code": "invalid_credentials",
            "message": INVALID_CREDENTIALS,
            "details": [],
        }

    def test_unknown_email_gives_identical_error(self, client) -> None:
        response = client.post(
            "/auth/login",
            json={"email": f"{unique('ghost')}@example.com", "password": DEFAULT_PASSWORD},
        )
        assert response.status_code == 401
        assert response.json()["error"]["message"] == INVALID_CREDENTIALS

    def test_inactive_user_cannot_login(self, client, make_user) -> None:
        user = make_user(is_active=False)
        response = client.post(
            "/auth/login", json={"email": user.email, "password": DEFAULT_PASSWORD}
        )
        assert response.status_code == 401
        assert response.json()["error"]["message"] == INVALID_CREDENTIALS

    def test_missing_fields_is_validation_error(self, client) -> None:
        response = client.post("/auth/login", json={"email": "a@example.com"})
        assert response.status_code == 400
        assert response.json()["error"]["details"][0]["field"] == "body.password"

    def test_password_is_never_echoed_in_errors(self, client) -> None:
        response = client.post("/auth/login", json={"email": "bad", "password": "S3cret!Value"})
        assert response.status_code == 400
        assert "S3cret!Value" not in response.text


class TestTokenValidation:
    @pytest.fixture
    def admin_payload(self, admin: User) -> dict:
        now = datetime.now(UTC)
        return {
            "sub": str(admin.id),
            "role": "ADMIN",
            "type": "access",
            "iat": now,
            "exp": now + timedelta(minutes=5),
        }

    def _call(self, client, headers: dict[str, str] | None = None):
        return client.get("/domains", headers=headers or {})

    def test_missing_token(self, client) -> None:
        response = self._call(client)
        assert response.status_code == 401
        assert response.json()["error"]["code"] == "not_authenticated"
        assert response.headers["www-authenticate"] == "Bearer"

    def test_garbage_token(self, client) -> None:
        response = self._call(client, {"Authorization": "Bearer not.a.jwt"})
        assert response.status_code == 401
        assert response.json()["error"]["code"] == "invalid_token"

    def test_non_bearer_scheme(self, client, admin_headers) -> None:
        token = admin_headers["Authorization"].split()[1]
        response = self._call(client, {"Authorization": f"Basic {token}"})
        assert response.status_code == 401

    def test_expired_token(self, client, admin_payload) -> None:
        admin_payload["iat"] = datetime.now(UTC) - timedelta(hours=2)
        admin_payload["exp"] = datetime.now(UTC) - timedelta(hours=1)
        response = self._call(client, {"Authorization": f"Bearer {_token(admin_payload)}"})
        assert response.status_code == 401
        assert response.json()["error"]["code"] == "token_expired"

    def test_wrong_signature(self, client, admin_payload) -> None:
        forged = _token(admin_payload, secret="not-the-real-secret-key-but-long-enough")
        response = self._call(client, {"Authorization": f"Bearer {forged}"})
        assert response.status_code == 401
        assert response.json()["error"]["code"] == "invalid_token"

    def test_wrong_token_type(self, client, admin_payload) -> None:
        admin_payload["type"] = "refresh"
        response = self._call(client, {"Authorization": f"Bearer {_token(admin_payload)}"})
        assert response.status_code == 401

    def test_missing_required_claim(self, client, admin_payload) -> None:
        del admin_payload["iat"]
        response = self._call(client, {"Authorization": f"Bearer {_token(admin_payload)}"})
        assert response.status_code == 401

    def test_non_uuid_subject(self, client, admin_payload) -> None:
        admin_payload["sub"] = "not-a-uuid"
        response = self._call(client, {"Authorization": f"Bearer {_token(admin_payload)}"})
        assert response.status_code == 401

    def test_token_for_unknown_user(self, client) -> None:
        token = create_access_token(uuid.uuid4(), UserRole.ADMIN)
        response = self._call(client, {"Authorization": f"Bearer {token}"})
        assert response.status_code == 401

    def test_token_of_deactivated_user(self, client, db: Session, admin: User) -> None:
        headers = auth_headers(admin)
        admin.is_active = False
        db.flush()
        assert self._call(client, headers).status_code == 401

    def test_role_comes_from_database_not_token(self, client, admin: User) -> None:
        headers = auth_headers(admin, role=UserRole.VIEWER)
        response = client.post("/auth/register", headers=headers, json=_register_body())
        assert response.status_code == 201


class TestRegister:
    def test_admin_registers_user(self, client, db: Session, admin_headers) -> None:
        email = f"{unique('Jane')}@Example.COM"
        response = client.post(
            "/auth/register",
            headers=admin_headers,
            json=_register_body(email=email, full_name="  Jane Analyst  "),
        )

        assert response.status_code == 201
        body = response.json()
        assert body["email"] == email.lower()
        assert body["full_name"] == "Jane Analyst"
        assert body["role"] == "ANALYST"
        assert body["is_active"] is True
        assert "password" not in body and "password_hash" not in body

        stored = UserRepository(db).get_by_email(email)
        assert stored is not None
        assert stored.password_hash != DEFAULT_PASSWORD
        assert verify_password(DEFAULT_PASSWORD, stored.password_hash)

    def test_registered_user_can_login(self, client, admin_headers) -> None:
        body = _register_body(role="VIEWER")
        client.post("/auth/register", headers=admin_headers, json=body)
        response = client.post(
            "/auth/login", json={"email": body["email"], "password": body["password"]}
        )
        assert response.status_code == 200

    def test_duplicate_email_case_insensitive(self, client, admin_headers, viewer: User) -> None:
        response = client.post(
            "/auth/register", headers=admin_headers, json=_register_body(email=viewer.email.upper())
        )
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "email_taken"

    @pytest.mark.parametrize(
        "overrides",
        [
            {"password": "weakpass"},
            {"password": "Aa1!" + "x" * 70},
            {"email": "not-an-email"},
            {"role": "ROOT"},
            {"full_name": "   "},
        ],
    )
    def test_invalid_payload_is_rejected(self, client, admin_headers, overrides) -> None:
        response = client.post(
            "/auth/register", headers=admin_headers, json=_register_body(**overrides)
        )
        assert response.status_code == 400
        assert response.json()["error"]["code"] == "validation_error"


class TestSeedFirstAdmin:
    @pytest.mark.usefixtures("admin")
    def test_skips_when_users_exist(self, db: Session) -> None:
        before = db.scalar(select(func.count()).select_from(User))
        AuthService(db).seed_first_admin(f"{unique('seed')}@example.com", DEFAULT_PASSWORD)
        assert db.scalar(select(func.count()).select_from(User)) == before

    def test_creates_admin_when_no_users(self, db: Session, monkeypatch) -> None:
        monkeypatch.setattr(UserRepository, "any_exist", lambda _self: False)
        email = f"{unique('Seed')}@Example.com"

        AuthService(db).seed_first_admin(email, DEFAULT_PASSWORD)

        seeded = UserRepository(db).get_by_email(email)
        assert seeded is not None
        assert seeded.email == email.lower()
        assert seeded.role == UserRole.ADMIN

    def test_rejects_weak_seed_password(self, db: Session, monkeypatch) -> None:
        monkeypatch.setattr(UserRepository, "any_exist", lambda _self: False)
        with pytest.raises(ValueError):
            AuthService(db).seed_first_admin(f"{unique('seed')}@example.com", "weak")
