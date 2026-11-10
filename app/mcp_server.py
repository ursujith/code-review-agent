from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

mcp = FastMCP(
    "ai-code-review-agent",
    instructions="Review unified Git diffs and GitLab merge requests. Findings are advisory; validate them before acting.",
)


def _ai_client():
    from app.ai.client import OpenAICompatibleClient

    api_key = os.getenv("AI_API_KEY", "")
    if not api_key:
        raise RuntimeError("AI_API_KEY is missing. Configure it in the project .env file.")
    return OpenAICompatibleClient(
        base_url=os.getenv("AI_BASE_URL", "https://api.openai.com/v1"),
        api_key=api_key,
        model=os.getenv("AI_MODEL", "gpt-4o-mini"),
    )


@mcp.tool()
async def parse_diff(diff_text: str) -> dict[str, Any]:
    """Parse a unified Git diff and return changed files, changed lines and totals."""
    from app.review.diff_parser import parse_git_diff

    if not diff_text.strip():
        raise ValueError("diff_text cannot be empty")
    if len(diff_text) > 200_000:
        raise ValueError("diff_text exceeds the 200000 character limit")
    parsed = parse_git_diff(diff_text)
    return {
        "total_files": parsed.total_files,
        "total_added_lines": parsed.total_added_lines,
        "total_deleted_lines": parsed.total_deleted_lines,
        "files": [
            {
                "old_path": item.old_path,
                "new_path": item.new_path,
                "change_type": item.change_type,
                "is_binary": item.is_binary,
                "added_lines": [{"line": x.new_line_number, "content": x.content} for x in item.added_lines],
                "deleted_lines": [{"line": x.old_line_number, "content": x.content} for x in item.deleted_lines],
            }
            for item in parsed.files
        ],
    }


@mcp.tool()
async def review_diff(
    diff_text: str,
    context: str = "",
    min_confidence: float = 0.65,
    agents: list[str] | None = None,
) -> dict[str, Any]:
    """Run parallel bug, security, performance and maintainability agents on a unified diff."""
    from app.ai.agents.specialists import SPECIALISTS
    from app.ai.orchestrator import run_multi_agent_review, OrchestrationValidationError

    available = {agent.name: agent for agent in SPECIALISTS}
    requested = agents or list(available)
    unknown = sorted(set(requested) - set(available))
    if unknown:
        raise ValueError(f"Unknown agents: {', '.join(unknown)}. Available: {', '.join(available)}")
    selected = tuple(agent for name, agent in available.items() if name in requested)
    try:
        return await run_multi_agent_review(
            _ai_client(), diff_text, context or None,
            min_confidence=min_confidence, specialists=selected,
        )
    except OrchestrationValidationError as exc:
        raise ValueError(str(exc)) from exc


@mcp.tool()
async def review_gitlab_merge_request(
    project_id: str,
    merge_request_iid: int,
    publish_comments: bool = False,
    min_confidence: float = 0.65,
) -> dict[str, Any]:
    """Fetch and review a GitLab MR. Preview-only by default; publish_comments=true writes comments to GitLab."""
    from app.ai.orchestrator import run_multi_agent_review
    from app.providers.gitlab.client import GitLabClient
    from app.providers.gitlab.review_workflow import run_gitlab_review

    token = os.getenv("GITLAB_TOKEN", "")
    if not token:
        raise RuntimeError("GITLAB_TOKEN is missing. Configure it in the project .env file.")
    gitlab = GitLabClient(
        base_url=os.getenv("GITLAB_BASE_URL", "https://gitlab.com"),
        token=token,
    )
    if publish_comments:
        return await run_gitlab_review(
            gitlab, project_id, merge_request_iid, _ai_client(),
            min_confidence=min_confidence,
        )

    mr = await gitlab.get_merge_request(project_id, merge_request_iid)
    if not mr.get("diff_text", "").strip():
        raise ValueError("Merge request contains no reviewable text diff")
    review = await run_multi_agent_review(
        _ai_client(), mr["diff_text"], context=None,
        min_confidence=min_confidence,
    )
    return {
        "status": "preview",
        "project_id": str(project_id),
        "merge_request_iid": merge_request_iid,
        "merge_request_url": mr.get("web_url"),
        "title": mr.get("title"),
        "review": review,
        "published": False,
        "message": "Preview only. Set publish_comments=true to post findings to GitLab.",
    }


@mcp.tool()
async def review_gitlab_merge_request_url(
    merge_request_url: str,
    publish_comments: bool = False,
    min_confidence: float = 0.65,
    max_workspace_projects: int = 20,
) -> dict[str, Any]:
    """Review an MR from its URL; automatically discover its top-level group and index accessible sibling repositories."""
    from app.services.mr_review_service import review_merge_request_url

    return await review_merge_request_url(
        merge_request_url,
        publish_comments=publish_comments,
        min_confidence=min_confidence,
        max_workspace_projects=max_workspace_projects,
    )


if __name__ == "__main__":
    mcp.run(transport="stdio")
