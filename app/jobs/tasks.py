from __future__ import annotations

import asyncio
import os
from datetime import datetime, timezone

from app.ai.client import AIProviderError, OpenAICompatibleClient
from app.jobs.celery_app import celery_app
from app.jobs.store import get_job, update_job
from app.providers.gitlab.client import GitLabClient, GitLabError
from app.providers.gitlab.review_workflow import run_gitlab_review


def _is_retryable(exc: Exception) -> bool:
    if isinstance(exc, GitLabError):
        return exc.status_code in {429, 502, 503, 504}
    if isinstance(exc, AIProviderError):
        return exc.status_code == 429 or exc.status_code >= 500
    return False


@celery_app.task(
    bind=True,
    name="app.jobs.tasks.run_gitlab_review_task",
    max_retries=int(os.getenv("REVIEW_TASK_MAX_RETRIES", "3")),
    default_retry_delay=int(os.getenv("REVIEW_TASK_RETRY_DELAY_SECONDS", "30")),
)
def run_gitlab_review_task(self, job_id: str, project_id: str, merge_request_iid: int) -> dict:
    """Execute a GitLab review in a worker process with bounded retries."""
    previous = get_job(job_id) or {}
    update_job(
        job_id,
        status="running",
        started_at=previous.get("started_at") or datetime.now(timezone.utc).isoformat(),
        attempts=str(self.request.retries + 1),
        error=None,
    )
    try:
        gitlab_token = os.getenv("GITLAB_TOKEN", "")
        ai_key = os.getenv("AI_API_KEY", "")
        if not gitlab_token or not ai_key:
            raise RuntimeError("Worker requires GITLAB_TOKEN and AI_API_KEY environment variables")

        gitlab = GitLabClient(os.getenv("GITLAB_BASE_URL", "https://gitlab.com"), gitlab_token)
        ai = OpenAICompatibleClient(
            os.getenv("AI_BASE_URL", "https://api.openai.com/v1"),
            ai_key,
            os.getenv("AI_MODEL", "gpt-4o-mini"),
        )
        result = asyncio.run(run_gitlab_review(gitlab, str(project_id), merge_request_iid, ai))
        update_job(job_id, status="completed", result=result)
        return {"job_id": job_id, "status": "completed"}
    except Exception as exc:
        if _is_retryable(exc) and self.request.retries < self.max_retries:
            update_job(
                job_id,
                status="retrying",
                error={"message": str(exc), "retry": self.request.retries + 1},
                attempts=str(self.request.retries + 1),
            )
            raise self.retry(exc=exc)
        update_job(
            job_id,
            status="failed",
            error={"type": type(exc).__name__, "message": str(exc)},
            attempts=str(self.request.retries + 1),
        )
        raise
