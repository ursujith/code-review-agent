from app import knowledge
from app.cross_service_intelligence import cross_project_impact, workspace_architecture


def _insert(conn, project_id, name, path, content, ref="main"):
    conn.execute(
        "INSERT INTO code_chunks(project_id,project_name,ref,path,start_line,end_line,content,content_hash) VALUES(?,?,?,?,?,?,?,?)",
        (project_id, name, ref, path, 1, len(content.splitlines()), content, project_id + path),
    )


def test_cross_project_impact_finds_exact_changed_type_import(tmp_path, monkeypatch):
    monkeypatch.setattr(knowledge, "DB_PATH", tmp_path / "cross.db")
    conn = knowledge._connect()
    try:
        _insert(conn, "shared", "group/shared-models",
                "src/main/java/com/acme/shared/UserDto.java",
                "package com.acme.shared;\npublic class UserDto { private String name; }")
        _insert(conn, "consumer", "group/user-service",
                "src/main/java/com/acme/user/UserService.java",
                "package com.acme.user;\nimport com.acme.shared.UserDto;\npublic class UserService {}")
        conn.commit()
    finally:
        conn.close()

    result = cross_project_impact("shared", ["src/main/java/com/acme/shared/UserDto.java"], "main")
    assert result["projects_scanned"] == 1
    assert any(f["relationship"] == "imports_changed_type"
               and f["consumer_project_id"] == "consumer"
               and f["confidence"] == "high" for f in result["consumer_findings"])


def test_workspace_architecture_lists_indexed_projects(tmp_path, monkeypatch):
    monkeypatch.setattr(knowledge, "DB_PATH", tmp_path / "workspace.db")
    conn = knowledge._connect()
    try:
        _insert(conn, "one", "group/one", "src/main/java/A.java", "package com.acme; class A {}")
        _insert(conn, "two", "group/two", "src/main/java/B.java", "package com.acme; class B {}")
        conn.commit()
    finally:
        conn.close()
    result = workspace_architecture()
    assert result["projects_indexed"] == 2
    assert {p["project_id"] for p in result["projects"]} == {"one", "two"}
