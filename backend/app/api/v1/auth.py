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

    Uses Supabase's built-in invite_user_by_email which:
      1. Creates the row in auth.users (or 409s if it exists already).
      2. Sends an invite email through Supabase's mailer.

    The link in that email goes to Supabase's /auth/v1/verify?type=invite
    endpoint. After verify, Supabase redirects to redirect_to with HASH
    tokens (implicit flow) because the original invite request carried
    no code_challenge. Our /auth/callback already handles hash tokens
    client-side, so this works on any device.

    Earlier we briefly tried admin.generate_link in here, but the SDK
    docstring confirms it just RETURNS a URL without sending email —
    'to be sent via a custom email provider'. So no email ever went
    out, and we were patching the gap with manually-pasted links.
    Reverted to invite_user_by_email which actually sends.

    On 'already invited' errors, we fall back to admin.generate_link
    (type='magiclink') and return the URL so the admin can paste it
    manually — same single magic-link UX, just delivered out-of-band.
    """
    from supabase import create_client

    supabase = create_client(settings.supabase_url, settings.supabase_service_key)

    frontend = (settings.frontend_url
                or (settings.cors_origin_list[0] if settings.cors_origin_list else "")
                ).rstrip("/")
    redirect_to = f"{frontend}/auth/callback" if frontend else None

    email = request.email.strip().lower()

    # Primary path: send the invite email.
    options = {"redirect_to": redirect_to} if redirect_to else None
    try:
        kwargs: dict = {}
        if options:
            kwargs["options"] = options
        supabase.auth.admin.invite_user_by_email(email, **kwargs)
        return {
            "status": "invited",
            "email": email,
            "redirect_to": redirect_to,
            "magic_link": None,
            "message": "Invite email sent. Tap the link in the email to land on the dashboard.",
        }
    except Exception as e:
        msg = str(e).lower()
        already_exists = (
            "already" in msg or "registered" in msg or "exists" in msg
        )
        if not already_exists:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Failed to send invite: {e}",
            )

    # Fallback for 'already exists': they already have a row but
    # invite_user_by_email refuses to re-send. Mint a magic link via
    # generate_link (no email) and return the URL so the admin can
    # paste it via WhatsApp/SMS/etc.
    try:
        link_kwargs: dict = {"type": "magiclink", "email": email}
        if options:
            link_kwargs["options"] = options
        result = supabase.auth.admin.generate_link(link_kwargs)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"User exists but couldn't mint magic link: {e}",
        )
    properties = getattr(result, "properties", None) or {}
    action_link = (
        properties.get("action_link") if isinstance(properties, dict)
        else getattr(properties, "action_link", None)
    )
    return {
        "status": "existing_user",
        "email": email,
        "redirect_to": redirect_to,
        "magic_link": action_link,
        "message": "User already exists — no email sent. Copy the magic_link and send it directly.",
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
