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
        # snapshot every 30 min (graph), and recompute prices once per UTC day
        from datetime import datetime, timezone
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        for guild in list(self.bot.guilds):
            try:
                await self.eco.record_snapshot(guild.id)
                # daily rebalance: only if we haven't already today
                last = await self.eco.repo.get_guild_setting(guild.id, "economy:last_rebalance")
                if last != today:
                    await self.eco.recompute_reference(guild.id)
                    await self.eco.repo.set_guild_setting(guild.id, "economy:last_rebalance", today)
            except Exception as e:
                print(f"[Ignio][Economy] snapshot/rebalance failed for {guild.id}: {e}")

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

    @commands.command(name="rebalance", aliases=["resync"])
    @commands.guild_only()
    async def rebalance_cmd(self, ctx):
        if not _is_admin(ctx.author, self.settings):
            await ctx.reply(embed=self._err("Only admins can rebalance the shop."))
            return
        old_ref = await self.eco.reference_balance(ctx.guild.id)
        new_ref = await self.eco.recompute_reference(ctx.guild.id)
        prices = await self.eco.all_item_prices(ctx.guild.id)
        e = discord.Embed(title="✅ Shop rebalanced", color=ACCENT)
        e.description = (f"Reference balance: **{_fmt(old_ref)} → {_fmt(new_ref)}** sobs.\n"
                         f"Prices are now locked to the current economy.")
        e.add_field(name="A few new prices", value=(
            f"Basic Shield — {_fmt(prices['shield'])}\n"
            f"Tax Audit — {_fmt(prices['tax_audit'])}\n"
            f"King's Decree — {_fmt(prices['king'])}"
        ), inline=False)
        e.set_footer(text="Prices auto-rebalance daily too.")
        await ctx.reply(embed=e)

    @commands.group(name="treasury", aliases=["pot", "vault"], invoke_without_command=True)
    @commands.guild_only()
    async def treasury_cmd(self, ctx):
        if not _is_admin(ctx.author, self.settings):
            await ctx.reply(embed=self._err("Only admins can view the treasury.")); return
        gid = ctx.guild.id
        stats = await self.eco.treasury_stats(gid)

        def name_lookup(uid):
            m = ctx.guild.get_member(uid)
            if not m:
                return f"user {uid}"
            try:
                from core.profile.render import clean_name, renderable
                disp = clean_name(m.display_name)
                return disp if renderable(disp) else m.name
            except Exception:
                return m.display_name

        try:
            from core.profile.small_cards import treasury_card
            import io
            img = treasury_card(stats, name_lookup)
            buf = io.BytesIO(); img.save(buf, format="PNG"); buf.seek(0)
            await ctx.reply(file=discord.File(buf, filename="treasury.png"))
            return
        except Exception as e:
            print(f"[Ignio][Treasury] card failed, using embed: {e}")

        em = discord.Embed(title="Server Treasury", color=ACCENT)
        em.description = f"**{_fmt(stats['treasury'])} sobs** in the pot."
        em.add_field(name="Today", value=_fmt(stats["today"]), inline=True)
        em.add_field(name="This week", value=_fmt(stats["week"]), inline=True)
        em.add_field(name="All-time", value=_fmt(stats["alltime"]), inline=True)
        em.set_footer(text=f"{ctx.prefix}treasury give @user <amount> to pay out")
        await ctx.reply(embed=em)

    @treasury_cmd.command(name="give", aliases=["pay", "payout"])
    @commands.guild_only()
    async def treasury_give(self, ctx, member: discord.Member = None, amount: int = None):
        if not _is_admin(ctx.author, self.settings):
            await ctx.reply(embed=self._err("Only admins can pay out the treasury.")); return
        if member is None or amount is None or amount <= 0:
            await ctx.reply(embed=self._err(f"Usage: `{ctx.prefix}treasury give @user <amount>`.")); return
        gid = ctx.guild.id
        ok = await self.eco.spend_treasury(gid, amount)
        if not ok:
            pot = await self.eco.get_treasury(gid)
            await ctx.reply(embed=self._err(f"The treasury only has **{_fmt(pot)}** sobs.")); return
        new_bal = await self.eco.repo.adjust_received(gid, member.id, amount)
        e = discord.Embed(title="✅ Treasury payout", color=ACCENT)
        e.description = (f"Gave **{_fmt(amount)} sobs** to {member.mention} from the treasury.\n"
                        f"Their balance: **{_fmt(new_bal)}** · Pot left: **{_fmt(await self.eco.get_treasury(gid))}**")
        await ctx.reply(embed=e)

    @commands.command(name="tax")
    @commands.guild_only()
    async def tax_cmd(self, ctx, pct: str | None = None):
        gid = ctx.guild.id
        if pct is None:
            cur = await self.eco.get_tax_pct(gid)
            suggested = await self.eco.suggest_tax(gid)
            pot = await self.eco.get_treasury(gid)
            e = discord.Embed(title="Shop tax", color=ACCENT)
            e.description = (f"**{cur}%** is added on top of built-in items.\n"
                             f"That tax goes to the **server treasury** (now **{_fmt(pot)}** sobs).\n"
                             f"Auto-suggested for this economy: **{suggested}%**.")
            e.set_footer(text=f"Admins: {ctx.prefix}tax <percent> · {ctx.prefix}tax auto · {ctx.prefix}treasury")
            await ctx.reply(embed=e)
            return
        if not _is_admin(ctx.author, self.settings):
            await ctx.reply(embed=self._err("Only admins can set the tax.")); return
        if pct.lower() == "auto":
            await self.eco.set_tax_pct(gid, None)
            await ctx.reply(embed=discord.Embed(title="✅ Tax set to AUTO",
                description="It now adjusts to the server economy automatically.", color=ACCENT))
            return
        try:
            v = int(pct)
        except ValueError:
            await ctx.reply(embed=self._err("Give a number (e.g. `15`) or `auto`.")); return
        await self.eco.set_tax_pct(gid, v)
        await ctx.reply(embed=discord.Embed(
            title="✅ Tax updated", description=f"Built-in purchases now add **{max(0,min(50,v))}%** on top (to the treasury).",
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
