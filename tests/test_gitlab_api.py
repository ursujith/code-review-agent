from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_gitlab_endpoint_requires_token(monkeypatch):
    monkeypatch.delenv("GITLAB_TOKEN", raising=False)
    response = client.get("/api/v1/providers/gitlab/projects/123/merge-requests/4")
    assert response.status_code == 400
    assert "GITLAB_TOKEN" in response.json()["detail"]
