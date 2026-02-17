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
        """
        If member is in a VC with exactly 1 other REAL user, return that other user.
        Otherwise return None.
        """
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

    async def _send_duo_embed(
        self,
        ctx: commands.Context,
        user_a: discord.Member,
        user_b: discord.Member,
    ):
        # must be in a server
        if ctx.guild is None:
            return await ctx.reply("This command only works in a server.")

        gid = ctx.guild.id
        now = now_utc_ts()

        # effective config (DB overrides)
        cfg = await self.repos.get_effective_config(gid, self.settings)
        default_tz = str(cfg["default_tz"])
        grace_hour = int(cfg["grace_hour_local"])
        min_required = int(cfg["min_overlap_seconds"])
        bar_width = int(cfg["progress_bar_width"])

        # day_key respects grace window + tz
        today_key = day_key_from_utc_ts(now, default_tz, grace_hour)

        # create duo + read today
        duo_id = await self.repos.get_or_create_duo(gid, user_a.id, user_b.id, now)

        today_seconds = await self.repos.add_duo_daily_seconds(gid, duo_id, today_key, 0, now)
        current, longest, _ = await self.repos.get_streak_row(gid, duo_id)

        # heatmap = current month only
        today = date.today()
        first_day_key = date(today.year, today.month, 1).toordinal()
        last_day_num = calendar.monthrange(today.year, today.month)[1]
        last_day_key = date(today.year, today.month, last_day_num).toordinal()

        day_map = await self.repos.get_duo_day_map(gid, duo_id, first_day_key, last_day_key)

        # connection score (all-time seconds)
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
        )

        await ctx.reply(embed=embed)

    @commands.command(name="streak")
    async def streak(self, ctx: commands.Context, other: discord.Member = None):
        """
        Usage:
          !streak @OtherUser
          !streak   (uses your current VC duo if you're in one)
        """
        # must be in a server
        if ctx.guild is None:
            return await ctx.reply("This command only works in a server.")

        # if no mention, try live VC duo
        if other is None:
            if not isinstance(ctx.author, discord.Member):
                return await ctx.reply("Usage: `!streak @OtherUser`")

            live_other = self._get_live_duo_from_vc(ctx.author)
            if live_other is None:
                return await ctx.reply("Usage: `!streak @OtherUser` (or join a VC with exactly 1 other real user)")
            other = live_other

        # edge cases
        if other.bot:
            return await ctx.reply("Bots don't count for streaks.")
        if other.id == ctx.author.id:
            return await ctx.reply("You can't streak with yourself.")

        await self._send_duo_embed(ctx, ctx.author, other)

    @commands.command(name="progress")
    async def progress(self, ctx: commands.Context):
        """
        Usage:
          !progress
        Shows streak/progress with your current VC duo (if you're in one).
        """
        # must be in a server
        if ctx.guild is None:
            return await ctx.reply("This command only works in a server.")

        if not isinstance(ctx.author, discord.Member):
            return await ctx.reply("This command only works for server members.")

        other = self._get_live_duo_from_vc(ctx.author)
        if other is None:
            return await ctx.reply("You need to be in a VC with exactly **1 other real user** to use `!progress`.")

        await self._send_duo_embed(ctx, ctx.author, other)
