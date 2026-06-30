# core/utilities/cards.py
"""
Compact image cards for Utilities: quote cards and captioned images.
Pure Pillow, reuses the bot's bundled fonts and style. No media is saved.
"""
from __future__ import annotations

import io
import textwrap

from PIL import Image, ImageDraw
from core.profile.render import f_title, f_label, f_reg, _round_mask, _text_w, clean_name

BG = (24, 22, 30)
CARD = (34, 31, 42)
INK = (238, 236, 244)
DIM = (150, 147, 165)
ACCENT = (240, 177, 50)


def _wrap_to_width(draw, text, font, max_w):
    """Word-wrap text to fit a pixel width; returns list of lines."""
    words = text.split()
    lines, cur = [], ""
    for w in words:
        trial = (cur + " " + w).strip()
        if _text_w(draw, trial, font) <= max_w or not cur:
            cur = trial
        else:
            lines.append(cur); cur = w
    if cur:
        lines.append(cur)
    return lines


def quote_card(display_name: str, text: str, timestamp: str,
               avatar: Image.Image | None = None) -> io.BytesIO:
    """One clean quote image: avatar, name, message, timestamp, tiny branding."""
    W = 720
    name = clean_name(display_name) or "someone"
    body = (text or "").strip()
    if len(body) > 280:
        body = body[:277].rstrip() + "…"

    scratch = ImageDraw.Draw(Image.new("RGBA", (10, 10)))
    body_font = f_reg(26)
    lines = _wrap_to_width(scratch, body, body_font, W - 150)
    lines = lines[:6]
    line_h = 36
    H = max(180, 120 + len(lines) * line_h + 40)

    img = Image.new("RGBA", (W, H), BG + (255,))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([12, 12, W - 12, H - 12], radius=22, fill=CARD)

    # avatar
    ax, ay, asz = 36, 36, 64
    if avatar is not None:
        av = avatar.convert("RGBA").resize((asz, asz))
        mask = Image.new("L", (asz, asz), 0)
        ImageDraw.Draw(mask).ellipse([0, 0, asz, asz], fill=255)
        img.paste(av, (ax, ay), mask)
    else:
        d.ellipse([ax, ay, ax + asz, ay + asz], fill=(70, 66, 84))
        init = (name[:1] or "?").upper()
        d.text((ax + asz // 2 - _text_w(d, init, f_title(30)) // 2, ay + 14),
               init, font=f_title(30), fill=INK)

    d.text((ax + asz + 18, ay + 6), name, font=f_title(26), fill=INK)
    d.text((ax + asz + 18, ay + 38), timestamp, font=f_reg(16), fill=DIM)

    y = ay + asz + 24
    for ln in lines:
        d.text((36, y), ln, font=body_font, fill=INK)
        y += line_h

    d.text((W - 90, H - 34), "ignio", font=f_label(14), fill=(90, 86, 104))

    img.putalpha(_round_mask((W, H), 24))
    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="PNG")
    buf.seek(0)
    return buf


def caption_gif(base: Image.Image, caption: str, max_bytes: int = 8 * 1024 * 1024):
    """Caption an animated GIF, preserving animation. Returns (BytesIO, is_animated).
    Falls back to a first-frame still if the GIF is too big/slow to render safely."""
    cap = (caption or "").strip()
    n_frames = getattr(base, "n_frames", 1)
    # safety caps: don't render huge/long GIFs frame-by-frame
    if n_frames > 120 or (base.size[0] * base.size[1]) > 1_200_000:
        base.seek(0)
        return caption_image(base.convert("RGBA"), cap), False

    scratch = ImageDraw.Draw(Image.new("RGBA", (10, 10)))
    W, H = base.size
    size = max(20, min(46, W // 16))
    font = f_title(size)
    lines = _wrap_to_width(scratch, cap[:140], font, W - 40)[:3]
    line_h = size + 8
    bar_h = 20 + len(lines) * line_h + 10

    frames = []
    durations = []
    try:
        for i in range(n_frames):
            base.seek(i)
            frame = base.convert("RGBA")
            out = Image.new("RGBA", (W, H + bar_h), (255, 255, 255, 255))
            out.paste(frame, (0, bar_h))
            d = ImageDraw.Draw(out)
            y = 14
            for ln in lines:
                lw = _text_w(d, ln, font)
                d.text(((W - lw) // 2, y), ln, font=font, fill=(15, 15, 18))
                y += line_h
            frames.append(out.convert("P", palette=Image.ADAPTIVE))
            durations.append(base.info.get("duration", 80))
    except Exception:
        base.seek(0)
        return caption_image(base.convert("RGBA"), cap), False

    buf = io.BytesIO()
    frames[0].save(buf, format="GIF", save_all=True, append_images=frames[1:],
                   duration=durations, loop=0, disposal=2)
    if buf.tell() > max_bytes:
        # too large animated — fall back to first-frame still
        base.seek(0)
        return caption_image(base.convert("RGBA"), cap), False
    buf.seek(0)
    return buf, True


def caption_image(base: Image.Image, caption: str) -> io.BytesIO:
    """Add a top caption bar to an image, auto-wrapped to fit. Returns PNG."""
    base = base.convert("RGBA")
    W, H = base.size
    cap = (caption or "").strip()
    if len(cap) > 140:
        cap = cap[:137].rstrip() + "…"

    scratch = ImageDraw.Draw(Image.new("RGBA", (10, 10)))
    # scale font to image width
    size = max(20, min(46, W // 16))
    font = f_title(size)
    lines = _wrap_to_width(scratch, cap, font, W - 40)[:3]
    line_h = size + 8
    bar_h = 20 + len(lines) * line_h + 10

    out = Image.new("RGBA", (W, H + bar_h), (255, 255, 255, 255))
    out.paste(base, (0, bar_h))
    d = ImageDraw.Draw(out)
    y = 14
    for ln in lines:
        lw = _text_w(d, ln, font)
        d.text(((W - lw) // 2, y), ln, font=font, fill=(15, 15, 18))
        y += line_h

    buf = io.BytesIO()
    out.convert("RGB").save(buf, format="PNG")
    buf.seek(0)
    return buf
