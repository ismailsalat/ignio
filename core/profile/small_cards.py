# core/profile/small_cards.py
"""Small, slick info cards: daily claim, about. Use the custom icons."""
from __future__ import annotations

from PIL import Image, ImageDraw
from core.profile.render import f_title, f_label, f_num, f_reg, _round_mask, _text_w, _fmt
from core.profile.icons import icon

AMBER = (240, 177, 50)
SOFT = (255, 205, 110)
INK = (240, 238, 245)
DIM = (155, 152, 170)
PANEL = (40, 37, 50)
BG = (26, 24, 32)
GREEN = (90, 200, 130)


def _base(W, H, r=28):
    img = Image.new("RGBA", (W, H), BG + (255,))
    return img, ImageDraw.Draw(img)


def daily_card(reward: int, streak: int, balance: int, next_reward: int, maxed: bool) -> Image.Image:
    W, H = 720, 300
    img, d = _base(W, H)
    PAD = 40

    # sob icon + title
    si = icon("sob", 56)
    if si: img.alpha_composite(si, (PAD, 34))
    d.text((PAD + 70, 38), "Daily claimed!", font=f_title(38), fill=INK)

    # reward big number with sob icon
    d.text((PAD, 112), "YOU GOT", font=f_label(16), fill=DIM)
    si2 = icon("sob", 44)
    if si2: img.alpha_composite(si2, (PAD, 134))
    d.text((PAD + 54, 132), f"{_fmt(reward)} sobs", font=f_num(44), fill=AMBER)

    # streak pill with fire icon
    fx = W - 250
    d.rounded_rectangle([fx, 120, W - PAD, 180], radius=18, fill=PANEL)
    fi = icon("fire", 40)
    if fi: img.alpha_composite(fi, (fx + 16, 130))
    d.text((fx + 62, 128), "STREAK", font=f_label(14), fill=DIM)
    d.text((fx + 62, 146), f"{streak} day(s)", font=f_num(24), fill=SOFT)

    # balance + next hint
    d.text((PAD, 210), "BALANCE", font=f_label(14), fill=DIM)
    d.text((PAD, 230), f"{_fmt(balance)} sobs", font=f_num(28), fill=INK)
    hint = "Max reward — keep the streak!" if maxed else f"Tomorrow: {_fmt(next_reward)} sobs"
    d.text((PAD, 268), hint, font=f_reg(17), fill=DIM)

    img.putalpha(_round_mask((W, H), 28))
    return img


def about_card(version, codename, released, uptime, servers, ping, notes) -> Image.Image:
    W = 760
    note_lines = notes[:6]
    H = 250 + len(note_lines) * 30 + 30
    img, d = _base(W, H)
    PAD = 40

    si = icon("sob", 60)
    if si: img.alpha_composite(si, (PAD, 32))
    d.text((PAD + 76, 36), "Ignio", font=f_title(42), fill=INK)
    d.text((PAD + 78, 86), f"v{version} — {codename}", font=f_reg(20), fill=SOFT)

    # stat chips
    chips = [("Released", released), ("Uptime", uptime), ("Servers", str(servers)), ("Ping", ping)]
    cw = (W - PAD * 2 - 30) / 4
    for i, (k, v) in enumerate(chips):
        x = PAD + i * (cw + 10)
        d.rounded_rectangle([x, 130, x + cw, 200], radius=14, fill=PANEL)
        d.text((x + 14, 142), k, font=f_label(13), fill=DIM)
        d.text((x + 14, 162), str(v), font=f_num(20), fill=INK)

    # latest update
    d.text((PAD, 218), "LATEST UPDATE", font=f_label(15), fill=AMBER)
    y = 248
    for n in note_lines:
        d.ellipse([PAD, y + 7, PAD + 8, y + 15], fill=AMBER)
        d.text((PAD + 18, y), n[:64], font=f_reg(17), fill=INK)
        y += 30

    img.putalpha(_round_mask((W, H), 28))
    return img
