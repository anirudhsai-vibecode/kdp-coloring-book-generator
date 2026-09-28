"""Tests for kdp_coloring.pipeline module."""

import pytest
from pathlib import Path

from kdp_coloring.pipeline import generate_book


def test_generate_book_dry_run(sample_config_yaml, mock_env, temp_dir):
    """Test generating a book in dry-run mode."""
    from kdp_coloring.config import load_config

    # Point config to temp dir for output
    cfg = load_config(sample_config_yaml)

    interior, cover, meta = generate_book(
        theme_name="pets",
        pages=5,
        author="Test Author",
        dry_run=True,
        output_root=temp_dir,
    )

    assert interior.exists()
    assert cover.exists()
    assert interior.stat().st_size > 0
    assert cover.stat().st_size > 0

    assert meta["title"] is not None
    assert meta["author"] == "Test Author"
    assert meta["theme_key"] == "pets"
    assert meta["pages"] == 5
    assert "interior" in meta["paths"]
    assert "cover" in meta["paths"]


def test_generate_book_different_themes(sample_config_yaml, mock_env, temp_dir):
    """Test generating books with different themes."""
    for theme in ["pets", "garden", "animals"]:
        interior, cover, meta = generate_book(
            theme_name=theme,
            pages=3,
            author="Test Author",
            dry_run=True,
            output_root=temp_dir,
        )
        assert interior.exists()
        assert cover.exists()
        assert meta["theme_key"] == theme


def test_generate_book_with_seed(sample_config_yaml, mock_env, temp_dir):
    """Test generating a book with a seed for reproducibility."""
    interior1, cover1, meta1 = generate_book(
        theme_name="pets",
        pages=5,
        author="Test Author",
        seed=42,
        dry_run=True,
        output_root=temp_dir,
    )

    # Generate again with same seed
    interior2, cover2, meta2 = generate_book(
        theme_name="pets",
        pages=5,
        author="Test Author",
        seed=42,
        dry_run=True,
        output_root=temp_dir,
    )

    # Should produce same title (and potentially same subjects if RNG is deterministic)
    assert meta1["title"] == meta2["title"]


def test_generate_book_default_author(sample_config_yaml, monkeypatch, temp_dir):
    """Test default author from config when not provided in env."""
    # Set explicit author in env to override the project's .env
    monkeypatch.setenv("AUTHOR", "Config Author")

    interior, cover, meta = generate_book(
        theme_name="pets",
        pages=3,
        author=None,
        dry_run=True,
        output_root=temp_dir,
    )

    # Author from env takes precedence over config.yaml
    assert meta["author"] == "Config Author"


def test_generate_book_random_theme(sample_config_yaml, mock_env, temp_dir):
    """Test generating a book with random theme (None)."""
    from kdp_coloring.themes import load_themes, THEMES_PATH

    themes = load_themes(THEMES_PATH)
    expected_keys = list(themes.keys())

    interior, cover, meta = generate_book(
        theme_name=None,
        pages=3,
        author="Test Author",
        dry_run=True,
        output_root=temp_dir,
    )

    assert interior.exists()
    assert cover.exists()
    assert meta["theme_key"] in expected_keys


def test_generate_book_creates_images_dir(sample_config_yaml, mock_env, temp_dir):
    """Test that images directory is created with page images."""
    interior, cover, meta = generate_book(
        theme_name="pets",
        pages=5,
        author="Test Author",
        dry_run=True,
        output_root=temp_dir,
    )

    images_dir = interior.parent / "images"
    assert images_dir.exists()
    page_images = list(images_dir.glob("page_*.png"))
    assert len(page_images) == 5


if __name__ == "__main__":
    pytest.main([__file__, "-v"])