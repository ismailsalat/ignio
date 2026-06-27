# core/profile/cog.py
"""
Profile card system for !sob.

- build_profile_card(): turns a user's real sob stats into a PNG card.
- Free preset backgrounds for everyone; other wallpapers are owner-only.
- Per-user settings (background, color) stored in guild_settings (no migration).
- Owner kill-switch (profile_enabled) so the whole thing can fall back to the
  old embed instantly if a bug shows up.
- The OWNER gets a 'dev' badge; nobody else has badges yet.
"""
from __future__ import annotations

import io
import os

import discord

from core.profile import render

# Backgrounds everyone may use.
FREE_BACKGROUNDS = {"sunset", "lowpoly", "cloud", "amber", "midnight", "sky"}
# Colors everyone may use.
FREE_COLORS = {"white", "amber"}

DEFAULT_BACKGROUND = "midnight"
DEFAULT_COLOR = "amber"

WALLPAPER_DIR = os.path.join(os.path.dirname(__file__), "wallpapers")


def _all_wallpapers() -> set[str]:
    out = set()
    if os.path.isdir(WALLPAPER_DIR):
        for f in os.listdir(WALLPAPER_DIR):
            n, ext = os.path.splitext(f)
            if ext.lower() in (".png", ".jpg", ".jpeg", ".webp"):
                out.add(n.lower())   # lowercase so 'Japan.png' matches input 'japan'
    return out


class ProfileService:
    """Holds the logic; the SobCog calls into this."""

    def __init__(self, bot, settings, sob_repo):
        self.bot = bot
        self.settings = settings
        self.sob_repo = sob_repo

    # ---- owner / kill-switch -----------------------------------------

    def _is_owner(self, user_id: int) -> bool:
        return user_id in set(getattr(self.settings, "owner_ids", ()) or ())

    async def profile_enabled(self, guild_id: int) -> bool:
        """Owner kill-switch. Default ON; '0' turns it off (fall back to embed)."""
        raw = await self.sob_repo.get_guild_setting(guild_id, "profile_enabled")
        return raw != "0"

    async def set_profile_enabled(self, guild_id: int, on: bool) -> None:
        await self.sob_repo.set_guild_setting(guild_id, "profile_enabled", "1" if on else "0")

    # ---- per-user settings -------------------------------------------

    async def get_user_background(self, guild_id: int, user_id: int) -> str:
        raw = await self.sob_repo.get_guild_setting(guild_id, f"profile:bg:{user_id}")
        return raw or DEFAULT_BACKGROUND

    async def get_user_color(self, guild_id: int, user_id: int) -> str:
        raw = await self.sob_repo.get_guild_setting(guild_id, f"profile:color:{user_id}")
        return raw or DEFAULT_COLOR

    async def set_user_background(self, guild_id: int, user_id: int, bg: str) -> tuple[bool, str]:
        bg = bg.lower().strip()
        allowed = bg in FREE_BACKGROUNDS or (self._is_owner(user_id) and bg in _all_wallpapers())
        if not allowed:
            return False, "not_allowed"
        await self.sob_repo.set_guild_setting(guild_id, f"profile:bg:{user_id}", bg)
        return True, bg

    async def set_user_color(self, guild_id: int, user_id: int, color: str) -> tuple[bool, str]:
        color = color.lower().strip()
        if color not in FREE_COLORS:
            return False, "not_allowed"
        await self.sob_repo.set_guild_setting(guild_id, f"profile:color:{user_id}", color)
        return True, color

    # ---- card building ------------------------------------------------

    async def _fetch_avatar(self, member) -> "discord.Image | None":
        try:
            asset = member.display_avatar.replace(size=256, static_format="png")
            data = await asset.read()
            from PIL import Image
            return Image.open(io.BytesIO(data)).convert("RGBA")
        except Exception:
            return None

    async def build_profile_card(self, guild, member) -> discord.File | None:
        """Return a discord.File of the card, or None if anything fails
        (caller then falls back to the embed)."""
        try:
            gid, uid = guild.id, member.id
            stats = await self.sob_repo.get_user_stats(gid, uid)
            rank_alltime = await self.sob_repo.get_user_alltime_rank(gid, uid)
            snitch_row = await self.sob_repo.get_snitch_row(gid, uid)
            threshold = await self.sob_repo.get_snitch_threshold(gid)

            sobs_at_last = snitch_row["sobs_at_last_grant"] if snitch_row else 0
            tokens = 1 if (snitch_row and snitch_row["token_available"] == 1) else 0
            into = max(0, stats["sobs_alltime"] - sobs_at_last)

            badges = ["dev"] if self._is_owner(uid) else []

            card_stats = {
                "name": member.display_name,
                "handle": member.name,
                "rank": rank_alltime if stats["sobs_alltime"] > 0 else "—",
                "sobs_today": stats["sobs_today"],
                "sobs_week": stats["sobs_week"],
                "sobs_alltime": stats["sobs_alltime"],
                "tokens": tokens,
                "next_threshold": threshold,
                "sobs_into_threshold": min(into, threshold),
                "badges": badges,
                "theme": await self.get_user_color(gid, uid),
            }

            avatar = await self._fetch_avatar(member)
            wallpaper = await self.get_user_background(gid, uid)

            img = render.make_card(card_stats, avatar_img=avatar, wallpaper=wallpaper)
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            buf.seek(0)
            return discord.File(buf, filename="sob_profile.png")
        except Exception as e:
            print(f"[Ignio][Profile] card build failed, falling back to embed: {e}")
            return None
