#!/usr/bin/env python3
"""
Hard-FAIL QA gates for KDP coloring-book image pages and PDF packages.

Exit codes:
  0 — all hard checks PASS
  1 — one or more hard FAILs

See qa_checks/THRESHOLDS.md for exact thresholds.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Sequence

import numpy as np
from PIL import Image

try:
    import cv2
except ImportError:  # pragma: no cover
    cv2 = None  # type: ignore

# ---------------------------------------------------------------------------
# Constants (mirrored in qa_checks/THRESHOLDS.md)
# ---------------------------------------------------------------------------

CANVAS_W, CANVAS_H = 2550, 3300
DPI = 300
MARGIN_IN = 0.5
MARGIN_PX = int(MARGIN_IN * DPI)  # 150

SOLID_FILL_AREA_FRAC = 0.02
WIRE_WINDOW = 400
WIRE_STRIDE = 200
WIRE_RUN_LIMIT = 40
HAIRLINE_ROW_STEP = 25
HAIRLINE_MEDIAN_MAX = 5  # median horizontal run < 5 → evaluate thin1
HAIRLINE_THIN1_FRAC = 0.01  # fail if > 1% of runs are length-1

PAGE_W_PT, PAGE_H_PT = 612.0, 792.0
PT_TOL = 0.5
SPINE_TOL_IN = 0.001
BLEED_IN = 0.125
TRIM_W_IN, TRIM_H_IN = 8.5, 11.0
WRAP_H_IN = 11.25
SPINE_TEXT_MIN_IN = 0.25
DEFAULT_SPINE_FACTOR = 0.002252
DEFAULT_DESIGNS = 32
DEFAULT_FRONT_MATTER = 4
AUTHOR_PLACEHOLDER = "Your Name Here"
BARCODE_W_IN, BARCODE_H_IN = 2.0, 1.2

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".webp"}


# ---------------------------------------------------------------------------
# Report helpers
# ---------------------------------------------------------------------------

@dataclass
class CheckResult:
    name: str
    status: str  # PASS | FAIL | WARNING | SKIP
    detail: str = ""
    hard: bool = True

    @property
    def failed_hard(self) -> bool:
        return self.hard and self.status == "FAIL"


@dataclass
class FileReport:
    path: str
    checks: list[CheckResult] = field(default_factory=list)

    @property
    def hard_fail(self) -> bool:
        return any(c.failed_hard for c in self.checks)

    def add(self, name: str, status: str, detail: str = "", hard: bool = True) -> None:
        self.checks.append(CheckResult(name, status, detail, hard))


def _print_report(reports: Sequence[FileReport], title: str) -> int:
    print(f"\n=== {title} ===")
    any_fail = False
    for r in reports:
        overall = "FAIL" if r.hard_fail else "PASS"
        if r.hard_fail:
            any_fail = True
        print(f"\n[{overall}] {r.path}")
        for c in r.checks:
            tag = c.status
            soft = "" if c.hard else " (soft)"
            detail = f" — {c.detail}" if c.detail else ""
            print(f"  {tag:8s} {c.name}{soft}{detail}")
    print()
    if any_fail:
        print("RESULT: FAIL (one or more hard checks failed)")
        return 1
    print("RESULT: PASS")
    return 0


# ---------------------------------------------------------------------------
# Image checks
# ---------------------------------------------------------------------------

def _as_gray(im: Image.Image) -> np.ndarray:
    """Return uint8 grayscale (0=black, 255=white)."""
    return np.array(im.convert("L"), dtype=np.uint8)


def _black_mask(gray: np.ndarray, thr: int = 128) -> np.ndarray:
    """True where ink (near-black)."""
    return gray < thr


def check_canvas(rep: FileReport, im: Image.Image) -> None:
    w, h = im.size
    if w == CANVAS_W and h == CANVAS_H:
        rep.add("canvas", "PASS", f"{w}×{h} portrait")
    else:
        rep.add("canvas", "FAIL", f"got {w}×{h}, need {CANVAS_W}×{CANVAS_H} portrait")


def check_pure_bw(rep: FileReport, im: Image.Image, gray: np.ndarray) -> None:
    if im.mode == "1":
        rep.add("pure_bw", "PASS", "mode=1 (1-bit)")
        return
    mid = int(np.count_nonzero((gray >= 2) & (gray <= 253)))
    # unique colors on RGB or L
    rgb = np.array(im.convert("RGB"))
    # subsample for speed on ncolors estimate if huge — full unique on reshaped
    flat = rgb.reshape(-1, 3)
    # Use view-based unique count
    dtype = np.dtype((np.void, flat.dtype.itemsize * 3))
    uniq = np.unique(flat.view(dtype))
    ncolors = int(uniq.size)
    if mid == 0 and ncolors <= 2:
        rep.add("pure_bw", "PASS", f"ncolors={ncolors}, mid_gray=0")
    else:
        parts = []
        if mid:
            parts.append(f"mid_gray_pixels={mid} (L in 2–253 must be 0)")
        if ncolors > 2:
            parts.append(f"ncolors={ncolors} (≤2 required, or mode 1)")
        rep.add("pure_bw", "FAIL", "; ".join(parts) or "not pure B&W")


def check_margin_ink(rep: FileReport, gray: np.ndarray) -> None:
    h, w = gray.shape
    m = MARGIN_PX
    if h < 2 * m or w < 2 * m:
        rep.add("margin_ink", "FAIL", f"image too small for {m}px margin")
        return
    ink = _black_mask(gray)
    border = np.zeros_like(ink, dtype=bool)
    border[:m, :] = True
    border[-m:, :] = True
    border[:, :m] = True
    border[:, -m:] = True
    count = int(np.count_nonzero(ink & border))
    if count == 0:
        rep.add("margin_ink", "PASS", f"0 ink pixels in {m}px (0.5″) margin")
    else:
        rep.add("margin_ink", "FAIL", f"{count} ink pixels in {m}px margin strip")


def _is_filled_region(mask_cc: np.ndarray, area: int) -> bool:
    """Heuristic: solid fill vs thin stroke ring."""
    if cv2 is None:
        # Fallback: fill ratio in bounding box
        ys, xs = np.where(mask_cc)
        if len(xs) == 0:
            return False
        bw = int(xs.max() - xs.min() + 1)
        bh = int(ys.max() - ys.min() + 1)
        bbox_area = max(1, bw * bh)
        return (area / bbox_area) > 0.55 and bw >= 40 and bh >= 40

    u8 = mask_cc.astype(np.uint8) * 255
    kernel = np.ones((3, 3), np.uint8)
    eroded = cv2.erode(u8, kernel, iterations=2)
    eroded_area = int(np.count_nonzero(eroded))
    if eroded_area > max(500, int(0.15 * area)):
        return True
    ys, xs = np.where(mask_cc)
    if len(xs) == 0:
        return False
    bw = int(xs.max() - xs.min() + 1)
    bh = int(ys.max() - ys.min() + 1)
    bbox_area = max(1, bw * bh)
    return (area / bbox_area) > 0.55 and bw >= 40 and bh >= 40


def check_solid_fills(rep: FileReport, gray: np.ndarray) -> None:
    h, w = gray.shape
    page_area = h * w
    thr_area = int(SOLID_FILL_AREA_FRAC * page_area)
    ink = _black_mask(gray).astype(np.uint8)

    if cv2 is not None:
        n, labels, stats, _ = cv2.connectedComponentsWithStats(ink, connectivity=8)
        offenders = []
        for i in range(1, n):
            area = int(stats[i, cv2.CC_STAT_AREA])
            if area <= thr_area:
                continue
            cc = labels == i
            if _is_filled_region(cc, area):
                offenders.append(area)
        if offenders:
            worst = max(offenders)
            frac = worst / page_area * 100
            rep.add(
                "solid_fills",
                "FAIL",
                f"{len(offenders)} filled region(s) >2% page (worst {worst}px / {frac:.2f}%)",
            )
        else:
            rep.add("solid_fills", "PASS", f"no filled CC > {thr_area} px (~2%)")
        return

    # numpy flood-fill fallback (slower)
    visited = np.zeros_like(ink, dtype=bool)
    offenders = 0
    worst = 0
    ys_all, xs_all = np.where(ink > 0)
    for y0, x0 in zip(ys_all[::50], xs_all[::50]):  # stride seeds
        if visited[y0, x0]:
            continue
        # BFS
        stack = [(y0, x0)]
        visited[y0, x0] = True
        cells = [(y0, x0)]
        while stack:
            y, x = stack.pop()
            for dy, dx in ((0, 1), (0, -1), (1, 0), (-1, 0)):
                ny, nx = y + dy, x + dx
                if 0 <= ny < h and 0 <= nx < w and not visited[ny, nx] and ink[ny, nx]:
                    visited[ny, nx] = True
                    stack.append((ny, nx))
                    cells.append((ny, nx))
        area = len(cells)
        if area > thr_area:
            cc = np.zeros_like(ink, dtype=bool)
            for y, x in cells:
                cc[y, x] = True
            if _is_filled_region(cc, area):
                offenders += 1
                worst = max(worst, area)
    if offenders:
        rep.add("solid_fills", "FAIL", f"{offenders} filled region(s); worst={worst}px")
    else:
        rep.add("solid_fills", "PASS", "no large filled regions (numpy fallback)")


def _count_distinct_thin_lines(win: np.ndarray, horizontal: bool) -> int:
    """
    Count distinct thin straight line strokes in a window.

    Uses morphological opening to keep long thin segments, then collapses
    adjacent rows/cols so a 2–3 px stroke counts as one run (not dozens).
    """
    u8 = (win.astype(np.uint8) * 255)
    if cv2 is not None:
        if horizontal:
            kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (40, 1))
        else:
            kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (1, 40))
        opened = cv2.morphologyEx(u8, cv2.MORPH_OPEN, kernel)
        ink = opened > 0
    else:
        ink = win.astype(bool)

    axis_len = win.shape[1] if horizontal else win.shape[0]
    cross_len = win.shape[0] if horizontal else win.shape[1]
    min_run = max(40, axis_len // 8)
    flags: list[bool] = []
    for i in range(cross_len):
        line = ink[i, :] if horizontal else ink[:, i]
        # longest contiguous run
        padded = np.concatenate(([False], line, [False]))
        d = np.diff(padded.astype(np.int8))
        starts = np.where(d == 1)[0]
        ends = np.where(d == -1)[0]
        lengths = ends - starts
        longest = int(lengths.max()) if lengths.size else 0
        ink_sum = int(line.sum())
        # thin: long run but not a filled band
        flags.append(longest >= min_run and ink_sum <= max(longest + 5, int(axis_len * 0.35)))

    # Collapse consecutive True flags into one distinct line
    count = 0
    prev = False
    for f in flags:
        if f and not prev:
            count += 1
        prev = f
    return count


def check_wire_grid(rep: FileReport, gray: np.ndarray) -> None:
    ink = _black_mask(gray)
    h, w = ink.shape
    worst = 0
    worst_pos = (0, 0)
    for y0 in range(0, max(1, h - WIRE_WINDOW + 1), WIRE_STRIDE):
        for x0 in range(0, max(1, w - WIRE_WINDOW + 1), WIRE_STRIDE):
            win = ink[y0 : y0 + WIRE_WINDOW, x0 : x0 + WIRE_WINDOW]
            if win.shape[0] < WIRE_WINDOW or win.shape[1] < WIRE_WINDOW:
                continue
            score = _count_distinct_thin_lines(win, True) + _count_distinct_thin_lines(win, False)
            if score > worst:
                worst = score
                worst_pos = (x0, y0)
    if worst > WIRE_RUN_LIMIT:
        rep.add(
            "wire_grid",
            "FAIL",
            f"{worst} thin parallel/orthogonal runs in 400×400 @ {worst_pos} (limit {WIRE_RUN_LIMIT})",
        )
    else:
        rep.add("wire_grid", "PASS", f"max window score={worst} (limit {WIRE_RUN_LIMIT})")


def check_hairlines(rep: FileReport, gray: np.ndarray) -> None:
    ink = _black_mask(gray)
    h, w = ink.shape
    runs: list[int] = []
    for y in range(0, h, HAIRLINE_ROW_STEP):
        row = ink[y]
        padded = np.concatenate(([False], row.astype(bool), [False]))
        diffs = np.diff(padded.astype(np.int8))
        starts = np.where(diffs == 1)[0]
        ends = np.where(diffs == -1)[0]
        for s, e in zip(starts, ends):
            runs.append(int(e - s))
    if not runs:
        rep.add("hairlines", "PASS", "no horizontal black runs (blank?)")
        return
    med = float(np.median(runs))
    thin1 = sum(1 for r in runs if r == 1) / len(runs)
    if med < HAIRLINE_MEDIAN_MAX and thin1 > HAIRLINE_THIN1_FRAC:
        rep.add(
            "hairlines",
            "FAIL",
            f"median_h_run={med:.1f}px (<{HAIRLINE_MEDIAN_MAX}), thin1={thin1:.2%} (>{HAIRLINE_THIN1_FRAC:.0%})",
        )
    else:
        rep.add(
            "hairlines",
            "PASS",
            f"median_h_run={med:.1f}px, thin1={thin1:.2%} (n={len(runs)})",
        )


def _normalize_scene(s: str) -> set[str]:
    tokens = "".join(c.lower() if c.isalnum() or c.isspace() else " " for c in s).split()
    stop = {"a", "an", "the", "and", "with", "of", "in", "on", "for", "to"}
    return {t for t in tokens if t not in stop and len(t) > 1}


def check_near_dupe(
    rep: FileReport,
    scene: str | None,
    prior_scenes: Sequence[str] | None,
) -> None:
    if prior_scenes is None:
        rep.add("near_dupe", "SKIP", "no --prior-scenes JSON provided", hard=False)
        return
    if not scene:
        rep.add("near_dupe", "SKIP", "no scene label for this file", hard=False)
        return
    cur = _normalize_scene(scene)
    if not cur:
        rep.add("near_dupe", "SKIP", "empty scene tokens", hard=False)
        return
    best_j = 0.0
    best_prior = ""
    for p in prior_scenes:
        other = _normalize_scene(p)
        if not other:
            continue
        inter = len(cur & other)
        union = len(cur | other) or 1
        j = inter / union
        if j > best_j:
            best_j = j
            best_prior = p
    if best_j >= 0.75:
        rep.add(
            "near_dupe",
            "WARNING",
            f"Jaccard={best_j:.2f} vs prior «{best_prior[:80]}»",
            hard=False,
        )
    else:
        rep.add("near_dupe", "PASS", f"max Jaccard={best_j:.2f}", hard=False)


def qa_image(
    path: Path,
    *,
    scene: str | None = None,
    prior_scenes: Sequence[str] | None = None,
) -> FileReport:
    rep = FileReport(str(path))
    try:
        im = Image.open(path)
        im.load()
    except Exception as e:
        rep.add("open", "FAIL", str(e))
        return rep

    check_canvas(rep, im)
    gray = _as_gray(im)
    check_pure_bw(rep, im, gray)
    check_margin_ink(rep, gray)
    check_solid_fills(rep, gray)
    check_wire_grid(rep, gray)
    check_hairlines(rep, gray)
    check_near_dupe(rep, scene or path.stem, prior_scenes)
    return rep


def iter_images(root: Path) -> list[Path]:
    if root.is_file():
        return [root]
    files = sorted(
        p for p in root.rglob("*") if p.is_file() and p.suffix.lower() in IMAGE_EXTS
    )
    return files


# ---------------------------------------------------------------------------
# PDF checks
# ---------------------------------------------------------------------------

def _mediabox_size(page: Any) -> tuple[float, float]:
    box = page.mediabox
    w = float(box.width)
    h = float(box.height)
    return w, h


def _extract_text(reader: Any, max_pages: int | None = None) -> str:
    chunks: list[str] = []
    pages = reader.pages
    n = len(pages) if max_pages is None else min(len(pages), max_pages)
    for i in range(n):
        try:
            chunks.append(pages[i].extract_text() or "")
        except Exception:
            continue
    return "\n".join(chunks)


def check_author(rep: FileReport, reader: Any, author_text_file: Path | None) -> None:
    bits: list[str] = []
    meta = reader.metadata
    if meta:
        for key in ("/Author", "/Creator", "/Producer", "/Subject", "/Title"):
            try:
                val = meta.get(key) if hasattr(meta, "get") else getattr(meta, key[1:].lower(), None)
            except Exception:
                val = None
            if val:
                bits.append(str(val))
        # pypdf DocumentInformation attributes
        for attr in ("author", "creator", "producer", "subject", "title"):
            try:
                v = getattr(meta, attr, None)
                if v:
                    bits.append(str(v))
            except Exception:
                pass
    bits.append(_extract_text(reader, max_pages=min(6, len(reader.pages))))
    if author_text_file and author_text_file.is_file():
        bits.append(author_text_file.read_text(encoding="utf-8", errors="replace"))
    blob = "\n".join(bits)
    if AUTHOR_PLACEHOLDER in blob:
        rep.add("author", "FAIL", f'found placeholder "{AUTHOR_PLACEHOLDER}"')
    else:
        rep.add("author", "PASS", "no author placeholder detected")


def check_page_size(rep: FileReport, reader: Any) -> None:
    bad = []
    for i, page in enumerate(reader.pages):
        w, h = _mediabox_size(page)
        # allow landscape swap? interior must be portrait 612x792
        ok = abs(w - PAGE_W_PT) <= PT_TOL and abs(h - PAGE_H_PT) <= PT_TOL
        if not ok:
            bad.append(f"p{i+1}:{w:.1f}×{h:.1f}")
            if len(bad) >= 5:
                break
    if bad:
        rep.add("page_size", "FAIL", f"expected {PAGE_W_PT}×{PAGE_H_PT} pt; bad e.g. {', '.join(bad)}")
    else:
        rep.add("page_size", "PASS", f"all pages {PAGE_W_PT}×{PAGE_H_PT} pt (±{PT_TOL})")


def check_page_count_layout(
    rep: FileReport,
    reader: Any,
    *,
    front_matter: int,
    designs: int,
) -> None:
    n = len(reader.pages)
    if n % 2 != 0:
        rep.add("page_count_even", "FAIL", f"page count {n} is odd")
    else:
        rep.add("page_count_even", "PASS", f"page count {n} is even")

    remaining = n - front_matter
    expected = designs * 2
    if remaining != expected:
        rep.add(
            "art_blank_pairs",
            "FAIL",
            f"after front-matter {front_matter}: remaining={remaining}, "
            f"expected {expected} ({designs} designs × art+blank). "
            f"Layout: [N front] + [art,blank]×designs → total N+2×designs",
        )
    else:
        rep.add(
            "art_blank_pairs",
            "PASS",
            f"front={front_matter}, designs={designs}, content={remaining} (art/blank pairs)",
        )


def check_security(rep: FileReport, reader: Any, path: Path) -> None:
    # Password / encryption
    try:
        encrypted = bool(getattr(reader, "is_encrypted", False))
    except Exception:
        encrypted = False
    if encrypted:
        # If we could open it, it may still be flagged; treat encryption as FAIL
        rep.add("password", "FAIL", "PDF is encrypted / password-protected")
    else:
        rep.add("password", "PASS", "not encrypted")

    # Forms
    root = reader.trailer.get("/Root") if hasattr(reader, "trailer") else None
    has_form = False
    has_js = False
    try:
        if root is not None:
            # AcroForm
            if "/AcroForm" in root:
                acro = root["/AcroForm"]
                fields = None
                try:
                    fields = acro.get("/Fields")
                except Exception:
                    pass
                if fields:
                    has_form = True
                else:
                    has_form = True  # presence of AcroForm is enough
            # OpenAction / Names JS
            if "/OpenAction" in root:
                oa = str(root.get("/OpenAction"))
                if "JavaScript" in oa or "/JS" in oa:
                    has_js = True
            if "/Names" in root:
                names = root["/Names"]
                if names is not None and "/JavaScript" in names:
                    has_js = True
            if "/AA" in root:
                has_js = True
    except Exception as e:
        rep.add("forms_js_probe", "WARNING", f"could not fully probe catalog: {e}", hard=False)

    # Also scan page /AA and /Annots for JS
    try:
        for page in reader.pages[:20]:
            if "/AA" in page:
                has_js = True
            if "/Annots" in page:
                annots = page["/Annots"]
                if annots:
                    for a in annots:
                        try:
                            obj = a.get_object() if hasattr(a, "get_object") else a
                            s = str(obj)
                            if "/JS" in s or "JavaScript" in s:
                                has_js = True
                            if obj.get("/Subtype") == "/Widget":
                                has_form = True
                        except Exception:
                            continue
    except Exception:
        pass

    if has_form:
        rep.add("forms", "FAIL", "AcroForm / widget annotations present")
    else:
        rep.add("forms", "PASS", "no forms detected")

    if has_js:
        rep.add("javascript", "FAIL", "JavaScript / additional-actions detected")
    else:
        rep.add("javascript", "PASS", "no JavaScript detected")


def check_cover_geometry(
    rep: FileReport,
    reader: Any,
    *,
    pages: int,
    spine_factor: float,
) -> None:
    spine = pages * spine_factor
    wrap_w = BLEED_IN + TRIM_W_IN + spine + TRIM_W_IN + BLEED_IN
    wrap_h = WRAP_H_IN
    if not reader.pages:
        rep.add("cover_geometry", "FAIL", "cover PDF has no pages")
        return
    w_pt, h_pt = _mediabox_size(reader.pages[0])
    w_in = w_pt / 72.0
    h_in = h_pt / 72.0
    # Infer spine from MediaBox: W = 0.125+8.5+spine+8.5+0.125 = 17.25 + spine
    inferred_spine = w_in - (2 * BLEED_IN + 2 * TRIM_W_IN)
    spine_ok = abs(inferred_spine - spine) <= SPINE_TOL_IN or abs(w_in - wrap_w) <= SPINE_TOL_IN
    h_ok = abs(h_in - wrap_h) <= SPINE_TOL_IN or abs(h_pt - wrap_h * 72) <= PT_TOL
    details = (
        f"expected spine={spine:.6f}in (±{SPINE_TOL_IN}), wrap≈{wrap_w:.6f}×{wrap_h}; "
        f"MediaBox={w_in:.6f}×{h_in:.6f}in (inferred_spine={inferred_spine:.6f})"
    )
    if spine_ok and h_ok:
        rep.add("cover_geometry", "PASS", details)
    else:
        problems = []
        if not spine_ok:
            problems.append(f"spine/width mismatch (want spine {spine:.6f})")
        if not h_ok:
            problems.append(f"height want {wrap_h}")
        rep.add("cover_geometry", "FAIL", "; ".join(problems) + " | " + details)

    # Soft: spine text when spine < 0.25
    if spine < SPINE_TEXT_MIN_IN:
        text = ""
        try:
            text = reader.pages[0].extract_text() or ""
        except Exception:
            text = ""
        # Heuristic: we cannot know spine-only glyphs easily; soft note
        if text.strip():
            rep.add(
                "spine_text",
                "WARNING",
                f"spine={spine:.4f}in < {SPINE_TEXT_MIN_IN}: ensure spine text skipped "
                f"(extractable text present; verify visually)",
                hard=False,
            )
        else:
            rep.add(
                "spine_text",
                "PASS",
                f"spine={spine:.4f}in < {SPINE_TEXT_MIN_IN}; little/no extractable text",
                hard=False,
            )
    else:
        rep.add(
            "spine_text",
            "SKIP",
            f"spine={spine:.4f}in ≥ {SPINE_TEXT_MIN_IN}; text expected/allowed",
            hard=False,
        )


def check_barcode_zone(rep: FileReport, cover_path: Path) -> None:
    """Optional: rasterize cover first page and check back bottom-right clear."""
    try:
        from pdf2image import convert_from_path  # type: ignore
    except ImportError:
        rep.add(
            "barcode_zone",
            "SKIP",
            "TODO: install optional pdf2image (+ poppler) to rasterize cover and "
            f"verify back bottom-right ~{BARCODE_W_IN}×{BARCODE_H_IN} in clear",
            hard=False,
        )
        return

    try:
        images = convert_from_path(str(cover_path), dpi=DPI, first_page=1, last_page=1)
    except Exception as e:
        rep.add("barcode_zone", "SKIP", f"pdf2image render failed: {e}", hard=False)
        return
    if not images:
        rep.add("barcode_zone", "SKIP", "no raster from cover", hard=False)
        return

    im = images[0]
    # Full wrap: [bleed][back][spine][front][bleed]
    # We need spine from width
    w_px, h_px = im.size
    w_in = w_px / DPI
    spine_in = w_in - (2 * BLEED_IN + 2 * TRIM_W_IN)
    # Back trim rect in wrap coords
    back_left = BLEED_IN
    back_bottom = BLEED_IN  # from bottom of wrap
    # Barcode: bottom-right of BACK — inward from back trim
    # Zone: from (back_right - 2.0in) to back_right, bottom 1.2in of trim
    zone_right = back_left + TRIM_W_IN
    zone_left = zone_right - BARCODE_W_IN
    zone_bottom = back_bottom
    zone_top = zone_bottom + BARCODE_H_IN
    # Convert to pixel coords (PIL: y=0 at top)
    x0 = int(round(zone_left * DPI))
    x1 = int(round(zone_right * DPI))
    y1 = h_px - int(round(zone_bottom * DPI))
    y0 = h_px - int(round(zone_top * DPI))
    x0, x1 = max(0, x0), min(w_px, x1)
    y0, y1 = max(0, y0), min(h_px, y1)
    crop = im.crop((x0, y0, x1, y1))
    gray = np.array(crop.convert("L"))
    # "Clear" means mostly uniform / no dark art — allow solid light bg
    # Fail if significant dark ink variance (line art / text)
    dark = int(np.count_nonzero(gray < 80))
    frac = dark / max(1, gray.size)
    # Also check it's not highly textured
    std = float(gray.std())
    if frac > 0.02 and std > 25:
        rep.add(
            "barcode_zone",
            "FAIL",
            f"back BR zone has dark_frac={frac:.2%}, std={std:.1f} "
            f"(want clear ~{BARCODE_W_IN}×{BARCODE_H_IN} in); spine_inferred={spine_in:.4f}",
            hard=True,
        )
    else:
        # Optional dependency path: PASS is informational; FAIL (above) is hard.
        rep.add(
            "barcode_zone",
            "PASS",
            f"zone clear-ish dark_frac={frac:.2%}, std={std:.1f}",
            hard=False,
        )


def qa_interior_pdf(
    path: Path,
    *,
    front_matter: int,
    designs: int,
    author_text: Path | None,
) -> FileReport:
    from pypdf import PdfReader

    rep = FileReport(str(path))
    try:
        reader = PdfReader(str(path))
    except Exception as e:
        rep.add("open", "FAIL", str(e))
        return rep

    if getattr(reader, "is_encrypted", False):
        try:
            reader.decrypt("")
        except Exception:
            rep.add("password", "FAIL", "cannot open encrypted PDF")
            return rep

    check_security(rep, reader, path)
    check_author(rep, reader, author_text)
    check_page_size(rep, reader)
    check_page_count_layout(rep, reader, front_matter=front_matter, designs=designs)
    return rep


def qa_cover_pdf(
    path: Path,
    *,
    pages: int,
    spine_factor: float,
    author_text: Path | None,
) -> FileReport:
    from pypdf import PdfReader

    rep = FileReport(str(path))
    try:
        reader = PdfReader(str(path))
    except Exception as e:
        rep.add("open", "FAIL", str(e))
        return rep

    if getattr(reader, "is_encrypted", False):
        try:
            reader.decrypt("")
        except Exception:
            rep.add("password", "FAIL", "cannot open encrypted PDF")
            return rep

    check_security(rep, reader, path)
    check_author(rep, reader, author_text)
    check_cover_geometry(rep, reader, pages=pages, spine_factor=spine_factor)
    check_barcode_zone(rep, path)
    return rep


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def cmd_images(args: argparse.Namespace) -> int:
    root = Path(args.path)
    if not root.exists():
        print(f"ERROR: path not found: {root}", file=sys.stderr)
        return 1
    prior = None
    if args.prior_scenes:
        prior = json.loads(Path(args.prior_scenes).read_text(encoding="utf-8"))
        if not isinstance(prior, list):
            print("ERROR: --prior-scenes must be a JSON list of strings", file=sys.stderr)
            return 1
    paths = iter_images(root)
    if not paths:
        print(f"ERROR: no images under {root}", file=sys.stderr)
        return 1
    reports = [qa_image(p, prior_scenes=prior) for p in paths]
    return _print_report(reports, f"IMAGE QA ({len(reports)} file(s))")


def cmd_pdf(args: argparse.Namespace) -> int:
    reports: list[FileReport] = []
    author_text = Path(args.author_text) if args.author_text else None

    if args.interior:
        ip = Path(args.interior)
        if not ip.exists():
            print(f"ERROR: interior not found: {ip}", file=sys.stderr)
            return 1
        reports.append(
            qa_interior_pdf(
                ip,
                front_matter=args.front_matter_pages,
                designs=args.designs,
                author_text=author_text,
            )
        )

    if args.cover:
        cp = Path(args.cover)
        if not cp.exists():
            print(f"ERROR: cover not found: {cp}", file=sys.stderr)
            return 1
        if args.pages is None:
            print("ERROR: --pages is required with --cover (interior page count for spine)", file=sys.stderr)
            return 1
        reports.append(
            qa_cover_pdf(
                cp,
                pages=args.pages,
                spine_factor=args.spine_factor,
                author_text=author_text,
            )
        )

    if not reports:
        print("ERROR: provide --interior and/or --cover", file=sys.stderr)
        return 1
    return _print_report(reports, "PDF QA")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="qa_gate.py",
        description="Hard-FAIL QA gates for KDP coloring book images and PDFs.",
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    pi = sub.add_parser("images", help="QA PNG/JPG page images")
    pi.add_argument("path", help="Image file or directory")
    pi.add_argument(
        "--prior-scenes",
        help="Optional JSON list of prior scene strings (near-dupe soft FLAG only)",
    )
    pi.set_defaults(func=cmd_images)

    pp = sub.add_parser("pdf", help="QA interior and/or cover PDF package")
    pp.add_argument("--interior", help="Path to interior.pdf")
    pp.add_argument("--cover", help="Path to cover.pdf")
    pp.add_argument(
        "--pages",
        type=int,
        default=None,
        help="Interior page count (required for cover spine check)",
    )
    pp.add_argument(
        "--spine-factor",
        type=float,
        default=DEFAULT_SPINE_FACTOR,
        help=f"KDP white-paper spine factor (default {DEFAULT_SPINE_FACTOR})",
    )
    pp.add_argument(
        "--front-matter-pages",
        type=int,
        default=DEFAULT_FRONT_MATTER,
        help=f"Front-matter pages before art/blank pairs (default {DEFAULT_FRONT_MATTER})",
    )
    pp.add_argument(
        "--designs",
        type=int,
        default=DEFAULT_DESIGNS,
        help=f"Number of art designs expected (default {DEFAULT_DESIGNS})",
    )
    pp.add_argument(
        "--author-text",
        help="Optional text/metadata file also scanned for author placeholder",
    )
    pp.set_defaults(func=cmd_pdf)
    return p


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())
