# bot/cogs/admin.py
from __future__ import annotations

import traceback
import discord
from discord.ext import commands
from datetime import datetime, timezone

from bot.core.timecore import now_utc_ts, day_key_from_utc_ts
from bot.config import e as emoji


def _parse_seconds(text: str) -> int:
    """
    Accept:
      180        -> 180 seconds
      3m         -> 180 seconds
      10m        -> 600 seconds
      2h         -> 7200 seconds
    """
    s = (text or "").strip().lower()
    if not s:
        raise ValueError("empty")

    if s.endswith("m"):
        return int(s[:-1]) * 60
    if s.endswith("h"):
        return int(s[:-1]) * 3600
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
    Admin-only debug + test commands for Ignio.
    """

    def __init__(self, bot: commands.Bot, settings=None, repos=None, vc_state=None, vc_cog=None):
        self.bot = bot
        self.settings = settings if settings is not None else getattr(bot, "settings", None)
        self.repos = repos if repos is not None else getattr(bot, "repos", None)
        self.vc_state = vc_state if vc_state is not None else getattr(bot, "vc_state", None)
        self.vc_cog = vc_cog

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

    async def _fail(self, ctx: commands.Context, err: Exception):
        print("[Ignio][AdminCog] command error:", _short_err(err))
        traceback.print_exc()
        try:
            await ctx.reply(f"❌ `{_short_err(err)}`")
        except Exception:
            pass

    def _require_repos(self) -> bool:
        return bool(self.repos)

    # ---------- BASIC ----------

    @commands.command(name="ping")
    @commands.guild_only()
    @admin_or_owner()
    async def ping(self, ctx: commands.Context):
        try:
            await ctx.reply(f"🏓 pong ({round(self.bot.latency * 1000)}ms)")
        except Exception as err:
            await self._fail(ctx, err)

    @commands.command(name="loaded")
    @commands.guild_only()
    @admin_or_owner()
    async def loaded(self, ctx: commands.Context):
        try:
            cogs = ", ".join(self.bot.cogs.keys()) or "none"
            cmds = ", ".join(sorted([c.name for c in self.bot.commands]))
            await ctx.reply(f"**Cogs:** {cogs}\n**Commands:** {cmds}")
        except Exception as err:
            await self._fail(ctx, err)

    # ---------- CONFIG (DB-backed) ----------

    @commands.command(name="ignio_config")
    @commands.guild_only()
    @admin_or_owner()
    async def ignio_config(self, ctx: commands.Context):
        try:
            if not self._require_repos():
                return await ctx.reply("repos not available on AdminCog.")
            gid = ctx.guild.id
            cfg = await self.repos.get_effective_config(gid, self.settings)

            msg = (
                f"**Ignio Config (effective / live)**\n"
                f"- default_tz: `{cfg['default_tz']}`\n"
                f"- grace_hour_local: `{cfg['grace_hour_local']}`\n"
                f"- min_overlap_seconds: `{cfg['min_overlap_seconds']}`\n"
                f"- tick_seconds: `{cfg['tick_seconds']}`\n"
                f"- disconnect_buffer_seconds: `{cfg['disconnect_buffer_seconds']}`\n"
                f"- progress_bar_width: `{cfg['progress_bar_width']}`\n"
                f"- privacy_default_private: `{cfg.get('privacy_default_private', False)}`\n"
                f"- privacy_admin_can_view: `{cfg.get('privacy_admin_can_view', False)}`\n"
                f"- heatmap_met_emoji: `{cfg.get('heatmap_met_emoji', '🟥')}`\n"
                f"- heatmap_empty_emoji: `{cfg.get('heatmap_empty_emoji', '⬜')}`\n"
            )
            await ctx.reply(msg)
        except Exception as err:
            await self._fail(ctx, err)

    @commands.command(name="set_min")
    @commands.guild_only()
    @admin_or_owner()
    async def set_min(self, ctx: commands.Context, value: str):
        """
        !set_min 120
        !set_min 2m
        """
        try:
            if not self._require_repos():
                return await ctx.reply("repos not available on AdminCog.")
            gid = ctx.guild.id
            now = now_utc_ts()

            seconds = _parse_seconds(value)
            seconds = max(30, min(seconds, 6 * 60 * 60))
            await self.repos.set_config_int(gid, "min_overlap_seconds", seconds, now)

            cfg = await self.repos.get_effective_config(gid, self.settings)
            dk = day_key_from_utc_ts(now, str(cfg["default_tz"]), int(cfg["grace_hour_local"]))

            fn = getattr(self.repos, "recalc_today_all_duos", None)
            if fn:
                updated = await fn(gid, dk, int(cfg["min_overlap_seconds"]), now)
                await ctx.reply(f"✅ min_overlap_seconds set to `{seconds}` sec. Recalc updated `{updated}` duos today.")
            else:
                await ctx.reply(f"✅ min_overlap_seconds set to `{seconds}` sec. (Repo has no recalc_today_all_duos.)")
        except Exception as err:
            await self._fail(ctx, err)

    @commands.command(name="set_tick")
    @commands.guild_only()
    @admin_or_owner()
    async def set_tick(self, ctx: commands.Context, seconds: int):
        try:
            if not self._require_repos():
                return await ctx.reply("repos not available on AdminCog.")
            gid = ctx.guild.id
            now = now_utc_ts()

            seconds = max(5, min(int(seconds), 120))
            await self.repos.set_config_int(gid, "tick_seconds", seconds, now)
            await ctx.reply(f"✅ tick_seconds set to `{seconds}`.")
        except Exception as err:
            await self._fail(ctx, err)

    @commands.command(name="recalc_today")
    @commands.guild_only()
    @admin_or_owner()
    async def recalc_today(self, ctx: commands.Context):
        try:
            if not self._require_repos():
                return await ctx.reply("repos not available on AdminCog.")
            gid = ctx.guild.id
            now = now_utc_ts()

            cfg = await self.repos.get_effective_config(gid, self.settings)
            dk = day_key_from_utc_ts(now, str(cfg["default_tz"]), int(cfg["grace_hour_local"]))

            fn = getattr(self.repos, "recalc_today_all_duos", None)
            if not fn:
                return await ctx.reply("❌ repos.recalc_today_all_duos not implemented.")

            updated = await fn(gid, dk, int(cfg["min_overlap_seconds"]), now)
            await ctx.reply(f"✅ Recalc done. Updated `{updated}` duos today.")
        except Exception as err:
            await self._fail(ctx, err)

    # ---------- LOOP / TIME ----------

    @commands.command(name="tick_status")
    @commands.guild_only()
    @admin_or_owner()
    async def tick_status(self, ctx: commands.Context):
        try:
            vc_cog = self._get_vc_cog()
            if not vc_cog:
                return await ctx.reply("VC cog not found (is vc_tracker loaded?)")

            loop = getattr(vc_cog, "tick", None) or getattr(vc_cog, "tick_loop", None)
            if not loop:
                return await ctx.reply("Couldn’t find tick task on VC cog (expected `.tick` or `.tick_loop`).")

            await ctx.reply(f"Tick loop running: `{loop.is_running()}`")
        except Exception as err:
            await self._fail(ctx, err)

    @commands.command(name="day_key")
    @commands.guild_only()
    @admin_or_owner()
    async def day_key_cmd(self, ctx: commands.Context):
        try:
            if not self._require_repos():
                return await ctx.reply("repos not available on AdminCog.")
            gid = ctx.guild.id
            now = now_utc_ts()
            cfg = await self.repos.get_effective_config(gid, self.settings)

            dk = day_key_from_utc_ts(now, str(cfg["default_tz"]), int(cfg["grace_hour_local"]))
            dt_utc = datetime.fromtimestamp(now, tz=timezone.utc).isoformat()

            await ctx.reply(
                f"**Day Key Debug**\n"
                f"- now_utc: `{dt_utc}`\n"
                f"- tz: `{cfg['default_tz']}`\n"
                f"- grace_hour_local: `{cfg['grace_hour_local']}`\n"
                f"- day_key: `{dk}`"
            )
        except Exception as err:
            await self._fail(ctx, err)

    # ---------- DB HEALTH ----------

    @commands.command(name="db_counts")
    @commands.guild_only()
    @admin_or_owner()
    async def db_counts(self, ctx: commands.Context):
        try:
            if not self._require_repos():
                return await ctx.reply("repos not available on AdminCog.")
            gid = ctx.guild.id
            counts = await self.repos.counts_for_guild(gid)
            out = [
                "**DB Counts (this server)**",
                f"- duos: `{counts['duos']}`",
                f"- duo_daily: `{counts['duo_daily']}`",
                f"- duo_streaks: `{counts['duo_streaks']}`",
            ]
            await ctx.reply("\n".join(out))
        except Exception as err:
            await self._fail(ctx, err)

    # ============================================================
    # ✅ TEST / DEV COMMANDS (dangerous) — use for debugging only
    # ============================================================

    async def _today_key(self, guild_id: int, now: int) -> int:
        cfg = await self.repos.get_effective_config(guild_id, self.settings)
        return day_key_from_utc_ts(now, str(cfg["default_tz"]), int(cfg["grace_hour_local"]))

    @commands.command(name="test_add_today")
    @commands.guild_only()
    @admin_or_owner()
    async def test_add_today(self, ctx: commands.Context, user_a: discord.Member, user_b: discord.Member, amount: str):
        """
        TEST: adds overlap seconds to TODAY for a duo.
        Usage:
          !test_add_today @a @b 60
          !test_add_today @a @b 3m
        """
        try:
            if not self._require_repos():
                return await ctx.reply("repos not available.")
            if user_a.bot or user_b.bot or user_a.id == user_b.id:
                return await ctx.reply("Pick two different real users.")

            gid = ctx.guild.id
            now = now_utc_ts()
            dk = await self._today_key(gid, now)
            secs = max(0, _parse_seconds(amount))

            duo_id = await self.repos.get_or_create_duo(gid, user_a.id, user_b.id, now)
            total = await self.repos.add_duo_daily_seconds(gid, duo_id, dk, secs, now)

            await ctx.reply(f"✅ TEST added `{secs}` sec to today. New today total=`{total}` sec (day_key `{dk}`).")
        except Exception as err:
            await self._fail(ctx, err)

    @commands.command(name="test_set_today")
    @commands.guild_only()
    @admin_or_owner()
    async def test_set_today(self, ctx: commands.Context, user_a: discord.Member, user_b: discord.Member, amount: str):
        """
        TEST: sets TODAY overlap seconds exactly.
        Usage:
          !test_set_today @a @b 300
          !test_set_today @a @b 10m
        """
        try:
            if not self._require_repos():
                return await ctx.reply("repos not available.")
            if user_a.bot or user_b.bot or user_a.id == user_b.id:
                return await ctx.reply("Pick two different real users.")

            gid = ctx.guild.id
            now = now_utc_ts()
            dk = await self._today_key(gid, now)
            secs = max(0, _parse_seconds(amount))

            duo_id = await self.repos.get_or_create_duo(gid, user_a.id, user_b.id, now)
            conn = await self.repos.raw_conn(gid)

            await conn.execute(
                """
                INSERT INTO duo_daily (duo_id, day_key, overlap_seconds, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(duo_id, day_key)
                DO UPDATE SET overlap_seconds=excluded.overlap_seconds, updated_at=excluded.updated_at
                """,
                (int(duo_id), int(dk), int(secs), int(now)),
            )
            await conn.commit()

            await ctx.reply(f"✅ TEST set today overlap_seconds=`{secs}` (day_key `{dk}`) for duo_id `{duo_id}`.")
        except Exception as err:
            await self._fail(ctx, err)

    @commands.command(name="test_set_day")
    @commands.guild_only()
    @admin_or_owner()
    async def test_set_day(self, ctx: commands.Context, user_a: discord.Member, user_b: discord.Member, day_key: int, amount: str):
        """
        TEST: sets overlap seconds for a specific day_key (date.toordinal()).
        Usage:
          !test_set_day @a @b 739300 600
        """
        try:
            if not self._require_repos():
                return await ctx.reply("repos not available.")
            if user_a.bot or user_b.bot or user_a.id == user_b.id:
                return await ctx.reply("Pick two different real users.")

            gid = ctx.guild.id
            now = now_utc_ts()
            secs = max(0, _parse_seconds(amount))

            duo_id = await self.repos.get_or_create_duo(gid, user_a.id, user_b.id, now)
            conn = await self.repos.raw_conn(gid)

            await conn.execute(
                """
                INSERT INTO duo_daily (duo_id, day_key, overlap_seconds, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(duo_id, day_key)
                DO UPDATE SET overlap_seconds=excluded.overlap_seconds, updated_at=excluded.updated_at
                """,
                (int(duo_id), int(day_key), int(secs), int(now)),
            )
            await conn.commit()

            await ctx.reply(f"✅ TEST set day_key `{day_key}` overlap_seconds=`{secs}` for duo_id `{duo_id}`.")
        except Exception as err:
            await self._fail(ctx, err)

    @commands.command(name="test_set_streak")
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
        """
        TEST: force-set streak row values.
        Usage:
          !test_set_streak @a @b 5 12 739300
        """
        try:
            if not self._require_repos():
                return await ctx.reply("repos not available.")
            if user_a.bot or user_b.bot or user_a.id == user_b.id:
                return await ctx.reply("Pick two different real users.")

            gid = ctx.guild.id
            now = now_utc_ts()

            duo_id = await self.repos.get_or_create_duo(gid, user_a.id, user_b.id, now)
            conn = await self.repos.raw_conn(gid)

            await conn.execute(
                """
                INSERT INTO duo_streaks (duo_id, current_streak, longest_streak, last_completed_day_key, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(duo_id)
                DO UPDATE SET
                  current_streak=excluded.current_streak,
                  longest_streak=excluded.longest_streak,
                  last_completed_day_key=excluded.last_completed_day_key,
                  updated_at=excluded.updated_at
                """,
                (int(duo_id), int(current_streak), int(longest_streak), int(last_completed_day_key), int(now)),
            )
            await conn.commit()

            await ctx.reply(
                f"✅ TEST set streaks for duo_id `{duo_id}`:\n"
                f"- current={current_streak}\n- longest={longest_streak}\n- last_completed_day_key={last_completed_day_key}"
            )
        except Exception as err:
            await self._fail(ctx, err)

    @commands.command(name="test_clear_duo")
    @commands.guild_only()
    @admin_or_owner()
    async def test_clear_duo(self, ctx: commands.Context, user_a: discord.Member, user_b: discord.Member):
        """
        TEST: deletes a specific duo and all its rows.
        Usage:
          !test_clear_duo @a @b
        """
        try:
            if not self._require_repos():
                return await ctx.reply("repos not available.")
            if user_a.bot or user_b.bot or user_a.id == user_b.id:
                return await ctx.reply("Pick two different real users.")

            gid = ctx.guild.id
            now = now_utc_ts()
            duo_id = await self.repos.get_or_create_duo(gid, user_a.id, user_b.id, now)
            conn = await self.repos.raw_conn(gid)

            await conn.execute("DELETE FROM duo_daily WHERE duo_id=?", (int(duo_id),))
            await conn.execute("DELETE FROM duo_streaks WHERE duo_id=?", (int(duo_id),))
            await conn.execute("DELETE FROM duos WHERE duo_id=?", (int(duo_id),))
            await conn.commit()

            await ctx.reply(f"✅ TEST cleared duo_id `{duo_id}` and all associated rows.")
        except Exception as err:
            await self._fail(ctx, err)

    # ---------- DM TESTS (viewable embeds) ----------

    async def _dm_embed(self, member: discord.Member, embed: discord.Embed) -> bool:
        try:
            await member.send(embed=embed)
            return True
        except Exception:
            return False

    @commands.command(name="test_dm_restore")
    @commands.guild_only()
    @admin_or_owner()
    async def test_dm_restore(self, ctx: commands.Context, member: discord.Member):
        """
        TEST: sends a restore-available DM (white_fire) as an embed.
        Usage:
          !test_dm_restore @user
        """
        try:
            embed = discord.Embed(
                title=f"{emoji('white_fire')} Streak Restore Available",
                description="Your duo streak ended, but you can still restore it.",
            )
            embed.add_field(name="What to do", value="Hop in VC with your duo before the restore window ends.", inline=False)
            embed.set_footer(text="(test DM)")

            ok = await self._dm_embed(member, embed)
            await ctx.reply("✅ Restore DM sent." if ok else "❌ Could not DM (user closed DMs?)")
        except Exception as err:
            await self._fail(ctx, err)

    @commands.command(name="test_dm_ice")
    @commands.guild_only()
    @admin_or_owner()
    async def test_dm_ice(self, ctx: commands.Context, member: discord.Member):
        """
        TEST: sends a restore-expired DM (ice) as an embed.
        Usage:
          !test_dm_ice @user
        """
        try:
            embed = discord.Embed(
                title=f"{emoji('ice')} Streak Lost",
                description="Restore window expired. This streak can’t be restored anymore.",
            )
            embed.set_footer(text="(test DM)")

            ok = await self._dm_embed(member, embed)
            await ctx.reply("✅ Ice DM sent." if ok else "❌ Could not DM (user closed DMs?)")
        except Exception as err:
            await self._fail(ctx, err)

    @commands.command(name="test_dm_text")
    @commands.guild_only()
    @admin_or_owner()
    async def test_dm_text(self, ctx: commands.Context, member: discord.Member, *, message: str):
        """
        TEST: send a custom DM message (plain text).
        Usage:
          !test_dm_text @user hello there
        """
        try:
            try:
                await member.send(f"(test DM) {message}")
                ok = True
            except Exception:
                ok = False

            await ctx.reply("✅ sent DM" if ok else "❌ could not DM (user closed DMs?)")
        except Exception as err:
            await self._fail(ctx, err)


async def setup(bot: commands.Bot):
    await bot.add_cog(AdminCog(bot))
