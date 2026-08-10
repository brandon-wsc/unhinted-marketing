import uuid
from typing import Annotated

from fastapi import Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from internal.auth.deps import get_current_user
from internal.memory.database import get_db
from internal.memory.models import User
from internal.memory.repos import get_company, get_org_membership, user_has_org_access

# Tenant roles that may change shared company settings (voice, org catalog).
COMPANY_SETTINGS_EDITOR_ROLES = frozenset({"owner", "admin"})


async def require_company_access(
    company_id: uuid.UUID,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> uuid.UUID:
    company = await get_company(db, company_id)
    if not company:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Company not found")
    if not await user_has_org_access(db, user.id, company_id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")
    return company_id


async def require_company_settings_editor(
    company_id: uuid.UUID,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> uuid.UUID:
    """Owner/admin only — members may read settings but not write."""
    await require_company_access(company_id, user, db)
    membership = await get_org_membership(db, user.id, company_id)
    if not membership or membership.role not in COMPANY_SETTINGS_EDITOR_ROLES:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only company owners or admins can edit settings",
        )
    return company_id
