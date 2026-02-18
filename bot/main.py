# bot/main.py
import asyncio
import logging
import os
import discord
from discord.ext import commands

from bot.config import load_settings
from bot.services.db_manager import DatabaseManager
from bot.services.repos import Repos
from bot.loader import load_all

logging.basicConfig(level=logging.INFO)

def get_db_dir(settings_env: str) -> str:
    """
    Local default: bot/database
    Railway + volume: /data/database  (set DB_DIR in Railway variables)

    Dev/Prod safe default:
      - if DB_DIR is set, we use it
      - else if IGNIO_ENV=dev -> bot/database_dev
      - else -> bot/database
    """
    explicit = os.getenv("DB_DIR", "").strip()
    if explicit:
        return explicit

    # Safe default separation if user doesn't set DB_DIR
    if settings_env == "dev":
        return "bot/database_dev"
    return "bot/database"

async def run():
    settings = load_settings()

    # ✅ PREFIX from config (dev/prod)
    prefix = settings.command_prefix_dev if settings.env == "dev" else settings.command_prefix_prod
    print(f"[Ignio] PREFIX='{prefix}' (env={settings.env})")

    intents = discord.Intents.default()
    intents.message_content = True
    intents.voice_states = True
    intents.members = True

    bot = commands.Bot(command_prefix=prefix, intents=intents)

    # ✅ DB folder (local vs Railway)
    db_dir = get_db_dir(settings.env)
    os.makedirs(db_dir, exist_ok=True)
    print(f"[Ignio] ENV={settings.env} | DB_DIR={db_dir}")

    db_manager = DatabaseManager(folder=db_dir)
    repos = Repos(db_manager)

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
        await db_manager.close_all()

if __name__ == "__main__":
    asyncio.run(run())
