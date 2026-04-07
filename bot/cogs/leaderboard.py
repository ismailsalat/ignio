from __future__ import annotations

from typing import Any

import discord
from discord.ext import commands

from bot.ui.help_embeds import leaderboard_help_embed


class LeaderboardCog(commands.Cog):
    def __init__(self, bot: commands.Bot, settings, repos):
        self.bot = bot
        self.settings = settings
        self.repos = repos

    # ---------------- helpers ----------------

    def _get_prefix(self) -> str:
        try:
            p = getattr(self.bot, "command_prefix", None)
            if isinstance(p, str) and p.strip():
                return p.strip()
        except Exception:
            pass
        return "!"

    async def _duo_is_private(self, guild_id: int, u1: int, u2: int, default_private: bool) -> bool:
        v1 = await self.repos.get_user_setting_bool(
            guild_id=guild_id,
            user_id=u1,
            key="privacy_private",
            default=default_private,
        )
        v2 = await self.repos.get_user_setting_bool(
            guild_id=guild_id,
            user_id=u2,
            key="privacy_private",
            default=default_private,
        )
        return v1 or v2

    def _fmt_duration(self, seconds: int) -> str:
        seconds = max(0, int(seconds))
        h = seconds // 3600
        m = (seconds % 3600) // 60
        s = seconds % 60

        if h > 0 and m > 0:
            return f"{h}h {m}m"
        if h > 0:
            return f"{h}h"
        if m > 0:
            return f"{m}m"
        return f"{s}s"

    def _duo_label(self, guild: discord.Guild, user_ids: list[int]) -> str:
        members: list[str] = []

        for user_id in user_ids[:2]:
            member = guild.get_member(int(user_id))
            if member is not None:
                members.append(member.mention)
            else:
                members.append(f"User {user_id}")

        if len(members) == 2:
            return f"{members[0]} + {members[1]}"
        if len(members) == 1:
            return members[0]
        return "Unknown duo"

    async def _filter_public_duos(
        self,
        guild: discord.Guild,
        rows: list[dict[str, Any]],
    ) -> list[tuple[dict[str, Any], list[int]]]:
        cfg = await self.repos.get_effective_config(guild.id, self.settings)
        default_private = bool(cfg.get("privacy_default_private", 0))

        public_rows: list[tuple[dict[str, Any], list[int]]] = []

        for row in rows:
            streak_id = int(row["streak_id"])
            members = await self.repos.get_streak_members(streak_id)
            if len(members) != 2:
                continue

            u1, u2 = sorted(int(x) for x in members)
            if await self._duo_is_private(guild.id, u1, u2, default_private):
                continue

            public_rows.append((row, [u1, u2]))

        return public_rows

    def _build_rank_lines(
        self,
        guild: discord.Guild,
        rows: list[tuple[dict[str, Any], list[int]]],
        *,
        mode: str,
        limit: int = 10,
    ) -> str:
        if not rows:
            return "No public duos found yet."

        lines: list[str] = []

        for idx, (row, members) in enumerate(rows[:limit], start=1):
            duo = self._duo_label(guild, members)

            if mode == "current":
                value = f"`{int(row['current_streak'])}d`"
            elif mode == "best":
                value = f"`{int(row['longest_streak'])}d`"
            elif mode == "score":
                value = f"`{self._fmt_duration(int(row['connection_score']))}`"
            else:
                value = "`—`"

            lines.append(f"**#{idx}** {duo} — {value}")

        return "\n".join(lines)

    async def _send_overview(self, ctx: commands.Context):
        guild = ctx.guild

        current_rows = await self.repos.top_by_current_streak(
            guild_id=guild.id,
            limit=5,
            streak_type="duo",
        )
        best_rows = await self.repos.top_by_longest_streak(
            guild_id=guild.id,
            limit=5,
            streak_type="duo",
        )
        score_rows = await self.repos.top_by_connection_score(
            guild_id=guild.id,
            limit=5,
            streak_type="duo",
        )

        current_public = await self._filter_public_duos(guild, current_rows)
        best_public = await self._filter_public_duos(guild, best_rows)
        score_public = await self._filter_public_duos(guild, score_rows)

        embed = discord.Embed(
            title="📊 Leaderboards",
            description="Public duo rankings for this server.",
        )

        embed.add_field(
            name="🔥 Current",
            value=self._build_rank_lines(guild, current_public, mode="current", limit=5),
            inline=False,
        )

        embed.add_field(
            name="🏆 Best",
            value=self._build_rank_lines(guild, best_public, mode="best", limit=5),
            inline=False,
        )

        embed.add_field(
            name="🤝 Score",
            value=self._build_rank_lines(guild, score_public, mode="score", limit=5),
            inline=False,
        )

        p = self._get_prefix()
        embed.set_footer(text=f"Use {p}lb streak | {p}lb best | {p}lb cs")
        await ctx.reply(embed=embed)

    async def _send_current_lb(self, ctx: commands.Context):
        guild = ctx.guild

        rows = await self.repos.top_by_current_streak(
            guild_id=guild.id,
            limit=10,
            streak_type="duo",
        )
        public_rows = await self._filter_public_duos(guild, rows)

        embed = discord.Embed(
            title="🔥 Current Streak Leaderboard",
            description=self._build_rank_lines(guild, public_rows, mode="current", limit=10),
        )
        embed.set_footer(text=f"Use {self._get_prefix()}lb best or {self._get_prefix()}lb cs")
        await ctx.reply(embed=embed)

    async def _send_best_lb(self, ctx: commands.Context):
        guild = ctx.guild

        rows = await self.repos.top_by_longest_streak(
            guild_id=guild.id,
            limit=10,
            streak_type="duo",
        )
        public_rows = await self._filter_public_duos(guild, rows)

        embed = discord.Embed(
            title="🏆 Best Streak Leaderboard",
            description=self._build_rank_lines(guild, public_rows, mode="best", limit=10),
        )
        embed.set_footer(text=f"Use {self._get_prefix()}lb streak or {self._get_prefix()}lb cs")
        await ctx.reply(embed=embed)

    async def _send_score_lb(self, ctx: commands.Context):
        guild = ctx.guild

        rows = await self.repos.top_by_connection_score(
            guild_id=guild.id,
            limit=10,
            streak_type="duo",
        )
        public_rows = await self._filter_public_duos(guild, rows)

        embed = discord.Embed(
            title="🤝 Connection Score Leaderboard",
            description=self._build_rank_lines(guild, public_rows, mode="score", limit=10),
        )
        embed.set_footer(text=f"Use {self._get_prefix()}lb streak or {self._get_prefix()}lb best")
        await ctx.reply(embed=embed)

    # ---------------- commands ----------------

    @commands.group(name="lb", aliases=["leaderboard"], invoke_without_command=True)
    @commands.guild_only()
    async def lb_group(self, ctx: commands.Context):
        return await self._send_overview(ctx)

    @lb_group.command(name="help")
    @commands.guild_only()
    async def lb_help(self, ctx: commands.Context):
        return await ctx.reply(embed=leaderboard_help_embed(ctx))

    @lb_group.command(name="streak")
    @commands.guild_only()
    async def lb_streak(self, ctx: commands.Context):
        return await self._send_current_lb(ctx)

    @lb_group.command(name="current")
    @commands.guild_only()
    async def lb_current(self, ctx: commands.Context):
        return await self._send_current_lb(ctx)

    @lb_group.command(name="best")
    @commands.guild_only()
    async def lb_best(self, ctx: commands.Context):
        return await self._send_best_lb(ctx)

    @lb_group.command(name="record")
    @commands.guild_only()
    async def lb_record(self, ctx: commands.Context):
        return await self._send_best_lb(ctx)

    @lb_group.command(name="cs")
    @commands.guild_only()
    async def lb_cs(self, ctx: commands.Context):
        return await self._send_score_lb(ctx)

    @lb_group.command(name="score")
    @commands.guild_only()
    async def lb_score(self, ctx: commands.Context):
        return await self._send_score_lb(ctx)

    # ---------------- legacy hidden cmds ----------------

    @commands.command(name="streaklb", hidden=True)
    @commands.guild_only()
    async def streaklb(self, ctx: commands.Context):
        return await self._send_current_lb(ctx)

    @commands.command(name="bestlb", hidden=True)
    @commands.guild_only()
    async def bestlb(self, ctx: commands.Context):
        return await self._send_best_lb(ctx)

    @commands.command(name="cslb", hidden=True)
    @commands.guild_only()
    async def cslb(self, ctx: commands.Context):
        return await self._send_score_lb(ctx)