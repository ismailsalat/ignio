# bot/ui/heatmap.py
from __future__ import annotations

from datetime import date
import calendar


def _normalize_day_map(
    day_to_secs: dict[int, int] | None = None,
    day_to_seconds: dict[int, int] | None = None,
) -> dict[int, int]:
    raw = day_to_secs if day_to_secs is not None else day_to_seconds
    if raw is None:
        return {}

    clean: dict[int, int] = {}
    for k, v in raw.items():
        try:
            clean[int(k)] = int(v)
        except Exception:
            continue
    return clean


def _normalize_threshold(
    min_required: int | None = None,
    met_threshold_seconds: int | None = None,
) -> int:
    value = min_required if min_required is not None else met_threshold_seconds
    if value is None:
        return 1

    try:
        return max(1, int(value))
    except Exception:
        return 1


def _shade(
    secs: int,
    threshold: int,
    *,
    met_emoji: str,
    empty_emoji: str,
) -> str:
    return met_emoji if int(secs) >= int(threshold) else empty_emoji


def render_last_n_days_heatmap(
    day_to_secs: dict[int, int] | None = None,
    *,
    day_to_seconds: dict[int, int] | None = None,
    min_required: int | None = None,
    met_threshold_seconds: int | None = None,
    end_day_key: int,
    days: int,
    met_emoji: str,
    empty_emoji: str,
) -> str:
    day_map = _normalize_day_map(day_to_secs, day_to_seconds)
    threshold = _normalize_threshold(min_required, met_threshold_seconds)

    days = max(7, min(int(days), 56))
    end_day_key = int(end_day_key)

    keys = [end_day_key - i for i in range(days - 1, -1, -1)]
    cells = [
        _shade(
            day_map.get(k, 0),
            threshold,
            met_emoji=met_emoji,
            empty_emoji=empty_emoji,
        )
        for k in keys
    ]

    rows: list[str] = []
    for i in range(0, len(cells), 7):
        rows.append("".join(cells[i:i + 7]))

    legend = f"{empty_emoji} not met   {met_emoji} met"
    return "\n".join(rows) + f"\n{legend}"


def render_month_heatmap(
    day_to_secs: dict[int, int] | None = None,
    *,
    day_to_seconds: dict[int, int] | None = None,
    min_required: int | None = None,
    met_threshold_seconds: int | None = None,
    year: int | None = None,
    month: int | None = None,
    met_emoji: str,
    empty_emoji: str,
) -> str:
    """
    Compact month heatmap.

    Supports both old and new arg names:
    - day_to_secs / day_to_seconds
    - min_required / met_threshold_seconds
    """

    day_map = _normalize_day_map(day_to_secs, day_to_seconds)
    threshold = _normalize_threshold(min_required, met_threshold_seconds)

    today = date.today()
    year = int(year or today.year)
    month = int(month or today.month)

    cal = calendar.Calendar(firstweekday=6)  # Sunday first
    weeks = cal.monthdayscalendar(year, month)

    rows: list[str] = []

    for week in weeks:
        row_cells: list[str] = []
        for day_num in week:
            if day_num == 0:
                row_cells.append("  ")
                continue

            dk = date(year, month, day_num).toordinal()
            secs = day_map.get(dk, 0)
            row_cells.append(
                _shade(
                    secs,
                    threshold,
                    met_emoji=met_emoji,
                    empty_emoji=empty_emoji,
                )
            )

        rows.append("".join(row_cells).rstrip())

    legend = f"{empty_emoji} not met   {met_emoji} met"
    return "\n".join(rows) + f"\n{legend}"