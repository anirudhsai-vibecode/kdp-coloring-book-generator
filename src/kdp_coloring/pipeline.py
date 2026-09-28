"""Core generation pipeline for coloring books."""

from __future__ import annotations

import json
import logging
import random
from datetime import datetime
from pathlib import Path
from typing import Any

from .config import load_config
from .image_gen import generate_page_image
from .pdf_builder import build_cover_pdf, build_interior_pdf
from .themes import generate_title, load_themes, pick_subjects, pick_theme, slugify

logger = logging.getLogger(__name__)

def generate_book(
    theme_name: str | None,
    pages: int,
    author: str | None,
    seed: int | None = None,
    output_root: Path | None = None,
    dry_run: bool = False,
) -> tuple[Path, Path, dict[str, Any]]:
    """Generate a full KDP coloring book and return PDF paths and metadata."""
    cfg = load_config()
    themes = load_themes()

    # 1. Setup
    rng = random.Random(seed)
    theme_key, theme = pick_theme(themes, theme_name, rng)
    title = generate_title(theme_key, theme, rng)
    author = author or cfg["author"]
    subjects = pick_subjects(theme, pages, rng)

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    slug = slugify(f"{theme_key}-{title}")[:60]
    out_root = output_root or Path(cfg["output_dir"])
    book_dir = out_root / f"{slug}-{stamp}"
    images_dir = book_dir / "images"
    images_dir.mkdir(parents=True, exist_ok=True)

    # 2. Generation
    image_paths: list[Path] = []
    for i, subject in enumerate(subjects):
        out_img = images_dir / f"page_{i + 1:03d}.png"
        generate_page_image(
            subject=subject,
            out_path=out_img,
            dry_run=dry_run,
            page_index=i,
            seed=seed,
            cfg=cfg,
            theme_key=theme_key,
            theme=theme,
        )
        image_paths.append(out_img)

    # 3. PDF Packaging
    interior_path = book_dir / "interior.pdf"
    cover_path = book_dir / "cover.pdf"

    build_interior_pdf(image_paths, interior_path, cfg)
    build_cover_pdf(
        title=title,
        author=author,
        theme_display=theme.get("display_name") or theme_key,
        page_count=pages,
        out_path=cover_path,
        front_image=image_paths[0] if image_paths else None,
        cfg=cfg,
    )

    # 4. Metadata
    metadata = {
        "title": title,
        "author": author,
        "theme_key": theme_key,
        "pages": pages,
        "created_at": datetime.now().isoformat(),
        "paths": {
            "interior": str(interior_path),
            "cover": str(cover_path),
        }
    }

    return interior_path, cover_path, metadata
