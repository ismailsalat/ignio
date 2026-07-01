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
        """A 5-round server race: guess the country the arrow points to.
        Anyone can guess. First correct answer wins the round. Wrong guesses are
        silent. Pays a little sob (daily cap unchanged)."""
        gid = ctx.guild.id
        if not await self._enabled(gid):
            await ctx.reply(embed=discord.Embed(description="The map game is disabled here.", color=RED))
            return
        if ctx.channel.id in self._active:
            await ctx.reply(embed=discord.Embed(
                description="A Map Game is already running here — join by typing your guess!",
                color=ACCENT))
            return
        self._active.add(ctx.channel.id)
        try:
            await self._run_session(ctx, gid)
        finally:
            self._active.discard(ctx.channel.id)

    def _dots(self, done: int, total: int = 5) -> str:
        return " ".join("●" if i < done else "○" for i in range(total))

    async def _show_round_card(self, ctx, state, country, round_no, total_rounds):
        """Replace the game message with a fresh round card (map image).
        Discord can't swap an attachment via edit, so we delete + resend, keeping
        exactly one game card in the channel."""
        buf = render_board(country["x"], country["y"], round_no, total_rounds)
        header = (f"🗺️ **Map Game** · Round {round_no}/{total_rounds}\n"
                  f"{self._dots(round_no - 1, total_rounds)}\n"
                  f"Type the country name below · {GUESS_SECONDS}s")
        old = state.get("msg")
        state["msg"] = await ctx.send(content=header, file=discord.File(buf, filename="mapgame.png"))
        if old is not None:
            try:
                await old.delete()
            except Exception:
                pass

    async def _show_transition(self, ctx, state, desc, color):
        """Edit the current game message into a compact result state (no image)."""
        msg = state.get("msg")
        e = discord.Embed(description=desc, color=color)
        if msg is not None:
            try:
                await msg.edit(content=None, embed=e, attachments=[])
                return
            except Exception:
                pass
        state["msg"] = await ctx.send(embed=e)

    async def _run_session(self, ctx, gid, total_rounds: int = 5):
        import asyncio
        state = {"msg": None}
        winners = []
        for rnd in range(1, total_rounds + 1):
            result = await self._run_round(ctx, gid, rnd, total_rounds, state)
            winners.append((rnd, result["winner"], result["country"]))
            if rnd < total_rounds:
                await asyncio.sleep(2)
        # final results — edit the same card into a compact summary (no image)
        lines = [f"{r}. {(w or 'Nobody')} — {c}" for r, w, c in winners]
        desc = "🏁 **Map Game complete**\n\n" + "\n".join(lines) + \
               f"\n\nRun `{ctx.prefix}mapgame` to start another race."
        await self._show_transition(ctx, state, desc, ACCENT)

    async def _run_round(self, ctx, gid, round_no, total_rounds, state):
        import asyncio
        country = secrets.choice(COUNTRIES)
        reward = REWARD_BY_DIFFICULTY.get(country["difficulty"], 3)

        await self._show_round_card(ctx, state, country, round_no, total_rounds)

        winner = {"id": None, "display": None}
        lock = asyncio.Lock()
        last_guess: dict[int, float] = {}

        def check(m):
            if m.channel.id != ctx.channel.id or m.author.bot:
                return False
            now = time.monotonic()
            if now - last_guess.get(m.author.id, 0) < 1.0:
                return False
            last_guess[m.author.id] = now
            return _matches(m.content, country)  # only CORRECT guesses pass; wrong = silent

        try:
            msg = await self.bot.wait_for("message", check=check, timeout=GUESS_SECONDS)
        except asyncio.TimeoutError:
            nxt = "" if round_no == total_rounds else f"\n\nRound {round_no + 1} starting…"
            await self._show_transition(
                ctx, state,
                f"⌛ Time's up — it was **{country['emoji']} {country['name']}**." + nxt, RED)
            return {"winner": None, "country": country["name"]}

        async with lock:
            if winner["id"] is not None:
                return {"winner": winner["display"], "country": country["name"]}
            winner["id"] = msg.author.id
            winner["display"] = msg.author.display_name

        # reward with the SAME cap logic as before (unchanged amounts/caps)
        earned = await self._earned_today(gid, msg.author.id)
        capped = earned >= DAILY_REWARD_CAP
        give = 0 if capped else min(reward, DAILY_REWARD_CAP - earned)
        desc = f"✅ **{msg.author.display_name}** got it — {country['emoji']} {country['name']}"
        if give > 0:
            try:
                await self.repo.adjust_received(
                    gid, msg.author.id, give, event_type=ledger.EVT_MAPGAME_REWARD,
                    metadata={"country": country["name"]})
                await self._add_earned(gid, msg.author.id, give)
                desc += f"\n+{give} sobs · {earned + give}/{DAILY_REWARD_CAP} today"
            except Exception as ex:
                print(f"[Ignio][MapGame] reward failed: {ex}")
        elif capped:
            desc += "\n(daily sob cap reached — still a great guess!)"
        if round_no < total_rounds:
            desc += f"\n\nRound {round_no + 1} starting…"
        await self._show_transition(ctx, state, desc, GREEN)
        return {"winner": msg.author.display_name, "country": country["name"]}


def _today() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


async def setup(bot):  # pragma: no cover
    pass
