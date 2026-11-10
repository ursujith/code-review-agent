from __future__ import annotations

import json
import os
import re
import sqlite3
from collections import Counter
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import quote

import httpx

DB_PATH = Path(os.getenv("KNOWLEDGE_DB_PATH", "./data/repository_knowledge.sqlite3"))
MAX_FILE_BYTES = int(os.getenv("KNOWLEDGE_MAX_FILE_BYTES", "250000"))
MAX_FILES = int(os.getenv("KNOWLEDGE_MAX_FILES", "5000"))
ALLOWED_SUFFIXES = {".py", ".java", ".js", ".jsx", ".ts", ".tsx", ".go", ".rb", ".php", ".cs", ".cpp", ".h", ".sql", ".yaml", ".yml", ".json", ".xml", ".properties", ".md", ".gradle", ".toml"}
IGNORED_PARTS = {".git", "node_modules", "vendor", "build", "dist", ".gradle", ".idea", "target"}


def _connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("""CREATE TABLE IF NOT EXISTS code_chunks (
        id INTEGER PRIMARY KEY, project_id TEXT NOT NULL, project_name TEXT NOT NULL,
        ref TEXT NOT NULL, path TEXT NOT NULL, start_line INTEGER NOT NULL,
        end_line INTEGER NOT NULL, content TEXT NOT NULL, content_hash TEXT NOT NULL,
        UNIQUE(project_id, ref, path, start_line, content_hash))""")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_chunks_project ON code_chunks(project_id, ref)")
    conn.execute("""CREATE TABLE IF NOT EXISTS workspace_projects (
        group_id TEXT NOT NULL, project_id TEXT NOT NULL, project_name TEXT,
        default_branch TEXT, web_url TEXT, status TEXT NOT NULL DEFAULT 'discovered',
        last_indexed_at TEXT, last_result_json TEXT,
        PRIMARY KEY(group_id, project_id))""")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_workspace_group ON workspace_projects(group_id, status)")

    conn.execute("""CREATE TABLE IF NOT EXISTS review_feedback (
        id INTEGER PRIMARY KEY, project_id TEXT NOT NULL, mr_iid INTEGER,
        finding_fingerprint TEXT NOT NULL, decision TEXT NOT NULL,
        reason TEXT, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)""")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_feedback_fingerprint ON review_feedback(finding_fingerprint)")
    conn.commit()
    return conn


def _chunks(text: str, size: int = 80, overlap: int = 12):
    lines = text.splitlines()
    step = max(1, size - overlap)
    for start in range(0, len(lines), step):
        part = lines[start:start + size]
        if part:
            yield start + 1, start + len(part), "\n".join(part)


def _hash(value: str) -> str:
    import hashlib
    return hashlib.sha256(value.encode("utf-8", errors="replace")).hexdigest()


async def _gitlab_get(base_url: str, token: str, path: str, params: dict | None = None):
    headers = {"PRIVATE-TOKEN": token, "Accept": "application/json"}
    async with httpx.AsyncClient(timeout=45, follow_redirects=False) as client:
        response = await client.get(f"{base_url.rstrip('/')}/api/v4/{path.lstrip('/')}", headers=headers, params=params)
    if response.status_code in (401, 403):
        raise ValueError("GitLab rejected the token or it lacks the required read permissions")
    if response.status_code == 404:
        raise ValueError("GitLab project/group or repository resource was not found")
    if response.status_code == 429:
        raise ValueError("GitLab rate limit reached; retry later")
    response.raise_for_status()
    return response


async def discover_group_projects(base_url: str, token: str, group_id: str) -> list[dict]:
    encoded = quote(str(group_id), safe="")
    projects: list[dict] = []
    for page in range(1, 101):
        response = await _gitlab_get(base_url, token, f"groups/{encoded}/projects", {"include_subgroups": "true", "per_page": 100, "page": page, "with_shared": "false"})
        batch = response.json()
        if not isinstance(batch, list):
            raise ValueError("GitLab returned an unexpected group projects response")
        projects.extend({"id": item.get("id"), "name": item.get("name"), "path_with_namespace": item.get("path_with_namespace"), "default_branch": item.get("default_branch"), "web_url": item.get("web_url")} for item in batch)
        if len(batch) < 100:
            break
    return projects


async def index_project(base_url: str, token: str, project_id: str, ref: str | None = None) -> dict:
    encoded = quote(str(project_id), safe="")
    project_response = await _gitlab_get(base_url, token, f"projects/{encoded}")
    project = project_response.json()
    selected_ref = ref or project.get("default_branch")
    if not selected_ref:
        raise ValueError("Project has no default branch; provide ref explicitly")
    files: list[dict] = []
    for page in range(1, 101):
        response = await _gitlab_get(base_url, token, f"projects/{encoded}/repository/tree", {"recursive": "true", "per_page": 100, "page": page, "ref": selected_ref})
        batch = response.json()
        if not isinstance(batch, list):
            raise ValueError("GitLab returned an unexpected repository tree response")
        files.extend(item for item in batch if item.get("type") == "blob")
        if len(batch) < 100 or len(files) >= MAX_FILES:
            break
    inserted = 0
    skipped = 0
    conn = _connect()
    try:
        conn.execute("DELETE FROM code_chunks WHERE project_id=? AND ref=?", (str(project_id), selected_ref))
        for item in files[:MAX_FILES]:
            path = item.get("path", "")
            pure = PurePosixPath(path)
            if any(part in IGNORED_PARTS for part in pure.parts) or pure.suffix.lower() not in ALLOWED_SUFFIXES:
                skipped += 1
                continue
            try:
                raw = await _gitlab_get(base_url, token, f"projects/{encoded}/repository/files/{quote(path, safe='')}/raw", {"ref": selected_ref})
                content = raw.text
            except Exception:
                skipped += 1
                continue
            if len(content.encode("utf-8", errors="replace")) > MAX_FILE_BYTES or "\x00" in content:
                skipped += 1
                continue
            for start, end, chunk in _chunks(content):
                conn.execute("INSERT OR IGNORE INTO code_chunks(project_id,project_name,ref,path,start_line,end_line,content,content_hash) VALUES(?,?,?,?,?,?,?,?)", (str(project_id), project.get("path_with_namespace") or project.get("name", str(project_id)), selected_ref, path, start, end, chunk, _hash(chunk)))
                inserted += 1
        conn.commit()
    finally:
        conn.close()
    return {"project_id": str(project_id), "project": project.get("path_with_namespace"), "ref": selected_ref, "tree_files": len(files), "chunks_indexed": inserted, "files_skipped": skipped}


def retrieve_context(project_ids: list[str], query: str, *, limit: int = 8, max_chars: int = 24000) -> dict:
    terms = [x.lower() for x in re.findall(r"[A-Za-z_][A-Za-z0-9_]{2,}", query)]
    terms = list(dict.fromkeys(terms))[:80]
    if not terms:
        return {"context": "", "sources": [], "chunks": 0}
    conn = _connect()
    try:
        placeholders = ",".join("?" for _ in project_ids)
        if project_ids:
            rows = conn.execute(f"SELECT * FROM code_chunks WHERE project_id IN ({placeholders})", project_ids).fetchall()
        else:
            rows = conn.execute("SELECT * FROM code_chunks").fetchall()
    finally:
        conn.close()
    scored = []
    for row in rows:
        text = (row["path"] + "\n" + row["content"]).lower()
        score = sum(text.count(term) * (2 if term in row["path"].lower() else 1) for term in terms)
        if score:
            scored.append((score, row))
    scored.sort(key=lambda x: (-x[0], x[1]["path"], x[1]["start_line"]))
    selected, sources, used = [], [], 0
    for score, row in scored[:limit * 4]:
        block = f"\n--- {row['project_name']}:{row['path']}:{row['start_line']}-{row['end_line']} (relevance {score}) ---\n{row['content']}\n"
        if used + len(block) > max_chars:
            continue
        selected.append(block); used += len(block)
        sources.append({"project_id": row["project_id"], "project": row["project_name"], "ref": row["ref"], "path": row["path"], "start_line": row["start_line"], "end_line": row["end_line"], "score": score})
        if len(selected) >= limit:
            break
    return {"context": "".join(selected), "sources": sources, "chunks": len(selected)}


def save_rules(project_id: str, rules: dict) -> dict:
    allowed = {"instructions", "required_checks", "forbidden_patterns", "severity_overrides"}
    unknown = set(rules) - allowed
    if unknown:
        raise ValueError(f"Unsupported rule fields: {', '.join(sorted(unknown))}")
    if not isinstance(rules.get("instructions", ""), str) or len(rules.get("instructions", "")) > 12000:
        raise ValueError("instructions must be a string of at most 12000 characters")
    for field in ("required_checks", "forbidden_patterns"):
        if field in rules and (not isinstance(rules[field], list) or len(rules[field]) > 100 or not all(isinstance(x, str) and len(x) <= 500 for x in rules[field])):
            raise ValueError(f"{field} must be a list of at most 100 short strings")
    path = Path(os.getenv("REVIEW_RULES_DIR", "./review-rules"))
    path.mkdir(parents=True, exist_ok=True)
    safe_id = re.sub(r"[^A-Za-z0-9_.-]", "_", str(project_id))
    target = path / f"{safe_id}.json"
    target.write_text(json.dumps(rules, indent=2), encoding="utf-8")
    return {"project_id": str(project_id), "rules": rules}


def load_rules(project_id: str) -> dict:
    path = Path(os.getenv("REVIEW_RULES_DIR", "./review-rules"))
    safe_id = re.sub(r"[^A-Za-z0-9_.-]", "_", str(project_id))
    target = path / f"{safe_id}.json"
    return json.loads(target.read_text(encoding="utf-8")) if target.exists() else {}


def architecture_map(project_id: str) -> dict:
    conn = _connect()
    try:
        rows = conn.execute("SELECT path, content FROM code_chunks WHERE project_id=?", (str(project_id),)).fetchall()
    finally:
        conn.close()
    modules = Counter()
    imports: dict[str, set[str]] = {}
    for row in rows:
        path, content = row["path"], row["content"]
        module = path.split("/")[0] if "/" in path else "root"
        modules[module] += 1
        refs = set(re.findall(r"(?:from|import)\s+([\w.]+)|import\s+([\w.]+)", content))
        flat = {a or b for a, b in refs if a or b}
        if flat:
            imports.setdefault(module, set()).update(flat)
    return {"project_id": str(project_id), "modules": [{"name": name, "indexed_chunks": count} for name, count in modules.most_common()], "imports_by_module": {k: sorted(v)[:100] for k, v in imports.items()}, "note": "Heuristic import map from indexed source chunks; validate inferred relationships before relying on them."}


def record_feedback(project_id: str, mr_iid: int | None, fingerprint: str, decision: str, reason: str | None) -> dict:
    if decision not in {"accepted", "rejected"}:
        raise ValueError("decision must be 'accepted' or 'rejected'")
    conn = _connect()
    try:
        conn.execute("INSERT INTO review_feedback(project_id,mr_iid,finding_fingerprint,decision,reason) VALUES(?,?,?,?,?)", (str(project_id), mr_iid, fingerprint, decision, reason))
        conn.commit()
    finally:
        conn.close()
    return {"project_id": str(project_id), "merge_request_iid": mr_iid, "finding_fingerprint": fingerprint, "decision": decision, "stored": True, "note": "Feedback is stored for reporting only; it does not automatically alter prompts or suppress future findings."}


def feedback_summary(project_id: str) -> dict:
    conn = _connect()
    try:
        rows = conn.execute("SELECT decision, COUNT(*) AS count FROM review_feedback WHERE project_id=? GROUP BY decision", (str(project_id),)).fetchall()
    finally:
        conn.close()
    return {row["decision"]: row["count"] for row in rows}


def record_workspace_project(group_id: str, project: dict, status: str, result: dict | None = None) -> None:
    """Persist discovery and indexing status for a GitLab group project."""
    conn = _connect()
    try:
        conn.execute(
            """INSERT INTO workspace_projects
            (group_id, project_id, project_name, default_branch, web_url, status,
             last_indexed_at, last_result_json)
            VALUES(?,?,?,?,?,?,CASE WHEN ?='indexed' THEN CURRENT_TIMESTAMP ELSE NULL END,?)
            ON CONFLICT(group_id, project_id) DO UPDATE SET
              project_name=excluded.project_name,
              default_branch=excluded.default_branch,
              web_url=excluded.web_url,
              status=excluded.status,
              last_indexed_at=CASE WHEN excluded.status='indexed' THEN CURRENT_TIMESTAMP
                                   ELSE workspace_projects.last_indexed_at END,
              last_result_json=excluded.last_result_json""",
            (str(group_id), str(project.get("id")), project.get("path_with_namespace") or project.get("name"),
             project.get("default_branch"), project.get("web_url"), status, status,
             json.dumps(result, ensure_ascii=False) if result is not None else None),
        )
        conn.commit()
    finally:
        conn.close()


def workspace_index_status(group_id: str) -> dict:
    conn = _connect()
    try:
        rows = conn.execute(
            """SELECT project_id, project_name, default_branch, web_url, status,
                      last_indexed_at, last_result_json
               FROM workspace_projects WHERE group_id=? ORDER BY project_name""",
            (str(group_id),),
        ).fetchall()
    finally:
        conn.close()
    projects = []
    for row in rows:
        item = dict(row)
        item["last_result"] = json.loads(item.pop("last_result_json")) if item.get("last_result_json") else None
        projects.append(item)
    counts = Counter(item["status"] for item in projects)
    return {"group_id": str(group_id), "total_projects": len(projects),
            "indexed": counts.get("indexed", 0), "failed": counts.get("failed", 0),
            "discovered": counts.get("discovered", 0), "projects": projects}


def indexed_workspace_project_ids(group_id: str | None = None) -> list[str]:
    conn = _connect()
    try:
        if group_id:
            rows = conn.execute(
                "SELECT DISTINCT project_id FROM workspace_projects WHERE group_id=? AND status='indexed'",
                (str(group_id),),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT DISTINCT project_id FROM workspace_projects WHERE status='indexed'"
            ).fetchall()
    finally:
        conn.close()
    return [str(row["project_id"]) for row in rows]


def indexed_refs(project_id: str) -> list[str]:
    conn = _connect()
    try:
        rows = conn.execute(
            "SELECT DISTINCT ref FROM code_chunks WHERE project_id=? ORDER BY ref",
            (str(project_id),),
        ).fetchall()
    finally:
        conn.close()
    return [str(row["ref"]) for row in rows]


async def resolve_merge_request_url(base_url: str, token: str, merge_request_url: str) -> dict:
    """Resolve an MR URL to its project, IID and top-level GitLab group path."""
    from urllib.parse import urlparse
    parsed = urlparse(merge_request_url.strip())
    if parsed.scheme != "https" or not parsed.netloc or parsed.query or parsed.fragment:
        raise ValueError("Provide a clean HTTPS GitLab merge request URL without query parameters")
    if parsed.netloc.lower() != urlparse(base_url).netloc.lower():
        raise ValueError("Merge request URL host does not match GITLAB_BASE_URL")
    match = re.fullmatch(r"/(.+)/-/merge_requests/(\d+)/?", parsed.path)
    if not match:
        raise ValueError("URL must have the form /group/project/-/merge_requests/123")
    project_path, iid_text = match.groups()
    project_response = await _gitlab_get(base_url, token, f"projects/{quote(project_path, safe='')}")
    project = project_response.json()
    namespace = project.get("namespace") or {}
    if namespace.get("kind") != "group" or not namespace.get("id"):
        raise ValueError("The MR project is not under a GitLab group")
    group = (await _gitlab_get(base_url, token, f"groups/{quote(str(namespace['id']), safe='')}")).json()
    visited = set()
    while group.get("parent_id"):
        group_id = str(group.get("id"))
        if group_id in visited:
            raise ValueError("GitLab returned a cyclic group hierarchy")
        visited.add(group_id)
        group = (await _gitlab_get(base_url, token, f"groups/{quote(str(group['parent_id']), safe='')}")).json()
    return {
        "project_id": str(project["id"]),
        "project_path": project.get("path_with_namespace") or project_path,
        "merge_request_iid": int(iid_text),
        "group_id": str(group.get("full_path") or group.get("id")),
        "group_name": group.get("name"),
        "group_full_path": group.get("full_path"),
    }
