"""Image generation: Cloudflare FLUX, Pollinations, optional HF, + outline post-process."""

from __future__ import annotations

import base64
import logging
import os
import time
import urllib.parse
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


def _download(url: str, timeout: int = 120) -> Image.Image:
    resp = requests.get(url, timeout=timeout, headers={"User-Agent": "kdp-coloring-book-generator/1.0"})
    resp.raise_for_status()
    from io import BytesIO

    return Image.open(BytesIO(resp.content)).convert("RGB")


def generate_pollinations(
    prompt: str,
    width: int,
    height: int,
    cfg: dict[str, Any],
    seed: int | None = None,
) -> Image.Image:
    """
    Free-tier path: Pollinations.ai image URL (no API key required).

    Limitations: rate limits, variable quality, occasional downtime,
    and generated art may need heavy post-processing for true line art.
    Long prompts are trimmed so the GET URL stays within practical limits
    (very long encoded prompts often 500 on image.pollinations.ai).
    """
    base = cfg["pollinations_url"].rstrip("/")
    # Keep prompt short enough that encoded URL remains usable (~1800 raw chars).
    pol_prompt = prompt if len(prompt) <= 1800 else prompt[:1800].rsplit(" ", 1)[0]
    encoded = urllib.parse.quote(pol_prompt)
    params = {
        "width": width,
        "height": height,
        "nologo": "true",
        "enhance": "false",
    }
    if seed is not None:
        params["seed"] = seed
    qs = urllib.parse.urlencode(params)
    url = f"{base}/{encoded}?{qs}"
    logger.info("Fetching Pollinations image…")
    return _download(url)




def _cloudflare_creds(cfg: dict[str, Any]) -> tuple[str, str]:
    """Return (account_id, api_token) from config/env. Never log values."""
    account_id = (cfg.get("cloudflare_account_id") or "").strip()
    token = (cfg.get("cloudflare_api_token") or "").strip()
    if not account_id:
        account_id = (os.environ.get("CLOUDFLARE_ACCOUNT_ID") or "").strip()
    if not token:
        token = (os.environ.get("CLOUDFLARE_API_TOKEN") or "").strip()
    return account_id, token


def cloudflare_available(cfg: dict[str, Any] | None = None) -> bool:
    """True when both Cloudflare env credentials are present."""
    c = cfg or {}
    account_id, token = _cloudflare_creds(c)
    return bool(account_id and token)


def generate_cloudflare(
    prompt: str,
    width: int,
    height: int,
    cfg: dict[str, Any],
) -> Image.Image:
    """
    Cloudflare Workers AI — FLUX.1-schnell (@cf/black-forest-labs/flux-1-schnell).

    Requires CLOUDFLARE_ACCOUNT_ID + CLOUDFLARE_API_TOKEN.
    API accepts prompt + steps only (no width/height); we resize afterward.
    Response JSON: result.image is base64-encoded JPEG.
    """
    from io import BytesIO

    account_id, token = _cloudflare_creds(cfg)
    if not account_id or not token:
        raise RuntimeError("CLOUDFLARE_ACCOUNT_ID / CLOUDFLARE_API_TOKEN not set")

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

    logger.info("Fetching Cloudflare Workers AI (FLUX.1-schnell) image…")
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
            raise RuntimeError(f"Cloudflare AI HTTP {resp.status_code} code={code}: {msg}")
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

def generate_huggingface(
    prompt: str,
    width: int,
    height: int,
    cfg: dict[str, Any],
) -> Image.Image:
    """Optional HF Inference API (requires HF_TOKEN). Uses a free public model."""
    token = cfg.get("hf_token") or ""
    if not token:
        raise RuntimeError("HF_TOKEN not set")

    # FLUX / SD models may require paid tiers; use a commonly available free model id.
    model = "black-forest-labs/FLUX.1-schnell"
    api_url = f"https://api-inference.huggingface.co/models/{model}"
    headers = {"Authorization": f"Bearer {token}"}
    payload = {
        "inputs": prompt,
        "parameters": {"width": min(width, 1024), "height": min(height, 1024)},
    }
    resp = requests.post(api_url, headers=headers, json=payload, timeout=180)
    if resp.status_code == 503:
        # Model loading
        time.sleep(10)
        resp = requests.post(api_url, headers=headers, json=payload, timeout=180)
    resp.raise_for_status()
    from io import BytesIO

    img = Image.open(BytesIO(resp.content)).convert("RGB")
    if img.size != (width, height):
        img = img.resize((width, height), Image.Resampling.LANCZOS)
    return img


def _resolve_provider(c: dict[str, Any]) -> str:
    """
    Prefer Cloudflare when config says so OR both CF env vars are set.
    Otherwise use configured provider (pollinations / huggingface).
    """
    provider = str(c.get("provider", "pollinations")).lower()
    if provider == "cloudflare" or cloudflare_available(c):
        return "cloudflare"
    return provider


def generate_with_retries(
    prompt: str,
    cfg: dict[str, Any] | None = None,
    seed: int | None = None,
) -> Image.Image:
    """Try configured provider with exponential backoff. Returns RAW (unprocessed) RGB image."""
    c = cfg or load_config()
    provider = _resolve_provider(c)
    retries = int(c.get("retries", 4))
    base = float(c.get("backoff_base_sec", 2.0))
    w, h = int(c["image_width_px"]), int(c["image_height_px"])

    def _call(p: str) -> Image.Image:
        if p == "cloudflare":
            return generate_cloudflare(prompt, w, h, c)
        if p == "huggingface" and c.get("hf_token"):
            return generate_huggingface(prompt, w, h, c)
        return generate_pollinations(prompt, w, h, c, seed=seed)

    last_err: Exception | None = None
    for attempt in range(retries):
        try:
            return _call(provider)
        except Exception as e:
            last_err = e
            err_l = str(e).lower()
            # CF free-tier neuron exhaustion / rate limit — back off harder
            if "4006" in err_l or "daily free allocation" in err_l or "429" in err_l:
                wait = max(base * (2**attempt), 30.0) * 2
            # Intermittent CF NSFW false positives — short retry often succeeds
            elif "8007" in err_l or "nsfw" in err_l:
                wait = base * (1.5**attempt) + 1.0
            else:
                wait = base * (2**attempt)
            logger.warning(
                "Image gen attempt %s/%s (%s) failed: %s — retry in %.1fs",
                attempt + 1,
                retries,
                provider,
                e,
                wait,
            )
            time.sleep(wait)

    # Fallbacks: Cloudflare → Pollinations → Hugging Face (if token)
    fallbacks: list[str] = []
    if provider == "cloudflare":
        fallbacks.append("pollinations")
    if provider != "huggingface" and c.get("hf_token"):
        fallbacks.append("huggingface")
    if provider != "pollinations" and "pollinations" not in fallbacks:
        fallbacks.append("pollinations")

    for fb in fallbacks:
        try:
            logger.info("Falling back to provider=%s", fb)
            return _call(fb)
        except Exception as e:
            last_err = e

    raise RuntimeError(f"Image generation failed after retries: {last_err}")


def generate_page_image(
    subject: str,
    out_path: Path,
    *,
    dry_run: bool = False,
    page_index: int = 0,
    seed: int | None = None,
    cfg: dict[str, Any] | None = None,
) -> Path:
    """Generate one coloring page image and save as PNG (plus raw/ for reprocess)."""
    from .themes import build_prompt

    c = cfg or load_config()
    w, h = int(c["image_width_px"]), int(c["image_height_px"])
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    if dry_run:
        return save_placeholder(out_path, subject, w, h, page_index)

    prompt = build_prompt(subject, c)
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
