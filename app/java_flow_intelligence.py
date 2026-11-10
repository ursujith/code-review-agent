\
"""Heuristic Java/Spring call-flow and contract inventory."""
from __future__ import annotations
import re
from collections import defaultdict
from app.knowledge import _connect

CLASS_RE = re.compile(r"\b(class|interface|enum|record)\s+([A-Z]\w*)")
PACKAGE_RE = re.compile(r"^\s*package\s+([\w.]+)\s*;", re.M)
IMPORT_RE = re.compile(r"^\s*import\s+(?:static\s+)?([\w.]+);", re.M)
METHOD_RE = re.compile(r"(?m)(?:^|[{};])\s*(?:public|protected|private)\s+(?:static\s+|final\s+|synchronized\s+|abstract\s+)*(?:<[^>]+>\s*)?([\w.$<>, ?\[\].]+?)\s+(\w+)\s*\(([^;{}]*)\)\s*(?:throws\s+[\w., ]+)?\s*\{")
FIELD_RE = re.compile(r"(?m)^\s*(?:private|protected|public)\s+(?:final\s+)?([\w.$<>?, \[\]]+)\s+(\w+)\s*(?:=|;)")
ANNOTATION_RE = re.compile(r"@(Get|Post|Put|Patch|Delete|Request)Mapping\s*(?:\((.*?)\))?", re.S)
VALUE_RE = re.compile(r'''(?:value|path)\s*=\s*[\"']([^\"']+)[\"']|^\s*[\"']([^\"']+)[\"']''')

def _files(project_id, ref=None):
    conn = _connect()
    try:
        sql = "SELECT ref,path,start_line,content FROM code_chunks WHERE project_id=?"
        args = [str(project_id)]
        if ref:
            sql += " AND ref=?"; args.append(ref)
        rows = conn.execute(sql, args).fetchall()
    finally:
        conn.close()
    grouped = defaultdict(dict)
    for row in rows:
        for offset, line in enumerate(row["content"].splitlines()):
            grouped[(row["ref"], row["path"])][row["start_line"] + offset] = line
    return [{"ref": key[0], "path": key[1], "source": "\n".join(lines.get(i, "") for i in range(1, max(lines)+1))}
            for key, lines in grouped.items() if lines]

def _layer(path):
    p = "/" + path.lower()
    for marker, layer in [("/controller/", "controller"), ("/service/", "service"), ("/repository/", "repository"), ("/entity/", "entity"), ("/dto/", "dto"), ("/client/", "client"), ("/config/", "configuration")]:
        if marker in p:
            return layer
    return "other"

def _body(source, start):
    opening = source.find("{", start)
    if opening < 0: return ""
    depth = 0; quote = None; escaped = False
    for index in range(opening, len(source)):
        char = source[index]
        if quote:
            if escaped: escaped = False
            elif char == "\\": escaped = True
            elif char == quote: quote = None
            continue
        if char in ("'", '"'): quote = char
        elif char == "{": depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0: return source[opening+1:index]
    return source[opening+1:]

def analyze_java_flows(project_id, ref=None):
    files = _files(project_id, ref)
    inventory = []; by_class = {}
    for file in files:
        if not file["path"].endswith(".java"): continue
        source = file["source"]; match = CLASS_RE.search(source)
        if not match: continue
        name = match.group(2)
        package_match = PACKAGE_RE.search(source)
        package = package_match.group(1) if package_match else ""
        fields = [{"type": " ".join(m.group(1).split()), "name": m.group(2)} for m in FIELD_RE.finditer(source)]
        methods = []
        for method in METHOD_RE.finditer(source):
            body = _body(source, method.start())
            calls = sorted(set(re.findall(r"\b([a-zA-Z_]\w*)\s*\(", body)) - {"if", "for", "while", "switch", "catch", "return", "new", "this", "super"})
            methods.append({"name": method.group(2), "return_type": " ".join(method.group(1).split()), "parameters": method.group(3).strip(), "line": source.count("\n", 0, method.start())+1, "calls": calls})
        item = {"class": name, "package": package, "file": file["path"], "ref": file["ref"], "fields": fields, "methods": methods, "imports": sorted(set(IMPORT_RE.findall(source))), "annotations": sorted(set(re.findall(r"@([A-Za-z_]\w*)", source)))}
        inventory.append(item); by_class[name] = item
    flows = []
    for item in inventory:
        injected = []
        for field in item["fields"]:
            target = field["type"].split("<")[0].split(".")[-1]
            if target in by_class and target != item["class"]:
                injected.append({"field": field["name"], "target_class": target, "target_file": by_class[target]["file"], "confidence": "medium"})
        for method in item["methods"]:
            calls = []
            for target in injected:
                target_item = by_class[target["target_class"]]
                for called in method["calls"]:
                    if any(m["name"] == called for m in target_item["methods"]):
                        calls.append({"method": called, "target_class": target["target_class"], "target_file": target["target_file"], "target_layer": _layer(target["target_file"]), "confidence": "medium"})
            flows.append({"class": item["class"], "file": item["file"], "layer": _layer(item["file"]), "method": method["name"], "line": method["line"], "calls": calls})
    endpoints = []
    for item in inventory:
        source = next(f["source"] for f in files if f["path"] == item["file"] and f["ref"] == item["ref"])
        base = ""
        for ann in ANNOTATION_RE.finditer(source):
            raw = ann.group(2) or ""; value_match = VALUE_RE.search(raw)
            value = (value_match.group(1) or value_match.group(2)) if value_match else ""
            if ann.group(1) == "Request": base = value; continue
            endpoints.append({"class": item["class"], "file": item["file"], "http_method": ann.group(1).upper(), "path": base + value or "/", "line": source.count("\n", 0, ann.start())+1})
    dto_usage = []
    for item in inventory:
        source = next(f["source"] for f in files if f["path"] == item["file"] and f["ref"] == item["ref"])
        used = sorted({name for name in by_class if name.endswith(("DTO", "Dto", "Request", "Response")) and name != item["class"] and re.search(r"\b"+re.escape(name)+r"\b", source)})
        if used: dto_usage.append({"class": item["class"], "file": item["file"], "types": used})
    return {"project_id": str(project_id), "ref": ref, "java_files": len(inventory), "classes": inventory, "method_flows": flows, "rest_contracts": endpoints, "dto_usage": dto_usage, "limitations": ["Static regex-based Java analysis; overloaded methods and complex signatures may be missed.", "Call edges are inferred only through fields whose declared type matches an indexed class.", "No Java compiler, bytecode, runtime trace, or full control-flow analysis is used."]}

def analyze_flow_impact(project_id, changed_paths, ref=None):
    analysis = analyze_java_flows(project_id, ref)
    changed = set(changed_paths)
    changed_classes = {c["class"] for c in analysis["classes"] if c["file"] in changed}
    impacts = []
    for flow in analysis["method_flows"]:
        if flow["file"] in changed: continue
        hits = [call for call in flow["calls"] if call["target_class"] in changed_classes]
        if hits:
            impacts.append({"file": flow["file"], "class": flow["class"], "method": flow["method"], "line": flow["line"], "relationship": "calls_changed_class_method", "evidence": hits, "confidence": "medium", "recommendation": "Review this caller for behavior, exception, and return-contract changes."})
    contracts = [endpoint for endpoint in analysis["rest_contracts"] if endpoint["file"] in changed]
    return {"project_id": str(project_id), "changed_paths": sorted(changed), "changed_classes": sorted(changed_classes), "potential_callers": impacts, "changed_rest_contracts": contracts, "dto_usage": [item for item in analysis["dto_usage"] if item["file"] in changed or set(item["types"]) & changed_classes], "limitations": analysis["limitations"]}
