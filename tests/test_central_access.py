from fastapi.testclient import TestClient

from app.main import app


def test_web_ui_is_served():
    response = TestClient(app).get("/")
    assert response.status_code == 200
    assert "AI Code Review Agent" in response.text
    assert "GitLab merge-request URL" in response.text


def test_agent_review_requires_access_token(monkeypatch):
    monkeypatch.setenv("AGENT_ACCESS_TOKEN", "test-secret")
    response = TestClient(app).post(
        "/api/v1/agent/review-merge-request",
        json={"merge_request_url": "https://gitlab.example.com/group/project/-/merge_requests/1"},
    )
    assert response.status_code == 401


def test_agent_review_rejects_wrong_token(monkeypatch):
    monkeypatch.setenv("AGENT_ACCESS_TOKEN", "test-secret")
    response = TestClient(app).post(
        "/api/v1/agent/review-merge-request",
        headers={"Authorization": "Bearer wrong"},
        json={"merge_request_url": "https://gitlab.example.com/group/project/-/merge_requests/1"},
    )
    assert response.status_code == 401


def test_agent_review_requires_server_token_configuration(monkeypatch):
    monkeypatch.delenv("AGENT_ACCESS_TOKEN", raising=False)
    response = TestClient(app).post(
        "/api/v1/agent/review-merge-request",
        headers={"Authorization": "Bearer anything"},
        json={"merge_request_url": "https://gitlab.example.com/group/project/-/merge_requests/1"},
    )
    assert response.status_code == 503


def test_authorized_agent_review_uses_shared_service(monkeypatch):
    from app.services import mr_review_service

    monkeypatch.setenv("AGENT_ACCESS_TOKEN", "test-secret")

    async def fake_review(url, **kwargs):
        return {
            "resolved": {"project_id": "42", "merge_request_iid": 7},
            "workspace_indexing": {"discovered": 1, "indexed": ["42"], "failed": [], "limit": 20},
            "result": {"status": "preview", "published": False},
            "received_url": url,
            "publish_comments": kwargs["publish_comments"],
        }

    monkeypatch.setattr(mr_review_service, "review_merge_request_url", fake_review)
    response = TestClient(app).post(
        "/api/v1/agent/review-merge-request",
        headers={"Authorization": "Bearer test-secret"},
        json={"merge_request_url": "https://gitlab.example.com/group/project/-/merge_requests/7"},
    )
    assert response.status_code == 200
    assert response.json()["result"]["status"] == "preview"
    assert response.json()["publish_comments"] is False
