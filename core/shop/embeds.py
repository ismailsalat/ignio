# core/shop/embeds.py
from __future__ import annotations

import time

import discord

from core.shop.catalog import CATEGORIES, item_icon

ACCENT = 0xF0B132


def _fmt_left(expires_at: int) -> str:
    if expires_at <= 0:
        return "until used"
    remaining = expires_at - int(time.time())
    if remaining <= 0:
        return "expired"
    h = remaining // 3600
    m = (remaining % 3600) // 60
    if h > 0:
        return f"{h}h {m}m left"
    return f"{m}m left"


def shop_embed(guild_name: str, catalog: list[dict], balance: int) -> discord.Embed:
    e = discord.Embed(title="🛒 Sob Shop", color=ACCENT)
    e.description = f"Your balance: **{balance}** sobs\nBuy with `!shop buy <item>` · use with `!use <item>`"

    # group by category, in CATEGORIES order
    for cat_key, (cat_icon, cat_label) in CATEGORIES.items():
        items = [it for it in catalog if it["category"] == cat_key and it["enabled"]]
        if not items:
            if cat_key == "server":
                e.add_field(
                    name=f"{cat_icon} {cat_label}",
                    value="*Server owners can add rewards here.*",
                    inline=False,
                )
            continue
        lines = []
        for it in items:
            stock = it.get("stock", -1)
            stock_txt = "" if stock is None or stock < 0 else f" · stock {stock}"
            lines.append(
                f"{it['icon']} **{it['name']}** — `{it['price']}` sobs{stock_txt}\n"
                f"⤷ {it['description']}"
            )
        e.add_field(name=f"{cat_icon} {cat_label}", value="\n".join(lines), inline=False)

    e.set_footer(text="Spending sobs lowers your leaderboard score — choose wisely.")
    return e


def inventory_embed(member: discord.Member, inventory: dict[str, int], catalog: list[dict]) -> discord.Embed:
    e = discord.Embed(title="🎒 Your Inventory", color=ACCENT, description=member.mention)
    name_by_key = {it["key"]: it for it in catalog}
    if not inventory:
        e.add_field(name="Empty", value="Visit `!shop` to buy items.", inline=False)
        return e
    lines = []
    for key, qty in inventory.items():
        it = name_by_key.get(key, {"icon": item_icon(key), "name": key})
        lines.append(f"{it['icon']} **{it['name']}** ×{qty}")
    e.add_field(name="Items held", value="\n".join(lines), inline=False)
    e.set_footer(text="Use an item with !use <item>")
    return e


def effects_embed(member: discord.Member, effects: list[dict]) -> discord.Embed:
    e = discord.Embed(title="✨ Active Effects", color=ACCENT, description=member.mention)
    if not effects:
        e.add_field(name="None", value="No buffs or debuffs active.", inline=False)
        return e
    lines = []
    for eff in effects:
        icon = item_icon(eff["effect_key"])
        lines.append(f"{icon} **{eff['effect_key'].title()}** · {_fmt_left(eff['expires_at'])}")
    e.add_field(name="Effects", value="\n".join(lines), inline=False)
    return e


def buy_success_embed(member: discord.Member, item: dict, qty: int, new_balance: int) -> discord.Embed:
    e = discord.Embed(title="✅ Purchased", color=ACCENT)
    e.add_field(name="Item", value=f"{item['icon']} {item['name']} ×{qty}", inline=True)
    charged = item.get("_charged", item["price"] * qty)
    tax = item.get("_tax", 0)
    if tax > 0:
        base = item["price"] * qty
        e.add_field(name="Cost", value=f"`{charged}` sobs\n({base} + {tax} tax)", inline=True)
    else:
        e.add_field(name="Cost", value=f"`{charged}` sobs", inline=True)
    e.add_field(name="Balance", value=f"`{new_balance}` sobs", inline=True)
    e.set_footer(text="It's in your inventory — use it with !use")
    return e


def category_embed(cat_key: str, items: list[dict]) -> discord.Embed:
    icon, label = CATEGORIES.get(cat_key, ("📦", cat_key.title()))
    e = discord.Embed(title=f"{icon} {label}", color=ACCENT)
    if not items:
        e.description = "Nothing here yet."
        return e
    lines = []
    for it in items:
        stock = it.get("stock", -1)
        stock_txt = "" if stock is None or stock < 0 else f" · stock {stock}"
        lines.append(f"{it['icon']} **{it['name']}** — `{it['price']}` sobs{stock_txt}\n⤷ {it['description']}")
    e.description = "\n\n".join(lines)
    e.set_footer(text="Tap a button below to buy · ◀️ Back for categories")
    return e


def error_embed(desc: str) -> discord.Embed:
    return discord.Embed(title="⚠️ Error", description=desc, color=ACCENT)


def my_stuff_embed(member: discord.Member, inventory: dict[str, int], effects: list[dict], catalog: list[dict]) -> discord.Embed:
    e = discord.Embed(title="🎒 Your Stuff", color=ACCENT, description=member.mention)
    name_by_key = {it["key"]: it for it in catalog}

    if inventory:
        lines = []
        for key, qty in inventory.items():
            it = name_by_key.get(key, {"icon": item_icon(key), "name": key})
            lines.append(f"{it['icon']} **{it['name']}** ×{qty}")
        e.add_field(name="Inventory", value="\n".join(lines), inline=False)
    else:
        e.add_field(name="Inventory", value="Empty — visit `!shop`.", inline=False)

    if effects:
        elines = []
        for eff in effects:
            icon = item_icon(eff["effect_key"])
            elines.append(f"{icon} **{eff['effect_key'].title()}** · {_fmt_left(eff['expires_at'])}")
        e.add_field(name="Active effects", value="\n".join(elines), inline=False)
    else:
        e.add_field(name="Active effects", value="None right now.", inline=False)

    e.set_footer(text="Tap a button to use an item, or !use <item>")
    return e


def used_embed(title: str, desc: str) -> discord.Embed:
    return discord.Embed(title=f"✅ {title}", description=desc, color=ACCENT)
