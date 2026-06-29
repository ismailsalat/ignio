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


def treasury_card(stats: dict, name_lookup) -> Image.Image:
    """Server treasury stats. name_lookup(uid) -> display string."""
    W = 760
    recent = stats.get("recent", [])[:5]
    H = 320 + max(1, len(recent)) * 34 + 40
    img, d = _base(W, H)
    PAD = 40

    si = icon("sob", 52)
    if si: img.alpha_composite(si, (PAD, 32))
    d.text((PAD + 66, 36), "Server Treasury", font=f_title(36), fill=INK)
    d.text((PAD + 68, 82), "tax collected from shop purchases", font=f_reg(18), fill=DIM)

    # big pot number
    d.text((PAD, 122), "IN THE POT", font=f_label(15), fill=DIM)
    pi = icon("sob", 40)
    if pi: img.alpha_composite(pi, (PAD, 146))
    d.text((PAD + 50, 144), f"{_fmt(stats.get('treasury', 0))} sobs", font=f_num(40), fill=AMBER)

    # taxed chips
    chips = [("Today", stats.get("today", 0)), ("This week", stats.get("week", 0)),
             ("All-time", stats.get("alltime", 0)), ("Taxpayers", stats.get("payers", 0))]
    cw = (W - PAD * 2 - 30) / 4
    for i, (k, v) in enumerate(chips):
        x = PAD + i * (cw + 10)
        d.rounded_rectangle([x, 210, x + cw, 276], radius=14, fill=PANEL)
        d.text((x + 14, 222), k, font=f_label(12), fill=DIM)
        d.text((x + 14, 242), _fmt(v), font=f_num(18), fill=INK)

    # recent taxpayers
    d.text((PAD, 292), "RECENT TAXPAYERS", font=f_label(14), fill=AMBER)
    y = 320
    if recent:
        for r in recent:
            d.text((PAD, y), name_lookup(r["user_id"])[:24], font=f_reg(17), fill=INK)
            amt = f"+{_fmt(r['amount'])}"
            d.text((W - PAD - _text_w(d, amt, f_num(17)), y), amt, font=f_num(17), fill=SOFT)
            y += 34
    else:
        d.text((PAD, y), "No tax collected yet.", font=f_reg(17), fill=DIM)
        y += 34

    # all-time top
    top = stats.get("top")
    if top:
        d.text((PAD, y + 6), f"Top contributor: {name_lookup(top['user_id'])[:20]} "
               f"({_fmt(top['total'])})", font=f_reg(16), fill=DIM)

    img.putalpha(_round_mask((W, H), 28))
    return img


def guide_card() -> Image.Image:
    """Newcomer 'how this bot works' explainer — actionable, with real commands."""
    W = 840
    earn = [
        ("React with a sob emoji", "on others' messages = they earn"),
        ("!daily", "free sobs every day — keep a streak"),
        ("!ss (reply to a msg)", "snitch to wipe & steal their sobs"),
        ("!buy audit  +  !use audit @user", "steal a cut of someone's sobs"),
    ]
    protect = [
        ("!buy shield", "then  !use shield <seconds>"),
        ("Shields block snitches AND audits", "buy seconds, use when targeted"),
        ("!buy guardian", "blocks the next few snitches"),
    ]
    know = [
        ("!sob", "your profile & rank"),
        ("!sob stats", "where your sobs come from"),
        ("!shop", "everything you can buy"),
        ("!help", "every command"),
    ]
    H = 150 + len(earn)*40 + 70 + len(protect)*40 + 70 + len(know)*36 + 60
    img, d = _base(W, H)
    PAD = 44

    si = icon("sob", 56)
    if si: img.alpha_composite(si, (PAD, 32))
    d.text((PAD + 72, 34), "How Ignio Works", font=f_title(38), fill=INK)
    d.text((PAD + 74, 82), "earn sobs, protect them, climb the leaderboard", font=f_reg(18), fill=DIM)

    def section(title, color, items, y, cmd_color):
        d.text((PAD, y), title, font=f_label(17), fill=color)
        y += 34
        for cmd, desc in items:
            d.text((PAD, y), cmd, font=f_num(20), fill=cmd_color)
            cw = _text_w(d, cmd, f_num(20))
            d.text((PAD + cw + 16, y + 2), desc, font=f_reg(17), fill=DIM)
            y += 40
        return y

    y = 140
    y = section("EARN SOBS", AMBER, earn, y, INK)
    y += 24
    y = section("PROTECT YOURSELF  (most people forget this!)", GREEN, protect, y, GREEN)
    y += 24
    d.text((PAD, y), "GOOD TO KNOW", font=f_label(17), fill=SOFT); y += 34
    for cmd, desc in know:
        d.text((PAD, y), cmd, font=f_num(19), fill=AMBER)
        cw = _text_w(d, cmd, f_num(19))
        d.text((PAD + cw + 16, y + 2), desc, font=f_reg(16), fill=DIM)
        y += 36

    y += 8
    d.text((PAD, y), "Getting audited a lot? Buy a shield - it's the #1 way to stay safe.",
           font=f_reg(17), fill=INK)

    img.putalpha(_round_mask((W, H), 28))
    return img


# ----------------------------------------------------------------------
# Audit limit / cooldown card (shown when an auditor is capped or cooling down)
# ----------------------------------------------------------------------
RED = (235, 110, 110)


def _fmt_dur(secs: int) -> str:
    secs = max(0, int(secs))
    h, rem = divmod(secs, 3600)
    m, s = divmod(rem, 60)
    if h: return f"{h}h {m}m"
    if m: return f"{m}m"
    return f"{s}s"


def audit_limit_card(kind: str, info: dict) -> Image.Image:
    """kind = 'audit_capped' or 'audit_cooldown'."""
    W, H = 720, 230
    img, d = _base(W, H)
    PAD = 40

    if kind == "audit_capped":
        title = "Audit limit reached"
        cap = int(info.get("cap", 0))
        big = f"{cap}/{cap}"
        sub = "You've used all your audits for today."
        hint = "Resets at midnight UTC. Snitch or react to earn meanwhile."
    else:
        title = "Audit cooling down"
        left = int(info.get("cooldown_left", 0))
        big = _fmt_dur(left)
        done = int(info.get("done", 0)); cap = int(info.get("cap", 0))
        sub = f"Wait before your next audit. ({done}/{cap} used today)"
        hint = "Cooldown stops one person draining the whole server at once."

    d.text((PAD, 36), "⏳  " + title, font=f_title(34), fill=INK)
    # big value pill
    d.text((PAD, 104), "READY IN" if kind == "audit_cooldown" else "USED TODAY", font=f_label(15), fill=DIM)
    d.text((PAD, 126), big, font=f_num(48), fill=RED)
    d.text((PAD, 196), sub, font=f_reg(18), fill=INK)
    d.text((PAD, 168), hint, font=f_reg(15), fill=DIM)

    img.putalpha(_round_mask((W, H), 28))
    return img


# ----------------------------------------------------------------------
# Shield suggestion card (nudges an audit victim to protect their sobs)
# ----------------------------------------------------------------------
def shield_suggest_card(lost_today: int, shield_price: int | None = None) -> Image.Image:
    W, H = 720, 250
    img, d = _base(W, H)
    PAD = 40

    d.text((PAD, 34), "🛡️  You're being audited", font=f_title(34), fill=INK)

    # lost-today panel
    d.text((PAD, 100), "LOST TO AUDITS TODAY", font=f_label(15), fill=DIM)
    si = icon("sob", 40)
    if si: img.alpha_composite(si, (PAD, 122))
    d.text((PAD + 50, 120), f"{_fmt(lost_today)} sobs", font=f_num(40), fill=RED)

    # suggestion pill on the right
    bx = W - 300
    d.rounded_rectangle([bx, 96, W - PAD, 176], radius=18, fill=PANEL)
    d.text((bx + 20, 108), "PROTECT YOURSELF", font=f_label(14), fill=SOFT)
    tip = "Buy a Shield" + (f" · {_fmt(shield_price)} sobs" if shield_price else "")
    d.text((bx + 20, 130), tip, font=f_num(22), fill=INK)

    d.text((PAD, 196), "!buy shield   then   !use shield <seconds>", font=f_num(20), fill=AMBER)
    d.text((PAD, 224), "A shield blocks snitches & audits. Tap Dismiss to hide this.", font=f_reg(15), fill=DIM)

    img.putalpha(_round_mask((W, H), 28))
    return img


# ----------------------------------------------------------------------
# Stats card — !sob stats. Shows where YOUR sobs come from + costs/cooldowns.
# ----------------------------------------------------------------------
def stats_card(name: str, balance: int, earned: dict, spent: dict,
               rates: dict, cooldowns: dict) -> Image.Image:
    """
    earned: {'reactions':int,'snitch':int,'audit':int,'daily':int,'games':int}
    spent:  {'shop':int,'tax':int,'audits':int,'games':int}
    rates:  {'sob_value':int,'snitch_steal_pct':int,'audit_basic_pct':float,
             'audit_heist_pct':float,'audit_cap':int}
    cooldowns: {'audit_left':int,'audits_left':int}
    """
    W, H = 760, 580
    img, d = _base(W, H)
    PAD = 40

    # header
    d.text((PAD, 30), f"{name} — Stats", font=f_title(34), fill=INK)
    si = icon("sob", 34)
    if si: img.alpha_composite(si, (PAD, 80))
    d.text((PAD + 44, 78), f"{_fmt(balance)} sobs", font=f_num(30), fill=AMBER)

    # two columns: EARNED FROM / SPENT ON
    colL, colR = PAD, W // 2 + 10
    yTop = 142
    d.text((colL, yTop), "WHERE YOUR SOBS CAME FROM", font=f_label(15), fill=SOFT)
    d.text((colR, yTop), "WHAT YOU SPENT ON", font=f_label(15), fill=SOFT)

    def rows(items, x, y, positive):
        for lbl, val in items:
            d.text((x, y), lbl, font=f_reg(19), fill=DIM)
            vt = f"{_fmt(val)}"
            d.text((x + 250 - _text_w(d, vt, f_num(19)), y), vt, font=f_num(19),
                   fill=GREEN if positive else RED)
            y += 34
        return y

    earned_items = [
        ("Reactions", earned.get("reactions", 0)),
        ("Snitch steals", earned.get("snitch", 0)),
        ("Audit steals", earned.get("audit", 0)),
        ("Daily", earned.get("daily", 0)),
        ("Games", earned.get("games", 0)),
    ]
    spent_items = [
        ("Shop", spent.get("shop", 0)),
        ("Taxes", spent.get("tax", 0)),
        ("Lost to audits", spent.get("audits", 0)),
        ("Games", spent.get("games", 0)),
    ]
    rows(earned_items, colL, yTop + 32, positive=True)
    rows(spent_items, colR, yTop + 32, positive=False)

    # divider
    dy = 358
    d.line([(PAD, dy), (W - PAD, dy)], fill=PANEL, width=2)

    # "HOW EARNING WORKS" quick reference
    d.text((PAD, dy + 16), "HOW EARNING WORKS", font=f_label(15), fill=SOFT)
    ref = [
        f"Each reaction is worth ~{_fmt(rates.get('sob_value',1))} sobs",
        f"Snitch steals {rates.get('snitch_steal_pct',50)}% of wiped sobs",
        f"Audit Basic {int(rates.get('audit_basic_pct',0.03)*100)}% · Heist {int(rates.get('audit_heist_pct',0.08)*100)}% of a target",
    ]
    y = dy + 46
    for line in ref:
        d.ellipse([PAD + 2, y + 8, PAD + 12, y + 18], fill=SOFT)
        d.text((PAD + 26, y), line, font=f_reg(18), fill=INK)
        y += 32

    # your audit allowance pill
    by = H - 70
    d.rounded_rectangle([PAD, by, W - PAD, by + 50], radius=16, fill=PANEL)
    cap = rates.get("audit_cap", 0)
    left = cooldowns.get("audits_left", cap)
    cd = cooldowns.get("audit_left", 0)
    cd_txt = "ready now" if cd <= 0 else f"cooldown {_fmt_dur(cd)}"
    d.text((PAD + 18, by + 14), f"Your audits today: {left}/{cap} left · {cd_txt}",
           font=f_num(20), fill=INK)

    img.putalpha(_round_mask((W, H), 28))
    return img
