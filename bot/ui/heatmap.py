# bot/ui/heatmap.py
from __future__ import annotations

from datetime import date
import calendar


def _shade(secs: int, min_required: int) -> str:
    """
    Only 2 states:
    ⬜ = not met / no streak that day
    🟩 = met requirement
    """
    return "🟩" if int(secs) >= int(min_required) else "⬜"


def render_month_heatmap(
    day_to_secs: dict[int, int],
    *,
    min_required: int,
    year: int | None = None,
    month: int | None = None,
) -> str:
    """
    Month heatmap (calendar-style), current month by default.

    day_key = date.toordinal()

    Uses spaces for padding cells that are outside the month.
    """
    today = date.today()
    year = year or today.year
    month = month or today.month

    first_weekday, num_days = calendar.monthrange(year, month)  # Monday=0..Sunday=6

    cells: list[str | None] = [None] * first_weekday
    for d in range(1, num_days + 1):
        dk = date(year, month, d).toordinal()
        secs = int(day_to_secs.get(dk, 0))
        cells.append(_shade(secs, min_required))

    # pad end to full weeks
    while len(cells) % 7 != 0:
        cells.append(None)

    # build rows
    rows: list[str] = []
    for i in range(0, len(cells), 7):
        week = cells[i : i + 7]
        # None pads as spaces so we only show ⬜/🟩 for real days
        row = "".join(("  " if c is None else c) for c in week)
        rows.append(row)

    month_name = calendar.month_name[month]
    header = f"{month_name} {year}  (1-{num_days})"
    legend = "⬜ not met   🟩 met"

    return f"{header}\n" + "\n".join(rows) + f"\n{legend}"
