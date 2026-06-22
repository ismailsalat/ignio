# core/time_utils.py
from __future__ import annotations

import time
from datetime import date


def now_ts() -> int:
    """Current unix timestamp (seconds)."""
    return int(time.time())


def day_key(d: date | None = None) -> int:
    """Ordinal day number (date.toordinal). Stable, sortable integer."""
    return (d or date.today()).toordinal()


def week_key(d: date | None = None) -> int:
    """ISO week key as yyyy*100 + ww (e.g. 2026 week 25 -> 202625)."""
    iso = (d or date.today()).isocalendar()
    return iso[0] * 100 + iso[1]


def today_keys() -> tuple[int, int]:
    """(day_key, week_key) for today."""
    today = date.today()
    return day_key(today), week_key(today)
