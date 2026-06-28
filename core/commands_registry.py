# core/commands_registry.py
"""
SINGLE SOURCE OF TRUTH for every command.

>>> When you add or change a command, update THIS file. <<<
Help, the category lists, and gating all read from here, so you never have to
hunt through multiple files again.

Each entry:
  name:     the command as typed (without prefix)
  cat:      category key (see CATEGORIES)
  desc:     one-line description
  usage:    how to call it (without prefix), or None to use just the name
  admin:    True if admin/owner-only (shown only to them)
  owner:    True if bot-owner-only
"""
from __future__ import annotations

# category key -> (emoji, label)  — emoji used only in buttons/headers, sparingly
CATEGORIES = {
    "sobs":    ("😭", "Sobs & Profile"),
    "profile": ("🎴", "Profile"),
    "shop":    ("🛒", "Shop"),
    "economy": ("😭", "Economy"),
    "admin":   ("🛡️", "Admin"),
    "info":    ("ℹ️", "Info"),
}

COMMANDS = [
    # ---- Sobs & Profile ----
    {"name": "sob", "cat": "sobs", "desc": "Your profile card", "usage": "sob"},
    {"name": "sob @user", "cat": "sobs", "desc": "Another member's profile card", "usage": "sob @user"},
    {"name": "sob lb", "cat": "sobs", "desc": "Server leaderboard", "usage": "sob lb"},
    {"name": "ss", "cat": "sobs", "desc": "Reply to a message to wipe its sobs (uses a token)", "usage": "ss"},

    # ---- Profile customization ----
    {"name": "sob set", "cat": "profile", "desc": "See your current background & color", "usage": "sob set"},
    {"name": "sob backgrounds", "cat": "profile", "desc": "List all backgrounds", "usage": "sob backgrounds"},
    {"name": "sob colors", "cat": "profile", "desc": "List all colors", "usage": "sob colors"},
    {"name": "sob set background", "cat": "profile", "desc": "Change your background", "usage": "sob set background <name>"},
    {"name": "sob set color", "cat": "profile", "desc": "Change your color", "usage": "sob set color <name>"},

    # ---- Shop ----
    {"name": "shop", "cat": "shop", "desc": "Browse & buy (category buttons)", "usage": "shop"},
    {"name": "daily", "cat": "shop", "desc": "Claim your daily sobs (streak bonus!)", "usage": "daily"},
    {"name": "buy", "cat": "shop", "desc": "Buy an item by name or key", "usage": "buy <item> [qty]"},
    {"name": "me", "cat": "shop", "desc": "Your items + active effects", "usage": "me"},
    {"name": "use", "cat": "shop", "desc": "Use an item", "usage": "use <item> [@user]"},

    # ---- Economy ----
    {"name": "rate", "cat": "economy", "desc": "Show this server's sob⇄$ rate", "usage": "rate"},
    {"name": "value", "cat": "economy", "desc": "What some sobs are worth in $", "usage": "value <sobs>"},
    {"name": "worth", "cat": "economy", "desc": "How many sobs a $ amount is", "usage": "worth <$>"},
    {"name": "economy", "cat": "economy", "desc": "Economy health card", "usage": "economy"},
    {"name": "rate set", "cat": "economy", "desc": "Set the exchange rate", "usage": "rate set <sobs>", "admin": True},
    {"name": "tax", "cat": "economy", "desc": "Show/set the shop burn tax", "usage": "tax [percent]", "admin": True},
    {"name": "multiplier", "cat": "economy", "desc": "Show/set the sob multiplier", "usage": "mult [number|auto]", "admin": True},

    # ---- Admin ----
    {"name": "admin profile", "cat": "admin", "desc": "Toggle image profile cards", "usage": "admin profile on|off", "admin": True},
    {"name": "admin givesob", "cat": "admin", "desc": "Give sobs to a user", "usage": "admin givesob @user <n>", "admin": True},
    {"name": "admin givetoken", "cat": "admin", "desc": "Give snitch tokens", "usage": "admin givetoken @user <n>", "admin": True},
    {"name": "admin reset", "cat": "admin", "desc": "Reset a user's sobs", "usage": "admin reset @user", "admin": True},
    {"name": "admin recount", "cat": "admin", "desc": "Recount all sobs", "usage": "admin recount", "admin": True},
    {"name": "admin threshold", "cat": "admin", "desc": "Set sobs-per-token", "usage": "admin threshold <n>", "admin": True},
    {"name": "admin emoji", "cat": "admin", "desc": "Manage accepted sob emojis", "usage": "admin emoji list|add|remove", "admin": True},
    {"name": "shop additem", "cat": "admin", "desc": "Add a server item (price in sobs or $)", "usage": "shop additem <key> <price|$X> <name>", "admin": True},
    {"name": "shop setstock", "cat": "admin", "desc": "Set item stock (-1 = unlimited)", "usage": "shop setstock <key> <n>", "admin": True},
    {"name": "shop removeitem", "cat": "admin", "desc": "Disable a server item", "usage": "shop removeitem <key>", "admin": True},
    {"name": "shop setchannel", "cat": "admin", "desc": "Where claims are posted", "usage": "shop setchannel #channel", "admin": True},
    {"name": "shop setrole", "cat": "admin", "desc": "Who gets pinged on a claim", "usage": "shop setrole @role", "admin": True},
    {"name": "shop boostmult", "cat": "admin", "desc": "Set the boost steal multiplier", "usage": "shop boostmult <n>", "admin": True},
    {"name": "disable", "cat": "admin", "desc": "Disable a category/command (optionally per-channel)", "usage": "disable <category|command> [#channel]", "admin": True},
    {"name": "enable", "cat": "admin", "desc": "Re-enable a category/command", "usage": "enable <category|command> [#channel]", "admin": True},
    {"name": "commandconfig", "cat": "admin", "desc": "See what's disabled where", "usage": "commandconfig", "admin": True},
    {"name": "perms", "cat": "admin", "desc": "View/grant role permissions", "usage": "perms [grant|revoke @role <perm>]", "admin": True},
    {"name": "announce", "cat": "admin", "desc": "Post an announcement", "usage": "announce #channel Title | Body", "admin": True},

    # ---- Info ----
    {"name": "help", "cat": "info", "desc": "This menu", "usage": "help"},
    {"name": "about", "cat": "info", "desc": "Bot info, version & latest updates", "usage": "about"},
    {"name": "version", "cat": "info", "desc": "Current version", "usage": "version"},
    {"name": "rate", "cat": "info", "desc": "Exchange rate", "usage": "rate"},  # cross-listed for discovery
]


def for_category(cat: str, *, is_admin: bool = False, is_owner: bool = False) -> list[dict]:
    out = []
    for c in COMMANDS:
        if c["cat"] != cat:
            continue
        if c.get("owner") and not is_owner:
            continue
        if c.get("admin") and not (is_admin or is_owner):
            continue
        out.append(c)
    return out


def visible_categories(is_admin: bool = False) -> list[str]:
    cats = ["sobs", "profile", "shop", "economy", "info"]
    if is_admin:
        cats.append("admin")
    return cats
