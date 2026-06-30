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
    "games":   ("🎲", "Games"),
    "economy": ("😭", "Economy"),
    "admin":   ("🛡️", "Admin"),
    "info":    ("ℹ️", "Info"),
}

COMMANDS = [
    # ---- Sobs & Profile ----
    {"name": "sob", "cat": "sobs", "desc": "Your profile card", "usage": "sob"},
    {"name": "sob @user", "cat": "sobs", "desc": "Another member's profile card", "usage": "sob @user"},
    {"name": "sob lb", "cat": "sobs", "desc": "Server leaderboard", "usage": "sob lb"},
    {"name": "sob stats", "cat": "sobs", "desc": "Where your sobs come from + your audit allowance (picture)", "usage": "sob stats"},
    {"name": "sob tips", "cat": "sobs", "desc": "Turn the occasional shield reminder on/off for yourself", "usage": "sob tips on|off"},
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
    {"name": "use", "cat": "shop", "desc": "Use an item (shields: !use shield <seconds>)", "usage": "use <item> [amount] [@user]"},

    # ---- Economy ----
    {"name": "rate", "cat": "economy", "desc": "Show this server's sob⇄$ rate", "usage": "rate"},
    {"name": "value", "cat": "economy", "desc": "What some sobs are worth in $", "usage": "value <sobs>"},
    {"name": "worth", "cat": "economy", "desc": "How many sobs a $ amount is", "usage": "worth <$>"},
    {"name": "economy", "cat": "economy", "desc": "Economy health card", "usage": "economy"},
    {"name": "rate set", "cat": "economy", "desc": "Set the exchange rate", "usage": "rate set <sobs>", "admin": True},
    {"name": "tax", "cat": "economy", "desc": "Show/set the shop tax (feeds the treasury)", "usage": "tax [percent|auto]", "admin": True},
    {"name": "treasury", "cat": "economy", "desc": "Server tax pot + stats", "usage": "treasury", "admin": True},
    {"name": "treasury give", "cat": "economy", "desc": "Pay sobs from the treasury", "usage": "treasury give @user <amount>", "admin": True},
    {"name": "multiplier", "cat": "economy", "desc": "Show/set the sob multiplier", "usage": "mult [number|auto]", "admin": True},
    {"name": "rebalance", "cat": "economy", "desc": "Refresh shop prices to the current economy", "usage": "rebalance", "admin": True},

    # ---- Admin ----
    {"name": "admin profile", "cat": "admin", "desc": "Toggle image profile cards", "usage": "admin profile on|off", "admin": True},
    {"name": "admin givesob", "cat": "admin", "desc": "Give sobs to a user", "usage": "admin givesob @user <n>", "admin": True},
    {"name": "admin givetoken", "cat": "admin", "desc": "Give snitch tokens", "usage": "admin givetoken @user <n>", "admin": True},
    {"name": "admin reset", "cat": "admin", "desc": "Reset a user's sobs", "usage": "admin reset @user", "admin": True},
    {"name": "admin recount", "cat": "admin", "desc": "Recount all sobs", "usage": "admin recount", "admin": True},
    {"name": "admin threshold", "cat": "admin", "desc": "Set sobs-per-token", "usage": "admin threshold <n>", "admin": True},
    {"name": "admin emoji", "cat": "admin", "desc": "Manage accepted sob emojis", "usage": "admin emoji list|add|remove", "admin": True},
    {"name": "admin whoami", "cat": "admin", "desc": "Show your admin/owner status & perms", "usage": "admin whoami", "admin": True},
    {"name": "admin config", "cat": "admin", "desc": "This server's full sob config", "usage": "admin config", "admin": True},
    {"name": "admin stats", "cat": "admin", "desc": "Bot-wide stats (owner)", "usage": "admin stats", "owner": True},
    {"name": "admin servers", "cat": "admin", "desc": "List servers the bot is in (owner)", "usage": "admin servers", "owner": True},

    # ---- Admin: economy controls (disable / limit) ----
    {"name": "admin freeze", "cat": "admin", "desc": "Emergency: pause ALL earning/economy server-wide", "usage": "admin freeze on|off", "admin": True},
    {"name": "admin shop", "cat": "admin", "desc": "Open/close the WHOLE shop", "usage": "admin shop on|off", "admin": True},
    {"name": "admin item", "cat": "admin", "desc": "Disable/enable a shop item, or give/take items from a user", "usage": "admin item disable|enable|give|take ...", "admin": True},
    {"name": "admin category", "cat": "admin", "desc": "Disable/enable a whole shop category", "usage": "admin category disable|enable <name>", "admin": True},
    {"name": "admin auditcap", "cat": "admin", "desc": "Max audits one person can do per day", "usage": "admin auditcap <n>", "admin": True},
    {"name": "admin auditcd", "cat": "admin", "desc": "Cooldown between a person's audits (seconds)", "usage": "admin auditcd <seconds>", "admin": True},
    {"name": "admin protection", "cat": "admin", "desc": "View/override the protection price factor (auto-tuned)", "usage": "admin protection [0.5-1.2|auto]", "admin": True},
    {"name": "admin steal", "cat": "admin", "desc": "Turn !steal on/off for the server", "usage": "admin steal on|off", "admin": True},
    {"name": "admin steal config", "cat": "admin", "desc": "View/tune steal chance, caps, cooldowns", "usage": "admin steal config [chance]", "admin": True},
    {"name": "admin altblock", "cat": "admin", "desc": "Block/flag alt-farm reactions", "usage": "admin altblock on|off", "admin": True},
    {"name": "admin tips", "cat": "admin", "desc": "Shield reminders on/off for the whole server", "usage": "admin tips on|off", "admin": True},

    # ---- Admin: audit & investigation ----
    {"name": "admin audit", "cat": "admin", "desc": "Trace where a user's sobs came from + reconciliation", "usage": "admin audit @user [page]", "admin": True},
    {"name": "admin audit tx", "cat": "admin", "desc": "Show every entry in one transaction", "usage": "admin audit tx <id>", "admin": True},
    {"name": "admin suspicious", "cat": "admin", "desc": "Flag exploit-like behavior for a user", "usage": "admin suspicious @user", "admin": True},
    {"name": "admin weekly", "cat": "admin", "desc": "Weekly reaction farm-pair report", "usage": "admin weekly", "admin": True},
    {"name": "admin export", "cat": "admin", "desc": "Export ALL economy data (ledger, security, reconciliation)", "usage": "admin export", "admin": True},
    {"name": "admin auditexport", "cat": "admin", "desc": "Full JSON of one user for analysis", "usage": "admin auditexport @user", "admin": True},
    {"name": "admin import", "cat": "admin", "desc": "Import an economy export (owner)", "usage": "admin import", "owner": True},

    # ---- Admin: shop management ----
    {"name": "shop additem", "cat": "admin", "desc": "Add a server item (price in sobs or $)", "usage": "shop additem <key> <price|$X> <name>", "admin": True},
    {"name": "shop setstock", "cat": "admin", "desc": "Set item stock (-1 = unlimited)", "usage": "shop setstock <key> <n>", "admin": True},
    {"name": "shop removeitem", "cat": "admin", "desc": "Remove a custom server item", "usage": "shop removeitem <key>", "admin": True},
    {"name": "shop setchannel", "cat": "admin", "desc": "Where claims are posted", "usage": "shop setchannel #channel", "admin": True},
    {"name": "shop setrole", "cat": "admin", "desc": "Who gets pinged on a claim", "usage": "shop setrole @role", "admin": True},
    {"name": "shop boostmult", "cat": "admin", "desc": "Set the boost steal multiplier", "usage": "shop boostmult <n>", "admin": True},
    {"name": "disable", "cat": "admin", "desc": "Disable a category/command (optionally per-channel)", "usage": "disable <category|command> [#channel]", "admin": True},
    {"name": "enable", "cat": "admin", "desc": "Re-enable a category/command", "usage": "enable <category|command> [#channel]", "admin": True},
    {"name": "commandconfig", "cat": "admin", "desc": "See what's disabled where", "usage": "commandconfig", "admin": True},
    {"name": "perms", "cat": "admin", "desc": "View/grant role permissions", "usage": "perms [grant|revoke @role <perm>]", "admin": True},
    {"name": "announce", "cat": "admin", "desc": "Post an announcement", "usage": "announce #channel Title | Body", "admin": True},

    # ---- Games ----
    {"name": "roulette", "cat": "games", "desc": "Russian Roulette — wager sobs 50/50", "usage": "roulette @user <amount>"},
    {"name": "roulettestats", "cat": "games", "desc": "See roulette match history & odds", "usage": "rrstats"},
    {"name": "steal", "cat": "games", "desc": "Risky gamble to steal sobs (~45% odds, small + capped)", "usage": "steal @user [lockpick]"},
    {"name": "steal stats", "cat": "games", "desc": "Your steal record (profit, attempts, immunity)", "usage": "steal stats"},
    {"name": "sobship", "cat": "games", "desc": "Fun love-meter between two people (no sobs involved)", "usage": "sobship @user [@user2]"},

    # ---- Info ----
    {"name": "help", "cat": "info", "desc": "This menu", "usage": "help"},
    {"name": "guide", "cat": "info", "desc": "How the bot works (for newcomers)", "usage": "guide"},
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
    cats = ["sobs", "profile", "shop", "games", "economy", "info"]
    if is_admin:
        cats.append("admin")
    return cats
