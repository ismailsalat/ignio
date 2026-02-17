# bot/config.py
from __future__ import annotations

from dataclasses import dataclass
import os

# Only load .env locally if python-dotenv is installed and a .env file exists.
try:
    from dotenv import load_dotenv
except Exception:
    load_dotenv = None


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
    min_overlap_seconds: int = 3 * 60
    tick_seconds: int = 15
    disconnect_buffer_seconds: int = 60

    daily_cap_seconds: int = 3 * 60 * 60

    # ---------------- AFK ignore ----------------
    ignore_afk_channels: bool = True
    afk_channel_ids: tuple[int, ...] = ()

    # ---------------- UI ----------------
    progress_bar_width: int = 12
    heatmap_days: int = 28
    heatmap_met_emoji: str = "🟥"
    heatmap_empty_emoji: str = "⬜"

    # ---------------- Privacy ----------------
    privacy_default_private: bool = False
    privacy_admin_can_view: bool = True

    # ---------------- DM reminders ----------------
    dm_reminders_enabled: bool = True
    dm_remind_before_minutes: int = 30
    dm_remind_cooldown_minutes: int = 120

    dm_streak_end_enabled: bool = True
    dm_streak_end_restore_enabled: bool = True
    dm_streak_end_ice_enabled: bool = True
    restore_window_hours: int = 24


def load_settings() -> Settings:
    # Local dev convenience: read .env if available (does NOT override Railway env vars)
    if load_dotenv is not None:
        load_dotenv(override=False)

    token = (
        os.getenv("DISCORD_TOKEN", "").strip()
        or os.getenv("TOKEN", "").strip()
        or os.getenv("DISCORD_BOT_TOKEN", "").strip()
    )

    if not token:
        raise RuntimeError(
            "Missing DISCORD_TOKEN. Set DISCORD_TOKEN in Railway → Variables, "
            "or add DISCORD_TOKEN=... to a local .env file."
        )

    return Settings(token=token)
