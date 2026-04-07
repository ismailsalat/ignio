from __future__ import annotations

import discord

try:
    from bot.config import e as cfg_emoji
except Exception:
    cfg_emoji = None


def _get_prefix_from_bot(bot) -> str:
    try:
        p = getattr(bot, "command_prefix", None)
        if isinstance(p, str) and p.strip():
            return p.strip()
    except Exception:
        pass
    return "!"


def _guild_emoji(guild: discord.Guild | None, *names: str) -> str | None:
    if guild is None:
        return None
    lname = {n.lower() for n in names if isinstance(n, str) and n.strip()}
    for em in getattr(guild, "emojis", []) or []:
        if em and getattr(em, "name", "").lower() in lname:
            return str(em)
    return None


def _emoji(guild: discord.Guild | None, key: str, default: str) -> str:
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


def admin_help_embed(ctx) -> discord.Embed:
    prefix = _get_prefix_from_bot(getattr(ctx, "bot", None))
    guild = getattr(ctx, "guild", None)

    shield = _emoji(guild, "shield", "🛡️")
    gear = _emoji(guild, "gear", "⚙️")
    db = _emoji(guild, "database", "🗄️")
    clock = _emoji(guild, "clock", "⏱️")
    test = _emoji(guild, "test", "🧪")
    warn = _emoji(guild, "warning", "⚠️")

    embed = discord.Embed(
        title=f"{shield} Ignio Admin",
        description="Admin-only utilities. Use the hub command so the bot stays easy to manage.",
    )

    embed.add_field(
        name=f"{gear} Config",
        value=(
            f"`{prefix}admin config` → show live effective config\n"
            f"`{prefix}admin set min 3m` → set min overlap (supports `180`, `3m`, `2h`)\n"
            f"`{prefix}admin set tick 15` → set tick seconds\n"
            f"`{prefix}admin recalc today` → recalc today totals using current config"
        ),
        inline=False,
    )

    embed.add_field(
        name=f"{clock} Loop / time",
        value=(
            f"`{prefix}admin tick status` → tick loop running?\n"
            f"`{prefix}admin daykey` → debug day key / timezone"
        ),
        inline=False,
    )

    embed.add_field(
        name=f"{db} DB",
        value=f"`{prefix}admin db counts` → rows/duos counts for this server",
        inline=False,
    )

    embed.add_field(
        name=f"{test} Tests (dangerous)",
        value=(
            f"{warn} These change data.\n"
            f"`{prefix}admin test add_today @a @b 3m`\n"
            f"`{prefix}admin test set_today @a @b 10m`\n"
            f"`{prefix}admin test set_day @a @b <day_key> 10m`\n"
            f"`{prefix}admin test set_streak @a @b <cur> <best> <last_day_key>`\n"
            f"`{prefix}admin test clear_duo @a @b`"
        ),
        inline=False,
    )

    embed.add_field(
        name="DM tests",
        value=(
            f"`{prefix}admin dm restore @user`\n"
            f"`{prefix}admin dm ice @user`\n"
            f"`{prefix}admin dm text @user <message>`"
        ),
        inline=False,
    )

    embed.set_footer(text=f"Tip: {prefix}admin help  • legacy commands still work but are hidden")
    return embed


def user_settings_help_embed(ctx) -> discord.Embed:
    prefix = _get_prefix_from_bot(getattr(ctx, "bot", None))
    guild = getattr(ctx, "guild", None)

    gear = _emoji(guild, "gear", "⚙️")
    lock = _emoji(guild, "lock", "🔒")
    mail = _emoji(guild, "mail", "📩")
    warn = _emoji(guild, "warning", "⚠️")
    ice = _emoji(guild, "ice", "🧊")
    fire = _emoji(guild, "white_fire", "🔥")

    embed = discord.Embed(
        title=f"{gear} Ignio Settings",
        description="Your personal preferences for this server.",
    )

    embed.add_field(
        name="Main command",
        value=(
            f"`{prefix}settings` → show your current settings\n"
            f"`{prefix}settings help` → show this menu\n"
            f"`{prefix}settings privacy on/off` → make your duos private/public\n"
            f"`{prefix}settings dm on/off` → DM reminders before day ends\n"
            f"`{prefix}settings lost on/off` → notify when your streak is lost\n"
            f"`{prefix}settings dmice on/off` → notify when restore expires (ice)\n"
            f"`{prefix}settings dmrestore on/off` → notify when restore is available"
        ),
        inline=False,
    )

    embed.add_field(
        name="Examples",
        value=(
            f"`{prefix}settings`\n"
            f"`{prefix}settings privacy on`\n"
            f"`{prefix}settings dm off`\n"
            f"`{prefix}settings lost on`\n"
            f"`{prefix}settings dmice off`\n"
            f"`{prefix}settings dmrestore on`"
        ),
        inline=False,
    )

    embed.add_field(
        name=f"{lock} Privacy",
        value="If either duo member turns privacy on, that duo becomes private (leaderboards hide it too).",
        inline=False,
    )

    embed.add_field(
        name=f"{mail} DM notifications",
        value=(
            f"{mail} **Reminders** = “you’re about to miss today”\n"
            f"{warn} **Lost** = “your streak ended”\n"
            f"{fire} **Restore** = “you can still restore it”\n"
            f"{ice} **Ice** = “restore window expired”"
        ),
        inline=False,
    )

    embed.set_footer(text=f"Legacy still works: {prefix}dmend (same as {prefix}settings lost), {prefix}privacy, {prefix}dm, {prefix}dmice")
    return embed


def user_settings_status_embed(ctx, *, privacy: bool, dm: bool, dm_lost: bool, dm_restore: bool, dm_ice: bool) -> discord.Embed:
    prefix = _get_prefix_from_bot(getattr(ctx, "bot", None))
    guild = getattr(ctx, "guild", None)

    gear = _emoji(guild, "gear", "⚙️")
    lock = _emoji(guild, "lock", "🔒")
    mail = _emoji(guild, "mail", "📩")
    warn = _emoji(guild, "warning", "⚠️")
    ice = _emoji(guild, "ice", "🧊")
    fire = _emoji(guild, "white_fire", "🔥")

    def onoff(b: bool) -> str:
        return "ON" if b else "OFF"

    embed = discord.Embed(
        title=f"{gear} Your Ignio Settings",
        description="These settings only affect you (in this server).",
    )

    embed.add_field(name=f"{lock} Privacy", value=f"`{onoff(privacy)}`", inline=True)
    embed.add_field(name=f"{mail} DM reminders", value=f"`{onoff(dm)}`", inline=True)
    embed.add_field(name=f"{warn} Streak lost alerts", value=f"`{onoff(dm_lost)}`", inline=True)
    embed.add_field(name=f"{fire} Restore alerts", value=f"`{onoff(dm_restore)}`", inline=True)
    embed.add_field(name=f"{ice} Ice alerts", value=f"`{onoff(dm_ice)}`", inline=True)

    embed.set_footer(text=f"Change: {prefix}settings help")
    return embed


# ============================================================
# DM / Notification Embeds
# ============================================================

def streak_restore_available_embed(ctx, *, duo_label: str | None = None, minutes_left: int | None = None) -> discord.Embed:
    guild = getattr(ctx, "guild", None)
    white_fire = _emoji(guild, "white_fire", "🤍")

    lines: list[str] = []

    if duo_label:
        lines.append(f"Your streak with **{duo_label}** ended, but you can still restore it.")
    else:
        lines.append("Your duo streak ended, but you can still restore it.")

    lines.append("")
    lines.append("**What to do**")
    lines.append("Hop in VC with your duo before the restore window ends.")

    if minutes_left is not None and minutes_left > 0:
        if minutes_left >= 60:
            h = minutes_left // 60
            m = minutes_left % 60
            time_text = f"{h}h {m}m" if m else f"{h}h"
        else:
            time_text = f"{minutes_left}m"

        lines.append("")
        lines.append(f"Time left: **{time_text}**")

    return discord.Embed(
        title=f"{white_fire} Streak Restore Available",
        description="\n".join(lines),
    )


def streak_lost_embed(ctx, *, duo_label: str | None = None) -> discord.Embed:
    guild = getattr(ctx, "guild", None)
    ice = _emoji(guild, "ice", "🧊")

    if duo_label:
        desc = (
            f"Your streak with **{duo_label}** expired.\n"
            "This streak can’t be restored anymore."
        )
    else:
        desc = (
            "Restore window expired.\n"
            "This streak can’t be restored anymore."
        )

    return discord.Embed(
        title=f"{ice} Streak Lost",
        description=desc,
    )


def end_of_day_warning_embed(ctx, *, duo_label: str | None = None, remaining_seconds: int) -> discord.Embed:
    guild = getattr(ctx, "guild", None)
    fire = _emoji(guild, "fire", "🔥")

    remaining_seconds = max(0, int(remaining_seconds))
    h = remaining_seconds // 3600
    m = (remaining_seconds % 3600) // 60

    if h > 0:
        need = f"{h}h {m}m"
    elif m > 0:
        need = f"{m}m"
    else:
        need = "<1m"

    if duo_label:
        desc = (
            f"You still need about **{need}** in VC with **{duo_label}** today.\n\n"
            "Hop in before the day ends."
        )
    else:
        desc = (
            f"You still need about **{need}** in VC today.\n\n"
            "Hop in before the day ends."
        )

    return discord.Embed(
        title=f"{fire} Streak Reminder",
        description=desc,
    )


def restore_success_embed(ctx, *, duo_label: str | None = None, current_streak: int | None = None) -> discord.Embed:
    guild = getattr(ctx, "guild", None)
    fire = _emoji(guild, "fire", "🔥")

    lines: list[str] = []

    if duo_label:
        lines.append(f"Your streak with **{duo_label}** has been restored.")
    else:
        lines.append("Your streak has been restored.")

    if current_streak is not None and current_streak > 0:
        lines.append("")
        lines.append(f"Current streak: **{current_streak}**")

    return discord.Embed(
        title=f"{fire} Streak Restored",
        description="\n".join(lines),
    )