# core/games/mapgame_cog.py
"""
!mapgame — guess the country the arrow points to.

Fun geography game that pays a little sob for correct guesses, up to a daily cap.
Past the cap you can keep playing for fun (no reward). Lives under Games.
"""
from __future__ import annotations

import secrets
import time

import discord
from discord.ext import commands

from core.games.mapgame_data import COUNTRIES, ALIASES
from core.games.mapgame_render import render_board
from core import ledger

ACCENT = 0x6FB7B0
GREEN = 0x4FB477
RED = 0xE0524F

# ---- tunables (admin-overridable) ----
REWARD_BY_DIFFICULTY = {1: 3, 2: 5, 3: 8}   # sob reward per correct guess
DAILY_REWARD_CAP = 60                        # max sob/day from the map game
GUESS_SECONDS = 20                           # time to answer one round


def _norm(s: str) -> str:
    return "".join(ch for ch in s.lower().strip() if ch.isalnum() or ch == " ").strip()


def _matches(guess: str, country: dict) -> bool:
    g = _norm(guess)
    if not g:
        return False
    if g == _norm(country["name"]):
        return True
    if ALIASES.get(g) == country["name"]:
        return True
    # allow dropping "the " and minor variants
    if g.replace("the ", "") == _norm(country["name"]).replace("the ", ""):
        return True
    return False


class MapGameCog(commands.Cog):
    def __init__(self, bot, settings, sob_repo, economy):
        self.bot = bot
        self.settings = settings
        self.repo = sob_repo
        self.economy = economy
        self._active: set[int] = set()    # channel_ids with a running round

    async def _enabled(self, gid: int) -> bool:
        return (await self.repo.get_guild_setting(gid, "mapgame:enabled")) != "0"

    async def _earned_today(self, gid: int, uid: int) -> int:
        raw = await self.repo.get_guild_setting(gid, f"mapgame:earned:{uid}:{_today()}")
        try:
            return int(raw)
        except (TypeError, ValueError):
            return 0

    async def _add_earned(self, gid: int, uid: int, amount: int) -> None:
        cur = await self._earned_today(gid, uid)
        await self.repo.set_guild_setting(gid, f"mapgame:earned:{uid}:{_today()}", str(cur + amount))

    @commands.command(name="mapgame", aliases=["guesscountry", "geo"])
    @commands.guild_only()
    @commands.cooldown(1, 12, commands.BucketType.channel)
    async def mapgame(self, ctx: commands.Context):
        """Guess the country the arrow points to. Pays a little sob (daily cap)."""
        gid = ctx.guild.id
        if not await self._enabled(gid):
            await ctx.reply(embed=discord.Embed(description="The map game is disabled here.", color=RED))
            return
        # one active map per channel, so the channel never floods with maps
        if ctx.channel.id in self._active:
            await ctx.reply(embed=discord.Embed(
                description="A map round is already running here — answer that one first!",
                color=ACCENT))
            return
        self._active.add(ctx.channel.id)
        try:
            await self._run_round(ctx, gid)
        finally:
            self._active.discard(ctx.channel.id)

    async def _run_round(self, ctx, gid):
        country = secrets.choice(COUNTRIES)
        reward = REWARD_BY_DIFFICULTY.get(country["difficulty"], 3)
        earned = await self._earned_today(gid, ctx.author.id)
        capped = earned >= DAILY_REWARD_CAP

        buf = render_board(country["x"], country["y"])
        intro = ("🗺️ **Map Game** — what country is the arrow pointing to? "
                 f"You have {GUESS_SECONDS}s. Type your answer!")
        if capped:
            intro += "\n*(You've hit today's sob cap — still fun to play though!)*"
        await ctx.reply(content=intro, file=discord.File(buf, filename="mapgame.png"))

        def check(m):
            return m.author.id == ctx.author.id and m.channel.id == ctx.channel.id

        try:
            msg = await self.bot.wait_for("message", check=check, timeout=GUESS_SECONDS)
        except Exception:
            await ctx.send(embed=discord.Embed(
                title="⏱️ Time's up!",
                description=f"It was **{country['emoji']} {country['name']}**.",
                color=RED))
            return

        if _matches(msg.content, country):
            # award if under the daily cap
            give = 0
            if not capped:
                give = min(reward, DAILY_REWARD_CAP - earned)
            e = discord.Embed(title="✅ Correct!",
                              description=f"That's **{country['emoji']} {country['name']}**!",
                              color=GREEN)
            if give > 0:
                try:
                    await self.repo.adjust_received(
                        gid, ctx.author.id, give, event_type=ledger.EVT_MAPGAME_REWARD,
                        metadata={"country": country["name"]})
                    await self._add_earned(gid, ctx.author.id, give)
                    new_today = earned + give
                    e.add_field(name="Reward", value=f"+{give} sobs  ·  {new_today}/{DAILY_REWARD_CAP} today",
                                inline=False)
                except Exception as ex:
                    print(f"[Ignio][MapGame] reward failed: {ex}")
            else:
                e.set_footer(text="No sobs this time (daily cap reached) — but nice guess!")
            await msg.reply(embed=e)
        else:
            await msg.reply(embed=discord.Embed(
                title="❌ Not quite",
                description=f"It was **{country['emoji']} {country['name']}**. Try again with `{ctx.prefix}mapgame`!",
                color=RED))


def _today() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


async def setup(bot):  # pragma: no cover
    pass
