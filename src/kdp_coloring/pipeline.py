"""Core generation pipeline for coloring books."""

from __future__ import annotations

import json
import logging
import random
from datetime import datetime
from pathlib import Path
from typing import Any

from .config import load_config, cover_size_inches, spine_width_inches
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
    logger.info("Starting book generation: theme=%s, pages=%d, author=%s", theme_key, pages, author)
    logger.info("Book directory: %s", book_dir)

    # 2. Generation
    image_paths: list[Path] = []
    logger.info("Generating %d pages...", pages)
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
        logger.info("Generated page %d/%d: %s", i + 1, pages, subject)

    # 3. PDF Packaging
    logger.info("Building PDFs...")
    interior_path = book_dir / "interior.pdf"
    cover_path = book_dir / "cover.pdf"

    build_interior_pdf(image_paths, interior_path, cfg)
    logger.info("Interior PDF built: %s", interior_path)
    build_cover_pdf(
        title=title,
        author=author,
        theme_display=theme.get("display_name") or theme_key,
        page_count=pages,
        out_path=cover_path,
        front_image=image_paths[0] if image_paths else None,
        cfg=cfg,
    )
    logger.info("Cover PDF built: %s", cover_path)

    # 4. Calculate cover/spine dimensions
    total_w_in, total_h_in, spine_in = cover_size_inches(pages, cfg)
    cover_size = [total_w_in, total_h_in]

    # 5. Failed dump directory
    failed_dump_dir = book_dir / "failed_dump"

    # 6. Metadata - includes all fields required by BookMetadata schema
    metadata = {
        "title": title,
        "author": author,
        "theme_key": theme_key,
        "theme_display": theme.get("display_name") or theme_key,
        "pages": pages,
        "seed": seed,
        "dry_run": dry_run,
        "created_at": datetime.now().isoformat(),
        "interior_pdf": str(interior_path),
        "cover_pdf": str(cover_path),
        "images_dir": str(images_dir),
        "failed_dump_dir": str(failed_dump_dir),
        "spine_width_in": spine_in,
        "cover_size_in": cover_size,
        "paper": cfg.get("paper", "white"),
        "subjects": subjects,
    }

    return interior_path, cover_path, metadata
