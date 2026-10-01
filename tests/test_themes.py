"""Tests for kdp_coloring.themes module."""

import pytest
import tempfile
import yaml
from pathlib import Path

from kdp_coloring.themes import (
    load_themes,
    list_theme_keys,
    pick_theme,
    generate_title,
    pick_subjects,
    is_pet_theme,
    check_theme_subject,
    filter_subjects_for_theme,
    build_prompt,
    slugify,
)


def test_slugify():
    """Test slugify function creates URL-safe slugs."""
    assert slugify("Hello World") == "hello-world"
    assert slugify("Cute Pets!@#") == "cute-pets"
    assert slugify("  spaces  ") == "spaces"
    assert slugify("") == "book"


def test_load_themes(sample_themes_yaml):
    """Test loading themes from YAML file."""
    themes = load_themes(sample_themes_yaml)
    assert isinstance(themes, dict)
    assert "pets" in themes
    assert "garden" in themes
    assert "animals" in themes
    assert themes["pets"]["display_name"] == "Cute Pets"
    assert len(themes["pets"]["subjects"]) == 5


def test_load_themes_empty_raises(temp_dir):
    """Test loading empty themes raises ValueError."""
    empty_path = temp_dir / "empty.yaml"
    empty_path.write_text("")
    with pytest.raises(ValueError, match="No themes found"):
        load_themes(empty_path)


def test_list_theme_keys(sample_themes_yaml):
    """Test listing theme keys."""
    themes = load_themes(sample_themes_yaml)
    keys = list_theme_keys(themes)
    assert keys == ["animals", "garden", "pets"]


def test_pick_theme_by_key(sample_themes_yaml):
    """Test picking theme by key."""
    themes = load_themes(sample_themes_yaml)
    key, theme = pick_theme(themes, "pets")
    assert key == "pets"
    assert theme["display_name"] == "Cute Pets"


def test_pick_theme_by_display_name(sample_themes_yaml):
    """Test picking theme by display name."""
    themes = load_themes(sample_themes_yaml)
    key, theme = pick_theme(themes, "Cute Pets")
    assert key == "pets"


def test_pick_theme_random(sample_themes_yaml):
    """Test picking random theme."""
    themes = load_themes(sample_themes_yaml)
    key, theme = pick_theme(themes)
    assert key in themes
    assert theme == themes[key]


def test_pick_theme_unknown_raises(sample_themes_yaml):
    """Test picking unknown theme raises SystemExit."""
    themes = load_themes(sample_themes_yaml)
    with pytest.raises(SystemExit):
        pick_theme(themes, "nonexistent")


def test_generate_title(sample_themes_yaml):
    """Test title generation."""
    themes = load_themes(sample_themes_yaml)
    theme = themes["pets"]
    title = generate_title("pets", theme)
    assert isinstance(title, str)
    assert "Cute Pets" in title or "Pets" in title


def test_pick_subjects(sample_themes_yaml):
    """Test picking subjects."""
    themes = load_themes(sample_themes_yaml)
    theme = themes["pets"]
    subjects = pick_subjects(theme, 3)
    assert len(subjects) == 3
    assert all(s in theme["subjects"] for s in subjects)


def test_pick_subjects_more_than_pool(sample_themes_yaml):
    """Test picking more subjects than in pool cycles correctly."""
    themes = load_themes(sample_themes_yaml)
    theme = themes["pets"]
    subjects = pick_subjects(theme, 10)
    assert len(subjects) == 10
    assert all(s in theme["subjects"] for s in subjects)


def test_is_pet_theme(sample_themes_yaml):
    """Test pet theme detection."""
    themes = load_themes(sample_themes_yaml)
    assert is_pet_theme("pets", themes["pets"]) is True
    assert is_pet_theme("garden", themes["garden"]) is False
    assert is_pet_theme("my_pets", {"display_name": "My Pets"}) is True
    assert is_pet_theme("wild_animals", {"display_name": "Wild Animals"}) is False


def test_check_theme_subject_pet_theme_valid(sample_themes_yaml):
    """Test check_theme_subject accepts valid pet subjects."""
    themes = load_themes(sample_themes_yaml)
    theme = themes["pets"]

    # Valid pet subjects
    ok, reason = check_theme_subject("cute puppy playing", theme_key="pets", theme=theme)
    assert ok is True
    assert reason == ""

    ok, reason = check_theme_subject("kitten with yarn", theme_key="pets", theme=theme)
    assert ok is True

    ok, reason = check_theme_subject("dog with collar", theme_key="pets", theme=theme)
    assert ok is True


def test_check_theme_subject_pet_theme_rejects_off_theme(sample_themes_yaml):
    """Test check_theme_subject rejects off-theme subjects for pets."""
    themes = load_themes(sample_themes_yaml)
    theme = themes["pets"]

    # Garden chores rejected
    ok, reason = check_theme_subject("garden weeding", theme_key="pets", theme=theme)
    assert ok is False
    assert "pets theme rejects" in reason

    # Farm tools rejected
    ok, reason = check_theme_subject("rake and shovel", theme_key="pets", theme=theme)
    assert ok is False

    # Bare jars rejected
    ok, reason = check_theme_subject("mason jar on shelf", theme_key="pets", theme=theme)
    assert ok is False


def test_check_theme_subject_pet_theme_allows_pet_related_props(sample_themes_yaml):
    """Test check_theme_subject allows pet-related props with pet context."""
    themes = load_themes(sample_themes_yaml)
    theme = themes["pets"]

    # Pet-related props allowed
    ok, reason = check_theme_subject("treat jar for dog", theme_key="pets", theme=theme)
    assert ok is True

    ok, reason = check_theme_subject("leash and collar", theme_key="pets", theme=theme)
    assert ok is True


def test_check_theme_subject_non_pet_theme(sample_themes_yaml):
    """Test check_theme_subject passes for non-pet themes."""
    themes = load_themes(sample_themes_yaml)
    theme = themes["garden"]

    ok, reason = check_theme_subject("garden weeding", theme_key="garden", theme=theme)
    assert ok is True
    assert reason == ""

    ok, reason = check_theme_subject("mason jar on shelf", theme_key="garden", theme=theme)
    assert ok is True


def test_filter_subjects_for_theme(sample_themes_yaml):
    """Test filtering subjects for theme."""
    themes = load_themes(sample_themes_yaml)
    theme = themes["pets"]

    subjects = ["cute puppy", "garden weeding", "kitten with yarn", "rake and shovel"]
    kept, rejected = filter_subjects_for_theme(subjects, theme_key="pets", theme=theme)

    assert "cute puppy" in kept
    assert "kitten with yarn" in kept
    assert len(rejected) == 2
    assert all(r[0] in ["garden weeding", "rake and shovel"] for r in rejected)


def test_build_prompt(sample_themes_yaml, mock_env):
    """Test prompt building."""
    themes = load_themes(sample_themes_yaml)
    theme = themes["pets"]

    prompt = build_prompt("cute puppy", theme_key="pets", theme=theme)
    assert isinstance(prompt, str)
    assert "cute puppy" in prompt
    assert "coloring-book" in prompt  # config uses "coloring-book"
    assert "black" in prompt and "white" in prompt
    assert len(prompt) <= 2048  # Cloudflare limit


def test_build_prompt_truncation(sample_themes_yaml, monkeypatch):
    """Test prompt truncation at 2048 chars."""
    themes = load_themes(sample_themes_yaml)
    theme = themes["pets"]

    # Mock config to use short strings for predictable truncation test
    import kdp_coloring.themes as themes_module
    original_load_config = themes_module.load_config

    def mock_load_config():
        return {
            "prompt_suffix": "coloring page, black and white line drawing, outline only",
            "avoid_prompt": "solid black areas, shading, gray, hatching, gradients, color",
            "anatomy_check": "correct anatomy, proper proportions",
            "theme_constraint": "",
            "theme_lock": {},
        }

    monkeypatch.setattr(themes_module, "load_config", mock_load_config)

    # Build a very long prompt by repeating
    prompt = build_prompt("cute puppy " + "very " * 500, theme_key="pets", theme=theme)
    assert len(prompt) <= 2048

    monkeypatch.setattr(themes_module, "load_config", original_load_config)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])