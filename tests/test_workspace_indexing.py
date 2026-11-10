from fastapi.testclient import TestClient

from app import knowledge
from app.main import app
from app.api.routes import knowledge as knowledge_routes


def test_workspace_index_status_and_project_ids(tmp_path, monkeypatch):
    monkeypatch.setattr(knowledge, "DB_PATH", tmp_path / "knowledge.db")
    project = {
        "id": 101,
        "name": "auth-service",
        "path_with_namespace": "platform/auth-service",
        "default_branch": "main",
        "web_url": "https://gitlab.example/platform/auth-service",
    }
    knowledge.record_workspace_project("platform", project, "discovered")
    assert knowledge.workspace_index_status("platform")["discovered"] == 1

    knowledge.record_workspace_project(
        "platform", project, "indexed",
        {"project_id": "101", "ref": "main", "chunks_indexed": 12},
    )
    status = knowledge.workspace_index_status("platform")
    assert status["indexed"] == 1
    assert status["projects"][0]["last_result"]["chunks_indexed"] == 12
    assert knowledge.indexed_workspace_project_ids("platform") == ["101"]


def test_indexed_refs_are_project_scoped(tmp_path, monkeypatch):
    monkeypatch.setattr(knowledge, "DB_PATH", tmp_path / "knowledge.db")
    conn = knowledge._connect()
    try:
        conn.execute(
            """INSERT INTO code_chunks
            (project_id,project_name,ref,path,start_line,end_line,content,content_hash)
            VALUES(?,?,?,?,?,?,?,?)""",
            ("101", "platform/auth-service", "main", "Auth.java", 1, 1, "class Auth {}", "a"),
        )
        conn.execute(
            """INSERT INTO code_chunks
            (project_id,project_name,ref,path,start_line,end_line,content,content_hash)
            VALUES(?,?,?,?,?,?,?,?)""",
            ("101", "platform/auth-service", "release", "Auth.java", 1, 1, "class Auth {}", "b"),
        )
        conn.execute(
            """INSERT INTO code_chunks
            (project_id,project_name,ref,path,start_line,end_line,content,content_hash)
            VALUES(?,?,?,?,?,?,?,?)""",
            ("202", "platform/image-service", "develop", "Image.java", 1, 1, "class Image {}", "c"),
        )
        conn.commit()
    finally:
        conn.close()
    assert knowledge.indexed_refs("101") == ["main", "release"]


def test_group_index_endpoint_continues_after_project_failure(monkeypatch):
    async def fake_discover(base, token, group_id):
        return [
            {"id": 1, "name": "good", "path_with_namespace": "platform/good", "default_branch": "main"},
            {"id": 2, "name": "bad", "path_with_namespace": "platform/bad", "default_branch": "main"},
        ]

    async def fake_index(base, token, project_id, ref=None):
        if str(project_id) == "2":
            raise ValueError("repository unavailable")
        return {"project_id": str(project_id), "ref": "main", "chunks_indexed": 3}

    monkeypatch.setattr(knowledge_routes, "_credentials", lambda: ("https://gitlab.example", "token"))
    monkeypatch.setattr(knowledge_routes, "discover_group_projects", fake_discover)
    monkeypatch.setattr(knowledge_routes, "index_project", fake_index)
    monkeypatch.setattr(knowledge_routes, "record_workspace_project", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        knowledge_routes, "workspace_index_status",
        lambda group_id: {"group_id": group_id, "total_projects": 2, "indexed": 1, "failed": 1,
                          "discovered": 0, "projects": []},
    )

    response = TestClient(app).post(
        "/api/v1/knowledge/groups/platform/index",
        json={"max_projects": 10},
    )
    assert response.status_code == 200
    payload = response.json()
    assert [item["status"] for item in payload["results"]] == ["indexed", "failed"]
    assert payload["workspace_status"]["failed"] == 1
