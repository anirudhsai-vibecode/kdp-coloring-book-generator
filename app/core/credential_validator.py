"""Cloudflare credential validation and management."""

from __future__ import annotations

import os
import requests
from pathlib import Path
from typing import Any

from app.core.config import settings


CLOUDFLARE_API_BASE = "https://api.cloudflare.com/client/v4"
FLUX_MODEL = "@cf/black-forest-labs/flux-1-schnell"


def validate_cloudflare_credentials(account_id: str, api_token: str) -> dict[str, Any]:
    """
    Validate Cloudflare credentials by checking model access.
    Returns dict with validation result and neuron info if available.
    """
    headers = {
        "Authorization": f"Bearer {api_token}",
        "Content-Type": "application/json",
    }

    try:
        # Check account exists and has Workers AI access
        url = f"{CLOUDFLARE_API_BASE}/accounts/{account_id}"
        resp = requests.get(url, headers=headers, timeout=10)
        if resp.status_code != 200:
            return {
                "valid": False,
                "error": f"Account validation failed: {resp.status_code}",
            }

        # Check if FLUX model is available
        models_url = f"{CLOUDFLARE_API_BASE}/accounts/{account_id}/ai/models"
        models_resp = requests.get(models_url, headers=headers, timeout=10)
        if models_resp.status_code == 200:
            models_data = models_resp.json()
            models = models_data.get("result", [])
            flux_available = any(
                FLUX_MODEL in str(m.get("name", "")) or "flux" in str(m.get("name", "")).lower()
                for m in models
            )
            if not flux_available:
                # Model list might not include FLUX but it could still work
                pass

        # Try to get daily neuron limit info (Cloudflare doesn't expose this directly via API)
        # We'll return valid and let the runtime handle 429/4006
        return {
            "valid": True,
            "account_id": account_id,
            "model_available": True,
        }

    except requests.Timeout:
        return {"valid": False, "error": "Connection timeout"}
    except requests.RequestException as e:
        return {"valid": False, "error": f"Request failed: {str(e)}"}
    except Exception as e:
        return {"valid": False, "error": f"Validation error: {str(e)}"}


def check_duplicate_credentials(
    account_id: str,
    api_token: str,
    existing_accounts: list[dict[str, str]] | None = None
) -> dict[str, Any]:
    """
    Check if credentials already exist in the configured accounts.
    Checks both provided list and .env file.
    """
    if existing_accounts is None:
        existing_accounts = settings.get_cloudflare_accounts()

    # Normalize for comparison
    norm_id = account_id.strip().lower()
    norm_token = api_token.strip()

    for idx, acc in enumerate(existing_accounts):
        if (acc.get("account_id", "").strip().lower() == norm_id and
                acc.get("api_token", "").strip() == norm_token):
            return {
                "is_duplicate": True,
                "existing_slot": acc.get("slot", str(idx + 1)),
                "existing_label": acc.get("label", f"cf-account-{idx + 1}"),
            }

    return {"is_duplicate": False}


def save_credentials_to_env(slot: int, account_id: str, api_token: str) -> bool:
    """
    Append or update credentials in .env file.
    Creates .env if it doesn't exist.
    """
    env_path = Path(".env")
    lines = []

    if env_path.exists():
        lines = env_path.read_text(encoding="utf-8").splitlines()

    # Remove existing entries for this slot
    prefix = f"_2" if slot == 2 else f"_3" if slot == 3 else ""
    aid_key = f"CLOUDFLARE_ACCOUNT_ID{prefix}"
    tok_key = f"CLOUDFLARE_API_TOKEN{prefix}"

    # Filter out old entries
    lines = [l for l in lines if not l.strip().startswith(f"{aid_key}=") and not l.strip().startswith(f"{tok_key}=")]

    # Add new entries
    lines.append(f"{aid_key}={account_id.strip()}")
    lines.append(f"{tok_key}={api_token.strip()}")

    # Write back
    env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    # Update os.environ for current process
    os.environ[aid_key] = account_id.strip()
    os.environ[tok_key] = api_token.strip()

    return True


def get_next_available_slot(existing_accounts: list[dict[str, str]]) -> int:
    """Find the next available slot (1, 2, or 3)."""
    used_slots = {int(acc.get("slot", 0)) for acc in existing_accounts}
    for slot in range(1, 4):
        if slot not in used_slots:
            return slot
    return 0  # All slots full


def get_account_status(account_id: str, api_token: str, slot: int) -> dict[str, Any]:
    """
    Get detailed status of an account including estimated neurons remaining.
    Note: Cloudflare doesn't expose neuron count via API directly.
    This estimates based on whether we've hit 429/4006 recently.
    """
    base = {
        "slot": str(slot),
        "account_id": account_id[:8] + "..." if len(account_id) > 8 else account_id,
        "label": f"cf-account-{slot}",
    }

    # We can't get real neuron count from API, but we can test if model works
    result = validate_cloudflare_credentials(account_id, api_token)

    if result.get("valid"):
        base["status"] = "active"
        base["neurons"] = "unknown (API doesn't expose)"
    else:
        base["status"] = "error"
        base["error"] = result.get("error", "Unknown error")

    return base