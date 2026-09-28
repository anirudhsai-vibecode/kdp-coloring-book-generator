"""Application configuration for FastAPI + RQ workers."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # App
    app_name: str = "kdp-coloring-book-generator"
    app_host: str = "0.0.0.0"
    app_port: int = 8000
    debug: bool = False

    # Redis / RQ
    redis_url: str = "redis://localhost:6379/0"
    rq_queue_name: str = "book_generation"
    rq_worker_ttl: int = 3600  # 1 hour max job time

    # File storage
    output_dir: str = "output"
    failed_dump_dir: str = "failed_dump"

    # Cloudflare (from env)
    cloudflare_account_id: str = ""
    cloudflare_api_token: str = ""
    cloudflare_account_id_2: str = ""
    cloudflare_api_token_2: str = ""
    cloudflare_account_id_3: str = ""
    cloudflare_api_token_3: str = ""

    # KDP defaults
    default_pages: int = 50
    default_author: str = "Your Name Here"
    paper: str = "white"

    def get_cloudflare_accounts(self) -> list[dict[str, str]]:
        """Return ordered list of configured CF accounts."""
        accounts = []
        for slot, (aid_key, tok_key) in enumerate([
            ("cloudflare_account_id", "cloudflare_api_token"),
            ("cloudflare_account_id_2", "cloudflare_api_token_2"),
            ("cloudflare_account_id_3", "cloudflare_api_token_3"),
        ], start=1):
            account_id = getattr(self, aid_key, "").strip()
            token = getattr(self, tok_key, "").strip()
            if account_id and token:
                accounts.append({
                    "account_id": account_id,
                    "api_token": token,
                    "slot": str(slot),
                    "label": f"cf-account-{slot}",
                })
        return accounts


settings = Settings()


def get_output_path() -> Path:
    """Get the output directory path."""
    return Path(settings.output_dir).resolve()


def get_failed_dump_path(book_dir: Path) -> Path:
    """Get the failed_dump directory for a book."""
    return book_dir / settings.failed_dump_dir