# QA / Packager hard-FAIL thresholds

Exact gates enforced by `scripts/qa_gate.py`. Soft checks print `WARNING` / `FLAG` / `SKIP` only and never alone force exit code 1 (unless a hard check also fails).

## A) Image pages (PNG / JPG)

| Check | Threshold | Severity |
|-------|-----------|----------|
| Canvas size | Exactly **2550 × 3300** portrait (8.5″ × 11″ @ 300 DPI) | HARD FAIL |
| Pure B&W / 1-bit | Mode `1`, **or** unique colors ≤ 2, **and** mid-gray pixels with L ∈ **[2, 253]** count must be **0** | HARD FAIL |
| Safe margin | Ink (near-black, L < 128) inside the outer **0.5″** strip (**150 px** @ 300 DPI) must be **0** | HARD FAIL |
| Solid black fills | Any connected black component with area **> ~2% of page** (`page_pixels * 0.02`) **and** filled (not a thin stroke ring) → FAIL | HARD FAIL |
| Wire-grid density | In any **400 × 400** window, **> ~40** thin parallel/orthogonal black runs → FAIL | HARD FAIL |
| Stroke hairlines | Sample every **25th** row; collect horizontal black-run lengths. If median run **< 5 px**, compute `thin1` = fraction of runs with length **1**. Fail if **thin1 > 1%** of runs | HARD FAIL |
| Eyes / pupils (heuristic) | For character pages (default: all image pages): upper half of subject bbox must contain **≥ 1** small dark circular-ish connected component (pupil-like blob). Best-effort CV; clear FAIL reason. Default **ON**; disable with `--skip-eyes` | HARD FAIL (default); SKIP if `--skip-eyes` |
| Chore-class duplicate | With `--scene-list` JSON/YAML of `{page, subject}`: normalize tool/action classes (`broom-sweep`, `watering-can`, `stir-spoon`, `hang-laundry`, `scrub-brush`, `mop-floor`, `dust-cloth`, `vacuum`, `rake-leaves`, `wash-window`, `fold-laundry`, `take-trash`, `make-bed`, `set-table`, `wash-car`, `garden-hoe`, `paint-brush`, …). **Same class twice in one book → FAIL**. Soft near-dupe becomes **hard** when both scenes share a chore class | HARD FAIL when scene-list provided |
| Near-dupe (generic) | Optional JSON list of prior scene strings (`--prior-scenes`). Jaccard ≥ 0.75 without shared chore class → **WARNING** only. Skip if not provided | SOFT (unless chore-class match → HARD) |

### Eyes / pupils heuristic (best-effort)

Documented as a **heuristic**, not a guarantee:

1. Subject bbox = bounding box of near-black ink (L < 128).
2. Face region = **upper half** of that bbox, horizontally inset ~10%.
3. Find connected dark components that are small (`area ≥ 12` and `≤ ~4%` of face pixels), roughly square (`aspect ≤ 2.2`), reasonably filled (`fill ≥ 0.35`), and circular-ish (`4πA/P² ≥ 0.45` when OpenCV contours available).
4. **FAIL** if fewer than **1** such blob. Reason string always mentions `heuristic` and suggests regenerate or `--skip-eyes`.

False positives/negatives happen (side profiles, closed eyes, solid eye ovals). Teammates may pass `--skip-eyes` for a known-good batch after visual check; default remains ON to reduce QA load.

### Solid-fill “filled vs thin stroke” heuristic

A large black CC is treated as a **fill** (not a stroke) when:

- `area > 0.02 * W * H`, and
- after morphological erosion (3×3, 2 iterations) a non-trivial core remains (`eroded_area > 0.15 * area` **or** `eroded_area > 500`), **or**
- fill ratio `area / bbox_area > 0.55` with bbox both dimensions ≥ 40 px.

Thin outline rings that collapse under erosion are allowed even if area is large.

### Wire-grid heuristic

For each 400×400 tile (stride 200):

- Morphological open with a long thin kernel (40×1 / 1×40) to keep straight segments.
- Count **distinct** horizontal + vertical thin line strokes (adjacent rows/cols collapsed so a 2–3 px stroke = 1 run).
- FAIL if `h_runs + v_runs > 40` in any window.

### Chore-class normalization

`--scene-list` example (JSON):

```json
[
  {"page": 1, "subject": "puppy sweeping floor with broom"},
  {"page": 2, "subject": "kitten watering plants with watering can"}
]
```

YAML list of `{page, subject}` is also accepted. Subjects are lowercased; substring patterns map to a single class id. Two pages mapping to the same id → book-level **chore_class_dupe** FAIL.

## B) PDF package

| Check | Threshold | Severity |
|-------|-----------|----------|
| Author string | Must **not** contain `"Your Name Here"` (PDF metadata, extractable text, and optional `--author-text` file) | HARD FAIL |
| Interior page size | MediaBox ≈ **612 × 792 pt** (8.5″ × 11″), ±0.5 pt | HARD FAIL |
| Page count parity | Total page count must be **even** | HARD FAIL |
| Art / blank pairing | After `--front-matter-pages N` (default 4), remaining pages should equal `--designs` × 2 (default designs **32** → **64** content pages). Odd remaining indices after front matter should be near-blank (ink &lt; 0.05% of page when rasterizable; otherwise documented soft skip) | HARD FAIL on count mismatch; blank-pair content soft if no raster |
| **Page numbers** | Sample interior pages (after front matter) must show detectable page numbers. Prefer **pdf2image** (+ poppler) raster of corners / bottom-center for drawn numerals; also accept extractable text digits. **FAIL** if neither path finds enough hits | HARD FAIL |
| Cover spine | Given `--pages` and `--spine-factor` (default **0.002252**): `spine ≈ pages * factor` within **±0.001** in. Wrap **W ≈ 0.125 + 8.5 + spine + 8.5 + 0.125**; **H ≈ 11.25**. Accept cover MediaBox if present (±0.5 pt) | HARD FAIL |
| Barcode zone | Bottom-right of **back** cover ≈ **2.0″ × 1.2″** clear of ink/art. Requires optional `pdf2image` (+ poppler) to rasterize cover page 1; otherwise **TODO / skip with note** | SOFT skip if unavailable |
| Spine text | If spine **&lt; 0.25 in**, spine text should be skipped. Soft check when text extraction available | SOFT |
| Password / forms / JS | Encrypted PDF, AcroForm fields, or JavaScript → **FAIL** | HARD FAIL |

### Page-number gate dependency

- **Optional but recommended:** `pdf2image>=1.17.0` and host `poppler-utils` (see `requirements.txt` comment).
- Without pdf2image, only **extractable text** digits are checked. Pure drawn numerals with no text layer will **FAIL** until pdf2image is installed or numbers are embedded as text.
- Corner heuristic looks for digit-like dark connected components (no OCR) in four corners + bottom-center.

## Expected interior layout (32 designs)

```
[front matter: N pages]           # default N=4: title, copyright, belongs-to, how-to
[art_1, blank_1] × 32 designs     # 64 pages; blank backs reduce marker bleed-through
─────────────────────────────────
Total pages = N + 2*designs       # e.g. 4 + 64 = 68 (even)
```

Confirm spine with the [Amazon KDP Cover Calculator](https://kdp.amazon.com/cover-calculator) before upload.
