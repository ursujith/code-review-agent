from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.session import get_session
from app.api.deps import set_db_context, Principal, current_principal
from app.models import Organization, User, Membership
from app.core.security import hash_password, verify_password, create_token

router = APIRouter(prefix="/auth", tags=["auth"])

class RegisterIn(BaseModel):
    organization_name: str = Field(min_length=2, max_length=160)
    organization_slug: str = Field(pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
    full_name: str = Field(min_length=2, max_length=160)
    email: EmailStr
    password: str = Field(min_length=12, max_length=128)

class LoginIn(BaseModel):
    email: EmailStr
    password: str

class SwitchOrganizationIn(BaseModel):
    organization_id: UUID

@router.post("/register", status_code=201)
async def register(body: RegisterIn, db: AsyncSession = Depends(get_session)):
    existing = await db.execute(select(User.id).where(User.email == body.email))
    if existing.scalar_one_or_none():
        raise HTTPException(409, "Email is already registered")
    org = Organization(name=body.organization_name, slug=body.organization_slug)
    user = User(email=body.email, full_name=body.full_name,
                password_hash=hash_password(body.password))
    try:
        db.add(org)
        await db.flush()
        db.add(user)
        await db.flush()
        await set_db_context(db, user.id, org.id)
        db.add(Membership(organization_id=org.id, user_id=user.id, role="owner"))
        await db.flush()
    except IntegrityError:
        raise HTTPException(409, "Organization slug or email already exists")
    return {"access_token": create_token(str(user.id), str(org.id)), "token_type": "bearer"}

@router.post("/login")
async def login(body: LoginIn, db: AsyncSession = Depends(get_session)):
    user = (await db.execute(select(User).where(User.email == body.email))).scalar_one_or_none()
    if not user or not user.is_active or not verify_password(body.password, user.password_hash):
        raise HTTPException(401, "Invalid email or password")
    await set_db_context(db, user.id)
    memberships = (await db.execute(
        select(Membership).where(Membership.user_id == user.id).order_by(Membership.id)
    )).scalars().all()
    if not memberships:
        raise HTTPException(403, "No organization membership")
    return {
        "access_token": create_token(str(user.id), str(memberships[0].organization_id)),
        "token_type": "bearer",
        "organization_selection_required": len(memberships) > 1,
    }

@router.get("/organizations")
async def my_organizations(
    principal: Principal = Depends(current_principal),
    db: AsyncSession = Depends(get_session),
):
    # Remove only the tenant filter inside this transaction. The RLS policy
    # still restricts membership rows to the authenticated user_id.
    await db.execute(text("SELECT set_config('app.current_tenant_id', '', true)"))
    rows = (await db.execute(
        select(Organization.id, Organization.name, Organization.slug, Membership.role)
        .join(Membership, Membership.organization_id == Organization.id)
        .where(Membership.user_id == principal.user_id)
        .order_by(Organization.name)
    )).all()
    return [
        {"id": str(row.id), "name": row.name, "slug": row.slug, "role": row.role}
        for row in rows
    ]

@router.post("/switch-organization")
async def switch_organization(
    body: SwitchOrganizationIn,
    principal: Principal = Depends(current_principal),
    db: AsyncSession = Depends(get_session),
):
    # RLS context is already scoped to the current user and current tenant.
    # The membership check is deliberately user-scoped; switching does not grant
    # membership in an organization the user does not belong to.
    await db.execute(text("SELECT set_config('app.current_tenant_id', '', true)"))
    membership = (await db.execute(
        select(Membership).where(
            Membership.user_id == principal.user_id,
            Membership.organization_id == body.organization_id,
        )
    )).scalar_one_or_none()
    if membership is None:
        raise HTTPException(403, "You are not a member of this organization")
    return {
        "access_token": create_token(str(principal.user_id), str(body.organization_id)),
        "token_type": "bearer",
    }
