"""Regression tests for scripts/qa_gate.py hard-FAIL image checks.

These tests drive the gate's own report builder (qa_image) directly so they
run without a browser, without Cloudflare credentials, and without a full
book on disk. They assert on the CheckResult list, not on printed output.

Found by /qa on 2026-09-28. Report: .gstack/qa-reports/qa-report-kdp-coloring-book-generator-2026-09-28.md
"""

from __future__ import annotations

from pathlib import Path

import pytest

from qa_gate import FileReport, qa_image  # noqa: E402


def _checks(report: FileReport) -> dict[str, str]:
    """Map check name -> status for assertions."""
    return {c.name: c.status for c in report.checks}


def test_zero_byte_png_is_hard_fail_not_crash(tmp_path: Path) -> None:
    """Regression: ISSUE-002 — a 0-byte PNG must FAIL the `open` check, not raise.

    A truncated/zero-byte page PNG is a real failure mode: the pipeline writes
    the file, the exit gate runs, and PIL raises UnidentifiedImageError. The
    gate must surface it as a FAIL report (so the page gets regenerated) rather
    than aborting the whole gate with an unhandled exception.
    """
    bad = tmp_path / "page_001.png"
    bad.write_bytes(b"")

    report = qa_image(bad)

    assert report.hard_fail, "zero-byte image must be a hard FAIL"
    checks = _checks(report)
    assert checks.get("open") == "FAIL"
    # The only check that ran — no canvas/pure_bw/etc. on a 0-byte file.
    assert [c.name for c in report.checks] == ["open"]


def test_empty_png_does_not_mask_as_pass(tmp_path: Path) -> None:
    """An empty PNG must never report PASS on any check."""
    bad = tmp_path / "page_002.png"
    bad.write_bytes(b"")

    report = qa_image(bad)
    assert not any(c.status == "PASS" for c in report.checks)


def test_missing_file_is_hard_fail(tmp_path: Path) -> None:
    """A path that does not exist must FAIL, not raise FileNotFoundError."""
    missing = tmp_path / "does_not_exist.png"

    report = qa_image(missing)

    assert report.hard_fail
    assert _checks(report)["open"] == "FAIL"


def test_valid_processed_page_passes(tmp_path: Path) -> None:
    """Sanity check: a real processed page passes the gate (not just failures)."""
    from PIL import Image

    from kdp_coloring.image_gen import postprocess_line_art  # type: ignore[import-untyped]
    from kdp_coloring.placeholders import draw_placeholder  # type: ignore[import-untyped]

    img = draw_placeholder("dinosaur and a butterfly", 2550, 3300, 0)
    page = tmp_path / "page_001.png"
    postprocess_line_art(img).save(page, format="PNG")

    report = qa_image(page)
    assert not report.hard_fail, [c.name for c in report.checks if c.status == "FAIL"]