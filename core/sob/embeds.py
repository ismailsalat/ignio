# core/sob/embeds.py
from __future__ import annotations

import discord

from core.sob.repo import SNITCH_EXPIRY_SECONDS

# ── server emojis ───────────────────────────────────────────────────────────
SOB = "<:4612win11emojisob:1493190644221480960>"
HAND = "<:handsob:1493198316299747419>"
TOMATO = "<:tomatosob:1493198299140722760>"
ANTI = "<:antisob:1493198277674537071>"

COLOR = 0xF0B132


# ── small helpers ────────────────────────────────────────────────────────────

def mention(guild: discord.Guild, user_id: int) -> str:
    m = guild.get_member(user_id)
    return m.mention if m else f"<@{user_id}>"


def _rank_suffix(n: int) -> str:
    if 11 <= (n % 100) <= 13:
        return f"{n}th"
    return {1: f"{n}st", 2: f"{n}nd", 3: f"{n}rd"}.get(n % 10, f"{n}th")


def _rank_display(count: int, rank: int) -> str:
    return "—" if count == 0 else _rank_suffix(rank)


def _leader_line(guild: discord.Guild, data: dict | None, badge: str = "") -> str:
    if data is None:
        return "—"
    icon = badge or SOB
    return f"{icon} {mention(guild, data['user_id'])} · **{data['count']}**"


def sobs_until_next(alltime: int, threshold: int, sobs_at_last: int) -> int:
    next_grant = threshold if sobs_at_last == 0 else sobs_at_last + threshold
    return max(0, next_grant - alltime)


def _expiry_text(granted_at: int, now_ts: int) -> str:
    remaining = SNITCH_EXPIRY_SECONDS - (now_ts - granted_at)
    if remaining <= 0:
        return "expired"
    hours = remaining // 3600
    return f"expires in {hours // 24}d" if hours >= 24 else f"expires in {hours}h"


# ── embeds ────────────────────────────────────────────────────────────────────

def personal_embed(
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
        title=f"{SOB} Your Sob Stats",
        description=user.mention,
        color=COLOR,
    )

    t, w, a = stats["sobs_today"], stats["sobs_week"], stats["sobs_alltime"]
    embed.add_field(name="Today", value=f"{SOB} **{t}** · {_rank_display(t, rank_today)}", inline=True)
    embed.add_field(name="This week", value=f"{SOB} **{w}** · {_rank_display(w, rank_week)}", inline=True)
    embed.add_field(name="All time", value=f"{SOB} **{a}** · {_rank_display(a, rank_alltime)}", inline=True)

    has_token = snitch_row is not None and snitch_row["token_available"] == 1
    if has_token:
        expiry = _expiry_text(snitch_row["token_granted_at"], now_ts)
        token_val = f"{ANTI} **Ready** · {expiry} · reply to a message with `!ss`"
    else:
        sobs_at_last = snitch_row["sobs_at_last_grant"] if snitch_row else 0
        left = sobs_until_next(a, snitch_threshold, sobs_at_last)
        token_val = f"**{left}** sob{'s' if left != 1 else ''} until next token"

    embed.add_field(name=f"{ANTI} Snitch token", value=token_val, inline=False)
    embed.set_footer(text=f"Every {snitch_threshold} sobs = 1 token · !sob lb for leaderboard")
    return embed


def leaderboard_embed(
    *,
    guild: discord.Guild,
    daily_leader: dict | None,
    weekly_leader: dict | None,
    alltime_leader: dict | None,
    top_giver: dict | None,
    top_snitch: dict | None,
) -> discord.Embed:
    embed = discord.Embed(title=f"{SOB} Sob Leaderboard", color=COLOR)
    embed.add_field(name="Today", value=_leader_line(guild, daily_leader), inline=True)
    embed.add_field(name="This week", value=_leader_line(guild, weekly_leader), inline=True)
    embed.add_field(name="All time", value=_leader_line(guild, alltime_leader, badge=TOMATO), inline=True)
    embed.add_field(name="Top sob giver", value=_leader_line(guild, top_giver), inline=True)
    embed.add_field(name=f"{ANTI} Top snitch", value=_leader_line(guild, top_snitch), inline=True)
    embed.add_field(name="\u200b", value="\u200b", inline=True)
    embed.set_footer(text="!sob for your personal stats")
    return embed


def snitch_success_embed(
    *,
    snitcher: discord.Member,
    target: discord.Member | discord.User,
    sobs_removed: int,
    sobs_left_until_next: int,
    threshold: int,
) -> discord.Embed:
    sob_word = "sob" if sobs_removed == 1 else "sobs"
    embed = discord.Embed(
        title=f"{ANTI} Snitched!",
        description=(
            f"{snitcher.mention} snitched on {target.mention}.\n"
            f"**{sobs_removed}** {sob_word} removed from that message."
        ),
        color=COLOR,
    )
    left = sobs_left_until_next
    embed.add_field(
        name="Next token",
        value=(f"**{left}** more sob{'s' if left != 1 else ''} to earn one"
               if left > 0 else "Earn your next sob to get a new token"),
        inline=False,
    )
    embed.set_footer(text=f"Tokens earned every {threshold} sobs · expire after 7 days")
    return embed



def profile_options_embed(title, options, current, usage):
    """Show available profile options, marking the current one."""
    embed = discord.Embed(title=title, color=COLOR)
    lines = []
    for o in options:
        mark = " ✅ (current)" if o == current else ""
        lines.append(f"• **{o}**{mark}")
    embed.description = "\n".join(lines)
    embed.set_footer(text=usage)
    return embed


def snitch_help_embed(prefix: str = "!") -> discord.Embed:
    embed = discord.Embed(
        title=f"{SOB} Sob & Snitch",
        description="React with a sob emoji to give someone a sob. Earn snitch tokens to wipe sobs.",
        color=COLOR,
    )
    embed.add_field(
        name="Commands",
        value=(
            f"`{prefix}sob` → your personal sob stats\n"
            f"`{prefix}sob lb` → server leaderboard\n"
            f"`{prefix}ss` → (reply to a message) use a snitch token"
        ),
        inline=False,
    )
    embed.add_field(
        name=f"{ANTI} Snitch tokens",
        value=(
            "Every set number of sobs you receive earns a token.\n"
            "Reply to a message with `!ss` to wipe all sobs from it.\n"
            "Tokens expire after 7 days if unused."
        ),
        inline=False,
    )
    return embed
