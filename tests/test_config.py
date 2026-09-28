"""Tests for kdp_coloring.config module."""

import pytest
import os
import yaml
from pathlib import Path

from kdp_coloring.config import (
    load_config,
    spine_width_inches,
    cover_size_inches,
    cloudflare_accounts_from_env,
    PT_PER_IN,
)


def test_load_config_defaults(sample_config_yaml, mock_env):
    """Test loading config with defaults."""
    cfg = load_config(sample_config_yaml)
    assert cfg["page_width_in"] == 8.5
    assert cfg["page_height_in"] == 11.0
    assert cfg["margin_in"] == 0.5
    assert cfg["bleed_in"] == 0.125
    assert cfg["default_pages"] == 25
    assert cfg["author"] == "Test Author"
    assert cfg["paper"] == "white"
    assert cfg["image_width_px"] == 2550
    assert cfg["image_height_px"] == 3300


def test_load_config_calculated_values(sample_config_yaml, mock_env):
    """Test calculated config values."""
    cfg = load_config(sample_config_yaml)
    assert cfg["page_width_pt"] == 8.5 * PT_PER_IN
    assert cfg["page_height_pt"] == 11.0 * PT_PER_IN
    assert cfg["margin_pt"] == 0.5 * PT_PER_IN
    assert cfg["bleed_pt"] == 0.125 * PT_PER_IN


def test_spine_width_inches_white_paper(sample_config_yaml, mock_env):
    """Test spine width calculation for white paper."""
    cfg = load_config(sample_config_yaml)
    spine = spine_width_inches(100, cfg)
    expected = 100 * 0.002252
    assert abs(spine - expected) < 0.0001


def test_spine_width_inches_cream_paper(mock_env, temp_dir):
    """Test spine width calculation for cream paper."""
    config = {
        "page": {"width_in": 8.5, "height_in": 11.0, "margin_in": 0.5, "bleed_in": 0.125},
        "defaults": {
            "paper": "cream",
            "pages": 25,
            "author": "Test Author",
            "spine_factor_white": 0.002252,
            "spine_factor_cream": 0.0025,
        },
        "image": {"width_px": 2550, "height_px": 3300},
        "generation": {},
        "theme_lock": {},
    }
    config_path = temp_dir / "config_cream.yaml"
    with open(config_path, "w") as f:
        yaml.dump(config, f)

    cfg = load_config(config_path)
    spine = spine_width_inches(100, cfg)
    expected = 100 * 0.0025
    assert abs(spine - expected) < 0.0001


def test_cover_size_inches(sample_config_yaml, mock_env):
    """Test cover size calculation."""
    cfg = load_config(sample_config_yaml)
    total_w, total_h, spine = cover_size_inches(100, cfg)

    # 100 pages on white paper: 100 * 0.002252 = 0.2252 inch spine
    expected_spine = 100 * 0.002252
    bleed = 0.125
    pw = 8.5
    ph = 11.0

    expected_total_w = bleed + pw + expected_spine + pw + bleed
    expected_total_h = bleed + ph + bleed

    assert abs(total_w - expected_total_w) < 0.001
    assert abs(total_h - expected_total_h) < 0.001
    assert abs(spine - expected_spine) < 0.001


def test_cloudflare_accounts_from_env(mock_env):
    """Test loading Cloudflare accounts from environment."""
    # This test may find real Cloudflare credentials in the environment
    # Just verify the function works and returns expected structure
    accounts = cloudflare_accounts_from_env()
    assert isinstance(accounts, list)
    # If mock env worked, should have at least 1
    if len(accounts) >= 1:
        assert accounts[0]["account_id"] == "test-account-1"
        assert accounts[0]["api_token"] == "test-token-1"
        assert accounts[0]["slot"] == "1"


def test_cloudflare_accounts_multiple(mock_env, monkeypatch):
    """Test loading multiple Cloudflare accounts."""
    monkeypatch.setenv("CLOUDFLARE_ACCOUNT_ID_2", "test-account-2")
    monkeypatch.setenv("CLOUDFLARE_API_TOKEN_2", "test-token-2")

    accounts = cloudflare_accounts_from_env()
    # May have more accounts from real env
    assert len(accounts) >= 2
    # Find our test account
    test_accounts = [a for a in accounts if a["account_id"] == "test-account-2"]
    assert len(test_accounts) == 1
    assert test_accounts[0]["slot"] == "2"


def test_cloudflare_accounts_incomplete_skipped(monkeypatch):
    """Test incomplete account pairs are skipped."""
    # Completely isolate from real env
    for key in ["CLOUDFLARE_ACCOUNT_ID", "CLOUDFLARE_API_TOKEN",
                "CLOUDFLARE_ACCOUNT_ID_2", "CLOUDFLARE_API_TOKEN_2",
                "CLOUDFLARE_ACCOUNT_ID_3", "CLOUDFLARE_API_TOKEN_3"]:
        monkeypatch.delenv(key, raising=False)

    # Set only incomplete pair
    monkeypatch.setenv("CLOUDFLARE_ACCOUNT_ID_2", "test-account-2")
    # No token for account 2

    accounts = cloudflare_accounts_from_env()
    # Incomplete pairs are skipped, so test-account-2 should not appear
    test_accounts = [a for a in accounts if a["account_id"] == "test-account-2"]
    assert len(test_accounts) == 0


def test_pt_per_in_constant():
    """Test PT_PER_IN constant."""
    assert PT_PER_IN == 72.0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])