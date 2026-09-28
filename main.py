#!/usr/bin/env python3
"""CLI entrypoint: generate a KDP kids coloring book (interior + cover PDFs)."""

from __future__ import annotations

import argparse
import json
import logging
import random
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

# Detail strings use Unicode (—, →, ≤, ≥, ×); on Windows the default console
# codepage is cp1252, so a single print() raises UnicodeEncodeError and the
# whole run aborts with no result. Reconfigure stdout/stderr to UTF-8 at
# startup so results always surface. (Same fix as qa_gate.py ISSUE-001.)
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
        sys.stderr.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except Exception:
        pass

# Ensure src/ is on path when running as script
ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

from kdp_coloring.config import cover_size_inches, load_config, spine_width_inches  # noqa: E402
from kdp_coloring.image_gen import (  # noqa: E402
    CloudflarePausedError,
    generate_page_image,
    reprocess_raw_images,
)
from kdp_coloring.pdf_builder import build_cover_pdf, build_interior_pdf, document_spine_formula  # noqa: E402
from kdp_coloring.themes import (  # noqa: E402
    check_theme_subject,
    filter_subjects_for_theme,
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
    p.add_argument(
        "--skip-exit-gate",
        action="store_true",
        help="Skip Page Factory hard image QA exit gate (not for production handoff)",
    )
    p.add_argument(
        "--max-regen",
        type=int,
        default=0,
        metavar="N",
        help=(
            "Hard cap of exit-gate FAIL regenerations per page. Default 0 = unlimited "
            "until exit-gate PASS (no force-save). Pass N>0 to opt in to a CF-conservation "
            "cap: after N FAILs, force-save the last attempt as the page final."
        ),
    )
    p.add_argument(
        "--require-user-review",
        action=argparse.BooleanOptionalAction,
        default=True,
        help=(
            "After all pages PASS, write AWAITING_USER_REVIEW.json and block packaging "
            "until USER_APPROVED.json appears (default: true). Use --no-require-user-review "
            "or --auto-approve to skip."
        ),
    )
    p.add_argument(
        "--auto-approve",
        action="store_true",
        help="Skip user-review gate (automation); package PDFs immediately after PASS finals.",
    )
    p.add_argument(
        "--packaging-only",
        type=str,
        metavar="DIR",
        default=None,
        help=(
            "Package PDFs for an existing book dir that already has PASS finals. "
            "Respects USER_APPROVED.json / --auto-approve / --require-user-review."
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

    images_dir = book_dir / "images"
    gate_code = run_page_factory_exit_gate(images_dir)
    if gate_code != 0:
        print(
            "EXIT GATE FAIL after reprocess — do NOT hand off to QA until pages PASS.",
            file=sys.stderr,
        )
        return 1

    return package_book(book_dir, image_paths, cfg, require_user_review=False, auto_approve=True)


def run_page_factory_exit_gate(images_path: Path, prior_scenes: Path | None = None) -> int:
    """Hard image QA before PDF / QA handoff. 0=PASS, 1=FAIL."""
    gate = ROOT / "scripts" / "page_factory_exit_gate.py"
    if not gate.is_file():
        # Fall back to qa_gate.py directly
        gate = ROOT / "scripts" / "qa_gate.py"
        cmd = [sys.executable, str(gate), "images", str(images_path)]
    else:
        cmd = [sys.executable, str(gate), str(images_path)]
    if prior_scenes is not None:
        cmd.extend(["--prior-scenes", str(prior_scenes)])
    logging.info("Page Factory exit gate: %s", " ".join(cmd))
    return int(subprocess.run(cmd, cwd=str(ROOT)).returncode)


def gate_single_image(image_path: Path) -> int:
    """Run hard image QA on one file. 0=PASS, 1=FAIL."""
    gate = ROOT / "scripts" / "qa_gate.py"
    cmd = [sys.executable, str(gate), "images", str(image_path)]
    return int(subprocess.run(cmd, cwd=str(ROOT)).returncode)


def _failed_dump_dir(book_dir: Path) -> Path:
    d = book_dir / "failed_dump"
    d.mkdir(parents=True, exist_ok=True)
    return d


def save_failed_dump(
    book_dir: Path,
    *,
    page_num: int,
    attempt: int,
    src_image: Path,
    reason: str,
    subject: str = "",
) -> Path:
    """Copy a FAIL image to failed_dump/page-NN-attempt-K.png and update manifest.json."""
    dump_dir = _failed_dump_dir(book_dir)
    # Zero-padded page number (2+ digits); attempt unpadded is fine but keep readable
    dest_name = f"page-{page_num:02d}-attempt-{attempt}.png"
    dest = dump_dir / dest_name
    if src_image.is_file():
        shutil.copy2(src_image, dest)
    else:
        logging.warning("Failed dump: source missing %s", src_image)

    manifest_path = dump_dir / "manifest.json"
    entries: list[dict] = []
    if manifest_path.is_file():
        try:
            data = json.loads(manifest_path.read_text(encoding="utf-8"))
            if isinstance(data, list):
                entries = data
            elif isinstance(data, dict) and isinstance(data.get("entries"), list):
                entries = data["entries"]
        except (json.JSONDecodeError, TypeError, ValueError):
            entries = []
    entries.append(
        {
            "page": page_num,
            "attempt": attempt,
            "reason": reason,
            "subject": subject,
            "path": str(dest.relative_to(book_dir)) if dest.exists() else dest_name,
            "saved_at": datetime.now().isoformat(timespec="seconds"),
        }
    )
    manifest_path.write_text(
        json.dumps({"entries": entries}, indent=2),
        encoding="utf-8",
    )
    return dest


def print_user_review_block(book_dir: Path) -> None:
    """Print a clear USER REVIEW REQUIRED block listing failed_dump contents."""
    dump_dir = book_dir / "failed_dump"
    manifest_path = dump_dir / "manifest.json"
    print()
    print("=" * 72)
    print("USER REVIEW REQUIRED")
    print("=" * 72)
    print(f"Book: {book_dir}")
    print(
        "All pages now have PASS finals, but AD/user must approve proceed vs "
        "replace any page from failed_dump before packaging."
    )
    if dump_dir.is_dir():
        dumps = sorted(dump_dir.glob("page-*-attempt-*.png"))
        print(f"failed_dump/ ({len(dumps)} image(s)):")
        for p in dumps:
            print(f"  - {p.name}")
        if manifest_path.is_file():
            print(f"  manifest: {manifest_path}")
            try:
                data = json.loads(manifest_path.read_text(encoding="utf-8"))
                for e in data.get("entries") or []:
                    print(
                        f"    page={e.get('page')} attempt={e.get('attempt')} "
                        f"reason={e.get('reason')}"
                    )
            except (json.JSONDecodeError, TypeError, ValueError):
                pass
    else:
        print("failed_dump/: (empty — no exit-gate FAILs during this run)")
    print()
    print("To approve packaging, create:")
    print(f"  {book_dir / 'USER_APPROVED.json'}")
    print("Then re-run:")
    print(f"  python main.py --packaging-only {book_dir} --auto-approve")
    print("Or pass --auto-approve on the generate run to skip this gate.")
    print("=" * 72)
    print()


def write_awaiting_user_review(book_dir: Path, meta: dict | None = None) -> Path:
    path = book_dir / "AWAITING_USER_REVIEW.json"
    payload = {
        "status": "AWAITING_USER_REVIEW",
        "book_dir": str(book_dir),
        "failed_dump": str(book_dir / "failed_dump"),
        "message": (
            "PASS finals exist. AD/user must approve proceed vs replace from "
            "failed_dump. Create USER_APPROVED.json to unlock packaging."
        ),
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "metadata": meta or {},
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


def user_review_unlocked(book_dir: Path, *, require_user_review: bool, auto_approve: bool) -> bool:
    if auto_approve or not require_user_review:
        return True
    return (book_dir / "USER_APPROVED.json").is_file()


def package_book(
    book_dir: Path,
    image_paths: list[Path],
    cfg: dict,
    *,
    title: str = "Coloring Book",
    author: str | None = None,
    theme_display: str = "Kids",
    page_count: int | None = None,
    theme_key: str | None = None,
    subjects: list[str] | None = None,
    seed: int | None = None,
    dry_run: bool = False,
    require_user_review: bool = True,
    auto_approve: bool = False,
    extra_meta: dict | None = None,
) -> int:
    """Build interior/cover PDFs if user review allows; else write AWAITING marker and exit 0."""
    book_dir = Path(book_dir)
    images_dir = book_dir / "images"
    page_count = page_count or len(image_paths)
    author = author or cfg["author"]

    meta_path = book_dir / "metadata.json"
    if meta_path.is_file():
        try:
            existing = json.loads(meta_path.read_text(encoding="utf-8"))
            title = existing.get("title") or title
            author = existing.get("author") or author
            theme_display = existing.get("theme_display") or theme_display
            theme_key = existing.get("theme_key") or theme_key
            page_count = int(existing.get("pages") or page_count)
            subjects = existing.get("subjects") or subjects
            seed = existing.get("seed") if seed is None else seed
            dry_run = bool(existing.get("dry_run", dry_run))
        except (json.JSONDecodeError, TypeError, ValueError):
            pass

    if not user_review_unlocked(
        book_dir, require_user_review=require_user_review, auto_approve=auto_approve
    ):
        print_user_review_block(book_dir)
        meta_stub = {
            "title": title,
            "author": author,
            "theme_key": theme_key,
            "theme_display": theme_display,
            "pages": page_count,
            "subjects": subjects,
            "packaging_blocked": True,
        }
        awaiting = write_awaiting_user_review(book_dir, meta_stub)
        # Ensure metadata exists for later packaging-only
        if not meta_path.is_file():
            meta_path.write_text(json.dumps(meta_stub, indent=2), encoding="utf-8")
        print(f"Wrote {awaiting} — packaging blocked until USER_APPROVED.json (exit 0).")
        return 0

    # Clear awaiting marker if present
    awaiting_path = book_dir / "AWAITING_USER_REVIEW.json"
    if awaiting_path.is_file():
        awaiting_path.unlink()

    interior_path = book_dir / "interior.pdf"
    cover_path = book_dir / "cover.pdf"

    logging.info("Building interior.pdf…")
    build_interior_pdf(image_paths, interior_path, cfg)

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

    total_w, total_h, spine = cover_size_inches(page_count, cfg)
    meta = {
        "title": title,
        "author": author,
        "theme_key": theme_key,
        "theme_display": theme_display,
        "pages": page_count,
        "seed": seed,
        "dry_run": dry_run,
        "trim_size_in": [cfg["page_width_in"], cfg["page_height_in"]],
        "spine_width_in": round(spine, 6),
        "cover_size_in": [round(total_w, 6), round(total_h, 6)],
        "paper": cfg["paper"],
        "spine_formula": document_spine_formula(cfg),
        "subjects": subjects or [],
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "packaging_blocked": False,
        "user_review": {
            "require_user_review": require_user_review,
            "auto_approve": auto_approve,
            "approved": True,
        },
        "paths": {
            "book_dir": str(book_dir),
            "interior_pdf": str(interior_path),
            "cover_pdf": str(cover_path),
            "images_dir": str(images_dir),
            "raw_images_dir": str(images_dir / "raw"),
            "failed_dump_dir": str(book_dir / "failed_dump"),
        },
    }
    if extra_meta:
        meta.update(extra_meta)
    meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")

    # Packaging-ready marker
    (book_dir / "PACKAGING_DONE.json").write_text(
        json.dumps(
            {
                "status": "PACKAGING_DONE",
                "interior_pdf": str(interior_path),
                "cover_pdf": str(cover_path),
                "created_at": datetime.now().isoformat(timespec="seconds"),
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    print()
    print("Done!")
    print(f"  Interior: {interior_path}")
    print(f"  Cover:    {cover_path}")
    print(f"  Metadata: {meta_path}")
    print(f"  Images:   {images_dir} ({len(image_paths)} files)")
    if not dry_run:
        print(f"  Raw:      {images_dir / 'raw'}")
    dump = book_dir / "failed_dump"
    if dump.is_dir() and any(dump.glob("page-*-attempt-*.png")):
        print(f"  Failed dump: {dump}")
    return 0


def generate_page_until_pass(
    *,
    subject: str,
    out_img: Path,
    book_dir: Path,
    page_index: int,
    page_num: int,
    args: argparse.Namespace,
    cfg: dict,
    theme_key: str,
    theme: dict,
) -> None:
    """Generate a page until exit-gate PASS (default) or an opt-in regen cap.

    Raises CloudflarePausedError on CF quota exhaustion (all accounts).
    Default ``--max-regen 0`` = unlimited until PASS (no force-save).
    A positive ``--max-regen`` hard-caps FAIL attempts; after the Nth FAIL, the
    last attempt remains in ``out_img`` as the page final (CF-conservation opt-in).
    """
    # Pre-check theme lock before spending neurons
    ok, reason = check_theme_subject(subject, theme_key=theme_key, theme=theme, cfg=cfg)
    if not ok:
        raise ValueError(reason)

    attempt = 0
    while True:
        attempt += 1
        logging.info(
            "Page %s attempt %s (max_regen=%s): %s",
            page_num,
            attempt,
            args.max_regen,
            subject,
        )
        try:
            generate_page_image(
                subject,
                out_img,
                dry_run=args.dry_run,
                page_index=page_index,
                seed=None
                if attempt == 1
                else (None if args.seed is None else args.seed + attempt * 1000 + page_index),
                cfg=cfg,
                theme_key=theme_key,
                theme=theme,
            )
        except CloudflarePausedError:
            # Do not leave a FAIL as final — remove partial if gate would fail
            if out_img.is_file():
                # Move partial aside rather than keep as final
                save_failed_dump(
                    book_dir,
                    page_num=page_num,
                    attempt=attempt,
                    src_image=out_img,
                    reason="STATUS PAUSED: Cloudflare daily quota exhausted",
                    subject=subject,
                )
                out_img.unlink(missing_ok=True)
            raise

        if args.skip_exit_gate:
            return

        code = gate_single_image(out_img)
        if code == 0:
            logging.info("Exit gate PASS page %s attempt %s", page_num, attempt)
            return

        reason = f"exit-gate FAIL attempt {attempt}"
        dump_path = save_failed_dump(
            book_dir,
            page_num=page_num,
            attempt=attempt,
            src_image=out_img,
            reason=reason,
            subject=subject,
        )
        max_regen = args.max_regen
        if isinstance(max_regen, int) and max_regen > 0 and attempt >= max_regen:
            logging.error(
                "HARD max-regen=%s hit for page %s after %s FAIL(s) — "
                "force-saving last attempt as page final to conserve Cloudflare quota",
                max_regen,
                page_num,
                attempt,
            )
            # Keep out_img in place: the last FAIL is the forced page final.
            return

        logging.warning(
            "Exit gate FAIL page %s attempt %s — dumped %s; regenerating…",
            page_num,
            attempt,
            dump_path.name,
        )
        # Brief pause so CF / gate aren't hammered
        if not args.dry_run:
            time.sleep(0.5)


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

    if args.packaging_only:
        book_dir = Path(args.packaging_only).resolve()
        images_dir = book_dir / "images"
        image_paths = sorted(images_dir.glob("page_*.png"))
        if not image_paths:
            print(f"No page_*.png in {images_dir}", file=sys.stderr)
            return 2
        if not args.skip_exit_gate:
            batch_code = run_page_factory_exit_gate(images_dir)
            if batch_code != 0:
                print("EXIT GATE FAIL — cannot package.", file=sys.stderr)
                return 1
        return package_book(
            book_dir,
            image_paths,
            cfg,
            require_user_review=args.require_user_review,
            auto_approve=args.auto_approve,
        )

    if args.pages < 1:
        print("--pages must be >= 1", file=sys.stderr)
        return 2

    n_cf = len(cfg.get("cloudflare_accounts") or [])
    if not args.dry_run and n_cf == 0:
        print(
            "ERROR: No Cloudflare accounts configured. Set CLOUDFLARE_ACCOUNT_ID + "
            "CLOUDFLARE_API_TOKEN (optional _2 / _3). Pollinations/HF are not used.",
            file=sys.stderr,
        )
        return 2
    if n_cf:
        logging.info("Cloudflare accounts loaded: %s", n_cf)

    rng = random.Random(args.seed)
    theme_key, theme = pick_theme(themes, args.theme, rng)
    title = generate_title(theme_key, theme, rng)
    author = args.author or cfg["author"]
    display = theme.get("display_name") or theme_key.replace("_", " ").title()
    subjects = pick_subjects(theme, args.pages, rng)

    # Theme lock: drop / replace off-theme subjects before generation
    kept, rejected = filter_subjects_for_theme(
        subjects, theme_key=theme_key, theme=theme, cfg=cfg
    )
    if rejected:
        for subj, reason in rejected:
            logging.warning("Theme lock rejected subject before gen: %s (%s)", subj, reason)
        # Refill from pool with theme-valid subjects only
        pool = list(theme.get("subjects") or [])
        valid_pool = [
            s
            for s in pool
            if check_theme_subject(s, theme_key=theme_key, theme=theme, cfg=cfg)[0]
        ]
        if not valid_pool:
            print(
                f"THEME LOCK: no valid subjects for theme '{theme_key}'",
                file=sys.stderr,
            )
            return 2
        while len(kept) < args.pages:
            batch = valid_pool[:]
            rng.shuffle(batch)
            for s in batch:
                if len(kept) >= args.pages:
                    break
                kept.append(s)
        subjects = kept[: args.pages]

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    slug = slugify(f"{theme_key}-{title}")[:60]
    out_root = Path(args.output_dir) if args.output_dir else Path(cfg["output_dir"])
    book_dir = out_root / f"{slug}-{stamp}"
    images_dir = book_dir / "images"
    images_dir.mkdir(parents=True, exist_ok=True)
    _failed_dump_dir(book_dir)  # ensure folder exists

    logging.info("Theme: %s (%s)", display, theme_key)
    logging.info("Title: %s", title)
    logging.info(
        "Pages: %s | dry_run=%s | seed=%s | max_regen=%s",
        args.pages,
        args.dry_run,
        args.seed,
        args.max_regen if args.max_regen is not None else 0,
    )
    logging.info("Output: %s", book_dir)
    logging.info(
        "Spine: %.4f in (%s paper)\n%s",
        spine_width_inches(args.pages, cfg),
        cfg["paper"],
        document_spine_formula(cfg),
    )

    image_paths: list[Path] = []
    try:
        for i, subject in enumerate(subjects):
            out_img = images_dir / f"page_{i + 1:03d}.png"
            logging.info("Page %s/%s: %s", i + 1, args.pages, subject)
            generate_page_until_pass(
                subject=subject,
                out_img=out_img,
                book_dir=book_dir,
                page_index=i,
                page_num=i + 1,
                args=args,
                cfg=cfg,
                theme_key=theme_key,
                theme=theme,
            )
            if not out_img.is_file():
                print(
                    f"STATUS PAUSED / missing final for page {i + 1} — aborting.",
                    file=sys.stderr,
                )
                return 1
            image_paths.append(out_img)
    except CloudflarePausedError as e:
        print(str(e), file=sys.stderr)
        print(
            f"Partial output under {book_dir}. failed_dump/ may contain last attempts. "
            "Resume after ~5:30 AM IST.",
            file=sys.stderr,
        )
        (book_dir / "STATUS_PAUSED.json").write_text(
            json.dumps(
                {
                    "status": "PAUSED",
                    "reason": str(e),
                    "resume_hint_ist": "~5:30 AM IST (Cloudflare free-tier daily reset)",
                    "created_at": datetime.now().isoformat(timespec="seconds"),
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        return 1

    if not args.skip_exit_gate:
        # Final directory sweep (catches anything missed)
        batch_code = run_page_factory_exit_gate(images_dir)
        if batch_code != 0:
            print(
                "EXIT GATE FAIL on batch sweep — do NOT hand off to QA. "
                "Finals were PASS individually; inspect images/ and failed_dump/.",
                file=sys.stderr,
            )
            return 1

    return package_book(
        book_dir,
        image_paths,
        cfg,
        title=title,
        author=author,
        theme_display=display,
        page_count=args.pages,
        theme_key=theme_key,
        subjects=subjects,
        seed=args.seed,
        dry_run=args.dry_run,
        require_user_review=args.require_user_review,
        auto_approve=args.auto_approve,
    )


if __name__ == "__main__":
    raise SystemExit(main())
