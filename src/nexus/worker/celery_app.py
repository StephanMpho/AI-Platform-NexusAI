"""Celery application.

Queues are separated by workload because they fail and scale differently:
ingestion is bursty and slow, rollups are periodic, evaluation runs are long.
"""

from __future__ import annotations

from celery import Celery

from nexus.config import get_settings

settings = get_settings()

celery_app = Celery("nexus", broker=settings.redis.url, backend=settings.redis.url)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    task_routes={
        "nexus.ingestion.*": {"queue": "ingestion"},
        "nexus.rollups.*": {"queue": "rollups"},
        "nexus.evaluation.*": {"queue": "evaluation"},
    },
    beat_schedule={
        "hourly-metric-rollup": {
            "task": "nexus.rollups.compute_hourly",
            "schedule": 3600.0,
        },
    },
)

from nexus.worker import tasks  # noqa: E402,F401 - registers tasks on import
