# bot/cogs/sob.py
from __future__ import annotations

import time

import discord
from discord.ext import commands

from bot.services.sob_repo import (
    SobRepo,
    SOB_EMOJIS,
    SNITCH_EXPIRY_SECONDS,
)

# ── server emojis ─────────────────────────────────────────────────────────────
_SOB    = "<:4612win11emojisob:1493190644221480960>"
_HAND   = "<:handsob:1493198316299747419>"
_TOMATO = "<:tomatosob:1493198299140722760>"
_ANTI   = "<:antisob:1493198277674537071>"

_COLOR  = 0xF0B132


# ── utilities ─────────────────────────────────────────────────────────────────

def _mention(guild: discord.Guild, user_id: int) -> str:
    m = guild.get_member(user_id)
    return m.mention if m else f"<@{user_id}>"


def _rank_suffix(n: int) -> str:
    if 11 <= (n % 100) <= 13:
        return f"{n}th"
    return {1: f"{n}st", 2: f"{n}nd", 3: f"{n}rd"}.get(n % 10, f"{n}th")


def _rank_display(count: int, rank: int) -> str:
    if count == 0:
        return "—"
    return _rank_suffix(rank)


def _leader_line(guild: discord.Guild, data: dict | None, badge: str = "") -> str:
    """badge replaces the default sob emoji on the left."""
    if data is None:
        return "—"
    name   = _mention(guild, data["user_id"])
    icon   = badge if badge else _SOB
    return f"{icon} {name} · **{data['count']}**"


def _sobs_until_next(alltime: int, threshold: int, sobs_at_last: int) -> int:
    next_grant = threshold if sobs_at_last == 0 else sobs_at_last + threshold
    return max(0, next_grant - alltime)


def _expiry_text(granted_at: int, now_ts: int) -> str:
    remaining = SNITCH_EXPIRY_SECONDS - (now_ts - granted_at)
    if remaining <= 0:
        return "expired"
    hours = remaining // 3600
    return f"expires in {hours // 24}d" if hours >= 24 else f"expires in {hours}h"


# ── embed builders ────────────────────────────────────────────────────────────

def _personal_embed(
    *,
    user: discord.Member,
    stats: dict,
    rank_today: int,
    rank_week: int,
    rank_alltime: int,
    snitch_row: dict | None,
    snitch_threshold: int,
    now_ts: int,
) -> discord.Embed:

    embed = discord.Embed(
        title=f"{_SOB} Your Sob Stats",
        description=user.mention,
        color=_COLOR,
    )

    t, w, a = stats["sobs_today"], stats["sobs_week"], stats["sobs_alltime"]

    embed.add_field(
        name="Today",
        value=f"{_SOB} **{t}** · {_rank_display(t, rank_today)}",
        inline=True,
    )
    embed.add_field(
        name="This week",
        value=f"{_SOB} **{w}** · {_rank_display(w, rank_week)}",
        inline=True,
    )
    embed.add_field(
        name="All time",
        value=f"{_SOB} **{a}** · {_rank_display(a, rank_alltime)}",
        inline=True,
    )

    has_token = snitch_row is not None and snitch_row["token_available"] == 1

    if has_token:
        expiry    = _expiry_text(snitch_row["token_granted_at"], now_ts)
        token_val = f"{_ANTI} **Ready** · {expiry} · reply to a message with `!ss`"
    else:
        sobs_at_last = snitch_row["sobs_at_last_grant"] if snitch_row else 0
        left         = _sobs_until_next(a, snitch_threshold, sobs_at_last)
        token_val    = f"**{left}** sob{'s' if left != 1 else ''} until next token"

    embed.add_field(
        name=f"{_ANTI} Snitch token",
        value=token_val,
        inline=False,
    )

    embed.set_footer(text=f"Every {snitch_threshold} sobs = 1 token · !sob lb for leaderboard")
    return embed


def _leaderboard_embed(
    *,
    guild: discord.Guild,
    daily_leader: dict | None,
    weekly_leader: dict | None,
    alltime_leader: dict | None,
    top_giver: dict | None,
    top_snitch: dict | None,
) -> discord.Embed:

    embed = discord.Embed(
        title=f"{_SOB} Sob Leaderboard",
        color=_COLOR,
    )

    # today + week get the normal sob emoji, all-time gets the tomato
    embed.add_field(
        name="Today",
        value=_leader_line(guild, daily_leader),
        inline=True,
    )
    embed.add_field(
        name="This week",
        value=_leader_line(guild, weekly_leader),
        inline=True,
    )
    embed.add_field(
        name="All time",
        value=_leader_line(guild, alltime_leader, badge=_TOMATO),
        inline=True,
    )
    embed.add_field(
        name="Top sob giver",
        value=_leader_line(guild, top_giver),
        inline=True,
    )
    embed.add_field(
        name=f"{_ANTI} Top snitch",
        value=_leader_line(guild, top_snitch),
        inline=True,
    )
    embed.add_field(name="\u200b", value="\u200b", inline=True)

    embed.set_footer(text="!sob for your personal stats")
    return embed


# ── cog ───────────────────────────────────────────────────────────────────────

class SobCog(commands.Cog):
    def __init__(self, bot: commands.Bot, settings, sob_repo: SobRepo):
        self.bot      = bot
        self.settings = settings
        self.sob_repo = sob_repo

    def _is_sob_emoji(self, emoji) -> bool:
        name = emoji if isinstance(emoji, str) else getattr(emoji, "name", str(emoji))
        return name in SOB_EMOJIS or str(emoji) in SOB_EMOJIS

    async def _resolve_message(self, channel, message_id: int) -> discord.Message | None:
        if channel is None:
            return None
        try:
            return await channel.fetch_message(message_id)
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            return None

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload: discord.RawReactionActionEvent):
        if not self._is_sob_emoji(payload.emoji):
            return
        if payload.guild_id is None:
            return

        guild = self.bot.get_guild(payload.guild_id)
        if guild is None:
            return

        reactor = guild.get_member(payload.user_id)
        if reactor is None or reactor.bot:
            return

        channel = guild.get_channel(payload.channel_id)
        message = await self._resolve_message(channel, payload.message_id)
        if message is None:
            return
        if message.author.bot:
            return

        target_id = message.author.id
        if target_id == payload.user_id:
            return

        threshold = await self.sob_repo.get_snitch_threshold(payload.guild_id)
        await self.sob_repo.add_sob(
            guild_id=payload.guild_id,
            message_id=payload.message_id,
            reactor_id=payload.user_id,
            target_id=target_id,
            snitch_threshold=threshold,
        )

    @commands.Cog.listener()
    async def on_raw_reaction_remove(self, payload: discord.RawReactionActionEvent):
        if not self._is_sob_emoji(payload.emoji):
            return
        if payload.guild_id is None:
            return

        await self.sob_repo.remove_sob(
            guild_id=payload.guild_id,
            message_id=payload.message_id,
            reactor_id=payload.user_id,
        )

    @commands.group(name="sob", invoke_without_command=True)
    @commands.guild_only()
    async def sob_group(self, ctx: commands.Context):
        guild  = ctx.guild
        user   = ctx.author
        now_ts = int(time.time())

        threshold    = await self.sob_repo.get_snitch_threshold(guild.id)
        stats        = await self.sob_repo.get_user_stats(guild.id, user.id)
        rank_today   = await self.sob_repo.get_user_daily_rank(guild.id, user.id)
        rank_week    = await self.sob_repo.get_user_weekly_rank(guild.id, user.id)
        rank_alltime = await self.sob_repo.get_user_alltime_rank(guild.id, user.id)
        snitch_row   = await self.sob_repo.get_snitch_row(guild.id, user.id)

        embed = _personal_embed(
            user=user,
            stats=stats,
            rank_today=rank_today,
            rank_week=rank_week,
            rank_alltime=rank_alltime,
            snitch_row=snitch_row,
            snitch_threshold=threshold,
            now_ts=now_ts,
        )
        await ctx.reply(embed=embed)

    @sob_group.command(name="lb", aliases=["leaderboard"])
    @commands.guild_only()
    async def sob_lb(self, ctx: commands.Context):
        guild = ctx.guild

        daily_leader   = await self.sob_repo.get_daily_leader(guild.id)
        weekly_leader  = await self.sob_repo.get_weekly_leader(guild.id)
        alltime_leader = await self.sob_repo.get_alltime_leader(guild.id)
        top_giver      = await self.sob_repo.get_top_giver(guild.id)
        top_snitch     = await self.sob_repo.get_top_snitch(guild.id)

        embed = _leaderboard_embed(
            guild=guild,
            daily_leader=daily_leader,
            weekly_leader=weekly_leader,
            alltime_leader=alltime_leader,
            top_giver=top_giver,
            top_snitch=top_snitch,
        )
        await ctx.reply(embed=embed)

    @commands.command(name="ss", aliases=["sobsnitch"])
    @commands.guild_only()
    async def sob_snitch(self, ctx: commands.Context):
        guild  = ctx.guild
        user   = ctx.author
        now_ts = int(time.time())

        ref = ctx.message.reference
        if ref is None:
            await ctx.reply(f"{_ANTI} You need to **reply** to a message to snitch it.", mention_author=False)
            return

        target_msg = ref.resolved
        if not isinstance(target_msg, discord.Message):
            target_msg = await self._resolve_message(ctx.channel, ref.message_id)

        if target_msg is None:
            await ctx.reply(f"{_ANTI} Couldn't find that message.", mention_author=False)
            return
        if target_msg.author.bot:
            await ctx.reply(f"{_ANTI} You can't snitch a bot's message.", mention_author=False)
            return
        if target_msg.author.id == user.id:
            await ctx.reply(f"{_ANTI} You can't snitch your own message.", mention_author=False)
            return

        success, reason, sobs_removed = await self.sob_repo.snitch_message(
            guild_id=guild.id,
            message_id=target_msg.id,
            snitcher_id=user.id,
            target_id=target_msg.author.id,
            now_ts=now_ts,
        )

        if success:
            threshold    = await self.sob_repo.get_snitch_threshold(guild.id)
            snitch_row   = await self.sob_repo.get_snitch_row(guild.id, user.id)
            stats        = await self.sob_repo.get_user_stats(guild.id, user.id)
            sobs_at_last = snitch_row["sobs_at_last_grant"] if snitch_row else 0
            left         = _sobs_until_next(stats["sobs_alltime"], threshold, sobs_at_last)
            sob_word     = "sob" if sobs_removed == 1 else "sobs"

            embed = discord.Embed(
                title=f"{_ANTI} Snitched!",
                description=(
                    f"{user.mention} snitched on {target_msg.author.mention}.\n"
                    f"**{sobs_removed}** {sob_word} removed from that message."
                ),
                color=_COLOR,
            )
            embed.add_field(
                name="Next token",
                value=f"**{left}** more sob{'s' if left != 1 else ''} to earn one" if left > 0 else "Earn your next sob to get a new token",
                inline=False,
            )
            embed.set_footer(text=f"Tokens earned every {threshold} sobs · expire after 7 days")
            await ctx.reply(embed=embed, mention_author=False)

        else:
            threshold = await self.sob_repo.get_snitch_threshold(guild.id)
            messages  = {
                "no_token":    f"{_ANTI} You don't have a snitch token. Receive **{threshold}** sobs to earn one.",
                "expired":     f"{_ANTI} Your snitch token expired (unused for 7 days). Earn a new one.",
                "no_sobs":     f"{_ANTI} That message has no sob reactions to remove.",
                "own_message": f"{_ANTI} You can't snitch your own message.",
                "bot_message": f"{_ANTI} You can't snitch a bot's message.",
            }
            await ctx.reply(messages.get(reason, f"{_ANTI} Something went wrong."), mention_author=False)