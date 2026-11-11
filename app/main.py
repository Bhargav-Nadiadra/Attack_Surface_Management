"""FastAPI application factory."""

from fastapi import FastAPI

from app.api import health
from app.core.config import settings


def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.APP_NAME,
        version="0.1.0",
        description="Passive DNS asset discovery (A, AAAA, NS, MX) for Attack Surface Management.",
    )
    app.include_router(health.router)
    return app


app = create_app()
