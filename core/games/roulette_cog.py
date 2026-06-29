# core/games/roulette_cog.py
"""Russian Roulette PvP — the first game on the reusable Games engine.

!roulette @user <amount>  — challenge someone for a wager.
Challenged player gets Accept / Decline buttons. On accept, a short dramatic
embed 'spin' plays, then the loser (50/50) pays the winner. 5% house tax to the
treasury. No sobs minted.
"""
from __future__ import annotations

import asyncio
import random

import discord
from discord.ext import commands

ACCENT = 0xF0B132
RED = 0xE0524F


def _fmt(n: int) -> str:
    return f"{n:,}"


class RouletteView(discord.ui.View):
    def __init__(self, cog, ctx, challenger, opponent, wager):
        super().__init__(timeout=60)
        self.cog = cog
        self.ctx = ctx
        self.challenger = challenger
        self.opponent = opponent
        self.wager = wager
        self.message = None
        self.resolved = False

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        # only the challenged player may press the buttons
        if interaction.user.id != self.opponent.id:
            await interaction.response.send_message(
                "This challenge isn't yours to answer.", ephemeral=True)
            return False
        return True

    async def on_timeout(self):
        if self.resolved:
            return
        self.resolved = True
        gid = self.ctx.guild.id
        self.cog.engine.clear_busy(gid, self.challenger.id, self.opponent.id)
        try:
            e = discord.Embed(title="🔫 Challenge expired",
                              description=f"{self.opponent.mention} didn't answer in time. Wager refunded.",
                              color=RED)
            if self.message:
                await self.message.edit(embed=e, view=None)
        except Exception:
            pass

    @discord.ui.button(label="Accept", style=discord.ButtonStyle.success)
    async def accept(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.resolved:
            return
        self.resolved = True
        for c in self.children:
            c.disabled = True
        await interaction.response.edit_message(view=self)
        await self.cog._play(interaction, self)

    @discord.ui.button(label="Decline", style=discord.ButtonStyle.danger)
    async def decline(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.resolved:
            return
        self.resolved = True
        gid = self.ctx.guild.id
        self.cog.engine.clear_busy(gid, self.challenger.id, self.opponent.id)
        e = discord.Embed(title="🔫 Challenge declined",
                          description=f"{self.opponent.mention} backed out. No sobs lost.",
                          color=RED)
        await interaction.response.edit_message(embed=e, view=None)


class RouletteCog(commands.Cog):
    def __init__(self, bot, settings, sob_repo, engine):
        self.bot = bot
        self.settings = settings
        self.sob_repo = sob_repo
        self.engine = engine

    @commands.command(name="roulette", aliases=["rr"])
    @commands.guild_only()
    async def roulette(self, ctx, *, args: str = None):
        gid = ctx.guild.id
        chal = ctx.author

        # Forgiving parse: a mention + a number in any order.
        member = ctx.message.mentions[0] if ctx.message.mentions else None
        amount = None
        if args:
            for tok in args.replace(",", "").split():
                if tok.isdigit():
                    amount = int(tok)
                    break

        if member is None or amount is None:
            await ctx.reply(embed=self._err(
                f"Usage: `{ctx.prefix}roulette @user <amount>`\n"
                f"Example: `{ctx.prefix}roulette @friend 100`"))
            return
        if amount <= 0:
            await ctx.reply(embed=self._err("Wager must be a positive number of sobs."))
            return
        if member.id == chal.id:
            await ctx.reply(embed=self._err("You can't challenge yourself."))
            return
        if member.bot:
            await ctx.reply(embed=self._err("You can't challenge a bot."))
            return

        cd = self.engine.on_cooldown(gid, chal.id)
        if cd > 0:
            await ctx.reply(embed=self._err(f"Slow down — try again in {cd}s."))
            return
        if self.engine.is_busy(gid, chal.id):
            await ctx.reply(embed=self._err("You're already in a match."))
            return
        if self.engine.is_busy(gid, member.id):
            await ctx.reply(embed=self._err(f"{member.mention} is already in a match."))
            return
        if not await self.engine.can_afford(gid, chal.id, amount):
            await ctx.reply(embed=self._err(f"You don't have **{_fmt(amount)}** sobs to wager."))
            return
        if not await self.engine.can_afford(gid, member.id, amount):
            await ctx.reply(embed=self._err(f"{member.mention} doesn't have **{_fmt(amount)}** sobs."))
            return

        # lock both players + set challenger cooldown
        self.engine.mark_busy(gid, chal.id, member.id)
        self.engine.set_cooldown(gid, chal.id)

        e = discord.Embed(
            title="🔫 Russian Roulette",
            description=(f"{chal.mention} challenges {member.mention} for **{_fmt(amount)}** sobs.\n\n"
                         f"{member.mention}, do you accept? One of you walks away richer."),
            color=ACCENT,
        )
        e.set_footer(text="Decline within 60s or the challenge expires.")
        view = RouletteView(self, ctx, chal, member, amount)
        view.message = await ctx.reply(embed=e, view=view)

    async def _play(self, interaction, view):
        """Run the dramatic spin then settle."""
        gid = view.ctx.guild.id
        chal, opp, wager = view.challenger, view.opponent, view.wager
        msg = view.message

        async def show(desc, color=ACCENT, title="🔫 Russian Roulette"):
            try:
                e = discord.Embed(title=title, description=desc, color=color)
                await msg.edit(embed=e, view=None)
            except Exception:
                pass

        # re-validate both can still pay (balances may have changed)
        if not await self.engine.can_afford(gid, chal.id, wager) or \
           not await self.engine.can_afford(gid, opp.id, wager):
            self.engine.clear_busy(gid, chal.id, opp.id)
            await show(f"One player can no longer cover **{_fmt(wager)}** sobs. Match cancelled.", RED)
            return

        await show(f"{opp.mention} **accepts!**\nBoth wager **{_fmt(wager)}** sobs. Loading one round into six chambers…")
        await asyncio.sleep(1.4)
        await show("Spinning the cylinder…  🌀")
        await asyncio.sleep(1.4)

        # Visible, provably-fair mechanic: 6 chambers, one bullet, players alternate
        # pulling. Whoever pulls the loaded chamber loses. The bullet position and
        # turn order are random and shown, so there's nothing hidden.
        bullet = random.randint(1, 6)        # which chamber the round is in
        first = random.choice([chal, opp])   # who pulls first (random, fair)
        second = opp if first is chal else chal
        order = []
        for i in range(1, 7):
            order.append(first if i % 2 == 1 else second)
        loser_member = order[bullet - 1]

        await show("Trigger pulled…  😬")
        await asyncio.sleep(1.2)

        # reveal chamber by chamber up to the bullet (dramatic, and shows it's real)
        track = ""
        for i in range(1, bullet + 1):
            who = order[i - 1]
            if i < bullet:
                track += f"Chamber {i} — *click* ({who.display_name} safe)\n"
            else:
                track += f"Chamber {i} — **BANG** 💥 ({who.display_name})\n"
            await show(f"🔫 Spinning through the chambers…\n\n{track}")
            await asyncio.sleep(0.9)

        winner = chal.id if loser_member.id == opp.id else opp.id
        result = await self.engine.settle(gid, "roulette", chal.id, opp.id, winner, wager)
        self.engine.clear_busy(gid, chal.id, opp.id)

        win_member = chal if winner == chal.id else opp
        lose_member = opp if winner == chal.id else chal
        e = discord.Embed(
            title="🔫 *click… BANG!*",
            description=(f"The round was in **chamber {bullet}** of 6.\n\n"
                         f"💀 {lose_member.mention} takes the hit — loses **{_fmt(result['paid'])}** sobs.\n"
                         f"🏆 {win_member.mention} walks away with **{_fmt(result['net'])}** sobs!"),
            color=ACCENT,
        )
        if result["tax"] > 0:
            e.set_footer(text=f"House took {_fmt(result['tax'])} sobs to the treasury.")
        await msg.edit(embed=e, view=None)

    @commands.command(name="roulettestats", aliases=["rrstats"])
    @commands.guild_only()
    async def roulette_stats(self, ctx):
        """Show roulette match stats — proves the odds are fair over time."""
        gid = ctx.guild.id
        db = await self.sob_repo._db()
        total = await db.fetchone(
            "SELECT COUNT(*) AS n, COALESCE(SUM(wager),0) AS vol, COALESCE(SUM(tax),0) AS tax "
            "FROM game_events WHERE guild_id=? AND game='roulette'", (gid,))
        n = int(total["n"])
        if n == 0:
            await ctx.reply(embed=discord.Embed(
                title="🎲 Roulette stats",
                description="No matches played yet. Be the first — `!roulette @user <amount>`.",
                color=ACCENT))
            return
        # how often the challenger won (should trend to ~50%)
        chal_wins = await db.fetchone(
            "SELECT COUNT(*) AS c FROM game_events WHERE guild_id=? AND game='roulette' AND winner=challenger",
            (gid,))
        cw = int(chal_wins["c"])
        e = discord.Embed(title="🎲 Roulette stats", color=ACCENT)
        e.description = (f"**{n}** matches played · **{_fmt(int(total['vol']))}** sobs wagered\n"
                         f"Challenger won **{cw}** ({100*cw/n:.0f}%) · opponent won **{n-cw}** ({100*(n-cw)/n:.0f}%)\n"
                         f"The odds are a true 50/50 coin flip — it evens out over time.")
        e.set_footer(text=f"{_fmt(int(total['tax']))} sobs collected to the treasury")
        await ctx.reply(embed=e)

    def _err(self, desc):
        return discord.Embed(title="⚠️ Error", description=desc, color=ACCENT)


async def setup_roulette(bot, settings, sob_repo, engine):
    await bot.add_cog(RouletteCog(bot, settings, sob_repo, engine))
