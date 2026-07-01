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
               avatar: Image.Image | None = None, handle: str | None = None) -> io.BytesIO:
    """A clean Twitter-style quote card: avatar, name + verified, @handle, the
    message, timestamp, and realistic-looking engagement numbers."""
    import secrets

    W = 720
    name = clean_name(display_name) or "someone"
    at = "@" + (handle or name.lower().replace(" ", "")[:15] or "user")
    body = (text or "").strip()
    if len(body) > 280:
        body = body[:277].rstrip() + "…"

    # tweet-like colors (dark mode twitter/X)
    TW_BG = (21, 24, 28)
    TW_INK = (231, 233, 234)
    TW_DIM = (113, 118, 123)
    TW_BLUE = (29, 155, 240)

    scratch = ImageDraw.Draw(Image.new("RGBA", (10, 10)))
    body_font = f_reg(30)
    lines = _wrap_to_width(scratch, body, body_font, W - 80)[:8]
    line_h = 42
    top = 110
    body_h = len(lines) * line_h
    H = top + body_h + 120

    img = Image.new("RGBA", (W, H), TW_BG + (255,))
    d = ImageDraw.Draw(img)

    # avatar
    ax, ay, asz = 28, 28, 56
    if avatar is not None:
        av = avatar.convert("RGBA").resize((asz, asz))
        mask = Image.new("L", (asz, asz), 0)
        ImageDraw.Draw(mask).ellipse([0, 0, asz, asz], fill=255)
        img.paste(av, (ax, ay), mask)
    else:
        d.ellipse([ax, ay, ax + asz, ay + asz], fill=(70, 66, 84))
        init = (name[:1] or "?").upper()
        d.text((ax + asz // 2 - _text_w(d, init, f_title(26)) // 2, ay + 12),
               init, font=f_title(26), fill=TW_INK)

    # name + verified check + handle
    nx = ax + asz + 16
    d.text((nx, ay + 4), name, font=f_title(24), fill=TW_INK)
    nw = _text_w(d, name, f_title(24))
    # verified badge (drawn check so it always renders)
    bx, by = nx + nw + 8, ay + 9
    d.ellipse([bx, by, bx + 20, by + 20], fill=TW_BLUE)
    d.line([(bx + 5, by + 10), (bx + 9, by + 14), (bx + 15, by + 6)],
           fill=(255, 255, 255), width=2, joint="curve")
    d.text((nx, ay + 32), at, font=f_reg(18), fill=TW_DIM)

    # body
    y = top
    for ln in lines:
        d.text((28, y), ln, font=body_font, fill=TW_INK)
        y += line_h

    # timestamp line
    y += 8
    d.text((28, y), timestamp, font=f_reg(17), fill=TW_DIM)
    y += 34

    # divider
    d.line([(28, y), (W - 28, y)], fill=(47, 51, 54), width=1)
    y += 18

    # realistic engagement numbers
    def _fmt(n):
        if n >= 1000:
            return f"{n/1000:.1f}K".replace(".0K", "K")
        return str(n)
    replies = secrets.randbelow(900) + 12
    retweets = secrets.randbelow(4000) + 50
    likes = retweets * (3 + secrets.randbelow(4)) + secrets.randbelow(500)
    views = likes * (8 + secrets.randbelow(20)) + secrets.randbelow(9000)

    stats = [(_fmt(retweets), "Reposts"), (_fmt(likes), "Likes"), (_fmt(views), "Views")]
    sx = 28
    for val, lbl in stats:
        d.text((sx, y), val, font=f_title(20), fill=TW_INK)
        vw = _text_w(d, val, f_title(20))
        d.text((sx, y + 26), lbl, font=f_reg(14), fill=TW_DIM)
        lw = _text_w(d, lbl, f_reg(14))
        sx += max(vw, lw) + 48

    d.text((W - 70, H - 26), "ignio", font=f_label(13), fill=(70, 74, 78))

    img.putalpha(_round_mask((W, H), 22))
    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="PNG")
    buf.seek(0)
    return buf


def caption_gif(base: Image.Image, caption: str, max_bytes: int = 8 * 1024 * 1024):
    """Caption an animated GIF, preserving animation. Returns (BytesIO, is_animated).
    Falls back to a first-frame still if the GIF is too big/slow to render safely.

    Correctly composites partial/delta frames (GIF disposal) onto a running
    canvas so frames that only store changed pixels don't render as blank/white."""
    cap = (caption or "").strip()
    n_frames = getattr(base, "n_frames", 1)
    if n_frames > 150 or (base.size[0] * base.size[1]) > 1_500_000:
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
        # running canvas that carries previous frame content (handles disposal)
        prev = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        for i in range(n_frames):
            base.seek(i)
            # composite this (possibly partial) frame onto the previous canvas
            cur = base.convert("RGBA")
            canvas = prev.copy()
            canvas.alpha_composite(cur)
            prev = canvas.copy()

            # flatten the fully-composited frame onto white, then add caption bar
            flat = Image.new("RGBA", (W, H), (255, 255, 255, 255))
            flat.alpha_composite(canvas)

            out = Image.new("RGBA", (W, H + bar_h), (255, 255, 255, 255))
            out.paste(flat, (0, bar_h))
            d = ImageDraw.Draw(out)
            y = 14
            for ln in lines:
                lw = _text_w(d, ln, font)
                d.text(((W - lw) // 2, y), ln, font=font, fill=(15, 15, 18))
                y += line_h
            frames.append(out.convert("RGB").convert("P", palette=Image.ADAPTIVE, colors=256))
            durations.append(base.info.get("duration", 80))
    except Exception:
        base.seek(0)
        return caption_image(base.convert("RGBA"), cap), False

    buf = io.BytesIO()
    frames[0].save(buf, format="GIF", save_all=True, append_images=frames[1:],
                   duration=durations, loop=0, disposal=1, optimize=False)
    if buf.tell() > max_bytes:
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
