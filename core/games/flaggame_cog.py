# core/games/flaggame_cog.py
"""
!mapflag — a server-COMPETITIVE flag guessing game.

The bot posts a flag; the FIRST person in the channel to name the country wins
the round and the sob reward. Each person has a daily reward cap; past it they
can still play and win rounds for fun (no sob). One winner per round, claimed
atomically so a tie can't pay two people.
"""
from __future__ import annotations

import asyncio
import secrets

import discord
from discord.ext import commands

from core.games.mapgame_data import COUNTRIES, ALIASES
from core import ledger

ACCENT = 0xF0B132
GREEN = 0x4FB477
RED = 0xE0524F

REWARD_BY_DIFFICULTY = {1: 3, 2: 5, 3: 8}
DAILY_REWARD_CAP = 60
ROUND_SECONDS = 25


def _today() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


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
    if g.replace("the ", "") == _norm(country["name"]).replace("the ", ""):
        return True
    return False


class FlagGameCog(commands.Cog):
    def __init__(self, bot, settings, sob_repo, economy):
        self.bot = bot
        self.settings = settings
        self.repo = sob_repo
        self.economy = economy
        # active round per channel: channel_id -> dict(country, claimed, lock)
        self._rounds: dict[int, dict] = {}

    async def _enabled(self, gid: int) -> bool:
        return (await self.repo.get_guild_setting(gid, "mapflag:enabled")) != "0"

    async def _earned_today(self, gid: int, uid: int) -> int:
        raw = await self.repo.get_guild_setting(gid, f"mapflag:earned:{uid}:{_today()}")
        try:
            return int(raw)
        except (TypeError, ValueError):
            return 0

    async def _add_earned(self, gid: int, uid: int, amount: int) -> None:
        cur = await self._earned_today(gid, uid)
        await self.repo.set_guild_setting(gid, f"mapflag:earned:{uid}:{_today()}", str(cur + amount))

    @commands.command(name="mapflag", aliases=["flagquiz", "guessflag"])
    @commands.guild_only()
    @commands.cooldown(1, 12, commands.BucketType.channel)
    async def mapflag(self, ctx: commands.Context):
        """Server race: first to name the country whose flag is shown wins."""
        gid = ctx.guild.id
        if not await self._enabled(gid):
            await ctx.reply(embed=discord.Embed(description="The flag game is disabled here.", color=RED))
            return
        if ctx.channel.id in self._rounds:
            await ctx.reply(embed=discord.Embed(
                description="A flag round is already running in this channel — answer that one first!",
                color=ACCENT))
            return

        country = secrets.choice(COUNTRIES)
        self._rounds[ctx.channel.id] = {"country": country, "claimed": False,
                                        "lock": asyncio.Lock()}

        e = discord.Embed(
            title="🚩 Flag Game — first to answer wins!",
            description=(f"# {country['emoji']}\n\n"
                         f"**What country is this flag?** Type your answer — fastest correct wins!\n"
                         f"*{ROUND_SECONDS}s on the clock.*"),
            color=ACCENT)
        await ctx.reply(embed=e)

        def check(m):
            return (m.channel.id == ctx.channel.id and not m.author.bot
                    and self._rounds.get(ctx.channel.id) is not None)

        deadline = ROUND_SECONDS
        winner = None
        while deadline > 0:
            import time as _t
            t0 = _t.monotonic()
            try:
                msg = await self.bot.wait_for("message", check=check, timeout=deadline)
            except asyncio.TimeoutError:
                break
            deadline -= (_t.monotonic() - t0)
            if not _matches(msg.content, country):
                continue
            # atomic claim — only the first correct answer wins
            rnd = self._rounds.get(ctx.channel.id)
            if rnd is None:
                break
            async with rnd["lock"]:
                if rnd["claimed"]:
                    continue
                rnd["claimed"] = True
                winner = msg.author
            break

        self._rounds.pop(ctx.channel.id, None)

        if winner is None:
            await ctx.send(embed=discord.Embed(
                title="⏱️ Nobody got it!",
                description=f"That flag was **{country['emoji']} {country['name']}**.",
                color=RED))
            return

        # reward the winner (up to their personal daily cap)
        reward = REWARD_BY_DIFFICULTY.get(country["difficulty"], 3)
        earned = await self._earned_today(gid, winner.id)
        give = max(0, min(reward, DAILY_REWARD_CAP - earned))
        e = discord.Embed(
            title="🏆 We have a winner!",
            description=f"{winner.mention} got it first — **{country['emoji']} {country['name']}**!",
            color=GREEN)
        if give > 0:
            try:
                await self.repo.adjust_received(
                    gid, winner.id, give, event_type=ledger.EVT_MAPGAME_REWARD,
                    metadata={"country": country["name"], "mode": "flag"})
                await self._add_earned(gid, winner.id, give)
                e.add_field(name="Reward",
                            value=f"+{give} sobs  ·  {earned + give}/{DAILY_REWARD_CAP} today",
                            inline=False)
            except Exception as ex:
                print(f"[Ignio][FlagGame] reward failed: {ex}")
        else:
            e.set_footer(text="No sobs (daily cap reached) — but the glory is yours!")
        await ctx.send(embed=e)


async def setup(bot):  # pragma: no cover
    pass
