"""Celery application (Redis broker + result backend)."""

from celery import Celery
from celery.signals import worker_process_init

from app.core.config import settings

celery_app = Celery(
    "asm",
    broker=settings.CELERY_BROKER_URL,
    backend=settings.CELERY_RESULT_BACKEND,
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    broker_connection_retry_on_startup=True,
    beat_schedule={},
)


@worker_process_init.connect
def _reset_db_pool(**_: object) -> None:
    """Give each forked worker process its own DB connections (never share a pool across fork)."""
    from app.core.database import engine

    engine.dispose(close=False)
