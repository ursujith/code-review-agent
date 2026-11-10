import httpx
import pytest

from app.providers.gitlab.client import GitLabClient, GitLabError


@pytest.mark.asyncio
async def test_fetch_merge_request_and_build_unified_diff():
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path.endswith("/changes"):
            return httpx.Response(200, json={"changes": [{
                "old_path": "src/app.py",
                "new_path": "src/app.py",
                "new_file": False,
                "deleted_file": False,
                "renamed_file": False,
                "diff": "@@ -1,2 +1,2 @@\n-old()\n+new()",
            }]})
        return httpx.Response(200, json={
            "title": "Fix app", "description": "A change", "state": "opened",
            "web_url": "https://gitlab.example/group/project/-/merge_requests/7",
            "source_branch": "feature", "target_branch": "main",
            "diff_refs": {"head_sha": "head123", "base_sha": "base123"},
        })

    client = GitLabClient(
        "https://gitlab.example", "test-token", transport=httpx.MockTransport(handler)
    )
    result = await client.get_merge_request("group/project", 7)

    assert result["title"] == "Fix app"
    assert result["source_sha"] == "head123"
    assert "diff --git a/src/app.py b/src/app.py" in result["diff_text"]
    assert "-old()\n+new()" in result["diff_text"]
    assert len(requests) == 2
    assert all(req.headers["PRIVATE-TOKEN"] == "test-token" for req in requests)
    assert "/projects/group%2Fproject/" in str(requests[0].url)


@pytest.mark.asyncio
async def test_gitlab_not_found_maps_to_404():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"message": "Not found"})

    client = GitLabClient(
        "https://gitlab.example", "test-token", transport=httpx.MockTransport(handler)
    )
    with pytest.raises(GitLabError) as error:
        await client.get_merge_request("123", 1)
    assert error.value.status_code == 404


def test_token_is_required():
    with pytest.raises(ValueError):
        GitLabClient("https://gitlab.com", " ")
