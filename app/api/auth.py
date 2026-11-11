from typing import Annotated

from fastapi import APIRouter, Depends, status

from app.api.deps import DbSession, enforce_login_rate_limit, require_permission
from app.core.permissions import Permission
from app.models.user import User
from app.schemas.auth import LoginRequest, RegisterRequest, TokenResponse
from app.schemas.error import ErrorResponse
from app.schemas.user import UserResponse
from app.services.auth_service import AuthService

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post(
    "/login",
    response_model=TokenResponse,
    dependencies=[Depends(enforce_login_rate_limit)],
    responses={
        401: {"model": ErrorResponse, "description": "Invalid credentials"},
        429: {"model": ErrorResponse, "description": "Too many login attempts"},
    },
)
def login(data: LoginRequest, db: DbSession) -> TokenResponse:
    return AuthService(db).login(data.email, data.password)


@router.post(
    "/register",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register a new user (Admin only)",
    responses={
        401: {"model": ErrorResponse, "description": "Missing or invalid token"},
        403: {"model": ErrorResponse, "description": "Caller is not Admin"},
        409: {"model": ErrorResponse, "description": "Email already registered"},
    },
)
def register(
    data: RegisterRequest,
    db: DbSession,
    _: Annotated[User, Depends(require_permission(Permission.USER_REGISTER))],
) -> UserResponse:
    return UserResponse.model_validate(AuthService(db).register(data))
