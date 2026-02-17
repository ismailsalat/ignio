# bot/loader.py
from __future__ import annotations

from bot.cogs.vc_tracker import VcTrackerCog
from bot.cogs.admin import AdminCog
from bot.cogs.streaks import StreaksCog
from bot.cogs.leaderboard import LeaderboardCog
from bot.cogs.errors import ErrorHandlerCog

async def load_all(bot, settings, repos, vc_state=None):
    # attach deps so any cog can grab them if needed
    bot.settings = settings
    bot.repos = repos
    if vc_state is not None:
        bot.vc_state = vc_state

    # ---- VC TRACKER ----
    try:
        vc_cog = VcTrackerCog(bot, settings, repos)
        await bot.add_cog(vc_cog)
        print("[Ignio] VcTrackerCog loaded ✅")
    except Exception as e:
        print(f"[Ignio] VcTrackerCog FAILED ❌: {e}")
        vc_cog = None

    # ---- ADMIN ----
    try:
        if vc_cog is not None:
            await bot.add_cog(AdminCog(bot, settings, repos, vc_cog.state, vc_cog))
        else:
            # fallback: pass None so admin still loads (tick_status will explain)
            await bot.add_cog(AdminCog(bot, settings, repos, None, None))
        print("[Ignio] AdminCog loaded ✅")
    except Exception as e:
        print(f"[Ignio] AdminCog FAILED ❌: {e}")

    # ---- STREAKS ----
    try:
        await bot.add_cog(StreaksCog(bot, settings, repos))
        print("[Ignio] StreaksCog loaded ✅")
    except Exception as e:
        print(f"[Ignio] StreaksCog FAILED ❌: {e}")

    # ---- LEADERBOARD ----
    try:
        await bot.add_cog(LeaderboardCog(bot, settings, repos))
        print("[Ignio] LeaderboardCog loaded ✅")
    except Exception as e:
        print(f"[Ignio] LeaderboardCog FAILED ❌: {e}")

    # ---- ERRORS ----
    try:
        await bot.add_cog(ErrorHandlerCog(bot))
        print("[Ignio] ErrorHandlerCog loaded ✅")
    except Exception as e:
        print(f"[Ignio] ErrorHandlerCog FAILED ❌: {e}")

    print("[Ignio] cogs:", ", ".join(bot.cogs.keys()))
