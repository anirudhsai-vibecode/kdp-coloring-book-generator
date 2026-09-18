# KDP Kids Coloring Book Generator

Generate **print-ready Amazon KDP** coloring books for ages **3–7**:

- Random (or chosen) theme each run
- Default **50** interior pages (use `--pages 25` for free-tier AI limits)
- Trim size **8.5″ × 11″** (612 × 792 pt)
- Full-wrap **cover PDF** (back + spine + front)
- Free AI line art via **Cloudflare Workers AI (FLUX.1-schnell)** when CF env vars are set; **Pollinations.ai** fallback (no key); optional Hugging Face token
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

# Full run (Pollinations free image API)
python main.py --pages 25

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

Output layout:

```
output/<slug>-<timestamp>/
  images/page_001.png …
  interior.pdf
  cover.pdf
  metadata.json
```

---

## Free-tier AI notes

### Preferred: Cloudflare Workers AI (FLUX.1-schnell)

1. Create a free Cloudflare account and Workers AI API token (Run permission).
2. Copy `.env.example` → `.env` and set:
   - `CLOUDFLARE_ACCOUNT_ID`
   - `CLOUDFLARE_API_TOKEN`
3. Set `image.provider: cloudflare` in `config.yaml` (default), **or** leave any provider — if both CF env vars are set, Cloudflare is used first automatically.
4. Model: `@cf/black-forest-labs/flux-1-schnell` (`steps: 4` by default; free ~10,000 Neurons/day).
5. Outputs still go through `postprocess_line_art` for kids outline pages.

Never commit real tokens. The app reads credentials only from the environment / `.env` and does not log them.

### Fallback: Pollinations.ai (no key)

- HTTP image URL: `https://image.pollinations.ai/prompt/<encoded prompt>`
- **No API key required** — used when Cloudflare is unset or fails
- Images are post-processed toward cleaner line art

**Limitations found / expected:**

- Rate limits and occasional slow responses or timeouts
- Quality varies; not always perfect “coloring book” outlines (shading may appear — post-process helps)
- Public free service — availability and terms can change
- For bulk/50-page books, prefer `--pages 25` or run in batches with delays
- Retries + exponential backoff are built in (`config.yaml` → `image.retries`)

### Optional: Hugging Face

1. Copy `.env.example` → `.env`
2. Set `HF_TOKEN=hf_...`
3. Set `image.provider: huggingface` in `config.yaml` (or keep as later fallback)

Free HF Inference tiers have quotas and model cold-starts; some models may require a paid plan.

### Dry-run

`--dry-run` draws simple geometric line art with Pillow. Use this to validate PDFs and KDP layout without any AI service.

---

## Configuration

- `config.yaml` — page size, margins, bleed, spine factors, image size, provider
- `.env` / `.env.example` — `CLOUDFLARE_ACCOUNT_ID`, `CLOUDFLARE_API_TOKEN`, `AUTHOR`, `HF_TOKEN`, optional `POLLINATIONS_URL`
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

```bash
# Image pages (PNG/JPG) — canvas, pure B&W, margins, solid fills, wire-grid, hairlines
python scripts/qa_gate.py images path/to/dir
python scripts/qa_gate.py images path/to/page.png

# Optional near-dupe soft FLAG (never hard-FAIL alone)
python scripts/qa_gate.py images path/to/dir --prior-scenes prior_scenes.json

# PDF package — interior and/or cover
python scripts/qa_gate.py pdf --interior output/.../interior.pdf \
  --front-matter-pages 4 --designs 32

python scripts/qa_gate.py pdf --interior output/.../interior.pdf \
  --cover output/.../cover.pdf --pages 68 --spine-factor 0.002252 \
  --author-text metadata_author.txt
```

Expected interior layout for **32 designs**: `[N front-matter] + [art, blank]×32` (default N=4 → **68** pages, even). Cover spine ≈ `pages × 0.002252` (white B&W); wrap H ≈ 11.25″. Optional barcode-zone raster needs `pdf2image` + poppler (skipped with a TODO note if missing).

## Project layout

```
kdp-coloring-book-generator/
  main.py
  config.yaml
  requirements.txt
  .env.example
  README.md
  scripts/
    qa_gate.py
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
