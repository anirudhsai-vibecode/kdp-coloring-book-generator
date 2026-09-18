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
python main.py --pages 8 --theme ... --dry-run
# --skip-exit-gate   # escape hatch only
# --max-regen 2      # retries per page on FAIL (default 2)
```

`main.py` runs the gate per page (with regen) and a final directory sweep before building PDFs. Exit code **1** means do not hand off to QA.
