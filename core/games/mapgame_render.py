# core/games/mapgame_render.py
"""Render the !mapgame board: the world map with a marker + arrow on the target
country, drawn cleanly with a title bar. Pure PIL (no runtime map libraries)."""
from __future__ import annotations

import io
import os

from PIL import Image, ImageDraw
from core.profile.render import f_title, f_label, f_reg, _round_mask, _text_w

HERE = os.path.dirname(os.path.abspath(__file__))
MAP_PATH = os.path.join(HERE, "assets", "worldmap.png")

INK = (245, 243, 250)
DIM = (90, 110, 120)
MARK = (228, 70, 70)
MARK_GLOW = (228, 70, 70, 60)
PANEL = (250, 249, 240)

PAD = 24
BAR_H = 70


def _load_map():
    return Image.open(MAP_PATH).convert("RGBA")


def render_board(country_x: float, country_y: float, round_no: int = 1,
                 total: int = 5, prompt: str = "Which country is the arrow pointing to?") -> io.BytesIO:
    base = _load_map()
    mw, mh = base.size

    W = mw + 2 * PAD
    H = mh + 2 * PAD + BAR_H
    card = Image.new("RGBA", (W, H), (26, 24, 32, 255))
    d = ImageDraw.Draw(card)

    # title bar
    d.text((PAD, 18), "Map Game", font=f_title(34), fill=INK)
    rtxt = f"Round {round_no}/{total}"
    d.text((W - PAD - _text_w(d, rtxt, f_label(20)), 30), rtxt, font=f_label(20), fill=(240, 177, 50))

    # paste the map
    mx, my = PAD, PAD + BAR_H
    card.alpha_composite(base, (mx, my))

    # marker on the country (translate to card coords)
    cx, cy = mx + country_x, my + country_y

    # soft glow ring
    glow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow)
    for r, a in ((30, 40), (22, 70), (15, 120)):
        gd.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(228, 70, 70, a))
    card.alpha_composite(glow)

    # crisp target ring
    d.ellipse([cx - 13, cy - 13, cx + 13, cy + 13], outline=MARK, width=4)
    d.ellipse([cx - 3, cy - 3, cx + 3, cy + 3], fill=MARK)

    # arrow coming from the open ocean toward the marker (pick a clear direction)
    # default from upper-left; if near the left edge, come from upper-right.
    from_left = cx > mw * 0.30 + mx
    ax = cx - 64 if from_left else cx + 64
    ay = cy - 64
    tipx = cx - 16 if from_left else cx + 16
    tipy = cy - 16
    d.line([(ax, ay), (tipx, tipy)], fill=MARK, width=5)
    # arrowhead
    if from_left:
        d.polygon([(tipx, tipy), (tipx - 16, tipy - 2), (tipx - 2, tipy - 16)], fill=MARK)
    else:
        d.polygon([(tipx, tipy), (tipx + 16, tipy - 2), (tipx + 2, tipy - 16)], fill=MARK)

    # prompt under the map
    d.text((PAD, H - 0), "", font=f_reg(18), fill=DIM)  # noop keeps layout stable

    card.putalpha(_round_mask((W, H), 24))
    buf = io.BytesIO()
    card.convert("RGB").save(buf, format="PNG")
    buf.seek(0)
    return buf
