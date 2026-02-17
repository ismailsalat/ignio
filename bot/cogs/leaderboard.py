# bot/cogs/leaderboard.py
import discord
from discord.ext import commands

from bot.config import e


class LeaderboardCog(commands.Cog):
    def __init__(self, bot: commands.Bot, settings, repos):
        self.bot = bot
        self.settings = settings
        self.repos = repos

    def _name_for_duo(self, guild: discord.Guild, u1: int, u2: int) -> str:
        m1 = guild.get_member(u1)
        m2 = guild.get_member(u2)
        a = m1.mention if m1 else f"`{u1}`"
        b = m2.mention if m2 else f"`{u2}`"
        return f"{a} + {b}"

    @commands.command(name="lb")
    async def lb(self, ctx: commands.Context, kind: str = "streak"):
        """
        Usage:
          !lb streak   -> top current streak
          !lb best     -> top best streak
          !lb cs       -> top connection score
        """
        gid = ctx.guild.id
        kind = (kind or "streak").lower().strip()

        if kind in ("streak", "current"):
            rows = await self.repos.top_by_current_streak(gid, limit=10)
            title = f"{e('fire')} Leaderboard — Current Streak"
            suffix = "days"
        elif kind in ("best", "record"):
            rows = await self.repos.top_by_best_streak(gid, limit=10)
            title = f"{e('fire')} Leaderboard — Best Streak"
            suffix = "days"
        elif kind in ("cs", "score", "connection"):
            rows = await self.repos.top_by_connection_score(gid, limit=10)
            title = f"{e('fire')} Leaderboard — Connection Score"
            suffix = "sec"
        else:
            return await ctx.reply("Use: `!lb streak` | `!lb best` | `!lb cs`")

        embed = discord.Embed(title=title)

        if not rows:
            embed.description = "No data yet. Hop in VC together first."
            return await ctx.reply(embed=embed)

        lines = []
        for i, (duo_id, val) in enumerate(rows, start=1):
            users = await self.repos.get_duo_users(gid, duo_id)
            if not users:
                continue
            u1, u2 = users
            duo_name = self._name_for_duo(ctx.guild, u1, u2)
            lines.append(f"**#{i}** {duo_name} — **{val} {suffix}**")

        embed.description = "\n".join(lines)[:4000]
        await ctx.reply(embed=embed)
