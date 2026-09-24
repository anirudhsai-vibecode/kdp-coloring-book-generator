"""Theme loading, random selection, titles, and page subject prompts."""

from __future__ import annotations

import random
import re
from pathlib import Path
from typing import Any

import yaml

from .config import THEMES_PATH, load_config

# --- Theme lock: known theme keyword constraints --------------------------------
# Themes whose key/display contain "pet" must keep pets as the main subject.
# Garden chores / farm tools / jars-as-main-subject are rejected unless pet-related.

_PET_ANIMAL_TERMS = (
    "dog", "puppy", "puppies", "cat", "kitten", "kitty", "hamster", "fish",
    "goldfish", "bird", "parrot", "budgie", "canary", "rabbit", "bunny",
    "guinea pig", "turtle", "tortoise", "lizard", "ferret", "chinchilla",
    "gerbil", "mouse", "rat", "snake", "hedgehog", "pet",
)

_PET_RELATED_PROP_TERMS = (
    "collar", "leash", "yarn", "bowl", "tank", "cage", "hutch", "wheel",
    "toy", "bone", "basket", "scratching", "pet bed", "dog house", "treat",
    "litter", "aquarium", "stand",  # parrot stand etc.
)

# Main-subject reject list for pet themes (garden chores / farm tools / bare jars)
_PET_OFF_THEME_TERMS = (
    "garden chore", "garden", "weeding", "rake", "shovel", "hoe", "watering can",
    "wheelbarrow", "compost", "lawn mower", "farm tool", "pitchfork",
    "tractor", "plow", "harvest", "vegetable garden", "flower pot only",
    "mason jar", "cookie jar", "jam jar", "spice jar",
)


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


def is_pet_theme(theme_key: str | None, theme: dict[str, Any] | None = None) -> bool:
    """True when theme key or display name contains 'pet'."""
    key = (theme_key or "").lower()
    display = ""
    if theme:
        display = str(theme.get("display_name") or "").lower()
    blob = f"{key} {display}"
    return "pet" in blob


def theme_constraint_text(
    theme_key: str | None = None,
    theme: dict[str, Any] | None = None,
    cfg: dict[str, Any] | None = None,
) -> str:
    """Return prompt constraint sentence(s) for the active theme."""
    c = cfg or {}
    lock = c.get("theme_lock") or {}
    parts: list[str] = []

    # Config-level default theme_constraint (optional)
    default = " ".join(str(c.get("theme_constraint") or "").split())
    if default:
        parts.append(default)

    # Per-theme overrides from config.yaml theme_lock.<key>
    if theme_key and isinstance(lock, dict):
        entry = lock.get(theme_key) or lock.get((theme_key or "").lower())
        if isinstance(entry, dict):
            custom = " ".join(str(entry.get("constraint") or "").split())
            if custom:
                parts.append(custom)
        elif isinstance(entry, str) and entry.strip():
            parts.append(" ".join(entry.split()))

    if is_pet_theme(theme_key, theme):
        # Built-in pets lock (always applied when theme contains "pet")
        pets_default = (
            "THEME LOCK (pets): The main subject MUST be a pet animal "
            "(dog, cat, hamster, fish, bird pet, rabbit, guinea pig, turtle, etc.) "
            "or a clearly pet-related scene with that pet visible. "
            "Do NOT make garden chores, farm tools, or jars the main subject "
            "unless the pet is clearly present and primary."
        )
        if isinstance(lock, dict):
            pets_cfg = lock.get("pets") or lock.get("pet")
            if isinstance(pets_cfg, dict) and pets_cfg.get("constraint"):
                pets_default = " ".join(str(pets_cfg["constraint"]).split())
        if pets_default not in parts:
            parts.append(pets_default)

    return " ".join(parts).strip()


def check_theme_subject(
    subject: str,
    *,
    theme_key: str | None = None,
    theme: dict[str, Any] | None = None,
    cfg: dict[str, Any] | None = None,
) -> tuple[bool, str]:
    """Simple off-theme subject check for known themes.

    Returns (ok, reason). On failure, reason explains the theme lock violation.
    """
    del cfg  # reserved for future config-driven term lists
    subj = (subject or "").lower().strip()
    if not subj:
        return False, "empty subject"

    if is_pet_theme(theme_key, theme):
        has_pet = any(term in subj for term in _PET_ANIMAL_TERMS)
        has_pet_prop = any(term in subj for term in _PET_RELATED_PROP_TERMS)
        # Explicit off-theme props/chores as main subject
        for bad in _PET_OFF_THEME_TERMS:
            if bad in subj and not has_pet:
                return (
                    False,
                    f"pets theme rejects off-theme subject '{subject}' "
                    f"(matched '{bad}'; main subject must be a pet)",
                )
        # Bare jar without pet context
        if re.search(r"\bjar\b", subj) and not has_pet and "treat" not in subj:
            return (
                False,
                f"pets theme rejects jar-as-main-subject '{subject}' "
                "(unless pet-related, e.g. treat jar with a pet)",
            )
        # Must have a pet animal OR a clearly pet-related prop (collar/leash/treat…)
        if not has_pet and not has_pet_prop:
            return (
                False,
                f"pets theme requires a pet subject; got '{subject}'",
            )
        # Prop-only without pet animal: allow leash/collar/treat jar but flag garden-like
        if not has_pet and has_pet_prop:
            # OK — pet-related prop scenes (leash and collar set, treat jar)
            return True, ""

    return True, ""


def filter_subjects_for_theme(
    subjects: list[str],
    *,
    theme_key: str | None = None,
    theme: dict[str, Any] | None = None,
    cfg: dict[str, Any] | None = None,
) -> tuple[list[str], list[tuple[str, str]]]:
    """Split subjects into (kept, rejected[(subject, reason)])."""
    kept: list[str] = []
    rejected: list[tuple[str, str]] = []
    for s in subjects:
        ok, reason = check_theme_subject(s, theme_key=theme_key, theme=theme, cfg=cfg)
        if ok:
            kept.append(s)
        else:
            rejected.append((s, reason))
    return kept, rejected


def build_prompt(
    subject: str,
    cfg: dict[str, Any] | None = None,
    *,
    max_chars: int | None = 2048,
    theme_key: str | None = None,
    theme: dict[str, Any] | None = None,
) -> str:
    """Build the default kids coloring-book prompt (elephant-style template).

    Cloudflare FLUX has no separate negative-prompt field, so `avoid_prompt`
    is appended as an Avoid: list. Subject is injected into the illustration ask.
    An optional `anatomy_check` block is appended after the style suffix so every
    page prompt includes anatomy QC instructions.
    Theme lock constraints (e.g. pets) are folded in when theme_key/theme given.

    Cloudflare FLUX rejects prompts longer than 2048 characters. When `max_chars`
    is set (default 2048), pack in priority order: intro+subject, theme lock,
    anatomy_check, prompt_suffix, Avoid list — trimming Avoid then suffix at word
    boundaries so we never mid-cut a word (hard truncation has tripped CF NSFW
    filters). Pass max_chars=None to return the full untrimmed prompt.
    """
    c = cfg or load_config()
    suffix = " ".join(str(c.get("prompt_suffix") or "").split())
    anatomy = " ".join(str(c.get("anatomy_check") or "").split())
    avoid = " ".join(str(c.get("avoid_prompt") or "").split())
    theme_c = theme_constraint_text(theme_key, theme, c)

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

    # Ideal full prompt (theme lock sits early so it survives trimming)
    parts = [intro]
    if theme_c:
        parts.append(theme_c)
    if suffix:
        parts.append(suffix)
    if anatomy:
        parts.append(anatomy)
    if avoid:
        parts.append(f"Avoid: {avoid}")
    full = _join(parts)
    if max_chars is None or len(full) <= max_chars:
        return full

    # Over limit: keep intro + theme + anatomy first, then suffix, then Avoid.
    fixed = _join([p for p in [intro, theme_c, anatomy] if p])
    remaining = max_chars - len(fixed) - (1 if fixed else 0)
    if remaining < 0:
        # Extreme case — keep intro + theme, trim anatomy.
        core = _join([p for p in [intro, theme_c] if p])
        if anatomy:
            budget = max_chars - len(core) - 1
            return _join([core, _trim_words(anatomy, budget)])
        return _trim_words(core, max_chars)

    suffix_use = _trim_words(suffix, remaining) if suffix else ""
    packed = _join([p for p in [intro, theme_c, suffix_use, anatomy] if p])
    remaining = max_chars - len(packed) - 1
    if avoid and remaining > len("Avoid: ") + 10:
        avoid_use = _trim_words(avoid, remaining - len("Avoid: "))
        if avoid_use:
            packed = _join([packed, f"Avoid: {avoid_use}"])
    return packed
