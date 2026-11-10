from __future__ import annotations

from urllib.parse import quote

import httpx


class GitLabError(Exception):
    """A safe, provider-level error that does not expose credentials."""

    def __init__(self, message: str, status_code: int = 502) -> None:
        super().__init__(message)
        self.status_code = status_code


class GitLabClient:
    def __init__(
        self,
        base_url: str,
        token: str,
        *,
        timeout: float = 20.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        if not token.strip():
            raise ValueError("A GitLab access token is required")
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.timeout = timeout
        self.transport = transport

    async def get_merge_request(self, project_id: str, merge_request_iid: int) -> dict:
        project = quote(str(project_id), safe="")
        base = f"{self.base_url}/api/v4/projects/{project}/merge_requests/{merge_request_iid}"
        headers = {"PRIVATE-TOKEN": self.token, "Accept": "application/json"}

        async with httpx.AsyncClient(
            timeout=self.timeout, transport=self.transport, follow_redirects=False
        ) as client:
            details = await self._get_json(client, base, headers)
            changes_payload = await self._get_json(client, f"{base}/changes", headers)

        changes = changes_payload.get("changes", [])
        if not isinstance(changes, list):
            raise GitLabError("GitLab returned an invalid merge request changes response")

        return {
            "provider": "gitlab",
            "project_id": str(project_id),
            "merge_request_iid": merge_request_iid,
            "title": details.get("title"),
            "description": details.get("description"),
            "state": details.get("state"),
            "web_url": details.get("web_url"),
            "source_branch": details.get("source_branch"),
            "target_branch": details.get("target_branch"),
            "source_sha": (details.get("diff_refs") or {}).get("head_sha"),
            "target_sha": (details.get("diff_refs") or {}).get("base_sha"),
            "diff_refs": details.get("diff_refs") or {},
            "changes": changes,
            "diff_text": self._to_unified_diff(changes),
        }

    async def _get_json(
        self, client: httpx.AsyncClient, url: str, headers: dict[str, str]
    ) -> dict:
        try:
            response = await client.get(url, headers=headers)
        except httpx.TimeoutException as exc:
            raise GitLabError("GitLab request timed out", 504) from exc
        except httpx.RequestError as exc:
            raise GitLabError("Could not connect to GitLab", 502) from exc

        if response.status_code in (401, 403):
            raise GitLabError("GitLab rejected the token or its permissions", 502)
        if response.status_code == 404:
            raise GitLabError("GitLab project or merge request was not found", 404)
        if response.status_code == 429:
            raise GitLabError("GitLab rate limit reached; retry later", 429)
        if response.status_code >= 500:
            raise GitLabError("GitLab is temporarily unavailable", 502)
        if response.is_error:
            raise GitLabError(f"GitLab request failed with status {response.status_code}", 502)
        try:
            payload = response.json()
        except ValueError as exc:
            raise GitLabError("GitLab returned invalid JSON") from exc
        if not isinstance(payload, dict):
            raise GitLabError("GitLab returned an unexpected response")
        return payload


    async def create_merge_request_note(
        self, project_id: str, merge_request_iid: int, body: str
    ) -> dict:
        """Publish a review summary as a merge request note."""
        project = quote(str(project_id), safe="")
        url = (
            f"{self.base_url}/api/v4/projects/{project}/merge_requests/"
            f"{merge_request_iid}/notes"
        )
        return await self._post_json(url, {"body": body})

    async def create_merge_request_discussion(
        self, project_id: str, merge_request_iid: int, body: str, position: dict
    ) -> dict:
        """Publish an inline discussion on a changed merge-request line."""
        project = quote(str(project_id), safe="")
        url = (
            f"{self.base_url}/api/v4/projects/{project}/merge_requests/"
            f"{merge_request_iid}/discussions"
        )
        return await self._post_json(url, {"body": body, "position": position})

    async def _post_json(self, url: str, payload: dict) -> dict:
        headers = {"PRIVATE-TOKEN": self.token, "Accept": "application/json"}
        try:
            async with httpx.AsyncClient(
                timeout=self.timeout, transport=self.transport, follow_redirects=False
            ) as client:
                response = await client.post(url, headers=headers, json=payload)
        except httpx.TimeoutException as exc:
            raise GitLabError("GitLab write request timed out", 504) from exc
        except httpx.RequestError as exc:
            raise GitLabError("Could not connect to GitLab", 502) from exc

        if response.status_code in (401, 403):
            raise GitLabError("GitLab rejected the token or its permissions", 502)
        if response.status_code == 404:
            raise GitLabError("GitLab project or merge request was not found", 404)
        if response.status_code == 429:
            raise GitLabError("GitLab rate limit reached; retry later", 429)
        if response.status_code >= 500:
            raise GitLabError("GitLab is temporarily unavailable", 502)
        if response.is_error:
            raise GitLabError(f"GitLab write failed with status {response.status_code}", 502)
        try:
            result = response.json()
        except ValueError as exc:
            raise GitLabError("GitLab returned invalid JSON") from exc
        if not isinstance(result, dict):
            raise GitLabError("GitLab returned an unexpected write response")
        return result

    @staticmethod
    def _to_unified_diff(changes: list[dict]) -> str:
        chunks: list[str] = []
        for item in changes:
            old_path = item.get("old_path") or item.get("new_path") or "unknown"
            new_path = item.get("new_path") or old_path
            diff = item.get("diff") or ""
            if not diff:
                # GitLab may omit a diff for binary, oversized, or unchanged files.
                continue
            header = [f"diff --git a/{old_path} b/{new_path}"]
            if item.get("renamed_file"):
                header.extend([f"rename from {old_path}", f"rename to {new_path}"])
            header.extend([
                "--- /dev/null" if item.get("new_file") else f"--- a/{old_path}",
                "+++ /dev/null" if item.get("deleted_file") else f"+++ b/{new_path}",
                diff.rstrip("\n"),
            ])
            chunks.extend(header)
        return "\n".join(chunks) + ("\n" if chunks else "")
