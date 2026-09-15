import logging
from uuid import UUID

import jwt
from jwt import PyJWKClient

from app.core.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

# Cache the JWKS client
_jwks_client: PyJWKClient | None = None


def _get_jwks_client() -> PyJWKClient:
    global _jwks_client
    if _jwks_client is None:
        jwks_url = f"{settings.supabase_url}/auth/v1/.well-known/jwks.json"
        _jwks_client = PyJWKClient(jwks_url)
    return _jwks_client


def verify_token(token: str) -> UUID | None:
    """Verify a Supabase JWT and extract the user ID.

    Supports both HS256 (older projects) and ES256 (newer projects).
    """
    try:
        # First, peek at the algorithm
        header = jwt.get_unverified_header(token)
        alg = header.get("alg", "HS256")

        if alg == "HS256":
            # Legacy: symmetric verification with JWT secret
            payload = jwt.decode(
                token,
                settings.supabase_jwt_secret,
                algorithms=["HS256"],
                audience="authenticated",
            )
        else:
            # Modern: asymmetric verification with JWKS
            jwks_client = _get_jwks_client()
            signing_key = jwks_client.get_signing_key_from_jwt(token)
            payload = jwt.decode(
                token,
                signing_key.key,
                algorithms=[alg],
                audience="authenticated",
            )

        user_id = payload.get("sub")
        if not user_id:
            return None
        return UUID(user_id)

    except (jwt.InvalidTokenError, ValueError, Exception) as e:
        logger.debug("Token verification failed: %s", e)
        return None


def decode_token_claims(token: str) -> dict:
    """Decode a JWT to extract claims like email.

    Only call AFTER verify_token has confirmed the token is valid.
    """
    try:
        payload = jwt.decode(token, options={"verify_signature": False})
        return payload
    except Exception:
        return {}
