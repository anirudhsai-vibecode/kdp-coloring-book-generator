# Page Factory exit gate

Page Factory must not hand pages to QA until hard image checks PASS.

## Flow

1. **Generate** page PNG(s) (outline post-process included).
2. **Exit gate** — `python scripts/page_factory_exit_gate.py <images_dir>`  
   (wraps `python scripts/qa_gate.py images <images_dir>`).
3. On **FAIL** → regenerate that page (do **not** send to QA).
4. On **PASS** → safe for QA / interior PDF packaging.

## Checks (hard FAIL)

See `qa_checks/THRESHOLDS.md`. Includes:

- Canvas exactly **2550 × 3300** portrait
- Pure 1-bit / no mid-gray
- No ink in **0.5″** margin
- Solid black fills, wire-grid density, hairline strokes
- **Eyes / pupils** heuristic (default ON; `--skip-eyes` to disable)
- **Chore-class uniqueness** when `--scene-list` is provided (same tool/action class twice → FAIL)
- Interior PDF **page numbers** required at package QA (`qa_gate.py pdf`)

Out of hard gate: pose correctness, busy backgrounds, Amazon uniqueness (generic near-dupe remains soft unless chore-class match).

## CLI

```bash
# Standalone after a batch is written
python scripts/page_factory_exit_gate.py output/some-book/images
python scripts/page_factory_exit_gate.py output/some-book/images \
  --scene-list scenes.yaml --prior-scenes prior.json
# --skip-eyes   # escape hatch for pupils heuristic only

# Built into main generate path (default on)
python main.py --pages 8 --theme ... --dry-run --auto-approve
# --skip-exit-gate   # escape hatch only
# --max-regen N      # optional pause-and-ask after N FAILs (default: unlimited until PASS)
# --require-user-review (default) blocks packaging until USER_APPROVED.json
```

`main.py` regenerates each page until the exit gate PASSes (never force-saves FAIL as final).
Every FAIL is copied to `failed_dump/page-NN-attempt-K.png`. On Cloudflare daily quota
exhaustion (all accounts) → STATUS PAUSED. A final directory sweep runs before packaging.
Exit code **1** means do not hand off to QA / resume after pause.


## AD FLOOR LOCKS (pipeline)

1. **Until PASS** — regenerate each page until exit-gate PASS. Never force-save a FAIL as final. Hard pause only on Cloudflare quota exhaustion (all configured accounts).
2. **Cloudflare only** — no Pollinations/HF fallback. Up to 3 CF account slots (`CLOUDFLARE_ACCOUNT_ID` / `_2` / `_3`). On HTTP 429 code 4006, rotate to the next account.
3. **failed_dump/** — every exit-gate FAIL is saved as `page-NN-attempt-K.png` (+ `manifest.json`). After all pages PASS, packaging waits for user/AD review (`USER_APPROVED.json` or `--auto-approve`).
4. **Theme lock** — subjects/props must stay in-theme (e.g. pets rejects garden/jar-as-main-subject). Hard fail before final.
