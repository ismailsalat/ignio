# core/daily_cog.py
"""!daily — the faucet. Claim once/24h, streak bonus, optional catch-up."""
from __future__ import annotations

import time
import discord
from discord.ext import commands

ACCENT = 0xF0B132

# Tunable defaults (per-server overridable via guild_settings later).
BASE = 30           # base sobs per claim
STREAK_STEP = 10    # +per consecutive day
CAP = 80            # max per claim
COOLDOWN = 86400    # 24h
GRACE = 172800      # 48h: claim within this keeps the streak; beyond resets


class DailyCog(commands.Cog):
    def __init__(self, bot, settings, sob_repo):
        self.bot = bot
        self.settings = settings
        self.repo = sob_repo

    async def _get_claim(self, gid, uid):
        db = await self.repo._db()
        row = await db.fetchone(
            "SELECT last_claim, streak, total_claimed FROM daily_claims WHERE guild_id=? AND user_id=?",
            (gid, uid),
        )
        if row:
            return row["last_claim"], row["streak"], row["total_claimed"]
        return 0, 0, 0

    async def _save_claim(self, gid, uid, last_claim, streak, total):
        db = await self.repo._db()
        await db.execute(
            "INSERT INTO daily_claims (guild_id, user_id, last_claim, streak, total_claimed) "
            "VALUES (?,?,?,?,?) "
            "ON CONFLICT(guild_id, user_id) DO UPDATE SET last_claim=excluded.last_claim, "
            "streak=excluded.streak, total_claimed=excluded.total_claimed",
            (gid, uid, last_claim, streak, total),
        )
        await db.commit()

    @commands.command(name="daily", aliases=["claim"])
    @commands.guild_only()
    async def daily_cmd(self, ctx):
        gid, uid, now = ctx.guild.id, ctx.author.id, int(time.time())
        last, streak, total = await self._get_claim(gid, uid)

        elapsed = now - last
        if last and elapsed < COOLDOWN:
            remaining = COOLDOWN - elapsed
            h, m = divmod(remaining // 60, 60)
            e = discord.Embed(
                title="⏳ Already claimed",
                description=f"Come back in **{h}h {m}m** for your next daily.",
                color=ACCENT,
            )
            e.set_footer(text=f"Current streak: {streak} day(s)")
            await ctx.reply(embed=e)
            return

        # streak: continued if within grace window, else reset to 1
        if last and elapsed <= GRACE:
            streak += 1
        else:
            streak = 1

        reward = min(BASE + (streak - 1) * STREAK_STEP, CAP)
        new_total = await self.repo.adjust_received(gid, uid, reward)
        await self._save_claim(gid, uid, now, streak, total + reward)

        nxt = min(BASE + streak * STREAK_STEP, CAP)
        maxed = reward >= CAP

        # Try the picture card first; fall back to an embed.
        try:
            from core.profile.small_cards import daily_card
            import io
            img = daily_card(reward, streak, new_total, nxt, maxed)
            buf = io.BytesIO(); img.save(buf, format="PNG"); buf.seek(0)
            await ctx.reply(file=discord.File(buf, filename="daily.png"))
            return
        except Exception as e:
            print(f"[Ignio][Daily] card failed, using embed: {e}")

        e = discord.Embed(title="🪙 Daily claimed!", color=ACCENT)
        e.description = f"You got **{reward} sobs**."
        e.add_field(name="Streak", value=f"🔥 {streak} day(s)", inline=True)
        e.add_field(name="Balance", value=f"{new_total:,} sobs", inline=True)
        if maxed:
            e.set_footer(text="You're at the max daily reward — keep the streak alive!")
        else:
            e.set_footer(text=f"Come back tomorrow for {nxt} sobs (keep the streak!)")
        await ctx.reply(embed=e)
