# core/games/redgreen_cog.py
"""
!flag — Red Flag / Green Flag voting game.

The bot drops a spicy/funny dating scenario (optionally aimed at a mentioned
person) and everyone votes with buttons. Live tally, no sobs — it's pure chat
chaos. Each user's vote counts once (changing it moves the count, never double).
"""
from __future__ import annotations

import secrets

import discord
from discord.ext import commands

from core.games.redgreen_data import GENERIC, TARGETED

RED = 0xE0524F
GREEN = 0x4FB477
VOTE_SECONDS = 45


class FlagVoteView(discord.ui.View):
    def __init__(self, scenario: str, on_close=None):
        super().__init__(timeout=VOTE_SECONDS)
        self.scenario = scenario
        self.votes: dict[int, str] = {}     # user_id -> "red" | "green"
        self.message: discord.Message | None = None
        self._on_close = on_close

    def _counts(self):
        red = sum(1 for v in self.votes.values() if v == "red")
        green = sum(1 for v in self.votes.values() if v == "green")
        return red, green

    def _embed(self, closed: bool = False) -> discord.Embed:
        red, green = self._counts()
        total = red + green
        title = "🚩 Red Flag or ✅ Green Flag?"
        e = discord.Embed(title=title, description=f"## {self.scenario}", color=0xF0B132)
        if total == 0:
            bar = "*No votes yet — be the first!*"
        else:
            rp = round(red / total * 100)
            gp = 100 - rp
            rb = "🟥" * max(0, round(rp / 10))
            gb = "🟩" * max(0, round(gp / 10))
            bar = f"🚩 **{red}** ({rp}%)\n{rb or '▫️'}\n\n✅ **{green}** ({gp}%)\n{gb or '▫️'}"
        e.add_field(name="\u200b", value=bar, inline=False)
        if closed:
            if total == 0:
                e.set_footer(text="Voting closed — nobody voted. Cowards.")
            elif red > green:
                e.set_footer(text="🚩 The people have spoken: RED FLAG. Run.")
            elif green > red:
                e.set_footer(text="✅ The people have spoken: GREEN FLAG. Lock it in.")
            else:
                e.set_footer(text="It's a TIE — chaotic, just like this relationship.")
        else:
            e.set_footer(text=f"Vote below • {VOTE_SECONDS}s")
        return e

    async def _refresh(self, interaction: discord.Interaction):
        await interaction.response.edit_message(embed=self._embed(), view=self)

    @discord.ui.button(label="Red Flag", emoji="🚩", style=discord.ButtonStyle.danger)
    async def red(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.votes[interaction.user.id] = "red"
        await self._refresh(interaction)

    @discord.ui.button(label="Green Flag", emoji="✅", style=discord.ButtonStyle.success)
    async def green(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.votes[interaction.user.id] = "green"
        await self._refresh(interaction)

    async def on_timeout(self):
        for child in self.children:
            child.disabled = True
        if self.message:
            try:
                await self.message.edit(embed=self._embed(closed=True), view=self)
            except Exception:
                pass
        if self._on_close:
            try:
                self._on_close()
            except Exception:
                pass


class RedGreenCog(commands.Cog):
    def __init__(self, bot, settings):
        self.bot = bot
        self.settings = settings
        self._active: set[int] = set()    # channels with a live vote

    async def _enabled(self, gid: int) -> bool:
        # reuse a simple per-guild toggle stored on the settings service if present
        return True

    @commands.command(name="flag", aliases=["redflag", "greenflag", "rgf"])
    @commands.guild_only()
    @commands.cooldown(1, 10, commands.BucketType.channel)
    async def flag(self, ctx: commands.Context, member: discord.Member = None):
        """Red Flag / Green Flag voting game. `!flag` or `!flag @user` to aim it."""
        if ctx.channel.id in self._active:
            await ctx.reply(embed=discord.Embed(
                description="There's already a flag vote running here — let that one finish!",
                color=0xF0B132))
            return

        if member is not None and not member.bot:
            template = secrets.choice(TARGETED)
            scenario = template.format(name=member.display_name)
        else:
            scenario = secrets.choice(GENERIC)

        view = FlagVoteView(scenario, on_close=lambda: self._active.discard(ctx.channel.id))
        self._active.add(ctx.channel.id)
        msg = await ctx.reply(embed=view._embed(), view=view)
        view.message = msg


async def setup(bot):  # pragma: no cover
    pass
