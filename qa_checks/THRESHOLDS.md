# QA / Packager hard-FAIL thresholds

Exact gates enforced by `scripts/qa_gate.py`. Soft checks print `WARNING` / `FLAG` only and never alone force exit code 1.

## A) Image pages (PNG / JPG)

| Check | Threshold | Severity |
|-------|-----------|----------|
| Canvas size | Exactly **2550 × 3300** portrait (8.5″ × 11″ @ 300 DPI) | HARD FAIL |
| Pure B&W / 1-bit | Mode `1`, **or** unique colors ≤ 2, **and** mid-gray pixels with L ∈ **[2, 253]** count must be **0** | HARD FAIL |
| Safe margin | Ink (near-black, L < 128) inside the outer **0.5″** strip (**150 px** @ 300 DPI) must be **0** | HARD FAIL |
| Solid black fills | Any connected black component with area **> ~2% of page** (`page_pixels * 0.02`) **and** filled (not a thin stroke ring) → FAIL | HARD FAIL |
| Wire-grid density | In any **400 × 400** window, **> ~40** thin parallel/orthogonal black runs → FAIL | HARD FAIL |
| Stroke hairlines | Sample every **25th** row; collect horizontal black-run lengths. If median run **< 5 px**, compute `thin1` = fraction of runs with length **1**. Fail if **thin1 > 1%** of runs | HARD FAIL |
| Near-dupe chore | Optional JSON list of prior scene strings. Similarity / overlap → print **WARNING / FLAG** only. Never hard-FAIL alone; skip if not provided | SOFT |

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

## B) PDF package

| Check | Threshold | Severity |
|-------|-----------|----------|
| Author string | Must **not** contain `"Your Name Here"` (PDF metadata, extractable text, and optional `--author-text` file) | HARD FAIL |
| Interior page size | MediaBox ≈ **612 × 792 pt** (8.5″ × 11″), ±0.5 pt | HARD FAIL |
| Page count parity | Total page count must be **even** | HARD FAIL |
| Art / blank pairing | After `--front-matter-pages N` (default 4), remaining pages should equal `--designs` × 2 (default designs **32** → **64** content pages). Odd remaining indices after front matter should be near-blank (ink &lt; 0.05% of page when rasterizable; otherwise documented soft skip) | HARD FAIL on count mismatch; blank-pair content soft if no raster |
| Cover spine | Given `--pages` and `--spine-factor` (default **0.002252**): `spine ≈ pages * factor` within **±0.001** in. Wrap **W ≈ 0.125 + 8.5 + spine + 8.5 + 0.125**; **H ≈ 11.25**. Accept cover MediaBox if present (±0.5 pt) | HARD FAIL |
| Barcode zone | Bottom-right of **back** cover ≈ **2.0″ × 1.2″** clear of ink/art. Requires optional `pdf2image` (+ poppler) to rasterize cover page 1; otherwise **TODO / skip with note** | SOFT skip if unavailable |
| Spine text | If spine **&lt; 0.25 in**, spine text should be skipped. Soft check when text extraction available | SOFT |
| Password / forms / JS | Encrypted PDF, AcroForm fields, or JavaScript → **FAIL** | HARD FAIL |

## Expected interior layout (32 designs)

```
[front matter: N pages]           # default N=4: title, copyright, belongs-to, how-to
[art_1, blank_1] × 32 designs     # 64 pages; blank backs reduce marker bleed-through
─────────────────────────────────
Total pages = N + 2*designs       # e.g. 4 + 64 = 68 (even)
```

Confirm spine with the [Amazon KDP Cover Calculator](https://kdp.amazon.com/cover-calculator) before upload.
