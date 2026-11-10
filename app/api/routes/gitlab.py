import os

from fastapi import APIRouter, Header, HTTPException

from app.providers.gitlab import GitLabClient, GitLabError
from app.review.diff_parser import parse_git_diff

router = APIRouter(prefix="/providers/gitlab", tags=["GitLab integration"])


@router.get("/projects/{project_id}/merge-requests/{merge_request_iid}")
async def fetch_merge_request(
    project_id: str,
    merge_request_iid: int,
    token: str | None = Header(default=None, alias="PRIVATE-TOKEN"),
) -> dict:
    """Fetch merge request metadata and its diff from GitLab.

    Supply PRIVATE-TOKEN as a request header, or configure GITLAB_TOKEN locally.
    Never pass access tokens in query parameters.
    """
    access_token = token or os.getenv("GITLAB_TOKEN")
    if not access_token:
        raise HTTPException(status_code=400, detail="Configure GITLAB_TOKEN or send PRIVATE-TOKEN")

    gitlab_url = (os.getenv("GITLAB_BASE_URL") or "https://gitlab.com").rstrip("/")
    try:
        result = await GitLabClient(gitlab_url, access_token).get_merge_request(
            project_id, merge_request_iid
        )
    except GitLabError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc

    parsed = parse_git_diff(result["diff_text"])
    result["diff_summary"] = {
        "total_files": parsed.total_files,
        "total_added_lines": parsed.total_added_lines,
        "total_deleted_lines": parsed.total_deleted_lines,
    }
    return result
