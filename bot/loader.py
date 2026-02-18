# bot/loader.py
from __future__ import annotations

import traceback

from bot.cogs.vc_tracker import VcTrackerCog
from bot.cogs.admin import AdminCog
from bot.cogs.streaks import StreaksCog
from bot.cogs.leaderboard import LeaderboardCog
from bot.cogs.user_settings import UserSettingsCog
from bot.cogs.errors import ErrorHandlerCog


async def load_all(bot, settings, repos, vc_state=None):
    print("[Ignio] Starting loader...")

    # attach shared deps (so any cog can grab them if needed)
    bot.settings = settings
    bot.repos = repos

    # ✅ Always ensure a shared VC state exists (but don't warn — this is normal)
    if vc_state is None:
        from bot.core.state import VcRuntimeState
        vc_state = VcRuntimeState()

    # expose it on bot so other cogs / utilities can access it
    bot.vc_state = vc_state

    vc_cog = None

    # ---------------- VC TRACKER ----------------
    try:
        # Prefer injecting vc_state if the cog supports it
        try:
            vc_cog = VcTrackerCog(bot, settings, repos, vc_state=vc_state)
        except TypeError:
            vc_cog = VcTrackerCog(bot, settings, repos)

        await bot.add_cog(vc_cog)
        print("[Ignio] ✅ VcTrackerCog loaded")
    except Exception:
        print("[Ignio] ❌ VcTrackerCog FAILED")
        traceback.print_exc()
        vc_cog = None

    # Determine the best state reference for admin tools:
    # - if vc_cog exposes .state, use it (most accurate)
    # - else use the shared vc_state we created
    effective_state = getattr(vc_cog, "state", None) if vc_cog else None
    if effective_state is None:
        effective_state = vc_state

    # ---------------- ADMIN ----------------
    try:
        await bot.add_cog(
            AdminCog(
                bot=bot,
                settings=settings,
                repos=repos,
                vc_state=effective_state,
                vc_cog=vc_cog,
            )
        )
        print("[Ignio] ✅ AdminCog loaded")
    except Exception:
        print("[Ignio] ❌ AdminCog FAILED")
        traceback.print_exc()

    # ---------------- STREAKS ----------------
    try:
        await bot.add_cog(StreaksCog(bot, settings, repos))
        print("[Ignio] ✅ StreaksCog loaded")
    except Exception:
        print("[Ignio] ❌ StreaksCog FAILED")
        traceback.print_exc()

    # ---------------- USER SETTINGS ----------------
    try:
        await bot.add_cog(UserSettingsCog(bot, settings, repos))
        print("[Ignio] ✅ UserSettingsCog loaded")
    except Exception:
        print("[Ignio] ❌ UserSettingsCog FAILED")
        traceback.print_exc()

    # ---------------- LEADERBOARD ----------------
    try:
        await bot.add_cog(LeaderboardCog(bot, settings, repos))
        print("[Ignio] ✅ LeaderboardCog loaded")
    except Exception:
        print("[Ignio] ❌ LeaderboardCog FAILED")
        traceback.print_exc()

    # ---------------- ERROR HANDLER ----------------
    try:
        await bot.add_cog(ErrorHandlerCog(bot))
        print("[Ignio] ✅ ErrorHandlerCog loaded")
    except Exception:
        print("[Ignio] ❌ ErrorHandlerCog FAILED")
        traceback.print_exc()

    print("[Ignio] Loaded cogs:", ", ".join(bot.cogs.keys()))
