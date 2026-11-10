from dataclasses import dataclass
from uuid import UUID
import jwt
from fastapi import Depends, HTTPException
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.security import decode_token
from app.db.session import get_session
from app.models import User, Membership

bearer = HTTPBearer(auto_error=False)

@dataclass
class Principal:
    user_id: UUID
    tenant_id: UUID
    role: str

async def set_db_context(db: AsyncSession, user_id: UUID, tenant_id: UUID | None = None):
    # true = transaction-local; it is cleared automatically on commit/rollback.
    await db.execute(
        text("SELECT set_config('app.current_user_id', :user_id, true)"),
        {"user_id": str(user_id)},
    )
    if tenant_id is not None:
        await db.execute(
            text("SELECT set_config('app.current_tenant_id', :tenant_id, true)"),
            {"tenant_id": str(tenant_id)},
        )

async def current_principal(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    db: AsyncSession = Depends(get_session),
) -> Principal:
    if credentials is None:
        raise HTTPException(401, "Authentication required")
    try:
        claims = decode_token(credentials.credentials)
        user_id, tenant_id = UUID(claims["sub"]), UUID(claims["tid"])
    except (jwt.PyJWTError, KeyError, ValueError):
        raise HTTPException(401, "Invalid or expired token")

    await set_db_context(db, user_id, tenant_id)
    row = (await db.execute(
        select(User, Membership)
        .join(Membership, Membership.user_id == User.id)
        .where(
            User.id == user_id,
            User.is_active.is_(True),
            Membership.organization_id == tenant_id,
        )
    )).first()
    if row is None:
        raise HTTPException(401, "Membership is no longer active")
    return Principal(row[0].id, tenant_id, row[1].role)

def roles(*allowed):
    async def check(principal: Principal = Depends(current_principal)):
        if principal.role not in allowed:
            raise HTTPException(403, "Insufficient permissions")
        return principal
    return check
