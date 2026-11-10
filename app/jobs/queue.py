from __future__ import annotations

import hashlib
import json
import uuid

from celery import Task

from app.jobs.store import (
    claim_webhook,
    create_job,
    delete_job,
    get_job,
    get_webhook_job,
    release_webhook_claim,
)
from app.jobs.tasks import run_gitlab_review_task


def make_webhook_idempotency_key(payload: dict, event_uuid: str | None = None) -> str:
    if event_uuid and event_uuid.strip():
        source = f"gitlab-event:{event_uuid.strip()}"
    else:
        attrs = payload.get("object_attributes") or {}
        last_commit = attrs.get("last_commit") or {}
        source_data = {
            "project_id": (payload.get("project") or {}).get("id"),
            "merge_request_iid": attrs.get("iid"),
            "action": attrs.get("action"),
            "state": attrs.get("state"),
            "last_commit_id": last_commit.get("id"),
            "updated_at": attrs.get("updated_at"),
        }
        source = json.dumps(source_data, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(source.encode("utf-8")).hexdigest()


def enqueue_gitlab_review(
    project_id: str, merge_request_iid: int, idempotency_key: str
) -> tuple[str, bool]:
    """Queue one review per webhook event; return (job_id, already_queued)."""
    existing = get_webhook_job(idempotency_key)
    if existing:
        return existing, True

    job_id = str(uuid.uuid4())
    if not claim_webhook(idempotency_key, job_id):
        existing = get_webhook_job(idempotency_key)
        if existing:
            return existing, True
        raise RuntimeError("Could not claim webhook idempotency key")

    try:
        create_job(job_id, project_id=project_id, merge_request_iid=merge_request_iid)
        run_gitlab_review_task.apply_async(
            args=[job_id, str(project_id), merge_request_iid], task_id=job_id
        )
    except Exception:
        delete_job(job_id)
        release_webhook_claim(idempotency_key, job_id)
        raise
    return job_id, False
