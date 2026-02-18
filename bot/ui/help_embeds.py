# bot/ui/help_embeds.py
from __future__ import annotations

import discord

try:
    # your config has EMOJIS + e()
    from bot.config import e as cfg_emoji
except Exception:
    cfg_emoji = None


def _get_prefix_from_bot(bot) -> str:
    """
    Best-effort prefix detection.
    Works for your dev/prod prefix string setup.
    """
    try:
        p = getattr(bot, "command_prefix", None)
        if isinstance(p, str) and p.strip():
            return p.strip()
    except Exception:
        pass
    return "!"


def _guild_emoji(guild: discord.Guild | None, *names: str) -> str | None:
    """
    Find a custom emoji by name in the server.
    Returns string like '<:name:id>' if found.
    """
    if guild is None:
        return None
    lname = {n.lower() for n in names if isinstance(n, str) and n.strip()}
    for em in getattr(guild, "emojis", []) or []:
        if em and getattr(em, "name", "").lower() in lname:
            return str(em)
    return None


def _emoji(guild: discord.Guild | None, key: str, default: str) -> str:
    """
    Emoji priority:
    1) server emoji by name (key)
    2) your config emoji mapping e(key) if available
    3) default unicode
    """
    found = _guild_emoji(guild, key)
    if found:
        return found

    if cfg_emoji is not None:
        try:
            v = str(cfg_emoji(key) or "").strip()
            if v:
                return v
        except Exception:
            pass

    return default


def streak_help_embed(ctx) -> discord.Embed:
    """
    Clean, user-friendly help embed for streak command.
    """
    prefix = _get_prefix_from_bot(getattr(ctx, "bot", None))
    guild = getattr(ctx, "guild", None)

    fire = _emoji(guild, "fire", "🔥")
    vc = _emoji(guild, "vc", "🎧")
    people = _emoji(guild, "people", "👥")
    lock = _emoji(guild, "lock", "🔒")
    bolt = _emoji(guild, "bolt", "⚡")

    embed = discord.Embed(
        title=f"{fire} Ignio Streaks",
        description=(
            f"{vc} **Duo streaks are tracked automatically** when **exactly 2 real users** are in the same VC.\n"
            f"{bolt} Checking streaks never creates a streak — tracking starts only from VC overlap."
        ),
    )

    embed.add_field(
        name="How it works",
        value=(
            f"1) Join a VC with **exactly 1** other real user {people}\n"
            "2) Stay in VC long enough to meet the daily requirement\n"
            "3) Use the commands below to view stats"
        ),
        inline=False,
    )

    embed.add_field(
        name="Commands",
        value=(
            f"`{prefix}streak` → quick check with your VC duo\n"
            f"`{prefix}streak live` → same check, explicit VC mode\n"
            f"`{prefix}streak @user` → your streak with someone\n"
            f"`{prefix}streak @user1 @user2` → streak between two people\n"
            f"`{prefix}streak help` → show this menu"
        ),
        inline=False,
    )

    embed.add_field(
        name="Examples",
        value=(
            f"`{prefix}streak`\n"
            f"`{prefix}streak live`\n"
            f"`{prefix}streak @Milk`\n"
            f"`{prefix}streak @Milk @Hassan`"
        ),
        inline=False,
    )

    embed.add_field(
        name=f"{lock} Privacy",
        value=(
            "Some duos can be private.\n"
            "If a duo is private, only the duo members can view it "
            "(and admins if your server allows it)."
        ),
        inline=False,
    )

    embed.set_footer(text=f"Tip: If a command fails, it will tell you why — then you can use {prefix}streak help.")
    return embed


def leaderboard_help_embed(ctx) -> discord.Embed:
    """
    Clean, user-friendly help embed for leaderboard command.
    """
    prefix = _get_prefix_from_bot(getattr(ctx, "bot", None))
    guild = getattr(ctx, "guild", None)

    chart = _emoji(guild, "chart", "📊")
    fire = _emoji(guild, "fire", "🔥")
    trophy = _emoji(guild, "trophy", "🏆")
    shake = _emoji(guild, "handshake", "🤝")
    lock = _emoji(guild, "lock", "🔒")

    embed = discord.Embed(
        title=f"{chart} Ignio Leaderboards",
        description="Leaderboards show **public** duos only (private duos are hidden).",
    )

    embed.add_field(
        name="Commands",
        value=(
            f"`{prefix}lb` → overview (top 5 of each)\n"
            f"`{prefix}lb streak` → current streak leaderboard\n"
            f"`{prefix}lb best` → best/record streak leaderboard\n"
            f"`{prefix}lb cs` → connection score leaderboard\n"
            f"`{prefix}lb help` → show this menu"
        ),
        inline=False,
    )

    embed.add_field(
        name="Examples",
        value=(
            f"`{prefix}lb`\n"
            f"`{prefix}lb streak`\n"
            f"`{prefix}lb best`\n"
            f"`{prefix}lb cs`"
        ),
        inline=False,
    )

    embed.add_field(
        name=f"{fire} Current vs {trophy} Best",
        value=(
            f"{fire} **Current** = how many days the duo streak is *right now*\n"
            f"{trophy} **Best** = the duo’s all-time record"
        ),
        inline=False,
    )

    embed.add_field(
        name=f"{shake} Connection score",
        value="Total time spent together in VC (shown like `2h 10m`).",
        inline=False,
    )

    embed.add_field(
        name=f"{lock} Privacy",
        value="If either user enables privacy, that duo will **not** appear on leaderboards.",
        inline=False,
    )

    embed.set_footer(text=f"Tip: Use {prefix}lb help anytime. (Legacy cmds still work: {prefix}streaklb / {prefix}cslb)")
    return embed
