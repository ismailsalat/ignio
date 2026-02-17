# bot/config.py
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

    # Time rules
    default_tz: str = "America/Los_Angeles"
    grace_hour_local: int = 3

    # VC overlap rules
    min_overlap_seconds: int = 2 * 60     # 10 minutes
    tick_seconds: int = 15                 # add 15 seconds per tick
    disconnect_buffer_seconds: int = 60    # allow brief disconnect

    # UI
    progress_bar_width: int = 12

    # AFK ignore (optional)
    ignore_afk_channels: bool = True
    afk_channel_ids: tuple[int, ...] = ()  # put AFK voice channel IDs here later


def load_settings() -> Settings:
    token = os.getenv("DISCORD_TOKEN", "").strip()
    if not token:
        raise RuntimeError("Missing DISCORD_TOKEN in .env (DISCORD_TOKEN=...)")
    return Settings(token=token)
