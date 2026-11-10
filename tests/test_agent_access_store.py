from __future__ import annotations

from app.security import access_store


def test_create_authenticate_revoke_and_audit(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENT_ACCESS_DB_PATH", str(tmp_path / "access.sqlite3"))

    issued = access_store.create_token("developer.one")
    assert issued["token"].startswith("acr_")
    assert access_store.authenticate_token(issued["token"]) == "developer.one"

    # The database stores a hash, never the plaintext token.
    import sqlite3
    with sqlite3.connect(tmp_path / "access.sqlite3") as conn:
        stored = conn.execute("SELECT token_hash FROM agent_tokens").fetchone()[0]
    assert stored != issued["token"]

    access_store.record_review_audit(
        "developer.one", "https://gitlab.example/group/project/-/merge_requests/7", False, "completed"
    )
    logs = access_store.list_audit_logs()
    assert len(logs) == 1
    assert logs[0]["username"] == "developer.one"
    assert logs[0]["publish_comments"] == 0

    assert access_store.revoke_token(issued["id"]) is True
    assert access_store.authenticate_token(issued["token"]) is None
    assert access_store.revoke_token(issued["id"]) is False


def test_duplicate_username_rejected(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENT_ACCESS_DB_PATH", str(tmp_path / "access.sqlite3"))
    access_store.create_token("developer.one")
    try:
        access_store.create_token("developer.one")
    except ValueError as exc:
        assert "already exists" in str(exc)
    else:
        raise AssertionError("Expected duplicate username to be rejected")
