# KDP Kids Coloring Book Generator

Generate **print-ready Amazon KDP** coloring books for ages **3–7**:

- Random (or chosen) theme each run
- Default **50** interior pages (use `--pages 25` for free-tier AI limits)
- Trim size **8.5″ × 11″** (612 × 792 pt)
- Full-wrap **cover PDF** (back + spine + front)
- Cloudflare Workers AI (FLUX.1-schnell) generation
- FastAPI web service with async job queue (Redis/RQ)
- Hard-FAIL QA gates (print-ready compliance)
- **User authentication** (login / register) with JWT tokens
- Job ownership – users only see their own jobs
- Cloudflare quota handling – jobs pause on 4006 errors and resume when quota refills
- **Job lookup** – check any job status by ID (useful after relogin)

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
- Cloudflare credentials (for live generation) – manageable from the UI

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

# JWT secret (required for auth)
JWT_SECRET_KEY=your-super-secret-key-change-in-production
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
1. **Login / Register** – create an account or log in.
2. After login, the **Create New Book** form appears.
3. **Cloudflare Credentials** card (top) – add your Account ID + API Token (tested live before saving to `.env`)
4. Select theme, pages, author
5. Check "Dry run" for offline testing
6. Click "Generate Book"
7. Watch real-time progress
8. Download Interior/Cover PDFs when complete

#### 7. Lookup a Job (after relogin)
If you get logged out (network issue, session expiry, etc.) and want to check the status of a previously started job:
1. Log back in
2. Scroll to the **Job Lookup** section (below the Cloudflare Credentials card)
3. Enter the Job ID you received when you originally created the job
4. Click **Lookup Job** – the current status (Queued, Running, Awaiting Review, Completed, Failed, Paused) will be displayed
5. If the job completed, download links will appear in the main Job Progress card

---

## Authentication

The web service now requires a JWT token for all job‑related endpoints.

- **Register**: `POST /api/v1/auth/register` with `{email, password}`
- **Login**: `POST /api/v1/auth/login` with `{email, password}` → returns `{access_token, token_type}`
- **Me**: `GET /api/v1/auth/me` (Bearer token) → returns user info
- **Logout**: remove the token from client storage (no server‑side state)

In the web UI, after login the token is stored in `localStorage` and automatically attached to every API request.  
If you prefer to use curl or Postman, copy the `access_token` from the login response and add the header:

```bash
curl -H "Authorization: Bearer <access_token>" \
     -X POST http://localhost:8000/api/v1/books \
     -H "Content-Type: application/json" \
     -d '{"theme":"cute","pages":25,"author":"Alice"}'

# Lookup a job via API:
curl -H "Authorization: Bearer <access_token>" \
     http://localhost:8000/api/v1/books/<job_id>
```

---

## Job Lookup Endpoint

**POST** `/api/v1/auth/lookup` – Lookup a job by ID (requires authentication)

This endpoint allows users to find any job by its ID, but only if they are authenticated. The job ownership check ensures users can only see jobs they created.

**Response** – Returns the same data as `/api/v1/books/{job_id}`.

---

## Web API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/v1/themes` | List all themes |
| `POST` | `/api/v1/books` | Enqueue job (returns `job_id`) – **requires auth** |
| `GET` | `/api/v1/books/{job_id}` | Job status + metadata – **requires auth + ownership** |
| `GET` | `/api/v1/books/{job_id}/progress` | Real-time progress (SSE-ready) – **requires auth** |
| `GET` | `/api/v1/books/{job_id}/download/interior` | Download interior PDF – **requires auth + ownership** |
| `GET` | `/api/v1/books/{job_id}/download/cover` | Download cover PDF – **requires auth + ownership** |
| `POST` | `/api/v1/books/{job_id}/approve` | Approve awaiting-review job – **requires auth + ownership** |
| `POST` | `/api/v1/credentials/test` | Test Cloudflare credentials (no save) |
| `POST` | `/api/v1/credentials` | Save validated credentials to `.env` |
| `GET` | `/api/v1/credentials` | List configured accounts with status |
| `DELETE` | `/api/v1/credentials/{slot}` | Remove credentials from slot (1–3) |
| `POST` | `/api/v1/credentials/reload` | Force reload from `.env` |
| `POST` | `/api/v1/auth/register` | User registration |
| `POST` | `/api/v1/auth/login` | Login – returns JWT access token |
| `GET`  | `/api/v1/auth/me` | Get current user info (Bearer token) |
| `POST` | `/api/v1/auth/logout` | Logout (client‑side token removal) |

---

## Configuration Files

| File | Purpose |
|------|---------|
| `config.yaml` | Page size, margins, bleed, spine factors, AI thresholds |
| `.env` | Cloudflare credentials, author name, JWT secret (managed via UI or CLI) |
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
  - Authentication events (login, register, token validation)
  - Job lookup requests

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
│   ├── templates/index.html  # Web UI (now with Job Lookup card)
│   ├── api/routes.py         # REST endpoints (job + auth + lookup)
│   ├── api/auth.py           # Auth endpoints
│   ├── middleware/auth.py    # JWT auth middleware
│   ├── core/token_utils.py   # JWT create/verify helpers
│   ├── workers/tasks.py      # RQ job handlers
│   ├── core/config.py        # Settings
│   ├── core/queue.py         # Redis/RQ helpers
│   └── models/
│       ├── user.py           # User model + helpers
│       └── schemas.py        # Pydantic models (jobs, themes, etc.)
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