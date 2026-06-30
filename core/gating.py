# core/gating.py
"""
Per-channel command gating, organized by category.

Admins can disable a whole CATEGORY or a single COMMAND, either server-wide
or in a specific channel. Stored in guild_settings (no migration):

    gate:cat:<category>             -> "1"   (category disabled server-wide)
    gate:cat:<category>:<chan_id>   -> "1"   (category disabled in one channel)
    gate:cmd:<command>              -> "1"   (command disabled server-wide)
    gate:cmd:<command>:<chan_id>    -> "1"   (command disabled in one channel)

Admins and the bot owner always bypass gating (so they can't lock themselves
out). The 'admin' category can never be disabled.
"""
from __future__ import annotations

# Which top-level command belongs to which category.
# (key = the root command name as registered in discord.py)
COMMAND_CATEGORY: dict[str, str] = {
    # Sobs
    "sob": "sobs",
    "ss": "sobs",
    # Shop
    "shop": "shop",
    "buy": "shop",
    "use": "shop",
    "me": "shop",
    "daily": "shop",
    "roulette": "games",
    "rr": "games",
    "roulettestats": "games",
    "steal": "games",
    "sobship": "games",
    # Profile (the !sob set lives under sob, but the card itself is 'sobs')
    # Admin / config (never disablable)
    "admin": "admin",
    "perms": "admin",
    "announce": "admin",
    "rate": "admin",
    "economy": "admin",
    "rebalance": "admin",
    "tax": "admin",
    "multiplier": "admin",
    "treasury": "admin",
}

CATEGORIES = ("sobs", "shop", "profile", "games", "admin")
PROTECTED_CATEGORIES = {"admin"}  # never disablable


def category_of(command_name: str) -> str:
    return COMMAND_CATEGORY.get(command_name, "other")


def _is_admin(member, settings) -> bool:
    owner_ids = set(getattr(settings, "owner_ids", ()) or ())
    if member.id in owner_ids:
        return True
    perms = getattr(member, "guild_permissions", None)
    return bool(perms and (perms.administrator or perms.manage_guild))


class Gating:
    def __init__(self, sob_repo):
        self.repo = sob_repo

    # ---- rule storage ----------------------------------------------------

    async def _on(self, guild_id, key) -> bool:
        return (await self.repo.get_guild_setting(guild_id, key)) == "1"

    async def disable_category(self, guild_id, category, channel_id=None):
        key = f"gate:cat:{category}" + (f":{channel_id}" if channel_id else "")
        await self.repo.set_guild_setting(guild_id, key, "1")

    async def enable_category(self, guild_id, category, channel_id=None):
        key = f"gate:cat:{category}" + (f":{channel_id}" if channel_id else "")
        await self.repo.set_guild_setting(guild_id, key, "0")

    async def disable_command(self, guild_id, command, channel_id=None):
        key = f"gate:cmd:{command}" + (f":{channel_id}" if channel_id else "")
        await self.repo.set_guild_setting(guild_id, key, "1")

    async def enable_command(self, guild_id, command, channel_id=None):
        key = f"gate:cmd:{command}" + (f":{channel_id}" if channel_id else "")
        await self.repo.set_guild_setting(guild_id, key, "0")

    # ---- the check -------------------------------------------------------

    async def is_blocked(self, guild_id, channel_id, command_name) -> bool:
        """True if this command is disabled here (server-wide or this channel)."""
        cat = category_of(command_name)
        if cat in PROTECTED_CATEGORIES:
            return False
        # command-level, channel then server-wide
        if await self._on(guild_id, f"gate:cmd:{command_name}:{channel_id}"):
            return True
        if await self._on(guild_id, f"gate:cmd:{command_name}"):
            return True
        # category-level, channel then server-wide
        if await self._on(guild_id, f"gate:cat:{cat}:{channel_id}"):
            return True
        if await self._on(guild_id, f"gate:cat:{cat}"):
            return True
        return False

    async def list_rules(self, guild_id) -> list[dict]:
        """All active disable rules, including per-channel, for the config panel.
        Returns list of {scope, name, channel_id} dicts."""
        db = await self.repo._db()
        rows = await db.fetchall(
            "SELECT key, value FROM guild_settings WHERE guild_id = ? AND key LIKE 'gate:%'",
            (guild_id,),
        )
        out = []
        for row in rows:
            key, value = row["key"], row["value"]
            if value != "1":
                continue
            parts = key.split(":")  # gate:cat:<name>[:chan]  or gate:cmd:<name>[:chan]
            if len(parts) < 3:
                continue
            scope = "category" if parts[1] == "cat" else "command"
            name = parts[2]
            channel_id = int(parts[3]) if len(parts) >= 4 and parts[3].isdigit() else None
            out.append({"scope": scope, "name": name, "channel_id": channel_id})
        return out
