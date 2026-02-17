# bot/ui/formatting.py
import discord
from bot.config import e
from bot.ui.heatmap import render_month_heatmap

def progress_bar(current: int, goal: int, width: int) -> str:
    current = max(0, min(current, goal))
    filled = int((current / goal) * width) if goal > 0 else 0
    return "█" * filled + "░" * (width - filled)

def fmt_hms(seconds: int) -> str:
    seconds = max(0, int(seconds))
    h = seconds // 3600
    m = (seconds % 3600) // 60
    s = seconds % 60
    if h > 0:
        return f"{h}h {m}m"
    if m > 0:
        return f"{m}m {s}s"
    return f"{s}s"

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
) -> discord.Embed:

    if status == "frozen":
        icon = e("white_fire")
    elif status == "lost":
        icon = e("ice")
    else:
        icon = e("fire")

    bar = progress_bar(today_seconds, min_required, bar_width)
    pct = int((today_seconds / min_required) * 100) if min_required > 0 else 0
    pct = max(0, min(pct, 100))

    embed = discord.Embed(
        title=f"{icon} Duo VC Streak",
        description=f"{user_a.mention} + {user_b.mention}",
    )

    embed.add_field(
        name="Today",
        value=(
            f"**{fmt_hms(today_seconds)} / {fmt_hms(min_required)}**  ({pct}%)\n"
            f"`{bar}`"
        ),
        inline=False,
    )

    embed.add_field(
        name="Streak",
        value=f"Current: **{current_streak}**\nBest: **{longest_streak}**",
        inline=True,
    )

    embed.add_field(
        name="Connection Score",
        value=f"Total: **{fmt_hms(connection_score_seconds)}**",
        inline=True,
    )

    heat = render_month_heatmap(heatmap_day_to_secs, min_required=min_required)
    embed.add_field(name="This month", value=f"```{heat}```", inline=False)


    embed.set_footer(text="Tip: hop in VC together to fill today’s bar 🔥")
    return embed
