# Testing

100% test coverage is the key to great vibe coding. Tests let you move fast,
trust your instincts, and ship with confidence — without them, vibe coding is
just yolo coding. With tests, it's a superpower.

## Framework

- **pytest 9.1.1** — standard Python test runner.

## How to run

```bash
python -m pytest            # full suite
python -m pytest -v         # verbose, one line per test
python -m pytest tests/test_qa_gate.py::test_zero_byte_png_is_hard_fail_not_crash  # one test
```

Tests live in `tests/`. `tests/conftest.py` puts `src/` and `scripts/` on
`sys.path` so `import kdp_coloring` and `import qa_gate` work from anywhere.

## Test layers

- **Unit** — pure functions and gate checks (`tests/test_qa_gate.py`).
- **Integration** — pipeline stages wired together (build a book dir, run
  `postprocess_line_art`, gate the result). No network, no Cloudflare
  credentials, no browser.
- **Smoke** — run the CLI end-to-end (`python main.py --dry-run --pages 5`)
  and confirm the exit gate and PDF QA pass.

## Conventions

- File naming: `tests/test_<module>.py`, functions `test_<what>`.
- Assertions name the exact check that failed (`assert checks["open"] == "FAIL"`),
  not "it renders".
- Mock all external dependencies (Cloudflare API, network, browser). Tests
  never read secrets or API keys.
- When fixing a bug, write a regression test that reproduces the exact
  precondition that triggered it.
- When adding a conditional, test both paths.
- Never commit code that makes existing tests fail.