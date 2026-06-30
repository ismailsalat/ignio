# core/games/sobship_cog.py
"""
!sobship @user — a fun love-meter (no sobs involved). Renders an animated GIF of
a heart filling to a deterministic compatibility score for the pair.

Pure fun: it never touches anyone's balance, inventory, or stats.
"""
from __future__ import annotations

import discord
from discord.ext import commands

from core.games.sobship_render import make_sobship_gif, ship_score

ACCENT = 0xEB546E


class SobShipCog(commands.Cog):
    def __init__(self, bot, settings):
        self.bot = bot
        self.settings = settings

    @commands.command(name="sobship", aliases=["ship", "lovemeter", "match"])
    @commands.guild_only()
    @commands.cooldown(1, 5, commands.BucketType.user)
    async def sobship(self, ctx: commands.Context, a: discord.Member = None,
                      b: discord.Member = None):
        """Measure the ~love~ between two people. `!sobship @user` or
        `!sobship @userA @userB`."""
        # resolve the pair
        if a is None:
            await ctx.reply(embed=discord.Embed(
                title="Sob-Ship 💘", color=ACCENT,
                description=("Measure the love between two people!\n"
                             "`!sobship @user` — you and them\n"
                             "`!sobship @userA @userB` — pair two others\n\n"
                             "Just for fun — no sobs are won or lost.")))
            return
        if b is None:
            # ship the author with the mentioned person
            user_a, user_b = ctx.author, a
        else:
            user_a, user_b = a, b

        if user_a.id == user_b.id:
            await ctx.reply(embed=discord.Embed(
                description="You can't ship someone with themselves! Pick two different people.",
                color=ACCENT))
            return

        async with ctx.typing():
            try:
                buf, score = make_sobship_gif(
                    user_a.display_name, user_b.display_name, user_a.id, user_b.id)
            except Exception as e:
                print(f"[Ignio][SobShip] render failed: {e}")
                score = ship_score(user_a.id, user_b.id)
                await ctx.reply(f"💘 **{user_a.display_name}** × **{user_b.display_name}** — **{score}%**")
                return

        file = discord.File(buf, filename="sobship.gif")
        await ctx.reply(file=file)


async def setup(bot):  # pragma: no cover
    pass
