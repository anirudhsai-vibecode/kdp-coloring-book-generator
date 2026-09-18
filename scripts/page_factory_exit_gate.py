#!/usr/bin/env python3
"""
Page Factory post-generate exit gate.

Run AFTER page images are written and BEFORE QA handoff / PDF package:

  python scripts/page_factory_exit_gate.py path/to/images_dir
  python scripts/page_factory_exit_gate.py path/to/images_dir --prior-scenes scenes.json

Delegates hard FAILs to scripts/qa_gate.py images (canvas 2550×3300, 1-bit,
0.5″ margin, solid fills, wire-grid, hairlines). Soft near-dupe flags only.

Exit codes:
  0 — all hard checks PASS (safe to hand to QA)
  1 — one or more hard FAILs (regenerate failing pages; do NOT send to QA)
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
QA_GATE = ROOT / "scripts" / "qa_gate.py"


def run_exit_gate(images_path: Path, prior_scenes: Path | None = None) -> int:
    if not QA_GATE.is_file():
        print(f"ERROR: missing {QA_GATE}", file=sys.stderr)
        return 1
    if not images_path.exists():
        print(f"ERROR: path not found: {images_path}", file=sys.stderr)
        return 1

    cmd = [sys.executable, str(QA_GATE), "images", str(images_path)]
    if prior_scenes is not None:
        cmd.extend(["--prior-scenes", str(prior_scenes)])

    print(f"Page Factory exit gate → {' '.join(cmd)}")
    result = subprocess.run(cmd, cwd=str(ROOT))
    if result.returncode != 0:
        print(
            "EXIT GATE FAIL — regenerate failing page(s); do NOT hand off to QA.",
            file=sys.stderr,
        )
    else:
        print("EXIT GATE PASS — safe to hand off to QA.")
    return int(result.returncode)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description="Page Factory exit gate: hard image QA before QA handoff.",
    )
    p.add_argument("path", help="Image file or directory of page PNGs")
    p.add_argument(
        "--prior-scenes",
        help="Optional JSON list of prior scene strings (soft near-dupe flag only)",
    )
    args = p.parse_args(argv)
    prior = Path(args.prior_scenes) if args.prior_scenes else None
    return run_exit_gate(Path(args.path), prior_scenes=prior)


if __name__ == "__main__":
    raise SystemExit(main())
