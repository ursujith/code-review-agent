"""Heuristic Spring Boot architecture inventory and change-impact analysis.

This module deliberately reports evidence and confidence rather than claiming a
complete call graph. Java parsing is regex-based; production-grade resolution
should later use JavaParser/JDT and build-tool dependency metadata.
"""
from __future__ import annotations

import re
from collections import defaultdict
from pathlib import Path
from typing import Any

from app.knowledge import _connect

JAVA_CLASS = re.compile(r"\b(class|interface|enum|record)\s+([A-Z][A-Za-z0-9_]*)")
JAVA_IMPORT = re.compile(r"^\s*import\s+(?:static\s+)?([\w.]+);", re.M)
ANNOTATION = re.compile(r"@(GetMapping|PostMapping|PutMapping|PatchMapping|DeleteMapping|RequestMapping)\s*(?:\((.*?)\))?", re.S)
PATH_VALUE = re.compile(r"""(?:value|path)?\s*=\s*["']([^"']+)["']|^\s*["']([^"']+)["']""")
FIELD = re.compile(r"^\s*(?:private|protected|public)\s+(?:final\s+)?([\w<>?,.\[\] ]+)\s+([a-zA-Z_]\w*)\s*(?:=|;)", re.M)
ENTITY_ANNOTATIONS = {"Entity", "Table", "Embeddable"}
MAPPING_ANNOTATIONS = {"OneToOne", "OneToMany", "ManyToOne", "ManyToMany"}
HTTP_CLIENT_HINTS = ("RestTemplate", "WebClient", "FeignClient", "HttpClient", "WebServiceTemplate")
BUILD_FILES = {"pom.xml", "build.gradle", "build.gradle.kts"}


def _annotation_value(args: str | None) -> str | None:
    if not args:
        return None
    match = PATH_VALUE.search(args)
    return (match.group(1) or match.group(2)) if match else None


def _java_inventory(path: str, source: str) -> dict[str, Any]:
    package_match = re.search(r"^\s*package\s+([\w.]+)\s*;", source, re.M)
    package = package_match.group(1) if package_match else ""
    classes = [{"kind": m.group(1), "name": m.group(2)} for m in JAVA_CLASS.finditer(source)]
    imports = sorted(set(JAVA_IMPORT.findall(source)))
    annotations = [m.group(1) for m in re.finditer(r"@([A-Za-z_]\w*)", source)]
    class_name = classes[0]["name"] if classes else Path(path).stem
    endpoints = []
    class_base = None
    for match in ANNOTATION.finditer(source):
        value = _annotation_value(match.group(2))
        if match.group(1) == "RequestMapping":
            class_base = value or ""
            continue
        if value is not None or match.group(1) in {"GetMapping", "PostMapping", "PutMapping", "PatchMapping", "DeleteMapping"}:
            method = match.group(1).replace("Mapping", "").upper()
            line = source.count("\n", 0, match.start()) + 1
            route = (class_base or "") + (value or "")
            endpoints.append({"http_method": method, "path": route or "/", "line": line, "class": class_name})
    is_entity = any(a in ENTITY_ANNOTATIONS for a in annotations)
    entity_fields = []
    if is_entity:
        for field in FIELD.finditer(source):
            line = source.count("\n", 0, field.start()) + 1
            entity_fields.append({"type": " ".join(field.group(1).split()), "name": field.group(2), "line": line})
    relations = []
    for match in re.finditer(r"@(OneToOne|OneToMany|ManyToOne|ManyToMany)\b", source):
        tail = source[match.end():match.end() + 500]
        field = FIELD.search(tail)
        relations.append({
            "relationship": match.group(1),
            "field": field.group(2) if field else None,
            "line": source.count("\n", 0, match.start()) + 1,
            "confidence": "medium" if field else "low",
        })
    client_usage = [hint for hint in HTTP_CLIENT_HINTS if hint in source]
    return {
        "path": path, "package": package, "classes": classes, "imports": imports,
        "annotations": sorted(set(annotations)), "endpoints": endpoints,
        "is_entity": is_entity, "entity_fields": entity_fields,
        "entity_relationships": relations, "http_client_hints": client_usage,
    }


def _read_project(project_id: str, ref: str | None):
    conn = _connect()
    try:
        sql = "SELECT project_name,ref,path,content,start_line FROM code_chunks WHERE project_id=?"
        params: list[Any] = [str(project_id)]
        if ref:
            sql += " AND ref=?"
            params.append(ref)
        rows = conn.execute(sql, params).fetchall()
        return rows
    finally:
        conn.close()


def analyze_spring_project(project_id: str, ref: str | None = None) -> dict:
    rows = _read_project(project_id, ref)
    files: dict[tuple[str, str], dict[int, str]] = defaultdict(dict)
    project_names = set()
    for row in rows:
        project_names.add(row["project_name"])
        for offset, line in enumerate(row["content"].splitlines()):
            files[(row["ref"], row["path"])][row["start_line"] + offset] = line
    inventory, build_dependencies = [], []
    for (selected_ref, path), numbered in sorted(files.items()):
        source = "\n".join(numbered.get(i, "") for i in range(1, max(numbered) + 1))
        suffix = Path(path).suffix.lower()
        if suffix == ".java":
            inventory.append(dict(_java_inventory(path, source), ref=selected_ref))
        elif Path(path).name in BUILD_FILES:
            # Keep dependency coordinates and versions as evidence, without resolving transitive deps.
            if Path(path).name == "pom.xml":
                for match in re.finditer(r"<groupId>\s*([^<]+)</groupId>\s*<artifactId>\s*([^<]+)</artifactId>(?:\s*<version>\s*([^<]+)</version>)?", source):
                    build_dependencies.append({"path": path, "group": match.group(1).strip(), "artifact": match.group(2).strip(), "version": (match.group(3) or "").strip() or None})
            else:
                for match in re.finditer(r"""(?:implementation|api|compileOnly|runtimeOnly)\s*(?:\(|\s)\s*['"]([^'"]+)['"]""", source):
                    build_dependencies.append({"path": path, "coordinate": match.group(1)})
    endpoints = [dict(item, ref=entry["ref"], file=entry["path"]) for entry in inventory for item in entry["endpoints"]]
    entities = [{
        "file": entry["path"], "ref": entry["ref"], "package": entry["package"],
        "classes": entry["classes"], "fields": entry["entity_fields"],
        "relationships": entry["entity_relationships"],
    } for entry in inventory if entry["is_entity"]]
    service_clients = [{
        "file": entry["path"], "ref": entry["ref"], "classes": entry["classes"],
        "client_hints": entry["http_client_hints"], "imports": entry["imports"],
    } for entry in inventory if entry["http_client_hints"]]
    layers = defaultdict(list)
    for entry in inventory:
        path = entry["path"].lower()
        layer = next((name for marker, name in [
            ("/controller/", "controller"), ("/service/", "service"),
            ("/repository/", "repository"), ("/entity/", "entity"),
            ("/model/", "model"), ("/config/", "configuration"),
            ("/configuration/", "configuration"), ("/client/", "client"),
        ] if marker in "/" + path), "other")
        layers[layer].append(entry["path"])
    return {
        "project_id": str(project_id), "project_names": sorted(project_names),
        "refs_analyzed": sorted({key[0] for key in files}),
        "files_analyzed": len(files), "java_files_analyzed": len(inventory),
        "layers": {key: sorted(value) for key, value in sorted(layers.items())},
        "rest_endpoints": endpoints, "jpa_entities": entities,
        "service_clients": service_clients, "build_dependencies": build_dependencies,
        "limitations": [
            "Java extraction is source-pattern based, not a compiler-backed semantic analysis.",
            "Endpoint paths may omit composed class/method path variants or constants.",
            "Service-client hints do not prove a live runtime call relationship.",
            "Build dependencies are direct textual declarations; transitive resolution is not performed.",
        ],
    }


def analyze_change_impact(project_id: str, changed_paths: list[str], ref: str | None = None) -> dict:
    architecture = analyze_spring_project(project_id, ref)
    changed = set(changed_paths)
    affected = []
    for entry in architecture.get("service_clients", []):
        if entry["file"] in changed:
            affected.append({
                "file": entry["file"], "reason": "Changed file contains an HTTP/service client indicator.",
                "confidence": "low", "evidence": entry["client_hints"],
            })
    for entry in architecture.get("rest_endpoints", []):
        if entry["file"] in changed:
            affected.append({
                "file": entry["file"], "reason": "Changed file declares a REST endpoint; review API compatibility.",
                "confidence": "medium",
                "evidence": [f"{entry['http_method']} {entry['path']} at line {entry['line']}"],
            })
    for entity in architecture.get("jpa_entities", []):
        if entity["file"] in changed:
            affected.append({
                "file": entity["file"], "reason": "Changed JPA entity; review schema and persistence compatibility.",
                "confidence": "medium", "evidence": [f"{len(entity['fields'])} fields, {len(entity['relationships'])} relationships"],
            })
    return {
        "project_id": str(project_id), "changed_paths": sorted(changed),
        "potential_impacts": affected,
        "cross_repository_impact": "not_assessed",
        "note": "This first version identifies review hotspots within one indexed project. It does not prove downstream consumers or cross-repository impact.",
    }
