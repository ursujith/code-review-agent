import json

from app import knowledge


def test_indexed_chunks_retrievable_and_project_scoped(tmp_path, monkeypatch):
    monkeypatch.setattr(knowledge, "DB_PATH", tmp_path / "knowledge.db")
    conn = knowledge._connect()
    try:
        conn.execute("INSERT INTO code_chunks(project_id,project_name,ref,path,start_line,end_line,content,content_hash) VALUES(?,?,?,?,?,?,?,?)", ("10", "group/auth-service", "main", "src/AuthService.java", 1, 4, "public class AuthService { validateToken(); }", "hash-a"))
        conn.execute("INSERT INTO code_chunks(project_id,project_name,ref,path,start_line,end_line,content,content_hash) VALUES(?,?,?,?,?,?,?,?)", ("20", "group/image-service", "main", "src/Image.java", 1, 4, "class Image { resize(); }", "hash-b"))
        conn.commit()
    finally:
        conn.close()
    result = knowledge.retrieve_context(["10"], "AuthService validateToken")
    assert result["chunks"] == 1
    assert "AuthService" in result["context"]
    assert "Image" not in result["context"]


def test_project_rules_round_trip(tmp_path, monkeypatch):
    monkeypatch.setenv("REVIEW_RULES_DIR", str(tmp_path))
    saved = knowledge.save_rules("group/project", {"instructions": "Use constructor injection", "required_checks": ["Validate input"]})
    assert saved["project_id"] == "group/project"
    assert knowledge.load_rules("group/project")["required_checks"] == ["Validate input"]


def test_feedback_is_recorded_without_auto_learning(tmp_path, monkeypatch):
    monkeypatch.setattr(knowledge, "DB_PATH", tmp_path / "knowledge.db")
    result = knowledge.record_feedback("12", 4, "finding-123456", "rejected", "False positive")
    assert result["stored"] is True
    assert "does not automatically" in result["note"]
    assert knowledge.feedback_summary("12") == {"rejected": 1}


def test_rules_reject_unknown_fields(tmp_path, monkeypatch):
    monkeypatch.setenv("REVIEW_RULES_DIR", str(tmp_path))
    try:
        knowledge.save_rules("1", {"prompt_override": "unsafe"})
    except ValueError as exc:
        assert "Unsupported" in str(exc)
    else:
        raise AssertionError("unknown rule field should be rejected")
