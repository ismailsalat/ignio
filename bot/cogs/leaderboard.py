# bot/cogs/leaderboard.py
from __future__ import annotations

import discord
from discord.ext import commands

from bot.ui.help_embeds import leaderboard_help_embed


def fmt_hms(seconds: int) -> str:
    seconds = max(0, int(seconds))
    h = seconds // 3600
    m = (seconds % 3600) // 60

    if h > 0:
        return f"{h}h {m}m"
    if m > 0:
        return f"{m}m"
    return f"{seconds}s"


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

    def _help_hint(self) -> str:
        return f"Need help? Use `{self._get_prefix()}lb help`."

    async def _soft_fail(self, ctx: commands.Context, msg: str):
        return await ctx.reply(f"{msg}\n{self._help_hint()}")

    async def _send_lb_help(self, ctx: commands.Context):
        return await ctx.reply(embed=leaderboard_help_embed(ctx))

    def _member_label(self, guild: discord.Guild, user_id: int) -> str:
        member = guild.get_member(user_id)
        if member is None:
            return f"`{user_id}`"
        return member.mention

    async def _duo_name(self, guild: discord.Guild, streak_id: int) -> str:
        user_ids = await self.repos.get_streak_members(streak_id)
        if len(user_ids) != 2:
            return f"`streak {streak_id}`"

        a = self._member_label(guild, user_ids[0])
        b = self._member_label(guild, user_ids[1])
        return f"{a} + {b}"

    async def _duo_is_private(self, guild_id: int, streak_id: int, default_private: bool) -> bool:
        user_ids = await self.repos.get_streak_members(streak_id)
        if len(user_ids) != 2:
            return False

        v1 = await self.repos.get_user_setting_bool(
            guild_id=guild_id,
            user_id=user_ids[0],
            key="privacy_private",
            default=default_private,
        )
        v2 = await self.repos.get_user_setting_bool(
            guild_id=guild_id,
            user_id=user_ids[1],
            key="privacy_private",
            default=default_private,
        )
        return v1 or v2

    async def _build_lines(
        self,
        ctx: commands.Context,
        rows: list[dict],
        *,
        mode: str,
        limit: int,
    ) -> list[str]:
        guild_id = ctx.guild.id
        cfg = await self.repos.get_effective_config(guild_id, self.settings)
        default_private = bool(cfg.get("privacy_default_private", 0))

        lines: list[str] = []
        pos = 0

        for row in rows:
            streak_id = int(row["streak_id"])

            # leaderboard is duo-only for now
            if str(row["streak_type"]) != "duo":
                continue

            if await self._duo_is_private(guild_id, streak_id, default_private):
                continue

            duo_name = await self._duo_name(ctx.guild, streak_id)

            if mode == "streak":
                value = f'{int(row["current_streak"])}d'
            elif mode == "best":
                value = f'{int(row["longest_streak"])}d'
            else:
                value = fmt_hms(int(row["connection_score"]))

            pos += 1
            lines.append(f"**#{pos}** {duo_name} — **{value}**")

            if pos >= limit:
                break

        if not lines:
            return ["No public duos yet."]

        return lines

    def _simple_embed(self, title: str, description: str) -> discord.Embed:
        return discord.Embed(
            title=title,
            description=description,
        )

    # ---------------- views ----------------

    async def _send_current_lb(self, ctx: commands.Context):
        rows = await self.repos.top_by_current_streak(ctx.guild.id, limit=25, streak_type="duo")
        lines = await self._build_lines(ctx, rows, mode="streak", limit=10)

        embed = self._simple_embed(
            "🔥 Current Streak Leaderboard",
            "\n".join(lines),
        )
        embed.set_footer(text=f"Use {self._get_prefix()}lb best or {self._get_prefix()}lb cs")
        return await ctx.reply(embed=embed)

    async def _send_best_lb(self, ctx: commands.Context):
        rows = await self.repos.top_by_longest_streak(ctx.guild.id, limit=25, streak_type="duo")
        lines = await self._build_lines(ctx, rows, mode="best", limit=10)

        embed = self._simple_embed(
            "🏆 Best Streak Leaderboard",
            "\n".join(lines),
        )
        embed.set_footer(text=f"Use {self._get_prefix()}lb streak or {self._get_prefix()}lb cs")
        return await ctx.reply(embed=embed)

    async def _send_cs_lb(self, ctx: commands.Context):
        rows = await self.repos.top_by_connection_score(ctx.guild.id, limit=25, streak_type="duo")
        lines = await self._build_lines(ctx, rows, mode="cs", limit=10)

        embed = self._simple_embed(
            "🤝 Connection Score Leaderboard",
            "\n".join(lines),
        )
        embed.set_footer(text=f"Use {self._get_prefix()}lb streak or {self._get_prefix()}lb best")
        return await ctx.reply(embed=embed)

    async def _send_overview(self, ctx: commands.Context):
        gid = ctx.guild.id

        current_rows = await self.repos.top_by_current_streak(gid, limit=10, streak_type="duo")
        best_rows = await self.repos.top_by_longest_streak(gid, limit=10, streak_type="duo")
        cs_rows = await self.repos.top_by_connection_score(gid, limit=10, streak_type="duo")

        current_lines = await self._build_lines(ctx, current_rows, mode="streak", limit=5)
        best_lines = await self._build_lines(ctx, best_rows, mode="best", limit=5)
        cs_lines = await self._build_lines(ctx, cs_rows, mode="cs", limit=5)

        embed = discord.Embed(title="📊 Leaderboards")
        embed.add_field(name="🔥 Current", value="\n".join(current_lines)[:1024], inline=False)
        embed.add_field(name="🏆 Best", value="\n".join(best_lines)[:1024], inline=False)
        embed.add_field(name="🤝 Score", value="\n".join(cs_lines)[:1024], inline=False)
        embed.set_footer(text=f"Use {self._get_prefix()}lb streak | {self._get_prefix()}lb best | {self._get_prefix()}lb cs")

        return await ctx.reply(embed=embed)

    # ---------------- commands ----------------

    @commands.command(name="lb", aliases=["leaderboard"])
    @commands.guild_only()
    async def lb(self, ctx: commands.Context, kind: str | None = None):
        kind = (kind or "").strip().lower()

        if kind in ("help", "h", "?"):
            return await self._send_lb_help(ctx)

        if kind in ("", "all", "overview"):
            return await self._send_overview(ctx)

        if kind in ("streak", "current"):
            return await self._send_current_lb(ctx)

        if kind in ("best", "record"):
            return await self._send_best_lb(ctx)

        if kind in ("cs", "score", "connection"):
            return await self._send_cs_lb(ctx)

        return await self._soft_fail(ctx, "Invalid option.")

    @commands.command(name="streaklb", hidden=True)
    @commands.guild_only()
    async def streaklb(self, ctx: commands.Context, kind: str = "streak"):
        kind = (kind or "streak").strip().lower()
        if kind in ("best", "record"):
            return await self.lb(ctx, "best")
        return await self.lb(ctx, "streak")

    @commands.command(name="cslb", hidden=True)
    @commands.guild_only()
    async def cslb(self, ctx: commands.Context):
        return await self.lb(ctx, "cs")