# bot/cogs/leaderboard.py
from __future__ import annotations

import discord
from discord.ext import commands

from bot.config import e
from bot.core.timecore import now_utc_ts


def fmt_hms(seconds: int) -> str:
    seconds = max(0, int(seconds))
    h = seconds // 3600
    m = (seconds % 3600) // 60
    s = seconds % 60
    if h > 0:
        return f"{h}h {m}m"
    if m > 0:
        return f"{m}m"
    return f"{s}s"


class LeaderboardCog(commands.Cog):
    def __init__(self, bot: commands.Bot, settings, repos):
        self.bot = bot
        self.settings = settings
        self.repos = repos

    # ---------------- helpers ----------------

    def _name_for_duo(self, guild: discord.Guild, u1: int, u2: int) -> str:
        m1 = guild.get_member(u1)
        m2 = guild.get_member(u2)
        a = m1.mention if m1 else f"`{u1}`"
        b = m2.mention if m2 else f"`{u2}`"
        return f"{a} + {b}"

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
        """
        Privacy policy:
          If either user has privacy_private=1 => duo is private.
          If no override exists => fallback to default_private.
        """
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
            # if table isn't there yet, fail open
            return False

    async def _build_list_lines(self, ctx: commands.Context, rows, *, kind: str, limit: int) -> list[str]:
        """
        rows are expected like [(duo_id, value), ...]
        kind: 'streak' | 'best' | 'cs'
        Applies privacy filtering (private duos are excluded).
        """
        gid = ctx.guild.id
        cfg = await self.repos.get_effective_config(gid, self.settings)
        default_private = bool(cfg.get("privacy_default_private", False))

        lines: list[str] = []
        pos = 0

        for duo_id, val in rows:
            users = await self.repos.get_duo_users(gid, duo_id)
            if not users:
                continue

            u1, u2 = users

            # ✅ privacy filter for leaderboards
            if await self._duo_is_private(gid, u1, u2, default_private):
                continue

            pos += 1
            duo_name = self._name_for_duo(ctx.guild, u1, u2)

            if kind == "cs":
                shown = fmt_hms(val)
            else:
                shown = f"{int(val)} days"

            lines.append(f"**#{pos}** {duo_name} — **{shown}**")

            if pos >= limit:
                break

        if not lines:
            return ["No public duos yet."]

        return lines

    async def _try_add_rank_footer(self, ctx: commands.Context, embed: discord.Embed, kind: str):
        """
        Optional: show your VC duo rank if repo supports rank methods.
        Won't crash if not implemented.
        """
        if not isinstance(ctx.author, discord.Member):
            return

        other = self._get_live_duo_from_vc(ctx.author)
        if other is None:
            return

        get_or_create = getattr(self.repos, "get_or_create_duo", None)
        if not get_or_create:
            return

        gid = ctx.guild.id
        duo_id = await get_or_create(gid, ctx.author.id, other.id, now_utc_ts())

        rank_fn = None
        if kind == "streak":
            rank_fn = getattr(self.repos, "rank_for_current_streak", None)
        elif kind == "best":
            rank_fn = getattr(self.repos, "rank_for_best_streak", None)
        elif kind == "cs":
            rank_fn = getattr(self.repos, "rank_for_duo_connection_score", None)

        if not rank_fn:
            return

        try:
            rank = await rank_fn(gid, duo_id)
        except Exception:
            return

        if rank:
            embed.set_footer(text=f"Your VC duo rank: #{rank}")

    # ---------------- commands ----------------

    @commands.command(name="streaklb")
    @commands.guild_only()
    async def streaklb(self, ctx: commands.Context, kind: str = "streak"):
        """
        Usage:
          !streaklb          -> top current streak
          !streaklb streak   -> top current streak
          !streaklb best     -> top best streak
        """
        gid = ctx.guild.id
        kind = (kind or "streak").lower().strip()

        if kind in ("streak", "current"):
            rows = await self.repos.top_by_current_streak(gid, limit=50)
            title = f"{e('fire')} Streak Leaderboard — Current"
            rank_kind = "streak"
        elif kind in ("best", "record"):
            rows = await self.repos.top_by_best_streak(gid, limit=50)
            title = f"{e('fire')} Streak Leaderboard — Best"
            rank_kind = "best"
        else:
            return await ctx.reply("Use: `!streaklb` | `!streaklb best`")

        embed = discord.Embed(title=title)
        if not rows:
            embed.description = "No data yet. Hop in VC together first."
            return await ctx.reply(embed=embed)

        lines = await self._build_list_lines(ctx, rows, kind=rank_kind, limit=10)
        embed.description = "\n".join(lines)[:4000]

        await self._try_add_rank_footer(ctx, embed, rank_kind)
        await ctx.reply(embed=embed)

    @commands.command(name="cslb")
    @commands.guild_only()
    async def cslb(self, ctx: commands.Context):
        """
        Usage:
          !cslb  -> top connection score
        """
        gid = ctx.guild.id
        rows = await self.repos.top_by_connection_score(gid, limit=50)

        embed = discord.Embed(title=f"{e('fire')} Connection Score Leaderboard")
        if not rows:
            embed.description = "No data yet. Hop in VC together first."
            return await ctx.reply(embed=embed)

        lines = await self._build_list_lines(ctx, rows, kind="cs", limit=10)
        embed.description = "\n".join(lines)[:4000]

        await self._try_add_rank_footer(ctx, embed, "cs")
        await ctx.reply(embed=embed)

    @commands.command(name="lb")
    @commands.guild_only()
    async def lb(self, ctx: commands.Context, kind: str | None = None):
        """
        Usage:
          !lb           -> combined overview (top 5 of each)
          !lb streak    -> same as streaklb current
          !lb best      -> same as streaklb best
          !lb cs        -> same as cslb
        """
        gid = ctx.guild.id
        kind = (kind or "").lower().strip()

        if kind in ("streak", "current"):
            return await self.streaklb(ctx, "streak")
        if kind in ("best", "record"):
            return await self.streaklb(ctx, "best")
        if kind in ("cs", "score", "connection"):
            return await self.cslb(ctx)

        cur_rows = await self.repos.top_by_current_streak(gid, limit=50)
        best_rows = await self.repos.top_by_best_streak(gid, limit=50)
        cs_rows = await self.repos.top_by_connection_score(gid, limit=50)

        embed = discord.Embed(
            title=f"{e('fire')} Ignio Leaderboards",
            description="Top **public** duos across streaks + connection score.",
        )

        if not (cur_rows or best_rows or cs_rows):
            embed.description = "No data yet. Hop in VC together first."
            return await ctx.reply(embed=embed)

        cur_lines = await self._build_list_lines(ctx, cur_rows, kind="streak", limit=5) if cur_rows else ["No data"]
        best_lines = await self._build_list_lines(ctx, best_rows, kind="best", limit=5) if best_rows else ["No data"]
        cs_lines = await self._build_list_lines(ctx, cs_rows, kind="cs", limit=5) if cs_rows else ["No data"]

        embed.add_field(name="🔥 Current Streak", value="\n".join(cur_lines)[:1024], inline=False)
        embed.add_field(name="🏆 Best Streak", value="\n".join(best_lines)[:1024], inline=False)
        embed.add_field(name="🤝 Connection Score", value="\n".join(cs_lines)[:1024], inline=False)

        embed.set_footer(text="Use !streaklb | !streaklb best | !cslb for full top 10")
        await ctx.reply(embed=embed)
