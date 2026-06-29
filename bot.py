# bot.py
from __future__ import annotations

import logging
import os

import discord
from discord.ext import commands

from config import load_settings
from core.backup import backup_database
from core.db import DatabaseManager
from core.sob.repo import SobRepo
from core.sob.cog import SobCog
from core.admin.cog import AdminCog
from core.shop.repo import ShopRepo
from core.shop.cog import ShopCog
from core.help.cog import HelpCog
from core.perms_cog import PermsCog
from core.announce_cog import AnnounceCog
from core.profile.cog import ProfileService
from core.gating import Gating
from core.gating_cog import GatingCog
from core.about_cog import AboutCog
from core.economy import Economy
from core.economy_cog import EconomyCog
from core.daily_cog import DailyCog
from core.games.roulette_cog import RouletteCog

logging.basicConfig(level=logging.INFO)


def get_db_dir(env: str) -> str:
    """
    Local default: dev -> database_dev, prod -> database.
    Railway / volume: set DB_DIR=/data/database.
    """
    explicit = os.getenv("DB_DIR", "").strip()
    if explicit:
        return explicit
    return "database_dev" if env == "dev" else "database"


async def run() -> None:
    settings = load_settings()
    prefix = settings.command_prefix_dev if settings.env == "dev" else settings.command_prefix_prod
    print(f"[Ignio] PREFIX='{prefix}' (env={settings.env})")

    intents = discord.Intents.default()
    intents.message_content = True
    intents.members = True
    intents.reactions = True

    bot = commands.Bot(command_prefix=prefix, intents=intents)

    # Make is_owner() recognize the configured owner IDs too.
    if settings.owner_ids:
        bot.owner_ids = set(settings.owner_ids)

    db_dir = get_db_dir(settings.env)
    os.makedirs(db_dir, exist_ok=True)
    db_path = os.path.join(db_dir, "ignio.sqlite3")
    print(f"[Ignio] ENV={settings.env} | DB_PATH={db_path}")

    db_manager = DatabaseManager(path=db_path)
    sob_repo = SobRepo(db_manager)
    economy = Economy(sob_repo)
    from core.games.engine import GamesEngine
    games_engine = GamesEngine(sob_repo, economy)
    shop_repo = ShopRepo(db_manager, sob_repo, economy)
    # Risk-based protection pricing (prices shields/wards from each buyer's own
    # exposure, never above the damage prevented).
    from core.protection import Protection
    protection = Protection(economy, sob_repo)
    shop_repo.protection = protection
    economy.protection = protection
    profile_service = ProfileService(bot, settings, sob_repo)
    gate = Gating(sob_repo)

    # Safety net: back up the live DB before migrations run on first boot.
    # Enabled by default in prod; toggle with DB_BACKUP_ON_START=0/1.
    backup_default = "1" if settings.env == "prod" else "0"
    if os.getenv("DB_BACKUP_ON_START", backup_default).strip() in ("1", "true", "yes", "on"):
        try:
            backup_database(db_path)
        except Exception as exc:  # never let a backup failure block startup
            print(f"[Ignio] ⚠️ DB backup skipped (error: {exc})")

    @bot.event
    async def setup_hook():
        # Force-connect once so migrations run before the bot is ready.
        await db_manager.get()
        for name, cog in (
            ("SobCog", SobCog(bot, settings, sob_repo, shop_repo, profile_service, economy)),
            ("AdminCog", AdminCog(bot, settings, db_manager, sob_repo, profile_service)),
            ("ShopCog", ShopCog(bot, settings, shop_repo, sob_repo, economy)),
            ("HelpCog", HelpCog(bot, settings)),
            ("PermsCog", PermsCog(bot, settings, sob_repo)),
            ("AnnounceCog", AnnounceCog(bot, settings, sob_repo)),
            ("GatingCog", GatingCog(bot, settings, gate)),
            ("EconomyCog", EconomyCog(bot, settings, sob_repo)),
            ("DailyCog", DailyCog(bot, settings, sob_repo)),
            ("AboutCog", AboutCog(bot, settings, sob_repo)),
            ("RouletteCog", RouletteCog(bot, settings, sob_repo, games_engine)),
        ):
            try:
                await bot.add_cog(cog)
                print(f"[Ignio] ✅ {name} loaded")
            except Exception:
                import traceback
                print(f"[Ignio] ❌ {name} FAILED to load")
                traceback.print_exc()
        print("[Ignio] setup_hook: done")

        # Safety: refund any roulette/game escrow left 'pending' from a crash or
        # restart mid-match, so locked wagers are never silently lost.
        try:
            refunded = await games_engine.recover_pending()
            if refunded:
                print(f"[Ignio] ♻️ refunded {refunded} orphaned game escrow(s)")
        except Exception as exc:
            print(f"[Ignio] ⚠️ escrow recovery skipped (error: {exc})")

    @bot.event
    async def on_ready():
        print(f"[Ignio] ✅ ONLINE as {bot.user} | guilds={len(bot.guilds)} | env={settings.env}")

    @bot.check
    async def _gating_check(ctx):
        # No gating in DMs or when there's no command.
        if ctx.guild is None or ctx.command is None:
            return True
        root = ctx.command.root_parent or ctx.command
        try:
            blocked = await gate.is_blocked(ctx.guild.id, ctx.channel.id, root.name)
        except Exception:
            return True  # never let the gate check crash a command

        from core.gating import _is_admin
        if _is_admin(ctx.author, settings):
            # Admins always bypass — but if this command is disabled for normal
            # users here, leave a quiet note so the admin knows the rule is live.
            if blocked:
                try:
                    await ctx.send(
                        f"🛠️ *Heads up: this command is disabled here for non-admins — "
                        f"you're seeing it because you're an admin. `{ctx.prefix}commandconfig` to review.*",
                        delete_after=8,
                    )
                except Exception:
                    pass
            return True

        if blocked:
            raise commands.CheckFailure("That command is disabled here.")
        return True

    @bot.event
    async def on_message(message: discord.Message):
        if message.author.bot:
            return
        await bot.process_commands(message)

    @bot.event
    async def on_command_error(ctx, error):
        # Unwrap to the original error where relevant.
        err = getattr(error, "original", error)

        if isinstance(error, commands.CommandNotFound):
            return  # ignore unknown commands silently
        if isinstance(error, commands.MissingRequiredArgument):
            await ctx.reply(f"Missing something — try `{ctx.prefix}{ctx.command} {ctx.command.signature}`")
            return
        if isinstance(error, commands.BadArgument):
            await ctx.reply("That didn't look right. Check the command and try again.")
            return
        if isinstance(error, commands.CheckFailure):
            await ctx.reply(str(error) or "You can't use that here.")
            return
        if isinstance(error, commands.NoPrivateMessage):
            await ctx.reply("That command only works in a server.")
            return

        # Anything else: log it server-side, give the user a soft message.
        print(f"[Ignio][Error] {type(err).__name__}: {err}")
        try:
            await ctx.reply("Something went wrong with that command.")
        except Exception:
            pass

    try:
        await bot.start(settings.token)
    finally:
        await db_manager.close()