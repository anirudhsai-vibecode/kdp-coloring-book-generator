"""Load configuration defaults from YAML and environment."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

# Project root: .../kdp-coloring-book-generator
PACKAGE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = PACKAGE_DIR.parent.parent
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "config.yaml"
THEMES_PATH = PACKAGE_DIR / "themes.yaml"
OUTPUT_DIR = PROJECT_ROOT / "output"

# Points per inch (PDF)
PT_PER_IN = 72.0

# Env / box-secrets keys for Cloudflare multi-account rotation (slot 1 = primary).
_CF_ACCOUNT_KEYS = (
    ("CLOUDFLARE_ACCOUNT_ID", "CLOUDFLARE_API_TOKEN"),
    ("CLOUDFLARE_ACCOUNT_ID_2", "CLOUDFLARE_API_TOKEN_2"),
    ("CLOUDFLARE_ACCOUNT_ID_3", "CLOUDFLARE_API_TOKEN_3"),
)


def _load_box_card_secrets() -> None:
    """If Grok Bot card secrets exist, inject missing CLOUDFLARE_* into os.environ.

    Secrets live in /home/box/agent-data/box-secrets.json under `card`.
    Never log values.
    """
    secrets_path = Path("/home/box/agent-data/box-secrets.json")
    if not secrets_path.is_file():
        return
    try:
        import json

        data = json.loads(secrets_path.read_text(encoding="utf-8"))
    except Exception:
        return
    card = data.get("card") if isinstance(data, dict) else None
    if not isinstance(card, dict):
        return
    # Primary + rotated accounts; legacy HF/Pollinations keys ignored for live gen.
    secret_keys = [
        "CLOUDFLARE_API_TOKEN",
        "CLOUDFLARE_ACCOUNT_ID",
        "CLOUDFLARE_API_TOKEN_2",
        "CLOUDFLARE_ACCOUNT_ID_2",
        "CLOUDFLARE_API_TOKEN_3",
        "CLOUDFLARE_ACCOUNT_ID_3",
    ]
    for key in secret_keys:
        if os.environ.get(key):
            continue
        val = card.get(key)
        if isinstance(val, str) and val.strip():
            os.environ[key] = val


def load_env() -> None:
    """Load .env from project root, then Grok Bot card secrets if needed."""
    load_dotenv(PROJECT_ROOT / ".env")
    _load_box_card_secrets()


def cloudflare_accounts_from_env() -> list[dict[str, str]]:
    """Return ordered list of {account_id, api_token, slot} for configured CF accounts.

    Slot 1 = CLOUDFLARE_ACCOUNT_ID / CLOUDFLARE_API_TOKEN
    Slot 2 = CLOUDFLARE_ACCOUNT_ID_2 / CLOUDFLARE_API_TOKEN_2
    Slot 3 = CLOUDFLARE_ACCOUNT_ID_3 / CLOUDFLARE_API_TOKEN_3
    Incomplete pairs are skipped. Values never logged.
    """
    accounts: list[dict[str, str]] = []
    for slot, (aid_key, tok_key) in enumerate(_CF_ACCOUNT_KEYS, start=1):
        account_id = (os.environ.get(aid_key) or "").strip()
        token = (os.environ.get(tok_key) or "").strip()
        if account_id and token:
            accounts.append(
                {
                    "account_id": account_id,
                    "api_token": token,
                    "slot": str(slot),
                    "label": f"cf-account-{slot}",
                }
            )
    return accounts


def load_config(path: Path | None = None) -> dict[str, Any]:
    """Load YAML config; fall back to built-in defaults if file missing."""
    load_env()
    cfg_path = path or DEFAULT_CONFIG_PATH
    if cfg_path.is_file():
        with cfg_path.open(encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
    else:
        data = {}

    page = data.get("page", {})
    defaults = data.get("defaults", {})
    image = data.get("image", {})
    generation = data.get("generation", {})
    theme_lock = data.get("theme_lock", {}) or {}

    width_in = float(page.get("width_in", 8.5))
    height_in = float(page.get("height_in", 11.0))
    margin_in = float(page.get("margin_in", 0.5))
    bleed_in = float(page.get("bleed_in", 0.125))

    paper = str(defaults.get("paper", "white")).lower()
    spine_white = float(defaults.get("spine_factor_white", 0.002252))
    spine_cream = float(defaults.get("spine_factor_cream", 0.0025))

    prompt_suffix = generation.get(
        "prompt_suffix",
        "coloring page, black and white line drawing, outline only, "
        "simple bold black outlines, pure white fill interiors, pure white background, "
        "coloring book line art ONLY, NO solid black areas, NO shading, NO gray, "
        "NO hatching fills, NO gradients, NO color, single cute subject centered, "
        "thick clean continuous outlines for kids ages 3-7, original character, "
        "NO text, NO watermark, NO logo, no trademarked characters",
    )
    if isinstance(prompt_suffix, str):
        prompt_suffix = " ".join(prompt_suffix.split())

    anatomy_check = generation.get("anatomy_check", "")
    if isinstance(anatomy_check, str):
        anatomy_check = " ".join(anatomy_check.split())
    else:
        anatomy_check = ""

    theme_constraint_default = generation.get("theme_constraint", "")
    if isinstance(theme_constraint_default, str):
        theme_constraint_default = " ".join(theme_constraint_default.split())
    else:
        theme_constraint_default = ""

    cf_accounts = cloudflare_accounts_from_env()
    primary = cf_accounts[0] if cf_accounts else {}

    return {
        "page_width_in": width_in,
        "page_height_in": height_in,
        "page_width_pt": width_in * PT_PER_IN,
        "page_height_pt": height_in * PT_PER_IN,
        "margin_in": margin_in,
        "margin_pt": margin_in * PT_PER_IN,
        "bleed_in": bleed_in,
        "bleed_pt": bleed_in * PT_PER_IN,
        "default_pages": int(defaults.get("pages", 50)),
        "author": os.getenv("AUTHOR") or str(defaults.get("author", "Your Name Here")),
        "paper": paper,
        "spine_factor": spine_cream if paper == "cream" else spine_white,
        "spine_factor_white": spine_white,
        "spine_factor_cream": spine_cream,
        "image_width_px": int(image.get("width_px", 2550)),
        "image_height_px": int(image.get("height_px", 3300)),
        "retries": int(image.get("retries", 4)),
        "backoff_base_sec": float(image.get("backoff_base_sec", 2.0)),
        # Live generation is Cloudflare-only (no Pollinations/HF fallback).
        "provider": str(image.get("provider", "cloudflare")).lower(),
        "prompt_suffix": prompt_suffix,
        "avoid_prompt": " ".join(str(generation.get("avoid_prompt", "")).split()),
        "anatomy_check": anatomy_check,
        "theme_constraint": theme_constraint_default,
        "theme_lock": theme_lock if isinstance(theme_lock, dict) else {},
        "cloudflare_accounts": cf_accounts,
        "cloudflare_account_id": primary.get("account_id")
        or (os.getenv("CLOUDFLARE_ACCOUNT_ID") or ""),
        "cloudflare_api_token": primary.get("api_token")
        or (os.getenv("CLOUDFLARE_API_TOKEN") or ""),
        "cloudflare_steps": int(image.get("cloudflare_steps", 4)),
        "project_root": PROJECT_ROOT,
        "output_dir": OUTPUT_DIR,
        "themes_path": THEMES_PATH,
    }


def spine_width_inches(page_count: int, cfg: dict[str, Any] | None = None) -> float:
    """
    Calculate KDP paperback spine width in inches.

    Amazon KDP (B&W interior) approximate formula:
      white paper: spine_in = page_count * 0.002252
      cream paper: spine_in = page_count * 0.0025

    Always verify with the KDP Cover Calculator before upload.
    """
    c = cfg or load_config()
    return page_count * float(c["spine_factor"])


def cover_size_inches(
    page_count: int, cfg: dict[str, Any] | None = None
) -> tuple[float, float, float]:
    """
    Return (total_width_in, height_in, spine_in) for a full-wrap cover
    including bleed on all sides.

    Layout: [bleed][back][spine][front][bleed]
    Height: [bleed][page_height][bleed]
    """
    c = cfg or load_config()
    spine = spine_width_inches(page_count, c)
    bleed = float(c["bleed_in"])
    pw = float(c["page_width_in"])
    ph = float(c["page_height_in"])
    total_w = bleed + pw + spine + pw + bleed
    total_h = bleed + ph + bleed
    return total_w, total_h, spine
