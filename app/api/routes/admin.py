from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from app.security.access_store import create_token, list_tokens, revoke_token, list_audit_logs

router = APIRouter(prefix="/admin/agent-access", tags=["agent access administration"])


class CreateDeveloperRequest(BaseModel):
    username: str = Field(min_length=1, max_length=120)


@router.post("/tokens", status_code=201)
async def issue_developer_token(request: CreateDeveloperRequest) -> dict:
    try:
        return create_token(request.username)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/tokens")
async def get_developer_tokens() -> dict:
    return {"tokens": list_tokens()}


@router.delete("/tokens/{token_id}")
async def revoke_developer_token(token_id: int) -> dict:
    if not revoke_token(token_id):
        raise HTTPException(status_code=404, detail="Active token not found")
    return {"status": "revoked", "token_id": token_id}


@router.get("/audit")
async def get_audit_logs(limit: int = Query(default=100, ge=1, le=500)) -> dict:
    return {"audit_logs": list_audit_logs(limit)}
