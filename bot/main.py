import asyncio
import logging
import discord
from discord.ext import commands

from bot.config import load_settings
from bot.services.db_manager import DatabaseManager
from bot.services.repos import Repos
from bot.loader import load_all

logging.basicConfig(level=logging.INFO)

async def run():
    settings = load_settings()

    intents = discord.Intents.default()
    intents.message_content = True
    intents.voice_states = True
    intents.members = True

    bot = commands.Bot(command_prefix="!", intents=intents)

    db_manager = DatabaseManager(folder="database")
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
