from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from uuid import UUID
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.api.deps import Principal, current_principal, roles
from app.db.session import get_session
from app.models import Project, Workspace

router = APIRouter(prefix="/projects", tags=["projects"])

class ProjectIn(BaseModel):
    workspace_id: UUID
    name: str = Field(min_length=2, max_length=160)
    slug: str = Field(pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")

@router.post("", status_code=201)
async def create(body: ProjectIn, p: Principal = Depends(roles("owner", "admin", "developer")),
                 db: AsyncSession = Depends(get_session)):
    workspace = (await db.execute(select(Workspace).where(
        Workspace.id == body.workspace_id,
        Workspace.organization_id == p.tenant_id))).scalar_one_or_none()
    if workspace is None:
        raise HTTPException(404, "Workspace not found")
    item = Project(organization_id=p.tenant_id, workspace_id=workspace.id,
                   name=body.name, slug=body.slug)
    db.add(item)
    await db.flush()
    await db.refresh(item)
    return {"id": item.id, "workspace_id": item.workspace_id,
            "name": item.name, "slug": item.slug}

@router.get("")
async def list_all(p: Principal = Depends(current_principal),
                   db: AsyncSession = Depends(get_session)):
    rows = (await db.execute(select(Project).where(
        Project.organization_id == p.tenant_id))).scalars().all()
    return [{"id": x.id, "workspace_id": x.workspace_id,
             "name": x.name, "slug": x.slug} for x in rows]
