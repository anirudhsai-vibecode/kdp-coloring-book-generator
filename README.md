# KDP Kids Coloring Book Generator

Generate **print-ready Amazon KDP** coloring books for ages **3–7**:

- Random (or chosen) theme each run
- Default **50** interior pages (use `--pages 25` for free-tier AI limits)
- Trim size **8.5″ × 11″** (612 × 792 pt)
- Full-wrap **cover PDF** (back + spine + front)
- Free AI line art via **Cloudflare Workers AI (FLUX.1-schnell)** only (multi-account rotation on daily quota). Pollinations/HF are **not** used as generation fallback
- `--dry-run` placeholders so the PDF pipeline works offline

**No trademarked characters** (no Disney, Pokémon, Peppa Pig, etc.) — original cute subjects only.

---

## Quick start

```bash
cd /workspace/kdp-coloring-book-generator
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Offline verification (no API keys, no network for images)
python main.py --dry-run --pages 5

# Full run (requires CLOUDFLARE_ACCOUNT_ID + CLOUDFLARE_API_TOKEN)
python main.py --pages 25 --auto-approve

# Specific theme + seed + author
python main.py --theme dinosaurs --pages 50 --seed 42 --author "Your Name Here"
```

List themes:

```bash
python main.py --list-themes
```

---

## CLI options

| Flag | Description |
|------|-------------|
| `--pages N` | Coloring page count (default 50) |
| `--theme NAME` | Theme key/name; omit for random |
| `--seed N` | Reproducible RNG seed |
| `--author "..."` | Cover author (default placeholder) |
| `--dry-run` | Pillow placeholder line art (no network) |
| `--list-themes` | Show themes and exit |
| `--output-dir PATH` | Override output root |
| `--max-regen N` | Pause-and-ask after N exit-gate FAILs per page (default: unlimited until PASS) |
| `--require-user-review` / `--no-require-user-review` | Block packaging until USER_APPROVED.json (default: on) |
| `--auto-approve` | Skip user-review gate (automation) |
| `--packaging-only DIR` | Build PDFs for an existing PASS book dir |
| `--skip-exit-gate` | Escape hatch — skip image QA (not for production) |

Output layout:

```
output/<slug>-<timestamp>/
  images/page_001.png …
  images/raw/page_001.png …
  failed_dump/page-01-attempt-1.png …
  failed_dump/manifest.json
  AWAITING_USER_REVIEW.json   # when --require-user-review and not yet approved
  USER_APPROVED.json          # create this to unlock packaging
  PACKAGING_DONE.json         # after PDFs built
  interior.pdf
  cover.pdf
  metadata.json
```

---

## Free-tier AI notes

### Cloudflare Workers AI only (FLUX.1-schnell)

Live generation uses **Cloudflare Workers AI** exclusively. Pollinations and Hugging Face are **removed** from the provider fallback chain.

1. Create one or more free Cloudflare accounts and Workers AI API tokens (Run permission).
2. Copy `.env.example` → `.env` and set:
   - `CLOUDFLARE_ACCOUNT_ID` / `CLOUDFLARE_API_TOKEN` (primary)
   - Optional rotation: `CLOUDFLARE_ACCOUNT_ID_2` / `CLOUDFLARE_API_TOKEN_2`
   - Optional rotation: `CLOUDFLARE_ACCOUNT_ID_3` / `CLOUDFLARE_API_TOKEN_3`
3. The same keys are also loaded from `/home/box/agent-data/box-secrets.json` → `card` when present (Grok Bot).
4. Model: `@cf/black-forest-labs/flux-1-schnell` (`cloudflare_steps` in `config.yaml`; free ~10,000 Neurons/day per account).
5. On HTTP **429** with code **4006** / message containing **daily free allocation** or **10000 neurons**, the generator **rotates to the next unused account immediately**. If all accounts are exhausted → **STATUS PAUSED** (resume ~5:30 AM IST). FAIL images are never force-saved as finals.
6. Outputs still go through `postprocess_line_art` for kids outline pages.

Never commit real tokens. The app reads credentials only from the environment / `.env` / box-secrets and does not log them.

### Pipeline locks

- **Regen until PASS**: each page regenerates until the exit gate PASSes. Default is unlimited. Optional `--max-regen N` is a pause-and-ask threshold only (never force-final).
- **failed_dump/**: every exit-gate FAIL is copied to `output/<book>/failed_dump/page-NN-attempt-K.png` with `manifest.json`.
- **User review**: `--require-user-review` (default true) writes `AWAITING_USER_REVIEW.json` and blocks PDF packaging until `USER_APPROVED.json` appears, or pass `--auto-approve`.
- **Theme lock**: pet themes require pet subjects; garden chores / jars-as-main-subject / farm tools are rejected unless pet-related. See `theme_lock` in `config.yaml` and `build_prompt()`.

### Dry-run

`--dry-run` draws simple geometric line art with Pillow. Use this to validate PDFs and KDP layout without any AI service.

---

## Configuration

- `config.yaml` — page size, margins, bleed, spine factors, image size, provider
- `.env` / `.env.example` — `CLOUDFLARE_ACCOUNT_ID`/`_TOKEN` (+ optional `_2`/`_3`), `AUTHOR`
- `src/kdp_coloring/themes.yaml` — themes, title templates, subject pools

### Spine width (KDP B&W paperback)

```
white paper: spine_inches ≈ page_count × 0.002252
cream paper: spine_inches ≈ page_count × 0.0025
```

Always **confirm with the [Amazon KDP Cover Calculator](https://kdp.amazon.com/cover-calculator)** before uploading. Factors are configurable in `config.yaml`.

Cover PDF size (with 0.125″ bleed):

```
width  = bleed + 8.5 + spine + 8.5 + bleed
height = bleed + 11 + bleed
```

---

## KDP upload checklist

1. **Interior**
   - Upload `interior.pdf`
   - Trim: **8.5″ × 11″**
   - Interior: **Black & white** (or “Premium color” only if you intentionally add color — this tool targets B&W line art)
   - Paper: **White** (or Cream — match `config.yaml` paper / spine factor)
   - No page numbers required; keep art inside ~0.5″ margins (configured)

2. **Cover**
   - Upload `cover.pdf` (full wrap: back | spine | front)
   - Or rebuild in KDP Cover Creator using title/author from `metadata.json`
   - Leave KDP barcode area clear (marked on back cover)
   - Verify spine text is readable for your page count

3. **Metadata**
   - Replace author placeholder before publishing
   - Replace back-cover blurb placeholder
   - Categories: Children’s Books → Activity Books / Coloring Books
   - Age range: 3–7
   - Keywords: avoid trademarked character names

4. **Quality**
   - Spot-check pages for muddy gray fills; re-run problem pages or use dry-run style if needed
   - Confirm no copyrighted/trademarked characters appear in AI output
   - Order a proof copy before wide release

5. **Free-tier tip**
   - Start with `--pages 25` while testing AI generation
   - Scale to 50 once prompts/provider are stable

---

## Themes included

Animals, farm, ocean, dinosaurs, vehicles, alphabet, numbers, seasons, space, insects, birds, food, pets, jungle, arctic, construction, garden, weather, sports.

Each theme has title templates and a large subject pool so pages get different prompts.

---


## QA hard-FAIL gates

Automated print QA for page images and KDP PDF packages. Exit code **0** = all hard checks PASS; **1** = any hard FAIL. Soft checks print `WARNING` / `SKIP` only.

Thresholds are documented in [`qa_checks/THRESHOLDS.md`](qa_checks/THRESHOLDS.md).

### Page Factory exit gate (before QA handoff)

After generate, before QA: run the exit gate. On FAIL → regenerate; do **not** send to QA. Wired into `main.py` by default (unlimited regen until PASS; optional `--max-regen N` pause-and-ask; escape with `--skip-exit-gate`). Details: [`docs/PAGE_FACTORY.md`](docs/PAGE_FACTORY.md).

```bash
python scripts/page_factory_exit_gate.py path/to/images_dir
```

```bash
# Image pages (PNG/JPG) — canvas, pure B&W, margins, solid fills, wire-grid,
# hairlines, eyes/pupils heuristic (default ON; --skip-eyes to disable)
python scripts/qa_gate.py images path/to/dir
python scripts/qa_gate.py images path/to/page.png

# Optional near-dupe soft FLAG; chore-class hard FAIL with --scene-list
python scripts/qa_gate.py images path/to/dir --prior-scenes prior_scenes.json
python scripts/qa_gate.py images path/to/dir --scene-list scenes.yaml

# PDF package — interior and/or cover (page numbers hard FAIL on interior)
python scripts/qa_gate.py pdf --interior output/.../interior.pdf \
  --front-matter-pages 4 --designs 32

python scripts/qa_gate.py pdf --interior output/.../interior.pdf \
  --cover output/.../cover.pdf --pages 68 --spine-factor 0.002252 \
  --author-text metadata_author.txt
```

Expected interior layout for **32 designs**: `[N front-matter] + [art, blank]×32` (default N=4 → **68** pages, even). Cover spine ≈ `pages × 0.002252` (white B&W); wrap H ≈ 11.25″. Optional barcode-zone + page-number corner raster needs `pdf2image` + poppler (page numbers still checked via extractable text; drawn-only numerals FAIL until pdf2image is available).

## Project layout

```
kdp-coloring-book-generator/
  main.py
  config.yaml
  requirements.txt
  .env.example
  README.md
  docs/
    MASTER_PROMPT.md
    PAGE_FACTORY.md
  scripts/
    qa_gate.py
    page_factory_exit_gate.py
  qa_checks/
    THRESHOLDS.md
  src/kdp_coloring/
    config.py
    themes.py
    themes.yaml
    image_gen.py
    placeholders.py
    pdf_builder.py
  output/
```

---

## License / responsibility

You are responsible for reviewing AI-generated art for trademark/copyright issues before publishing on KDP. This tool is a helper for original, age-appropriate coloring books — not a source of branded character content.
