"""Authentication API endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPBearer

from app.core.token_utils import create_access_token
from app.models.user import User, UserCreate, UserPublic, save_user, get_user_by_email


router = APIRouter(prefix="/api/v1/auth", tags=["auth"])
security = HTTPBearer()


@router.post("/register", response_model=UserPublic)
async def register(user_data: UserCreate):
    """Register a new user."""
    # Check if user exists
    if get_user_by_email(user_data.email):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email already registered",
        )

    # Create user
    user = User.create(user_data.email, user_data.password)
    save_user(user)

    return UserPublic.from_user(user)


@router.post("/login")
async def login(user_data: UserCreate):
    """Login user and return access token."""
    # Get user by email
    user = get_user_by_email(user_data.email)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
        )

    # Verify password
    if not user.verify_password(user_data.password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
        )

    # Create access token
    access_token = create_access_token(user.id)

    return {"access_token": access_token, "token_type": "bearer"}


@router.get("/me", response_model=UserPublic)
async def get_current_user(user: User = Depends(security)):
    """Get current user info."""
    return UserPublic.from_user(user)


@router.post("/logout")
async def logout():
    """Logout endpoint (client-side token removal)."""
    return {"message": "Successfully logged out"}
