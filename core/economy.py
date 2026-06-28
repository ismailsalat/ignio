# core/economy.py
"""
Economy helpers: per-server exchange rate, rate recommendation, daily supply
snapshots, and inflation signal. All settings live in guild_settings (no
migration); snapshots use the economy_snapshots table (migration 204).
"""
from __future__ import annotations

import time
from datetime import datetime, timezone

DEFAULT_RATE = 50000        # sobs per $1 (admin's own event anchor: 5,000,000 = $100)
RATE_KEY = "economy:rate"
MULT_KEY = "economy:sob_mult"
TAX_KEY = "economy:tax_pct"
BURNED_KEY = "economy:total_burned"

DEFAULT_TAX_PCT = 30        # % of a built-in purchase that is burned

# Item tier multipliers — price = reference_balance * tier (auto-scales per server).
ITEM_TIERS = {
    "shield": 0.4, "shield_plus": 1.2, "fortress": 3.0, "guardian": 8.0, "reflect": 50.0,
    "freeze": 0.5, "freeze_deep": 1.7, "tax_audit": 6.0, "slow_curse": 8.0, "marked": 16.0, "jail": 65.0,
    "boost": 0.3, "boost_adv": 1.2, "hunter": 2.5, "lucky": 4.0, "king": 80.0,
}
REF_FLOOR = 50              # reference never below this (new-server safety)


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


class Economy:
    def __init__(self, sob_repo):
        self.repo = sob_repo

    # ---- exchange rate ----------------------------------------------------

    async def get_rate(self, guild_id: int) -> int:
        raw = await self.repo.get_guild_setting(guild_id, RATE_KEY)
        try:
            v = int(raw)
            return v if v > 0 else DEFAULT_RATE
        except (TypeError, ValueError):
            return DEFAULT_RATE

    async def set_rate(self, guild_id: int, sobs_per_dollar: int) -> None:
        await self.repo.set_guild_setting(guild_id, RATE_KEY, str(int(sobs_per_dollar)))

    async def sobs_to_usd(self, guild_id: int, sobs: int) -> float:
        rate = await self.get_rate(guild_id)
        return sobs / rate

    async def usd_to_sobs(self, guild_id: int, usd: float) -> int:
        rate = await self.get_rate(guild_id)
        return int(round(usd * rate))

    # ---- supply + recommendation -----------------------------------------

    async def _db(self):
        return await self.repo._db()

    async def total_supply(self, guild_id: int) -> tuple[int, int]:
        """(total sobs in circulation, number of players with >0)."""
        db = await self._db()
        row = await db.fetchone(
            "SELECT COALESCE(SUM(sobs_received_alltime),0) AS s, "
            "COUNT(*) AS c FROM sob_users WHERE guild_id = ? AND sobs_received_alltime > 0",
            (guild_id,),
        )
        return int(row["s"]), int(row["c"])

    # ---- auto-balance: reference, prices, multiplier, tax -----------------

    async def reference_balance(self, guild_id: int) -> int:
        """Median balance of active players (>=10 sobs), floored. Whale-proof."""
        db = await self._db()
        rows = await db.fetchall(
            "SELECT sobs_received_alltime AS s FROM sob_users "
            "WHERE guild_id = ? AND sobs_received_alltime >= 10 "
            "ORDER BY sobs_received_alltime",
            (guild_id,),
        )
        vals = [int(r["s"]) for r in rows]
        if not vals:
            return REF_FLOOR
        mid = len(vals) // 2
        median = vals[mid] if len(vals) % 2 else (vals[mid - 1] + vals[mid]) / 2
        return max(REF_FLOOR, int(median))

    async def item_price(self, guild_id: int, item_key: str) -> int | None:
        """Auto-scaled price for a built-in item, or None if not a tiered item."""
        tier = ITEM_TIERS.get(item_key)
        if tier is None:
            return None
        ref = await self.reference_balance(guild_id)
        return max(10, int(round(ref * tier / 10) * 10))

    async def all_item_prices(self, guild_id: int) -> dict:
        ref = await self.reference_balance(guild_id)
        return {k: max(10, int(round(ref * t / 10) * 10)) for k, t in ITEM_TIERS.items()}

    async def get_sob_multiplier(self, guild_id: int) -> float:
        """How many sobs each reaction/snitch is worth. Default ON: auto from
        the economy unless an admin pinned a fixed value."""
        raw = await self.repo.get_guild_setting(guild_id, MULT_KEY)
        if raw is not None:
            try:
                return max(0.1, float(raw))
            except (ValueError, TypeError):
                pass
        return await self.suggest_multiplier(guild_id)

    async def set_sob_multiplier(self, guild_id: int, value: float | None) -> None:
        if value is None:
            await self.repo.set_guild_setting(guild_id, MULT_KEY, "")
        else:
            await self.repo.set_guild_setting(guild_id, MULT_KEY, str(max(0.1, float(value))))

    async def suggest_multiplier(self, guild_id: int) -> float:
        ref = await self.reference_balance(guild_id)
        sig = await self.inflation_signal(guild_id)
        if ref < 100:
            return 3.0
        if ref < 300:
            return 2.0
        if sig["status"] == "red":
            return 0.5
        if sig["status"] == "yellow":
            return 0.75
        return 1.0

    async def get_tax_pct(self, guild_id: int) -> int:
        raw = await self.repo.get_guild_setting(guild_id, TAX_KEY)
        try:
            v = int(raw)
            return max(0, min(90, v))
        except (TypeError, ValueError):
            return DEFAULT_TAX_PCT

    async def set_tax_pct(self, guild_id: int, pct: int) -> None:
        await self.repo.set_guild_setting(guild_id, TAX_KEY, str(max(0, min(90, int(pct)))))

    async def add_burned(self, guild_id: int, amount: int) -> None:
        raw = await self.repo.get_guild_setting(guild_id, BURNED_KEY)
        try:
            cur = int(raw)
        except (TypeError, ValueError):
            cur = 0
        await self.repo.set_guild_setting(guild_id, BURNED_KEY, str(cur + max(0, amount)))

    async def get_burned(self, guild_id: int) -> int:
        raw = await self.repo.get_guild_setting(guild_id, BURNED_KEY)
        try:
            return int(raw)
        except (TypeError, ValueError):
            return 0

    async def recommend_rate(self, guild_id: int) -> dict:
        """Suggest a sobs-per-dollar rate anchored to player effort.

        Always returns a usable number — even for a brand-new/empty server,
        where it falls back to a sensible starter rate instead of something silly.
        """
        total, players = await self.total_supply(guild_id)
        avg = (total / players) if players else 0

        if players < 5 or total < 1000:
            # New or tiny server: not enough economy to measure. Pick a sane
            # starter so admins have a real number from day one.
            rec = DEFAULT_RATE      # 50,000 / $1
            new_server = True
        else:
            typical = max(avg, 500)
            rec = int(round(typical / 0.50 / 100.0) * 100)   # nearest 100
            rec = max(1000, min(rec, 100000))                # sane band
            new_server = False

        return {
            "recommended": rec,
            "total": total,
            "players": players,
            "avg": avg,
            "new_server": new_server,
        }

    # ---- snapshots + inflation -------------------------------------------

    async def record_snapshot(self, guild_id: int) -> None:
        """Write a supply snapshot. Keyed to the half-hour slot so we capture
        ~48 points/day and the inflation graph fills in within hours."""
        total, players = await self.total_supply(guild_id)
        now = int(time.time())
        slot = now - (now % 1800)   # round down to a 30-minute slot
        db = await self._db()
        await db.execute(
            "INSERT INTO economy_snapshots (guild_id, day, total_sobs, players, created_at) "
            "VALUES (?,?,?,?,?) "
            "ON CONFLICT(guild_id, day) DO UPDATE SET total_sobs=excluded.total_sobs, "
            "players=excluded.players",
            (guild_id, str(slot), total, players, now),
        )
        await db.commit()

    async def supply_history(self, guild_id: int, points: int = 24) -> list[dict]:
        db = await self._db()
        rows = await db.fetchall(
            "SELECT day, total_sobs, players FROM economy_snapshots "
            "WHERE guild_id = ? ORDER BY CAST(day AS INTEGER) DESC LIMIT ?",
            (guild_id, points),
        )
        return [{"slot": r["day"], "total": r["total_sobs"], "players": r["players"]}
                for r in reversed(rows)]

    async def inflation_signal(self, guild_id: int) -> dict:
        """Compare oldest vs newest snapshot to flag inflation.
        For a brand-new server with <2 points, returns 'new' (not an error)."""
        hist = await self.supply_history(guild_id, 24)
        if len(hist) < 2:
            # New/starting server: no trend yet, but not broken — show current.
            cur = hist[0]["total"] if hist else (await self.total_supply(guild_id))[0]
            return {"status": "new", "pct": 0.0, "points": [cur]}
        first, last = hist[0]["total"], hist[-1]["total"]
        pct = ((last - first) / first * 100) if first else 0.0
        if pct <= 5:
            status = "green"
        elif pct <= 25:
            status = "yellow"
        else:
            status = "red"
        return {"status": status, "pct": pct, "points": [h["total"] for h in hist]}
