from __future__ import annotations

import calendar
from datetime import date

import discord

from bot.ui.heatmap import render_month_heatmap

try:
    from bot.config import e as cfg_emoji
except Exception:
    cfg_emoji = None


def _guild_emoji(guild: discord.Guild | None, *names: str) -> str | None:
    if guild is None:
        return None

    wanted = {str(n).lower().strip() for n in names if str(n).strip()}
    for em in getattr(guild, "emojis", []) or []:
        try:
            if getattr(em, "name", "").lower() in wanted:
                return str(em)
        except Exception:
            continue
    return None


def _emoji(guild: discord.Guild | None, key: str, default: str) -> str:
    found = _guild_emoji(guild, key)
    if found:
        return found

    if cfg_emoji is not None:
        try:
            value = str(cfg_emoji(key) or "").strip()
            if value:
                return value
        except Exception:
            pass

    return default


def progress_bar(current: int, goal: int, width: int) -> str:
    current = max(0, int(current))
    goal = max(0, int(goal))
    width = max(6, int(width))

    if goal <= 0:
        filled = 0
    else:
        current = min(current, goal)
        filled = int((current / goal) * width)

    return "█" * filled + "░" * (width - filled)


def fmt_hms(seconds: int) -> str:
    seconds = max(0, int(seconds))
    h = seconds // 3600
    m = (seconds % 3600) // 60
    s = seconds % 60

    if h > 0 and m > 0:
        return f"{h}h {m}m"
    if h > 0:
        return f"{h}h"
    if m > 0 and s > 0:
        return f"{m}m {s}s"
    if m > 0:
        return f"{m}m"
    return f"{s}s"


def fmt_compact_hms(seconds: int) -> str:
    seconds = max(0, int(seconds))
    h = seconds // 3600
    m = (seconds % 3600) // 60

    if h > 0 and m > 0:
        return f"{h}h {m}m"
    if h > 0:
        return f"{h}h"
    return f"{m}m"


def pct_text(current: int, goal: int) -> str:
    current = max(0, int(current))
    goal = max(0, int(goal))
    if goal <= 0:
        return "0%"
    return f"{min(100, round((current / goal) * 100))}%"


def _status_line(
    *,
    guild: discord.Guild | None,
    status: str,
    current_streak: int,
    today_seconds: int,
    min_required: int,
) -> str:
    fire = _emoji(guild, "fire", "🔥")
    white_fire = _emoji(guild, "white_fire", "🤍")
    ice = _emoji(guild, "ice", "🧊")
    bolt = _emoji(guild, "bolt", "⚡")

    remaining = max(0, int(min_required) - int(today_seconds))

    if current_streak > 0 and today_seconds >= min_required:
        return f"{fire} **Safe today** • streak protected"
    if current_streak > 0 and remaining > 0:
        return f"{white_fire} **Active streak** • {fmt_compact_hms(remaining)} left today"
    if str(status).lower() == "active":
        return f"{bolt} **Building** • {fmt_compact_hms(remaining)} left today"
    return f"{ice} **Idle** • not completed today"


def _month_label_from_map(day_map: dict[int, int]) -> str | None:
    if not day_map:
        return None
    try:
        first_key = min(day_map.keys())
        d = date.fromordinal(int(first_key))
        return d.strftime("%B %Y")
    except Exception:
        return None


def _heatmap_block(
    *,
    guild: discord.Guild | None,
    heatmap_day_to_secs: dict[int, int],
    heatmap_met_emoji: str,
    heatmap_empty_emoji: str,
    min_required: int,
) -> str:
    if not heatmap_day_to_secs:
        return "No activity yet this month."

    month_label = _month_label_from_map(heatmap_day_to_secs)

    body = render_month_heatmap(
        day_to_seconds=heatmap_day_to_secs,
        met_threshold_seconds=max(1, int(min_required)),
        met_emoji=str(heatmap_met_emoji),
        empty_emoji=str(heatmap_empty_emoji),
    )

    body = f"```{body}```"

    legend_done = str(heatmap_met_emoji or _emoji(guild, "fire", "🔥"))
    legend_empty = str(heatmap_empty_emoji or _emoji(guild, "dot", "▫️"))

    parts: list[str] = []
    if month_label:
        parts.append(f"**{month_label}**")
    parts.append(body)
    parts.append(f"{legend_done} met day  •  {legend_empty} not met")

    return "\n".join(parts)


def _timing_lines(
    *,
    ends_in_text: str | None,
    restore_in_text: str | None,
) -> str:
    lines: list[str] = []

    if ends_in_text:
        lines.append(f"**Ends in:** `{ends_in_text}`")

    if restore_in_text:
        lines.append(f"**Restore:** `{restore_in_text}` left")

    return "\n".join(lines)


def duo_status_embed(
    *,
    user_a: discord.Member,
    user_b: discord.Member,
    today_seconds: int,
    min_required: int,
    current_streak: int,
    longest_streak: int,
    bar_width: int,
    status: str,
    connection_score_seconds: int,
    heatmap_day_to_secs: dict[int, int],
    heatmap_met_emoji: str,
    heatmap_empty_emoji: str,
    ends_in_text: str | None = None,
    restore_in_text: str | None = None,
) -> discord.Embed:
    guild = getattr(user_a, "guild", None)

    fire = _emoji(guild, "fire", "🔥")
    people = _emoji(guild, "people", "👥")
    chart = _emoji(guild, "chart", "📊")
    trophy = _emoji(guild, "trophy", "🏆")
    handshake = _emoji(guild, "handshake", "🤝")
    clock = _emoji(guild, "clock", "⏱️")

    pair_title = f"{user_a.display_name} + {user_b.display_name}"

    today_seconds = max(0, int(today_seconds))
    min_required = max(1, int(min_required))
    current_streak = max(0, int(current_streak))
    longest_streak = max(0, int(longest_streak))
    connection_score_seconds = max(0, int(connection_score_seconds))
    bar_width = max(6, int(bar_width))

    bar = progress_bar(today_seconds, min_required, bar_width)
    percent = pct_text(today_seconds, min_required)
    remaining_today = max(0, min_required - today_seconds)

    embed = discord.Embed(
        title=f"{fire} Duo Streak",
        description=(
            f"{people} **{pair_title}**\n"
            f"{_status_line(guild=guild, status=status, current_streak=current_streak, today_seconds=today_seconds, min_required=min_required)}"
        ),
    )

    today_lines = [
        f"`{bar}` **{percent}**",
        f"**Progress:** `{fmt_hms(today_seconds)}` / `{fmt_hms(min_required)}`",
        f"**Left today:** `{fmt_hms(remaining_today)}`",
    ]

    timing_block = _timing_lines(
        ends_in_text=ends_in_text,
        restore_in_text=restore_in_text,
    )
    if timing_block:
        today_lines.append(timing_block)

    embed.add_field(
        name=f"{clock} Today",
        value="\n".join(today_lines),
        inline=False,
    )

    embed.add_field(
        name=f"{fire} Current",
        value=f"`{current_streak}` days",
        inline=True,
    )

    embed.add_field(
        name=f"{trophy} Best",
        value=f"`{longest_streak}` days",
        inline=True,
    )

    embed.add_field(
        name=f"{handshake} Connection",
        value=f"`{fmt_hms(connection_score_seconds)}`",
        inline=True,
    )

    embed.add_field(
        name=f"{chart} Heatmap",
        value=_heatmap_block(
            guild=guild,
            heatmap_day_to_secs=heatmap_day_to_secs,
            heatmap_met_emoji=heatmap_met_emoji,
            heatmap_empty_emoji=heatmap_empty_emoji,
            min_required=min_required,
        ),
        inline=False,
    )

    embed.set_footer(text="Ignio • duo streak view")
    return embed


def leaderboard_value_line(label: str, value: str) -> str:
    return f"**{label}:** {value}"


def compact_duo_label(user_a: discord.Member | None, user_b: discord.Member | None) -> str:
    a = "Unknown" if user_a is None else user_a.display_name
    b = "Unknown" if user_b is None else user_b.display_name
    return f"{a} + {b}"


def month_progress_summary(day_map: dict[int, int], min_required: int) -> tuple[int, int]:
    total_days = 0
    met_days = 0

    for _, secs in sorted(day_map.items()):
        total_days += 1
        if int(secs) >= int(min_required):
            met_days += 1

    return met_days, total_days


def recent_days_text(day_map: dict[int, int], *, limit: int = 7) -> str:
    if not day_map:
        return "No recent activity."

    lines: list[str] = []
    for day_key in sorted(day_map.keys(), reverse=True)[: max(1, int(limit))]:
        d = date.fromordinal(int(day_key))
        secs = int(day_map[day_key])
        lines.append(f"`{d.strftime('%b %d')}` — {fmt_compact_hms(secs)}")

    return "\n".join(lines)


def current_month_bounds() -> tuple[int, int]:
    today = date.today()
    first = date(today.year, today.month, 1).toordinal()
    last_num = calendar.monthrange(today.year, today.month)[1]
    last = date(today.year, today.month, last_num).toordinal()
    return first, last