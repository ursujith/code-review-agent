from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any

from redis import Redis

JOB_TTL_SECONDS = int(os.getenv("REVIEW_JOB_TTL_SECONDS", "604800"))
IDEMPOTENCY_TTL_SECONDS = int(os.getenv("WEBHOOK_IDEMPOTENCY_TTL_SECONDS", "604800"))


def get_redis() -> Redis:
    url = os.getenv("REDIS_URL", "redis://localhost:6380/0")
    return Redis.from_url(url, decode_responses=True, socket_connect_timeout=3)


def _job_key(job_id: str) -> str:
    return f"review-job:{job_id}"


def create_job(job_id: str, *, project_id: str, merge_request_iid: int) -> None:
    now = datetime.now(timezone.utc).isoformat()
    client = get_redis()
    client.hset(
        _job_key(job_id),
        mapping={
            "job_id": job_id,
            "status": "queued",
            "project_id": str(project_id),
            "merge_request_iid": str(merge_request_iid),
            "created_at": now,
            "updated_at": now,
            "attempts": "0",
        },
    )
    client.expire(_job_key(job_id), JOB_TTL_SECONDS)


def update_job(job_id: str, *, status: str, **fields: Any) -> None:
    mapping = {
        "status": status,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    for key, value in fields.items():
        if value is None:
            continue
        mapping[key] = value if isinstance(value, str) else json.dumps(value, default=str)
    client = get_redis()
    key = _job_key(job_id)
    client.hset(key, mapping=mapping)
    client.expire(key, JOB_TTL_SECONDS)


def get_job(job_id: str) -> dict[str, Any] | None:
    data = get_redis().hgetall(_job_key(job_id))
    if not data:
        return None
    for field in ("result", "error"):
        if field in data:
            try:
                data[field] = json.loads(data[field])
            except (TypeError, ValueError):
                pass
    if "attempts" in data:
        data["attempts"] = int(data["attempts"])
    return data


def claim_webhook(idempotency_key: str, job_id: str) -> bool:
    return bool(
        get_redis().set(
            f"review-webhook:{idempotency_key}", job_id, nx=True, ex=IDEMPOTENCY_TTL_SECONDS
        )
    )


def get_webhook_job(idempotency_key: str) -> str | None:
    return get_redis().get(f"review-webhook:{idempotency_key}")


def release_webhook_claim(idempotency_key: str, job_id: str) -> None:
    client = get_redis()
    key = f"review-webhook:{idempotency_key}"
    client.eval(
        "if redis.call('get', KEYS[1]) == ARGV[1] then return redis.call('del', KEYS[1]) else return 0 end",
        1,
        key,
        job_id,
    )


def delete_job(job_id: str) -> None:
    get_redis().delete(_job_key(job_id))
