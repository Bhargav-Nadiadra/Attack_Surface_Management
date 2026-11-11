import uuid
from collections.abc import Callable, Iterator
from datetime import datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.api.deps import get_login_rate_limiter, get_scan_dispatcher
from app.core.database import engine, get_db
from app.core.security import create_access_token, hash_password
from app.main import app
from app.models import Asset, Domain, RecordType, Scan, ScanStatus, User, UserRole

DEFAULT_PASSWORD = "Str0ng!Pass"


def unique(prefix: str = "t") -> str:
    return f"{prefix}-{uuid.uuid4().hex[:10]}"


def auth_headers(user: User, role: UserRole | None = None) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(user.id, role or user.role)}"}


class UnlimitedRateLimiter:
    def __init__(self) -> None:
        self.checked: list[str] = []
        self.failures: list[str] = []

    def retry_after(self, key: str) -> int | None:
        self.checked.append(key)
        return None

    def record_failure(self, key: str) -> None:
        self.failures.append(key)


class RecordingDispatcher:
    def __init__(self) -> None:
        self.sent: list[uuid.UUID] = []
        self.succeed = True

    def dispatch(self, scan_id: uuid.UUID) -> bool:
        self.sent.append(scan_id)
        return self.succeed


@pytest.fixture(scope="session")
def default_password_hash() -> str:
    return hash_password(DEFAULT_PASSWORD)


@pytest.fixture
def db() -> Iterator[Session]:
    connection = engine.connect()
    transaction = connection.begin()
    session = Session(
        bind=connection,
        join_transaction_mode="create_savepoint",
        autoflush=False,
        expire_on_commit=False,
    )
    try:
        yield session
    finally:
        session.close()
        transaction.rollback()
        connection.close()


@pytest.fixture
def dispatcher() -> RecordingDispatcher:
    return RecordingDispatcher()


@pytest.fixture
def rate_limiter() -> UnlimitedRateLimiter:
    return UnlimitedRateLimiter()


@pytest.fixture
def client(
    db: Session, dispatcher: RecordingDispatcher, rate_limiter: UnlimitedRateLimiter
) -> Iterator[TestClient]:
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_scan_dispatcher] = lambda: dispatcher
    app.dependency_overrides[get_login_rate_limiter] = lambda: rate_limiter
    try:
        yield TestClient(app, raise_server_exceptions=False)
    finally:
        app.dependency_overrides.clear()


@pytest.fixture
def make_user(db: Session, default_password_hash: str) -> Callable[..., User]:
    def factory(
        role: UserRole = UserRole.VIEWER,
        *,
        email: str | None = None,
        password: str | None = None,
        is_active: bool = True,
    ) -> User:
        user = User(
            email=email or f"{unique(role.value.lower())}@example.com",
            password_hash=hash_password(password) if password else default_password_hash,
            full_name=f"{role.value.title()} User",
            role=role,
            is_active=is_active,
        )
        db.add(user)
        db.commit()
        return user

    return factory


@pytest.fixture
def admin(make_user: Callable[..., User]) -> User:
    return make_user(UserRole.ADMIN)


@pytest.fixture
def analyst(make_user: Callable[..., User]) -> User:
    return make_user(UserRole.ANALYST)


@pytest.fixture
def viewer(make_user: Callable[..., User]) -> User:
    return make_user(UserRole.VIEWER)


@pytest.fixture
def admin_headers(admin: User) -> dict[str, str]:
    return auth_headers(admin)


@pytest.fixture
def analyst_headers(analyst: User) -> dict[str, str]:
    return auth_headers(analyst)


@pytest.fixture
def viewer_headers(viewer: User) -> dict[str, str]:
    return auth_headers(viewer)


@pytest.fixture
def make_scan(db: Session) -> Callable[..., Scan]:
    def factory(
        domain: Domain,
        status: ScanStatus = ScanStatus.COMPLETED,
        *,
        created_at: datetime | None = None,
        started_at: datetime | None = None,
        completed_at: datetime | None = None,
        triggered_by: uuid.UUID | None = None,
    ) -> Scan:
        scan = Scan(
            domain_id=domain.id,
            status=status,
            triggered_by=triggered_by,
            started_at=started_at,
            completed_at=completed_at,
        )
        if created_at is not None:
            scan.created_at = created_at
        db.add(scan)
        db.commit()
        return scan

    return factory


@pytest.fixture
def make_domain(db: Session, admin: User, make_scan: Callable[..., Scan]) -> Callable[..., Domain]:
    def factory(
        name: str | None = None,
        status: ScanStatus = ScanStatus.COMPLETED,
        *,
        with_scan: bool = True,
    ) -> Domain:
        domain = Domain(name=name or f"{unique('d')}.com", status=status, created_by=admin.id)
        db.add(domain)
        db.commit()
        if with_scan:
            make_scan(domain, status, triggered_by=admin.id)
        return domain

    return factory


@pytest.fixture
def make_asset(db: Session) -> Callable[..., Asset]:
    def factory(scan: Scan, record_type: RecordType, value: str) -> Asset:
        asset = Asset(scan_id=scan.id, domain_id=scan.domain_id, type=record_type, value=value)
        db.add(asset)
        db.commit()
        return asset

    return factory
