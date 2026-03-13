"""Per-user rate limiter using slowapi (in-memory storage)."""

import jwt
from slowapi import Limiter
from slowapi.util import get_remote_address
from starlette.requests import Request

from app.core.config import settings
from app.core.security import ALGORITHM


def _get_user_key(request: Request) -> str:
    """Return a rate-limit key based on the authenticated user ID.

    Falls back to the client IP address when the JWT is missing or invalid
    (unauthenticated requests are still rate-limited by IP).
    """
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        token = auth[7:]
        try:
            payload = jwt.decode(
                token,
                settings.SECRET_KEY,
                algorithms=[ALGORITHM],
                options={"verify_exp": False},
            )
            sub = payload.get("sub")
            if sub:
                return f"user:{sub}"
        except Exception:
            pass
    return get_remote_address(request)


limiter = Limiter(key_func=_get_user_key)
