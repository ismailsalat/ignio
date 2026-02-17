# bot/cogs/admin.py
from __future__ import annotations

import traceback
import discord
from discord.ext import commands
from datetime import datetime, timezone

from bot.core.timecore import now_utc_ts, day_key_from_utc_ts


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


def _short_err(e: Exception) -> str:
    return f"{type(e).__name__}: {e}"


class AdminCog(commands.Cog):
    """
    Admin-only debug commands for Ignio.
    Works with manual loader injection.
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
            self.bot.get_cog("VcTrackerCog")  # ✅ your actual class name
            or self.bot.get_cog("VCTrackerCog")
            or self.bot.get_cog("VCTracker")
            or self.bot.get_cog("VcTracker")
            or self.bot.get_cog("vc_tracker")
        )

    async def _fail(self, ctx: commands.Context, e: Exception):
        # print full traceback in terminal
        print("[Ignio][AdminCog] command error:", _short_err(e))
        traceback.print_exc()

        # respond in discord (short)
        try:
            await ctx.reply(f"❌ `{_short_err(e)}`")
        except Exception:
            pass

    # ---------- BASIC ----------

    @commands.command(name="ping")
    @commands.guild_only()
    @commands.has_permissions(administrator=True)
    async def ping(self, ctx: commands.Context):
        try:
            await ctx.reply(f"🏓 pong ({round(self.bot.latency * 1000)}ms)")
        except Exception as e:
            await self._fail(ctx, e)

    @commands.command(name="loaded")
    @commands.guild_only()
    @commands.has_permissions(administrator=True)
    async def loaded(self, ctx: commands.Context):
        try:
            cogs = ", ".join(self.bot.cogs.keys()) or "none"
            cmds = ", ".join(sorted([c.name for c in self.bot.commands]))
            await ctx.reply(f"**Cogs:** {cogs}\n**Commands:** {cmds}")
        except Exception as e:
            await self._fail(ctx, e)

    # ---------- CONFIG (DB-backed) ----------

    @commands.command(name="ignio_config")
    @commands.guild_only()
    @commands.has_permissions(administrator=True)
    async def ignio_config(self, ctx: commands.Context):
        try:
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
            )
            await ctx.reply(msg)
        except Exception as e:
            await self._fail(ctx, e)

    @commands.command(name="set_min")
    @commands.guild_only()
    @commands.has_permissions(administrator=True)
    async def set_min(self, ctx: commands.Context, value: str):
        """
        !set_min 180
        !set_min 3m
        """
        try:
            gid = ctx.guild.id
            now = now_utc_ts()

            seconds = _parse_seconds(value)
            seconds = max(30, min(seconds, 6 * 60 * 60))

            await self.repos.set_config_int(gid, "min_overlap_seconds", seconds, now)

            cfg = await self.repos.get_effective_config(gid, self.settings)
            day_key = day_key_from_utc_ts(now, str(cfg["default_tz"]), int(cfg["grace_hour_local"]))

            updated = await self.repos.recalc_today_all_duos(
                gid,
                day_key,
                int(cfg["min_overlap_seconds"]),
                now,
            )

            await ctx.reply(f"✅ min_overlap_seconds set to `{seconds}` sec. Recalc updated `{updated}` duos today.")
        except Exception as e:
            await self._fail(ctx, e)

    @commands.command(name="set_tick")
    @commands.guild_only()
    @commands.has_permissions(administrator=True)
    async def set_tick(self, ctx: commands.Context, seconds: int):
        try:
            gid = ctx.guild.id
            now = now_utc_ts()

            seconds = max(5, min(int(seconds), 120))
            await self.repos.set_config_int(gid, "tick_seconds", seconds, now)
            await ctx.reply(f"✅ tick_seconds set to `{seconds}` (seconds added per tick).")
        except Exception as e:
            await self._fail(ctx, e)

    @commands.command(name="recalc_today")
    @commands.guild_only()
    @commands.has_permissions(administrator=True)
    async def recalc_today(self, ctx: commands.Context):
        try:
            gid = ctx.guild.id
            now = now_utc_ts()

            cfg = await self.repos.get_effective_config(gid, self.settings)
            day_key = day_key_from_utc_ts(now, str(cfg["default_tz"]), int(cfg["grace_hour_local"]))

            updated = await self.repos.recalc_today_all_duos(
                gid,
                day_key,
                int(cfg["min_overlap_seconds"]),
                now,
            )
            await ctx.reply(f"✅ Recalc done. Updated `{updated}` duos today.")
        except Exception as e:
            await self._fail(ctx, e)

    # ---------- LOOP / TIME ----------

    @commands.command(name="tick_status")
    @commands.guild_only()
    @commands.has_permissions(administrator=True)
    async def tick_status(self, ctx: commands.Context):
        try:
            vc_cog = self._get_vc_cog()
            if not vc_cog:
                return await ctx.reply("VC cog not found (is vc_tracker loaded?)")

            loop = getattr(vc_cog, "tick", None) or getattr(vc_cog, "tick_loop", None)
            if not loop:
                return await ctx.reply("Couldn’t find tick task on VC cog (expected `.tick` or `.tick_loop`).")

            running = loop.is_running()
            await ctx.reply(f"Tick loop running: `{running}`")
        except Exception as e:
            await self._fail(ctx, e)

    @commands.command(name="day_key")
    @commands.guild_only()
    @commands.has_permissions(administrator=True)
    async def day_key_cmd(self, ctx: commands.Context):
        try:
            gid = ctx.guild.id
            now = now_utc_ts()
            cfg = await self.repos.get_effective_config(gid, self.settings)

            day_key = day_key_from_utc_ts(now, str(cfg["default_tz"]), int(cfg["grace_hour_local"]))
            dt_utc = datetime.fromtimestamp(now, tz=timezone.utc).isoformat()

            await ctx.reply(
                f"**Day Key Debug**\n"
                f"- now_utc: `{dt_utc}`\n"
                f"- tz: `{cfg['default_tz']}`\n"
                f"- grace_hour_local: `{cfg['grace_hour_local']}`\n"
                f"- day_key: `{day_key}`"
            )
        except Exception as e:
            await self._fail(ctx, e)

    # ---------- VC STATE ----------

    @commands.command(name="vc_state")
    @commands.guild_only()
    @commands.has_permissions(administrator=True)
    async def vc_state_cmd(self, ctx: commands.Context):
        try:
            gid = ctx.guild.id

            if not self.vc_state:
                return await ctx.reply("vc_state not available (vc_tracker didn’t attach state).")

            channels = getattr(self.vc_state, "channel_members", {}).get(gid, {})
            if not channels:
                return await ctx.reply("No tracked VC channels right now.")

            lines = ["**VC State (runtime)**"]
            for ch_id, members in channels.items():
                ch = ctx.guild.get_channel(ch_id)
                ch_name = ch.name if ch else f"unknown({ch_id})"
                lines.append(f"\n🔊 **{ch_name}** ({ch_id})")
                lines.append(f"Members counted: {len(members)}")
                lines.append("```" + ", ".join(str(m) for m in sorted(members)) + "```")

            await ctx.reply("\n".join(lines)[:1900])
        except Exception as e:
            await self._fail(ctx, e)

    @commands.command(name="vc_buffer")
    @commands.guild_only()
    @commands.has_permissions(administrator=True)
    async def vc_buffer_cmd(self, ctx: commands.Context):
        try:
            if not self.vc_state:
                return await ctx.reply("vc_state not available.")

            now = now_utc_ts()
            gid = ctx.guild.id

            recently_left = getattr(self.vc_state, "recently_left", {})
            kept = []
            for (g_id, u_id), (ch_id, left_ts) in recently_left.items():
                if g_id != gid:
                    continue
                age = now - left_ts
                kept.append((u_id, ch_id, age))

            if not kept:
                return await ctx.reply("No users currently in disconnect buffer.")

            kept.sort(key=lambda x: x[2])
            lines = ["**Disconnect Buffer (runtime)**"]
            for u_id, ch_id, age in kept:
                ch = ctx.guild.get_channel(ch_id)
                ch_name = ch.name if ch else f"unknown({ch_id})"
                lines.append(f"- user `{u_id}` left `{ch_name}` {int(age)}s ago")

            await ctx.reply("\n".join(lines)[:1900])
        except Exception as e:
            await self._fail(ctx, e)

    # ---------- DB HEALTH ----------

    @commands.command(name="db_counts")
    @commands.guild_only()
    @commands.has_permissions(administrator=True)
    async def db_counts(self, ctx: commands.Context):
        try:
            gid = ctx.guild.id
            counts = await self.repos.counts_for_guild(gid)
            out = [
                "**DB Counts (this server)**",
                f"- duos: `{counts['duos']}`",
                f"- duo_daily: `{counts['duo_daily']}`",
                f"- duo_streaks: `{counts['duo_streaks']}`",
            ]
            await ctx.reply("\n".join(out))
        except Exception as e:
            await self._fail(ctx, e)

    @commands.command(name="duo_debug")
    @commands.guild_only()
    @commands.has_permissions(administrator=True)
    async def duo_debug(self, ctx: commands.Context, user_a: discord.Member, user_b: discord.Member):
        try:
            if user_a.id == user_b.id:
                return await ctx.reply("Pick two different users.")

            gid = ctx.guild.id
            now = now_utc_ts()
            cfg = await self.repos.get_effective_config(gid, self.settings)
            day_key = day_key_from_utc_ts(now, str(cfg["default_tz"]), int(cfg["grace_hour_local"]))

            duo_id = await self.repos.get_or_create_duo(gid, user_a.id, user_b.id, now)
            today_seconds = await self.repos.add_duo_daily_seconds(gid, duo_id, day_key, 0, now)
            current, longest, last_completed = await self.repos.get_streak_row(gid, duo_id)

            msg = (
                f"**Duo Debug**\n"
                f"- duo_id: `{duo_id}`\n"
                f"- users: `{user_a.id}` + `{user_b.id}`\n"
                f"- today day_key: `{day_key}`\n"
                f"- today overlap_seconds: `{today_seconds}`\n"
                f"- current_streak: `{current}`\n"
                f"- longest_streak: `{longest}`\n"
                f"- last_completed_day_key: `{last_completed}`\n"
            )
            await ctx.reply(msg)
        except Exception as e:
            await self._fail(ctx, e)

    @commands.command(name="db_last_daily")
    @commands.guild_only()
    @commands.has_permissions(administrator=True)
    async def db_last_daily(self, ctx: commands.Context, user_a: discord.Member, user_b: discord.Member, n: int = 7):
        try:
            if user_a.id == user_b.id:
                return await ctx.reply("Pick two different users.")

            gid = ctx.guild.id
            n = max(1, min(int(n), 30))

            now = now_utc_ts()
            duo_id = await self.repos.get_or_create_duo(gid, user_a.id, user_b.id, now)

            conn = await self.repos.raw_conn(gid)
            cur = await conn.execute(
                """
                SELECT day_key, overlap_seconds, updated_at
                FROM duo_daily
                WHERE duo_id=?
                ORDER BY day_key DESC
                LIMIT ?
                """,
                (duo_id, n),
            )
            rows = await cur.fetchall()

            if not rows:
                return await ctx.reply("No duo_daily rows for that duo yet.")

            lines = [f"**Last {n} duo_daily rows** (duo_id `{duo_id}`)"]
            for dk, secs, updated_at in rows:
                lines.append(f"- day_key `{dk}` | secs `{secs}` | updated_at `{updated_at}`")

            await ctx.reply("\n".join(lines)[:1900])
        except Exception as e:
            await self._fail(ctx, e)

    @commands.command(name="db_reset_guild")
    @commands.guild_only()
    @commands.has_permissions(administrator=True)
    async def db_reset_guild(self, ctx: commands.Context, confirm: str = ""):
        try:
            if confirm != "CONFIRM":
                return await ctx.reply("Type: `!db_reset_guild CONFIRM` (wipes THIS server only)")

            gid = ctx.guild.id
            conn = await self.repos.raw_conn(gid)

            await conn.execute("DELETE FROM duo_daily")
            await conn.execute("DELETE FROM duo_streaks")
            await conn.execute("DELETE FROM duos")
            await conn.commit()

            await ctx.reply("✅ Wiped all Ignio data for this server.")
        except Exception as e:
            await self._fail(ctx, e)
