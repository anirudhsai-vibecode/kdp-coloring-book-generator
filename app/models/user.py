"""User model and helpers for authentication."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

import bcrypt
from pydantic import BaseModel


class User(BaseModel):
    """User model stored in Redis."""
    id: str = str(uuid.uuid4())
    email: str
    password_hash: str
    created_at: datetime = datetime.utcnow()
    is_active: bool = True

    @classmethod
    def create(cls, email: str, password: str) -> User:
        """Create a new user with hashed password."""
        hashed = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
        return cls(email=email, password_hash=hashed)

    def verify_password(self, password: str) -> bool:
        """Verify a password against the stored hash."""
        return bcrypt.checkpw(password.encode("utf-8"), self.password_hash.encode("utf-8"))


class UserCreate(BaseModel):
    email: str
    password: str


class UserPublic(BaseModel):
    id: str
    email: str
    created_at: datetime

    @classmethod
    def from_user(cls, user: User) -> UserPublic:
        return cls(id=user.id, email=user.email, created_at=user.created_at)


def user_key(user_id: str) -> str:
    """Redis key for a user."""
    return f"user:{user_id}"


def user_jobs_key(user_id: str) -> str:
    """Redis key for a user's jobs set."""
    return f"user_jobs:{user_id}"


def save_user(user: User) -> bool:
    """Save user to Redis."""
    from app.core.queue import get_redis_connection
    redis = get_redis_connection()
    user_dict = user.model_dump()
    # Convert datetime to ISO string for Redis
    user_dict["created_at"] = user_dict["created_at"].isoformat()
    return bool(redis.hset(user_key(user.id), mapping=user_dict))


def get_user(user_id: str) -> User | None:
    """Retrieve user from Redis."""
    from app.core.queue import get_redis_connection
    redis = get_redis_connection()
    data = redis.hgetall(user_key(user_id))
    if not data:
        return None
    # Convert ISO string back to datetime
    data["created_at"] = datetime.fromisoformat(data["created_at"])
    return User(**data)


def get_user_by_email(email: str) -> User | None:
    """Find user by email (linear scan through users)."""
    from app.core.queue import get_redis_connection
    redis = get_redis_connection()
    # Scan all user keys
    cursor = "0"
    while cursor != 0:
        cursor, keys = redis.scan(cursor, match="user:*")
        for key in keys:
            data = redis.hgetall(key)
            if data.get("email") == email:
                data["created_at"] = datetime.fromisoformat(data["created_at"])
                return User(**data)
    return None


def add_job_to_user(user_id: str, job_id: str) -> bool:
    """Add job ID to user's job set."""
    from app.core.queue import get_redis_connection
    redis = get_redis_connection()
    return bool(redis.sadd(user_jobs_key(user_id), job_id))


def remove_job_from_user(user_id: str, job_id: str) -> bool:
    """Remove job ID from user's job set."""
    from app.core.queue import get_redis_connection
    redis = get_redis_connection()
    return bool(redis.srem(user_jobs_key(user_id), job_id))


def get_user_jobs(user_id: str) -> list[str]:
    """Get all job IDs for a user."""
    from app.core.queue import get_redis_connection
    redis = get_redis_connection()
    return list(redis.smembers(user_jobs_key(user_id)))
