from fastapi.testclient import TestClient

from app.main import app


def _payload():
    return {
        "object_kind": "merge_request",
        "project": {"id": 123},
        "object_attributes": {
            "iid": 45,
            "action": "open",
            "state": "opened",
            "last_commit": {"id": "abc123"},
        },
    }


def test_gitlab_webhook_rejects_invalid_secret(monkeypatch):
    monkeypatch.setenv("GITLAB_WEBHOOK_SECRET", "expected-secret")
    response = TestClient(app).post(
        "/api/v1/webhooks/gitlab",
        headers={"X-Gitlab-Token": "wrong"},
        json={"object_kind": "merge_request"},
    )
    assert response.status_code == 401


def test_gitlab_webhook_ignores_non_merge_request_event(monkeypatch):
    monkeypatch.setenv("GITLAB_WEBHOOK_SECRET", "expected-secret")
    response = TestClient(app).post(
        "/api/v1/webhooks/gitlab",
        headers={"X-Gitlab-Token": "expected-secret"},
        json={"object_kind": "push"},
    )
    assert response.status_code == 200
    assert response.json()["status"] == "ignored"


def test_gitlab_webhook_enqueues_review(monkeypatch):
    monkeypatch.setenv("GITLAB_WEBHOOK_SECRET", "expected-secret")
    monkeypatch.setenv("GITLAB_TOKEN", "gitlab-token")
    monkeypatch.setenv("AI_API_KEY", "ai-key")
    monkeypatch.setattr(
        "app.jobs.queue.enqueue_gitlab_review",
        lambda project_id, iid, key: ("job-123", False),
    )
    response = TestClient(app).post(
        "/api/v1/webhooks/gitlab",
        headers={"X-Gitlab-Token": "expected-secret", "X-Gitlab-Event-UUID": "event-1"},
        json=_payload(),
    )
    assert response.status_code == 202
    assert response.json()["status"] == "queued"
    assert response.json()["job_id"] == "job-123"


def test_gitlab_webhook_reports_duplicate(monkeypatch):
    monkeypatch.setenv("GITLAB_WEBHOOK_SECRET", "expected-secret")
    monkeypatch.setenv("GITLAB_TOKEN", "gitlab-token")
    monkeypatch.setenv("AI_API_KEY", "ai-key")
    monkeypatch.setattr(
        "app.jobs.queue.enqueue_gitlab_review",
        lambda project_id, iid, key: ("job-existing", True),
    )
    response = TestClient(app).post(
        "/api/v1/webhooks/gitlab",
        headers={"X-Gitlab-Token": "expected-secret"},
        json=_payload(),
    )
    assert response.status_code == 202
    assert response.json()["status"] == "already_queued"
