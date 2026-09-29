# KDP Kids Coloring Book Generator

Generate **print-ready Amazon KDP** coloring books for ages **3–7**:

- Random (or chosen) theme each run
- Default **50** interior pages (use `--pages 25` for free-tier AI limits)
- Trim size **8.5″ × 11″** (612 × 792 pt)
- Full-wrap **cover PDF** (back + spine + front)
- Cloudflare Workers AI (FLUX.1-schnell) generation
- FastAPI web service with async job queue (Redis/RQ)
- Hard-FAIL QA gates (print-ready compliance)

**No trademarked characters** — original cute subjects only.

---

## Quick Start

### Option 1: CLI (Direct Generation)

```bash
# Offline test (no API keys needed)
python main.py --dry-run --pages 5

# Live generation (requires Cloudflare credentials in .env)
python main.py --pages 25 --auto-approve
```

### Option 2: Web UI (Recommended)

#### Prerequisites
- **Docker Desktop** (for Redis)
- **Python 3.13+**
- Cloudflare credentials (for live generation) — **now manageable from the UI**

#### 1. Start Redis
```bash
# Using Docker Desktop
docker run -d --name redis -p 6379:6379 redis:7-alpine

# Verify
docker exec redis redis-cli ping
# Should return: PONG
```

#### 2. Install Dependencies
```bash
pip install -r requirements.txt
```

#### 3. Configure Environment
You can now add Cloudflare credentials **directly from the Web UI** (recommended):
1. Start the app (steps 4–5 below)
2. Open http://localhost:8000
3. Scroll to the **Cloudflare Credentials** card
4. Paste Account ID + API Token → click **Test & Save** — validated against the live Cloudflare API before saving to `.env`

Or manually create `.env` in project root:
```bash
# Required for live generation (optional for dry-run)
CLOUDFLARE_ACCOUNT_ID=your_account_id
CLOUDFLARE_API_TOKEN=your_token

# Optional rotation accounts
CLOUDFLARE_ACCOUNT_ID_2=...
CLOUDFLARE_API_TOKEN_2=...
CLOUDFLARE_ACCOUNT_ID_3=...
CLOUDFLARE_API_TOKEN_3=...

# Author name (default: "Your Name Here")
AUTHOR=Your Name
```

#### 4. Start API Server
```bash
uvicorn app.main:app --reload
# Or: python -m uvicorn app.main:app --reload
```
- API docs: http://localhost:8000/docs
- Web UI: http://localhost:8000

#### 5. Start Worker (in separate terminal)
```bash
python worker.py
```

#### 6. Generate a Book
Open http://localhost:8000 in your browser:
1. **Cloudflare Credentials** card (top) — add your Account ID + API Token (tested live before saving to `.env`)
2. Select theme, pages, author
3. Check "Dry run" for offline testing
4. Click "Generate Book"
5. Watch real-time progress
6. Download Interior/Cover PDFs when complete

---

## Architecture (Approach B)

```
┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│   Browser   │────▶│  FastAPI    │────▶│   Redis     │
│  (Frontend) │     │   (API)     │     │  (Queue)    │
└─────────────┘     └─────────────┘     └──────┬──────┘
                                               │
                    ┌──────────────────────────┘
                    ▼
              ┌─────────────┐
              │   Worker    │
              │  (RQ)       │
              └──────┬──────┘
                     │
        ┌────────────┼────────────┐
        ▼            ▼            ▼
   ┌────────┐  ┌───────────┐ ┌────────┐
   │ Cloud- │  │  QA Gates │ │  PDF   │
   │ flare  │  │           │ │ Builder│
   └────────┘  └───────────┘ └────────┘
```

- **API Layer**: FastAPI handles requests, enqueues jobs to Redis/RQ.
- **Worker Layer**: RQ workers process jobs — Cloudflare rotation, QA gates, PDF assembly.
- **Pipeline**: `kdp_coloring.pipeline.generate_book()` — pure function, reusable.
- **Deployment**: Fly.io ready (Dockerfile, fly.toml included).

---

## CLI Options

| Flag | Description |
|------|-------------|
| `--pages N` | Coloring page count (default: 50) |
| `--theme NAME` | Theme key/name; omit for random |
| `--seed N` | Reproducible RNG seed |
| `--author "..."` | Cover author name |
| `--dry-run` | Placeholder images (no network/API) |
| `--list-themes` | Show available themes |
| `--max-regen N` | Max FAIL retries per page (0 = unlimited) |
| `--auto-approve` | Skip user-review gate |
| `--skip-exit-gate` | Skip image QA (not for production) |

Output layout:
```
output/<slug>-<timestamp>/
  images/page_001.png …
  images/raw/page_001.png …
  failed_dump/page-01-attempt-1.png …
  failed_dump/manifest.json
  interior.pdf
  cover.pdf
  metadata.json
```

---

## Web API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/v1/themes` | List all themes |
| `POST` | `/api/v1/books` | Enqueue job (returns `job_id`) |
| `GET` | `/api/v1/books/{job_id}` | Job status + metadata |
| `GET` | `/api/v1/books/{job_id}/progress` | Real-time progress (SSE-ready) |
| `GET` | `/api/v1/books/{job_id}/download/interior` | Download interior PDF |
| `GET` | `/api/v1/books/{job_id}/download/cover` | Download cover PDF |
| `POST` | `/api/v1/books/{job_id}/approve` | Approve awaiting-review job |
| `POST` | `/api/v1/credentials/test` | Test Cloudflare credentials (no save) |
| `POST` | `/api/v1/credentials` | Save validated credentials to `.env` |
| `GET` | `/api/v1/credentials` | List configured accounts with status |
| `DELETE` | `/api/v1/credentials/{slot}` | Remove credentials from slot (1–3) |
| `POST` | `/api/v1/credentials/reload` | Force reload from `.env` |

---

## Configuration Files

| File | Purpose |
|------|---------|
| `config.yaml` | Page size, margins, bleed, spine factors, AI thresholds |
| `.env` | Cloudflare credentials, author name (managed via UI or CLI) |
| `app/core/config.py` | Web service settings (Redis URL, queue name, etc.) |
| `src/kdp_coloring/themes.yaml` | Theme definitions, subject pools |
| `qa_checks/THRESHOLDS.md` | QA gate thresholds |

---

## Logging

All modules use Python `logging` with a consistent format:
```
%(asctime)s [%(levelname)s] %(name)s: %(message)s
```

- **App / Worker**: `logging.basicConfig()` initialized in `app/main.py` and `worker.py` (INFO level, H:M:S timestamps)
- **Pipeline modules**: `logger = logging.getLogger(__name__)` at module level
- **Key events logged**:
  - Book generation start/completion with params
  - Per-page image generation progress
  - PDF assembly (interior/cover)
  - Cloudflare account rotation on quota exhaustion
  - QA gate passes/failures

---

## Spine Width (KDP B&W Paperback)

```
white paper:  spine_inches ≈ page_count × 0.002252
cream paper:  spine_inches ≈ page_count × 0.0025
```

Always verify with the [Amazon KDP Cover Calculator](https://kdp.amazon.com/cover-calculator).

---

## KDP Upload Checklist

1. **Interior** — Upload `interior.pdf` | Trim: 8.5″×11″ | B&W | Paper: White/Cream | Keep art inside 0.5″ margins
2. **Cover** — Upload `cover.pdf` (full wrap) | Leave barcode area clear | Verify spine text readability
3. **Metadata** — Replace author placeholder | Categories: Children's Books → Activity/Coloring | Age: 3–7
4. **Quality** — Spot-check for gray fills | No trademarked characters | Order proof copy
5. **Free-tier tip** — Start with `--pages 25` while testing

---

## Development

### Run Tests
```bash
python -m pytest
```

### Project Structure
```
kdp-coloring-book-generator/
├── main.py                    # CLI entrypoint
├── worker.py                  # RQ worker entrypoint
├── config.yaml                # Core configuration
├── requirements.txt           # Python dependencies
├── Dockerfile                 # Fly.io container
├── fly.toml                   # Fly.io deployment config
├── app/
│   ├── main.py               # FastAPI app + frontend
│   ├── templates/index.html  # Web UI
│   ├── api/routes.py         # REST endpoints
│   ├── workers/tasks.py      # RQ job handlers
│   ├── core/config.py        # Settings
│   ├── core/queue.py         # Redis/RQ helpers
│   └── models/schemas.py     # Pydantic models
├── src/kdp_coloring/
│   ├── pipeline.py           # Core generate_book()
│   ├── config.py             # Config loader
│   ├── themes.py             # Theme logic
│   ├── image_gen.py          # Cloudflare image generation
│   ├── pdf_builder.py        # PDF assembly
│   └── themes.yaml           # Theme data
├── scripts/qa_gate.py        # Hard-FAIL QA
└── output/                   # Generated books
```

---

## License / Responsibility

You are responsible for reviewing AI-generated art for trademark/copyright issues before publishing on KDP. This tool is a helper for original, age-appropriate coloring books — not a source of branded character content.