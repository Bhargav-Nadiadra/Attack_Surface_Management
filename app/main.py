import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from sqlalchemy.exc import SQLAlchemyError

from app.api import auth, domains, health, scans
from app.core.config import settings
from app.core.database import SessionLocal
from app.core.error_handlers import register_exception_handlers
from app.core.logging import configure_logging
from app.core.middleware import RequestLoggingMiddleware
from app.schemas.error import ErrorResponse
from app.services.auth_service import AuthService

logger = logging.getLogger("app.startup")


def seed_first_admin() -> None:
    try:
        with SessionLocal() as session:
            AuthService(session).seed_first_admin(
                settings.FIRST_ADMIN_EMAIL, settings.FIRST_ADMIN_PASSWORD.get_secret_value()
            )
    except SQLAlchemyError:
        logger.exception("startup.seed_admin_failed")


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    seed_first_admin()
    yield


def create_app() -> FastAPI:
    configure_logging(settings.LOG_LEVEL)

    app = FastAPI(
        title=settings.APP_NAME,
        version="0.1.0",
        description="Passive DNS asset discovery (A, AAAA, NS, MX) for Attack Surface Management.",
        lifespan=lifespan,
        responses={
            400: {"model": ErrorResponse, "description": "Validation failed"},
            500: {"model": ErrorResponse, "description": "Internal server error"},
        },
    )
    app.add_middleware(RequestLoggingMiddleware)
    register_exception_handlers(app)
    app.include_router(health.router)
    app.include_router(auth.router)
    app.include_router(domains.router)
    app.include_router(scans.router)
    return app


app = create_app()
