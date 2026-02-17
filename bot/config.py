# bot/config.py
from __future__ import annotations

from dataclasses import dataclass
import os
from dotenv import load_dotenv

load_dotenv()

EMOJIS = {
    "fire": "<:fire:1473077788658372742>",
    "white_fire": "<:whitefire:1473077888487002316>",
    "ice": "<:ice:1473077944036622489>",
}

def e(key: str) -> str:
    return EMOJIS.get(key, "")

@dataclass(frozen=True)
class Settings:
    token: str

    # ---------------- Time rules ----------------
    default_tz: str = "America/Los_Angeles"
    grace_hour_local: int = 3  # day closes at 3:00 AM local time

    # ---------------- VC overlap rules ----------------
    # Minimum overlap required to "complete" a day (streak preserved)
    min_overlap_seconds: int = 3 * 60          # default 3 minutes
    tick_seconds: int = 15                      # seconds added per tick
    disconnect_buffer_seconds: int = 60         # allow brief disconnect without breaking overlap

    # Anti-farm: cap overlap counted per duo per day (0 = unlimited)
    daily_cap_seconds: int = 3 * 60 * 60        # default 3 hours/day per duo

    # ---------------- AFK ignore ----------------
    ignore_afk_channels: bool = True
    afk_channel_ids: tuple[int, ...] = ()       # add AFK voice channel IDs here

    # ---------------- UI ----------------
    progress_bar_width: int = 12
    heatmap_days: int = 28                      # last N days
    # 2-color heatmap (met / not met)
    heatmap_met_emoji: str = "🟥"
    heatmap_empty_emoji: str = "⬜"

    # ---------------- Privacy ----------------
    # Privacy default is OFF (public). If either member enables privacy,
    # only duo members (and admins if enabled) can view streak.
    privacy_default_private: bool = False
    privacy_admin_can_view: bool = True

    # ---------------- DM reminders ----------------
    dm_reminders_enabled: bool = True
    dm_remind_before_minutes: int = 30          # remind this many minutes before day closes
    dm_remind_cooldown_minutes: int = 120       # per-duo cooldown to prevent spam

    # DM streak ended messages
    dm_streak_end_enabled: bool = True
    dm_streak_end_restore_enabled: bool = True  # white_fire message when it ends (restore possible)
    dm_streak_end_ice_enabled: bool = True      # ice message when restore window is over
    restore_window_hours: int = 24              # "restore possible" window length (message-only for now)

def load_settings() -> Settings:
    token = os.getenv("DISCORD_TOKEN", "").strip()
    if not token:
        raise RuntimeError("Missing DISCORD_TOKEN in .env (DISCORD_TOKEN=...)")
    return Settings(token=token)
