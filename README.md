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

## Quick start

### CLI Generation
```bash
python main.py --dry-run --pages 5
python main.py --pages 25 --auto-approve
```

### Web API
1. Setup Redis (required for async jobs).
2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
3. Run the API:
   ```bash
   uvicorn app.main:app --reload
   ```
4. Run the worker:
   ```bash
   python worker.py
   ```

---

## Architecture (Approach B)

- **API Layer**: FastAPI handles requests and enqueues jobs to Redis/RQ.
- **Worker Layer**: RQ workers handle async generation, Cloudflare rotation, and QA gate execution.
- **Pipeline**: `kdp_coloring.pipeline.generate_book()` encapsulates core logic for re-use.
- **Deployment**: Configured for Fly.io (Dockerfile/fly.toml included).

---

## CLI options

| Flag | Description |
|------|-------------|
| `--pages N` | Coloring page count |
| `--theme NAME` | Theme key/name |
| `--dry-run` | Placeholder generation (no network) |
| `--auto-approve` | Skip user-review gate |

---

## Web API endpoints

- `GET /api/v1/themes` — List available themes.
- `POST /api/v1/books` — Enqueue a new generation job (returns `job_id`).
- `GET /api/v1/books/{job_id}` — Get job status and metadata.
- `GET /api/v1/books/{job_id}/progress` — Get real-time job progress.
- `GET /api/v1/books/{job_id}/download/{file_type}` — Download `interior` or `cover` PDF.
- `POST /api/v1/books/{job_id}/approve` — Approve AWAITING_USER_REVIEW jobs.

---

## Configuration

- `config.yaml` — Core print specs and AI thresholds.
- `.env` — Cloudflare API credentials.
- `app/core/config.py` — Web service configuration.

See [`README.md` (legacy CLI details)](#cli-options) for detailed pipeline and QA gate documentation.
