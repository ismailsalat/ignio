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
import time as _t

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
        """A 5-round server race: first to name each flag's country wins the round."""
        gid = ctx.guild.id
        if not await self._enabled(gid):
            await ctx.reply(embed=discord.Embed(description="The flag game is disabled here.", color=RED))
            return
        if ctx.channel.id in self._rounds:
            await ctx.reply(embed=discord.Embed(
                description="A Flag Game is already running here — join by typing your guess!",
                color=ACCENT))
            return
        self._rounds[ctx.channel.id] = {"active": True}
        try:
            await self._run_flag_session(ctx, gid)
        finally:
            self._rounds.pop(ctx.channel.id, None)

    def _dots(self, done: int, total: int = 5) -> str:
        return " ".join("●" if i < done else "○" for i in range(total))

    async def _update_flag_msg(self, ctx, state, embed):
        """Edit the one persistent flag message, or create it the first time."""
        msg = state.get("msg")
        if msg is not None:
            try:
                await msg.edit(embed=embed)
                return
            except Exception:
                pass
        state["msg"] = await ctx.send(embed=embed)

    async def _run_flag_session(self, ctx, gid, total_rounds: int = 5):
        state = {"msg": None}
        winners = []
        for rnd in range(1, total_rounds + 1):
            res = await self._run_flag_round(ctx, gid, rnd, total_rounds, state)
            winners.append((rnd, res["winner"], res["country"]))
            if rnd < total_rounds:
                await asyncio.sleep(2)
        lines = [f"{r}. {(w or 'Nobody')} — {c}" for r, w, c in winners]
        await self._update_flag_msg(ctx, state, discord.Embed(
            title="🏁 Flag Game complete",
            description="\n".join(lines) + f"\n\nRun `{ctx.prefix}mapflag` to start another race.",
            color=ACCENT))

    async def _run_flag_round(self, ctx, gid, round_no: int, total_rounds: int, state):
        country = secrets.choice(COUNTRIES)
        claim = {"claimed": False, "winner": None}
        lock = asyncio.Lock()
        last_guess: dict[int, float] = {}

        await self._update_flag_msg(ctx, state, discord.Embed(
            title=f"🚩 Flag Game · Round {round_no}/{total_rounds}",
            description=(f"# {country['emoji']}\n{self._dots(round_no - 1, total_rounds)}\n\n"
                         f"**What country is this flag?** Type your guess · {ROUND_SECONDS}s"),
            color=ACCENT))

        def check(m):
            if m.channel.id != ctx.channel.id or m.author.bot:
                return False
            now = _t.monotonic()
            if now - last_guess.get(m.author.id, 0) < 1.0:
                return False
            last_guess[m.author.id] = now
            return _matches(m.content, country)  # wrong guesses never pass -> silent

        deadline = ROUND_SECONDS
        winner = None
        while deadline > 0:
            t0 = _t.monotonic()
            try:
                msg = await self.bot.wait_for("message", check=check, timeout=deadline)
            except asyncio.TimeoutError:
                break
            deadline -= (_t.monotonic() - t0)
            async with lock:
                if claim["claimed"]:
                    continue
                claim["claimed"] = True
                winner = msg.author
            break

        if winner is None:
            nxt = "" if round_no == total_rounds else "\n\nNext round starting…"
            await self._update_flag_msg(ctx, state, discord.Embed(
                description=f"⌛ Time's up — it was **{country['emoji']} {country['name']}**." + nxt,
                color=RED))
            return {"winner": None, "country": country["name"]}

        reward = REWARD_BY_DIFFICULTY.get(country["difficulty"], 3)
        earned = await self._earned_today(gid, winner.id)
        give = max(0, min(reward, DAILY_REWARD_CAP - earned))
        desc = f"✅ **{winner.display_name}** got it — {country['emoji']} {country['name']}"
        if give > 0:
            try:
                await self.repo.adjust_received(
                    gid, winner.id, give, event_type=ledger.EVT_MAPGAME_REWARD,
                    metadata={"country": country["name"], "mode": "flag"})
                await self._add_earned(gid, winner.id, give)
                desc += f"\n+{give} sobs · {earned + give}/{DAILY_REWARD_CAP} today"
            except Exception as ex:
                print(f"[Ignio][FlagGame] reward failed: {ex}")
        elif earned >= DAILY_REWARD_CAP:
            desc += "\n(daily sob cap reached — still a great guess!)"
        if round_no < total_rounds:
            desc += f"\n\nRound {round_no + 1} starting…"
        await self._update_flag_msg(ctx, state, discord.Embed(description=desc, color=GREEN))
        return {"winner": winner.display_name, "country": country["name"]}


async def setup(bot):  # pragma: no cover
    pass
