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

        # Atomically decide + record the claim so two concurrent !daily can't
        # both pay. We compute the new streak/reward, then conditionally write
        # the claim row ONLY if last_claim is still what we read (compare-and-set
        # via a WHERE clause). If the conditional write affects 0 rows, someone
        # else claimed first and we report cooldown instead of paying again.
        from core import ledger
        db = await self.repo._db()
        async with db.key_lock("daily", gid, uid):
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

            if last and elapsed <= GRACE:
                streak += 1
            else:
                streak = 1

            reward = min(BASE + (streak - 1) * STREAK_STEP, CAP)

            # compare-and-set the claim row; 0 rows => lost the race, bail.
            async with db.transaction() as conn:
                if last:
                    cur = await conn.execute(
                        "UPDATE daily_claims SET last_claim=?, streak=?, total_claimed=total_claimed+? "
                        "WHERE guild_id=? AND user_id=? AND last_claim=?",
                        (now, streak, reward, gid, uid, last),
                    )
                    claimed = cur.rowcount > 0
                else:
                    cur = await conn.execute(
                        "INSERT OR IGNORE INTO daily_claims (guild_id, user_id, last_claim, streak, total_claimed) "
                        "VALUES (?,?,?,?,?)",
                        (gid, uid, now, streak, reward),
                    )
                    claimed = cur.rowcount > 0
            if not claimed:
                # someone else claimed in the tiny window — treat as cooldown
                _l, _s, _t = await self._get_claim(gid, uid)
                remaining = max(1, COOLDOWN - (now - _l))
                h, m = divmod(remaining // 60, 60)
                await ctx.reply(embed=discord.Embed(
                    title="⏳ Already claimed",
                    description=f"Come back in **{h}h {m}m** for your next daily.",
                    color=ACCENT))
                return

            # claim recorded — now mint the reward + ledger row (intentional mint)
            new_total = await self.repo.adjust_received(
                gid, uid, reward, event_type=ledger.EVT_DAILY, actor_id=uid,
                metadata={"streak": streak})

        nxt = min(BASE + streak * STREAK_STEP, CAP)
        maxed = reward >= CAP

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
