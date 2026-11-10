from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.api.deps import Principal, current_principal, roles
from app.db.session import get_session
from app.models import Workspace

router = APIRouter(prefix="/workspaces", tags=["workspaces"])

class WorkspaceIn(BaseModel):
    name: str = Field(min_length=2, max_length=160)
    slug: str = Field(pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")

@router.post("", status_code=201)
async def create(body: WorkspaceIn, p: Principal = Depends(roles("owner", "admin")),
                 db: AsyncSession = Depends(get_session)):
    item = Workspace(organization_id=p.tenant_id, name=body.name, slug=body.slug)
    db.add(item)
    await db.flush()
    await db.refresh(item)
    return {"id": item.id, "name": item.name, "slug": item.slug}

@router.get("")
async def list_all(p: Principal = Depends(current_principal),
                   db: AsyncSession = Depends(get_session)):
    rows = (await db.execute(select(Workspace).where(
        Workspace.organization_id == p.tenant_id))).scalars().all()
    return [{"id": x.id, "name": x.name, "slug": x.slug} for x in rows]
