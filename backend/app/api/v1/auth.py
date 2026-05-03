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


class UpdateMeRequest(BaseModel):
    name: str


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


@router.patch("/me", response_model=UserResponse)
async def update_me(request: UpdateMeRequest, user: CurrentUser, db: DbSession):
    """Update the current user's display name.

    Used by the Profile page so the dashboard can greet "Good morning, Olalekan"
    instead of falling back to the email local-part. We trim whitespace and
    enforce a minimum length so a blank submission can't wipe the name."""
    name = (request.name or "").strip()
    if len(name) < 1:
        raise HTTPException(status_code=400, detail="Name cannot be empty")
    if len(name) > 100:
        raise HTTPException(status_code=400, detail="Name too long (max 100 chars)")
    user.name = name
    await db.commit()
    await db.refresh(user)
    return UserResponse(
        id=str(user.id),
        email=user.email,
        name=user.name,
        role=user.role,
    )


@router.post("/invite", status_code=status.HTTP_201_CREATED)
async def invite_user(request: InviteRequest, admin: AdminUser, db: DbSession):
    """Invite a new user by email (admin only).

    Creates the user with email pre-confirmed, then generates a MAGIC
    LINK (not a Supabase invite link) and sends it via Supabase's
    built-in email. The magic link uses implicit/hash tokens, which our
    /auth/callback handles client-side — no code_verifier round-trip
    needed, so the link works on any device.

    Why not `invite_user_by_email`? That uses Supabase's invite flow,
    which falls back to PKCE. The link arrives without a verifier
    cookie and `exchangeCodeForSession` fails, dropping the user on
    /login asking them to type their email all over again.

    We also return `magic_link` so the admin UI can show a copy-paste
    backup if email delivery is delayed.
    """
    from supabase import create_client

    supabase = create_client(settings.supabase_url, settings.supabase_service_key)

    frontend = (settings.frontend_url
                or (settings.cors_origin_list[0] if settings.cors_origin_list else "")
                ).rstrip("/")
    redirect_to = f"{frontend}/auth/callback" if frontend else None

    email = request.email.strip().lower()

    # 1. Make sure the user exists in auth.users with email pre-confirmed.
    #    create_user is idempotent across re-invites: if the row exists we
    #    catch the conflict and proceed to magic-link generation.
    try:
        supabase.auth.admin.create_user({
            "email": email,
            "email_confirm": True,
        })
    except Exception as e:
        # 422 / "already exists" is fine — they have a row, just (re)send
        # the magic link below.
        msg = str(e).lower()
        if "already" not in msg and "registered" not in msg and "exists" not in msg:
            # Anything else (rate limits, validation) is a real error.
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Failed to create user: {e}",
            )

    # 2. Generate the magic link. Passing an email triggers Supabase's
    #    built-in email send via their SMTP config.
    try:
        link_kwargs: dict = {"type": "magiclink", "email": email}
        if redirect_to:
            link_kwargs["options"] = {"redirect_to": redirect_to}
        result = supabase.auth.admin.generate_link(link_kwargs)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to generate magic link: {e}",
        )

    # supabase-py response shape:  result.properties.action_link
    properties = getattr(result, "properties", None) or {}
    if isinstance(properties, dict):
        action_link = properties.get("action_link")
    else:
        action_link = getattr(properties, "action_link", None)

    return {
        "status": "invited",
        "email": email,
        "redirect_to": redirect_to,
        "magic_link": action_link,
        "message": "Magic link sent. If the email is delayed, copy the magic_link and send it manually.",
    }


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
