# core/protection.py
"""
Personal protection-risk pricing.

Problem this solves: protection used to be priced off the whole-server reference
balance, so a Shield could cost thousands while a Basic Audit only took a few
hundred from you — nobody bought protection, they just ate the hit.

Fix: price each protection item from the BUYER'S OWN realistic loss, and never
let protection cost more than the damage it prevents. We use a 24h high-water
"risk balance" so a rich player can't dump/move sobs, buy cheap protection, then
get rich again.

Offensive and buff items keep their normal economy-scaled prices (in economy.py).
Only the protection category is risk-priced here:
  shield      - blocks snitches (per-second, sold in bulk packs)
  guardian    - blocks the next few snitches
  reflect     - bounces one snitch back at the attacker
  audit_ward  - blocks Basic Audits for 30 min
  vault_ward  - blocks Basic Audits AND Grand Heists for 30 min  (NEW, for the rich)

All formulas are deliberately a FRACTION of the loss they prevent, with a hard
ceiling so protection is always the rational buy when you're being targeted.
"""
from __future__ import annotations

import time

# ---- tunables (chosen for this bot) ----------------------------------------
# Audit damage (must match economy.py AUDIT_* — imported, not duplicated).
WARD_FRACTION = 0.35       # Audit Ward  = 35% of one Basic Audit loss
VAULT_FRACTION = 0.35      # Vault Ward  = 35% of (basic + heist) loss
SHIELD_FRACTION = 0.35     # Shield 30m  = 35% of expected snitch loss
GUARDIAN_FRACTION = 0.35   # Guardian    = 35% of 5 snitches
GUARDIAN_SNITCHES = 5
REFLECT_FRACTION = 0.45    # Reflect     = 45% of one snitch (also punishes attacker)

# Protection may never cost more than this share of the damage it prevents.
MAX_PRICE_VS_DAMAGE = 0.80

# Snitch-loss fallback when a player has no recent history: a share of balance.
SNITCH_FALLBACK_PCT = 0.08
# Reaction-economy fallback so brand-new players still see a sane shield price.
MIN_SNITCH_RISK = 8

SHIELD_WINDOW_SECONDS = 1800   # the "unit" a Shield price is quoted for (30 min)

# 24h high-water mark key prefix (stored in guild_settings)
HIGH24_PREFIX = "risk:high24"


def _floor_price(p: float, minimum: int) -> int:
    return max(minimum, int(round(p)))


def _cap_to_damage(price: int, damage: float) -> int:
    """Never let protection cost more than MAX_PRICE_VS_DAMAGE of the loss."""
    if damage <= 0:
        return price
    ceiling = int(damage * MAX_PRICE_VS_DAMAGE)
    return max(1, min(price, ceiling)) if ceiling > 0 else price


class Protection:
    """Risk-based pricing + risk read-outs. Wraps the Economy + sob repo."""

    def __init__(self, economy, sob_repo):
        self.eco = economy
        self.repo = sob_repo

    async def _db(self):
        return await self.repo._db()

    # ------------------------------------------------------------------
    # risk balance: max(current, 24h high)
    # ------------------------------------------------------------------
    async def note_balance(self, guild_id: int, user_id: int, balance: int) -> None:
        """Update the 24h high-water mark for a user. Cheap; call on any balance
        read we already do (profile, stats). Stored as "value:timestamp"."""
        now = int(time.time())
        key = f"{HIGH24_PREFIX}:{user_id}"
        raw = await self.repo.get_guild_setting(guild_id, key)
        hi, ts = 0, 0
        if raw:
            try:
                hv, tv = raw.split(":")
                hi, ts = int(hv), int(tv)
            except (ValueError, AttributeError):
                hi, ts = 0, 0
        # reset the high if the stored one is older than 24h
        if now - ts > 86400:
            hi, ts = 0, 0
        if balance >= hi:
            await self.repo.set_guild_setting(guild_id, key, f"{int(balance)}:{now}")

    async def risk_balance(self, guild_id: int, user_id: int) -> int:
        """max(current balance, highest balance in the last 24h)."""
        stats = await self.repo.get_user_stats(guild_id, user_id)
        cur = int(stats["sobs_alltime"])
        raw = await self.repo.get_guild_setting(guild_id, f"{HIGH24_PREFIX}:{user_id}")
        hi = 0
        if raw:
            try:
                hv, tv = raw.split(":")
                if int(time.time()) - int(tv) <= 86400:
                    hi = int(hv)
            except (ValueError, AttributeError):
                hi = 0
        return max(cur, hi)

    # ------------------------------------------------------------------
    # risk numbers (what an attacker can realistically take)
    # ------------------------------------------------------------------
    async def audit_risk(self, guild_id: int, user_id: int) -> dict:
        """Returns the realistic audit damage for this user right now."""
        from core.economy import (AUDIT_BASIC_PCT, AUDIT_HEIST_PCT,
                                   AUDIT_DAILY_IMMUNE_PCT)
        rb = await self.risk_balance(guild_id, user_id)
        lost_today = await self.eco.audit_loss_today(guild_id, user_id)
        day_cap = int((rb + lost_today) * AUDIT_DAILY_IMMUNE_PCT)
        remaining = max(0, day_cap - lost_today)
        basic = min(int(rb * AUDIT_BASIC_PCT), remaining if remaining > 0 else int(rb * AUDIT_BASIC_PCT))
        heist = min(int(rb * AUDIT_HEIST_PCT), remaining if remaining > 0 else int(rb * AUDIT_HEIST_PCT))
        return {
            "risk_balance": rb,
            "basic": basic,
            "heist": heist,
            "day_cap": day_cap,
            "lost_today": lost_today,
            "remaining": remaining,
        }

    async def snitch_risk(self, guild_id: int, user_id: int) -> int:
        """Estimated sobs lost in one successful snitch against this user.

        Uses their average actual snitch-wipe loss over the last 7 days; if they
        have no history, falls back to a small share of their risk balance."""
        db = await self._db()
        since = int(time.time()) - 7 * 86400
        # snitch_wipe ledger rows have a negative delta on the victim (subject)
        row = await db.fetchone(
            "SELECT COALESCE(AVG(-delta),0) AS avg_loss, COUNT(*) AS n "
            "FROM economy_ledger WHERE guild_id=? AND subject_id=? "
            "AND event_type='snitch_wipe' AND delta<0 AND created_at>=?",
            (guild_id, user_id, since),
        )
        if row and int(row["n"]) > 0 and float(row["avg_loss"]) > 0:
            return max(MIN_SNITCH_RISK, int(round(float(row["avg_loss"]))))
        # fallback from balance
        rb = await self.risk_balance(guild_id, user_id)
        return max(MIN_SNITCH_RISK, int(rb * SNITCH_FALLBACK_PCT))

    # ------------------------------------------------------------------
    # prices (always a fraction of, and capped below, the damage prevented)
    # ------------------------------------------------------------------
    async def price_for(self, guild_id: int, user_id: int, item_key: str) -> int | None:
        """Personal price for a protection item, or None if not risk-priced."""
        if item_key not in ("shield", "guardian", "reflect", "audit_ward", "vault_ward"):
            return None

        factor = await self.price_factor(guild_id)

        if item_key in ("audit_ward", "vault_ward"):
            ar = await self.audit_risk(guild_id, user_id)
            if item_key == "audit_ward":
                dmg = ar["basic"]
                price = _floor_price(WARD_FRACTION * dmg * factor, 5)
                return _cap_to_damage(price, dmg)
            else:  # vault_ward blocks basic + heist
                dmg = ar["basic"] + ar["heist"]
                price = _floor_price(VAULT_FRACTION * dmg * factor, 10)
                return _cap_to_damage(price, dmg)

        # snitch-based protection
        sr = await self.snitch_risk(guild_id, user_id)
        if item_key == "shield":
            # price quoted for a 30-min block; per-second derived by the shop.
            dmg = sr
            price = _floor_price(SHIELD_FRACTION * dmg * factor, 5)
            return _cap_to_damage(price, dmg)
        if item_key == "guardian":
            dmg = GUARDIAN_SNITCHES * sr
            price = _floor_price(GUARDIAN_FRACTION * dmg * factor, 10)
            return _cap_to_damage(price, dmg)
        if item_key == "reflect":
            dmg = sr
            price = _floor_price(REFLECT_FRACTION * dmg * factor, 10)
            return _cap_to_damage(price, dmg)
        return None

    async def shield_per_second(self, guild_id: int, user_id: int) -> float:
        """Per-second shield price = (30-min price) / 1800, min sensible floor."""
        thirty = await self.price_for(guild_id, user_id, "shield")
        if thirty is None:
            return 0.0
        return max(0.01, thirty / SHIELD_WINDOW_SECONDS)

    # ------------------------------------------------------------------
    # read-out for !sob stats protection section
    # ------------------------------------------------------------------
    async def risk_readout(self, guild_id: int, user_id: int) -> dict:
        ar = await self.audit_risk(guild_id, user_id)
        ward = await self.price_for(guild_id, user_id, "audit_ward")
        vault = await self.price_for(guild_id, user_id, "vault_ward")
        shield30 = await self.price_for(guild_id, user_id, "shield")
        return {
            "risk_balance": ar["risk_balance"],
            "basic": ar["basic"],
            "heist": ar["heist"],
            "lost_today": ar["lost_today"],
            "day_cap": ar["day_cap"],
            "ward_price": ward,
            "vault_price": vault,
            "shield30_price": shield30,
        }

    # ------------------------------------------------------------------
    # per-guild auto-balancing factor
    #
    # All prices are already a safe fraction of the damage (and hard-capped at
    # 80%), so they can never be "too expensive". The auto-balancer gently tunes
    # a guild-wide multiplier from real behaviour, within tight bounds, never
    # more than 10% per day, and admins can override it.
    # ------------------------------------------------------------------
    FACTOR_KEY = "protection:price_factor"   # stored as e.g. "1.00"
    FACTOR_MIN = 0.50
    FACTOR_MAX = 1.20
    MAX_STEP = 0.10                          # max change per day

    async def price_factor(self, guild_id: int) -> float:
        raw = await self.repo.get_guild_setting(guild_id, self.FACTOR_KEY)
        try:
            f = float(raw)
            return min(self.FACTOR_MAX, max(self.FACTOR_MIN, f))
        except (TypeError, ValueError):
            return 1.0

    async def set_price_factor(self, guild_id: int, factor: float) -> None:
        f = min(self.FACTOR_MAX, max(self.FACTOR_MIN, float(factor)))
        await self.repo.set_guild_setting(guild_id, self.FACTOR_KEY, f"{f:.2f}")

    async def auto_balance(self, guild_id: int) -> dict:
        """Daily job: look at how protection performed and nudge the guild-wide
        price factor by at most MAX_STEP. Logs the change. Returns a summary.

        Heuristic (kept simple + safe):
          - If protection almost never gets bought relative to attacks suffered,
            it's likely too pricey -> lower the factor a little.
          - If protection is bought very often relative to attacks (cheap/spammy),
            raise the factor a little.
        Bounds + the per-purchase 80% damage cap guarantee it stays sane.
        """
        import time as _t
        db = await self._db()
        since = int(_t.time()) - 86400
        # attacks suffered (snitch wipes + audits) in the last day
        atk = await db.fetchone(
            "SELECT COUNT(*) AS n FROM economy_ledger WHERE guild_id=? AND created_at>=? "
            "AND event_type IN ('snitch_wipe','audit_steal')", (guild_id, since))
        # protection purchases in the last day
        buys = await db.fetchone(
            "SELECT COUNT(*) AS n FROM economy_ledger WHERE guild_id=? AND created_at>=? "
            "AND event_type='shop_purchase_base_cost' AND item_key IN "
            "('shield','guardian','reflect','audit_ward','vault_ward')", (guild_id, since))
        attacks = int(atk["n"]) if atk else 0
        purchases = int(buys["n"]) if buys else 0

        cur = await self.price_factor(guild_id)
        new = cur
        reason = "stable"
        if attacks >= 10:
            ratio = purchases / max(1, attacks)
            if ratio < 0.15:            # lots of attacks, almost no one shielding
                new = cur - self.MAX_STEP
                reason = "protection underbought -> cheaper"
            elif ratio > 1.5:           # bought way more than attacks (too cheap)
                new = cur + self.MAX_STEP
                reason = "protection overbought -> pricier"
        new = min(self.FACTOR_MAX, max(self.FACTOR_MIN, round(new, 2)))
        if abs(new - cur) >= 0.01:
            await self.set_price_factor(guild_id, new)
            from core import ledger
            async with db.transaction() as conn:
                await ledger.record(
                    conn, guild_id=guild_id, event_type="protection_autobalance",
                    transaction_id=ledger.new_tx_id(), delta=0,
                    metadata={"from": cur, "to": new, "reason": reason,
                              "attacks": attacks, "purchases": purchases})
        return {"factor_before": cur, "factor_after": new, "reason": reason,
                "attacks": attacks, "purchases": purchases}
