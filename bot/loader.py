# bot/loader.py
from __future__ import annotations

import traceback

from bot.core.state import VcRuntimeState
from bot.cogs.vc_tracker import VcTrackerCog
from bot.cogs.admin import AdminCog
from bot.cogs.streaks import StreaksCog
from bot.cogs.leaderboard import LeaderboardCog
from bot.cogs.user_settings import UserSettingsCog
from bot.cogs.errors import ErrorHandlerCog


async def _safe_add_cog(bot, cog, name: str) -> bool:
    try:
        await bot.add_cog(cog)
        print(f"[Ignio] ✅ {name} loaded")
        return True
    except Exception:
        print(f"[Ignio] ❌ {name} FAILED")
        traceback.print_exc()
        return False


async def load_all(bot, settings, repos, vc_state=None):
    print("[Ignio] Starting loader...")

    # shared deps
    bot.settings = settings
    bot.repos = repos

    # shared runtime VC state
    if vc_state is None:
        vc_state = VcRuntimeState()
    bot.vc_state = vc_state

    # build cogs first
    vc_cog = VcTrackerCog(bot, settings, repos)
    admin_cog = AdminCog(
        bot=bot,
        settings=settings,
        repos=repos,
        vc_state=getattr(vc_cog, "state", vc_state),
        vc_cog=vc_cog,
    )
    streaks_cog = StreaksCog(bot, settings, repos)
    user_settings_cog = UserSettingsCog(bot, settings, repos)
    leaderboard_cog = LeaderboardCog(bot, settings, repos)
    error_cog = ErrorHandlerCog(bot)

    # load in order
    await _safe_add_cog(bot, vc_cog, "VcTrackerCog")
    await _safe_add_cog(bot, admin_cog, "AdminCog")
    await _safe_add_cog(bot, streaks_cog, "StreaksCog")
    await _safe_add_cog(bot, user_settings_cog, "UserSettingsCog")
    await _safe_add_cog(bot, leaderboard_cog, "LeaderboardCog")
    await _safe_add_cog(bot, error_cog, "ErrorHandlerCog")

    print("[Ignio] Loaded cogs:", ", ".join(bot.cogs.keys()))