from typing import Any

from celery import Celery
from celery.signals import setup_logging, worker_process_init

from app.core.config import settings
from app.core.database import engine
from app.core.logging import configure_logging

RUN_DISCOVERY_TASK = "scans.run_discovery"
SWEEP_STALE_TASK = "scans.sweep_stale"

celery_app = Celery(
    "asm",
    broker=settings.CELERY_BROKER_URL,
    backend=settings.CELERY_RESULT_BACKEND,
    include=["app.workers.tasks"],
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    task_ignore_result=True,
    worker_prefetch_multiplier=1,
    worker_hijack_root_logger=False,
    broker_connection_retry_on_startup=True,
    broker_connection_timeout=3,
    broker_transport_options={"socket_connect_timeout": 3, "socket_timeout": 5},
    redis_socket_connect_timeout=3,
    redis_socket_timeout=5,
    task_publish_retry_policy={
        "max_retries": 2,
        "interval_start": 0,
        "interval_step": 0.5,
        "interval_max": 1,
    },
    beat_schedule={
        "sweep-stale-scans": {
            "task": SWEEP_STALE_TASK,
            "schedule": float(settings.SWEEP_INTERVAL_SECONDS),
        },
    },
)


@setup_logging.connect
def _configure_worker_logging(**_: Any) -> None:
    configure_logging(settings.LOG_LEVEL)


@worker_process_init.connect
def _reset_db_pool(**_: Any) -> None:
    engine.dispose(close=False)
