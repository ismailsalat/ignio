# core/profile/eco_render.py
"""Economy health card image — no emoji (so no placeholder boxes), real graph."""
from __future__ import annotations

from PIL import Image, ImageDraw
from core.profile.render import f_title, f_label, f_num, f_reg, _round_mask, _text_w, _fmt

AMBER = (240, 177, 50)
GREEN = (80, 200, 120)
YELLOW = (240, 190, 70)
RED = (230, 80, 80)
GREY = (150, 147, 165)
INK = (240, 238, 245)
DIM = (150, 147, 165)
PANEL = (40, 37, 50)
BG = (24, 22, 30)

STATUS_COLOR = {"green": GREEN, "yellow": YELLOW, "red": RED, "new": GREY}
STATUS_WORD = {"green": "STABLE", "yellow": "WATCH", "red": "INFLATION RISK", "new": "NEW SERVER"}


def make_economy_card(data: dict) -> Image.Image:
    """
    data:
      guild_name, total, players, current_rate, recommended_rate,
      status (green|yellow|red|new), pct (float), points (list[int]),
      advice (str or None)
    """
    W, H, R = 1040, 560, 32
    img = Image.new("RGBA", (W, H), BG + (255,))
    d = ImageDraw.Draw(img)
    PAD = 40

    status = data.get("status", "new")
    scol = STATUS_COLOR.get(status, GREY)

    # title
    d.text((PAD, 30), "Server Economy", font=f_title(40), fill=INK)
    sub = f"{data.get('guild_name','')}  -  economic health"
    d.text((PAD, 80), sub, font=f_reg(22), fill=DIM)

    # status pill (top-right) — word, not emoji
    word = STATUS_WORD.get(status, "")
    pf = f_label(20)
    pw = _text_w(d, word, pf) + 44
    d.rounded_rectangle([W - PAD - pw, 36, W - PAD, 84], radius=24, fill=scol)
    d.text((W - PAD - pw + 22, 50), word, font=pf, fill=(20, 18, 16))

    # stat row
    stats = [
        ("Total sobs", _fmt(data.get("total", 0))),
        ("Players", _fmt(data.get("players", 0))),
        ("Sob multiplier", f"{data.get('multiplier', 1):g}x"),
        ("Total burned", _fmt(data.get("burned", 0))),
    ]
    cw = (W - PAD * 2 - 30) / 4
    for i, (k, v) in enumerate(stats):
        x = PAD + i * (cw + 10)
        d.rounded_rectangle([x, 120, x + cw, 200], radius=16, fill=PANEL)
        d.text((x + 16, 134), k, font=f_label(14), fill=DIM)
        d.text((x + 16, 156), v, font=f_num(24), fill=INK)

    # graph panel
    gx, gy, gw, gh = PAD, 230, W - PAD * 2, 200
    d.rounded_rectangle([gx, gy, gx + gw, gy + gh], radius=18, fill=PANEL)
    d.text((gx + 20, gy + 14), "SUPPLY TREND", font=f_label(16), fill=DIM)

    points = data.get("points", []) or []
    if len(points) >= 2:
        pmin, pmax = min(points), max(points)
        rng = (pmax - pmin) or 1
        plot = []
        innerx, innery = gx + 30, gy + 50
        innerw, innerh = gw - 60, gh - 80
        for i, p in enumerate(points):
            px = innerx + i * innerw / (len(points) - 1)
            py = innery + innerh - ((p - pmin) / rng) * innerh
            plot.append((px, py))
        # area under line
        line_col = STATUS_COLOR.get(status, AMBER)
        for i in range(len(plot) - 1):
            d.line([plot[i], plot[i + 1]], fill=line_col, width=4)
        for p in plot:
            d.ellipse([p[0] - 3, p[1] - 3, p[0] + 3, p[1] + 3], fill=line_col)
        # pct label
        if status != "new":
            pct = data.get("pct", 0.0)
            lbl = f"{pct:+.0f}%"
            d.text((gx + gw - _text_w(d, lbl, f_label(18)) - 20, gy + gh - 26),
                   lbl, font=f_label(18), fill=line_col)
    else:
        # not enough points yet — clear message, no broken graph
        msg = "Collecting data — the trend line appears after a few snapshots."
        d.text((gx + 30, gy + gh / 2 - 10), msg, font=f_reg(18), fill=DIM)

    # advice strip
    advice = data.get("advice")
    ay = 450
    if advice:
        d.rounded_rectangle([PAD, ay, W - PAD, ay + 80], radius=16, fill=(50, 40, 40))
        d.text((PAD + 20, ay + 14), "What to do", font=f_label(16), fill=scol)
        d.text((PAD + 20, ay + 40), advice, font=f_reg(17), fill=INK)
    else:
        d.rounded_rectangle([PAD, ay, W - PAD, ay + 80], radius=16, fill=PANEL)
        d.text((PAD + 20, ay + 28), "Economy looks healthy. Keep an eye on big event payouts.",
               font=f_reg(18), fill=DIM)

    img.putalpha(_round_mask((W, H), R))
    return img
