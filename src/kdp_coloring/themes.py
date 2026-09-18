"""Theme loading, random selection, titles, and page subject prompts."""

from __future__ import annotations

import random
import re
from pathlib import Path
from typing import Any

import yaml

from .config import THEMES_PATH, load_config


def slugify(text: str) -> str:
    """URL/filesystem-safe slug."""
    s = text.lower().strip()
    s = re.sub(r"[^\w\s-]", "", s)
    s = re.sub(r"[-\s]+", "-", s)
    return s.strip("-") or "book"


def load_themes(path: Path | None = None) -> dict[str, Any]:
    themes_path = path or THEMES_PATH
    with themes_path.open(encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    if not data:
        raise ValueError(f"No themes found in {themes_path}")
    return data


def list_theme_keys(themes: dict[str, Any] | None = None) -> list[str]:
    t = themes if themes is not None else load_themes()
    return sorted(t.keys())


def pick_theme(
    themes: dict[str, Any],
    theme_name: str | None = None,
    rng: random.Random | None = None,
) -> tuple[str, dict[str, Any]]:
    """Pick a theme by name or randomly. Returns (key, theme_dict)."""
    rng = rng or random.Random()
    if theme_name:
        key = theme_name.lower().strip().replace(" ", "_")
        # allow display name match
        if key not in themes:
            for k, v in themes.items():
                if str(v.get("display_name", "")).lower() == theme_name.lower().strip():
                    key = k
                    break
        if key not in themes:
            available = ", ".join(sorted(themes.keys()))
            raise SystemExit(f"Unknown theme '{theme_name}'. Available: {available}")
        return key, themes[key]

    key = rng.choice(list(themes.keys()))
    return key, themes[key]


def generate_title(
    theme_key: str,
    theme: dict[str, Any],
    rng: random.Random | None = None,
) -> str:
    rng = rng or random.Random()
    templates = theme.get("title_templates") or [
        "Cute {theme} Coloring Book for Kids",
    ]
    display = theme.get("display_name") or theme_key.replace("_", " ").title()
    tmpl = rng.choice(templates)
    return tmpl.format(theme=display)


def pick_subjects(
    theme: dict[str, Any],
    count: int,
    rng: random.Random | None = None,
) -> list[str]:
    """Pick `count` distinct subjects (cycle/shuffle if pool smaller)."""
    rng = rng or random.Random()
    pool = list(theme.get("subjects") or ["cute animal sitting"])
    if not pool:
        pool = ["cute animal sitting"]

    subjects: list[str] = []
    while len(subjects) < count:
        batch = pool[:]
        rng.shuffle(batch)
        subjects.extend(batch)
    return subjects[:count]


def build_prompt(
    subject: str,
    cfg: dict[str, Any] | None = None,
    *,
    max_chars: int | None = 2048,
) -> str:
    """Build the default kids coloring-book prompt (elephant-style template).

    Cloudflare FLUX has no separate negative-prompt field, so `avoid_prompt`
    is appended as an Avoid: list. Subject is injected into the illustration ask.
    An optional `anatomy_check` block is appended after the style suffix so every
    page prompt includes anatomy QC instructions.

    Cloudflare FLUX rejects prompts longer than 2048 characters. When `max_chars`
    is set (default 2048), pack in priority order: intro+subject, anatomy_check,
    prompt_suffix, Avoid list — trimming Avoid then suffix at word boundaries so
    we never mid-cut a word (hard truncation has tripped CF NSFW filters).
    Pass max_chars=None to return the full untrimmed prompt.
    """
    c = cfg or load_config()
    suffix = " ".join(str(c.get("prompt_suffix") or "").split())
    anatomy = " ".join(str(c.get("anatomy_check") or "").split())
    avoid = " ".join(str(c.get("avoid_prompt") or "").split())

    intro = (
        f"Create a clean, professional children's coloring-book illustration of {subject}."
    )

    def _join(parts: list[str]) -> str:
        return " ".join(p for p in parts if p)

    def _trim_words(text: str, budget: int) -> str:
        if budget <= 0 or not text:
            return ""
        if len(text) <= budget:
            return text
        cut = text[:budget]
        if " " in cut:
            cut = cut.rsplit(" ", 1)[0]
        return cut.rstrip(" ,;:")

    # Ideal full prompt
    parts = [intro]
    if suffix:
        parts.append(suffix)
    if anatomy:
        parts.append(anatomy)
    if avoid:
        parts.append(f"Avoid: {avoid}")
    full = _join(parts)
    if max_chars is None or len(full) <= max_chars:
        return full

    # Over limit: keep intro + anatomy first, then as much suffix as fits, then Avoid.
    fixed = _join([intro, anatomy] if anatomy else [intro])
    remaining = max_chars - len(fixed) - (1 if fixed else 0)
    if remaining < 0:
        # Extreme case: subject+anatomy alone too long — keep intro, trim anatomy.
        if anatomy:
            budget = max_chars - len(intro) - 1
            return _join([intro, _trim_words(anatomy, budget)])
        return _trim_words(intro, max_chars)

    suffix_use = _trim_words(suffix, remaining) if suffix else ""
    packed = _join([intro, suffix_use, anatomy] if anatomy else [intro, suffix_use])
    remaining = max_chars - len(packed) - 1
    if avoid and remaining > len("Avoid: ") + 10:
        avoid_use = _trim_words(avoid, remaining - len("Avoid: "))
        if avoid_use:
            packed = _join([packed, f"Avoid: {avoid_use}"])
    return packed
