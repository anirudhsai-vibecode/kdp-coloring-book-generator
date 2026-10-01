"""Cloudflare credential management API endpoints."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from app.core.config import settings
from app.core.credential_validator import (
    validate_cloudflare_credentials,
    check_duplicate_credentials,
    save_credentials_to_env,
    get_next_available_slot,
    get_account_status,
)

router = APIRouter(prefix="/api/v1/credentials", tags=["credentials"])


class CredentialTestRequest(BaseModel):
    account_id: str = Field(..., min_length=1)
    api_token: str = Field(..., min_length=1)


class CredentialTestResponse(BaseModel):
    valid: bool
    error: str | None = None
    account_id: str | None = None
    model_available: bool | None = None


class CredentialSaveRequest(BaseModel):
    account_id: str = Field(..., min_length=1)
    api_token: str = Field(..., min_length=1)


class CredentialSaveResponse(BaseModel):
    saved: bool
    slot: int | None = None
    message: str
    is_duplicate: bool = False


class CredentialListResponse(BaseModel):
    total: int
    accounts: list[dict]
    current_slot: str | None = None
    exhausted_slots: list[str] = []


@router.post("/test", response_model=CredentialTestResponse)
async def test_credentials(request: CredentialTestRequest) -> CredentialTestResponse:
    """Test Cloudflare credentials without saving."""
    result = validate_cloudflare_credentials(request.account_id, request.api_token)
    return CredentialTestResponse(**result)


@router.post("", response_model=CredentialSaveResponse, status_code=status.HTTP_201_CREATED)
async def save_credentials(request: CredentialSaveRequest) -> CredentialSaveResponse:
    """Save validated Cloudflare credentials to .env."""
    # First validate
    validation = validate_cloudflare_credentials(request.account_id, request.api_token)
    if not validation["valid"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid credentials: {validation.get('error', 'Unknown error')}",
        )

    # Check for duplicates
    existing = settings.get_cloudflare_accounts()
    dup_check = check_duplicate_credentials(request.account_id, request.api_token, existing)
    if dup_check["is_duplicate"]:
        return CredentialSaveResponse(
            saved=False,
            slot=int(dup_check["existing_slot"]),
            message=f"Credentials already exist in Slot {dup_check['existing_slot']} ({dup_check['existing_label']})",
            is_duplicate=True,
        )

    # Find next available slot
    slot = get_next_available_slot(existing)
    if slot == 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="All 3 credential slots are full. Remove an account first.",
        )

    # Save to .env
    save_credentials_to_env(slot, request.account_id, request.api_token)

    # Reload settings to pick up new values
    settings.__init__()

    return CredentialSaveResponse(
        saved=True,
        slot=slot,
        message=f"Credentials saved to Slot {slot}",
        is_duplicate=False,
    )


@router.get("", response_model=CredentialListResponse)
async def list_credentials() -> CredentialListResponse:
    """List all configured Cloudflare accounts with status."""
    accounts = settings.get_cloudflare_accounts()
    enriched = []

    for acc in accounts:
        status_info = get_account_status(
            acc["account_id"],
            acc["api_token"],
            int(acc["slot"]),
        )
        enriched.append({**acc, **status_info})

    return CredentialListResponse(
        total=len(enriched),
        accounts=enriched,
        current_slot="1" if enriched else None,
        exhausted_slots=[a["slot"] for a in enriched if a.get("status") == "error"],
    )


@router.delete("/{slot}")
async def delete_credentials(slot: int) -> dict:
    """Remove credentials from a specific slot."""
    if slot < 1 or slot > 3:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Slot must be 1, 2, or 3",
        )

    prefix = f"_2" if slot == 2 else f"_3" if slot == 3 else ""
    aid_key = f"CLOUDFLARE_ACCOUNT_ID{prefix}"
    tok_key = f"CLOUDFLARE_API_TOKEN{prefix}"

    # Clear from os.environ
    import os
    os.environ.pop(aid_key, None)
    os.environ.pop(tok_key, None)

    # Clear from .env file
    from pathlib import Path
    env_path = Path(".env")
    if env_path.exists():
        lines = env_path.read_text(encoding="utf-8").splitlines()
        lines = [l for l in lines if not l.strip().startswith(f"{aid_key}=") and not l.strip().startswith(f"{tok_key}=")]
        env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    # Reload settings
    settings.__init__()

    return {"deleted": True, "slot": slot, "message": f"Slot {slot} cleared"}


@router.post("/reload")
async def reload_credentials() -> dict:
    """Force reload of Cloudflare credentials from .env."""
    settings.__init__()
    accounts = settings.get_cloudflare_accounts()
    return {"reloaded": True, "total_accounts": len(accounts)}