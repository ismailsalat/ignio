# bot/cogs/user_settings.py
from __future__ import annotations

import discord
from discord.ext import commands

from bot.core.timecore import now_utc_ts


def _onoff(s: str) -> str:
    return "ON" if s == "1" else "OFF"


class UserSettingsCog(commands.Cog):
    """
    User-facing settings (per guild DB file).
    Stores overrides only in user_settings table.
    Defaults come from Settings in config.py via repos.get_effective_config().
    """

    def __init__(self, bot: commands.Bot, settings, repos):
        self.bot = bot
        self.settings = settings
        self.repos = repos

    async def _set_user_key(self, guild_id: int, user_id: int, key: str, value01: str, now_ts: int) -> None:
        conn = await self.repos.raw_conn(guild_id)
        await conn.execute(
            """
            INSERT INTO user_settings (user_id, key, value, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(user_id, key)
            DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at
            """,
            (int(user_id), str(key), str(value01), int(now_ts)),
        )
        await conn.commit()

    async def _get_user_key(self, guild_id: int, user_id: int, key: str) -> str | None:
        conn = await self.repos.raw_conn(guild_id)
        cur = await conn.execute(
            "SELECT value FROM user_settings WHERE user_id=? AND key=?",
            (int(user_id), str(key)),
        )
        row = await cur.fetchone()
        return None if not row else str(row[0])

    async def _get_user_bool_effective(self, gid: int, uid: int, key: str, default_bool: bool) -> bool:
        v = await self._get_user_key(gid, uid, key)
        if v is None:
            return bool(default_bool)
        return v == "1"

    def _parse_mode(self, mode: str) -> str:
        return (mode or "").strip().lower()

    # ------------------ SHOW ALL ------------------

    @commands.command(name="settings")
    @commands.guild_only()
    async def settings_cmd(self, ctx: commands.Context):
        """
        Shows your effective user settings (defaults + your overrides).
        """
        gid = ctx.guild.id
        uid = ctx.author.id

        cfg = await self.repos.get_effective_config(gid, self.settings)

        # defaults from config (Settings) via effective config
        default_private = bool(cfg.get("privacy_default_private", False))
        default_dm = bool(cfg.get("dm_reminders_enabled", True))
        default_end = bool(cfg.get("dm_streak_end_enabled", True))
        default_ice = bool(cfg.get("dm_streak_end_ice_enabled", True))
        default_restore = bool(cfg.get("dm_streak_end_restore_enabled", True))

        # effective user values (override if exists)
        privacy = await self._get_user_bool_effective(gid, uid, "privacy_private", default_private)
        dm = await self._get_user_bool_effective(gid, uid, "dm_reminders_enabled", default_dm)
        dm_end = await self._get_user_bool_effective(gid, uid, "dm_streak_end_enabled", default_end)
        dm_restore = await self._get_user_bool_effective(gid, uid, "dm_streak_end_restore_enabled", default_restore)
        dm_ice = await self._get_user_bool_effective(gid, uid, "dm_streak_end_ice_enabled", default_ice)

        msg = (
            "**Your Ignio Settings**\n"
            f"- Privacy: `{'ON' if privacy else 'OFF'}`\n"
            f"- DM reminders: `{'ON' if dm else 'OFF'}`\n"
            f"- DM streak ended: `{'ON' if dm_end else 'OFF'}`\n"
            f"- DM restore msg (white fire): `{'ON' if dm_restore else 'OFF'}`\n"
            f"- DM ice msg: `{'ON' if dm_ice else 'OFF'}`\n"
            "\n"
            "Change:\n"
            "- `!privacy on/off`\n"
            "- `!dm on/off`\n"
            "- `!dmend on/off`\n"
            "- `!dmice on/off`\n"
        )
        await ctx.reply(msg)

    # ------------------ PRIVACY ------------------

    @commands.command(name="privacy")
    @commands.guild_only()
    async def privacy(self, ctx: commands.Context, mode: str = ""):
        """
        Usage:
          !privacy
          !privacy on
          !privacy off
        """
        gid = ctx.guild.id
        uid = ctx.author.id
        now = now_utc_ts()

        cfg = await self.repos.get_effective_config(gid, self.settings)
        default_private = bool(cfg.get("privacy_default_private", False))

        mode = self._parse_mode(mode)
        if mode in ("", "status", "show"):
            v = await self._get_user_key(gid, uid, "privacy_private")
            eff = default_private if v is None else (v == "1")
            return await ctx.reply(f"🔒 Privacy is **{_onoff('1' if eff else '0')}** for you.")

        if mode in ("on", "enable", "1", "true"):
            await self._set_user_key(gid, uid, "privacy_private", "1", now)
            return await ctx.reply("🔒 Privacy **ON**. If either duo member has privacy on, the duo is private.")

        if mode in ("off", "disable", "0", "false"):
            await self._set_user_key(gid, uid, "privacy_private", "0", now)
            return await ctx.reply("✅ Privacy **OFF**. Your duos can show normally.")

        await ctx.reply("Use: `!privacy` | `!privacy on` | `!privacy off`")

    # ------------------ DM REMINDERS ------------------

    @commands.command(name="dm")
    @commands.guild_only()
    async def dm_reminders(self, ctx: commands.Context, mode: str = ""):
        """
        Usage:
          !dm
          !dm on
          !dm off
        Toggles DM reminders (before day closes).
        """
        gid = ctx.guild.id
        uid = ctx.author.id
        now = now_utc_ts()

        cfg = await self.repos.get_effective_config(gid, self.settings)
        default_dm = bool(cfg.get("dm_reminders_enabled", True))

        mode = self._parse_mode(mode)
        if mode in ("", "status", "show"):
            v = await self._get_user_key(gid, uid, "dm_reminders_enabled")
            eff = default_dm if v is None else (v == "1")
            return await ctx.reply(f"📩 DM reminders are **{_onoff('1' if eff else '0')}** for you.")

        if mode in ("on", "enable", "1", "true"):
            await self._set_user_key(gid, uid, "dm_reminders_enabled", "1", now)
            return await ctx.reply("📩 DM reminders **ON**.")

        if mode in ("off", "disable", "0", "false"):
            await self._set_user_key(gid, uid, "dm_reminders_enabled", "0", now)
            return await ctx.reply("📩 DM reminders **OFF**.")

        await ctx.reply("Use: `!dm` | `!dm on` | `!dm off`")

    # ------------------ DM STREAK END ------------------

    @commands.command(name="dmend")
    @commands.guild_only()
    async def dm_end(self, ctx: commands.Context, mode: str = ""):
        """
        Usage:
          !dmend
          !dmend on
          !dmend off
        Toggles DM message when a streak ends.
        """
        gid = ctx.guild.id
        uid = ctx.author.id
        now = now_utc_ts()

        cfg = await self.repos.get_effective_config(gid, self.settings)
        default_end = bool(cfg.get("dm_streak_end_enabled", True))

        mode = self._parse_mode(mode)
        if mode in ("", "status", "show"):
            v = await self._get_user_key(gid, uid, "dm_streak_end_enabled")
            eff = default_end if v is None else (v == "1")
            return await ctx.reply(f"⚠️ DM streak end is **{_onoff('1' if eff else '0')}** for you.")

        if mode in ("on", "enable", "1", "true"):
            await self._set_user_key(gid, uid, "dm_streak_end_enabled", "1", now)
            return await ctx.reply("⚠️ DM streak end **ON**.")

        if mode in ("off", "disable", "0", "false"):
            await self._set_user_key(gid, uid, "dm_streak_end_enabled", "0", now)
            return await ctx.reply("⚠️ DM streak end **OFF**.")

        await ctx.reply("Use: `!dmend` | `!dmend on` | `!dmend off`")

    @commands.command(name="dmice")
    @commands.guild_only()
    async def dm_ice(self, ctx: commands.Context, mode: str = ""):
        """
        Usage:
          !dmice
          !dmice on
          !dmice off
        Toggles the "ice" DM after restore window is over.
        """
        gid = ctx.guild.id
        uid = ctx.author.id
        now = now_utc_ts()

        cfg = await self.repos.get_effective_config(gid, self.settings)
        default_ice = bool(cfg.get("dm_streak_end_ice_enabled", True))

        mode = self._parse_mode(mode)
        if mode in ("", "status", "show"):
            v = await self._get_user_key(gid, uid, "dm_streak_end_ice_enabled")
            eff = default_ice if v is None else (v == "1")
            return await ctx.reply(f"🧊 DM ice msg is **{_onoff('1' if eff else '0')}** for you.")

        if mode in ("on", "enable", "1", "true"):
            await self._set_user_key(gid, uid, "dm_streak_end_ice_enabled", "1", now)
            return await ctx.reply("🧊 DM ice msg **ON**.")

        if mode in ("off", "disable", "0", "false"):
            await self._set_user_key(gid, uid, "dm_streak_end_ice_enabled", "0", now)
            return await ctx.reply("🧊 DM ice msg **OFF**.")

        await ctx.reply("Use: `!dmice` | `!dmice on` | `!dmice off`")
