# core/games/sobship_render.py
"""
!sobship — a fun love-meter (no sobs involved). Renders an animated GIF of a
heart filling up to a deterministic compatibility score for a pair of people.

Deterministic: the same two users always get the same score (order-independent),
so it's a repeatable bit of fun, not random each call.
"""
from __future__ import annotations

import hashlib
import io
import math

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

W, H = 720, 420


def ship_score(a_id: int, b_id: int) -> int:
    """Deterministic 0-100 score for a pair, independent of order."""
    lo, hi = sorted((int(a_id), int(b_id)))
    h = hashlib.sha256(f"{lo}:{hi}:sobship".encode()).hexdigest()
    return int(h[:8], 16) % 101


def _verdict(score: int) -> tuple[str, tuple]:
    if score >= 90:   return "Soulmates", (235, 84, 110)
    if score >= 75:   return "A perfect match!", (240, 120, 150)
    if score >= 60:   return "Strong sparks", (240, 150, 90)
    if score >= 45:   return "There's potential", (240, 177, 50)
    if score >= 30:   return "Just friends", (130, 180, 230)
    if score >= 15:   return "It's complicated", (150, 147, 165)
    return "Better as strangers", (120, 120, 135)


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
    d.text((W // 2 - _text_w(d, title, f_title(40)) // 2, 26), title, font=f_title(40), fill=INK)

    # the two names
    na = clean_name(name_a) or "someone"
    nb = clean_name(name_b) or "someone"
    pair = f"{na}  ×  {nb}"
    pf = f_reg(24)
    # ellipsize the pair to fit
    while _text_w(d, pair, pf) > W - 80 and (len(na) > 6 or len(nb) > 6):
        if len(na) >= len(nb):
            na = na[:-1]
        else:
            nb = nb[:-1]
        pair = f"{na}…  ×  {nb}…"
    d.text((W // 2 - _text_w(d, pair, pf) // 2, 78), pair, font=pf, fill=DIM)

    # big heart that fills bottom-up
    cx, cy, size = W // 2, 215, 150
    pts = _heart_points(cx, cy, size)
    # outline heart (empty)
    d.polygon(pts, outline=HEART_SOFT, width=3)
    # filled portion: clip a filled heart to a rising rectangle
    ys = [p[1] for p in pts]
    top, bot = min(ys), max(ys)
    fill_line = bot - (bot - top) * (fill_pct / 100.0)
    heart_mask = Image.new("L", (W, H), 0)
    ImageDraw.Draw(heart_mask).polygon(pts, fill=255)
    fill_layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    fd = ImageDraw.Draw(fill_layer)
    fd.rectangle([0, fill_line, W, bot + 5], fill=HEART + (255,))
    # keep only the part of the rectangle inside the heart
    fill_layer.putalpha(Image.composite(fill_layer.getchannel("A"), Image.new("L", (W, H), 0), heart_mask))
    img.alpha_composite(fill_layer)
    # heart outline on top so it stays crisp
    d.polygon(pts, outline=HEART, width=3)

    # percentage in the heart
    pct_txt = f"{int(fill_pct)}%"
    d.text((cx - _text_w(d, pct_txt, f_num(46)) // 2, cy - 28), pct_txt, font=f_num(46),
           fill=(255, 255, 255))

    # verdict (only once filled)
    if show_score:
        verdict, vcol = _verdict(final_score)
        vt = f_label(22)
        d.rounded_rectangle([W // 2 - 200, 350, W // 2 + 200, 396], radius=18, fill=PANEL)
        d.text((W // 2 - _text_w(d, verdict, vt) // 2, 360), verdict, font=vt, fill=vcol)

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
