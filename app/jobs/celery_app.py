from __future__ import annotations

import os

from celery import Celery
from dotenv import load_dotenv

load_dotenv()

broker_url = os.getenv("CELERY_BROKER_URL") or os.getenv("REDIS_URL", "redis://localhost:6380/0")
result_backend = os.getenv("CELERY_RESULT_BACKEND") or os.getenv("REDIS_URL", "redis://localhost:6380/0")

celery_app = Celery(
    "ai_code_review_agent",
    broker=broker_url,
    backend=result_backend,
    include=["app.jobs.tasks"],
)
celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    task_track_started=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    task_reject_on_worker_lost=True,
    task_time_limit=int(os.getenv("REVIEW_TASK_TIME_LIMIT_SECONDS", "1800")),
    task_soft_time_limit=int(os.getenv("REVIEW_TASK_SOFT_TIME_LIMIT_SECONDS", "1500")),
    result_expires=86400,
    broker_connection_retry_on_startup=True,
)
