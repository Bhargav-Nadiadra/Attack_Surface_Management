import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import AuditLog, Domain
from tests.conftest import DEFAULT_PASSWORD, unique


def _entries(db: Session, target_id: uuid.UUID) -> list[AuditLog]:
    return list(db.scalars(select(AuditLog).where(AuditLog.target_id == target_id)).all())


def test_user_registration_is_audited(client, db: Session, admin, admin_headers) -> None:
    email = f"{unique('audit')}@example.com"
    response = client.post(
        "/auth/register",
        headers=admin_headers,
        json={"email": email, "password": DEFAULT_PASSWORD, "full_name": "A", "role": "VIEWER"},
    )
    assert response.status_code == 201

    [entry] = _entries(db, uuid.UUID(response.json()["id"]))
    assert entry.action == "user.registered"
    assert entry.actor_id == admin.id
    assert entry.target_type == "user"
    assert entry.details == {"email": email, "role": "VIEWER"}
    assert DEFAULT_PASSWORD not in str(entry.details)


def test_domain_deletion_is_audited_and_outlives_the_domain(
    client, db: Session, admin, admin_headers, make_domain
) -> None:
    domain = make_domain()
    domain_id, name = domain.id, domain.name

    assert client.delete(f"/domains/{domain_id}", headers=admin_headers).status_code == 204

    db.expire_all()
    assert db.get(Domain, domain_id) is None
    [entry] = _entries(db, domain_id)
    assert (entry.action, entry.actor_id, entry.target_type, entry.details) == (
        "domain.deleted",
        admin.id,
        "domain",
        {"domain": name},
    )


def test_failed_actions_are_not_audited(client, db: Session, admin_headers, viewer) -> None:
    before = db.scalars(select(AuditLog)).all()

    duplicate = client.post(
        "/auth/register",
        headers=admin_headers,
        json={
            "email": viewer.email,
            "password": DEFAULT_PASSWORD,
            "full_name": "Dup",
            "role": "VIEWER",
        },
    )
    missing = client.delete(f"/domains/{uuid.uuid4()}", headers=admin_headers)

    assert (duplicate.status_code, missing.status_code) == (409, 404)
    assert db.scalars(select(AuditLog)).all() == before
