"""Dry-run placeholder line drawings (no network)."""

from __future__ import annotations

import math
from pathlib import Path

from PIL import Image, ImageDraw


def _center(w: int, h: int) -> tuple[int, int]:
    return w // 2, h // 2


def draw_placeholder(
    subject: str,
    width: int,
    height: int,
    page_index: int = 0,
) -> Image.Image:
    """
    Create a simple black-outline / white-background line drawing.
    Shape varies by page_index so pages look different without AI.
    """
    img = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(img)
    cx, cy = _center(width, height)
    # Keep art inset from edges (visual margin)
    pad = min(width, height) // 10
    style = page_index % 8
    stroke = max(4, min(width, height) // 80)

    def oval(bbox, width=stroke):
        draw.ellipse(bbox, outline="black", width=width)

    def poly(pts, width=stroke):
        draw.line(pts + [pts[0]], fill="black", width=width)

    if style == 0:
        # Sun-like circle with rays
        r = min(width, height) // 5
        oval((cx - r, cy - r, cx + r, cy + r))
        for i in range(8):
            ang = i * math.pi / 4
            x0 = cx + int((r + 20) * math.cos(ang))
            y0 = cy + int((r + 20) * math.sin(ang))
            x1 = cx + int((r + 80) * math.cos(ang))
            y1 = cy + int((r + 80) * math.sin(ang))
            draw.line([(x0, y0), (x1, y1)], fill="black", width=stroke)
    elif style == 1:
        # House
        body = [cx - 120, cy - 20, cx + 120, cy + 140]
        draw.rectangle(body, outline="black", width=stroke)
        roof = [(cx - 150, cy - 20), (cx, cy - 160), (cx + 150, cy - 20)]
        poly(roof)
        door = [cx - 30, cy + 40, cx + 30, cy + 140]
        draw.rectangle(door, outline="black", width=stroke)
    elif style == 2:
        # Star
        pts = []
        outer, inner = 140, 60
        for i in range(10):
            ang = -math.pi / 2 + i * math.pi / 5
            r = outer if i % 2 == 0 else inner
            pts.append((cx + int(r * math.cos(ang)), cy + int(r * math.sin(ang))))
        poly(pts)
    elif style == 3:
        # Simple fish
        oval((cx - 140, cy - 60, cx + 80, cy + 60))
        tail = [(cx + 80, cy), (cx + 160, cy - 70), (cx + 160, cy + 70)]
        poly(tail)
        oval((cx - 80, cy - 20, cx - 50, cy + 10))  # eye
    elif style == 4:
        # Balloon + string
        oval((cx - 70, cy - 160, cx + 70, cy))
        draw.line([(cx, cy), (cx, cy + 180)], fill="black", width=stroke)
        poly([(cx - 20, cy), (cx, cy + 20), (cx + 20, cy)])
    elif style == 5:
        # Tree
        trunk = [cx - 25, cy, cx + 25, cy + 180]
        draw.rectangle(trunk, outline="black", width=stroke)
        oval((cx - 120, cy - 160, cx + 120, cy + 40))
    elif style == 6:
        # Car
        body = [cx - 160, cy - 40, cx + 160, cy + 40]
        draw.rectangle(body, outline="black", width=stroke)
        cabin = [cx - 80, cy - 100, cx + 60, cy - 40]
        draw.rectangle(cabin, outline="black", width=stroke)
        oval((cx - 100, cy + 30, cx - 40, cy + 90))
        oval((cx + 40, cy + 30, cx + 100, cy + 90))
    else:
        # Flower
        oval((cx - 30, cy - 30, cx + 30, cy + 30))
        for i in range(6):
            ang = i * math.pi / 3
            px = cx + int(90 * math.cos(ang))
            py = cy + int(90 * math.sin(ang))
            oval((px - 35, py - 35, px + 35, py + 35))
        draw.line([(cx, cy + 30), (cx, cy + 200)], fill="black", width=stroke)

    # Outer safety frame (light)
    draw.rectangle(
        [pad // 2, pad // 2, width - pad // 2, height - pad // 2],
        outline="#cccccc",
        width=1,
    )

    # Caption note (tiny, outside main art) — keep minimal for coloring
    # Subject hint as small text at bottom for dry-run identification
    try:
        draw.text((pad, height - pad), f"{page_index + 1}. {subject[:50]}", fill="#888888")
    except Exception:
        pass

    return img


def save_placeholder(
    path: Path,
    subject: str,
    width: int,
    height: int,
    page_index: int = 0,
) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    img = draw_placeholder(subject, width, height, page_index)
    img.save(path, format="PNG")
    return path
