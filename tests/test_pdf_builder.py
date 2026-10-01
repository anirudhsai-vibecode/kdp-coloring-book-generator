"""Tests for kdp_coloring.pdf_builder module."""

import pytest
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock
from PIL import Image

from kdp_coloring.pdf_builder import (
    build_interior_pdf,
    build_cover_pdf,
    document_spine_formula,
)


def create_test_image(path: Path, size=(2550, 3300), color="white"):
    """Create a test image file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    img = Image.new("RGB", size, color)
    img.save(path)


def test_build_interior_pdf(sample_config_yaml, mock_env, temp_dir):
    """Test building interior PDF with images."""
    from kdp_coloring.config import load_config

    cfg = load_config(sample_config_yaml)

    # Create test images
    images_dir = temp_dir / "images"
    images_dir.mkdir()
    img1 = images_dir / "page_001.png"
    img2 = images_dir / "page_002.png"
    create_test_image(img1)
    create_test_image(img2)

    out_path = temp_dir / "interior.pdf"
    result = build_interior_pdf([img1, img2], out_path, cfg)

    assert result == out_path
    assert out_path.exists()
    assert out_path.stat().st_size > 0


def test_build_interior_pdf_empty_list(sample_config_yaml, mock_env, temp_dir):
    """Test building interior PDF with no images."""
    from kdp_coloring.config import load_config

    cfg = load_config(sample_config_yaml)
    out_path = temp_dir / "interior_empty.pdf"
    result = build_interior_pdf([], out_path, cfg)

    assert result == out_path
    assert out_path.exists()


def test_build_cover_pdf(sample_config_yaml, mock_env, temp_dir):
    """Test building cover PDF."""
    from kdp_coloring.config import load_config

    cfg = load_config(sample_config_yaml)

    # Create a front image
    images_dir = temp_dir / "images"
    images_dir.mkdir()
    front_img = images_dir / "page_001.png"
    create_test_image(front_img)

    out_path = temp_dir / "cover.pdf"
    result = build_cover_pdf(
        title="Test Coloring Book",
        author="Test Author",
        theme_display="Cute Pets",
        page_count=25,
        out_path=out_path,
        front_image=front_img,
        cfg=cfg,
    )

    assert result == out_path
    assert out_path.exists()
    assert out_path.stat().st_size > 0


def test_build_cover_pdf_no_front_image(sample_config_yaml, mock_env, temp_dir):
    """Test building cover PDF without front image."""
    from kdp_coloring.config import load_config

    cfg = load_config(sample_config_yaml)
    out_path = temp_dir / "cover_no_image.pdf"
    result = build_cover_pdf(
        title="Test Coloring Book",
        author="Test Author",
        theme_display="Cute Pets",
        page_count=25,
        out_path=out_path,
        front_image=None,
        cfg=cfg,
    )

    assert result == out_path
    assert out_path.exists()


def test_document_spine_formula(sample_config_yaml, mock_env):
    """Test spine formula documentation."""
    from kdp_coloring.config import load_config

    cfg = load_config(sample_config_yaml)
    formula = document_spine_formula(cfg)

    assert "KDP B&W paperback spine" in formula
    assert "white paper factor" in formula
    assert "cream paper factor" in formula
    assert "active" in formula
    assert "0.002252" in formula
    assert "0.0025" in formula


def test_document_spine_formula_cream_paper(mock_env, temp_dir):
    """Test spine formula for cream paper."""
    import yaml
    from kdp_coloring.config import load_config

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
    formula = document_spine_formula(cfg)

    assert "active (cream): 0.0025" in formula


if __name__ == "__main__":
    pytest.main([__file__, "-v"])