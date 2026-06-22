# core/shop/catalog.py
"""
Built-in shop catalog. Each category ships with one basic time-based item.
Server owners/admins add their own products to the "Server Items" category
via commands (stored in the shop_items table).

Effects are time-based for v1 (30 minutes). Held in inventory after purchase,
then activated with !use.
"""
from __future__ import annotations

# Category -> (icon, label) for grouping in the shop embed, in display order.
CATEGORIES: dict[str, tuple[str, str]] = {
    "protection": ("🛡️", "Protection"),
    "debuff": ("❄️", "Debuff"),
    "buff": ("⚡", "Buff"),
    "server": ("🎁", "Server Items"),
}

# How long each basic effect lasts, in seconds (30 minutes).
BASIC_DURATION_SECONDS = 30 * 60

# Default boost multiplier (sobs the snitcher gains = sobs wiped * this).
# Per-server overridable via the 'boost_multiplier' guild setting.
DEFAULT_BOOST_MULTIPLIER = 2

# Built-in items. price is in sobs (spent from the user's sob count).
# effect_key is what gets written to active_effects when used.
BUILTIN_ITEMS: dict[str, dict] = {
    "shield": {
        "key": "shield",
        "name": "Basic Shield",
        "icon": "🛡️",
        "category": "protection",
        "price": 50,
        "duration": BASIC_DURATION_SECONDS,
        "effect_key": "shield",
        "description": "Protects you from snitches for 30 minutes.",
    },
    "freeze": {
        "key": "freeze",
        "name": "Basic Freeze",
        "icon": "❄️",
        "category": "debuff",
        "price": 75,
        "duration": BASIC_DURATION_SECONDS,
        "effect_key": "freeze",
        "description": "Stops a rival from using snitch tokens for 30 minutes.",
    },
    "boost": {
        "key": "boost",
        "name": "Basic Boost",
        "icon": "⚡",
        "category": "buff",
        "price": 40,
        "duration": BASIC_DURATION_SECONDS,
        "effect_key": "boost",
        "multiplier": 1.5,  # default; overridable per-server via guild setting
        "description": "For 30 min, your snitches drain 1.5× the message's sobs from the target — and you steal them.",
    },
}

# Effects that target SOMEONE ELSE (used with !use <item> @target).
TARGETED_EFFECTS = {"freeze"}

# Effects that are self-applied (used with !use <item>).
SELF_EFFECTS = {"shield", "boost"}


DEFAULT_BOOST_MULTIPLIER = 1.5


def item_icon(item_key: str) -> str:
    it = BUILTIN_ITEMS.get(item_key)
    return it["icon"] if it else "📦"


def effect_for_item(item_key: str) -> str | None:
    it = BUILTIN_ITEMS.get(item_key)
    return it["effect_key"] if it else None
