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

# Print canvas locks (match qa_gate / config defaults)
_PRINT_W = 2550
_PRINT_H = 3300
_MARGIN_PX = 150  # 0.5″ @ 300 DPI
_SOLID_AREA_FRAC = 0.02


def _is_stroke_like(mask_cc: np.ndarray, area: int) -> bool:
    """True if component looks like stroke/outline art (do NOT desolidify → ribbons).

    Skip when 1–2 erosions erase nearly all ink, or perimeter²/area is high (thin rings).
    """
    u8 = (mask_cc.astype(np.uint8)) * 255
    # After 1–2 erosions, stroke art vanishes; true solid fills keep a core.
    eroded1 = cv2.erode(u8, np.ones((3, 3), np.uint8), iterations=1)
    eroded2 = cv2.erode(u8, np.ones((3, 3), np.uint8), iterations=2)
    rem1 = int(np.count_nonzero(eroded1))
    rem2 = int(np.count_nonzero(eroded2))
    if rem2 < max(80, int(0.05 * area)) or rem1 < max(120, int(0.12 * area)):
        return True
    # High perimeter²/area → thin elongated / already-outline rings
    cnts, _ = cv2.findContours(u8, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not cnts:
        return True
    peri = float(sum(cv2.arcLength(c, True) for c in cnts))
    if peri > 0 and (peri * peri) / max(area, 1) > 80.0:
        return True
    return False


def _is_filled_region(mask_cc: np.ndarray, area: int) -> bool:
    """Heuristic: True if connected component is a solid blob (not a thin stroke)."""
    if _is_stroke_like(mask_cc, area):
        return False
    u8 = (mask_cc.astype(np.uint8)) * 255
    eroded = cv2.erode(u8, np.ones((3, 3), np.uint8), iterations=2)
    if int(np.count_nonzero(eroded)) > max(500, int(0.15 * area)):
        return True
    ys, xs = np.where(mask_cc)
    if len(xs) == 0:
        return False
    bw = int(xs.max() - xs.min() + 1)
    bh = int(ys.max() - ys.min() + 1)
    return (area / max(1, bw * bh)) > 0.55 and bw >= 40 and bh >= 40


def desolidify_ink(ink255: np.ndarray, *, page_h: int | None = None, page_w: int | None = None) -> np.ndarray:
    """Hollow large solid black fills into outlines (AD FLOOR: bake into default postprocess).

    ink255: white=255 on ink pixels (OpenCV binary convention). Small blobs (pupils,
    thin strokes) are preserved; components > ~2% of page that look filled become rings.
    Already stroke-like components are never hollowed (avoids double-outline ribbons).
    Kid stroke thickness >= max(6, min(h,w)//280).
    """
    h, w = ink255.shape[:2]
    thr_area = int(_SOLID_AREA_FRAC * h * w)
    # Prefer thicker kid stroke when hollowing true fills (was max(4, //400) → too thin/ribbony)
    thickness = max(6, min(page_h or h, page_w or w) // 280)
    n, labels, stats, _ = cv2.connectedComponentsWithStats(ink255, connectivity=8)
    out = np.zeros_like(ink255)
    hollowed = 0
    skipped_stroke = 0
    for i in range(1, n):
        area = int(stats[i, cv2.CC_STAT_AREA])
        cc = labels == i
        if area > thr_area and _is_stroke_like(cc, area):
            out[cc] = 255
            skipped_stroke += 1
            continue
        if area > thr_area and _is_filled_region(cc, area):
            cnts, _ = cv2.findContours(
                (cc.astype(np.uint8) * 255), cv2.RETR_CCOMP, cv2.CHAIN_APPROX_SIMPLE
            )
            cv2.drawContours(out, cnts, -1, 255, thickness=thickness)
            hollowed += 1
        else:
            out[cc] = 255
    if hollowed or skipped_stroke:
        logger.info(
            "desolidify: hollowed %s large solid fill(s); skipped %s stroke-like",
            hollowed,
            skipped_stroke,
        )
    return out


def fit_print_canvas(
    img: Image.Image,
    *,
    width: int = _PRINT_W,
    height: int = _PRINT_H,
    margin: int = _MARGIN_PX,
) -> Image.Image:
    """Center content on 2550×3300 with safe margin; 1-bit black-on-white; desolidify."""
    gray = np.asarray(img.convert("L"))
    if gray.shape != (height, width):
        gray = np.asarray(img.resize((width, height), Image.Resampling.LANCZOS).convert("L"))
    ink = ((gray < 160).astype(np.uint8)) * 255
    ys, xs = np.where(ink > 0)
    canvas_ink = np.zeros((height, width), np.uint8)
    if ys.size == 0:
        return Image.fromarray(np.full((height, width), 255, np.uint8)).convert("RGB")
    y0, y1 = int(ys.min()), int(ys.max())
    x0, x1 = int(xs.min()), int(xs.max())
    pad = 20
    y0, y1 = max(0, y0 - pad), min(height - 1, y1 + pad)
    x0, x1 = max(0, x0 - pad), min(width - 1, x1 + pad)
    crop = ink[y0 : y1 + 1, x0 : x1 + 1]
    ch, cw = crop.shape
    max_w, max_h = width - 2 * margin, height - 2 * margin
    target_h = int(0.75 * max_h)
    scale = min(max_w / max(cw, 1), max_h / max(ch, 1))
    if ch * scale < target_h * 0.9:
        scale = min(max_w / max(cw, 1), target_h / max(ch, 1))
    nw = max(1, int(round(cw * scale)))
    nh = max(1, int(round(ch * scale)))
    resized = cv2.resize(crop, (nw, nh), interpolation=cv2.INTER_AREA)
    resized = ((resized > 80).astype(np.uint8)) * 255
    resized = desolidify_ink(resized, page_h=height, page_w=width)
    ox, oy = (width - nw) // 2, (height - nh) // 2
    canvas_ink[oy : oy + nh, ox : ox + nw] = resized
    canvas_ink = desolidify_ink(canvas_ink, page_h=height, page_w=width)
    canvas_ink[:margin, :] = 0
    canvas_ink[-margin:, :] = 0
    canvas_ink[:, :margin] = 0
    canvas_ink[:, -margin:] = 0
    page = np.full((height, width), 255, np.uint8)
    page[canvas_ink > 0] = 0
    return Image.fromarray(page).convert("RGB")



def mid_gray_frac(img: Image.Image) -> float:
    """Fraction of pixels in mid-gray band [40, 220] (raw or processed RGB/L)."""
    gray = np.asarray(img.convert("L"))
    return float(np.mean((gray >= 40) & (gray <= 220)))


def ribbon_risk(raw_or_processed: Image.Image) -> bool:
    """True if image would have taken the legacy heavy path OR looks like thin double contours.

    Used by regen scripts to reject attempts before saving as final:
      - mid-gray frac on input > ~0.08 (legacy heavy trigger), OR
      - processed ink looks like thin parallel double-outline ribbons.
    """
    gray = np.asarray(raw_or_processed.convert("L"))
    mid = float(np.mean((gray >= 40) & (gray <= 220)))
    if mid > 0.08:
        return True
    # Binary ink (black strokes on white)
    ink = ((gray < 128).astype(np.uint8)) * 255
    ink_frac = float(np.mean(ink > 0))
    if ink_frac < 0.005:
        return False
    # Distance-transform ridge: thin parallel double contours leave two close ink walls
    # with a narrow white channel. Count ink pixels that have a nearby parallel twin.
    inv = 255 - ink
    # Erode once: true solid thick strokes keep core; hollow ribbons vanish fast.
    eroded = cv2.erode(ink, np.ones((3, 3), np.uint8), iterations=2)
    rem = float(np.count_nonzero(eroded)) / max(1, int(np.count_nonzero(ink)))
    if rem < 0.15 and ink_frac > 0.02:
        # Most ink vanished after 2 erosions → thin/hollow strokes (ribbon-like)
        # Confirm with hole/ring density via morphology gradient
        grad = cv2.morphologyEx(ink, cv2.MORPH_GRADIENT, np.ones((3, 3), np.uint8))
        grad_frac = float(np.mean(grad > 0))
        if grad_frac > 0.6 * ink_frac:
            return True
    # Parallel double-contour: closing thin gaps between twin strokes floods a lot
    closed = cv2.morphologyEx(ink, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8), iterations=1)
    gained = float(np.count_nonzero((closed > 0) & (ink == 0))) / max(1, gray.size)
    if gained > 0.015 and rem < 0.25:
        return True
    return False


def postprocess_line_art(img: Image.Image) -> Image.Image:
    """
    Gentle B&W cleanup for already-clean FLUX / line-art outputs.

    Thresholds near-black strokes to pure black on pure white, whites out border
    (and Pollinations watermark corner), and drops tiny speckles. Always uses the
    gentle threshold path — never falls back to postprocess_line_art_heavy
    (legacy/opt-in only; mid-gray heavy path caused hollow ribbon strokes).
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

    mid_frac = float(np.mean((gray >= 40) & (gray <= 220)))
    if mid_frac > 0.08:
        # Do NOT call heavy — ribbon risk. Callers should reject/regen instead.
        logger.warning(
            "Gentle postprocess: mid-gray %.1f%% — staying on gentle path (heavy disabled)",
            mid_frac * 100,
        )

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
    # AD FLOOR: desolidify + print canvas fit (stops solid_fills CF burn)
    return fit_print_canvas(Image.fromarray(result).convert("RGB"), width=w, height=h)


def postprocess_line_art_heavy(img: Image.Image) -> Image.Image:
    """
    LEGACY / OPT-IN ONLY heavy OpenCV outline extractor. Not called by default postprocess.
    Prefer postprocess_line_art() (gentle-only). Mid-gray auto-fallback was removed — it
    produced hollow double-outline ribbons.

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
    return fit_print_canvas(Image.fromarray(result).convert("RGB"), width=w, height=h)


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
