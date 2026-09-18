#!/usr/bin/env python3
"""CLI entrypoint: generate a KDP kids coloring book (interior + cover PDFs)."""

from __future__ import annotations

import argparse
import json
import logging
import random
import sys
from datetime import datetime
from pathlib import Path

# Ensure src/ is on path when running as script
ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

from kdp_coloring.config import cover_size_inches, load_config, spine_width_inches  # noqa: E402
from kdp_coloring.image_gen import generate_page_image, reprocess_raw_images  # noqa: E402
from kdp_coloring.pdf_builder import build_cover_pdf, build_interior_pdf, document_spine_formula  # noqa: E402
from kdp_coloring.themes import (  # noqa: E402
    generate_title,
    list_theme_keys,
    load_themes,
    pick_subjects,
    pick_theme,
    slugify,
)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    cfg = load_config()
    p = argparse.ArgumentParser(
        description="Generate Amazon KDP kids coloring books (ages 3–7).",
    )
    p.add_argument(
        "--pages",
        type=int,
        default=cfg["default_pages"],
        help=f"Number of coloring pages (default: {cfg['default_pages']}; use 25 for free-tier limits)",
    )
    p.add_argument(
        "--theme",
        type=str,
        default=None,
        help="Theme key or display name (default: random). Use --list-themes to see options.",
    )
    p.add_argument("--seed", type=int, default=None, help="RNG seed for reproducibility")
    p.add_argument(
        "--author",
        type=str,
        default=None,
        help='Author name on cover (default: from config / "Your Name Here")',
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Generate placeholder line drawings (no network / no API keys)",
    )
    p.add_argument(
        "--list-themes",
        action="store_true",
        help="Print available themes and exit",
    )
    p.add_argument(
        "--output-dir",
        type=str,
        default=None,
        help="Override output root directory",
    )
    p.add_argument(
        "--reprocess",
        type=str,
        metavar="DIR",
        default=None,
        help=(
            "Re-run outline postprocess on an existing book folder's images/raw/, "
            "then rebuild interior.pdf + cover.pdf. Skips if raw/ is missing."
        ),
    )
    return p.parse_args(argv)


def reprocess_book(book_dir: Path, cfg: dict) -> int:
    """Reprocess raw images and rebuild PDFs for an existing book folder."""
    book_dir = book_dir.resolve()
    if not book_dir.is_dir():
        print(f"Book directory not found: {book_dir}", file=sys.stderr)
        return 2

    try:
        image_paths = reprocess_raw_images(book_dir, cfg)
    except FileNotFoundError as e:
        print(str(e), file=sys.stderr)
        return 1

    interior_path = book_dir / "interior.pdf"
    cover_path = book_dir / "cover.pdf"
    meta_path = book_dir / "metadata.json"

    logging.info("Building interior.pdf…")
    build_interior_pdf(image_paths, interior_path, cfg)

    title = "Coloring Book"
    author = cfg["author"]
    theme_display = "Kids"
    page_count = len(image_paths)
    if meta_path.is_file():
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            title = meta.get("title") or title
            author = meta.get("author") or author
            theme_display = meta.get("theme_display") or theme_display
            page_count = int(meta.get("pages") or page_count)
        except (json.JSONDecodeError, TypeError, ValueError) as e:
            logging.warning("Could not fully read metadata.json: %s", e)

    logging.info("Building cover.pdf…")
    build_cover_pdf(
        title=title,
        author=author,
        theme_display=theme_display,
        page_count=page_count,
        out_path=cover_path,
        front_image=image_paths[0] if image_paths else None,
        cfg=cfg,
    )

    if meta_path.is_file():
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            meta["reprocessed_at"] = datetime.now().isoformat(timespec="seconds")
            meta["paths"] = {
                **(meta.get("paths") or {}),
                "book_dir": str(book_dir),
                "interior_pdf": str(interior_path),
                "cover_pdf": str(cover_path),
                "images_dir": str(book_dir / "images"),
                "raw_images_dir": str(book_dir / "images" / "raw"),
            }
            meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")
        except (json.JSONDecodeError, TypeError, ValueError):
            pass

    print()
    print("Reprocess done!")
    print(f"  Interior: {interior_path}")
    print(f"  Cover:    {cover_path}")
    print(f"  Images:   {book_dir / 'images'} ({len(image_paths)} files)")
    return 0


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )
    args = parse_args(argv)
    cfg = load_config()
    themes = load_themes()

    if args.list_themes:
        for key in list_theme_keys(themes):
            display = themes[key].get("display_name", key)
            n = len(themes[key].get("subjects") or [])
            print(f"  {key:16s}  {display}  ({n} subjects)")
        return 0

    if args.reprocess:
        return reprocess_book(Path(args.reprocess), cfg)

    if args.pages < 1:
        print("--pages must be >= 1", file=sys.stderr)
        return 2

    rng = random.Random(args.seed)
    theme_key, theme = pick_theme(themes, args.theme, rng)
    title = generate_title(theme_key, theme, rng)
    author = args.author or cfg["author"]
    display = theme.get("display_name") or theme_key.replace("_", " ").title()
    subjects = pick_subjects(theme, args.pages, rng)

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    slug = slugify(f"{theme_key}-{title}")[:60]
    out_root = Path(args.output_dir) if args.output_dir else Path(cfg["output_dir"])
    book_dir = out_root / f"{slug}-{stamp}"
    images_dir = book_dir / "images"
    images_dir.mkdir(parents=True, exist_ok=True)

    logging.info("Theme: %s (%s)", display, theme_key)
    logging.info("Title: %s", title)
    logging.info("Pages: %s | dry_run=%s | seed=%s", args.pages, args.dry_run, args.seed)
    logging.info("Output: %s", book_dir)
    logging.info("Spine: %.4f in (%s paper)\n%s", spine_width_inches(args.pages, cfg), cfg["paper"], document_spine_formula(cfg))

    image_paths: list[Path] = []
    for i, subject in enumerate(subjects):
        out_img = images_dir / f"page_{i + 1:03d}.png"
        logging.info("Page %s/%s: %s", i + 1, args.pages, subject)
        generate_page_image(
            subject,
            out_img,
            dry_run=args.dry_run,
            page_index=i,
            seed=args.seed,
            cfg=cfg,
        )
        image_paths.append(out_img)

    interior_path = book_dir / "interior.pdf"
    cover_path = book_dir / "cover.pdf"

    logging.info("Building interior.pdf…")
    build_interior_pdf(image_paths, interior_path, cfg)

    logging.info("Building cover.pdf…")
    build_cover_pdf(
        title=title,
        author=author,
        theme_display=display,
        page_count=args.pages,
        out_path=cover_path,
        front_image=image_paths[0] if image_paths else None,
        cfg=cfg,
    )

    total_w, total_h, spine = cover_size_inches(args.pages, cfg)
    meta = {
        "title": title,
        "author": author,
        "theme_key": theme_key,
        "theme_display": display,
        "pages": args.pages,
        "seed": args.seed,
        "dry_run": args.dry_run,
        "trim_size_in": [cfg["page_width_in"], cfg["page_height_in"]],
        "spine_width_in": round(spine, 6),
        "cover_size_in": [round(total_w, 6), round(total_h, 6)],
        "paper": cfg["paper"],
        "spine_formula": document_spine_formula(cfg),
        "subjects": subjects,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "paths": {
            "book_dir": str(book_dir),
            "interior_pdf": str(interior_path),
            "cover_pdf": str(cover_path),
            "images_dir": str(images_dir),
            "raw_images_dir": str(images_dir / "raw"),
        },
    }
    meta_path = book_dir / "metadata.json"
    meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")

    print()
    print("Done!")
    print(f"  Interior: {interior_path}")
    print(f"  Cover:    {cover_path}")
    print(f"  Metadata: {meta_path}")
    print(f"  Images:   {images_dir} ({len(image_paths)} files)")
    if not args.dry_run:
        print(f"  Raw:      {images_dir / 'raw'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
