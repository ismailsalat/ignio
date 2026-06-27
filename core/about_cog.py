# core/about_cog.py
from __future__ import annotations

import time

import discord
from discord.ext import commands

from core import version as V

ACCENT = 0xF0B132


def _fmt_uptime(seconds: int) -> str:
    d, r = divmod(seconds, 86400)
    h, r = divmod(r, 3600)
    m, _ = divmod(r, 60)
    parts = []
    if d: parts.append(f"{d}d")
    if h: parts.append(f"{h}h")
    if m or not parts: parts.append(f"{m}m")
    return " ".join(parts)


class AboutCog(commands.Cog):
    def __init__(self, bot, settings):
        self.bot = bot
        self.settings = settings
        self.start_time = time.time()

    @commands.command(name="version", aliases=["ver"])
    async def version_cmd(self, ctx):
        e = discord.Embed(
            title="🔖 Ignio Version",
            description=f"**v{V.VERSION}** — {V.CODENAME}\nReleased {V.RELEASED}",
            color=ACCENT,
        )
        e.set_footer(text=f"{ctx.prefix}about for full patch notes")
        await ctx.reply(embed=e)

    @commands.command(name="about", aliases=["info", "botinfo"])
    async def about_cmd(self, ctx):
        latest = V.latest()
        uptime = _fmt_uptime(int(time.time() - self.start_time))

        e = discord.Embed(
            title="😭 About Ignio",
            description="A sob-tracking bot with a competitive snitch economy, shop, and profiles.",
            color=ACCENT,
        )
        e.add_field(name="Version", value=f"v{V.VERSION} — {V.CODENAME}", inline=True)
        e.add_field(name="Released", value=V.RELEASED, inline=True)
        e.add_field(name="Uptime", value=uptime, inline=True)
        e.add_field(name="Servers", value=str(len(self.bot.guilds)), inline=True)
        try:
            ping = round(self.bot.latency * 1000)
            ping_txt = f"{ping} ms" if ping == ping else "—"
        except (ValueError, TypeError):
            ping_txt = "—"
        e.add_field(name="Ping", value=ping_txt, inline=True)
        e.add_field(name="\u200b", value="\u200b", inline=True)

        notes = "\n".join(f"• {n}" for n in latest.get("notes", [])[:10])
        e.add_field(name=f"🆕 Latest update — v{latest['version']} ({latest['date']})",
                    value=notes or "—", inline=False)
        e.set_footer(text=f"{ctx.prefix}version for the short version · {ctx.prefix}help for commands")
        await ctx.reply(embed=e)
