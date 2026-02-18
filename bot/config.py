from __future__ import annotations

from dataclasses import dataclass
import os

# Optional: loads .env locally if installed, but will NOT override Railway env vars
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


def _normalize_env(v: str | None) -> str:
    """
    Returns 'dev' or 'prod' only.
    Defaults to 'prod' if unset/unknown.
    """
    s = (v or "").strip().lower()
    if s in ("dev", "development", "test", "testing"):
        return "dev"
    if s in ("prod", "production", "main", "live"):
        return "prod"
    return "prod"


@dataclass(frozen=True)
class Settings:
    token: str
    env: str = "prod"  # dev or prod

    # ---------------- Bot / Commands ----------------
    # Defaults (can be overridden by env vars, see load_settings)
    command_prefix_dev: str = "!!"
    command_prefix_prod: str = "!"

    # ---------------- Time rules ----------------
    default_tz: str = "America/Los_Angeles"
    grace_hour_local: int = 3  # day closes at 3:00 AM local time

    # ---------------- VC overlap rules ----------------
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
    heatmap_met_emoji: str = "🟥"
    heatmap_empty_emoji: str = "⬜"

    # ---------------- Privacy ----------------
    privacy_default_private: bool = False
    privacy_admin_can_view: bool = True

    # ---------------- DM reminders ----------------
    dm_reminders_enabled: bool = True
    dm_remind_before_minutes: int = 30
    dm_remind_cooldown_minutes: int = 120

    # DM streak ended messages
    dm_streak_end_enabled: bool = True
    dm_streak_end_restore_enabled: bool = True
    dm_streak_end_ice_enabled: bool = True
    restore_window_hours: int = 24

    # ---------------- Nickname Fire System (NEW) ----------------
    nickname_fire_enabled: bool = True
    nickname_fire_suffix: str = " 🔥"


def load_settings() -> Settings:
    # ---------- Normal behavior ----------
    if load_dotenv is not None:
        load_dotenv(override=False)

    env = _normalize_env(os.getenv("IGNIO_ENV") or os.getenv("ENV") or os.getenv("APP_ENV"))

    # ---------- DEBUG (safe: does NOT print token value) ----------
    def _safe_len(v: str | None) -> int:
        return len(v.strip()) if isinstance(v, str) else 0

    print("[ENV] IGNIO_ENV =", env)
    print("[ENV] Running on Railway? RAILWAY_ENVIRONMENT =", os.getenv("RAILWAY_ENVIRONMENT"))

    # Dev/prod token presence (never print token)
    print("[ENV] DISCORD_TOKEN_DEV present?  ", "DISCORD_TOKEN_DEV" in os.environ, "len=", _safe_len(os.getenv("DISCORD_TOKEN_DEV")))
    print("[ENV] DISCORD_TOKEN_PROD present? ", "DISCORD_TOKEN_PROD" in os.environ, "len=", _safe_len(os.getenv("DISCORD_TOKEN_PROD")))

    # Legacy/fallback token vars
    print("[ENV] DISCORD_TOKEN present? ", "DISCORD_TOKEN" in os.environ, "len=", _safe_len(os.getenv("DISCORD_TOKEN")))
    print("[ENV] TOKEN present?        ", "TOKEN" in os.environ, "len=", _safe_len(os.getenv("TOKEN")))
    print("[ENV] DISCORD_BOT_TOKEN present?", "DISCORD_BOT_TOKEN" in os.environ, "len=", _safe_len(os.getenv("DISCORD_BOT_TOKEN")))

    # Prefix overrides (safe to print)
    print("[ENV] IGNIO_PREFIX_DEV present?  ", "IGNIO_PREFIX_DEV" in os.environ, "value=", (os.getenv("IGNIO_PREFIX_DEV") or "").strip())
    print("[ENV] IGNIO_PREFIX_PROD present? ", "IGNIO_PREFIX_PROD" in os.environ, "value=", (os.getenv("IGNIO_PREFIX_PROD") or "").strip())

    # show any env keys related to token/discord/railway (no values)
    interesting = []
    for k in os.environ.keys():
        up = k.upper()
        if any(x in up for x in ["DISCORD", "TOKEN", "RAILWAY", "NIXPACKS", "PORT", "IGNIO", "ENV", "APP_ENV", "PREFIX"]):
            interesting.append(k)
    interesting_sorted = sorted(interesting)
    print("[ENV] Interesting env keys:", interesting_sorted[:80])
    if len(interesting_sorted) > 80:
        print("[ENV] (more keys omitted) total=", len(interesting_sorted))

    # ---------- Token selection ----------
    # Priority:
    # 1) DISCORD_TOKEN_DEV / DISCORD_TOKEN_PROD depending on IGNIO_ENV
    # 2) legacy DISCORD_TOKEN / TOKEN / DISCORD_BOT_TOKEN
    token = ""
    if env == "dev":
        token = (os.getenv("DISCORD_TOKEN_DEV", "").strip() or os.getenv("TOKEN_DEV", "").strip())
    else:
        token = (os.getenv("DISCORD_TOKEN_PROD", "").strip() or os.getenv("TOKEN_PROD", "").strip())

    if not token:
        token = (
            os.getenv("DISCORD_TOKEN", "").strip()
            or os.getenv("TOKEN", "").strip()
            or os.getenv("DISCORD_BOT_TOKEN", "").strip()
        )

    if not token:
        try:
            exists = os.path.exists(".env")
        except Exception:
            exists = False
        print("[ENV] .env exists in container? ", exists)

        raise RuntimeError(
            "Missing bot token.\n"
            "Set IGNIO_ENV=dev and DISCORD_TOKEN_DEV=... for dev, OR\n"
            "set IGNIO_ENV=prod and DISCORD_TOKEN_PROD=... for prod.\n"
            "Fallback supported: DISCORD_TOKEN / TOKEN / DISCORD_BOT_TOKEN."
        )

    # ---------- Prefix selection (defaults + optional env override) ----------
    # Default dev/prod prefixes are stored in Settings. Env can override without code changes.
    prefix_dev = (os.getenv("IGNIO_PREFIX_DEV") or "").strip() or "!!"
    prefix_prod = (os.getenv("IGNIO_PREFIX_PROD") or "").strip() or "!"

    return Settings(
        token=token,
        env=env,
        command_prefix_dev=prefix_dev,
        command_prefix_prod=prefix_prod,
    )
