# bot/cogs/streaks.py
import calendar
import discord
from discord.ext import commands
from datetime import date

from bot.core.timecore import now_utc_ts, day_key_from_utc_ts
from bot.ui.formatting import duo_status_embed


class StreaksCog(commands.Cog):
    def __init__(self, bot: commands.Bot, settings, repos):
        self.bot = bot
        self.settings = settings
        self.repos = repos

    def _get_live_duo_from_vc(self, member: discord.Member):
        if not member or not member.voice or not member.voice.channel:
            return None

        ch = member.voice.channel
        humans = [m for m in ch.members if not m.bot]
        if len(humans) != 2:
            return None

        other = humans[0] if humans[1].id == member.id else humans[1]
        if other.id == member.id:
            return None
        return other

    async def _duo_is_private(self, guild_id: int, u1: int, u2: int, default_private: bool) -> bool:
        try:
            conn = await self.repos.raw_conn(guild_id)
            fallback = "1" if default_private else "0"

            cur = await conn.execute(
                """
                SELECT user_id, value
                FROM user_settings
                WHERE key='privacy_private' AND user_id IN (?, ?)
                """,
                (int(u1), int(u2)),
            )
            rows = await cur.fetchall()
            vals = {int(uid): str(val) for uid, val in rows}

            v1 = vals.get(int(u1), fallback)
            v2 = vals.get(int(u2), fallback)
            return (v1 == "1") or (v2 == "1")
        except Exception:
            return False

    async def _can_view_duo(self, ctx: commands.Context, user_a: discord.Member, user_b: discord.Member, cfg: dict) -> bool:
        default_private = bool(cfg.get("privacy_default_private", False))
        admin_can_view = bool(cfg.get("privacy_admin_can_view", True))

        is_private = await self._duo_is_private(ctx.guild.id, user_a.id, user_b.id, default_private)
        if not is_private:
            return True

        if ctx.author.id in (user_a.id, user_b.id):
            return True

        if admin_can_view and isinstance(ctx.author, discord.Member) and ctx.author.guild_permissions.administrator:
            return True

        return False

    async def _send_duo_embed(self, ctx: commands.Context, user_a: discord.Member, user_b: discord.Member):
        if ctx.guild is None:
            return await ctx.reply("This command only works in a server.")

        gid = ctx.guild.id
        now = now_utc_ts()

        cfg = await self.repos.get_effective_config(gid, self.settings)

        # ✅ privacy gate
        if not await self._can_view_duo(ctx, user_a, user_b, cfg):
            return await ctx.reply("🔒 This duo streak is private.")

        default_tz = str(cfg["default_tz"])
        grace_hour = int(cfg["grace_hour_local"])
        min_required = int(cfg["min_overlap_seconds"])
        bar_width = int(cfg["progress_bar_width"])

        heat_met = str(cfg.get("heatmap_met_emoji", "🟥"))
        heat_empty = str(cfg.get("heatmap_empty_emoji", "⬜"))

        today_key = day_key_from_utc_ts(now, default_tz, grace_hour)

        # ✅ IMPORTANT: view-only. Do NOT create duo just by checking.
        duo_id = await self.repos.get_duo_id(gid, user_a.id, user_b.id)
        if duo_id is None:
            return await ctx.reply(
                "No streak yet for this duo.\n"
                "Join a VC **with exactly 2 real users** and it’ll start tracking."
            )

        # 0 seconds write = safe read of today total (your repo returns current value)
        today_seconds = await self.repos.add_duo_daily_seconds(gid, duo_id, today_key, 0, now)
        current, longest, _ = await self.repos.get_streak_row(gid, duo_id)

        today = date.today()
        first_day_key = date(today.year, today.month, 1).toordinal()
        last_day_num = calendar.monthrange(today.year, today.month)[1]
        last_day_key = date(today.year, today.month, last_day_num).toordinal()

        day_map = await self.repos.get_duo_day_map(gid, duo_id, first_day_key, last_day_key)
        cs = await self.repos.get_connection_score_seconds(gid, duo_id)

        embed = duo_status_embed(
            user_a=user_a,
            user_b=user_b,
            today_seconds=today_seconds,
            min_required=min_required,
            current_streak=current,
            longest_streak=longest,
            bar_width=bar_width,
            status="active",
            connection_score_seconds=cs,
            heatmap_day_to_secs=day_map,
            heatmap_met_emoji=heat_met,
            heatmap_empty_emoji=heat_empty,
        )

        await ctx.reply(embed=embed)

    # ---------------- commands ----------------

    @commands.command(name="streak")
    @commands.guild_only()
    async def streak(self, ctx: commands.Context, user1: discord.Member = None, user2: discord.Member = None):
        if user1 is None and user2 is None:
            if not isinstance(ctx.author, discord.Member):
                return await ctx.reply("Usage: `!streak @user1`")

            other = self._get_live_duo_from_vc(ctx.author)
            if other is None:
                return await ctx.reply("Usage: `!streak @user1` (or join a VC with exactly 1 other real user)")

            a, b = ctx.author, other

        elif user1 is not None and user2 is None:
            a, b = ctx.author, user1

        else:
            a, b = user1, user2

        if a is None or b is None:
            return await ctx.reply("Usage: `!streak @user1` or `!streak @user1 @user2`")
        if a.bot or b.bot:
            return await ctx.reply("Bots don't count for streaks.")
        if a.id == b.id:
            return await ctx.reply("Pick two different users.")

        await self._send_duo_embed(ctx, a, b)

    @commands.command(name="progress")
    @commands.guild_only()
    async def progress(self, ctx: commands.Context):
        if not isinstance(ctx.author, discord.Member):
            return await ctx.reply("This command only works for server members.")

        other = self._get_live_duo_from_vc(ctx.author)
        if other is None:
            return await ctx.reply("You need to be in a VC with exactly **1 other real user** to use `!progress`.")

        await self._send_duo_embed(ctx, ctx.author, other)
