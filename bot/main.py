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

def get_db_dir() -> str:
    """
    Local default: bot/database
    Railway + volume: /data/database  (set DB_DIR in Railway variables)
    """
    return os.getenv("DB_DIR", "bot/database").strip() or "bot/database"

async def run():
    settings = load_settings()

    intents = discord.Intents.default()
    intents.message_content = True
    intents.voice_states = True
    intents.members = True

    bot = commands.Bot(command_prefix="!", intents=intents)

    # ✅ DB folder (local vs Railway)
    db_dir = get_db_dir()
    os.makedirs(db_dir, exist_ok=True)
    print(f"[Ignio] DB_DIR={db_dir}")

    db_manager = DatabaseManager(folder=db_dir)
    repos = Repos(db_manager)

    @bot.event
    async def setup_hook():
        await load_all(bot, settings, repos)
        print("[Ignio] setup_hook: cogs loaded ✅")

    @bot.event
    async def on_ready():
        print(f"[Ignio] ✅ ONLINE as {bot.user} | guilds={len(bot.guilds)}")

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
