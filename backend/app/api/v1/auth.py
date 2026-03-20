from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, EmailStr
from sqlalchemy import select

from app.api.deps import CurrentUser, AdminUser, DbSession
from app.models.user import User
from app.core.config import get_settings

router = APIRouter()
settings = get_settings()


class InviteRequest(BaseModel):
    email: EmailStr


class UserResponse(BaseModel):
    id: str
    email: str
    name: str
    role: str

    model_config = {"from_attributes": True}


class UserListResponse(BaseModel):
    id: str
    email: str
    name: str
    role: str

    model_config = {"from_attributes": True}


@router.get("/me", response_model=UserResponse)
async def get_current_user(user: CurrentUser, db: DbSession):
    """Get the current authenticated user."""
    return UserResponse(
        id=str(user.id),
        email=user.email,
        name=user.name,
        role=user.role,
    )


@router.post("/invite", status_code=status.HTTP_201_CREATED)
async def invite_user(request: InviteRequest, admin: AdminUser, db: DbSession):
    """Invite a new user by email (admin only).

    Creates the user in Supabase Auth and sends an invite email.
    """
    from supabase import create_client

    supabase = create_client(settings.supabase_url, settings.supabase_service_key)

    try:
        result = supabase.auth.admin.invite_user_by_email(request.email)
        return {
            "status": "invited",
            "email": request.email,
            "message": "Invite email sent. User will appear after they accept.",
        }
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to invite user: {str(e)}",
        )


@router.get("/users", response_model=list[UserListResponse])
async def list_users(admin: AdminUser, db: DbSession):
    """List all users (admin only)."""
    result = await db.execute(select(User).order_by(User.created_at))
    users = result.scalars().all()
    return [
        UserListResponse(id=str(u.id), email=u.email, name=u.name, role=u.role)
        for u in users
    ]


@router.put("/users/{user_id}/role")
async def update_user_role(
    user_id: str,
    admin: AdminUser,
    db: DbSession,
    role: str = "user",
):
    """Update a user's role (admin only)."""
    if role not in ("admin", "user"):
        raise HTTPException(status_code=400, detail="Role must be 'admin' or 'user'")

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    user.role = role
    await db.commit()
    return {"status": "updated", "user_id": user_id, "role": role}
