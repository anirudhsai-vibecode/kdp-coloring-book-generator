#!/usr/bin/env python3
"""
Hard-FAIL QA gates for KDP coloring-book image pages and PDF packages.

Exit codes:
  0 -- all hard checks PASS
  1 -- one or more hard FAILs

See qa_checks/THRESHOLDS.md for exact thresholds.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Sequence

import numpy as np
from PIL import Image

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None  # type: ignore

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
HAIRLINE_MEDIAN_MAX = 5  # median horizontal run < 5 -> evaluate thin1
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

# Eyes heuristic (best-effort CV; see THRESHOLDS.md). Default ON; --skip-eyes to disable.
EYES_MIN_PUPILS = 1
EYES_MIN_AREA = 12
EYES_MAX_AREA_FRAC = 0.04  # of face-region pixels
EYES_MAX_ASPECT = 2.2
EYES_MIN_FILL = 0.35

# Chore / tool action classes -- same class twice in one book = hard FAIL.
# Patterns are lowercase substrings; longer / more specific first within each class.
CHORE_CLASS_PATTERNS: list[tuple[str, tuple[str, ...]]] = [
    ("broom-sweep", ("broom", "sweeping", "sweep the", "sweeping the floor")),
    ("watering-can", ("watering can", "watering-can", "water the plants", "watering plants", "watering flowers")),
    ("stir-spoon", ("stirring", "stir spoon", "mixing spoon", "stirring pot", "stir the")),
    ("hang-laundry", ("hang laundry", "hanging laundry", "clothesline", "hang clothes", "hanging clothes")),
    ("scrub-brush", ("scrub brush", "scrubbing", "scrub the", "dish brush", "washing dishes")),
    ("mop-floor", ("mopping", "mop the", "mop floor")),
    ("dust-cloth", ("dusting", "dust cloth", "feather duster", "dust the")),
    ("vacuum", ("vacuuming", "vacuum cleaner", "vacuum the")),
    ("rake-leaves", ("raking", "rake leaves", "rake the")),
    ("wash-window", ("washing window", "wash window", "window washing", "wipe window")),
    ("fold-laundry", ("folding laundry", "fold laundry", "folding clothes")),
    ("take-trash", ("take out trash", "taking out trash", "trash bag", "garbage bag")),
    ("make-bed", ("making bed", "make the bed", "making the bed")),
    ("set-table", ("setting table", "set the table", "setting the table")),
    ("wash-car", ("washing car", "wash the car", "hose the car")),
    ("garden-hoe", ("gardening hoe", "hoe the", "hoeing")),
    ("paint-brush", ("paint brush", "painting fence", "paint the fence")),
]

PAGE_NUM_SAMPLE_MAX = 6
PAGE_NUM_CORNER_FRAC = 0.12  # fraction of page W/H for corner crops


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
            detail = f" -- {c.detail}" if c.detail else ""
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
        rep.add("canvas", "PASS", f"{w}x{h} portrait")
    else:
        rep.add("canvas", "FAIL", f"got {w}x{h}, need {CANVAS_W}x{CANVAS_H} portrait")


def check_pure_bw(rep: FileReport, im: Image.Image, gray: np.ndarray) -> None:
    if im.mode == "1":
        rep.add("pure_bw", "PASS", "mode=1 (1-bit)")
        return
    mid = int(np.count_nonzero((gray >= 2) & (gray <= 253)))
    # unique colors on RGB or L
    rgb = np.array(im.convert("RGB"))
    # subsample for speed on ncolors estimate if huge -- full unique on reshaped
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
            parts.append(f"mid_gray_pixels={mid} (L in 2-253 must be 0)")
        if ncolors > 2:
            parts.append(f"ncolors={ncolors} (<=2 required, or mode 1)")
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
        rep.add("margin_ink", "PASS", f'0 ink pixels in {m}px (0.5") margin')
    else:
        rep.add("margin_ink", "FAIL", f"{count} ink pixels in {m}px margin strip")


def _is_filled_region(mask_cc: np.ndarray, area: int) -> bool:
    """Heuristic: compact solid paint-bucket fill vs thick stroke/outline network.

    Thick connected outline art survives mild erosion and used to false-positive
    as solid_fills, which pushed postprocess into morph-ring ribbons. Exclude
    stroke-like CCs via low bbox fill-ratio or high perimeter^2/area.
    """
    ys, xs = np.where(mask_cc)
    if len(xs) == 0:
        return False
    bw = int(xs.max() - xs.min() + 1)
    bh = int(ys.max() - ys.min() + 1)
    bbox_area = max(1, bw * bh)
    fill_ratio = area / bbox_area

    if cv2 is None:
        return fill_ratio > 0.55 and bw >= 40 and bh >= 40

    u8 = mask_cc.astype(np.uint8) * 255
    # Stroke / outline network signals
    if fill_ratio < 0.35:
        return False
    cnts, _ = cv2.findContours(u8, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if cnts:
        peri = float(sum(cv2.arcLength(c, True) for c in cnts))
        if peri > 0 and (peri * peri) / max(area, 1) > 100.0:
            return False

    kernel = np.ones((3, 3), np.uint8)
    eroded = cv2.erode(u8, kernel, iterations=2)
    eroded_area = int(np.count_nonzero(eroded))
    if eroded_area > max(500, int(0.15 * area)) and fill_ratio > 0.40:
        return True
    return fill_ratio > 0.55 and bw >= 40 and bh >= 40


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
    adjacent rows/cols so a 2-3 px stroke counts as one run (not dozens).
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



def check_hollow_ribbons(rep: FileReport, gray: np.ndarray) -> None:
    """HARD FAIL hollow double-outline / ribbon strokes (AD lock).

    Mirrors ``kdp_coloring.image_gen.ribbon_risk`` on processed 1-bit pages:
    solid thick strokes keep a core under mild erosion and have low morph-gradient
    relative to ink; hollow ribbons are edge-dominated and their white channels
    fill under a small morphological close.
    """
    if cv2 is None:
        rep.add("hollow_ribbons", "SKIP", "opencv unavailable")
        return
    ink = ((gray < 128).astype(np.uint8)) * 255
    n_ink = int(np.count_nonzero(ink))
    ink_frac = float(n_ink) / max(1, gray.size)
    if ink_frac < 0.005:
        rep.add("hollow_ribbons", "PASS", "too little ink to score ribbons")
        return
    eroded = cv2.erode(ink, np.ones((3, 3), np.uint8), iterations=2)
    rem = float(np.count_nonzero(eroded)) / max(1, n_ink)
    grad = cv2.morphologyEx(ink, cv2.MORPH_GRADIENT, np.ones((3, 3), np.uint8))
    grad_frac = float(np.mean(grad > 0))
    grad_ratio = grad_frac / max(ink_frac, 1e-9)
    closed = cv2.morphologyEx(ink, cv2.MORPH_CLOSE, np.ones((7, 7), np.uint8), iterations=1)
    gained = float(np.count_nonzero((closed > 0) & (ink == 0))) / max(1, gray.size)

    reasons: list[str] = []
    if rem < 0.15 and ink_frac > 0.02 and grad_ratio > 0.6:
        reasons.append(f"thin-wall rem2={rem:.2f} grad/ink={grad_ratio:.2f}")
    if ink_frac > 0.015 and grad_ratio > 0.70 and gained > 0.004:
        reasons.append(f"channel-fill close7={gained:.4f} grad/ink={grad_ratio:.2f}")
    if ink_frac > 0.015 and rem < 0.60 and grad_ratio > 0.75:
        reasons.append(f"edge-dominated rem2={rem:.2f} grad/ink={grad_ratio:.2f}")
    if gained > 0.012 and rem < 0.35:
        reasons.append(f"wide ribbon channels close7={gained:.4f} rem2={rem:.2f}")

    if reasons:
        rep.add(
            "hollow_ribbons",
            "FAIL",
            "hollow double-outline ribbons -- " + "; ".join(reasons),
        )
    else:
        rep.add(
            "hollow_ribbons",
            "PASS",
            f"solid strokes rem2={rem:.2f} grad/ink={grad_ratio:.2f} close7={gained:.4f}",
        )


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
            f"{worst} thin parallel/orthogonal runs in 400x400 @ {worst_pos} (limit {WIRE_RUN_LIMIT})",
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


def normalize_chore_class(subject: str) -> str | None:
    """Map a scene/subject string to a chore/tool action class, or None."""
    s = " ".join(
        "".join(c.lower() if c.isalnum() or c.isspace() else " " for c in subject).split()
    )
    if not s:
        return None
    for cls, patterns in CHORE_CLASS_PATTERNS:
        for pat in patterns:
            if pat in s:
                return cls
    return None


def _subject_bbox(ink: np.ndarray) -> tuple[int, int, int, int] | None:
    ys, xs = np.where(ink)
    if xs.size == 0:
        return None
    return int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())


def _count_pupil_like_blobs(face_ink: np.ndarray) -> tuple[int, str]:
    """
    Best-effort: count small dark circular-ish components in a face crop.

    Heuristic only -- line-art pupils vary; use --skip-eyes if unreliable for a run.
    """
    h, w = face_ink.shape
    if h < 8 or w < 8:
        return 0, "face region too small"
    face_area = h * w
    max_area = max(EYES_MIN_AREA + 1, int(EYES_MAX_AREA_FRAC * face_area))
    u8 = (face_ink.astype(np.uint8) * 255)

    pupils = 0
    if cv2 is not None:
        n, labels, stats, _ = cv2.connectedComponentsWithStats(u8, connectivity=8)
        for i in range(1, n):
            area = int(stats[i, cv2.CC_STAT_AREA])
            bw = int(stats[i, cv2.CC_STAT_WIDTH])
            bh = int(stats[i, cv2.CC_STAT_HEIGHT])
            if area < EYES_MIN_AREA or area > max_area:
                continue
            if bw < 3 or bh < 3:
                continue
            if bw > w * 0.35 or bh > h * 0.45:
                continue
            aspect = max(bw, bh) / max(1, min(bw, bh))
            if aspect > EYES_MAX_ASPECT:
                continue
            fill = area / max(1, bw * bh)
            if fill < EYES_MIN_FILL:
                continue
            # Circularity from contour when possible
            cc = (labels == i).astype(np.uint8) * 255
            contours, _ = cv2.findContours(cc, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            if contours:
                peri = float(cv2.arcLength(contours[0], True))
                if peri > 0:
                    circ = 4.0 * np.pi * area / (peri * peri)
                    if circ < 0.45:
                        continue
            pupils += 1
        return pupils, f"cv2 CC pupils={pupils} (face {w}x{h})"

    # Numpy fallback: scan for compact dark blobs via local bounding boxes of CCs
    visited = np.zeros_like(face_ink, dtype=bool)
    ys_all, xs_all = np.where(face_ink)
    for y0, x0 in zip(ys_all[::3], xs_all[::3]):
        if visited[y0, x0]:
            continue
        stack = [(int(y0), int(x0))]
        visited[y0, x0] = True
        cells: list[tuple[int, int]] = []
        while stack:
            y, x = stack.pop()
            cells.append((y, x))
            for dy, dx in ((0, 1), (0, -1), (1, 0), (-1, 0)):
                ny, nx = y + dy, x + dx
                if 0 <= ny < h and 0 <= nx < w and not visited[ny, nx] and face_ink[ny, nx]:
                    visited[ny, nx] = True
                    stack.append((ny, nx))
        area = len(cells)
        if area < EYES_MIN_AREA or area > max_area:
            continue
        ys = [c[0] for c in cells]
        xs = [c[1] for c in cells]
        bw = max(xs) - min(xs) + 1
        bh = max(ys) - min(ys) + 1
        aspect = max(bw, bh) / max(1, min(bw, bh))
        fill = area / max(1, bw * bh)
        if aspect <= EYES_MAX_ASPECT and fill >= EYES_MIN_FILL and bw >= 3 and bh >= 3:
            pupils += 1
    return pupils, f"numpy CC pupils={pupils} (face {w}x{h})"


def check_eyes_pupils(rep: FileReport, gray: np.ndarray, *, skip: bool = False) -> None:
    """
    Hard FAIL (heuristic): character page face region lacks dark pupil-like blobs.

    Looks at the upper half of the subject bbox for small dark circular-ish
    connected components. Best-effort; default ON. Use --skip-eyes to disable.
    """
    if skip:
        rep.add("eyes_pupils", "SKIP", "disabled via --skip-eyes", hard=False)
        return

    ink = _black_mask(gray)
    bbox = _subject_bbox(ink)
    if bbox is None:
        rep.add(
            "eyes_pupils",
            "FAIL",
            "heuristic: no subject ink -- cannot locate face/pupils",
        )
        return

    x0, y0, x1, y1 = bbox
    bw = x1 - x0 + 1
    bh = y1 - y0 + 1
    if bw < 40 or bh < 40:
        rep.add(
            "eyes_pupils",
            "FAIL",
            f"heuristic: subject bbox {bw}x{bh} too small for face/pupils",
        )
        return

    # Face = upper half of subject, horizontally inset 10%
    mid_y = y0 + bh // 2
    inset = max(1, bw // 10)
    fx0, fx1 = x0 + inset, x1 - inset
    face = ink[y0:mid_y, fx0:fx1]
    n_pupils, detail = _count_pupil_like_blobs(face)
    if n_pupils < EYES_MIN_PUPILS:
        rep.add(
            "eyes_pupils",
            "FAIL",
            f"heuristic: no dark pupil-like blobs in upper-half face "
            f"(found {n_pupils}, need >= {EYES_MIN_PUPILS}); {detail}. "
            f"Re-generate with clear visible eyes/pupils, or pass --skip-eyes",
        )
    else:
        rep.add(
            "eyes_pupils",
            "PASS",
            f"heuristic: {n_pupils} pupil-like blob(s) in face region; {detail}",
        )


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
    cur_chore = normalize_chore_class(scene)
    best_j = 0.0
    best_prior = ""
    chore_hit: str | None = None
    chore_prior = ""
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
        if cur_chore is not None:
            other_chore = normalize_chore_class(p)
            if other_chore == cur_chore:
                chore_hit = cur_chore
                chore_prior = p
    # Soft near-dupe becomes HARD when the shared chore/tool class matches.
    if chore_hit is not None:
        rep.add(
            "near_dupe",
            "FAIL",
            f"chore-class hard dupe: <<{chore_hit}>> also in prior <<{chore_prior[:80]}>> "
            f"(Jaccard={best_j:.2f})",
            hard=True,
        )
        return
    if best_j >= 0.75:
        rep.add(
            "near_dupe",
            "WARNING",
            f"Jaccard={best_j:.2f} vs prior <<{best_prior[:80]}>>",
            hard=False,
        )
    else:
        rep.add("near_dupe", "PASS", f"max Jaccard={best_j:.2f}", hard=False)


def check_chore_class_dupes(
    reports: list[FileReport],
    scene_list: Sequence[dict[str, Any]] | None,
) -> FileReport | None:
    """
    Book-level hard FAIL: same normalized chore/tool class on two+ pages.

    scene_list entries: {page, subject} (JSON or YAML via --scene-list).
    """
    if scene_list is None:
        return None
    rep = FileReport("--scene-list (book chore classes)")
    by_class: dict[str, list[str]] = {}
    for entry in scene_list:
        if not isinstance(entry, dict):
            continue
        page = entry.get("page", "?")
        subject = str(entry.get("subject", "") or "")
        cls = normalize_chore_class(subject)
        if cls is None:
            continue
        by_class.setdefault(cls, []).append(f"page {page}: {subject[:60]}")
    dupes = {k: v for k, v in by_class.items() if len(v) >= 2}
    if dupes:
        parts = [f"{cls} -> {'; '.join(pages)}" for cls, pages in sorted(dupes.items())]
        rep.add(
            "chore_class_dupe",
            "FAIL",
            "same chore/tool class twice in book: " + "; ".join(parts),
        )
    else:
        n = sum(1 for v in by_class.values() if v)
        rep.add(
            "chore_class_dupe",
            "PASS",
            f"{n} chore-class page(s), all unique classes",
        )
    reports.append(rep)
    return rep


def load_scene_list(path: Path) -> list[dict[str, Any]]:
    raw = path.read_text(encoding="utf-8")
    data: Any
    if path.suffix.lower() in {".yaml", ".yml"}:
        if yaml is None:
            raise RuntimeError("PyYAML required for --scene-list YAML files")
        data = yaml.safe_load(raw)
    else:
        data = json.loads(raw)
        # Allow YAML-looking .json mistake: if string, try yaml
        if isinstance(data, str) and yaml is not None:
            data = yaml.safe_load(data)
    if isinstance(data, dict) and "pages" in data:
        data = data["pages"]
    if not isinstance(data, list):
        raise ValueError("--scene-list must be a JSON/YAML list of {page, subject} objects")
    out: list[dict[str, Any]] = []
    for item in data:
        if isinstance(item, dict) and "subject" in item:
            out.append(item)
        elif isinstance(item, str):
            out.append({"page": len(out) + 1, "subject": item})
        else:
            raise ValueError(f"invalid scene-list entry: {item!r}")
    return out


def qa_image(
    path: Path,
    *,
    scene: str | None = None,
    prior_scenes: Sequence[str] | None = None,
    skip_eyes: bool = False,
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
    check_hollow_ribbons(rep, gray)
    check_wire_grid(rep, gray)
    check_hairlines(rep, gray)
    check_eyes_pupils(rep, gray, skip=skip_eyes)
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
            bad.append(f"p{i+1}:{w:.1f}x{h:.1f}")
            if len(bad) >= 5:
                break
    if bad:
        rep.add("page_size", "FAIL", f"expected {PAGE_W_PT}x{PAGE_H_PT} pt; bad e.g. {', '.join(bad)}")
    else:
        rep.add("page_size", "PASS", f"all pages {PAGE_W_PT}x{PAGE_H_PT} pt (+/-{PT_TOL})")


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
            f"expected {expected} ({designs} designs x art+blank). "
            f"Layout: [N front] + [art,blank]xdesigns -> total N+2xdesigns",
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
        f"expected spine={spine:.6f}in (+/-{SPINE_TOL_IN}), wrap~={wrap_w:.6f}x{wrap_h}; "
        f"MediaBox={w_in:.6f}x{h_in:.6f}in (inferred_spine={inferred_spine:.6f})"
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
            f"spine={spine:.4f}in >= {SPINE_TEXT_MIN_IN}; text expected/allowed",
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
            f"verify back bottom-right ~{BARCODE_W_IN}x{BARCODE_H_IN} in clear",
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
    # Barcode: bottom-right of BACK -- inward from back trim
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
    # "Clear" means mostly uniform / no dark art -- allow solid light bg
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
            f"(want clear ~{BARCODE_W_IN}x{BARCODE_H_IN} in); spine_inferred={spine_in:.4f}",
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


def _page_num_corner_crops(im: Image.Image) -> list[Image.Image]:
    """Bottom-center + four corner crops where page numbers are usually drawn."""
    w, h = im.size
    cw = max(8, int(w * PAGE_NUM_CORNER_FRAC))
    ch = max(8, int(h * PAGE_NUM_CORNER_FRAC))
    crops = [
        im.crop((0, 0, cw, ch)),
        im.crop((w - cw, 0, w, ch)),
        im.crop((0, h - ch, cw, h)),
        im.crop((w - cw, h - ch, w, h)),
        im.crop((w // 2 - cw, h - ch, w // 2 + cw, h)),  # bottom center
    ]
    return crops


def _corner_has_digit_like_ink(gray: np.ndarray) -> bool:
    """Heuristic: small dark CCs with digit-like aspect (no OCR)."""
    ink = gray < 128
    if int(ink.sum()) < 8:
        return False
    h, w = gray.shape
    u8 = (ink.astype(np.uint8) * 255)
    if cv2 is not None:
        n, _, stats, _ = cv2.connectedComponentsWithStats(u8, connectivity=8)
        for i in range(1, n):
            area = int(stats[i, cv2.CC_STAT_AREA])
            bw = int(stats[i, cv2.CC_STAT_WIDTH])
            bh = int(stats[i, cv2.CC_STAT_HEIGHT])
            if area < 12 or area > (h * w) * 0.35:
                continue
            # Digits are taller than wide-ish, not huge bars
            if bh < 6 or bw < 3:
                continue
            if bh > h * 0.9 or bw > w * 0.85:
                continue
            aspect = bh / max(1, bw)
            if 0.8 <= aspect <= 4.5:
                return True
        return False
    # Fallback: any non-trivial dark ink in corner counts as weak signal
    return int(ink.sum()) >= 20


def check_page_numbers(
    rep: FileReport,
    reader: Any,
    path: Path,
    *,
    front_matter: int,
) -> None:
    """
    Hard FAIL if interior sample pages have no detectable page numbers.

    Prefers pdf2image raster of corners (drawn numerals). Falls back to
    extractable text digits. Dependency: optional pdf2image + poppler
    (documented in THRESHOLDS.md / requirements.txt).
    """
    n = len(reader.pages)
    if n == 0:
        rep.add("page_numbers", "FAIL", "PDF has no pages")
        return

    # Sample interior content pages (skip pure front-matter when possible)
    start = min(front_matter, max(0, n - 1))
    candidates = list(range(start, n))
    if len(candidates) < 3:
        candidates = list(range(n))
    step = max(1, len(candidates) // PAGE_NUM_SAMPLE_MAX)
    sample_idxs = sorted(set(candidates[::step][:PAGE_NUM_SAMPLE_MAX]))
    if n - 1 not in sample_idxs:
        sample_idxs.append(n - 1)

    text_hits = 0
    # Footer-like page numbers: a line that is only 1-3 digits (optional spaces),
    # not body text that happens to contain a number.
    footer_num_re = re.compile(r"(?m)^\s*\d{1,3}\s*$")
    for i in sample_idxs:
        try:
            t = reader.pages[i].extract_text() or ""
        except Exception:
            t = ""
        if footer_num_re.search(t):
            text_hits += 1
            continue
        # Also accept a trailing short numeric token on the last non-empty line
        lines = [ln.strip() for ln in t.splitlines() if ln.strip()]
        if lines and re.fullmatch(r"\d{1,3}", lines[-1]):
            text_hits += 1

    raster_hits = 0
    raster_note = ""
    try:
        from pdf2image import convert_from_path  # type: ignore

        try:
            # 150 DPI enough for numeral blobs; 1-indexed pages for pdf2image
            for i in sample_idxs:
                images = convert_from_path(
                    str(path),
                    dpi=150,
                    first_page=i + 1,
                    last_page=i + 1,
                )
                if not images:
                    continue
                for crop in _page_num_corner_crops(images[0]):
                    g = np.array(crop.convert("L"))
                    if _corner_has_digit_like_ink(g):
                        raster_hits += 1
                        break
            raster_note = f"pdf2image corner hits={raster_hits}/{len(sample_idxs)}"
        except Exception as e:
            raster_note = f"pdf2image render failed: {e}"
    except ImportError:
        raster_note = (
            "pdf2image not installed (optional; needs poppler) -- "
            "drawn numerals in corners cannot be raster-checked"
        )

    # Pass if either text or raster finds numbers on >=2 sample pages,
    # or >=1 when the book is tiny.
    need = 2 if len(sample_idxs) >= 2 else 1
    if text_hits >= need or raster_hits >= need:
        rep.add(
            "page_numbers",
            "PASS",
            f"text_digit_pages={text_hits}, {raster_note}; samples={ [i+1 for i in sample_idxs] }",
        )
        return

    # Single-method weak signal: still fail hard -- teammates need reliable numbers
    if text_hits == 0 and raster_hits == 0:
        rep.add(
            "page_numbers",
            "FAIL",
            "no detectable page numbers on sample pages "
            f"(text_digit_pages=0, {raster_note}). "
            "Interior package must show page numbers; install pdf2image+poppler "
            "to detect drawn numerals, or embed extractable page-number text",
        )
    else:
        rep.add(
            "page_numbers",
            "FAIL",
            f"insufficient page-number evidence (text_digit_pages={text_hits}, "
            f"{raster_note}; need >={need} sample hits). "
            "Ensure every interior page shows a clear page number",
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
    check_page_numbers(rep, reader, path, front_matter=front_matter)
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

def _scene_for_path(path: Path, scene_by_page: dict[Any, str] | None) -> str | None:
    if not scene_by_page:
        return None
    stem = path.stem
    # page_001 / page-001 / 001
    m = re.search(r"(\d+)", stem)
    if m:
        num = int(m.group(1))
        if num in scene_by_page:
            return scene_by_page[num]
        if str(num) in scene_by_page:
            return scene_by_page[str(num)]
    return scene_by_page.get(stem)


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
    scene_list = None
    scene_by_page: dict[Any, str] | None = None
    if args.scene_list:
        try:
            scene_list = load_scene_list(Path(args.scene_list))
        except Exception as e:
            print(f"ERROR: --scene-list: {e}", file=sys.stderr)
            return 1
        scene_by_page = {}
        for entry in scene_list:
            page = entry.get("page")
            subj = str(entry.get("subject", ""))
            if page is not None:
                scene_by_page[page] = subj
                try:
                    scene_by_page[int(page)] = subj
                except (TypeError, ValueError):
                    pass
        # Also feed subjects into prior-scenes for near-dupe if not provided
        if prior is None:
            prior = [str(e.get("subject", "")) for e in scene_list if e.get("subject")]
    paths = iter_images(root)
    if not paths:
        print(f"ERROR: no images under {root}", file=sys.stderr)
        return 1
    reports: list[FileReport] = []
    for p in paths:
        scene = _scene_for_path(p, scene_by_page)
        # For near-dupe, exclude this page's own subject from prior
        page_prior = prior
        if prior is not None and scene:
            page_prior = [s for s in prior if s != scene]
        reports.append(
            qa_image(
                p,
                scene=scene or p.stem,
                prior_scenes=page_prior,
                skip_eyes=bool(args.skip_eyes),
            )
        )
    check_chore_class_dupes(reports, scene_list)
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
        help="Optional JSON list of prior scene strings (near-dupe soft FLAG; "
        "hard FAIL when chore-class matches)",
    )
    pi.add_argument(
        "--scene-list",
        help="JSON/YAML list of {page, subject} for the book; enables chore-class "
        "duplicate hard FAIL and per-page scene labels",
    )
    pi.add_argument(
        "--skip-eyes",
        action="store_true",
        help="Disable eyes/pupils heuristic hard FAIL (default: ON / best-effort)",
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
