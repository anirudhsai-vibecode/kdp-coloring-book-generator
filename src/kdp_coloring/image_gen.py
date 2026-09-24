"""Image generation: Cloudflare FLUX (multi-account) + outline post-process.

Live generation is Cloudflare Workers AI only — Pollinations/HF removed from
the provider fallback chain. On HTTP 429 code 4006 (daily free allocation /
~10000 neurons), rotate to the next configured CF account immediately.
"""

from __future__ import annotations

import base64
import logging
import os
import time
from pathlib import Path
from typing import Any

import cv2
import numpy as np
import requests
from PIL import Image

from .config import load_config
from .placeholders import save_placeholder

logger = logging.getLogger(__name__)


def postprocess_line_art(img: Image.Image) -> Image.Image:
    """
    Gentle B&W cleanup for already-clean FLUX / line-art outputs.

    Thresholds near-black strokes to pure black on pure white, whites out border
    (and Pollinations watermark corner), and drops tiny speckles. Avoids the
    heavy contour/Canny pipeline that doubles lines and jaggedizes clean art.
    Falls back to postprocess_line_art_heavy if the page is mostly mid-gray
    (shaded fills) rather than line art.
    """
    rgb = np.asarray(img.convert("RGB"))
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    h, w = gray.shape

    border = max(4, int(round(min(h, w) * 0.02)))
    gray[:border, :] = 255
    gray[-border:, :] = 255
    gray[:, :border] = 255
    gray[:, -border:] = 255

    # Pollinations watermark corner (harmless no-op for Cloudflare FLUX)
    corner_h = max(1, int(round(h * 0.12)))
    corner_w = max(1, int(round(w * 0.25)))
    gray[h - corner_h :, w - corner_w :] = 255

    # Mid-gray mass → shaded art; use heavy outline extractor instead
    mid_frac = float(np.mean((gray >= 40) & (gray <= 220)))
    if mid_frac > 0.08:
        logger.info("Gentle postprocess: mid-gray %.1f%% — falling back to heavy outline extractor", mid_frac * 100)
        return postprocess_line_art_heavy(img)

    # thr=160 matches prior gentle reference (~99.98% agreement)
    _, binary = cv2.threshold(gray, 160, 255, cv2.THRESH_BINARY_INV)

    min_cc = max(20, (h * w) // 100000)
    n_cc, cc_labels, cc_stats, _ = cv2.connectedComponentsWithStats(binary, connectivity=8)
    cleaned = np.zeros_like(binary)
    for i in range(1, n_cc):
        if cc_stats[i, cv2.CC_STAT_AREA] >= min_cc:
            cleaned[cc_labels == i] = 255

    cleaned[:border, :] = 0
    cleaned[-border:, :] = 0
    cleaned[:, :border] = 0
    cleaned[:, -border:] = 0
    cleaned[h - corner_h :, w - corner_w :] = 0

    result = np.full_like(cleaned, 255)
    result[cleaned > 0] = 0
    return Image.fromarray(result).convert("RGB")


def postprocess_line_art_heavy(img: Image.Image) -> Image.Image:
    """
    LEGACY heavy OpenCV outline extractor. Prefer postprocess_line_art() for clean FLUX line art.

    Designed for ages 3–7: mostly white page, continuous black outlines, open
    interiors to color. Never hard-binarizes shading into solid black fills.

    Pipeline:
      1. Grayscale
      2. White-out border + bottom-right watermark corner
      3. Strong blur (kills hatching / shading texture)
      4. Otsu segment → keep only large dark regions
      5. Draw contour outlines of those regions (exteriors + holes)
      6. Mild Canny on the blurred image for extra structure (sparse)
      7. Dilate / close for kid-friendly stroke width; drop speckles
    """
    rgb = np.asarray(img.convert("RGB"))
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    h, w = gray.shape

    # Border strip kills frame artifacts from the model
    border = max(4, int(round(min(h, w) * 0.02)))
    gray[:border, :] = 255
    gray[-border:, :] = 255
    gray[:, :border] = 255
    gray[:, -border:] = 255

    # Pollinations watermark (bottom-right; logos are wider than tall)
    corner_h = max(1, int(round(h * 0.12)))
    corner_w = max(1, int(round(w * 0.25)))
    gray[h - corner_h :, w - corner_w :] = 255

    # Strong blur merges fine hatching/shading into broad regions so we
    # extract shape outlines instead of every scribble stroke.
    blurred = cv2.GaussianBlur(gray, (13, 13), 0)

    # Segment dark content vs background
    _, binary = cv2.threshold(blurred, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    binary[:border, :] = 0
    binary[-border:, :] = 0
    binary[:, :border] = 0
    binary[:, -border:] = 0
    binary[h - corner_h :, w - corner_w :] = 0

    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7, 7))
    binary = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, k, iterations=2)
    binary = cv2.morphologyEx(binary, cv2.MORPH_OPEN, k, iterations=1)

    # Drop tiny dark islands before contouring
    min_blob = max(400, (h * w) // 8000)
    n_labels, labels, stats, _ = cv2.connectedComponentsWithStats(binary, connectivity=8)
    filtered = np.zeros_like(binary)
    for i in range(1, n_labels):
        if stats[i, cv2.CC_STAT_AREA] >= min_blob:
            filtered[labels == i] = 255

    # Contour outlines only (RETR_CCOMP → outer shapes + interior holes)
    contours, _ = cv2.findContours(filtered, cv2.RETR_CCOMP, cv2.CHAIN_APPROX_SIMPLE)
    outline = np.zeros_like(filtered)
    thickness = max(4, min(h, w) // 220)
    min_area = max(80, (h * w) // 25000)
    for cnt in contours:
        if cv2.contourArea(cnt) < min_area:
            continue
        # Light polygon approx smooths jagged Otsu boundaries a bit
        epsilon = 0.0015 * cv2.arcLength(cnt, True)
        approx = cv2.approxPolyDP(cnt, epsilon, True)
        cv2.drawContours(outline, [approx], -1, 255, thickness=thickness)

    # Sparse Canny on heavily blurred image (structural edges only, not hatch)
    canny = cv2.Canny(blurred, threshold1=100, threshold2=200)
    canny[:border, :] = 0
    canny[-border:, :] = 0
    canny[:, :border] = 0
    canny[:, -border:] = 0
    canny[h - corner_h :, w - corner_w :] = 0
    # Keep Canny only near contour structure so hatch crumbs don't flood the page
    near = cv2.dilate(outline, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (9, 9)), iterations=2)
    canny = cv2.bitwise_and(canny, near)

    combined = cv2.bitwise_or(outline, canny)

    # Kid-friendly stroke width + reconnect near-broken segments
    thick_k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
    thick = cv2.dilate(combined, thick_k, iterations=1)
    thick = cv2.morphologyEx(thick, cv2.MORPH_CLOSE, thick_k, iterations=1)

    # Remove speckles
    min_cc = max(40, (h * w) // 50000)
    n_cc, cc_labels, cc_stats, _ = cv2.connectedComponentsWithStats(thick, connectivity=8)
    cleaned = np.zeros_like(thick)
    for i in range(1, n_cc):
        if cc_stats[i, cv2.CC_STAT_AREA] >= min_cc:
            cleaned[cc_labels == i] = 255

    # Final white-outs
    cleaned[:border, :] = 0
    cleaned[-border:, :] = 0
    cleaned[:, :border] = 0
    cleaned[:, -border:] = 0
    cleaned[h - corner_h :, w - corner_w :] = 0

    # Black lines on pure white
    result = np.full_like(cleaned, 255)
    result[cleaned > 0] = 0
    return Image.fromarray(result).convert("RGB")


class CloudflarePausedError(RuntimeError):
    """Raised when all Cloudflare accounts are exhausted (daily free allocation).

    STATUS PAUSED — resume after free-tier reset (~5:30 AM IST / ~00:00 UTC).
    Do not force-save a FAIL image as final.
    """

    def __init__(self, message: str | None = None):
        msg = message or (
            "STATUS PAUSED: Cloudflare daily free allocation exhausted on all "
            "configured accounts (HTTP 429 / code 4006 / ~10000 neurons). "
            "Resume after free-tier reset (~5:30 AM IST). "
            "Do not force-save FAIL images as finals."
        )
        super().__init__(msg)


def _is_cf_quota_error(exc: BaseException | str, status_code: int | None = None) -> bool:
    """True for CF daily free allocation / neuron exhaustion (429 + 4006)."""
    text = str(exc).lower()
    if status_code == 429 and ("4006" in text or "neuron" in text or "daily free" in text):
        return True
    if "4006" in text:
        return True
    if "daily free allocation" in text:
        return True
    if "10000 neurons" in text or "10,000 neurons" in text or "10000 neuron" in text:
        return True
    if status_code == 429 and "neuron" in text:
        return True
    return False


def _cloudflare_accounts(cfg: dict[str, Any]) -> list[dict[str, str]]:
    """Ordered CF accounts from config (env / box-secrets already loaded)."""
    accounts = cfg.get("cloudflare_accounts") or []
    if accounts:
        return list(accounts)
    # Fallback: single primary from flat keys
    account_id = (cfg.get("cloudflare_account_id") or "").strip()
    token = (cfg.get("cloudflare_api_token") or "").strip()
    if not account_id:
        account_id = (os.environ.get("CLOUDFLARE_ACCOUNT_ID") or "").strip()
    if not token:
        token = (os.environ.get("CLOUDFLARE_API_TOKEN") or "").strip()
    if account_id and token:
        return [
            {
                "account_id": account_id,
                "api_token": token,
                "slot": "1",
                "label": "cf-account-1",
            }
        ]
    return []


def cloudflare_available(cfg: dict[str, Any] | None = None) -> bool:
    """True when at least one Cloudflare account pair is present."""
    return bool(_cloudflare_accounts(cfg or {}))


def generate_cloudflare(
    prompt: str,
    width: int,
    height: int,
    cfg: dict[str, Any],
    *,
    account: dict[str, str] | None = None,
) -> Image.Image:
    """
    Cloudflare Workers AI — FLUX.1-schnell (@cf/black-forest-labs/flux-1-schnell).

    Requires at least one CLOUDFLARE_ACCOUNT_ID + CLOUDFLARE_API_TOKEN pair.
    API accepts prompt + steps only (no width/height); we resize afterward.
    Response JSON: result.image is base64-encoded JPEG.

    On HTTP 429 with code 4006 / daily free allocation, raises RuntimeError
    whose message is detected by _is_cf_quota_error for account rotation.
    """
    from io import BytesIO

    acct = account
    if acct is None:
        accounts = _cloudflare_accounts(cfg)
        if not accounts:
            raise RuntimeError(
                "No Cloudflare credentials set. Configure CLOUDFLARE_ACCOUNT_ID / "
                "CLOUDFLARE_API_TOKEN (and optional _2 / _3 rotation accounts)."
            )
        acct = accounts[0]

    account_id = acct["account_id"]
    token = acct["api_token"]
    label = acct.get("label") or f"cf-account-{acct.get('slot', '?')}"

    url = (
        f"https://api.cloudflare.com/client/v4/accounts/{account_id}"
        "/ai/run/@cf/black-forest-labs/flux-1-schnell"
    )
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    steps = int(cfg.get("cloudflare_steps", 4))
    steps = max(1, min(steps, 8))
    # CF schema: prompt (required), steps (optional). No documented width/height.
    # CF FLUX prompt max is 2048 chars; prefer word-boundary trim if caller oversends.
    cf_prompt = prompt if len(prompt) <= 2048 else prompt[:2048].rsplit(" ", 1)[0]
    body = {"prompt": cf_prompt, "steps": steps}

    logger.info("Fetching Cloudflare Workers AI (FLUX.1-schnell) via %s…", label)
    resp = requests.post(url, headers=headers, json=body, timeout=180)
    try:
        data = resp.json()
    except Exception:
        data = {}
    if resp.status_code >= 400 or not data.get("success", True):
        errs = data.get("errors") or data.get("messages") or []
        # Prefer short code/message for logs (never log tokens/prompt secrets)
        if isinstance(errs, list) and errs:
            first = errs[0] if isinstance(errs[0], dict) else {"message": str(errs[0])}
            code = first.get("code")
            msg = str(first.get("message") or first)[:160]
            err = RuntimeError(
                f"Cloudflare AI HTTP {resp.status_code} code={code}: {msg}"
            )
            # Annotate for quota detection
            err.cf_status = resp.status_code  # type: ignore[attr-defined]
            err.cf_code = code  # type: ignore[attr-defined]
            raise err
        resp.raise_for_status()
        raise RuntimeError(f"Cloudflare AI error: {errs or data}")

    result = data.get("result") or {}
    b64 = result.get("image")
    if not b64:
        raise RuntimeError("Cloudflare AI response missing result.image")

    img = Image.open(BytesIO(base64.b64decode(b64))).convert("RGB")
    if img.size != (width, height):
        img = img.resize((width, height), Image.Resampling.LANCZOS)
    return img


def _resolve_provider(c: dict[str, Any]) -> str:
    """Live generation is Cloudflare-only. Pollinations/HF fallbacks removed."""
    provider = str(c.get("provider", "cloudflare")).lower()
    if provider != "cloudflare":
        logger.warning(
            "provider=%s ignored — live generation is Cloudflare-only "
            "(Pollinations/HF removed from fallback chain)",
            provider,
        )
    if not cloudflare_available(c):
        raise RuntimeError(
            "Cloudflare credentials required. Set CLOUDFLARE_ACCOUNT_ID + "
            "CLOUDFLARE_API_TOKEN (optional _2 / _3 for rotation). "
            "Pollinations/HF are not used as generation fallback."
        )
    return "cloudflare"


def generate_with_retries(
    prompt: str,
    cfg: dict[str, Any] | None = None,
    seed: int | None = None,
) -> Image.Image:
    """Try Cloudflare with retries + multi-account rotation on quota (4006).

    Returns RAW (unprocessed) RGB image. `seed` is accepted for API compat but
    CF FLUX.1-schnell does not expose a seed parameter.

    On daily free allocation exhaustion of ALL configured accounts, raises
    CloudflarePausedError (STATUS PAUSED) — never falls back to Pollinations/HF.
    """
    del seed  # CF API has no seed; kept for call-site compatibility
    c = cfg or load_config()
    _resolve_provider(c)
    retries = int(c.get("retries", 4))
    base = float(c.get("backoff_base_sec", 2.0))
    w, h = int(c["image_width_px"]), int(c["image_height_px"])
    accounts = _cloudflare_accounts(c)
    if not accounts:
        raise RuntimeError("No Cloudflare accounts configured")

    exhausted: set[str] = set()
    last_err: Exception | None = None
    account_index = 0

    # Cap total attempts: per-account retries, rotating on quota
    max_attempts = max(retries * len(accounts), retries)
    attempt = 0
    while attempt < max_attempts:
        # Skip exhausted accounts
        while account_index < len(accounts) and accounts[account_index]["slot"] in exhausted:
            account_index += 1
        if account_index >= len(accounts):
            # All accounts exhausted
            raise CloudflarePausedError()

        acct = accounts[account_index]
        label = acct.get("label") or f"cf-account-{acct.get('slot')}"
        try:
            return generate_cloudflare(prompt, w, h, c, account=acct)
        except Exception as e:
            last_err = e
            status = getattr(e, "cf_status", None)
            err_l = str(e).lower()
            if status is None and "http 429" in err_l:
                status = 429

            if _is_cf_quota_error(e, status_code=status):
                exhausted.add(acct["slot"])
                logger.warning(
                    "Cloudflare quota exhausted on %s (%s) — rotating to next account",
                    label,
                    e,
                )
                account_index += 1
                # Retry immediately on next account (no long wait)
                attempt += 1
                continue

            # Intermittent CF NSFW false positives — short retry often succeeds
            if "8007" in err_l or "nsfw" in err_l:
                wait = base * (1.5**attempt) + 1.0
            else:
                wait = base * (2 ** min(attempt, 6))
            logger.warning(
                "Image gen attempt %s/%s (%s) failed: %s — retry in %.1fs",
                attempt + 1,
                max_attempts,
                label,
                e,
                wait,
            )
            time.sleep(wait)
            attempt += 1

    if exhausted and len(exhausted) >= len(accounts):
        raise CloudflarePausedError()
    raise RuntimeError(f"Image generation failed after retries: {last_err}")


def generate_page_image(
    subject: str,
    out_path: Path,
    *,
    dry_run: bool = False,
    page_index: int = 0,
    seed: int | None = None,
    cfg: dict[str, Any] | None = None,
    theme_key: str | None = None,
    theme: dict[str, Any] | None = None,
) -> Path:
    """Generate one coloring page image and save as PNG (plus raw/ for reprocess)."""
    from .themes import build_prompt, check_theme_subject

    c = cfg or load_config()
    w, h = int(c["image_width_px"]), int(c["image_height_px"])
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    # Theme lock: reject off-theme subjects before spending CF neurons
    if theme_key or theme:
        ok, reason = check_theme_subject(subject, theme_key=theme_key, theme=theme, cfg=c)
        if not ok:
            raise ValueError(f"THEME LOCK FAIL: {reason}")

    if dry_run:
        return save_placeholder(out_path, subject, w, h, page_index)

    prompt = build_prompt(subject, c, theme_key=theme_key, theme=theme)
    page_seed = (seed + page_index) if seed is not None else None
    raw = generate_with_retries(prompt, c, seed=page_seed)
    raw = raw.resize((w, h), Image.Resampling.LANCZOS)

    # Persist raw so --reprocess can re-run outline pipeline without re-download
    raw_dir = out_path.parent / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    raw_path = raw_dir / out_path.name
    raw.save(raw_path, format="PNG")
    logger.info("Saved raw: %s", raw_path)

    processed = postprocess_line_art(raw)
    processed.save(out_path, format="PNG")
    return out_path




def reprocess_raw_images(book_dir: Path, cfg: dict[str, Any] | None = None) -> list[Path]:
    """
    Re-run postprocess_line_art on images/raw/*.png inside an existing book folder.
    Writes processed PNGs into images/. Returns sorted list of processed paths.
    """
    book_dir = Path(book_dir)
    raw_dir = book_dir / "images" / "raw"
    images_dir = book_dir / "images"
    c = cfg or load_config()
    w, h = int(c["image_width_px"]), int(c["image_height_px"])

    if not raw_dir.is_dir():
        raise FileNotFoundError(
            f"No images/raw/ directory in {book_dir}. "
            "Cannot reprocess — only processed PNGs exist (or this is a dry-run book). "
            "Regenerate with a live run to create raw sources."
        )

    raw_files = sorted(raw_dir.glob("page_*.png"))
    if not raw_files:
        raise FileNotFoundError(
            f"No page_*.png files in {raw_dir}. "
            "Cannot reprocess without raw sources."
        )

    images_dir.mkdir(parents=True, exist_ok=True)
    out_paths: list[Path] = []
    for raw_path in raw_files:
        logger.info("Reprocessing %s", raw_path.name)
        with Image.open(raw_path) as im:
            raw = im.convert("RGB")
        if raw.size != (w, h):
            raw = raw.resize((w, h), Image.Resampling.LANCZOS)
        processed = postprocess_line_art(raw)
        out_path = images_dir / raw_path.name
        processed.save(out_path, format="PNG")
        out_paths.append(out_path)
    return out_paths
