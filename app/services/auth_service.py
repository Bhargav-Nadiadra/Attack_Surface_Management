import logging
from typing import NoReturn

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.exceptions import AuthenticationError, ConflictError
from app.core.security import (
    access_token_ttl_seconds,
    burn_password_check,
    create_access_token,
    hash_password,
    verify_password,
)
from app.models.enums import UserRole
from app.models.user import User
from app.repositories.user_repository import UserRepository
from app.schemas.auth import RegisterRequest, TokenResponse
from app.schemas.validators import validate_password_strength

logger = logging.getLogger("app.auth")

INVALID_CREDENTIALS = "Invalid email or password."


class AuthService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.users = UserRepository(session)

    def register(self, data: RegisterRequest) -> User:
        if self.users.get_by_email(data.email):
            raise ConflictError("A user with this email already exists.", code="email_taken")

        user = User(
            email=data.email,
            password_hash=hash_password(data.password),
            full_name=data.full_name,
            role=data.role,
        )
        try:
            self.users.add(user)
            self.session.commit()
        except IntegrityError as exc:
            self.session.rollback()
            raise ConflictError(
                "A user with this email already exists.", code="email_taken"
            ) from exc

        logger.info("auth.user_registered", extra={"user_id": str(user.id), "role": user.role})
        return user

    def login(self, email: str, password: str) -> TokenResponse:
        user = self.users.get_by_email(email)

        if user is None:
            burn_password_check(password)
            self._login_failed(email, "unknown_email")
        elif not verify_password(password, user.password_hash):
            self._login_failed(email, "wrong_password")
        elif not user.is_active:
            self._login_failed(email, "inactive_user")

        logger.info("auth.login_success", extra={"user_id": str(user.id), "role": user.role})
        return TokenResponse(
            access_token=create_access_token(user.id, user.role),
            expires_in=access_token_ttl_seconds(),
        )

    def seed_first_admin(self, email: str, password: str) -> None:
        if self.users.any_exist():
            return

        validate_password_strength(password)
        admin = User(
            email=email.strip().lower(),
            password_hash=hash_password(password),
            full_name="Administrator",
            role=UserRole.ADMIN,
        )
        try:
            self.users.add(admin)
            self.session.commit()
        except IntegrityError:
            self.session.rollback()
            return
        logger.info("auth.first_admin_seeded", extra={"user_id": str(admin.id)})

    @staticmethod
    def _login_failed(email: str, reason: str) -> NoReturn:
        logger.warning("auth.login_failed", extra={"email": email, "reason": reason})
        raise AuthenticationError(INVALID_CREDENTIALS, code="invalid_credentials")
