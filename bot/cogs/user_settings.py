# bot/cogs/user_settings.py
from __future__ import annotations

import discord
from discord.ext import commands

from bot.core.timecore import now_utc_ts
from bot.ui.help_embeds import user_settings_help_embed, user_settings_status_embed


def _onoff01(s: str) -> str:
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

    # ---------------- internal db helpers ----------------

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

    async def _get_defaults(self, gid: int) -> dict:
        cfg = await self.repos.get_effective_config(gid, self.settings)
        return {
            "privacy_default_private": bool(cfg.get("privacy_default_private", False)),
            "dm_reminders_enabled": bool(cfg.get("dm_reminders_enabled", True)),
            "dm_streak_end_enabled": bool(cfg.get("dm_streak_end_enabled", True)),
            "dm_streak_end_ice_enabled": bool(cfg.get("dm_streak_end_ice_enabled", True)),
            "dm_streak_end_restore_enabled": bool(cfg.get("dm_streak_end_restore_enabled", True)),
        }

    async def _show_settings_embed(self, ctx: commands.Context):
        gid = ctx.guild.id
        uid = ctx.author.id

        defaults = await self._get_defaults(gid)

        privacy = await self._get_user_bool_effective(gid, uid, "privacy_private", defaults["privacy_default_private"])
        dm = await self._get_user_bool_effective(gid, uid, "dm_reminders_enabled", defaults["dm_reminders_enabled"])

        # "lost alerts" is the same underlying key as dm_streak_end_enabled (legacy dmend)
        dm_lost = await self._get_user_bool_effective(gid, uid, "dm_streak_end_enabled", defaults["dm_streak_end_enabled"])

        dm_restore = await self._get_user_bool_effective(
            gid, uid, "dm_streak_end_restore_enabled", defaults["dm_streak_end_restore_enabled"]
        )
        dm_ice = await self._get_user_bool_effective(gid, uid, "dm_streak_end_ice_enabled", defaults["dm_streak_end_ice_enabled"])

        return await ctx.reply(
            embed=user_settings_status_embed(
                ctx,
                privacy=privacy,
                dm=dm,
                dm_lost=dm_lost,
                dm_restore=dm_restore,
                dm_ice=dm_ice,
            )
        )

    async def _toggle_bool(
        self,
        ctx: commands.Context,
        *,
        key: str,
        default_bool: bool,
        mode: str,
        label_onoff: str,
        on_msg: str,
        off_msg: str,
        status_msg_prefix: str,
    ):
        gid = ctx.guild.id
        uid = ctx.author.id
        now = now_utc_ts()
        mode = self._parse_mode(mode)

        if mode in ("", "status", "show"):
            v = await self._get_user_key(gid, uid, key)
            eff = default_bool if v is None else (v == "1")
            return await ctx.reply(f"{status_msg_prefix} **{_onoff01('1' if eff else '0')}** for you.")

        if mode in ("on", "enable", "1", "true"):
            await self._set_user_key(gid, uid, key, "1", now)
            return await ctx.reply(on_msg)

        if mode in ("off", "disable", "0", "false"):
            await self._set_user_key(gid, uid, key, "0", now)
            return await ctx.reply(off_msg)

        # invalid -> help embed
        return await ctx.reply(embed=user_settings_help_embed(ctx))

    # ============================================================
    # ✅ New hub command (streak-style)
    # ============================================================

    @commands.group(name="settings", invoke_without_command=True)
    @commands.guild_only()
    async def settings_group(self, ctx: commands.Context):
        # `!settings` -> show status embed
        return await self._show_settings_embed(ctx)

    @settings_group.command(name="help")
    @commands.guild_only()
    async def settings_help(self, ctx: commands.Context):
        return await ctx.reply(embed=user_settings_help_embed(ctx))

    @settings_group.command(name="privacy")
    @commands.guild_only()
    async def settings_privacy(self, ctx: commands.Context, mode: str = ""):
        gid = ctx.guild.id
        defaults = await self._get_defaults(gid)
        return await self._toggle_bool(
            ctx,
            key="privacy_private",
            default_bool=defaults["privacy_default_private"],
            mode=mode,
            label_onoff="🔒 Privacy",
            status_msg_prefix="🔒 Privacy is",
            on_msg="🔒 Privacy **ON**. Your duos will be private if either person enables privacy.",
            off_msg="✅ Privacy **OFF**. Your duos can show normally.",
        )

    @settings_group.command(name="dm")
    @commands.guild_only()
    async def settings_dm(self, ctx: commands.Context, mode: str = ""):
        gid = ctx.guild.id
        defaults = await self._get_defaults(gid)
        return await self._toggle_bool(
            ctx,
            key="dm_reminders_enabled",
            default_bool=defaults["dm_reminders_enabled"],
            mode=mode,
            label_onoff="📩 DM reminders",
            status_msg_prefix="📩 DM reminders are",
            on_msg="📩 DM reminders **ON**. You’ll get a heads-up before the day ends.",
            off_msg="📩 DM reminders **OFF**.",
        )

    # ✅ NEW clean name (user-facing): `lost`
    # This maps to the legacy key dm_streak_end_enabled (old command dmend)
    @settings_group.command(name="lost")
    @commands.guild_only()
    async def settings_lost(self, ctx: commands.Context, mode: str = ""):
        gid = ctx.guild.id
        defaults = await self._get_defaults(gid)
        return await self._toggle_bool(
            ctx,
            key="dm_streak_end_enabled",
            default_bool=defaults["dm_streak_end_enabled"],
            mode=mode,
            label_onoff="⚠️ Streak lost alerts",
            status_msg_prefix="⚠️ Streak lost alerts are",
            on_msg="⚠️ **ON**. I’ll DM you when your streak is lost.",
            off_msg="⚠️ **OFF**. I won’t DM you when your streak is lost.",
        )

    # Legacy-friendly: keep `dmend` under settings too
    @settings_group.command(name="dmend")
    @commands.guild_only()
    async def settings_dmend(self, ctx: commands.Context, mode: str = ""):
        # redirect to the clean name
        return await self.settings_lost(ctx, mode)

    @settings_group.command(name="dmice")
    @commands.guild_only()
    async def settings_dmice(self, ctx: commands.Context, mode: str = ""):
        gid = ctx.guild.id
        defaults = await self._get_defaults(gid)
        return await self._toggle_bool(
            ctx,
            key="dm_streak_end_ice_enabled",
            default_bool=defaults["dm_streak_end_ice_enabled"],
            mode=mode,
            label_onoff="🧊 Ice alerts",
            status_msg_prefix="🧊 Ice alerts are",
            on_msg="🧊 **ON**. I’ll DM you when the restore window expires.",
            off_msg="🧊 **OFF**.",
        )

    @settings_group.command(name="dmrestore")
    @commands.guild_only()
    async def settings_dmrestore(self, ctx: commands.Context, mode: str = ""):
        gid = ctx.guild.id
        defaults = await self._get_defaults(gid)
        return await self._toggle_bool(
            ctx,
            key="dm_streak_end_restore_enabled",
            default_bool=defaults["dm_streak_end_restore_enabled"],
            mode=mode,
            label_onoff="🔥 Restore alerts",
            status_msg_prefix="🔥 Restore alerts are",
            on_msg="🔥 **ON**. I’ll DM you when a streak can still be restored.",
            off_msg="🔥 **OFF**.",
        )

    # ============================================================
    # ✅ Legacy commands kept (hidden) — nothing removed
    # ============================================================

    @commands.command(name="privacy", hidden=True)
    @commands.guild_only()
    async def privacy(self, ctx: commands.Context, mode: str = ""):
        return await self.settings_privacy(ctx, mode)

    @commands.command(name="dm", hidden=True)
    @commands.guild_only()
    async def dm_reminders(self, ctx: commands.Context, mode: str = ""):
        return await self.settings_dm(ctx, mode)

    # legacy name still works
    @commands.command(name="dmend", hidden=True)
    @commands.guild_only()
    async def dm_end(self, ctx: commands.Context, mode: str = ""):
        return await self.settings_lost(ctx, mode)

    @commands.command(name="dmice", hidden=True)
    @commands.guild_only()
    async def dm_ice(self, ctx: commands.Context, mode: str = ""):
        return await self.settings_dmice(ctx, mode)
