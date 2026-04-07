from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any
from dotenv import load_dotenv

# load .env (does NOT override Railway env vars)
load_dotenv()


# -------------------------------------------------
# emoji helper
# -------------------------------------------------

_EMOJI_MAP: dict[str, str] = {
    "fire": "🔥",
    "white_fire": "🤍",
    "ice": "🧊",
    "vc": "🎧",
    "people": "👥",
    "lock": "🔒",
    "bolt": "⚡",
    "chart": "📊",
    "trophy": "🏆",
    "handshake": "🤝",
    "shield": "🛡️",
    "gear": "⚙️",
    "database": "🗄️",
    "clock": "⏱️",
    "test": "🧪",
    "warning": "⚠️",
    "mail": "📩",
    "dot": "▫️",
}


def e(key: str | None = None) -> Any:
    if key is None:
        return dict(_EMOJI_MAP)
    return _EMOJI_MAP.get(str(key), "")


# -------------------------------------------------
# env helpers
# -------------------------------------------------

def _env_str(name: str, default: str = "") -> str:
    value = os.getenv(name)
    if value is None:
        return default
    value = value.strip()
    return value if value else default


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return int(raw.strip())
    except Exception:
        return default


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    value = raw.strip().lower()
    if value in ("1", "true", "yes", "on", "enabled"):
        return True
    if value in ("0", "false", "no", "off", "disabled"):
        return False
    return default


def _parse_afk_ids(raw: str) -> tuple[int, ...]:
    items: list[int] = []
    for part in (raw or "").split(","):
        part = part.strip()
        if not part:
            continue
        try:
            items.append(int(part))
        except Exception:
            continue
    return tuple(items)


# -------------------------------------------------
# token helpers
# -------------------------------------------------

def _pick_token(env_name: str) -> tuple[str, str, str]:
    dev_token = _env_str("DISCORD_TOKEN_DEV")
    prod_token = _env_str("DISCORD_TOKEN_PROD")

    # fallback (avoid unless needed)
    fallback = _env_str("DISCORD_TOKEN", _env_str("TOKEN"))

    if env_name == "dev":
        token = dev_token or fallback
    else:
        token = prod_token or fallback

    return token, dev_token, prod_token


# -------------------------------------------------
# main settings
# -------------------------------------------------

@dataclass(slots=True)
class Settings:
    env: str = "dev"
    command_prefix_dev: str = "!!"
    command_prefix_prod: str = "!"
    prefix: str = "!!"

    token: str = ""
    discord_token: str = ""
    discord_token_dev: str = ""
    discord_token_prod: str = ""

    default_tz: str = "America/Los_Angeles"
    grace_hour_local: int = 3
    min_overlap_seconds: int = 180
    tick_seconds: int = 15
    disconnect_buffer_seconds: int = 60

    daily_cap_seconds: int = 0

    progress_bar_width: int = 12
    heatmap_met_emoji: str = "🟥"
    heatmap_empty_emoji: str = "⬜"

    ignore_afk_channels: bool = False
    afk_channel_ids: tuple[int, ...] = ()

    privacy_default_private: bool = False
    privacy_admin_can_view: bool = True

    dm_reminders_enabled: bool = True
    dm_streak_end_enabled: bool = True
    dm_streak_end_ice_enabled: bool = True
    dm_streak_end_restore_enabled: bool = True

    streak_restore_enabled: bool = True
    streak_restore_window_minutes: int = 120
    streak_end_warning_minutes: int = 60

    nickname_fire_enabled: bool = True
    nickname_fire_suffix: str = " 🔥"
    nickname_edit_min_interval_seconds: int = 20


def load_settings() -> Settings:
    env_name = _env_str("IGNIO_ENV", "dev").lower()

    command_prefix_dev = _env_str("COMMAND_PREFIX_DEV", _env_str("PREFIX_DEV", "!!"))
    command_prefix_prod = _env_str("COMMAND_PREFIX_PROD", _env_str("PREFIX_PROD", "!"))

    token, dev_token, prod_token = _pick_token(env_name)

    settings = Settings(
        env=env_name,
        command_prefix_dev=command_prefix_dev,
        command_prefix_prod=command_prefix_prod,
        prefix=command_prefix_dev if env_name == "dev" else command_prefix_prod,

        token=token,
        discord_token=token,
        discord_token_dev=dev_token,
        discord_token_prod=prod_token,

        default_tz=_env_str("DEFAULT_TZ", "America/Los_Angeles"),
        grace_hour_local=_env_int("GRACE_HOUR_LOCAL", 3),
        min_overlap_seconds=_env_int("MIN_OVERLAP_SECONDS", 180),
        tick_seconds=_env_int("TICK_SECONDS", 15),
        disconnect_buffer_seconds=_env_int("DISCONNECT_BUFFER_SECONDS", 60),

        daily_cap_seconds=_env_int("DAILY_CAP_SECONDS", 0),

        progress_bar_width=_env_int("PROGRESS_BAR_WIDTH", 12),
        heatmap_met_emoji=_env_str("HEATMAP_MET_EMOJI", "🟥"),
        heatmap_empty_emoji=_env_str("HEATMAP_EMPTY_EMOJI", "⬜"),

        ignore_afk_channels=_env_bool("IGNORE_AFK_CHANNELS", False),

        privacy_default_private=_env_bool("PRIVACY_DEFAULT_PRIVATE", False),
        privacy_admin_can_view=_env_bool("PRIVACY_ADMIN_CAN_VIEW", True),

        dm_reminders_enabled=_env_bool("DM_REMINDERS_ENABLED", True),
        dm_streak_end_enabled=_env_bool("DM_STREAK_END_ENABLED", True),
        dm_streak_end_ice_enabled=_env_bool("DM_STREAK_END_ICE_ENABLED", True),
        dm_streak_end_restore_enabled=_env_bool("DM_STREAK_END_RESTORE_ENABLED", True),

        streak_restore_enabled=_env_bool("STREAK_RESTORE_ENABLED", True),
        streak_restore_window_minutes=_env_int("STREAK_RESTORE_WINDOW_MINUTES", 120),
        streak_end_warning_minutes=_env_int("STREAK_END_WARNING_MINUTES", 60),

        nickname_fire_enabled=_env_bool("NICKNAME_FIRE_ENABLED", True),
        nickname_fire_suffix=_env_str("NICKNAME_FIRE_SUFFIX", " 🔥"),
        nickname_edit_min_interval_seconds=_env_int("NICKNAME_EDIT_MIN_INTERVAL_SECONDS", 20),
    )

    settings.afk_channel_ids = _parse_afk_ids(os.getenv("AFK_CHANNEL_IDS", ""))

    return settings


settings = load_settings()