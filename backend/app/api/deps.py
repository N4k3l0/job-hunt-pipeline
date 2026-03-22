from typing import Annotated
from uuid import UUID

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import verify_token, decode_token_claims
from app.core.database import get_db
from app.models.user import User

security = HTTPBearer()

DbSession = Annotated[AsyncSession, Depends(get_db)]


async def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(security)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> User:
    """Verify JWT token and return the User record, creating it on first login."""
    token = credentials.credentials
    user_id = verify_token(token)
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
        )

    # Look up user in our database
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()

    if not user:
        # First login — auto-create user record via upsert
        claims = decode_token_claims(token)
        email = claims.get("email", "unknown@example.com")

        # First user ever is automatically admin
        count_result = await db.execute(select(User))
        is_first_user = len(count_result.scalars().all()) == 0

        stmt = pg_insert(User).values(
            id=user_id,
            email=email,
            name=email.split("@")[0],
            role="admin" if is_first_user else "user",
        ).on_conflict_do_nothing(index_elements=["id"])
        await db.execute(stmt)
        await db.commit()

        # Re-fetch the user
        result = await db.execute(select(User).where(User.id == user_id))
        user = result.scalar_one()

    return user


async def get_current_user_id(
    user: Annotated[User, Depends(get_current_user)],
) -> UUID:
    return user.id


async def require_admin(
    user: Annotated[User, Depends(get_current_user)],
) -> User:
    """Require the current user to be an admin."""
    if user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required",
        )
    return user


CurrentUserId = Annotated[UUID, Depends(get_current_user_id)]
CurrentUser = Annotated[User, Depends(get_current_user)]
AdminUser = Annotated[User, Depends(require_admin)]
