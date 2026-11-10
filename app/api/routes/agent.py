from __future__ import annotations

import os

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

router = APIRouter(prefix="/agent", tags=["central agent"])


class MRUrlReviewRequest(BaseModel):
    merge_request_url: str = Field(min_length=10, max_length=2048)
    publish_comments: bool = False
    min_confidence: float = Field(default=0.65, ge=0.0, le=1.0)
    max_workspace_projects: int = Field(default=20, ge=1, le=50)


@router.get("/config")
async def agent_config() -> dict:
    return {
        "name": "AI Code Review Agent",
        "review_mode": "preview by default",
        "mcp_endpoint": "/mcp",
        "access_token_required": bool(os.getenv("AGENT_ACCESS_TOKEN")),
    }


@router.post("/review-merge-request")
async def review_mr(request: MRUrlReviewRequest, http_request: Request) -> dict:
    if not os.getenv("AGENT_ACCESS_TOKEN", "").strip():
        raise HTTPException(
            status_code=503,
            detail="Central agent access is not configured. Set AGENT_ACCESS_TOKEN on the server.",
        )
    try:
        from app.services.mr_review_service import review_merge_request_url
        from app.security.access_store import record_review_audit
        result = await review_merge_request_url(
            request.merge_request_url,
            publish_comments=request.publish_comments,
            min_confidence=request.min_confidence,
            max_workspace_projects=request.max_workspace_projects,
        )
        record_review_audit(http_request.state.agent_username, request.merge_request_url, request.publish_comments, "completed")
        return result
    except ValueError as exc:
        from app.security.access_store import record_review_audit
        record_review_audit(http_request.state.agent_username, request.merge_request_url, request.publish_comments, "failed", str(exc))
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        from app.security.access_store import record_review_audit
        record_review_audit(http_request.state.agent_username, request.merge_request_url, request.publish_comments, "failed", str(exc))
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        from app.security.access_store import record_review_audit
        record_review_audit(http_request.state.agent_username, request.merge_request_url, request.publish_comments, "failed", type(exc).__name__)
        # Avoid returning provider payloads or credentials to browser clients.
        raise HTTPException(
            status_code=502,
            detail=f"Review could not be completed ({type(exc).__name__}). Check server logs.",
        ) from exc
