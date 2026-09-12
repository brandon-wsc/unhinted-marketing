import uuid
from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from internal.auth.jwt import TOKEN_TYPE_ACCESS, decode_token
from internal.auth.service import get_user_with_memberships
from internal.memory.database import get_db
from internal.memory.models import User

bearer_scheme = HTTPBearer(auto_error=False)


async def resolve_current_user(
    credentials: HTTPAuthorizationCredentials | None,
    db: AsyncSession,
) -> User:
    """Load the bearer user inside an already-open session.

    SSE must call this from a short-lived ``open_session()`` rather than
    ``Depends(get_current_user)`` — FastAPI keeps dependency sessions open
    until the response finishes, which for a stream is the whole connection.
    """
    if not credentials or credentials.scheme.lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        payload = decode_token(credentials.credentials, TOKEN_TYPE_ACCESS)
        user_id = uuid.UUID(payload["sub"])
    except (ValueError, KeyError):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        ) from None

    user = await get_user_with_memberships(db, user_id)
    if not user or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found or inactive",
        )
    return user


async def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> User:
    return await resolve_current_user(credentials, db)
