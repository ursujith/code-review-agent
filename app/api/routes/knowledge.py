from __future__ import annotations

import os
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.knowledge import (architecture_map, discover_group_projects, feedback_summary,
    index_project, load_rules, record_feedback, retrieve_context, save_rules,
    record_workspace_project, workspace_index_status)
from app.knowledge_intelligence import build_intelligence, dependency_graph, hybrid_retrieve, search_symbols
from app.spring_architecture import analyze_spring_project, analyze_change_impact
from app.cross_service_intelligence import workspace_architecture, cross_project_impact
from app.java_flow_intelligence import analyze_java_flows, analyze_flow_impact

router = APIRouter(prefix="/knowledge", tags=["repository knowledge"])


def _credentials():
    token = os.getenv("GITLAB_TOKEN", "")
    if not token:
        raise HTTPException(status_code=503, detail="GITLAB_TOKEN is not configured")
    return os.getenv("GITLAB_BASE_URL") or os.getenv("GITLAB_URL", "https://gitlab.com"), token


@router.get("/groups/{group_id}/projects")
async def list_group_projects(group_id: str):
    base, token = _credentials()
    try:
        return {"projects": await discover_group_projects(base, token, group_id)}
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


class WorkspaceIndexRequest(BaseModel):
    ref: str | None = Field(default=None, max_length=255)
    max_projects: int = Field(default=20, ge=1, le=50)
    force: bool = False


@router.post("/groups/{group_id}/index")
async def index_gitlab_workspace(group_id: str, request: WorkspaceIndexRequest):
    """Discover and index repositories in a GitLab group, continuing after individual failures."""
    base, token = _credentials()
    try:
        discovered = await discover_group_projects(base, token, group_id)
    except Exception as exc:
        raise HTTPException(status_code=502, detail="GitLab group discovery failed") from exc

    selected = discovered[:request.max_projects]
    previous = workspace_index_status(group_id)
    already_indexed = {
        item["project_id"] for item in previous["projects"]
        if item["status"] == "indexed"
    }
    results = []
    for project in selected:
        project_id = str(project.get("id"))
        if not project_id or project_id == "None":
            continue
        if project_id in already_indexed and not request.force and not request.ref:
            results.append({"project_id": project_id, "project": project.get("path_with_namespace"),
                            "status": "skipped", "reason": "already indexed"})
            continue
        record_workspace_project(group_id, project, "discovered")
        try:
            result = await index_project(base, token, project_id, request.ref)
            record_workspace_project(group_id, project, "indexed", result)
            results.append({**result, "status": "indexed"})
        except Exception as exc:
            safe_message = str(exc)[:500]
            record_workspace_project(group_id, project, "failed", {"error": safe_message})
            results.append({"project_id": project_id, "project": project.get("path_with_namespace"),
                            "status": "failed", "error": safe_message})

    status = workspace_index_status(group_id)
    return {
        "group_id": str(group_id),
        "discovered_projects": len(discovered),
        "processed_projects": len(results),
        "limit_applied": len(discovered) > len(selected),
        "results": results,
        "workspace_status": status,
        "note": "Indexing runs sequentially in this API request. Use max_projects in batches for large groups."
    }


@router.get("/groups/{group_id}/index-status")
def get_workspace_index_status(group_id: str):
    return workspace_index_status(group_id)


class IndexRequest(BaseModel):
    ref: str | None = Field(default=None, max_length=255)


@router.post("/projects/{project_id}/index")
async def index_repository(project_id: str, request: IndexRequest):
    base, token = _credentials()
    try:
        return await index_project(base, token, project_id, request.ref)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail="Repository indexing failed") from exc


class ContextRequest(BaseModel):
    query: str = Field(min_length=1, max_length=20000)
    project_ids: list[str] = Field(default_factory=list, max_length=50)
    limit: int = Field(default=8, ge=1, le=30)
    max_chars: int = Field(default=24000, ge=1000, le=100000)


@router.post("/context")
async def get_context(request: ContextRequest):
    return hybrid_retrieve(request.project_ids, request.query, limit=request.limit, max_chars=request.max_chars)


class RulesRequest(BaseModel):
    instructions: str = Field(default="", max_length=12000)
    required_checks: list[str] = Field(default_factory=list, max_length=100)
    forbidden_patterns: list[str] = Field(default_factory=list, max_length=100)
    severity_overrides: dict[str, str] = Field(default_factory=dict)


@router.put("/projects/{project_id}/rules")
async def put_rules(project_id: str, request: RulesRequest):
    try:
        return save_rules(project_id, request.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/projects/{project_id}/rules")
async def get_rules(project_id: str):
    return {"project_id": project_id, "rules": load_rules(project_id)}


@router.get("/projects/{project_id}/architecture")
async def get_architecture(project_id: str):
    return architecture_map(project_id)


class FeedbackRequest(BaseModel):
    merge_request_iid: int | None = Field(default=None, ge=1)
    finding_fingerprint: str = Field(min_length=8, max_length=128)
    decision: str = Field(pattern="^(accepted|rejected)$")
    reason: str | None = Field(default=None, max_length=2000)


@router.post("/projects/{project_id}/feedback")
async def submit_feedback(project_id: str, request: FeedbackRequest):
    return record_feedback(project_id, request.merge_request_iid, request.finding_fingerprint, request.decision, request.reason)


@router.get("/projects/{project_id}/feedback/summary")
async def get_feedback_summary(project_id: str):
    return {"project_id": project_id, "counts": feedback_summary(project_id)}


class IntelligenceRequest(BaseModel):
    ref: str | None = Field(default=None, max_length=255)


@router.post("/projects/{project_id}/intelligence/build")
def build_repository_intelligence(project_id: str, request: IntelligenceRequest):
    try:
        return build_intelligence(project_id, request.ref)
    except Exception as exc:
        raise HTTPException(status_code=500, detail="Repository intelligence build failed") from exc


@router.get("/projects/{project_id}/symbols")
def find_repository_symbols(project_id: str, query: str, limit: int = 30):
    if limit < 1 or limit > 100:
        raise HTTPException(status_code=400, detail="limit must be between 1 and 100")
    return {"symbols": search_symbols([project_id], query, limit)}


@router.get("/projects/{project_id}/dependencies")
def get_dependency_graph(project_id: str, ref: str | None = None):
    return dependency_graph(project_id, ref)


@router.get("/projects/{project_id}/spring-architecture")
def get_spring_architecture(project_id: str, ref: str | None = None):
    """Inventory Spring Boot REST endpoints, JPA entities, layers and client hints."""
    try:
        return analyze_spring_project(project_id, ref)
    except Exception as exc:
        raise HTTPException(status_code=500, detail="Spring architecture analysis failed") from exc


class ImpactRequest(BaseModel):
    changed_paths: list[str] = Field(min_length=1, max_length=200)
    ref: str | None = Field(default=None, max_length=255)


@router.post("/projects/{project_id}/impact-analysis")
def post_change_impact(project_id: str, request: ImpactRequest):
    try:
        return analyze_change_impact(project_id, request.changed_paths, request.ref)
    except Exception as exc:
        raise HTTPException(status_code=500, detail="Change impact analysis failed") from exc


@router.get("/workspace-architecture")
def get_workspace_architecture():
    """Summarize indexed projects and infer cross-project dependency edges."""
    try:
        return workspace_architecture()
    except Exception as exc:
        raise HTTPException(status_code=500, detail="Workspace architecture analysis failed") from exc


class CrossProjectImpactRequest(BaseModel):
    changed_paths: list[str] = Field(min_length=1, max_length=200)
    ref: str | None = Field(default=None, max_length=255)
    candidate_project_ids: list[str] = Field(default_factory=list, max_length=200)


@router.post("/projects/{project_id}/cross-project-impact")
def post_cross_project_impact(project_id: str, request: CrossProjectImpactRequest):
    """Find indexed repositories that statically reference changed Java types/packages."""
    try:
        return cross_project_impact(project_id, request.changed_paths, request.ref,
                                    request.candidate_project_ids or None)
    except Exception as exc:
        raise HTTPException(status_code=500, detail="Cross-project impact analysis failed") from exc


@router.get("/projects/{project_id}/java-flows")
def get_java_flows(project_id: str, ref: str | None = None):
    """Trace heuristic controller/service/repository method relationships."""
    try:
        return analyze_java_flows(project_id, ref)
    except Exception as exc:
        raise HTTPException(status_code=500, detail="Java flow analysis failed") from exc


@router.post("/projects/{project_id}/java-flow-impact")
def post_java_flow_impact(project_id: str, request: ImpactRequest):
    try:
        return analyze_flow_impact(project_id, request.changed_paths, request.ref)
    except Exception as exc:
        raise HTTPException(status_code=500, detail="Java flow impact analysis failed") from exc
