"""User model and helpers for authentication."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Dict, List

import bcrypt
from pydantic import BaseModel, Field


class User(BaseModel):
    """User model stored in Redis."""
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    email: str
    password_hash: str
    created_at: datetime = datetime.utcnow()
    is_active: bool = True

    @classmethod
    def create(cls, email: str, password: str) -> "User":
        """Create a new user with a hashed password."""
        # bcrypt has a 72-byte limit for passwords
        pw_bytes = password.encode("utf-8")
        if len(pw_bytes) > 72:
            pw_bytes = pw_bytes[:72]
        hashed = bcrypt.hashpw(pw_bytes, bcrypt.gensalt()).decode("utf-8")
        return cls(email=email, password_hash=hashed)

    def verify_password(self, password: str) -> bool:
        """Verify a password against the stored hash."""
        # bcrypt has a 72-byte limit for passwords
        pw_bytes = password.encode("utf-8")
        if len(pw_bytes) > 72:
            pw_bytes = pw_bytes[:72]
        return bcrypt.checkpw(pw_bytes, self.password_hash.encode("utf-8"))


class UserCreate(BaseModel):
    email: str
    password: str


class UserPublic(BaseModel):
    id: str
    email: str
    created_at: datetime

    @classmethod
    def from_user(cls, user: User) -> "UserPublic":
        return cls(id=user.id, email=user.email, created_at=user.created_at)


# ----- Redis key helpers -----

def user_key(user_id: str) -> str:
    """Redis key for a user."""
    return f"user:{user_id}"


def user_jobs_key(user_id: str) -> str:
    """Redis key for a user's jobs set."""
    return f"user_jobs:{user_id}"


# ----- Persistence helpers -----

def _decode_redis_hash(data: Dict[bytes, bytes]) -> Dict[str, str]:
    """Decode a redis.hgetall result into a str: str dict."""
    return {
        k.decode() if isinstance(k, (bytes, bytearray)) else k: v.decode() if isinstance(v, (bytes, bytearray)) else v
        for k, v in data.items()
    }


def save_user(user: User) -> bool:
    """Save user to Redis."""
    from app.core.queue import get_redis_connection
    redis = get_redis_connection()
    user_dict = user.model_dump()
    user_dict["created_at"] = user_dict["created_at"].isoformat()
    user_dict["is_active"] = int(user_dict["is_active"])
    return bool(redis.hset(user_key(user.id), mapping=user_dict))


# ---- Retrieval helpers -----

def get_user(user_id: str) -> User | None:
    """Retrieve user from Redis."""
    from app.core.queue import get_redis_connection
    redis = get_redis_connection()
    data = redis.hgetall(user_key(user_id))
    if not data:
        return None
    decoded = _decode_redis_hash(data)
    decoded["created_at"] = datetime.fromisoformat(decoded["created_at"])
    if "is_active" in decoded:
        decoded["is_active"] = bool(int(decoded["is_active"]))
    return User(**decoded)


# ---- Email lookup -----

def get_user_by_email(email: str) -> User | None:
    """Find user by email (linear scan through users)."""
    from app.core.queue import get_redis_connection
    redis = get_redis_connection()
    cursor = 0
    while True:
        cursor, keys = redis.scan(cursor=cursor, match="user:*")
        for key in keys:
            raw = redis.hgetall(key)
            decoded = _decode_redis_hash(raw)
            if decoded.get("email") == email:
                decoded["created_at"] = datetime.fromisoformat(decoded["created_at"])
                if "is_active" in decoded:
                    decoded["is_active"] = bool(int(decoded["is_active"]))
                return User(**decoded)
        if cursor == 0:
            break
    return None


# ---- Job set helpers -----

def add_job_to_user(user_id: str, job_id: str) -> bool:
    """Add a job ID to a user's job set."""
    from app.core.queue import get_redis_connection
    redis = get_redis_connection()
    return bool(redis.sadd(user_jobs_key(user_id), job_id))


def remove_job_from_user(user_id: str, job_id: str) -> bool:
    """Remove a job ID from a user's job set."""
    from app.core.queue import get_redis_connection
    redis = get_redis_connection()
    return bool(redis.srem(user_jobs_key(user_id), job_id))


def get_user_jobs(user_id: str) -> List[str]:
    """Get all job IDs for a user."""
    from app.core.queue import get_redis_connection
    redis = get_redis_connection()
    return [jid.decode() if isinstance(jid, (bytes, bytearray)) else jid for jid in redis.smembers(user_jobs_key(user_id))]