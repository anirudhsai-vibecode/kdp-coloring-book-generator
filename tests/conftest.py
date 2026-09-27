"""Test fixtures: put src/ and scripts/ on sys.path so `import kdp_coloring`
and `import qa_gate` work under pytest."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
for sub in ("src", "scripts"):
    p = ROOT / sub
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))