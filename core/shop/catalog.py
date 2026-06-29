# core/shop/catalog.py
"""
Shop catalog — built-in PvP items (Protection / Debuff / Buff).

Economy-safe by design:
- Effects are SHORT so people keep re-buying (the spending "circle").
- Steal/tax mechanics are TRANSFERS capped at the target's balance (no new sobs
  are minted, so they can't inflate the economy).
- Prices climb steeply so high-tier items are real sob sinks.

Each item:
  key, name, icon, category, price, duration (sec, 0 = instant),
  effect_key (what's written to active_effects),
  mechanic (machine-readable type the snitch/use logic checks),
  description.
"""
from __future__ import annotations

MIN = 60

DEFAULT_BOOST_MULTIPLIER = 2

BUILTIN_ITEMS: dict[str, dict] = {
    # ====================== PROTECTION ======================
    # Shield is now a STACKABLE per-second item: buy in bulk, choose how many
    # seconds to apply on use. Rich players need long protection -> buy more.
    "shield": {
        "key": "shield", "name": "Shield", "icon": "🛡️", "category": "protection",
        "price": 2, "duration": 1, "effect_key": "shield", "mechanic": "block_snitch",
        "stackable": True,
        "description": "1 second of snitch protection. Buy in bulk, then `!use shield <seconds>`.",
    },
    "guardian": {
        "key": "guardian", "name": "Guardian Angel", "icon": "😇", "category": "protection",
        "price": 2500, "duration": 0, "effect_key": "guardian", "mechanic": "block_charges",
        "charges": 5,
        "description": "Blocks the next 5 snitches against you (no time limit).",
    },
    "audit_ward": {
        "key": "audit_ward", "name": "Audit Ward", "icon": "🧾", "category": "protection",
        "price": 1500, "duration": 1800, "effect_key": "audit_ward", "mechanic": "block_audit",
        "description": "Blocks Basic Audits against you for 30 minutes.",
    },
    "reflect": {
        "key": "reflect", "name": "Reflect Shield", "icon": "🪞", "category": "protection",
        "price": 15000, "duration": 0, "effect_key": "reflect", "mechanic": "reflect_next",
        "charges": 1,
        "description": "The next snitch against you is reflected back at the attacker.",
    },

    # ====================== DEBUFF ======================
    "freeze": {
        "key": "freeze", "name": "Basic Freeze", "icon": "❄️", "category": "debuff",
        "price": 150, "duration": 5 * MIN, "effect_key": "freeze", "mechanic": "block_tokens",
        "description": "Stops a rival from using snitch tokens for 5 minutes.",
    },
    "freeze_deep": {
        "key": "freeze_deep", "name": "Deep Freeze", "icon": "🥶", "category": "debuff",
        "price": 500, "duration": 15 * MIN, "effect_key": "freeze", "mechanic": "block_tokens",
        "description": "Stops a rival from using snitch tokens for 15 minutes.",
    },
    "audit": {
        "key": "audit", "name": "Basic Audit", "icon": "💸", "category": "debuff",
        "price": 400, "duration": 0, "effect_key": "", "mechanic": "audit_basic",
        "description": "Steal 3% of a target's sobs (blockable by shields & wards, daily-capped).",
    },
    "heist": {
        "key": "heist", "name": "Grand Heist", "icon": "🏴‍☠️", "category": "debuff",
        "price": 16000, "duration": 0, "effect_key": "", "mechanic": "audit_heist",
        "description": "Steal 8% of a target's sobs. 20% chance to smash through their shield.",
    },
    "slow_curse": {
        "key": "slow_curse", "name": "Slow Curse", "icon": "🦥", "category": "debuff",
        "price": 2500, "duration": 20 * MIN, "effect_key": "slow", "mechanic": "halve_earnings",
        "description": "Target earns only 50% of normal sobs for 20 minutes.",
    },
    "marked": {
        "key": "marked", "name": "Marked Target", "icon": "🎯", "category": "debuff",
        "price": 5000, "duration": 30 * MIN, "effect_key": "marked", "mechanic": "mark_bounty",
        "bounty_pct": 0.20,
        "description": "For 30 min, anyone who snitches this player gains 20% more.",
    },
    "jail": {
        "key": "jail", "name": "Jail", "icon": "⛓️", "category": "debuff",
        "price": 20000, "duration": 30 * MIN, "effect_key": "jail", "mechanic": "lock_items",
        "description": "Target can't use any items for 30 minutes.",
    },

    # ====================== BUFF ======================
    "boost": {
        "key": "boost", "name": "Basic Boost", "icon": "⚡", "category": "buff",
        "price": 100, "duration": 5 * MIN, "effect_key": "boost", "mechanic": "steal_mult",
        "multiplier": 1.5,
        "description": "For 5 min, your snitches steal 1.5× the message's sobs from the target.",
    },
    "boost_adv": {
        "key": "boost_adv", "name": "Advanced Boost", "icon": "⚡", "category": "buff",
        "price": 350, "duration": 15 * MIN, "effect_key": "boost", "mechanic": "steal_mult",
        "multiplier": 2.0,
        "description": "For 15 min, your snitches steal 2× the message's sobs.",
    },
    "hunter": {
        "key": "hunter", "name": "Hunter's Blessing", "icon": "🏹", "category": "buff",
        "price": 750, "duration": 0, "effect_key": "hunter", "mechanic": "steal_mult_charges",
        "multiplier": 2.5, "charges": 10,
        "description": "Your next 10 snitches steal 2.5× (no time limit).",
    },
    "lucky": {
        "key": "lucky", "name": "Lucky Day", "icon": "🍀", "category": "buff",
        "price": 1200, "duration": 20 * MIN, "effect_key": "lucky", "mechanic": "earn_bonus",
        "bonus_pct": 0.50,
        "description": "All your sob earnings are +50% for 20 minutes.",
    },
    "king": {
        "key": "king", "name": "King's Decree", "icon": "👑", "category": "buff",
        "price": 25000, "duration": 10 * MIN, "effect_key": "king", "mechanic": "steal_mult_pierce",
        "multiplier": 3.0,
        "description": "For 10 min, your snitches steal 3× and ignore shields (except Reflect).",
    },
}

# Effects that target SOMEONE ELSE (used with !use <item> @target).
TARGETED_EFFECTS = {"freeze", "freeze_deep", "audit", "heist", "slow_curse", "marked", "jail"}

# Effects that are self-applied (used with !use <item>).
SELF_EFFECTS = {"shield", "guardian", "audit_ward", "reflect",
                "boost", "boost_adv", "hunter", "lucky", "king"}

# Mechanics whose advertised effect is actually enforced in code. Any built-in
# whose mechanic is NOT in this set is auto-disabled in the shop (see
# ShopRepo.get_catalog) so players can never buy something that does nothing.
# Every mechanic currently shipped is enforced; this guard keeps that honest if
# a new item is added before its logic exists.
ENFORCED_MECHANICS = {
    "block_snitch",       # shield (time-based)
    "block_charges",      # guardian (charge-based)
    "block_audit",        # audit_ward
    "reflect_next",       # reflect
    "block_tokens",       # freeze / deep freeze
    "audit_basic",        # basic audit
    "audit_heist",        # grand heist
    "halve_earnings",     # slow curse
    "mark_bounty",        # marked target
    "lock_items",         # jail
    "steal_mult",         # boost / advanced boost
    "steal_mult_charges", # hunter's blessing
    "earn_bonus",         # lucky day
    "steal_mult_pierce",  # king's decree
}

# Category display order + labels.
CATEGORY_ORDER = [
    ("protection", "🛡️ Protection"),
    ("debuff", "❄️ Debuff"),
    ("buff", "⚡ Buff"),
    ("server", "🎁 Server Items"),
]

# CATEGORIES dict (key -> (icon, label)) for embeds that group by category.
CATEGORIES = {
    "protection": ("🛡️", "Protection"),
    "debuff": ("❄️", "Debuff"),
    "buff": ("⚡", "Buff"),
    "server": ("🎁", "Server Items"),
}


def item_icon(key: str) -> str:
    """Icon for a built-in item or effect key; falls back to a gift box."""
    it = BUILTIN_ITEMS.get(key)
    if it:
        return it["icon"]
    # effect_key lookups (e.g. 'shield' from an active effect)
    for v in BUILTIN_ITEMS.values():
        if v.get("effect_key") == key:
            return v["icon"]
    return "🎁"
