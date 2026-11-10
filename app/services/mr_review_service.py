from __future__ import annotations

import os
from typing import Any

from app.ai.client import OpenAICompatibleClient


def build_ai_client() -> OpenAICompatibleClient:
    api_key = os.getenv("AI_API_KEY", "")
    if not api_key:
        raise RuntimeError("AI_API_KEY is not configured on the central agent server.")
    return OpenAICompatibleClient(
        base_url=os.getenv("AI_BASE_URL", "https://api.openai.com/v1"),
        api_key=api_key,
        model=os.getenv("AI_MODEL", "gpt-4o-mini"),
    )


async def review_merge_request_url(
    merge_request_url: str,
    *,
    publish_comments: bool = False,
    min_confidence: float = 0.65,
    max_workspace_projects: int = 20,
) -> dict[str, Any]:
    """Shared review workflow used by both the web application and MCP transports."""
    from app.knowledge import (
        resolve_merge_request_url,
        discover_group_projects,
        index_project,
        record_workspace_project,
        indexed_workspace_project_ids,
    )
    from app.providers.gitlab.client import GitLabClient
    from app.providers.gitlab.review_workflow import run_gitlab_review

    token = os.getenv("GITLAB_TOKEN", "")
    if not token:
        raise RuntimeError("GITLAB_TOKEN is not configured on the central agent server.")
    base_url = os.getenv("GITLAB_BASE_URL") or os.getenv("GITLAB_URL", "https://gitlab.com")
    resolved = await resolve_merge_request_url(base_url, token, merge_request_url)
    projects = await discover_group_projects(base_url, token, resolved["group_id"])

    limit = max(1, min(int(max_workspace_projects), 50))
    indexed: list[str] = []
    failed: list[dict[str, str]] = []
    for project in projects[:limit]:
        project_id = str(project.get("id"))
        if not project_id or project_id == "None":
            continue
        record_workspace_project(resolved["group_id"], project, "discovered")
        try:
            result = await index_project(base_url, token, project_id)
            record_workspace_project(resolved["group_id"], project, "indexed", result)
            indexed.append(project_id)
        except Exception as exc:
            record_workspace_project(
                resolved["group_id"], project, "failed",
                {"error": str(exc)[:300]},
            )
            failed.append({"project_id": project_id, "error": str(exc)[:300]})

    gitlab = GitLabClient(base_url=base_url, token=token)
    ai_client = build_ai_client()
    result = await run_gitlab_review(
        gitlab,
        resolved["project_id"],
        resolved["merge_request_iid"],
        ai_client,
        min_confidence=min_confidence,
        workspace_group_id=resolved["group_id"],
        publish_comments=publish_comments,
    )

    return {
        "resolved": resolved,
        "workspace_indexing": {
            "discovered": len(projects),
            "indexed": indexed,
            "failed": failed,
            "limit": limit,
            "not_indexed_due_to_limit": max(0, len(projects) - limit),
        },
        "result": result,
    }
