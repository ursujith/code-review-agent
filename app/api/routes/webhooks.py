from __future__ import annotations

import hmac
import os

from fastapi import APIRouter, Header, HTTPException, Request
from fastapi.responses import JSONResponse

from app.ai.client import AIProviderError, OpenAICompatibleClient
from app.providers.gitlab.client import GitLabClient, GitLabError
from app.providers.gitlab.review_workflow import run_gitlab_review

router = APIRouter(prefix="/webhooks", tags=["webhooks"])


@router.post("/gitlab")
async def gitlab_merge_request_webhook(
    request: Request,
    token: str | None = Header(default=None, alias="X-Gitlab-Token"),
    event_uuid: str | None = Header(default=None, alias="X-Gitlab-Event-UUID"),
) -> dict:
    """Validate a GitLab MR event and enqueue its review without blocking the webhook."""
    secret = os.getenv("GITLAB_WEBHOOK_SECRET", "")
    if not secret:
        raise HTTPException(status_code=503, detail="GITLAB_WEBHOOK_SECRET is not configured")
    if not token or not hmac.compare_digest(token, secret):
        raise HTTPException(status_code=401, detail="Invalid webhook token")

    try:
        payload = await request.json()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Webhook body must be valid JSON") from exc
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="Webhook body must be a JSON object")
    if payload.get("object_kind") != "merge_request":
        return {"status": "ignored", "reason": "not a merge request event"}

    attributes = payload.get("object_attributes") or {}
    action = attributes.get("action")
    state = attributes.get("state")
    if action not in {"open", "reopen", "update"} or state not in {"opened", "reopened"}:
        return {"status": "ignored", "reason": "merge request action does not trigger review"}

    project_id = (payload.get("project") or {}).get("id")
    iid = attributes.get("iid")
    if project_id is None or not isinstance(iid, int):
        raise HTTPException(
            status_code=400,
            detail="Webhook is missing project.id or object_attributes.iid",
        )
    if not os.getenv("GITLAB_TOKEN") or not os.getenv("AI_API_KEY"):
        raise HTTPException(status_code=503, detail="Configure GITLAB_TOKEN and AI_API_KEY")

    from redis.exceptions import RedisError

    from app.jobs.queue import enqueue_gitlab_review, make_webhook_idempotency_key

    idempotency_key = make_webhook_idempotency_key(payload, event_uuid)
    try:
        job_id, duplicate = enqueue_gitlab_review(str(project_id), iid, idempotency_key)
    except (RedisError, RuntimeError, OSError) as exc:
        raise HTTPException(status_code=503, detail="Could not enqueue review; retry webhook") from exc
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Review queue is unavailable; retry webhook") from exc

    return JSONResponse(
        status_code=202,
        content={
            "status": "already_queued" if duplicate else "queued",
            "job_id": job_id,
            "project_id": str(project_id),
            "merge_request_iid": iid,
            "status_url": f"/api/v1/reviews/jobs/{job_id}",
        },
    )
