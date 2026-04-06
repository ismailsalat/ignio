# bot/main.py
import asyncio
import logging
import os

import discord
from discord.ext import commands

from bot.config import load_settings
from bot.services.db_manager import DatabaseManager
from bot.services.streak_repo import StreakRepo
from bot.loader import load_all

logging.basicConfig(level=logging.INFO)


def get_db_dir(settings_env: str) -> str:
    """
    Local default:
      - dev  -> bot/database_dev
      - prod -> bot/database

    Railway / volume:
      - set DB_DIR=/data/database
    """
    explicit = os.getenv("DB_DIR", "").strip()
    if explicit:
        return explicit

    if settings_env == "dev":
        return "bot/database_dev"
    return "bot/database"


async def run():
    settings = load_settings()

    prefix = settings.command_prefix_dev if settings.env == "dev" else settings.command_prefix_prod
    print(f"[Ignio] PREFIX='{prefix}' (env={settings.env})")

    intents = discord.Intents.default()
    intents.message_content = True
    intents.voice_states = True
    intents.members = True

    bot = commands.Bot(command_prefix=prefix, intents=intents)

    db_dir = get_db_dir(settings.env)
    os.makedirs(db_dir, exist_ok=True)

    db_path = os.path.join(db_dir, "ignio.sqlite3")
    print(f"[Ignio] ENV={settings.env} | DB_PATH={db_path}")

    db_manager = DatabaseManager(path=db_path)
    repos = StreakRepo(db_manager)

    @bot.event
    async def setup_hook():
        await load_all(bot, settings, repos)
        print("[Ignio] setup_hook: cogs loaded ✅")

    @bot.event
    async def on_ready():
        print(f"[Ignio] ✅ ONLINE as {bot.user} | guilds={len(bot.guilds)} | env={settings.env}")

    @bot.event
    async def on_message(message: discord.Message):
        if message.author.bot:
            return
        await bot.process_commands(message)

    try:
        await bot.start(settings.token)
    finally:
        await db_manager.close()


if __name__ == "__main__":
    asyncio.run(run())