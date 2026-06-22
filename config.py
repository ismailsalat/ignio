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
    "sob": "😭",
    "anti": "🚫",
    "tomato": "🍅",
    "trophy": "🏆",
    "warning": "⚠️",
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


def _env_ids(name: str) -> tuple[int, ...]:
    raw = os.getenv(name, "") or ""
    ids: list[int] = []
    for part in raw.replace(";", ",").split(","):
        part = part.strip()
        if not part:
            continue
        try:
            ids.append(int(part))
        except ValueError:
            continue
    return tuple(ids)


# -------------------------------------------------
# token helper (dev/prod, kept as-is)
# -------------------------------------------------

def _pick_token(env_name: str) -> tuple[str, str, str]:
    dev_token = _env_str("DISCORD_TOKEN_DEV")
    prod_token = _env_str("DISCORD_TOKEN_PROD")
    fallback = _env_str("DISCORD_TOKEN", _env_str("TOKEN"))

    if env_name == "dev":
        token = dev_token or fallback
    else:
        token = prod_token or fallback

    return token, dev_token, prod_token


# -------------------------------------------------
# bot developer access
# -------------------------------------------------
# These user IDs always have admin/dev access, regardless of who owns the
# Discord application or the server. Add your own ID here. You can ALSO set
# the OWNER_IDS env var (comma-separated) — the two lists are merged.
DEV_OWNER_IDS: tuple[int, ...] = (
    734701612903170068,  # Milk
)


# -------------------------------------------------
# settings
# -------------------------------------------------

@dataclass(slots=True)
class Settings:
    env: str = "dev"
    command_prefix_dev: str = "!!"
    command_prefix_prod: str = "!"
    prefix: str = "!!"

    token: str = ""
    discord_token_dev: str = ""
    discord_token_prod: str = ""

    snitch_threshold: int = 10
    owner_ids: tuple[int, ...] = ()


def load_settings() -> Settings:
    env_name = _env_str("IGNIO_ENV", "dev").lower()

    command_prefix_dev = _env_str("COMMAND_PREFIX_DEV", _env_str("PREFIX_DEV", "!!"))
    command_prefix_prod = _env_str("COMMAND_PREFIX_PROD", _env_str("PREFIX_PROD", "!"))

    token, dev_token, prod_token = _pick_token(env_name)

    return Settings(
        env=env_name,
        command_prefix_dev=command_prefix_dev,
        command_prefix_prod=command_prefix_prod,
        prefix=command_prefix_dev if env_name == "dev" else command_prefix_prod,
        token=token,
        discord_token_dev=dev_token,
        discord_token_prod=prod_token,
        snitch_threshold=_env_int("SNITCH_THRESHOLD", 10),
        owner_ids=tuple(dict.fromkeys(DEV_OWNER_IDS + _env_ids("OWNER_IDS"))),
    )


settings = load_settings()
