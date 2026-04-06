from __future__ import annotations

from dataclasses import dataclass
import os

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
    return EMOJIS.get(key, key)


def _normalize_env(v: str | None) -> str:
    s = (v or "").strip().lower()

    if s in ("dev", "development", "test", "testing"):
        return "dev"
    if s in ("prod", "production", "main", "live"):
        return "prod"

    # safer default
    return "dev"


@dataclass(frozen=True)
class Settings:
    token: str
    env: str = "prod"

    # ---------------- Bot ----------------
    command_prefix_dev: str = "!!"
    command_prefix_prod: str = "!"

    @property
    def prefix(self) -> str:
        return self.command_prefix_dev if self.env == "dev" else self.command_prefix_prod

    # ---------------- Time ----------------
    default_tz: str = "America/Los_Angeles"
    grace_hour_local: int = 3

    # ---------------- VC ----------------
    min_overlap_seconds: int = 3 * 60
    tick_seconds: int = 15
    disconnect_buffer_seconds: int = 60
    daily_cap_seconds: int = 3 * 60 * 60

    # ---------------- AFK ----------------
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

    # ---------------- DM ----------------
    dm_reminders_enabled: bool = True
    dm_remind_before_minutes: int = 30
    dm_remind_cooldown_minutes: int = 120

    dm_streak_end_enabled: bool = True
    dm_streak_end_restore_enabled: bool = True
    dm_streak_end_ice_enabled: bool = True
    restore_window_hours: int = 24

    # ---------------- Nickname Fire ----------------
    nickname_fire_enabled: bool = True
    nickname_fire_suffix: str = " 🔥"


def load_settings() -> Settings:
    if load_dotenv is not None:
        load_dotenv(override=False)

    env = _normalize_env(
        os.getenv("IGNIO_ENV")
        or os.getenv("ENV")
        or os.getenv("APP_ENV")
    )

    def _safe_len(v: str | None) -> int:
        return len(v.strip()) if isinstance(v, str) else 0

    # only print debug in dev
    if env == "dev":
        print("[ENV] Mode:", env)
        print("[ENV] Railway:", os.getenv("RAILWAY_ENVIRONMENT"))
        print("[ENV] DEV token:", _safe_len(os.getenv("DISCORD_TOKEN_DEV")))
        print("[ENV] PROD token:", _safe_len(os.getenv("DISCORD_TOKEN_PROD")))

    # -------- token selection --------
    if env == "dev":
        token = os.getenv("DISCORD_TOKEN_DEV", "").strip() or os.getenv("TOKEN_DEV", "").strip()
    else:
        token = os.getenv("DISCORD_TOKEN_PROD", "").strip() or os.getenv("TOKEN_PROD", "").strip()

    if not token:
        token = (
            os.getenv("DISCORD_TOKEN", "").strip()
            or os.getenv("TOKEN", "").strip()
            or os.getenv("DISCORD_BOT_TOKEN", "").strip()
        )

    if not token:
        raise RuntimeError("Missing bot token")

    # -------- prefixes --------
    prefix_dev = (os.getenv("IGNIO_PREFIX_DEV") or "").strip() or "!!"
    prefix_prod = (os.getenv("IGNIO_PREFIX_PROD") or "").strip() or "!"

    return Settings(
        token=token,
        env=env,
        command_prefix_dev=prefix_dev,
        command_prefix_prod=prefix_prod,
    )