import uuid
from typing import Annotated

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.exceptions import AuthenticationError
from app.core.security import decode_access_token
from app.models.user import User
from app.repositories.user_repository import UserRepository

DbSession = Annotated[Session, Depends(get_db)]

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
