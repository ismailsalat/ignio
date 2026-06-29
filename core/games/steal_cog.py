# core/games/steal_cog.py
"""
!steal @user [lockpick] — a high-risk PvP gamble (lives under Games).

Low odds, real cost on failure, hard cooldowns + daily victim caps, tiny shop
items. Never a farming strategy — designed to stay break-even-ish before items.
All state changes are atomic (see core/steal.py).
"""
from __future__ import annotations

import discord
from discord.ext import commands

from core.steal import Steal, StealError

ACCENT = 0xF0B132
RED = 0xE0524F
GREEN = 0x4FB477


def _fmt(n: int) -> str:
    return f"{n:,}"


def _dur(secs: int) -> str:
    secs = max(0, int(secs)); h, r = divmod(secs, 3600); m, s = divmod(r, 60)
    if h: return f"{h}h {m}m"
    if m: return f"{m}m"
    return f"{s}s"


class StealCog(commands.Cog):
    def __init__(self, bot, settings, sob_repo, economy, shop_repo=None, protection=None):
        self.bot = bot
        self.settings = settings
        self.steal = Steal(economy, sob_repo, shop_repo, protection)

    @commands.group(name="steal", invoke_without_command=True)
    @commands.guild_only()
    async def steal_cmd(self, ctx: commands.Context, target: discord.Member = None, item: str = None):
        """Risk a steal against someone. `!steal @user` or `!steal @user lockpick`."""
        if target is None:
            await ctx.reply(embed=discord.Embed(
                title="🦝 Steal", color=ACCENT,
                description=("Risk a gamble to steal sobs.\n"
                             "`!steal @user` — 18% base chance.\n"
                             "`!steal @user lockpick` — spend a Lockpick for +4%.\n"
                             "`!steal stats` — your steal record.\n\n"
                             "Win: take a slice of their sobs. Lose: pay a caught fee. "
                             "Low odds, capped, cooldowns — it's a gamble, not a salary.")))
            return

        use_lockpick = bool(item and item.lower() in ("lockpick", "pick", "lp"))
        gid = ctx.guild.id

        if getattr(target, "bot", False):
            await ctx.reply(embed=discord.Embed(description="You can't steal from a bot.", color=RED))
            return

        try:
            res = await self.steal.attempt(gid, ctx.author.id, target.id, use_lockpick=use_lockpick)
        except StealError as e:
            await ctx.reply(embed=discord.Embed(description=f"🚫 {e.message}", color=RED))
            return
        except Exception as e:
            print(f"[Ignio][Steal] attempt failed: {e}")
            await ctx.reply(embed=discord.Embed(description="Something went wrong — no sobs moved.", color=RED))
            return

        if res["success"]:
            e = discord.Embed(title="🦝 Steal — success!", color=GREEN)
            e.description = (f"You stole **{_fmt(res['gain'])} sobs** from {target.mention}! "
                             f"(roll {res['roll']} < {res['chance']}%)")
            if res["tax"]:
                e.set_footer(text=f"{_fmt(res['tax'])} sobs went to the treasury · {res['attempts_left']} attempts left today")
        else:
            e = discord.Embed(title="🦝 Steal — caught!", color=RED)
            e.description = (f"{target.mention} caught you. You paid a fee of **{_fmt(res['fee'])} sobs**. "
                             f"(roll {res['roll']} ≥ {res['chance']}%)")
            e.set_footer(text=f"{_fmt(res['tax'])} to treasury · {_fmt(res['burned'])} burned · {res['attempts_left']} attempts left today")
        await ctx.reply(embed=e)

    @steal_cmd.command(name="stats")
    @commands.guild_only()
    async def steal_stats(self, ctx: commands.Context, member: discord.Member = None):
        """Your steal record."""
        user = member or ctx.author
        s = await self.steal.stats(ctx.guild.id, user.id)
        e = discord.Embed(title=f"🦝 Steal stats — {user.display_name}", color=ACCENT)
        e.add_field(name="As hunter",
                    value=(f"Net profit: **{_fmt(s['profit'])}**\n"
                           f"Stolen: {_fmt(s['stolen'])} · Fees paid: {_fmt(s['fees_paid'])}\n"
                           f"Attempts today: {s['attempts_today']}/{s['attempts_cap']}"),
                    inline=False)
        cd = s["cooldown_left"]
        e.add_field(name="Cooldown", value=("ready now" if cd <= 0 else _dur(cd)), inline=True)
        e.add_field(name="As target",
                    value=(f"Lost to steals: {_fmt(s['lost'])}\n"
                           f"Today: {_fmt(s['lost_today'])} / {_fmt(s['daily_cap'])} cap\n"
                           + (f"🛡️ immune for {_dur(s['immunity_left'])}" if s['immunity_left'] > 0 else "not immune")),
                    inline=False)
        await ctx.reply(embed=e)


async def setup(bot):  # pragma: no cover - not used (manual cog add in bot.py)
    pass
