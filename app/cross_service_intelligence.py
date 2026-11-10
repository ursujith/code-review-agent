"""Evidence-based cross-project dependency and change-impact analysis.

This is static source analysis, not a compiler or runtime call graph. Findings
include evidence and confidence so reviewers can validate inferred relationships.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from app.knowledge import _connect

JAVA_IMPORT = re.compile(r"^\s*import\s+(?:static\s+)?([\w.]+);", re.M)
JAVA_TYPES = re.compile(r"\b(?:class|interface|enum|record)\s+([A-Z][A-Za-z0-9_]*)")
POM_COORD = re.compile(
    r"<groupId>\s*([^<]+)\s*</groupId>\s*<artifactId>\s*([^<]+)\s*</artifactId>"
)
GRADLE_COORD = re.compile(r"""(?:implementation|api|compileOnly|runtimeOnly)\s*(?:\(|\s)\s*['"]([^'"]+)['"]""")
FEIGN = re.compile(r'@FeignClient\s*\((.*?)\)', re.S)
URL_MAPPING = re.compile(r'@(Get|Post|Put|Patch|Delete|Request)Mapping\s*(?:\((.*?)\))?', re.S)
STRING = re.compile(r'''(?:value|path|name|url)\s*=\s*["']([^"']+)["']|^\s*["']([^"']+)["']''')


def _project_files(conn, project_ids: list[str] | None = None, refs: dict[str, str] | None = None):
    sql = "SELECT project_id,project_name,ref,path,start_line,content FROM code_chunks"
    clauses, params = [], []
    if project_ids:
        clauses.append("project_id IN (" + ",".join("?" for _ in project_ids) + ")")
        params.extend(project_ids)
    if refs:
        for pid, ref in refs.items():
            clauses.append("(project_id=? AND ref=?)")
            params.extend([str(pid), ref])
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    rows = conn.execute(sql, params).fetchall()
    files: dict[tuple[str, str, str], dict[int, str]] = {}
    names = {}
    for row in rows:
        key = (row["project_id"], row["ref"], row["path"])
        files.setdefault(key, {})
        names[row["project_id"]] = row["project_name"]
        for offset, line in enumerate(row["content"].splitlines()):
            files[key][row["start_line"] + offset] = line
    result = []
    for (pid, ref, path), numbered in files.items():
        source = "\n".join(numbered.get(i, "") for i in range(1, max(numbered) + 1))
        result.append({"project_id": pid, "project": names.get(pid, pid), "ref": ref, "path": path, "source": source})
    return result


def _coordinates(source: str, path: str) -> set[str]:
    if Path(path).name == "pom.xml":
        return {f"{g.strip()}:{a.strip()}" for g, a in POM_COORD.findall(source)}
    if Path(path).name in {"build.gradle", "build.gradle.kts"}:
        return {m.group(1).split(":")[:2][0] + ":" + m.group(1).split(":")[:2][1]
                for m in GRADLE_COORD.finditer(source) if len(m.group(1).split(":")) >= 2}
    return set()


def workspace_architecture(group_id: str | None = None) -> dict[str, Any]:
    conn = _connect()
    try:
        files = _project_files(conn)
    finally:
        conn.close()
    projects = {}
    for f in files:
        p = projects.setdefault(f["project_id"], {"project_id": f["project_id"], "project": f["project"], "refs": set(), "files": 0, "java_files": 0, "build_coordinates": set()})
        p["refs"].add(f["ref"]); p["files"] += 1
        if f["path"].endswith(".java"): p["java_files"] += 1
        p["build_coordinates"].update(_coordinates(f["source"], f["path"]))
    coordinates = {}
    for pid, p in projects.items():
        for coordinate in p["build_coordinates"]:
            coordinates.setdefault(coordinate, []).append(pid)
    edges = []
    for f in files:
        imports = JAVA_IMPORT.findall(f["source"]) if f["path"].endswith(".java") else []
        for coordinate, providers in coordinates.items():
            if f["project_id"] in providers: continue
            group, artifact = coordinate.split(":", 1)
            matched = [imp for imp in imports if imp == group or imp.startswith(group + ".")]
            if matched:
                for provider in providers:
                    edges.append({"consumer_project_id": f["project_id"], "provider_project_id": provider,
                                  "consumer_file": f["path"], "coordinate": coordinate,
                                  "evidence": matched[:5], "confidence": "medium",
                                  "reason": "Java package import matches a groupId declared by an indexed project."})
    return {
        "projects": [{**p, "refs": sorted(p["refs"]), "build_coordinates": sorted(p["build_coordinates"])} for p in sorted(projects.values(), key=lambda x: x["project_id"])],
        "dependency_edges": edges,
        "projects_indexed": len(projects),
        "limitations": ["Only currently indexed projects and refs are analyzed.", "Package/groupId matching is heuristic and may produce false positives or miss dependencies.", "Transitive dependencies and runtime traffic are not resolved.", "A project is not proven to be a consumer merely because it shares a package prefix."]
    }


def cross_project_impact(project_id: str, changed_paths: list[str], ref: str | None = None,
                         candidate_project_ids: list[str] | None = None) -> dict[str, Any]:
    conn = _connect()
    try:
        source_files = _project_files(conn, [str(project_id)], {str(project_id): ref} if ref else None)
        other_files = _project_files(conn, candidate_project_ids)
    finally:
        conn.close()
    changed = [f for f in source_files if f["path"] in set(changed_paths)]
    if not changed:
        return {"project_id": str(project_id), "changed_paths": sorted(set(changed_paths)),
                "consumer_findings": [], "projects_scanned": len({f["project_id"] for f in other_files}),
                "warning": "No indexed source files matched the supplied changed_paths and ref."}
    changed_types, changed_packages, changed_coordinates = set(), set(), set()
    for f in changed:
        changed_types.update(JAVA_TYPES.findall(f["source"]))
        pkg = re.search(r"^\s*package\s+([\w.]+)\s*;", f["source"], re.M)
        if pkg: changed_packages.add(pkg.group(1))
        changed_coordinates.update(_coordinates(f["source"], f["path"]))
    findings = []
    for f in other_files:
        if f["project_id"] == str(project_id): continue
        imports = JAVA_IMPORT.findall(f["source"]) if f["path"].endswith(".java") else []
        matched_types = sorted({name for name in changed_types for imp in imports if imp.endswith("." + name) or imp == name})
        matched_packages = sorted({pkg for pkg in changed_packages for imp in imports if imp == pkg or imp.startswith(pkg + ".")})
        consumed_coordinates = sorted(_coordinates(f["source"], f["path"]) & changed_coordinates)
        feign = []
        for match in FEIGN.finditer(f["source"]):
            args = match.group(1)
            value = STRING.search(args)
            if value:
                feign.append(value.group(1))
        if matched_types:
            findings.append({"consumer_project_id": f["project_id"], "consumer_project": f["project"],
                "ref": f["ref"], "file": f["path"], "relationship": "imports_changed_type",
                "evidence": matched_types, "confidence": "high",
                "recommendation": "Check compilation, serialization compatibility, and all call sites for the changed type."})
        elif matched_packages:
            findings.append({"consumer_project_id": f["project_id"], "consumer_project": f["project"],
                "ref": f["ref"], "file": f["path"], "relationship": "imports_changed_package",
                "evidence": matched_packages, "confidence": "medium",
                "recommendation": "Check whether package-level API changes affect this consumer."})
        if consumed_coordinates:
            findings.append({"consumer_project_id": f["project_id"], "consumer_project": f["project"],
                "ref": f["ref"], "file": f["path"], "relationship": "declares_provider_artifact",
                "evidence": consumed_coordinates, "confidence": "medium",
                "recommendation": "Check dependency version alignment and rebuild this consumer."})
        if feign and changed:
            # Keep this as a low-confidence review hint, not a proven relationship.
            findings.append({"consumer_project_id": f["project_id"], "consumer_project": f["project"],
                "ref": f["ref"], "file": f["path"], "relationship": "feign_client_hint",
                "evidence": feign, "confidence": "low",
                "recommendation": "Manually compare Feign mappings with changed provider endpoints."})
    return {"project_id": str(project_id), "changed_paths": sorted(set(changed_paths)),
            "changed_types": sorted(changed_types), "changed_packages": sorted(changed_packages),
            "consumer_findings": findings,
            "projects_scanned": len({f["project_id"] for f in other_files if f["project_id"] != str(project_id)}),
            "analysis_mode": "static cross-project source matching",
            "limitations": ["Only indexed projects/refs are scanned.", "Exact imported type matches are strong evidence of source dependency, not proof of runtime impact.", "Endpoint compatibility is not fully resolved; Feign client hints require manual route comparison.", "Java parsing is regex-based, not compiler-backed."]}
