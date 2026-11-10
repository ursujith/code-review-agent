import pytest
from app import knowledge


@pytest.mark.asyncio
async def test_resolve_mr_url_discovers_root_group(monkeypatch):
    calls = []
    class Response:
        def __init__(self, payload): self.payload = payload
        def json(self): return self.payload
    async def fake_get(base, token, path, params=None):
        calls.append(path)
        if path == "projects/Coleman%2FProcessIntelligence%2Fmodeler-backend":
            return Response({"id": 42, "path_with_namespace": "Coleman/ProcessIntelligence/modeler-backend", "namespace": {"id": 20, "kind": "group"}})
        if path == "groups/20":
            return Response({"id": 20, "parent_id": 10, "full_path": "Coleman/ProcessIntelligence"})
        if path == "groups/10":
            return Response({"id": 10, "parent_id": None, "full_path": "Coleman", "name": "Coleman"})
        raise AssertionError(path)
    monkeypatch.setattr(knowledge, "_gitlab_get", fake_get)
    result = await knowledge.resolve_merge_request_url(
        "https://oxford.infor.com", "token",
        "https://oxford.infor.com/Coleman/ProcessIntelligence/modeler-backend/-/merge_requests/123",
    )
    assert result["project_id"] == "42"
    assert result["merge_request_iid"] == 123
    assert result["group_id"] == "Coleman"
    assert calls == ["projects/Coleman%2FProcessIntelligence%2Fmodeler-backend", "groups/20", "groups/10"]


@pytest.mark.asyncio
async def test_resolve_mr_url_rejects_other_host():
    with pytest.raises(ValueError, match="host"):
        await knowledge.resolve_merge_request_url(
            "https://oxford.infor.com", "token",
            "https://gitlab.com/group/project/-/merge_requests/1",
        )
