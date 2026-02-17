# bot/ui/heatmap.py
from __future__ import annotations

from datetime import date
import calendar


def _shade(
    secs: int,
    min_required: int,
    *,
    met_emoji: str,
    empty_emoji: str,
) -> str:
    """
    Pure renderer.
    No config imports here.
    """
    return met_emoji if int(secs) >= int(min_required) else empty_emoji


# ------------------------------------------------------------
# LAST N DAYS HEATMAP (RECOMMENDED)
# ------------------------------------------------------------
def render_last_n_days_heatmap(
    day_to_secs: dict[int, int],
    *,
    min_required: int,
    end_day_key: int,
    days: int,
    met_emoji: str,
    empty_emoji: str,
) -> str:
    """
    2-color heatmap.

    day_key = date.toordinal()

    end_day_key MUST come from your timecore logic
    so tz + grace window matches streak system.
    """

    days = max(7, min(int(days), 56))
    min_required = max(1, int(min_required))

    # oldest -> newest
    keys = [end_day_key - i for i in range(days - 1, -1, -1)]

    cells = [
        _shade(
            int(day_to_secs.get(k, 0)),
            min_required,
            met_emoji=met_emoji,
            empty_emoji=empty_emoji,
        )
        for k in keys
    ]

    rows = []
    for i in range(0, len(cells), 7):
        rows.append("".join(cells[i : i + 7]))

    legend = f"{empty_emoji} not met   {met_emoji} met"

    return "\n".join(rows) + f"\n{legend}"


# ------------------------------------------------------------
# MONTH HEATMAP (OPTIONAL)
# ------------------------------------------------------------
def render_month_heatmap(
    day_to_secs: dict[int, int],
    *,
    min_required: int,
    year: int | None = None,
    month: int | None = None,
    met_emoji: str,
    empty_emoji: str,
) -> str:
    """
    Calendar-style month heatmap.

    NOTE:
    This uses system date (not timecore day_key).
    Use last_n_days version for streak-accurate visuals.
    """

    today = date.today()
    year = year or today.year
    month = month or today.month

    first_weekday, num_days = calendar.monthrange(year, month)

    cells: list[str | None] = [None] * first_weekday

    for d in range(1, num_days + 1):
        dk = date(year, month, d).toordinal()
        secs = int(day_to_secs.get(dk, 0))

        cells.append(
            _shade(
                secs,
                min_required,
                met_emoji=met_emoji,
                empty_emoji=empty_emoji,
            )
        )

    while len(cells) % 7 != 0:
        cells.append(None)

    rows = []
    for i in range(0, len(cells), 7):
        week = cells[i : i + 7]
        row = "".join(("  " if c is None else c) for c in week)
        rows.append(row)

    legend = f"{empty_emoji} not met   {met_emoji} met"

    return "\n".join(rows) + f"\n{legend}"
