# core/profile/help_render.py
"""Clean help overview image (no messy emoji inside the picture)."""
from __future__ import annotations

from PIL import Image, ImageDraw
from core.profile.render import f_title, f_label, f_num, f_reg, _round_mask, _text_w

AMBER = (240, 177, 50)
INK = (240, 238, 245)
DIM = (155, 152, 170)
PANEL = (40, 37, 50)
BG = (24, 22, 30)
ACCENT_SOFT = (255, 205, 110)


def make_help_overview(categories: list[dict]) -> Image.Image:
    """
    categories: list of {label, desc, count} (already filtered for the viewer)
    Drawn as a clean grid of category tiles. No emoji inside (avoids tofu boxes).
    """
    W = 1040
    cols = 2
    rows = (len(categories) + cols - 1) // cols
    tile_h = 96
    top = 150
    H = top + rows * (tile_h + 16) + 40

    img = Image.new("RGBA", (W, H), BG + (255,))
    d = ImageDraw.Draw(img)
    PAD = 40

    # header
    d.text((PAD, 34), "Ignio — Help", font=f_title(44), fill=INK)
    d.text((PAD, 88), "Tap a button below to explore each area.", font=f_reg(22), fill=DIM)
    # little accent bar
    d.rounded_rectangle([PAD, 130, PAD + 90, 136], radius=3, fill=AMBER)

    tile_w = (W - PAD * 2 - 20) // cols
    for i, c in enumerate(categories):
        r, col = divmod(i, cols)
        x = PAD + col * (tile_w + 20)
        y = top + r * (tile_h + 16)
        d.rounded_rectangle([x, y, x + tile_w, y + tile_h], radius=18, fill=PANEL)
        # accent dot
        d.ellipse([x + 22, y + 28, x + 38, y + 44], fill=AMBER)
        d.text((x + 54, y + 20), c["label"], font=f_title(26), fill=INK)
        d.text((x + 54, y + 54), c["desc"], font=f_reg(17), fill=DIM)
        # count chip
        cnt = f"{c['count']}"
        cf = f_num(22)
        cw = _text_w(d, cnt, cf)
        d.text((x + tile_w - cw - 24, y + 34), cnt, font=cf, fill=ACCENT_SOFT)

    img.putalpha(_round_mask((W, H), 32))
    return img
