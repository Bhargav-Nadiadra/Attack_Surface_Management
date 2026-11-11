import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import bcrypt
import jwt

from app.core.config import settings
from app.core.exceptions import AuthenticationError
from app.models.enums import UserRole

_DUMMY_HASH = bcrypt.hashpw(b"timing-equalizer", bcrypt.gensalt()).decode()


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode(), password_hash.encode())
    except ValueError:
        return False


def burn_password_check(password: str) -> None:
    verify_password(password, _DUMMY_HASH)


def access_token_ttl_seconds() -> int:
    return settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60


def create_access_token(user_id: uuid.UUID, role: UserRole) -> str:
    now = datetime.now(UTC)
    payload = {
        "sub": str(user_id),
        "role": role.value,
        "type": "access",
        "iat": now,
        "exp": now + timedelta(seconds=access_token_ttl_seconds()),
    }
    return jwt.encode(
        payload, settings.JWT_SECRET_KEY.get_secret_value(), algorithm=settings.JWT_ALGORITHM
    )


def decode_access_token(token: str) -> dict[str, Any]:
    try:
        payload = jwt.decode(
            token,
            settings.JWT_SECRET_KEY.get_secret_value(),
            algorithms=[settings.JWT_ALGORITHM],
            options={"require": ["sub", "exp", "iat"]},
        )
    except jwt.ExpiredSignatureError as exc:
        raise AuthenticationError("Token has expired.", code="token_expired") from exc
    except jwt.InvalidTokenError as exc:
        raise AuthenticationError("Invalid token.", code="invalid_token") from exc

    if payload.get("type") != "access":
        raise AuthenticationError("Invalid token.", code="invalid_token")
    return payload
