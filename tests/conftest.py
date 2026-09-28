"""Shared pytest fixtures for kdp-coloring-book-generator tests."""

import pytest
import tempfile
import yaml
from pathlib import Path


@pytest.fixture
def temp_dir():
    """Create a temporary directory for test outputs."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def sample_themes_yaml(temp_dir):
    """Create a sample themes.yaml for testing."""
    themes = {
        "pets": {
            "display_name": "Cute Pets",
            "subjects": [
                "cute puppy playing",
                "kitten with yarn",
                "hamster in wheel",
                "goldfish in bowl",
                "parrot on perch",
            ],
            "title_templates": [
                "Adorable {theme} Coloring Book for Kids",
            ],
        },
        "garden": {
            "display_name": "Garden Scenes",
            "subjects": [
                "flowers blooming",
                "butterfly on flower",
                "watering can",
                "garden tools",
            ],
            "title_templates": [
                "Beautiful {theme} Coloring Book for Kids",
            ],
        },
        "animals": {
            "display_name": "Wild Animals",
            "subjects": [
                "lion resting",
                "elephant walking",
                "giraffe eating leaves",
                "monkey hanging",
            ],
            "title_templates": [
                "Amazing {theme} Coloring Book for Kids",
            ],
        },
    }
    themes_path = temp_dir / "themes.yaml"
    with open(themes_path, "w") as f:
        yaml.dump(themes, f)
    return themes_path


@pytest.fixture
def sample_config_yaml(temp_dir):
    """Create a sample config.yaml for testing."""
    config = {
        "page": {
            "width_in": 8.5,
            "height_in": 11.0,
            "margin_in": 0.5,
            "bleed_in": 0.125,
        },
        "defaults": {
            "paper": "white",
            "pages": 25,
            "author": "Test Author",
            "spine_factor_white": 0.002252,
            "spine_factor_cream": 0.0025,
        },
        "image": {
            "width_px": 2550,
            "height_px": 3300,
            "retries": 4,
            "backoff_base_sec": 2.0,
            "provider": "cloudflare",
            "cloudflare_steps": 4,
        },
        "generation": {
            "prompt_suffix": "coloring page, black and white line drawing, outline only",
            "avoid_prompt": "solid black areas, shading, gray, hatching, gradients, color",
            "anatomy_check": "correct anatomy, proper proportions",
            "theme_constraint": "",
        },
        "theme_lock": {
            "pets": {
                "constraint": "THEME LOCK (pets): The main subject MUST be a pet animal"
            }
        },
    }
    config_path = temp_dir / "config.yaml"
    with open(config_path, "w") as f:
        yaml.dump(config, f)
    return config_path


@pytest.fixture
def mock_env(monkeypatch):
    """Mock environment variables for Cloudflare credentials."""
    monkeypatch.setenv("CLOUDFLARE_ACCOUNT_ID", "test-account-1")
    monkeypatch.setenv("CLOUDFLARE_API_TOKEN", "test-token-1")
    monkeypatch.setenv("AUTHOR", "Test Author")


# Add the project src to path for imports
import sys
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))