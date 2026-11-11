from fastapi import APIRouter, status

from app.api.deps import CurrentUser, DbSession
from app.schemas.auth import LoginRequest, RegisterRequest, TokenResponse
from app.schemas.error import ErrorResponse
from app.schemas.user import UserResponse
from app.services.auth_service import AuthService

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post(
    "/login",
    response_model=TokenResponse,
    responses={401: {"model": ErrorResponse, "description": "Invalid credentials"}},
)
def login(data: LoginRequest, db: DbSession) -> TokenResponse:
    return AuthService(db).login(data.email, data.password)


@router.post(
    "/register",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
    responses={
        401: {"model": ErrorResponse, "description": "Not authenticated"},
        409: {"model": ErrorResponse, "description": "Email already registered"},
    },
)
def register(data: RegisterRequest, db: DbSession, _: CurrentUser) -> UserResponse:
    return UserResponse.model_validate(AuthService(db).register(data))
