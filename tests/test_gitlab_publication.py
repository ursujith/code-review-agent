import httpx
import pytest

from app.providers.gitlab.client import GitLabClient


@pytest.mark.asyncio
async def test_publish_inline_discussion_and_summary_note():
    captured = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append((request.method, request.url.path, request.read().decode()))
        return httpx.Response(201, json={"id": 10, "body": "created"})

    client = GitLabClient(
        "https://gitlab.example", "secret", transport=httpx.MockTransport(handler)
    )
    position = {
        "position_type": "text", "base_sha": "base", "start_sha": "start",
        "head_sha": "head", "old_path": "src/a.py", "new_path": "src/a.py",
        "new_line": 12,
    }
    await client.create_merge_request_discussion("group/project", 8, "Inline finding", position)
    await client.create_merge_request_note("group/project", 8, "Review summary")

    assert len(captured) == 2
    assert captured[0][0] == "POST"
    assert captured[0][1].endswith("/merge_requests/8/discussions")
    assert '"new_line":12' in captured[0][2]
    assert captured[1][1].endswith("/merge_requests/8/notes")
    assert "Review summary" in captured[1][2]
