#!/usr/bin/env python3
"""
Ignio sob profile card renderer.

make_card(stats) -> PIL.Image  (a finished profile card you can save as PNG)

Fonts are bundled in ./fonts so this runs anywhere with no install.
Only dependency: Pillow  (pip install pillow)
"""
from __future__ import annotations

import os
from PIL import Image, ImageDraw, ImageFont, ImageFilter

import unicodedata


def clean_name(s: str) -> str:
    """Strip emoji, symbols, and exotic-script characters the bundled (Latin)
    fonts can't render, so names don't show as ☐ boxes. Keeps Latin, Greek,
    Cyrillic, CJK, Hangul, Hiragana/Katakana, digits, punctuation, spaces."""
    if not s:
        return ""
    out = []
    for ch in s:
        cp = ord(ch)
        if ch.isspace():
            out.append(ch)
            continue
        cat = unicodedata.category(ch)
        # drop emoji / symbols / private-use / format / surrogate chars
        if cat in ("So", "Sk", "Cs", "Cf", "Co", "Cn"):
            continue
        # keep only scripts the bundled fonts actually have glyphs for
        keep = (
            cp < 0x250 or                  # Latin + Latin-1 + Latin Ext-A/B
            0x250 <= cp <= 0x2af or        # IPA extensions
            0x370 <= cp <= 0x52f or        # Greek + Cyrillic
            0x1e00 <= cp <= 0x1eff or      # Latin Extended Additional
            0x2010 <= cp <= 0x205e or      # general punctuation
            0x3040 <= cp <= 0x30ff or      # Hiragana + Katakana
            0x4e00 <= cp <= 0x9fff or      # CJK unified
            0xac00 <= cp <= 0xd7a3         # Hangul syllables
        )
        if keep:
            out.append(ch)
    return " ".join("".join(out).split()).strip()


def renderable(s: str, threshold: float = 0.5) -> bool:
    """True if enough of the string is basic Latin/ASCII to render readably.
    Used to decide whether to fall back to a username."""
    if not s:
        return False
    latin = sum(1 for c in s if ord(c) < 0x250 and c.strip())
    total = sum(1 for c in s if c.strip())
    return total > 0 and (latin / total) >= threshold


HERE = os.path.dirname(os.path.abspath(__file__))
FONTS = os.path.join(HERE, "fonts")
WALLPAPERS = os.path.join(HERE, "wallpapers")
BADGES = os.path.join(HERE, "badges")

# ---- theme -----------------------------------------------------------
# Color presets. Pick one with stats["theme"] = "amber" / "red" / ...
# or pass a custom (r,g,b) via stats["accent"].
THEMES = {
    "amber":  (240, 177, 50),
    "red":    (235, 70, 70),
    "blue":   (70, 150, 240),
    "green":  (80, 200, 120),
    "purple": (170, 110, 230),
    "pink":   (240, 110, 180),
    "cyan":   (60, 200, 210),
    "gold":   (220, 180, 60),
    "white":  (235, 235, 240),
}
DEFAULT_ACCENT = (240, 177, 50)    # #F0B132 amber

INK          = (245, 243, 250)
INK_DIM      = (150, 147, 165)
INK_FAINT    = (110, 107, 124)
BG_A         = (38, 35, 46)      # top-left of gradient
BG_B         = (22, 20, 28)      # bottom-right
CARD_EDGE    = (70, 66, 84)
PANEL        = (48, 45, 58)
TRACK        = (56, 53, 66)


def _resolve_accent(stats):
    """Figure out the accent color from stats: explicit (r,g,b) wins, then a
    named theme, else the default amber. Returns (accent, accent_soft)."""
    accent = stats.get("accent")
    if not accent:
        theme = (stats.get("theme") or "amber").lower()
        accent = THEMES.get(theme, DEFAULT_ACCENT)
    accent = tuple(accent)
    # a lighter version for highlights
    soft = tuple(min(255, int(c + (255 - c) * 0.35)) for c in accent)
    return accent, soft


def _f(name, size):
    return ImageFont.truetype(os.path.join(FONTS, name), size)

def f_title(s): return _f("Outfit-Bold.ttf", s)
def f_label(s): return _f("WorkSans-Bold.ttf", s)
def f_num(s):   return _f("BricolageGrotesque-Bold.ttf", s)
def f_reg(s):   return _f("Outfit-Regular.ttf", s)


# ---- helpers ---------------------------------------------------------
def _diag_gradient(size, a, b):
    """Diagonal gradient — nicer than a flat vertical one."""
    w, h = size
    grad = Image.new("RGB", size)
    px = grad.load()
    for y in range(h):
        for x in range(w):
            t = (x / w + y / h) / 2
            px[x, y] = (
                int(a[0] + (b[0]-a[0])*t),
                int(a[1] + (b[1]-a[1])*t),
                int(a[2] + (b[2]-a[2])*t),
            )
    return grad


def _round_mask(size, r):
    m = Image.new("L", size, 0)
    ImageDraw.Draw(m).rounded_rectangle([0, 0, size[0]-1, size[1]-1], radius=r, fill=255)
    return m


def _text_w(d, text, font):
    b = d.textbbox((0, 0), text, font=font)
    return b[2] - b[0]


def _fmt(n):
    if n >= 1_000_000: return f"{n/1_000_000:.2f}M"
    if n >= 10_000:    return f"{n/1_000:.1f}K"
    return f"{n:,}"


def _avatar(size, initial, avatar_img=None, accent=DEFAULT_ACCENT):
    """Circular avatar. Pass a PIL image as avatar_img for a real photo;
    otherwise draws an initial on an accent disc."""
    out = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).ellipse([0, 0, size-1, size-1], fill=255)

    if avatar_img is not None:
        a = avatar_img.convert("RGBA").resize((size, size))
        out.paste(a, (0, 0), mask)
    else:
        disc = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        dd = ImageDraw.Draw(disc)
        dd.ellipse([0, 0, size-1, size-1], fill=(64, 60, 76))
        ft = f_title(int(size * 0.46))
        b = dd.textbbox((0, 0), initial, font=ft)
        dd.text(((size-(b[2]-b[0]))/2 - b[0], (size-(b[3]-b[1]))/2 - b[1]),
                initial, font=ft, fill=accent)
        out.paste(disc, (0, 0), mask)
    return out


# ---- main ------------------------------------------------------------
def _cover(img, size):
    """Resize+crop an image to fill `size` exactly (like CSS background cover)."""
    tw, th = size
    iw, ih = img.size
    scale = max(tw / iw, th / ih)
    nw, nh = int(iw * scale), int(ih * scale)
    img = img.resize((nw, nh))
    left = (nw - tw) // 2
    top = (nh - th) // 2
    return img.crop((left, top, left + tw, top + th))


def make_card(stats: dict, avatar_img: Image.Image | None = None,
              wallpaper: str | None = None) -> Image.Image:
    """
    stats keys:
      name, handle, rank, tier (optional), sobs_today, sobs_week, sobs_alltime,
      tokens, next_threshold, sobs_into_threshold, badges (optional list), about
    wallpaper: filename (without extension) of any image in wallpapers/.
      Photos get a cover-crop + dark gradient so text stays readable.
      None -> a plain dark gradient.
    """
    W, H, R = 1040, 500, 40

    ACCENT, ACCENT_SOFT = _resolve_accent(stats)

    card = None
    used_photo = False

    if wallpaper:
        # Case-insensitive lookup so it works on Linux/Railway too (where the
        # filesystem is case-sensitive). Match by lowercased basename.
        want = wallpaper.lower()
        found = None
        if os.path.isdir(WALLPAPERS):
            for f in os.listdir(WALLPAPERS):
                n, ext = os.path.splitext(f)
                if n.lower() == want and ext.lower() in (".png", ".jpg", ".jpeg", ".webp"):
                    found = os.path.join(WALLPAPERS, f)
                    break
        if found:
            card = _cover(Image.open(found).convert("RGB"), (W, H)).convert("RGBA")
            used_photo = True

    if card is None:
        card = _diag_gradient((W, H), BG_A, BG_B).convert("RGBA")

    # readability overlay: darken the left (where the text sits)
    if used_photo:
        ov = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        op = ov.load()
        for x in range(W):
            a = int(205 - 120 * (x / W))
            a = max(70, min(210, a))
            for y in range(H):
                op[x, y] = (10, 9, 14, a)
        card = Image.alpha_composite(card, ov)

    # accent glow blooming from behind the avatar
    glow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(glow).ellipse([-120, -160, 360, 260], fill=ACCENT + (55,))
    glow = glow.filter(ImageFilter.GaussianBlur(90))
    card = Image.alpha_composite(card, glow)
    d = ImageDraw.Draw(card)

    PAD = 44

    # ---------- avatar with accent ring ----------
    av = 156
    ring = av + 12
    ax, ay = PAD, PAD
    d.ellipse([ax-6, ay-6, ax-6+ring, ay-6+ring], fill=ACCENT)          # ring
    d.ellipse([ax-6, ay-6, ax-6+ring, ay-6+ring], outline=ACCENT_SOFT, width=2)
    avatar = _avatar(av, stats["name"][:1].upper(), avatar_img, accent=ACCENT)
    card.paste(avatar, (ax, ay), avatar)
    d = ImageDraw.Draw(card)

    # ---------- name + handle ----------
    nx = ax + av + 34
    d.text((nx, ay + 6), stats["name"], font=f_title(54), fill=INK)
    d.text((nx, ay + 70), "@" + stats["handle"], font=f_reg(28), fill=INK_DIM)

    # tier/title chip (optional) e.g. "Snitch King"
    chip_y = ay + 112
    if stats.get("tier"):
        chip = stats["tier"]
        cf = f_label(22)
        cw = _text_w(d, chip, cf) + 36
        d.rounded_rectangle([nx, chip_y, nx+cw, chip_y+40], radius=20, fill=ACCENT)
        d.text((nx+18, chip_y+8), chip, font=cf, fill=(30, 26, 16))

    # ---------- rank badge (top right) ----------
    rtxt = f"#{stats['rank']}"
    rf = f_num(60)
    rw = _text_w(d, rtxt, rf)
    d.text((W - PAD - rw, ay + 2), rtxt, font=rf, fill=ACCENT)
    lbl = "ALL-TIME RANK"
    lf = f_label(18)
    d.text((W - PAD - _text_w(d, lbl, lf), ay + 70), lbl, font=lf, fill=INK_DIM)

    # tokens line under rank
    tok = f"{stats['tokens']} tokens"
    tf = f_label(22)
    d.text((W - PAD - _text_w(d, tok, tf), ay + 100), tok, font=tf, fill=ACCENT_SOFT)

    # ---------- progress bar to next token ----------
    bx, by = PAD, 244
    bw, bh = W - PAD*2, 30
    d.text((bx, by - 30), "NEXT TOKEN", font=f_label(18), fill=INK_DIM)
    prog = f"{stats['sobs_into_threshold']} / {stats['next_threshold']}"
    d.text((bx + bw - _text_w(d, prog, f_label(20)), by - 30), prog, font=f_label(20), fill=INK_DIM)
    d.rounded_rectangle([bx, by, bx+bw, by+bh], radius=15, fill=TRACK)
    frac = 0.0
    if stats.get("next_threshold"):
        frac = max(0.0, min(1.0, stats["sobs_into_threshold"] / stats["next_threshold"]))
    fw = int(bw * frac)
    if fw >= bh:
        bar = Image.new("RGBA", (fw, bh), (0, 0, 0, 0))
        bd = ImageDraw.Draw(bar)
        bd.rounded_rectangle([0, 0, fw-1, bh-1], radius=15, fill=ACCENT)
        card.paste(bar, (bx, by), bar)
        d = ImageDraw.Draw(card)

    # ---------- stat blocks ----------
    by2 = 300
    bh2 = 82
    gap = 22
    bw2 = (W - PAD*2 - gap*2) // 3
    for i, (label, val) in enumerate([
        ("TODAY", stats["sobs_today"]),
        ("THIS WEEK", stats["sobs_week"]),
        ("ALL-TIME", stats["sobs_alltime"]),
    ]):
        x = PAD + i*(bw2 + gap)
        d.rounded_rectangle([x, by2, x+bw2, by2+bh2], radius=18, fill=PANEL)
        d.rounded_rectangle([x+18, by2+16, x+18+28, by2+21, ], radius=3, fill=ACCENT)
        d.text((x+18, by2+28), label, font=f_label(16), fill=INK_DIM)
        d.text((x+18, by2+46), _fmt(val), font=f_num(30), fill=INK)

    # ---------- achievement badges row ----------
    badges = stats.get("badges") or []
    if badges:
        bsize = 46
        bgap = 12
        bx0 = PAD
        by0 = 438
        d.text((bx0, by0 - 24), "ACHIEVEMENTS", font=f_label(15), fill=INK_FAINT)
        x = bx0
        for name in badges[:12]:
            bp = os.path.join(BADGES, name + ".png")
            if os.path.exists(bp):
                icon = Image.open(bp).convert("RGBA").resize((bsize, bsize))
                card.paste(icon, (x, by0), icon)
                x += bsize + bgap
        d = ImageDraw.Draw(card)

    # round corners + edge
    mask = _round_mask((W, H), R)
    out = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    out.paste(card, (0, 0), mask)
    ImageDraw.Draw(out).rounded_rectangle([1, 1, W-2, H-2], radius=R, outline=CARD_EDGE, width=2)
    return out
