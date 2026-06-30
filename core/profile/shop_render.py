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
    "steal": (235, 120, 110),
    "server": (200, 150, 240),
}
CAT_LABELS = {
    "protection": "PROTECTION", "debuff": "DEBUFF", "buff": "BUFF",
    "steal": "STEAL", "server": "SERVER ITEMS",
}
# which glyph to draw per item key
GLYPHS = {
    "shield": "shield", "guardian": "shield", "audit_ward": "ward", "reflect": "mirror",
    "freeze": "freeze", "freeze_deep": "freeze", "audit": "coin", "heist": "skull",
    "slow_curse": "slow", "marked": "target", "jail": "lock",
    "boost": "bolt", "boost_adv": "bolt", "hunter": "bolt", "lucky": "clover", "king": "crown",
    "vault_ward": "ward", "lockpick": "lock", "safelock": "shield",
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


def make_shop_card(balance: int, grouped: dict, only_category: str | None = None,
                   preview: int = 3, page: int = 0, per_page: int = 6) -> Image.Image:
    """grouped: {category_key: [ {key,name,price,stackable,description} ]}

    Overview (only_category=None): shows up to `preview` items per category with a
    '+N more' hint and 'tap a category for the full list & details'.
    Category view (only_category set): shows full items WITH descriptions, paginated
    by `page`/`per_page`."""
    W = 860
    PAD = 40

    if only_category:
        cats = [only_category] if grouped.get(only_category) else []
        detail = True
    else:
        cats = [c for c in ["protection", "debuff", "buff", "steal", "server"] if grouped.get(c)]
        detail = False

    # build the row list, honoring preview/pagination
    layout = []   # (kind, payload)
    total_pages = 1
    for cat in cats:
        items = grouped[cat]
        if detail:
            total_pages = max(1, (len(items) + per_page - 1) // per_page)
            page = max(0, min(page, total_pages - 1))
            shown = items[page * per_page:(page + 1) * per_page]
            layout.append(("header", cat))
            for it in shown:
                layout.append(("item_detail", it))
        else:
            layout.append(("header", cat))
            for it in items[:preview]:
                layout.append(("item", it))
            extra = len(items) - preview
            if extra > 0:
                layout.append(("more", (cat, extra)))

    # measure height
    row_h = {"header": 40, "item": 56, "item_detail": 74, "more": 30}
    body_h = sum(row_h[k] for k, _ in layout)
    H = 116 + body_h + 50
    if detail and total_pages > 1:
        H += 26

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
    cur_col = SOFT
    for kind, payload in layout:
        if kind == "header":
            cur_col = CAT_COLORS.get(payload, SOFT)
            label = CAT_LABELS.get(payload, payload.upper())
            if detail and total_pages > 1:
                label = f"{label}   ·   page {page + 1}/{total_pages}"
            d.text((PAD, y), label, font=f_label(16), fill=cur_col)
            y += 40
        elif kind in ("item", "item_detail"):
            it = payload
            h = row_h[kind]
            d.rounded_rectangle([PAD, y, W - PAD, y + h - 8], radius=12, fill=PANEL)
            _glyph(d, img, PAD + 8, y + 2, GLYPHS.get(it["key"], "dot"), cur_col)
            stackable = it.get("stackable")
            price = f"{_fmt(it['price'])}/sec" if stackable else _fmt(it["price"])
            pf = f_num(20)
            pw = _text_w(d, price, pf)
            d.text((W - PAD - 18 - pw, y + 12), price, font=pf, fill=SOFT)
            name_max = (W - PAD - 18 - pw) - (PAD + 64) - 18
            fitted, nf = _fit_name(d, it["name"], name_max)
            d.text((PAD + 64, y + (10 if kind == "item" else 8)), fitted, font=nf, fill=INK)
            if kind == "item_detail":
                desc = clean_name(it.get("description", "")) or it.get("description", "")
                desc, df = _fit_desc(d, desc, W - PAD - (PAD + 64) - 18)
                d.text((PAD + 64, y + 36), desc, font=df, fill=DIM)
            y += h
        elif kind == "more":
            cat, extra = payload
            d.text((PAD + 64, y + 4), f"+{extra} more — tap {cat.title()} below for the full list & details",
                   font=f_reg(14), fill=DIM)
            y += row_h["more"]

    if detail:
        foot = "Tap an item button below to buy"
        if total_pages > 1:
            foot += "  ·  use Prev/Next for more"
    else:
        foot = "Tap a category button below for the full list & details"
    d.text((PAD, y), foot, font=f_reg(15), fill=DIM)

    img.putalpha(_round_mask((W, H), 28))
    return img


def _fit_desc(d, text, max_w, size=15):
    f = f_reg(size)
    if not text:
        return "", f
    while text and _text_w(d, text, f) > max_w:
        text = text[:-2] + "…"
    return text, f
