# core/profile/shop_render.py
"""Picture shop: category-colored item rows with drawn glyphs, auto-scaled names.
No emoji inside the image (Discord emoji render as tofu in Pillow)."""
from __future__ import annotations

import math
from PIL import Image, ImageDraw
from core.profile.render import f_title, f_label, f_num, f_reg, _round_mask, _text_w, _fmt, clean_name
from core.profile.icons import icon

INK = (240, 238, 245)
DIM = (150, 147, 165)
SOFT = (255, 205, 110)
PANEL = (38, 35, 48)
BG = (24, 22, 30)
CAT_COLORS = {
    "protection": (90, 160, 240),
    "debuff": (120, 200, 230),
    "buff": (245, 180, 70),
    "server": (200, 150, 240),
}
CAT_LABELS = {
    "protection": "PROTECTION", "debuff": "DEBUFF", "buff": "BUFF", "server": "SERVER ITEMS",
}
# which glyph to draw per item key
GLYPHS = {
    "shield": "shield", "guardian": "shield", "audit_ward": "ward", "reflect": "mirror",
    "freeze": "freeze", "freeze_deep": "freeze", "audit": "coin", "heist": "skull",
    "slow_curse": "slow", "marked": "target", "jail": "lock",
    "boost": "bolt", "boost_adv": "bolt", "hunter": "bolt", "lucky": "clover", "king": "crown",
}


def _glyph(d, img, x, y, kind, color):
    d.rounded_rectangle([x, y, x + 44, y + 44], radius=12, fill=(52, 48, 64))
    cx, cy = x + 22, y + 22
    if kind == "shield":
        d.polygon([(cx, y + 8), (x + 36, y + 16), (x + 36, y + 28), (cx, y + 38), (x + 8, y + 28), (x + 8, y + 16)], fill=color)
    elif kind == "ward":
        d.rounded_rectangle([x + 12, y + 10, x + 32, y + 34], radius=4, outline=color, width=3)
        d.line([x + 16, y + 22, x + 28, y + 22], fill=color, width=3)
    elif kind == "mirror":
        d.ellipse([x + 12, y + 8, x + 32, y + 36], outline=color, width=3)
        d.line([cx, y + 8, cx, y + 36], fill=color, width=2)
    elif kind == "freeze":
        for a in range(0, 360, 60):
            dx, dy = 12 * math.cos(math.radians(a)), 12 * math.sin(math.radians(a))
            d.line([cx, cy, cx + dx, cy + dy], fill=color, width=3)
    elif kind == "coin":
        d.ellipse([cx - 12, cy - 12, cx + 12, cy + 12], fill=color)
        d.text((cx - 4, cy - 9), "$", font=f_title(18), fill=(30, 30, 40))
    elif kind == "skull":
        d.ellipse([cx - 11, cy - 12, cx + 11, cy + 8], fill=color)
        d.rectangle([cx - 6, cy + 4, cx + 6, cy + 12], fill=color)
        d.ellipse([cx - 7, cy - 6, cx - 2, cy - 1], fill=(30, 30, 40))
        d.ellipse([cx + 2, cy - 6, cx + 7, cy - 1], fill=(30, 30, 40))
    elif kind == "slow":
        d.arc([x + 10, y + 10, x + 34, y + 34], 0, 270, fill=color, width=3)
    elif kind == "target":
        for r in (12, 7, 2):
            d.ellipse([cx - r, cy - r, cx + r, cy + r], outline=color, width=2)
    elif kind == "lock":
        d.rounded_rectangle([cx - 10, cy - 2, cx + 10, cy + 13], radius=3, fill=color)
        d.arc([cx - 7, cy - 14, cx + 7, cy + 4], 180, 360, fill=color, width=3)
    elif kind == "bolt":
        d.polygon([(cx + 2, y + 8), (x + 14, cy + 2), (cx, cy + 2), (cx + 4, y + 36), (x + 30, cy - 4), (cx + 2, cy - 4)], fill=color)
    elif kind == "clover":
        for ox, oy in [(-6, -6), (6, -6), (-6, 6), (6, 6)]:
            d.ellipse([cx + ox - 7, cy + oy - 7, cx + ox + 7, cy + oy + 7], fill=color)
    elif kind == "crown":
        d.polygon([(x + 8, y + 32), (x + 8, y + 18), (x + 16, y + 26), (cx, y + 12),
                   (x + 28, y + 26), (x + 36, y + 18), (x + 36, y + 32)], fill=color)
    else:
        d.ellipse([cx - 10, cy - 10, cx + 10, cy + 10], fill=color)


def _fit_name(d, text, max_w, start=21, lo=13):
    text = clean_name(text) or text
    if len(text) > 30:
        text = text[:29] + "…"
    size = start
    f = f_title(size)
    while size > lo:
        f = f_title(size)
        if _text_w(d, text, f) <= max_w:
            break
        size -= 1
    # final hard truncate if still too wide
    while text and _text_w(d, text, f) > max_w:
        text = text[:-2] + "…"
    return text, f


def make_shop_card(balance: int, grouped: dict, only_category: str | None = None) -> Image.Image:
    """grouped: {category_key: [ {key,name,price,stackable}, ... ]}"""
    W = 860
    PAD = 40
    cats = [only_category] if only_category else ["protection", "debuff", "buff", "server"]
    cats = [c for c in cats if grouped.get(c)]
    rows = sum(len(grouped[c]) for c in cats)
    H = 120 + len(cats) * 40 + rows * 56 + 50

    img = Image.new("RGBA", (W, H), BG + (255,))
    d = ImageDraw.Draw(img)

    si = icon("sob", 46)
    if si:
        img.alpha_composite(si, (PAD, 32))
    d.text((PAD + 62, 36), "Sob Shop", font=f_title(38), fill=INK)
    bal = f"Balance: {_fmt(balance)} sobs"
    bf = f_label(16)
    bw = _text_w(d, bal, bf) + 36
    d.rounded_rectangle([W - PAD - bw, 40, W - PAD, 80], radius=20, fill=PANEL)
    d.text((W - PAD - bw + 18, 50), bal, font=bf, fill=SOFT)

    y = 116
    for cat in cats:
        col = CAT_COLORS.get(cat, SOFT)
        d.text((PAD, y), CAT_LABELS.get(cat, cat.upper()), font=f_label(16), fill=col)
        y += 34
        for it in grouped[cat]:
            d.rounded_rectangle([PAD, y, W - PAD, y + 48], radius=12, fill=PANEL)
            _glyph(d, img, PAD + 8, y + 2, GLYPHS.get(it["key"], "dot"), col)
            # price
            stackable = it.get("stackable")
            price = f"{_fmt(it['price'])}/sec" if stackable else _fmt(it["price"])
            pf = f_num(20)
            pw = _text_w(d, price, pf)
            d.text((W - PAD - 18 - pw, y + 12), price, font=pf, fill=SOFT)
            # name (auto-scaled to fit)
            name_max = (W - PAD - 18 - pw) - (PAD + 64) - 18
            fitted, nf = _fit_name(d, it["name"], name_max)
            d.text((PAD + 64, y + 10), fitted, font=nf, fill=INK)
            y += 56
        y += 8

    d.text((PAD, y), "Tap a category button below to buy", font=f_reg(15), fill=DIM)
    img.putalpha(_round_mask((W, H), 28))
    return img
