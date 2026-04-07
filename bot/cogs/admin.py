from __future__ import annotations

import traceback
from datetime import datetime, timezone

import discord
from discord.ext import commands

from bot.core.timecore import now_utc_ts, day_key_from_utc_ts
from bot.ui.help_embeds import admin_help_embed


def _parse_seconds(text: str) -> int:
    s = (text or "").strip().lower()
    if not s:
        raise ValueError("empty value")

    if s.endswith("m"):
        return int(s[:-1]) * 60
    if s.endswith("h"):
        return int(s[:-1]) * 3600
    if s.endswith("s"):
        return int(s[:-1])
    return int(s)


def _short_err(err: Exception) -> str:
    return f"{type(err).__name__}: {err}"


def admin_or_owner():
    async def predicate(ctx: commands.Context) -> bool:
        try:
            if await ctx.bot.is_owner(ctx.author):
                return True
        except Exception:
            pass

        if not ctx.guild:
            return False

        perms = getattr(ctx.author, "guild_permissions", None)
        return bool(perms and perms.administrator)

    return commands.check(predicate)


class AdminCog(commands.Cog):
    """
    Admin/debug commands for Ignio.
    Extended version that preserves the original admin structure
    while adding the new restore/reminder/nickname config controls.
    """

    def __init__(self, bot, settings=None, repos=None, vc_state=None, vc_cog=None):
        self.bot = bot
        self.settings = settings if settings is not None else getattr(bot, "settings", None)
        self.repos = repos if repos is not None else getattr(bot, "repos", None)
        self.vc_state = vc_state if vc_state is not None else getattr(bot, "vc_state", None)
        self.vc_cog = vc_cog

    # ---------------- shared helpers ----------------

    def _get_prefix(self) -> str:
        try:
            p = getattr(self.bot, "command_prefix", None)
            if isinstance(p, str) and p.strip():
                return p.strip()
        except Exception:
            pass
        return "!"

    async def _send_admin_help(self, ctx: commands.Context):
        return await ctx.reply(embed=admin_help_embed(ctx))

    async def _soft_fail(self, ctx: commands.Context, msg: str):
        return await ctx.reply(f"{msg}\nNeed help? Use `{self._get_prefix()}admin help`.")

    async def _fail(self, ctx: commands.Context, err: Exception):
        print("[Ignio][AdminCog] command error:", _short_err(err))
        traceback.print_exc()
        try:
            await ctx.reply(f"❌ `{_short_err(err)}`")
        except Exception:
            pass

    def _require_repos(self) -> bool:
        return self.repos is not None

    def _get_vc_cog(self):
        if self.vc_cog:
            return self.vc_cog
        return (
            self.bot.get_cog("VcTrackerCog")
            or self.bot.get_cog("VCTrackerCog")
            or self.bot.get_cog("VCTracker")
            or self.bot.get_cog("VcTracker")
            or self.bot.get_cog("vc_tracker")
        )

    async def _today_key(self, guild_id: int, now_ts: int) -> int:
        cfg = await self.repos.get_effective_config(guild_id, self.settings)
        return day_key_from_utc_ts(
            now_ts,
            str(cfg["default_tz"]),
            int(cfg["grace_hour_local"]),
        )

    async def _get_duo_streak_id(
        self,
        guild_id: int,
        user_a: discord.Member,
        user_b: discord.Member,
        now_ts: int,
    ) -> int:
        if user_a.bot or user_b.bot or user_a.id == user_b.id:
            raise ValueError("Pick two different real users")
        return await self.repos.get_or_create_duo(guild_id, user_a.id, user_b.id, now_ts)

    async def _render_config_text(self, guild_id: int) -> str:
        cfg = await self.repos.get_effective_config(guild_id, self.settings)

        lines = [
            "**Ignio Config**",
            "",
            "**Core**",
            f"• default_tz: `{cfg.get('default_tz', self.settings.default_tz)}`",
            f"• grace_hour_local: `{cfg.get('grace_hour_local', self.settings.grace_hour_local)}`",
            f"• min_overlap_seconds: `{cfg.get('min_overlap_seconds', self.settings.min_overlap_seconds)}`",
            f"• tick_seconds: `{cfg.get('tick_seconds', self.settings.tick_seconds)}`",
            f"• disconnect_buffer_seconds: `{cfg.get('disconnect_buffer_seconds', self.settings.disconnect_buffer_seconds)}`",
            f"• progress_bar_width: `{cfg.get('progress_bar_width', self.settings.progress_bar_width)}`",
            "",
            "**Protection**",
            f"• daily_cap_seconds: `{cfg.get('daily_cap_seconds', getattr(self.settings, 'daily_cap_seconds', 0))}`",
            f"• ignore_afk_channels: `{cfg.get('ignore_afk_channels', 0)}`",
            "",
            "**Privacy / DMs**",
            f"• privacy_default_private: `{cfg.get('privacy_default_private', 0)}`",
            f"• privacy_admin_can_view: `{cfg.get('privacy_admin_can_view', 1)}`",
            f"• dm_reminders_enabled: `{cfg.get('dm_reminders_enabled', 1)}`",
            f"• dm_streak_end_enabled: `{cfg.get('dm_streak_end_enabled', 1)}`",
            f"• dm_streak_end_ice_enabled: `{cfg.get('dm_streak_end_ice_enabled', 1)}`",
            f"• dm_streak_end_restore_enabled: `{cfg.get('dm_streak_end_restore_enabled', 1)}`",
            "",
            "**Restore / Warning**",
            f"• streak_restore_enabled: `{cfg.get('streak_restore_enabled', 1)}`",
            f"• streak_restore_window_minutes: `{cfg.get('streak_restore_window_minutes', getattr(self.settings, 'streak_restore_window_minutes', 120))}`",
            f"• streak_end_warning_minutes: `{cfg.get('streak_end_warning_minutes', getattr(self.settings, 'streak_end_warning_minutes', 60))}`",
            "",
            "**Nickname Fire**",
            f"• nickname_fire_enabled: `{cfg.get('nickname_fire_enabled', 1)}`",
            f"• nickname_fire_suffix: `{cfg.get('nickname_fire_suffix', getattr(self.settings, 'nickname_fire_suffix', ' 🔥'))}`",
            f"• nickname_edit_min_interval_seconds: `{cfg.get('nickname_edit_min_interval_seconds', getattr(self.settings, 'nickname_edit_min_interval_seconds', 20))}`",
        ]
        return "\n".join(lines)

    async def _set_bool_cfg(self, guild_id: int, key: str, value: bool, now_ts: int):
        if hasattr(self.repos, "set_guild_setting_bool"):
            await self.repos.set_guild_setting_bool(guild_id=guild_id, key=key, value=value, now_ts=now_ts)
        else:
            await self.repos.set_guild_setting_int(guild_id=guild_id, key=key, value=1 if value else 0, now_ts=now_ts)

    # ============================================================
    # admin hub
    # ============================================================

    @commands.group(name="admin", invoke_without_command=True)
    @commands.guild_only()
    @admin_or_owner()
    async def admin_group(self, ctx: commands.Context):
        return await self._send_admin_help(ctx)

    @admin_group.command(name="help")
    @commands.guild_only()
    @admin_or_owner()
    async def admin_help(self, ctx: commands.Context):
        return await self._send_admin_help(ctx)

    # ---------------- config ----------------

    @admin_group.command(name="config")
    @commands.guild_only()
    @admin_or_owner()
    async def admin_config(self, ctx: commands.Context):
        return await self.ignio_config(ctx)

    @admin_group.group(name="set", invoke_without_command=True)
    @commands.guild_only()
    @admin_or_owner()
    async def admin_set(self, ctx: commands.Context):
        return await self._soft_fail(
            ctx,
            "Use `admin set min`, `tick`, `cap`, `restore`, `restore_window`, `warn`, `nickfire`, `nicksuffix`, `nickcooldown`, or `privacy`.",
        )

    @admin_set.command(name="min")
    @commands.guild_only()
    @admin_or_owner()
    async def admin_set_min(self, ctx: commands.Context, value: str):
        return await self.set_min(ctx, value)

    @admin_set.command(name="tick")
    @commands.guild_only()
    @admin_or_owner()
    async def admin_set_tick(self, ctx: commands.Context, seconds: int):
        return await self.set_tick(ctx, seconds)

    @admin_set.command(name="cap")
    @commands.guild_only()
    @admin_or_owner()
    async def admin_set_cap(self, ctx: commands.Context, value: str):
        return await self.set_cap(ctx, value)

    @admin_set.command(name="restore")
    @commands.guild_only()
    @admin_or_owner()
    async def admin_set_restore(self, ctx: commands.Context, mode: str):
        return await self.set_restore(ctx, mode)

    @admin_set.command(name="restore_window")
    @commands.guild_only()
    @admin_or_owner()
    async def admin_set_restore_window(self, ctx: commands.Context, minutes: int):
        return await self.set_restore_window(ctx, minutes)

    @admin_set.command(name="warn")
    @commands.guild_only()
    @admin_or_owner()
    async def admin_set_warn(self, ctx: commands.Context, minutes: int):
        return await self.set_warn(ctx, minutes)

    @admin_set.command(name="nickfire")
    @commands.guild_only()
    @admin_or_owner()
    async def admin_set_nickfire(self, ctx: commands.Context, mode: str):
        return await self.set_nickfire(ctx, mode)

    @admin_set.command(name="nicksuffix")
    @commands.guild_only()
    @admin_or_owner()
    async def admin_set_nicksuffix(self, ctx: commands.Context, *, suffix: str):
        return await self.set_nicksuffix(ctx, suffix=suffix)

    @admin_set.command(name="nickcooldown")
    @commands.guild_only()
    @admin_or_owner()
    async def admin_set_nickcooldown(self, ctx: commands.Context, seconds: int):
        return await self.set_nickcooldown(ctx, seconds)

    @admin_set.group(name="privacy", invoke_without_command=True)
    @commands.guild_only()
    @admin_or_owner()
    async def admin_set_privacy(self, ctx: commands.Context):
        return await self._soft_fail(ctx, "Use `admin set privacy default public/private` or `admin set privacy admin on/off`.")

    @admin_set_privacy.command(name="default")
    @commands.guild_only()
    @admin_or_owner()
    async def admin_set_privacy_default(self, ctx: commands.Context, mode: str):
        return await self.set_privacy_default(ctx, mode)

    @admin_set_privacy.command(name="admin")
    @commands.guild_only()
    @admin_or_owner()
    async def admin_set_privacy_admin(self, ctx: commands.Context, mode: str):
        return await self.set_privacy_admin(ctx, mode)

    # ---------------- time / loop ----------------

    @admin_group.group(name="tick", invoke_without_command=True)
    @commands.guild_only()
    @admin_or_owner()
    async def admin_tick(self, ctx: commands.Context):
        return await self._soft_fail(ctx, "Use `admin tick status`.")

    @admin_tick.command(name="status")
    @commands.guild_only()
    @admin_or_owner()
    async def admin_tick_status(self, ctx: commands.Context):
        return await self.tick_status(ctx)

    @admin_group.command(name="daykey")
    @commands.guild_only()
    @admin_or_owner()
    async def admin_daykey(self, ctx: commands.Context):
        return await self.day_key_cmd(ctx)

    # ---------------- db ----------------

    @admin_group.group(name="db", invoke_without_command=True)
    @commands.guild_only()
    @admin_or_owner()
    async def admin_db(self, ctx: commands.Context):
        return await self._soft_fail(ctx, "Use `admin db counts`.")

    @admin_db.command(name="counts")
    @commands.guild_only()
    @admin_or_owner()
    async def admin_db_counts(self, ctx: commands.Context):
        return await self.db_counts(ctx)

    # ---------------- test ----------------

    @admin_group.group(name="test", invoke_without_command=True)
    @commands.guild_only()
    @admin_or_owner()
    async def admin_test(self, ctx: commands.Context):
        return await self._soft_fail(
            ctx,
            "Use `admin test add_today`, `set_today`, `set_day`, `set_streak`, or `clear_duo`.",
        )

    @admin_test.command(name="add_today")
    @commands.guild_only()
    @admin_or_owner()
    async def admin_test_add_today(
        self,
        ctx: commands.Context,
        user_a: discord.Member,
        user_b: discord.Member,
        amount: str,
    ):
        return await self.test_add_today(ctx, user_a, user_b, amount)

    @admin_test.command(name="set_today")
    @commands.guild_only()
    @admin_or_owner()
    async def admin_test_set_today(
        self,
        ctx: commands.Context,
        user_a: discord.Member,
        user_b: discord.Member,
        amount: str,
    ):
        return await self.test_set_today(ctx, user_a, user_b, amount)

    @admin_test.command(name="set_day")
    @commands.guild_only()
    @admin_or_owner()
    async def admin_test_set_day(
        self,
        ctx: commands.Context,
        user_a: discord.Member,
        user_b: discord.Member,
        day_key: int,
        amount: str,
    ):
        return await self.test_set_day(ctx, user_a, user_b, day_key, amount)

    @admin_test.command(name="set_streak")
    @commands.guild_only()
    @admin_or_owner()
    async def admin_test_set_streak(
        self,
        ctx: commands.Context,
        user_a: discord.Member,
        user_b: discord.Member,
        current_streak: int,
        longest_streak: int,
        last_completed_day_key: int,
    ):
        return await self.test_set_streak(
            ctx,
            user_a,
            user_b,
            current_streak,
            longest_streak,
            last_completed_day_key,
        )

    @admin_test.command(name="clear_duo")
    @commands.guild_only()
    @admin_or_owner()
    async def admin_test_clear_duo(
        self,
        ctx: commands.Context,
        user_a: discord.Member,
        user_b: discord.Member,
    ):
        return await self.test_clear_duo(ctx, user_a, user_b)

    # ---------------- dm ----------------

    @admin_group.group(name="dm", invoke_without_command=True)
    @commands.guild_only()
    @admin_or_owner()
    async def admin_dm(self, ctx: commands.Context):
        return await self._soft_fail(ctx, "Use `admin dm restore`, `admin dm ice`, or `admin dm text`.")

    @admin_dm.command(name="restore")
    @commands.guild_only()
    @admin_or_owner()
    async def admin_dm_restore(self, ctx: commands.Context, member: discord.Member):
        return await self.test_dm_restore(ctx, member)

    @admin_dm.command(name="ice")
    @commands.guild_only()
    @admin_or_owner()
    async def admin_dm_ice(self, ctx: commands.Context, member: discord.Member):
        return await self.test_dm_ice(ctx, member)

    @admin_dm.command(name="text")
    @commands.guild_only()
    @admin_or_owner()
    async def admin_dm_text(self, ctx: commands.Context, member: discord.Member, *, message: str):
        return await self.test_dm_text(ctx, member, message=message)

    # ============================================================
    # legacy hidden commands
    # ============================================================

    @commands.command(name="ping", hidden=True)
    @commands.guild_only()
    @admin_or_owner()
    async def ping(self, ctx: commands.Context):
        try:
            await ctx.reply(f"🏓 pong ({round(self.bot.latency * 1000)}ms)")
        except Exception as err:
            await self._fail(ctx, err)

    @commands.command(name="loaded", hidden=True)
    @commands.guild_only()
    @admin_or_owner()
    async def loaded(self, ctx: commands.Context):
        try:
            cogs = ", ".join(self.bot.cogs.keys()) or "none"
            cmds = ", ".join(sorted(c.name for c in self.bot.commands))
            await ctx.reply(f"**Cogs:** {cogs}\n**Commands:** {cmds}")
        except Exception as err:
            await self._fail(ctx, err)

    # ---------------- config commands ----------------

    @commands.command(name="ignio_config", hidden=True)
    @commands.guild_only()
    @admin_or_owner()
    async def ignio_config(self, ctx: commands.Context):
        try:
            if not self._require_repos():
                return await ctx.reply("repos not available on AdminCog.")
            msg = await self._render_config_text(ctx.guild.id)
            await ctx.reply(msg)
        except Exception as err:
            await self._fail(ctx, err)

    @commands.command(name="set_min", hidden=True)
    @commands.guild_only()
    @admin_or_owner()
    async def set_min(self, ctx: commands.Context, value: str):
        try:
            if not self._require_repos():
                return await ctx.reply("repos not available on AdminCog.")

            gid = ctx.guild.id
            now_ts = now_utc_ts()

            seconds = _parse_seconds(value)
            seconds = max(30, min(seconds, 6 * 60 * 60))

            await self.repos.set_guild_setting_int(
                guild_id=gid,
                key="min_overlap_seconds",
                value=seconds,
                now_ts=now_ts,
            )

            await ctx.reply(f"✅ min_overlap_seconds set to `{seconds}` seconds.")
        except Exception as err:
            await self._fail(ctx, err)

    @commands.command(name="set_tick", hidden=True)
    @commands.guild_only()
    @admin_or_owner()
    async def set_tick(self, ctx: commands.Context, seconds: int):
        try:
            if not self._require_repos():
                return await ctx.reply("repos not available on AdminCog.")

            gid = ctx.guild.id
            now_ts = now_utc_ts()

            seconds = max(5, min(int(seconds), 120))

            await self.repos.set_guild_setting_int(
                guild_id=gid,
                key="tick_seconds",
                value=seconds,
                now_ts=now_ts,
            )

            await ctx.reply(f"✅ tick_seconds set to `{seconds}`.")
        except Exception as err:
            await self._fail(ctx, err)

    @commands.command(name="set_cap", hidden=True)
    @commands.guild_only()
    @admin_or_owner()
    async def set_cap(self, ctx: commands.Context, value: str):
        try:
            if not self._require_repos():
                return await ctx.reply("repos not available on AdminCog.")

            gid = ctx.guild.id
            now_ts = now_utc_ts()

            seconds = _parse_seconds(value)
            seconds = max(0, min(seconds, 24 * 60 * 60))

            await self.repos.set_guild_setting_int(
                guild_id=gid,
                key="daily_cap_seconds",
                value=seconds,
                now_ts=now_ts,
            )

            await ctx.reply(f"✅ daily_cap_seconds set to `{seconds}`.")
        except Exception as err:
            await self._fail(ctx, err)

    @commands.command(name="set_restore", hidden=True)
    @commands.guild_only()
    @admin_or_owner()
    async def set_restore(self, ctx: commands.Context, mode: str):
        try:
            if not self._require_repos():
                return await ctx.reply("repos not available on AdminCog.")

            mode = (mode or "").strip().lower()
            if mode not in ("on", "off"):
                return await ctx.reply("Use `on` or `off`.")

            gid = ctx.guild.id
            now_ts = now_utc_ts()

            await self._set_bool_cfg(gid, "streak_restore_enabled", mode == "on", now_ts)
            await ctx.reply(f"✅ streak_restore_enabled set to `{1 if mode == 'on' else 0}`.")
        except Exception as err:
            await self._fail(ctx, err)

    @commands.command(name="set_restore_window", hidden=True)
    @commands.guild_only()
    @admin_or_owner()
    async def set_restore_window(self, ctx: commands.Context, minutes: int):
        try:
            if not self._require_repos():
                return await ctx.reply("repos not available on AdminCog.")

            gid = ctx.guild.id
            now_ts = now_utc_ts()
            minutes = max(1, min(int(minutes), 24 * 60))

            await self.repos.set_guild_setting_int(
                guild_id=gid,
                key="streak_restore_window_minutes",
                value=minutes,
                now_ts=now_ts,
            )

            await ctx.reply(f"✅ streak_restore_window_minutes set to `{minutes}`.")
        except Exception as err:
            await self._fail(ctx, err)

    @commands.command(name="set_warn", hidden=True)
    @commands.guild_only()
    @admin_or_owner()
    async def set_warn(self, ctx: commands.Context, minutes: int):
        try:
            if not self._require_repos():
                return await ctx.reply("repos not available on AdminCog.")

            gid = ctx.guild.id
            now_ts = now_utc_ts()
            minutes = max(1, min(int(minutes), 12 * 60))

            await self.repos.set_guild_setting_int(
                guild_id=gid,
                key="streak_end_warning_minutes",
                value=minutes,
                now_ts=now_ts,
            )

            await ctx.reply(f"✅ streak_end_warning_minutes set to `{minutes}`.")
        except Exception as err:
            await self._fail(ctx, err)

    @commands.command(name="set_nickfire", hidden=True)
    @commands.guild_only()
    @admin_or_owner()
    async def set_nickfire(self, ctx: commands.Context, mode: str):
        try:
            if not self._require_repos():
                return await ctx.reply("repos not available on AdminCog.")

            mode = (mode or "").strip().lower()
            if mode not in ("on", "off"):
                return await ctx.reply("Use `on` or `off`.")

            gid = ctx.guild.id
            now_ts = now_utc_ts()

            await self._set_bool_cfg(gid, "nickname_fire_enabled", mode == "on", now_ts)
            await ctx.reply(f"✅ nickname_fire_enabled set to `{1 if mode == 'on' else 0}`.")
        except Exception as err:
            await self._fail(ctx, err)

    @commands.command(name="set_nicksuffix", hidden=True)
    @commands.guild_only()
    @admin_or_owner()
    async def set_nicksuffix(self, ctx: commands.Context, *, suffix: str):
        try:
            if not self._require_repos():
                return await ctx.reply("repos not available on AdminCog.")

            suffix = (suffix or "").rstrip()
            if not suffix:
                return await ctx.reply("Suffix cannot be empty.")

            gid = ctx.guild.id
            now_ts = now_utc_ts()

            await self.repos.set_guild_setting_str(
                guild_id=gid,
                key="nickname_fire_suffix",
                value=suffix,
                now_ts=now_ts,
            )

            await ctx.reply(f"✅ nickname_fire_suffix set to `{suffix}`.")
        except Exception as err:
            await self._fail(ctx, err)

    @commands.command(name="set_nickcooldown", hidden=True)
    @commands.guild_only()
    @admin_or_owner()
    async def set_nickcooldown(self, ctx: commands.Context, seconds: int):
        try:
            if not self._require_repos():
                return await ctx.reply("repos not available on AdminCog.")

            gid = ctx.guild.id
            now_ts = now_utc_ts()
            seconds = max(1, min(int(seconds), 600))

            await self.repos.set_guild_setting_int(
                guild_id=gid,
                key="nickname_edit_min_interval_seconds",
                value=seconds,
                now_ts=now_ts,
            )

            await ctx.reply(f"✅ nickname_edit_min_interval_seconds set to `{seconds}`.")
        except Exception as err:
            await self._fail(ctx, err)

    @commands.command(name="set_privacy_default", hidden=True)
    @commands.guild_only()
    @admin_or_owner()
    async def set_privacy_default(self, ctx: commands.Context, mode: str):
        try:
            if not self._require_repos():
                return await ctx.reply("repos not available on AdminCog.")

            mode = (mode or "").strip().lower()
            if mode not in ("public", "private"):
                return await ctx.reply("Use `public` or `private`.")

            gid = ctx.guild.id
            now_ts = now_utc_ts()

            await self._set_bool_cfg(gid, "privacy_default_private", mode == "private", now_ts)
            await ctx.reply(f"✅ privacy_default_private set to `{1 if mode == 'private' else 0}`.")
        except Exception as err:
            await self._fail(ctx, err)

    @commands.command(name="set_privacy_admin", hidden=True)
    @commands.guild_only()
    @admin_or_owner()
    async def set_privacy_admin(self, ctx: commands.Context, mode: str):
        try:
            if not self._require_repos():
                return await ctx.reply("repos not available on AdminCog.")

            mode = (mode or "").strip().lower()
            if mode not in ("on", "off"):
                return await ctx.reply("Use `on` or `off`.")

            gid = ctx.guild.id
            now_ts = now_utc_ts()

            await self._set_bool_cfg(gid, "privacy_admin_can_view", mode == "on", now_ts)
            await ctx.reply(f"✅ privacy_admin_can_view set to `{1 if mode == 'on' else 0}`.")
        except Exception as err:
            await self._fail(ctx, err)

    # ---------------- loop / time ----------------

    @commands.command(name="tick_status", hidden=True)
    @commands.guild_only()
    @admin_or_owner()
    async def tick_status(self, ctx: commands.Context):
        try:
            vc_cog = self._get_vc_cog()
            if not vc_cog:
                return await ctx.reply("VC tracker not found.")

            loop = getattr(vc_cog, "tick", None) or getattr(vc_cog, "tick_loop", None)
            if not loop:
                return await ctx.reply("Tick loop not found on VC tracker.")

            await ctx.reply(f"Tick loop running: `{loop.is_running()}`")
        except Exception as err:
            await self._fail(ctx, err)

    @commands.command(name="day_key", hidden=True)
    @commands.guild_only()
    @admin_or_owner()
    async def day_key_cmd(self, ctx: commands.Context):
        try:
            if not self._require_repos():
                return await ctx.reply("repos not available on AdminCog.")

            gid = ctx.guild.id
            now_ts = now_utc_ts()
            cfg = await self.repos.get_effective_config(gid, self.settings)

            day_key = day_key_from_utc_ts(
                now_ts,
                str(cfg["default_tz"]),
                int(cfg["grace_hour_local"]),
            )
            dt_utc = datetime.fromtimestamp(now_ts, tz=timezone.utc).isoformat()

            msg = (
                "**Day Key Debug**\n"
                f"• now_utc: `{dt_utc}`\n"
                f"• tz: `{cfg['default_tz']}`\n"
                f"• grace_hour_local: `{cfg['grace_hour_local']}`\n"
                f"• day_key: `{day_key}`"
            )
            await ctx.reply(msg)
        except Exception as err:
            await self._fail(ctx, err)

    # ---------------- db counts ----------------

    @commands.command(name="db_counts", hidden=True)
    @commands.guild_only()
    @admin_or_owner()
    async def db_counts(self, ctx: commands.Context):
        try:
            if not self._require_repos():
                return await ctx.reply("repos not available on AdminCog.")

            gid = ctx.guild.id
            db = await self.repos._db()

            streak_entities_row = await db.fetchone(
                "SELECT COUNT(*) AS c FROM streak_entities WHERE guild_id = ?",
                (gid,),
            )
            streak_members_row = await db.fetchone(
                """
                SELECT COUNT(*) AS c
                FROM streak_members sm
                JOIN streak_entities se ON se.streak_id = sm.streak_id
                WHERE se.guild_id = ?
                """,
                (gid,),
            )
            daily_progress_row = await db.fetchone(
                "SELECT COUNT(*) AS c FROM streak_daily_progress WHERE guild_id = ?",
                (gid,),
            )
            streak_state_row = await db.fetchone(
                "SELECT COUNT(*) AS c FROM streak_state WHERE guild_id = ?",
                (gid,),
            )
            logs_row = await db.fetchone(
                "SELECT COUNT(*) AS c FROM streak_activity_logs WHERE guild_id = ?",
                (gid,),
            )

            msg = (
                "**DB Counts**\n"
                f"• streak_entities: `{int(streak_entities_row['c'])}`\n"
                f"• streak_members: `{int(streak_members_row['c'])}`\n"
                f"• streak_daily_progress: `{int(daily_progress_row['c'])}`\n"
                f"• streak_state: `{int(streak_state_row['c'])}`\n"
                f"• streak_activity_logs: `{int(logs_row['c'])}`"
            )
            await ctx.reply(msg)
        except Exception as err:
            await self._fail(ctx, err)

    # ============================================================
    # test / dev commands
    # ============================================================

    @commands.command(name="test_add_today", hidden=True)
    @commands.guild_only()
    @admin_or_owner()
    async def test_add_today(
        self,
        ctx: commands.Context,
        user_a: discord.Member,
        user_b: discord.Member,
        amount: str,
    ):
        try:
            if not self._require_repos():
                return await ctx.reply("repos not available.")

            gid = ctx.guild.id
            now_ts = now_utc_ts()
            day_key = await self._today_key(gid, now_ts)
            seconds = max(0, _parse_seconds(amount))

            streak_id = await self._get_duo_streak_id(gid, user_a, user_b, now_ts)
            total = await self.repos.add_progress_seconds(
                streak_id=streak_id,
                guild_id=gid,
                day_key=day_key,
                seconds=seconds,
                now_ts=now_ts,
                event_type="manual_add",
                meta_json='{"source":"admin_test_add_today"}',
            )

            await self.repos.log_admin_action(
                guild_id=gid,
                admin_user_id=ctx.author.id,
                streak_id=streak_id,
                action_type="add_time",
                amount=seconds,
                note=f"Added time to today for duo {user_a.id}+{user_b.id}",
                now_ts=now_ts,
            )

            await ctx.reply(f"✅ Added `{seconds}` seconds to today. New total: `{total}` seconds.")
        except Exception as err:
            await self._fail(ctx, err)

    @commands.command(name="test_set_today", hidden=True)
    @commands.guild_only()
    @admin_or_owner()
    async def test_set_today(
        self,
        ctx: commands.Context,
        user_a: discord.Member,
        user_b: discord.Member,
        amount: str,
    ):
        try:
            if not self._require_repos():
                return await ctx.reply("repos not available.")

            gid = ctx.guild.id
            now_ts = now_utc_ts()
            day_key = await self._today_key(gid, now_ts)
            seconds = max(0, _parse_seconds(amount))

            streak_id = await self._get_duo_streak_id(gid, user_a, user_b, now_ts)
            db = await self.repos._db()

            await db.execute(
                """
                INSERT INTO streak_daily_progress (
                    streak_id, guild_id, day_key, progress_seconds, qualified, updated_at
                )
                VALUES (?, ?, ?, ?, 0, ?)
                ON CONFLICT(streak_id, day_key)
                DO UPDATE SET
                    progress_seconds = excluded.progress_seconds,
                    updated_at = excluded.updated_at
                """,
                (streak_id, gid, day_key, seconds, now_ts),
            )
            await db.commit()

            await self.repos.log_admin_action(
                guild_id=gid,
                admin_user_id=ctx.author.id,
                streak_id=streak_id,
                action_type="set_today_seconds",
                amount=seconds,
                note=f"Set today seconds for duo {user_a.id}+{user_b.id}",
                now_ts=now_ts,
            )

            await ctx.reply(f"✅ Set today to `{seconds}` seconds.")
        except Exception as err:
            await self._fail(ctx, err)

    @commands.command(name="test_set_day", hidden=True)
    @commands.guild_only()
    @admin_or_owner()
    async def test_set_day(
        self,
        ctx: commands.Context,
        user_a: discord.Member,
        user_b: discord.Member,
        day_key: int,
        amount: str,
    ):
        try:
            if not self._require_repos():
                return await ctx.reply("repos not available.")

            gid = ctx.guild.id
            now_ts = now_utc_ts()
            seconds = max(0, _parse_seconds(amount))

            streak_id = await self._get_duo_streak_id(gid, user_a, user_b, now_ts)
            db = await self.repos._db()

            await db.execute(
                """
                INSERT INTO streak_daily_progress (
                    streak_id, guild_id, day_key, progress_seconds, qualified, updated_at
                )
                VALUES (?, ?, ?, ?, 0, ?)
                ON CONFLICT(streak_id, day_key)
                DO UPDATE SET
                    progress_seconds = excluded.progress_seconds,
                    updated_at = excluded.updated_at
                """,
                (streak_id, gid, day_key, seconds, now_ts),
            )
            await db.commit()

            await self.repos.log_admin_action(
                guild_id=gid,
                admin_user_id=ctx.author.id,
                streak_id=streak_id,
                action_type="set_day_seconds",
                amount=seconds,
                note=f"Set seconds for day_key {day_key} for duo {user_a.id}+{user_b.id}",
                now_ts=now_ts,
            )

            await ctx.reply(f"✅ Set day `{day_key}` to `{seconds}` seconds.")
        except Exception as err:
            await self._fail(ctx, err)

    @commands.command(name="test_set_streak", hidden=True)
    @commands.guild_only()
    @admin_or_owner()
    async def test_set_streak(
        self,
        ctx: commands.Context,
        user_a: discord.Member,
        user_b: discord.Member,
        current_streak: int,
        longest_streak: int,
        last_completed_day_key: int,
    ):
        try:
            if not self._require_repos():
                return await ctx.reply("repos not available.")

            gid = ctx.guild.id
            now_ts = now_utc_ts()

            streak_id = await self._get_duo_streak_id(gid, user_a, user_b, now_ts)

            old_state = await self.repos.get_streak_state(streak_id)
            total_completed_days = 0 if old_state is None else int(old_state["total_completed_days"])

            await self.repos.save_streak_state(
                streak_id=streak_id,
                guild_id=gid,
                current_streak=int(current_streak),
                longest_streak=int(longest_streak),
                total_completed_days=total_completed_days,
                last_completed_day_key=int(last_completed_day_key),
                now_ts=now_ts,
            )

            await self.repos.log_admin_action(
                guild_id=gid,
                admin_user_id=ctx.author.id,
                streak_id=streak_id,
                action_type="set_streak",
                amount=int(current_streak),
                note=(
                    f"Set streak for duo {user_a.id}+{user_b.id}: "
                    f"current={current_streak}, longest={longest_streak}, "
                    f"last_completed_day_key={last_completed_day_key}"
                ),
                now_ts=now_ts,
            )

            await ctx.reply(
                "✅ Streak state updated.\n"
                f"• current: `{current_streak}`\n"
                f"• longest: `{longest_streak}`\n"
                f"• last_completed_day_key: `{last_completed_day_key}`"
            )
        except Exception as err:
            await self._fail(ctx, err)

    @commands.command(name="test_clear_duo", hidden=True)
    @commands.guild_only()
    @admin_or_owner()
    async def test_clear_duo(
        self,
        ctx: commands.Context,
        user_a: discord.Member,
        user_b: discord.Member,
    ):
        try:
            if not self._require_repos():
                return await ctx.reply("repos not available.")

            gid = ctx.guild.id
            now_ts = now_utc_ts()

            streak = await self.repos.get_streak_by_member_hash(
                guild_id=gid,
                member_ids=[user_a.id, user_b.id],
                only_active=False,
            )
            if streak is None:
                return await ctx.reply("No duo found for those users.")

            streak_id = int(streak["streak_id"])
            db = await self.repos._db()

            await db.execute("DELETE FROM streak_daily_progress WHERE streak_id = ?", (streak_id,))
            await db.execute("DELETE FROM streak_state WHERE streak_id = ?", (streak_id,))
            await db.execute("DELETE FROM streak_notifications WHERE streak_id = ?", (streak_id,))
            await db.execute("DELETE FROM streak_activity_logs WHERE streak_id = ?", (streak_id,))
            await db.execute("DELETE FROM streak_members WHERE streak_id = ?", (streak_id,))
            await db.execute("DELETE FROM streak_entities WHERE streak_id = ?", (streak_id,))
            await db.commit()

            await self.repos.log_admin_action(
                guild_id=gid,
                admin_user_id=ctx.author.id,
                streak_id=None,
                action_type="clear_duo",
                amount=None,
                note=f"Cleared duo for users {user_a.id}+{user_b.id}",
                now_ts=now_ts,
            )

            await ctx.reply("✅ Duo and all related data cleared.")
        except Exception as err:
            await self._fail(ctx, err)

    # ---------------- dm tests ----------------

    async def _dm_embed(self, member: discord.Member, embed: discord.Embed) -> bool:
        try:
            await member.send(embed=embed)
            return True
        except Exception:
            return False

    @commands.command(name="test_dm_restore", hidden=True)
    @commands.guild_only()
    @admin_or_owner()
    async def test_dm_restore(self, ctx: commands.Context, member: discord.Member):
        try:
            embed = discord.Embed(
                title="🔥 Streak Restore Available",
                description="Your duo streak ended, but it can still be restored.",
            )
            embed.add_field(
                name="What to do",
                value="Hop in VC with your duo before the restore window ends.",
                inline=False,
            )
            embed.set_footer(text="test DM")

            ok = await self._dm_embed(member, embed)
            await ctx.reply("✅ Restore DM sent." if ok else "❌ Could not DM that user.")
        except Exception as err:
            await self._fail(ctx, err)

    @commands.command(name="test_dm_ice", hidden=True)
    @commands.guild_only()
    @admin_or_owner()
    async def test_dm_ice(self, ctx: commands.Context, member: discord.Member):
        try:
            embed = discord.Embed(
                title="🧊 Streak Lost",
                description="Restore window expired. This streak cannot be restored anymore.",
            )
            embed.set_footer(text="test DM")

            ok = await self._dm_embed(member, embed)
            await ctx.reply("✅ Ice DM sent." if ok else "❌ Could not DM that user.")
        except Exception as err:
            await self._fail(ctx, err)

    @commands.command(name="test_dm_text", hidden=True)
    @commands.guild_only()
    @admin_or_owner()
    async def test_dm_text(self, ctx: commands.Context, member: discord.Member, *, message: str):
        try:
            try:
                await member.send(f"(test DM) {message}")
                ok = True
            except Exception:
                ok = False

            await ctx.reply("✅ Sent DM." if ok else "❌ Could not DM that user.")
        except Exception as err:
            await self._fail(ctx, err)


async def setup(bot: commands.Bot):
    await bot.add_cog(AdminCog(bot))