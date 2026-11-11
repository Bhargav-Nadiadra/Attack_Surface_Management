import logging
import uuid
from collections.abc import Callable
from typing import Annotated

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.exceptions import AuthenticationError, PermissionDeniedError
from app.core.permissions import Permission, roles_for
from app.core.security import decode_access_token
from app.models.enums import UserRole
from app.models.user import User
from app.repositories.user_repository import UserRepository
from app.services.scan_dispatcher import CeleryScanDispatcher, ScanDispatcher

logger = logging.getLogger("app.auth")

DbSession = Annotated[Session, Depends(get_db)]

_celery_dispatcher = CeleryScanDispatcher()


def get_scan_dispatcher() -> ScanDispatcher:
    return _celery_dispatcher


Dispatcher = Annotated[ScanDispatcher, Depends(get_scan_dispatcher)]

bearer_scheme = HTTPBearer(auto_error=False, description="JWT access token from /auth/login")


def get_current_user(
    db: DbSession,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
) -> User:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise AuthenticationError("Not authenticated.", code="not_authenticated")

    payload = decode_access_token(credentials.credentials)
    try:
        user_id = uuid.UUID(payload["sub"])
    except (KeyError, ValueError) as exc:
        raise AuthenticationError("Invalid token.", code="invalid_token") from exc

    user = UserRepository(db).get_by_id(user_id)
    if user is None or not user.is_active:
        raise AuthenticationError("User not found or inactive.", code="invalid_token")
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


def require_roles(*roles: UserRole) -> Callable[..., User]:
    allowed = frozenset(roles)

    def dependency(request: Request, user: CurrentUser) -> User:
        if user.role not in allowed:
            logger.warning(
                "auth.permission_denied",
                extra={
                    "user_id": str(user.id),
                    "role": user.role,
                    "method": request.method,
                    "path": request.url.path,
                },
            )
            raise PermissionDeniedError()
        return user

    return dependency


def require_permission(permission: Permission) -> Callable[..., User]:
    return require_roles(*roles_for(permission))
