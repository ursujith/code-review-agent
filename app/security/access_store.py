from __future__ import annotations

import hashlib
import os
import secrets
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _db_path() -> Path:
    path = Path(os.getenv("AGENT_ACCESS_DB_PATH", "./data/agent_access.sqlite3"))
    if not path.is_absolute():
        path = Path.cwd() / path
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(_db_path(), timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


def init_access_store() -> None:
    with _connect() as conn:
        conn.execute("""CREATE TABLE IF NOT EXISTS agent_tokens (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL UNIQUE,
            token_hash TEXT NOT NULL UNIQUE,
            token_prefix TEXT NOT NULL,
            created_at TEXT NOT NULL,
            revoked_at TEXT
        )""")
        conn.execute("""CREATE TABLE IF NOT EXISTS agent_audit_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL,
            action TEXT NOT NULL,
            merge_request_url TEXT,
            publish_comments INTEGER NOT NULL DEFAULT 0,
            status TEXT NOT NULL,
            detail TEXT,
            created_at TEXT NOT NULL
        )""")


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def authenticate_token(token: str) -> str | None:
    if not token:
        return None
    init_access_store()
    with _connect() as conn:
        row = conn.execute(
            "SELECT username FROM agent_tokens WHERE token_hash=? AND revoked_at IS NULL",
            (_hash(token),),
        ).fetchone()
    return str(row["username"]) if row else None


def create_token(username: str) -> dict[str, Any]:
    clean = username.strip()
    if not clean or len(clean) > 120:
        raise ValueError("username must contain between 1 and 120 characters")
    token = "acr_" + secrets.token_urlsafe(36)
    now = datetime.now(timezone.utc).isoformat()
    init_access_store()
    try:
        with _connect() as conn:
            cursor = conn.execute(
                "INSERT INTO agent_tokens(username,token_hash,token_prefix,created_at) VALUES(?,?,?,?)",
                (clean, _hash(token), token[:12], now),
            )
            token_id = cursor.lastrowid
    except sqlite3.IntegrityError as exc:
        raise ValueError("A developer with this username already exists") from exc
    return {"id": token_id, "username": clean, "token": token, "token_prefix": token[:12], "created_at": now}


def list_tokens() -> list[dict[str, Any]]:
    init_access_store()
    with _connect() as conn:
        rows = conn.execute(
            "SELECT id,username,token_prefix,created_at,revoked_at FROM agent_tokens ORDER BY id DESC"
        ).fetchall()
    return [dict(row) for row in rows]


def revoke_token(token_id: int) -> bool:
    init_access_store()
    with _connect() as conn:
        cursor = conn.execute(
            "UPDATE agent_tokens SET revoked_at=? WHERE id=? AND revoked_at IS NULL",
            (datetime.now(timezone.utc).isoformat(), token_id),
        )
    return cursor.rowcount > 0


def record_review_audit(
    username: str, merge_request_url: str, publish_comments: bool, status: str, detail: str = ""
) -> None:
    init_access_store()
    with _connect() as conn:
        conn.execute(
            "INSERT INTO agent_audit_log(username,action,merge_request_url,publish_comments,status,detail,created_at) VALUES(?,?,?,?,?,?,?)",
            (username, "review_merge_request", merge_request_url, int(publish_comments), status,
             detail[:500], datetime.now(timezone.utc).isoformat()),
        )


def list_audit_logs(limit: int = 100) -> list[dict[str, Any]]:
    init_access_store()
    with _connect() as conn:
        rows = conn.execute(
            "SELECT id,username,action,merge_request_url,publish_comments,status,detail,created_at "
            "FROM agent_audit_log ORDER BY id DESC LIMIT ?", (max(1, min(limit, 500)),)
        ).fetchall()
    return [dict(row) for row in rows]
