"""AST-aware repository intelligence and symbol/dependency retrieval.

Python uses the standard-library AST parser. Other languages use conservative
source patterns; all extracted relationships are heuristic and should be verified.
"""
from __future__ import annotations

import ast
import math
import re
import sqlite3
from collections import defaultdict
from pathlib import Path
from typing import Any

from app.knowledge import _connect

TOKEN_PATTERN = re.compile(r"[A-Za-z_][A-Za-z0-9_.$]{2,}")
DECLARATIONS = [
    ("class", re.compile(r"^\s*(?:public|protected|private|abstract|final|static|\s)*\bclass\s+([A-Za-z_$][\w$]*)", re.M)),
    ("interface", re.compile(r"^\s*(?:public|protected|private|\s)*\binterface\s+([A-Za-z_$][\w$]*)", re.M)),
    ("function", re.compile(r"^\s*(?:export\s+)?(?:async\s+)?function\s+([A-Za-z_$][\w$]*)\s*\(", re.M)),
    ("function", re.compile(r"^\s*(?:def|async\s+def)\s+([A-Za-z_]\w*)\s*\(", re.M)),
]
IMPORTS = re.compile(r"^\s*(?:import\s+(?:static\s+)?([\w.$]+)|from\s+([\w.]+)\s+import|(?:const|let|var)\s+.*?\s+from\s+['\"]([^'\"]+)['\"])", re.M)


def extract_symbols_and_imports(path: str, source: str) -> tuple[list[dict], list[str]]:
    symbols: list[dict] = []
    if Path(path).suffix.lower() == ".py":
        try:
            tree = ast.parse(source)
            for node in ast.walk(tree):
                if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                    symbols.append({"name": node.name, "kind": "class" if isinstance(node, ast.ClassDef) else "function", "start_line": node.lineno, "end_line": getattr(node, "end_lineno", node.lineno)})
        except SyntaxError:
            pass
    else:
        for kind, pattern in DECLARATIONS:
            for match in pattern.finditer(source):
                symbols.append({"name": match.group(1), "kind": kind, "start_line": source.count("\n", 0, match.start()) + 1, "end_line": source.count("\n", 0, match.start()) + 1})
    imports = sorted({next(group for group in match.groups() if group) for match in IMPORTS.finditer(source)})
    return symbols, imports


def build_intelligence(project_id: str, ref: str | None = None) -> dict:
    conn = _connect()
    try:
        sql = "SELECT ref,path,content,start_line FROM code_chunks WHERE project_id=?"
        params: list[Any] = [str(project_id)]
        if ref:
            sql += " AND ref=?"; params.append(ref)
        rows = conn.execute(sql, params).fetchall()
        conn.execute("""CREATE TABLE IF NOT EXISTS repository_symbols (
            id INTEGER PRIMARY KEY, project_id TEXT NOT NULL, ref TEXT NOT NULL,
            path TEXT NOT NULL, name TEXT NOT NULL, kind TEXT NOT NULL,
            start_line INTEGER NOT NULL, end_line INTEGER NOT NULL,
            UNIQUE(project_id,ref,path,name,kind,start_line))""")
        conn.execute("""CREATE TABLE IF NOT EXISTS repository_imports (
            id INTEGER PRIMARY KEY, project_id TEXT NOT NULL, ref TEXT NOT NULL,
            path TEXT NOT NULL, import_name TEXT NOT NULL,
            UNIQUE(project_id,ref,path,import_name))""")
        refs = sorted({row["ref"] for row in rows})
        if ref:
            refs = [ref]
        for selected_ref in refs:
            conn.execute("DELETE FROM repository_symbols WHERE project_id=? AND ref=?", (str(project_id), selected_ref))
            conn.execute("DELETE FROM repository_imports WHERE project_id=? AND ref=?", (str(project_id), selected_ref))
        files: dict[tuple[str, str], dict[int, str]] = defaultdict(dict)
        for row in rows:
            for offset, line in enumerate(row["content"].splitlines()):
                files[(row["ref"], row["path"])][row["start_line"] + offset] = line
        symbol_count = import_count = 0
        for (selected_ref, path), numbered in files.items():
            source = "\n".join(numbered.get(i, "") for i in range(1, max(numbered) + 1))
            symbols, imports = extract_symbols_and_imports(path, source)
            for symbol in symbols:
                conn.execute("INSERT OR IGNORE INTO repository_symbols(project_id,ref,path,name,kind,start_line,end_line) VALUES(?,?,?,?,?,?,?)", (str(project_id), selected_ref, path, symbol["name"], symbol["kind"], symbol["start_line"], symbol["end_line"]))
                symbol_count += 1
            for imported in imports:
                conn.execute("INSERT OR IGNORE INTO repository_imports(project_id,ref,path,import_name) VALUES(?,?,?,?)", (str(project_id), selected_ref, path, imported))
                import_count += 1
        conn.commit()
        return {"project_id": str(project_id), "refs_processed": refs, "files_analyzed": len(files), "symbols_indexed": symbol_count, "imports_indexed": import_count, "parser_note": "Python uses AST; other languages use conservative declaration/import patterns."}
    finally:
        conn.close()


def search_symbols(project_ids: list[str], query: str, limit: int = 30) -> list[dict]:
    terms = list(dict.fromkeys(token.lower() for token in TOKEN_PATTERN.findall(query)))
    if not terms:
        return []
    conn = _connect()
    try:
        if project_ids:
            marks = ",".join("?" for _ in project_ids)
            rows = conn.execute(f"SELECT project_id,ref,path,name,kind,start_line,end_line FROM repository_symbols WHERE project_id IN ({marks})", project_ids).fetchall()
        else:
            rows = conn.execute("SELECT project_id,ref,path,name,kind,start_line,end_line FROM repository_symbols").fetchall()
    finally:
        conn.close()
    ranked = []
    for row in rows:
        name = row["name"].lower()
        score = sum(5 if name == term else 3 if term in name else 0 for term in terms)
        if score:
            ranked.append((score, dict(row)))
    ranked.sort(key=lambda item: (-item[0], item[1]["path"], item[1]["start_line"]))
    return [dict(item, score=score) for score, item in ranked[:limit]]


def dependency_graph(project_id: str, ref: str | None = None) -> dict:
    conn = _connect()
    try:
        sql = "SELECT ref,path,import_name FROM repository_imports WHERE project_id=?"
        params: list[Any] = [str(project_id)]
        if ref:
            sql += " AND ref=?"; params.append(ref)
        rows = conn.execute(sql, params).fetchall()
    finally:
        conn.close()
    paths = sorted({row["path"] for row in rows})
    edges = []
    for row in rows:
        imported = row["import_name"]
        target = next((path for path in paths if path.replace("/", ".").removesuffix(Path(path).suffix).endswith(imported)), None)
        edges.append({"source": row["path"], "import": imported, "resolved_target": target, "resolution": "heuristic" if target else "unresolved", "ref": row["ref"]})
    return {"project_id": str(project_id), "ref": ref, "nodes": paths, "edges": edges}


def hybrid_retrieve(project_ids: list[str], query: str, *, limit: int = 10, max_chars: int = 30000) -> dict:
    """BM25-style lexical retrieval boosted by indexed symbol/path matches."""
    terms = list(dict.fromkeys(token.lower() for token in TOKEN_PATTERN.findall(query)))[:100]
    if not terms:
        return {"context": "", "sources": [], "chunks": 0, "retrieval": "bm25-symbol-hybrid"}
    conn = _connect()
    try:
        if project_ids:
            marks = ",".join("?" for _ in project_ids)
            rows = conn.execute(f"SELECT * FROM code_chunks WHERE project_id IN ({marks})", project_ids).fetchall()
            symbols = conn.execute(f"SELECT project_id,path,name FROM repository_symbols WHERE project_id IN ({marks})", project_ids).fetchall()
        else:
            rows = conn.execute("SELECT * FROM code_chunks").fetchall()
            symbols = conn.execute("SELECT project_id,path,name FROM repository_symbols").fetchall()
    finally:
        conn.close()
    symbol_map: dict[tuple[str, str], list[str]] = defaultdict(list)
    for symbol in symbols:
        symbol_map[(symbol["project_id"], symbol["path"])].append(symbol["name"].lower())
    docs = [(row, (row["path"] + "\n" + row["content"]).lower()) for row in rows]
    df = {term: sum(term in content for _, content in docs) for term in terms}
    avg_len = sum(len(content.split()) for _, content in docs) / max(1, len(docs))
    ranked = []
    for row, content in docs:
        length = len(content.split()); score = 0.0
        for term in terms:
            tf = content.count(term)
            if not tf: continue
            idf = math.log(1 + (len(docs) - df[term] + 0.5) / (df[term] + 0.5))
            score += idf * (tf * 2.2) / (tf + 1.2 * (0.25 + 0.75 * length / max(1, avg_len)))
            if term in row["path"].lower(): score += 2.0
            if any(term in name for name in symbol_map[(row["project_id"], row["path"])]): score += 1.5
        if score: ranked.append((score, row))
    ranked.sort(key=lambda item: (-item[0], item[1]["path"], item[1]["start_line"]))
    blocks, sources, used = [], [], 0
    for score, row in ranked[:limit * 5]:
        block = f"\n--- {row['project_name']}:{row['path']}:{row['start_line']}-{row['end_line']} (hybrid relevance {score:.2f}) ---\n{row['content']}\n"
        if used + len(block) > max_chars: continue
        blocks.append(block); used += len(block)
        sources.append({"project_id": row["project_id"], "project": row["project_name"], "ref": row["ref"], "path": row["path"], "start_line": row["start_line"], "end_line": row["end_line"], "score": round(score, 3)})
        if len(blocks) >= limit: break
    return {"context": "".join(blocks), "sources": sources, "chunks": len(blocks), "retrieval": "bm25-symbol-hybrid"}
