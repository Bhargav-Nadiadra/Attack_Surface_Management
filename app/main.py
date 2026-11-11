from fastapi import FastAPI

from app.api import health
from app.core.config import settings
from app.core.error_handlers import register_exception_handlers
from app.core.logging import configure_logging
from app.core.middleware import RequestLoggingMiddleware
from app.schemas.error import ErrorResponse


def create_app() -> FastAPI:
    configure_logging(settings.LOG_LEVEL)

    app = FastAPI(
        title=settings.APP_NAME,
        version="0.1.0",
        description="Passive DNS asset discovery (A, AAAA, NS, MX) for Attack Surface Management.",
        responses={
            400: {"model": ErrorResponse, "description": "Validation failed"},
            500: {"model": ErrorResponse, "description": "Internal server error"},
        },
    )
    app.add_middleware(RequestLoggingMiddleware)
    register_exception_handlers(app)
    app.include_router(health.router)
    return app


app = create_app()
