# core/profile/lb_render.py
"""Leaderboard card: top-10 all-time sobs, plus the summary leaders."""
from __future__ import annotations

import os
from PIL import Image, ImageDraw, ImageFilter

from core.profile.render import (
    _diag_gradient, _round_mask, _text_w, _fmt, _cover,
    f_title, f_label, f_num, f_reg, WALLPAPERS, DEFAULT_ACCENT, THEMES,
    INK, INK_DIM, INK_FAINT, BG_A, BG_B, CARD_EDGE, PANEL, TRACK,
)


def _resolve_accent(theme):
    accent = THEMES.get((theme or "amber").lower(), DEFAULT_ACCENT)
    soft = tuple(min(255, int(c + (255 - c) * 0.35)) for c in accent)
    return accent, soft


def make_leaderboard_card(data: dict, wallpaper: str | None = None, theme: str = "amber") -> Image.Image:
    """
    data keys:
      guild_name (str)
      top (list of dicts: {name, sobs} in rank order, up to 10)
      daily, weekly, giver, snitch  (each: {name, count} or None)
    """
    W, H, R = 1040, 760, 40
    ACCENT, ACCENT_SOFT = _resolve_accent(theme)

    # background
    card = None
    if wallpaper:
        want = wallpaper.lower()
        if os.path.isdir(WALLPAPERS):
            for f in os.listdir(WALLPAPERS):
                n, ext = os.path.splitext(f)
                if n.lower() == want and ext.lower() in (".png", ".jpg", ".jpeg", ".webp"):
                    card = _cover(Image.open(os.path.join(WALLPAPERS, f)).convert("RGB"), (W, H)).convert("RGBA")
                    break
    if card is None:
        card = _diag_gradient((W, H), BG_A, BG_B).convert("RGBA")
    else:
        card = Image.alpha_composite(card, Image.new("RGBA", (W, H), (12, 11, 16, 150)))

    d = ImageDraw.Draw(card)
    PAD = 44

    # title
    d.text((PAD, 34), "Sob Leaderboard", font=f_title(46), fill=INK)
    gname = data.get("guild_name", "")
    if gname:
        d.text((PAD, 90), gname, font=f_reg(24), fill=INK_DIM)

    # top-10 list
    top = data.get("top", [])[:10]
    y = 140
    row_h = 46
    medal = {0: (255, 200, 60), 1: (200, 205, 215), 2: (205, 150, 95)}  # gold/silver/bronze
    for i, entry in enumerate(top):
        ry = y + i * row_h
        # rank chip
        rank_col = medal.get(i, PANEL)
        d.rounded_rectangle([PAD, ry, PAD + 44, ry + 36], radius=10, fill=rank_col)
        rk = str(i + 1)
        rkf = f_num(22)
        d.text((PAD + 22 - _text_w(d, rk, rkf) / 2, ry + 5), rk,
               font=rkf, fill=(30, 26, 16) if i < 3 else INK)
        # name
        d.text((PAD + 60, ry + 4), entry["name"][:28], font=f_title(26), fill=INK)
        # sobs (right aligned)
        val = _fmt(entry["sobs"])
        vf = f_num(26)
        d.text((W - PAD - _text_w(d, val, vf), ry + 4), val, font=vf, fill=ACCENT_SOFT)

    # summary strip at the bottom
    sy = 140 + 10 * row_h + 16
    d.rounded_rectangle([PAD, sy, W - PAD, H - PAD], radius=20, fill=PANEL)
    cells = [
        ("TODAY", data.get("daily")),
        ("THIS WEEK", data.get("weekly")),
        ("TOP GIVER", data.get("giver")),
        ("TOP SNITCH", data.get("snitch")),
    ]
    cw = (W - PAD * 2) / 4
    for i, (label, info) in enumerate(cells):
        cx = PAD + i * cw + 18
        d.text((cx, sy + 18), label, font=f_label(15), fill=INK_DIM)
        if info:
            d.text((cx, sy + 40), info["name"][:14], font=f_title(20), fill=INK)
            d.text((cx, sy + 68), _fmt(info["count"]), font=f_num(22), fill=ACCENT_SOFT)
        else:
            d.text((cx, sy + 40), "—", font=f_title(20), fill=INK_FAINT)

    mask = _round_mask((W, H), R)
    out = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    out.paste(card, (0, 0), mask)
    ImageDraw.Draw(out).rounded_rectangle([1, 1, W - 2, H - 2], radius=R, outline=CARD_EDGE, width=2)
    return out
