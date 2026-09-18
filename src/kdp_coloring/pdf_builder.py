"""Build print-ready interior and full-wrap cover PDFs with reportlab."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Sequence

from PIL import Image as PILImage
from reportlab.lib.colors import HexColor, black, white
from reportlab.lib.units import inch
from reportlab.pdfgen import canvas

from .config import PT_PER_IN, cover_size_inches, load_config, spine_width_inches


def build_interior_pdf(
    image_paths: Sequence[Path],
    out_path: Path,
    cfg: dict[str, Any] | None = None,
) -> Path:
    """
    One coloring page per PDF page at 8.5\" × 11\".
    Images are centered within safe margins.
    """
    c = cfg or load_config()
    page_w = float(c["page_width_pt"])
    page_h = float(c["page_height_pt"])
    margin = float(c["margin_pt"])
    usable_w = page_w - 2 * margin
    usable_h = page_h - 2 * margin

    out_path.parent.mkdir(parents=True, exist_ok=True)
    cv = canvas.Canvas(str(out_path), pagesize=(page_w, page_h))

    for img_path in image_paths:
        # Fit image into usable box preserving aspect ratio
        with PILImage.open(img_path) as im:
            iw, ih = im.size
        scale = min(usable_w / iw, usable_h / ih)
        draw_w = iw * scale
        draw_h = ih * scale
        x = (page_w - draw_w) / 2
        y = (page_h - draw_h) / 2
        cv.setFillColor(white)
        cv.rect(0, 0, page_w, page_h, fill=1, stroke=0)
        cv.drawImage(
            str(img_path),
            x,
            y,
            width=draw_w,
            height=draw_h,
            preserveAspectRatio=True,
            anchor="c",
            mask="auto",
        )
        cv.showPage()

    cv.save()
    return out_path


def build_cover_pdf(
    *,
    title: str,
    author: str,
    theme_display: str,
    page_count: int,
    out_path: Path,
    front_image: Path | None = None,
    blurb: str | None = None,
    cfg: dict[str, Any] | None = None,
) -> Path:
    """
    Full-wrap cover PDF: back | spine | front, with bleed.

    Spine formula (KDP B&W):
      white paper: page_count * 0.002252 inches
      cream paper: page_count * 0.0025 inches
    Confirm with Amazon KDP Cover Calculator before uploading.
    """
    c = cfg or load_config()
    total_w_in, total_h_in, spine_in = cover_size_inches(page_count, c)
    bleed = float(c["bleed_in"])
    pw = float(c["page_width_in"])
    ph = float(c["page_height_in"])

    total_w = total_w_in * PT_PER_IN
    total_h = total_h_in * PT_PER_IN
    spine_pt = spine_in * PT_PER_IN
    bleed_pt = bleed * PT_PER_IN
    panel_w = pw * PT_PER_IN
    panel_h = ph * PT_PER_IN

    # Panel origins (from left)
    # [bleed][back][spine][front][bleed]
    back_x = bleed_pt
    spine_x = bleed_pt + panel_w
    front_x = bleed_pt + panel_w + spine_pt
    content_y = bleed_pt  # bottom of trim area

    out_path.parent.mkdir(parents=True, exist_ok=True)
    cv = canvas.Canvas(str(out_path), pagesize=(total_w, total_h))

    # Background
    cv.setFillColor(HexColor("#FFF8F0"))
    cv.rect(0, 0, total_w, total_h, fill=1, stroke=0)

    # --- BACK COVER ---
    back_blurb = blurb or (
        f"A fun coloring book for kids ages 3–7!\n\n"
        f"Theme: {theme_display}\n"
        f"{page_count} adorable pages to color.\n\n"
        f"Simple bold outlines · Perfect for little hands\n\n"
        f"[Blurb placeholder — replace before publishing]\n\n"
        f"© {author}"
    )
    cv.setFillColor(black)
    cv.setFont("Helvetica-Bold", 16)
    cv.drawString(back_x + 36, content_y + panel_h - 60, "About this book")
    cv.setFont("Helvetica", 11)
    text = cv.beginText(back_x + 36, content_y + panel_h - 90)
    text.setLeading(16)
    for line in back_blurb.split("\n"):
        text.textLine(line)
    cv.drawText(text)

    # Placeholder barcode area (KDP adds barcode)
    bar_w, bar_h = 2 * inch, 1.2 * inch
    bar_x = back_x + panel_w - bar_w - 36
    bar_y = content_y + 36
    cv.setStrokeColor(HexColor("#AAAAAA"))
    cv.setDash(3, 3)
    cv.rect(bar_x, bar_y, bar_w, bar_h, fill=0, stroke=1)
    cv.setDash()
    cv.setFont("Helvetica", 8)
    cv.setFillColor(HexColor("#888888"))
    cv.drawCentredString(bar_x + bar_w / 2, bar_y + bar_h / 2 - 4, "KDP barcode area")

    # --- SPINE ---
    if spine_pt >= 12:
        cv.saveState()
        cv.setFillColor(black)
        # Rotate text for spine
        spine_cx = spine_x + spine_pt / 2
        spine_cy = content_y + panel_h / 2
        cv.translate(spine_cx, spine_cy)
        cv.rotate(90)
        font_size = 10 if spine_pt < 24 else 12
        cv.setFont("Helvetica-Bold", font_size)
        spine_title = title if len(title) < 40 else title[:37] + "…"
        cv.drawCentredString(0, -font_size / 3, spine_title)
        cv.restoreState()

    # --- FRONT COVER ---
    cv.setFillColor(black)
    # Title area
    title_y = content_y + panel_h - 80
    cv.setFont("Helvetica-Bold", 22)
    # Wrap title
    max_title_width = panel_w - 72
    words = title.split()
    lines: list[str] = []
    current = ""
    for w in words:
        trial = f"{current} {w}".strip()
        if cv.stringWidth(trial, "Helvetica-Bold", 22) <= max_title_width:
            current = trial
        else:
            if current:
                lines.append(current)
            current = w
    if current:
        lines.append(current)
    ty = title_y
    for line in lines[:4]:
        cv.drawCentredString(front_x + panel_w / 2, ty, line)
        ty -= 28

    cv.setFont("Helvetica", 12)
    cv.drawCentredString(front_x + panel_w / 2, ty - 10, f"Ages 3–7 · {theme_display}")

    # Front art
    art_top = ty - 40
    art_bottom = content_y + 100
    art_h = max(art_top - art_bottom, 100)
    art_w = panel_w - 100
    art_x = front_x + (panel_w - art_w) / 2
    art_y = art_bottom

    if front_image and Path(front_image).is_file():
        with PILImage.open(front_image) as im:
            iw, ih = im.size
        scale = min(art_w / iw, art_h / ih)
        dw, dh = iw * scale, ih * scale
        ax = front_x + (panel_w - dw) / 2
        ay = art_bottom + (art_h - dh) / 2
        cv.drawImage(
            str(front_image),
            ax,
            ay,
            width=dw,
            height=dh,
            preserveAspectRatio=True,
            mask="auto",
        )
    else:
        cv.setStrokeColor(black)
        cv.setLineWidth(2)
        cv.rect(art_x, art_y, art_w, art_h, fill=0, stroke=1)
        cv.setFont("Helvetica", 14)
        cv.drawCentredString(front_x + panel_w / 2, art_y + art_h / 2, theme_display)

    # Author
    cv.setFillColor(black)
    cv.setFont("Helvetica-Oblique", 14)
    cv.drawCentredString(front_x + panel_w / 2, content_y + 50, author)

    # Subtle trim guides (non-printing intent — light gray for designer reference)
    cv.setStrokeColor(HexColor("#DDDDDD"))
    cv.setLineWidth(0.5)
    # Vertical panel guides
    cv.line(back_x, bleed_pt, back_x, total_h - bleed_pt)
    cv.line(spine_x, bleed_pt, spine_x, total_h - bleed_pt)
    cv.line(front_x, bleed_pt, front_x, total_h - bleed_pt)
    cv.line(front_x + panel_w, bleed_pt, front_x + panel_w, total_h - bleed_pt)

    cv.showPage()
    cv.save()
    return out_path


def document_spine_formula(cfg: dict[str, Any] | None = None) -> str:
    c = cfg or load_config()
    return (
        "KDP B&W paperback spine (inches) ≈ page_count × factor\n"
        f"  white paper factor: {c['spine_factor_white']}\n"
        f"  cream paper factor: {c['spine_factor_cream']}\n"
        f"  active ({c['paper']}): {c['spine_factor']}\n"
        "Always confirm with the Amazon KDP Cover Calculator before upload."
    )
