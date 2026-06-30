# core/games/sobship_render.py
"""
!sobship — a fun love-meter (no sobs involved). Renders an animated GIF of a
heart filling up to a random compatibility score for a pair of people.

The score is rolled fresh on every call, so the same two people can get a
different result each time — it's pure fun, never touches anyone's balance.
"""
from __future__ import annotations

import io
import math
import secrets

from PIL import Image, ImageDraw
from core.profile.render import f_title, f_label, f_num, f_reg, _round_mask, _text_w, clean_name

BG = (26, 24, 32)
INK = (240, 238, 245)
DIM = (150, 147, 165)
PANEL = (44, 40, 54)
TRACK = (58, 54, 70)
HEART = (235, 84, 110)
HEART_SOFT = (245, 140, 165)
GOLD = (240, 177, 50)

W, H = 720, 490


def ship_score(a_id: int = 0, b_id: int = 0) -> int:
    """A fresh random 0-100 love score every time it's called. (IDs are accepted
    for signature compatibility but no longer make it deterministic.)"""
    return secrets.randbelow(101)


def _verdict(score: int):
    """Returns (verdict, color, flavor) for a score."""
    if score >= 90:   return "Soulmates", (235, 84, 110), "the stars aligned for this one"
    if score >= 75:   return "A perfect match!", (240, 120, 150), "someone get the wedding planner"
    if score >= 60:   return "Strong sparks", (240, 150, 90), "there's definitely something here"
    if score >= 45:   return "There's potential", (240, 177, 50), "could go either way... exciting"
    if score >= 30:   return "Just friends", (130, 180, 230), "the friendzone is cozy, tbf"
    if score >= 15:   return "It's complicated", (150, 147, 165), "it's giving... chaos"
    return "Better as strangers", (120, 120, 135), "maybe just wave from afar"


def _heart_points(cx, cy, size):
    """Return a polygon approximating a heart centered at (cx, cy)."""
    pts = []
    for i in range(0, 360, 6):
        t = math.radians(i)
        x = 16 * math.sin(t) ** 3
        y = -(13 * math.cos(t) - 5 * math.cos(2 * t) - 2 * math.cos(3 * t) - math.cos(4 * t))
        pts.append((cx + x * size / 16.0, cy + y * size / 16.0))
    return pts


def _frame(name_a, name_b, fill_pct, final_score, show_score):
    img = Image.new("RGBA", (W, H), BG + (255,))
    d = ImageDraw.Draw(img)

    # title
    title = "Sob-Ship"
    d.text((W // 2 - _text_w(d, title, f_title(40)) // 2, 24), title, font=f_title(40), fill=INK)

    # --- two name chips, side by side, with a heart-divider between them ---
    # Each name lives in its own rounded chip so long names never collide with
    # the heart or each other. Names are truncated to the chip width.
    na = clean_name(name_a) or "someone"
    nb = clean_name(name_b) or "someone"

    def _truncate(draw, text, font, max_w):
        if _text_w(draw, text, font) <= max_w:
            return text
        ell = "…"
        while text and _text_w(draw, text + ell, font) > max_w:
            text = text[:-1]
        return (text + ell) if text else ell

    chip_y, chip_h = 84, 46
    gap = 54                      # space in the middle for the × divider
    chip_w = (W - 2 * 40 - gap) // 2
    pad_in = 16
    # pick a font size that fits the longer name into a chip
    name_font = f_reg(22)
    for size in (22, 20, 18, 17):
        name_font = f_reg(size)
        if (_text_w(d, na, name_font) <= chip_w - 2 * pad_in or len(na) <= 4) and \
           (_text_w(d, nb, name_font) <= chip_w - 2 * pad_in or len(nb) <= 4):
            break
    na_fit = _truncate(d, na, name_font, chip_w - 2 * pad_in)
    nb_fit = _truncate(d, nb, name_font, chip_w - 2 * pad_in)

    lx = 40
    rx = W - 40 - chip_w
    for cx0, txt in ((lx, na_fit), (rx, nb_fit)):
        d.rounded_rectangle([cx0, chip_y, cx0 + chip_w, chip_y + chip_h], radius=14, fill=PANEL)
        tw = _text_w(d, txt, name_font)
        ty = chip_y + (chip_h - name_font.size) // 2 - 2
        d.text((cx0 + (chip_w - tw) // 2, ty), txt, font=name_font, fill=INK)
    # small heart divider between the chips
    div = _heart_points(W // 2, chip_y + chip_h // 2, 18)
    d.polygon(div, fill=HEART)

    # big heart that fills bottom-up — lowered so it never touches the chips
    cx, cy, size = W // 2, 290, 135
    pts = _heart_points(cx, cy, size)
    d.polygon(pts, outline=HEART_SOFT, width=3)
    ys = [p[1] for p in pts]
    top, bot = min(ys), max(ys)
    fill_line = bot - (bot - top) * (fill_pct / 100.0)
    heart_mask = Image.new("L", (W, H), 0)
    ImageDraw.Draw(heart_mask).polygon(pts, fill=255)
    fill_layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    fd = ImageDraw.Draw(fill_layer)
    fd.rectangle([0, fill_line, W, bot + 5], fill=HEART + (255,))
    fill_layer.putalpha(Image.composite(fill_layer.getchannel("A"), Image.new("L", (W, H), 0), heart_mask))
    img.alpha_composite(fill_layer)
    d.polygon(pts, outline=HEART, width=3)

    # percentage in the heart
    pct_txt = f"{int(fill_pct)}%"
    d.text((cx - _text_w(d, pct_txt, f_num(46)) // 2, cy - 28), pct_txt, font=f_num(46),
           fill=(255, 255, 255))

    # verdict (only once filled) — pill + a little flavor line beneath it
    if show_score:
        verdict, vcol, flavor = _verdict(final_score)
        vt = f_label(22)
        vw = _text_w(d, verdict, vt)
        bw = max(220, vw + 60)
        d.rounded_rectangle([W // 2 - bw // 2, 408, W // 2 + bw // 2, 450], radius=18, fill=PANEL)
        d.text((W // 2 - vw // 2, 418), verdict, font=vt, fill=vcol)
        ff = f_reg(16)
        fw = _text_w(d, flavor, ff)
        d.text((W // 2 - fw // 2, 458), flavor, font=ff, fill=DIM)

    img.putalpha(_round_mask((W, H), 28))
    return img


def make_sobship_gif(name_a: str, name_b: str, a_id: int, b_id: int) -> io.BytesIO:
    """Build an animated GIF of the meter filling to the pair's score."""
    score = ship_score(a_id, b_id)
    frames = []
    # ease-out fill from 0 to score
    steps = 22
    for i in range(steps + 1):
        t = i / steps
        eased = 1 - (1 - t) ** 3
        cur = eased * score
        frames.append(_frame(name_a, name_b, cur, score, show_score=False).convert("P", palette=Image.ADAPTIVE))
    # hold the final frame with the verdict
    final = _frame(name_a, name_b, score, score, show_score=True).convert("P", palette=Image.ADAPTIVE)
    for _ in range(18):
        frames.append(final)

    buf = io.BytesIO()
    durations = [40] * (steps + 1) + [70] * 18
    frames[0].save(buf, format="GIF", save_all=True, append_images=frames[1:],
                   duration=durations, loop=0, disposal=2, optimize=True)
    buf.seek(0)
    return buf, score


def make_sobship_static(name_a: str, name_b: str, a_id: int, b_id: int):
    """A single still frame (fallback if GIF isn't wanted)."""
    score = ship_score(a_id, b_id)
    return _frame(name_a, name_b, score, score, show_score=True), score
