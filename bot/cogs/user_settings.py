# bot/cogs/user_settings.py
from __future__ import annotations

import discord
from discord.ext import commands

from bot.ui.help_embeds import user_settings_help_embed, user_settings_status_embed


def _onoff(value: bool) -> str:
    return "ON" if value else "OFF"


class UserSettingsCog(commands.Cog):
    """
    User-facing per-guild user settings.

    Stores user overrides in user_settings.
    Guild defaults come from guild_settings via repos.get_effective_config().
    """

    def __init__(self, bot: commands.Bot, settings, repos):
        self.bot = bot
        self.settings = settings
        self.repos = repos

    # ---------------- internal helpers ----------------

    def _parse_mode(self, mode: str) -> str:
        return (mode or "").strip().lower()

    async def _get_defaults(self, guild_id: int) -> dict[str, bool]:
        cfg = await self.repos.get_effective_config(guild_id, self.settings)

        return {
            "privacy_default_private": bool(cfg.get("privacy_default_private", False)),
            "dm_reminders_enabled": bool(cfg.get("dm_reminders_enabled", True)),
            "dm_streak_end_enabled": bool(cfg.get("dm_streak_end_enabled", True)),
            "dm_streak_end_ice_enabled": bool(cfg.get("dm_streak_end_ice_enabled", True)),
            "dm_streak_end_restore_enabled": bool(cfg.get("dm_streak_end_restore_enabled", True)),
        }

    async def _show_settings_embed(self, ctx: commands.Context):
        if ctx.guild is None:
            return

        guild_id = ctx.guild.id
        user_id = ctx.author.id
        defaults = await self._get_defaults(guild_id)

        privacy = await self.repos.get_user_setting_bool(
            guild_id=guild_id,
            user_id=user_id,
            key="privacy_private",
            default=defaults["privacy_default_private"],
        )

        dm = await self.repos.get_user_setting_bool(
            guild_id=guild_id,
            user_id=user_id,
            key="dm_reminders_enabled",
            default=defaults["dm_reminders_enabled"],
        )

        dm_lost = await self.repos.get_user_setting_bool(
            guild_id=guild_id,
            user_id=user_id,
            key="dm_streak_end_enabled",
            default=defaults["dm_streak_end_enabled"],
        )

        dm_restore = await self.repos.get_user_setting_bool(
            guild_id=guild_id,
            user_id=user_id,
            key="dm_streak_end_restore_enabled",
            default=defaults["dm_streak_end_restore_enabled"],
        )

        dm_ice = await self.repos.get_user_setting_bool(
            guild_id=guild_id,
            user_id=user_id,
            key="dm_streak_end_ice_enabled",
            default=defaults["dm_streak_end_ice_enabled"],
        )

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
        status_msg_prefix: str,
        on_msg: str,
        off_msg: str,
    ):
        if ctx.guild is None:
            return

        guild_id = ctx.guild.id
        user_id = ctx.author.id
        mode = self._parse_mode(mode)

        if mode in ("", "status", "show"):
            value = await self.repos.get_user_setting_bool(
                guild_id=guild_id,
                user_id=user_id,
                key=key,
                default=default_bool,
            )
            return await ctx.reply(f"{status_msg_prefix} **{_onoff(value)}** for you.")

        if mode in ("on", "enable", "1", "true"):
            await self.repos.set_user_setting_bool(
                guild_id=guild_id,
                user_id=user_id,
                key=key,
                value=True,
            )
            return await ctx.reply(on_msg)

        if mode in ("off", "disable", "0", "false"):
            await self.repos.set_user_setting_bool(
                guild_id=guild_id,
                user_id=user_id,
                key=key,
                value=False,
            )
            return await ctx.reply(off_msg)

        return await ctx.reply(embed=user_settings_help_embed(ctx))

    # ============================================================
    # settings hub
    # ============================================================

    @commands.group(name="settings", invoke_without_command=True)
    @commands.guild_only()
    async def settings_group(self, ctx: commands.Context):
        return await self._show_settings_embed(ctx)

    @settings_group.command(name="help")
    @commands.guild_only()
    async def settings_help(self, ctx: commands.Context):
        return await ctx.reply(embed=user_settings_help_embed(ctx))

    @settings_group.command(name="privacy")
    @commands.guild_only()
    async def settings_privacy(self, ctx: commands.Context, mode: str = ""):
        defaults = await self._get_defaults(ctx.guild.id)
        return await self._toggle_bool(
            ctx,
            key="privacy_private",
            default_bool=defaults["privacy_default_private"],
            mode=mode,
            status_msg_prefix="🔒 Privacy is",
            on_msg="🔒 Privacy **ON**. Your streaks will be private where supported.",
            off_msg="✅ Privacy **OFF**. Your streaks can show normally.",
        )

    @settings_group.command(name="dm")
    @commands.guild_only()
    async def settings_dm(self, ctx: commands.Context, mode: str = ""):
        defaults = await self._get_defaults(ctx.guild.id)
        return await self._toggle_bool(
            ctx,
            key="dm_reminders_enabled",
            default_bool=defaults["dm_reminders_enabled"],
            mode=mode,
            status_msg_prefix="📩 DM reminders are",
            on_msg="📩 DM reminders **ON**. You’ll get a heads-up before the day ends.",
            off_msg="📩 DM reminders **OFF**.",
        )

    @settings_group.command(name="lost")
    @commands.guild_only()
    async def settings_lost(self, ctx: commands.Context, mode: str = ""):
        defaults = await self._get_defaults(ctx.guild.id)
        return await self._toggle_bool(
            ctx,
            key="dm_streak_end_enabled",
            default_bool=defaults["dm_streak_end_enabled"],
            mode=mode,
            status_msg_prefix="⚠️ Streak lost alerts are",
            on_msg="⚠️ **ON**. I’ll DM you when your streak is lost.",
            off_msg="⚠️ **OFF**. I won’t DM you when your streak is lost.",
        )

    @settings_group.command(name="dmend")
    @commands.guild_only()
    async def settings_dmend(self, ctx: commands.Context, mode: str = ""):
        return await self.settings_lost(ctx, mode)

    @settings_group.command(name="dmice")
    @commands.guild_only()
    async def settings_dmice(self, ctx: commands.Context, mode: str = ""):
        defaults = await self._get_defaults(ctx.guild.id)
        return await self._toggle_bool(
            ctx,
            key="dm_streak_end_ice_enabled",
            default_bool=defaults["dm_streak_end_ice_enabled"],
            mode=mode,
            status_msg_prefix="🧊 Ice alerts are",
            on_msg="🧊 **ON**. I’ll DM you when the restore window expires.",
            off_msg="🧊 **OFF**.",
        )

    @settings_group.command(name="dmrestore")
    @commands.guild_only()
    async def settings_dmrestore(self, ctx: commands.Context, mode: str = ""):
        defaults = await self._get_defaults(ctx.guild.id)
        return await self._toggle_bool(
            ctx,
            key="dm_streak_end_restore_enabled",
            default_bool=defaults["dm_streak_end_restore_enabled"],
            mode=mode,
            status_msg_prefix="🔥 Restore alerts are",
            on_msg="🔥 **ON**. I’ll DM you when a streak can still be restored.",
            off_msg="🔥 **OFF**.",
        )

    # ============================================================
    # legacy commands
    # ============================================================

    @commands.command(name="privacy", hidden=True)
    @commands.guild_only()
    async def privacy(self, ctx: commands.Context, mode: str = ""):
        return await self.settings_privacy(ctx, mode)

    @commands.command(name="dm", hidden=True)
    @commands.guild_only()
    async def dm_reminders(self, ctx: commands.Context, mode: str = ""):
        return await self.settings_dm(ctx, mode)

    @commands.command(name="dmend", hidden=True)
    @commands.guild_only()
    async def dm_end(self, ctx: commands.Context, mode: str = ""):
        return await self.settings_lost(ctx, mode)

    @commands.command(name="dmice", hidden=True)
    @commands.guild_only()
    async def dm_ice(self, ctx: commands.Context, mode: str = ""):
        return await self.settings_dmice(ctx, mode)

    @commands.command(name="dmrestore", hidden=True)
    @commands.guild_only()
    async def dm_restore(self, ctx: commands.Context, mode: str = ""):
        return await self.settings_dmrestore(ctx, mode)