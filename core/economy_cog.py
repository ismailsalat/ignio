# core/economy_cog.py
from __future__ import annotations

import discord
from discord.ext import commands, tasks

from core.economy import Economy

ACCENT = 0xF0B132


def _is_admin(member, settings) -> bool:
    owner_ids = set(getattr(settings, "owner_ids", ()) or ())
    if member.id in owner_ids:
        return True
    perms = getattr(member, "guild_permissions", None)
    return bool(perms and (perms.administrator or perms.manage_guild))


def _fmt(n) -> str:
    return f"{int(n):,}"


class EconomyCog(commands.Cog):
    def __init__(self, bot, settings, sob_repo):
        self.bot = bot
        self.settings = settings
        self.eco = Economy(sob_repo)
        self._snapshot_loop.start()

    def cog_unload(self):
        self._snapshot_loop.cancel()

    @tasks.loop(minutes=30)
    async def _snapshot_loop(self):
        # snapshot every 30 min so the inflation graph fills in within hours
        for guild in list(self.bot.guilds):
            try:
                await self.eco.record_snapshot(guild.id)
            except Exception as e:
                print(f"[Ignio][Economy] snapshot failed for {guild.id}: {e}")

    @_snapshot_loop.before_loop
    async def _before(self):
        try:
            await self.bot.wait_until_ready()
        except Exception:
            pass

    def _err(self, d): return discord.Embed(title="⚠️ Error", description=d, color=ACCENT)

    # ---- rate -------------------------------------------------------------

    @commands.group(name="rate", invoke_without_command=True)
    @commands.guild_only()
    async def rate_group(self, ctx):
        rate = await self.eco.get_rate(ctx.guild.id)
        e = discord.Embed(title="💱 Exchange Rate", color=ACCENT)
        e.description = f"**{_fmt(rate)} sobs = $1** on this server."
        e.add_field(name="Examples",
                    value=f"$5 = {_fmt(rate*5)} sobs\n$10 = {_fmt(rate*10)} sobs", inline=True)
        e.set_footer(text=f"{ctx.prefix}value <sobs> · {ctx.prefix}worth <$> · admins: {ctx.prefix}rate set <sobs>")
        await ctx.reply(embed=e)

    @rate_group.command(name="set")
    @commands.guild_only()
    async def rate_set(self, ctx, sobs_per_dollar: int | None = None):
        if not _is_admin(ctx.author, self.settings):
            await ctx.reply(embed=self._err("Only admins can set the rate."))
            return
        if not sobs_per_dollar or sobs_per_dollar <= 0:
            await ctx.reply(embed=self._err(f"Usage: `{ctx.prefix}rate set <sobs per $1>` (e.g. `{ctx.prefix}rate set 50000`)."))
            return
        await self.eco.set_rate(ctx.guild.id, sobs_per_dollar)
        e = discord.Embed(title="✅ Rate updated",
                          description=f"**{_fmt(sobs_per_dollar)} sobs = $1** on this server.",
                          color=ACCENT)
        await ctx.reply(embed=e)

    @commands.command(name="tax")
    @commands.guild_only()
    async def tax_cmd(self, ctx, pct: int | None = None):
        if pct is None:
            cur = await self.eco.get_tax_pct(ctx.guild.id)
            burned = await self.eco.get_burned(ctx.guild.id)
            e = discord.Embed(title="Shop tax", color=ACCENT)
            e.description = (f"**{cur}%** of every built-in purchase is burned.\n"
                             f"Total burned so far: **{_fmt(burned)} sobs**.")
            e.set_footer(text=f"Admins: {ctx.prefix}tax <percent>")
            await ctx.reply(embed=e)
            return
        if not _is_admin(ctx.author, self.settings):
            await ctx.reply(embed=self._err("Only admins can set the tax.")); return
        await self.eco.set_tax_pct(ctx.guild.id, pct)
        await ctx.reply(embed=discord.Embed(
            title="✅ Tax updated", description=f"Built-in purchases now burn **{max(0,min(90,pct))}%**.",
            color=ACCENT))

    @commands.command(name="multiplier", aliases=["mult", "sobmult"])
    @commands.guild_only()
    async def mult_cmd(self, ctx, value: str | None = None):
        if value is None:
            cur = await self.eco.get_sob_multiplier(ctx.guild.id)
            suggested = await self.eco.suggest_multiplier(ctx.guild.id)
            e = discord.Embed(title="Sob multiplier", color=ACCENT)
            e.description = (f"Each reaction is worth **{cur:g}×** sobs.\n"
                             f"Auto-suggested for this economy: **{suggested:g}×**.")
            e.set_footer(text=f"Admins: {ctx.prefix}mult <number>  ·  {ctx.prefix}mult auto")
            await ctx.reply(embed=e)
            return
        if not _is_admin(ctx.author, self.settings):
            await ctx.reply(embed=self._err("Only admins can set the multiplier.")); return
        if value.lower() == "auto":
            await self.eco.set_sob_multiplier(ctx.guild.id, None)
            await ctx.reply(embed=discord.Embed(title="✅ Multiplier set to AUTO",
                description="It now adjusts to the server economy automatically.", color=ACCENT))
            return
        try:
            v = float(value)
        except ValueError:
            await ctx.reply(embed=self._err("Give a number (e.g. `2`) or `auto`.")); return
        await self.eco.set_sob_multiplier(ctx.guild.id, v)
        await ctx.reply(embed=discord.Embed(title="✅ Multiplier updated",
            description=f"Each reaction is now worth **{max(0.1,v):g}×** sobs.", color=ACCENT))

    @commands.command(name="value")
    @commands.guild_only()
    async def value_cmd(self, ctx, sobs: int | None = None):
        if sobs is None:
            await ctx.reply(embed=self._err(f"Usage: `{ctx.prefix}value <sobs>` — e.g. `{ctx.prefix}value 250000`."))
            return
        usd = await self.eco.sobs_to_usd(ctx.guild.id, sobs)
        await ctx.reply(f"💱 **{_fmt(sobs)} sobs ≈ ${usd:,.2f}**")

    @commands.command(name="worth")
    @commands.guild_only()
    async def worth_cmd(self, ctx, dollars: float | None = None):
        if dollars is None:
            await ctx.reply(embed=self._err(f"Usage: `{ctx.prefix}worth <$>` — e.g. `{ctx.prefix}worth 10`."))
            return
        sobs = await self.eco.usd_to_sobs(ctx.guild.id, dollars)
        await ctx.reply(f"💱 **${dollars:,.2f} ≈ {_fmt(sobs)} sobs**")

    # ---- economy health ---------------------------------------------------

    @commands.command(name="economy", aliases=["eco"])
    @commands.guild_only()
    async def economy_cmd(self, ctx):
        gid = ctx.guild.id
        try:
            await self.eco.record_snapshot(gid)
        except Exception:
            pass

        rate = await self.eco.get_rate(gid)
        rec = await self.eco.recommend_rate(gid)
        sig = await self.eco.inflation_signal(gid)
        mult = await self.eco.get_sob_multiplier(gid)
        burned = await self.eco.get_burned(gid)

        advice = None
        if sig["status"] == "red":
            advice = "Supply is growing fast (often event payouts). Raise the tax or use event tiers."
        elif sig["status"] == "new":
            advice = "New server — using a starter rate. It'll auto-tune as your economy grows."

        # Try the image card first; fall back to a text embed if it fails.
        try:
            from core.profile.eco_render import make_economy_card
            import io
            card = make_economy_card({
                "guild_name": ctx.guild.name,
                "total": rec["total"], "players": rec["players"],
                "current_rate": rate, "recommended_rate": rec["recommended"],
                "multiplier": mult, "burned": burned,
                "status": sig["status"], "pct": sig["pct"], "points": sig["points"],
                "advice": advice,
            })
            buf = io.BytesIO(); card.save(buf, format="PNG"); buf.seek(0)
            await ctx.reply(file=discord.File(buf, filename="economy.png"))
            return
        except Exception as e:
            print(f"[Ignio][Economy] card failed, using embed: {e}")

        # text fallback
        status_word = {"green": "🟢 Stable", "yellow": "🟡 Watch",
                       "red": "🔴 Inflating", "new": "⚪ New server"}[sig["status"]]
        e = discord.Embed(title="📊 Server Economy", color=ACCENT)
        e.add_field(name="Total sobs", value=_fmt(rec["total"]), inline=True)
        e.add_field(name="Players", value=_fmt(rec["players"]), inline=True)
        e.add_field(name="Current rate", value=f"{_fmt(rate)} / $1", inline=True)
        e.add_field(name="Suggested rate", value=f"{_fmt(rec['recommended'])} / $1", inline=True)
        e.add_field(name="Inflation", value=status_word
                    + (f" ({sig['pct']:+.0f}%)" if sig["status"] not in ("new",) else ""), inline=True)
        e.add_field(name="\u200b", value="\u200b", inline=True)
        if advice:
            e.add_field(name="Advice", value=advice, inline=False)
        await ctx.reply(embed=e)
