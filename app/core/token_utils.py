"""JWT token utilities for authentication."""

from datetime import datetime, timedelta
from typing import Any

from jose import jwt
from pydantic import BaseModel


class TokenPayload(BaseModel):
    sub: str  # user_id
    exp: int


SECRET_KEY = "your-secret-key-here-change-in-production"
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24 * 7  # 7 days


def create_access_token(subject: str) -> str:
    """Create JWT access token."""
    expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode = {"sub": subject, "exp": int(expire.timestamp())}
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


def verify_token(token: str) -> TokenPayload | None:
    """Verify JWT token and return payload if valid."""
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return TokenPayload(**payload)
    except Exception:
        return None


def get_token_from_header(authorization: str | None) -> str | None:
    """Extract token from Authorization header."""
    if not authorization:
        return None
    parts = authorization.split()
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return None
    return parts[1]
