# core/steal.py
"""
!steal — a high-risk, high-reward PvP gamble.

Design goals (from spec): exciting but NOT a farming strategy. Low odds, real
cost on failure, hard cooldowns, a strict daily victim cap, and only tiny shop
items that nudge the odds. It must never beat getting sobbed naturally.

Balance numbers (the safer "doc 5" set):
  planned_steal   = max(5, floor(1.25% of target risk_balance))
  base chance     = 18%
  success         -> hunter gets 90%, treasury 10%; target loses planned
  failure         -> target loses NOTHING; hunter pays 20% of planned as a fee
                     (half to treasury, half burned)
  attacker        -> 15-min cooldown, max 4/day, 60-min per-target lockout
  target          -> max 4% of risk_balance lost/day; 30-min immunity after a hit
  Lockpick        -> +4 points (one use, 24h expiry, no stacking)
  Safe Lock       -> -5 points for 20 min (no stacking)
  final chance clamped to [8%, 25%]

Everything that mutates state happens inside ONE Database.transaction() so a
double !steal can't double-charge or double-steal, and nothing partial is left
behind on an invalid attempt.
"""
from __future__ import annotations

import secrets
import time
from datetime import datetime, timezone

from core import ledger

# ---- tunables (admin-overridable via guild_settings) -----------------------
STEAL_PCT = 0.0125            # 1.25% of risk balance per successful hit
STEAL_MIN = 5
STEAL_HARD_CAP = 50_000       # absolute max a single steal can move
BASE_CHANCE = 18              # %
HUNTER_SHARE = 0.90           # hunter keeps 90% on success
TAX_PCT = 10                  # 10% of the stolen amount -> treasury
FAIL_FEE_PCT = 0.20           # caught fee = 20% of planned (half tax / half burn)

DAILY_VICTIM_PCT = 0.04       # a target can lose at most 4% of risk bal/day
DAILY_VICTIM_HARD = 50_000    # and never more than this absolute per day
MIN_TARGET_BALANCE = 500      # target must have at least this to be worth it
PROTECTED_FLOOR = 50          # never drain a target below this with a steal

ATTACKER_COOLDOWN = 15 * 60   # 15 min between attempts
ATTACKER_DAILY_ATTEMPTS = 4   # max valid attempts/day
PER_TARGET_LOCKOUT = 60 * 60  # can't re-hit the same target for 60 min
TARGET_IMMUNITY = 30 * 60     # 30 min immunity after a SUCCESSFUL steal

LOCKPICK_BONUS = 4            # +4 points
SAFELOCK_REDUCTION = 5       # -5 points
CHANCE_FLOOR = 8
CHANCE_CEIL = 25

SAFELOCK_DURATION = 20 * 60   # 20 min


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


class StealError(Exception):
    """User-facing reason a steal can't proceed (no state changed)."""
    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


class Steal:
    def __init__(self, economy, sob_repo, shop_repo=None, protection=None):
        self.eco = economy
        self.repo = sob_repo
        self.shop = shop_repo
        self.protection = protection

    async def _db(self):
        return await self.repo._db()

    # ---- config (admin overridable) ----
    async def _cfg_int(self, guild_id, key, default):
        raw = await self.repo.get_guild_setting(guild_id, key)
        try:
            return int(raw)
        except (TypeError, ValueError):
            return default

    async def is_enabled(self, guild_id: int) -> bool:
        return (await self.repo.get_guild_setting(guild_id, "steal:enabled")) != "0"

    async def base_chance(self, guild_id: int) -> int:
        return await self._cfg_int(guild_id, "steal:base_chance", BASE_CHANCE)

    # ---- risk balance ----
    async def _risk_balance(self, guild_id, user_id) -> int:
        if self.protection is not None:
            try:
                return await self.protection.risk_balance(guild_id, user_id)
            except Exception:
                pass
        stats = await self.repo.get_user_stats(guild_id, user_id)
        return int(stats["sobs_alltime"])

    async def planned_steal(self, guild_id: int, target_id: int) -> int:
        rb = await self._risk_balance(guild_id, target_id)
        return min(max(STEAL_MIN, int(rb * STEAL_PCT)), STEAL_HARD_CAP)

    # ---- daily / cooldown lookups ----
    async def _attacker_attempts_today(self, guild_id, attacker_id) -> int:
        db = await self._db()
        row = await db.fetchone(
            "SELECT COUNT(*) AS n FROM steal_events WHERE guild_id=? AND attacker_id=? AND day=?",
            (guild_id, attacker_id, _today()))
        return int(row["n"])

    async def _attacker_cooldown_left(self, guild_id, attacker_id) -> int:
        db = await self._db()
        row = await db.fetchone(
            "SELECT MAX(created_at) AS last FROM steal_events WHERE guild_id=? AND attacker_id=?",
            (guild_id, attacker_id))
        last = int(row["last"]) if row and row["last"] is not None else 0
        if last == 0:
            return 0
        return max(0, (last + ATTACKER_COOLDOWN) - int(time.time()))

    async def _per_target_lock_left(self, guild_id, attacker_id, target_id) -> int:
        db = await self._db()
        row = await db.fetchone(
            "SELECT MAX(created_at) AS last FROM steal_events "
            "WHERE guild_id=? AND attacker_id=? AND target_id=?",
            (guild_id, attacker_id, target_id))
        last = int(row["last"]) if row and row["last"] is not None else 0
        if last == 0:
            return 0
        return max(0, (last + PER_TARGET_LOCKOUT) - int(time.time()))

    async def _target_immunity_left(self, guild_id, target_id) -> int:
        """A target is immune for TARGET_IMMUNITY after a SUCCESSFUL steal."""
        db = await self._db()
        row = await db.fetchone(
            "SELECT MAX(created_at) AS last FROM steal_events "
            "WHERE guild_id=? AND target_id=? AND success=1",
            (guild_id, target_id))
        last = int(row["last"]) if row and row["last"] is not None else 0
        if last == 0:
            return 0
        return max(0, (last + TARGET_IMMUNITY) - int(time.time()))

    async def _target_lost_today(self, guild_id, target_id) -> int:
        db = await self._db()
        row = await db.fetchone(
            "SELECT COALESCE(SUM(moved),0) AS s FROM steal_events "
            "WHERE guild_id=? AND target_id=? AND day=? AND success=1",
            (guild_id, target_id, _today()))
        return int(row["s"])

    async def _target_daily_cap(self, guild_id, target_id) -> int:
        rb = await self._risk_balance(guild_id, target_id)
        return min(int(rb * DAILY_VICTIM_PCT), DAILY_VICTIM_HARD)

    # ---- preview (for the embed before rolling) ----
    async def preview(self, guild_id: int, attacker_id: int, target_id: int,
                      use_lockpick: bool = False) -> dict:
        """Validate and compute the steal WITHOUT mutating anything. Raises
        StealError with a user-facing message if it can't proceed."""
        if not await self.is_enabled(guild_id):
            raise StealError("Steal is currently disabled on this server.")
        if attacker_id == target_id:
            raise StealError("You can't steal from yourself.")

        # attacker limits
        if await self._attacker_attempts_today(guild_id, attacker_id) >= ATTACKER_DAILY_ATTEMPTS:
            raise StealError(f"You've used all {ATTACKER_DAILY_ATTEMPTS} of your steal attempts today.")
        cd = await self._attacker_cooldown_left(guild_id, attacker_id)
        if cd > 0:
            raise StealError(f"Steal is on cooldown — try again in {_fmt(cd)}.")
        plock = await self._per_target_lock_left(guild_id, attacker_id, target_id)
        if plock > 0:
            raise StealError(f"You hit this person recently — wait {_fmt(plock)} before targeting them again.")

        # target limits
        rb = await self._risk_balance(guild_id, target_id)
        if rb < MIN_TARGET_BALANCE:
            raise StealError(f"That target is too poor to steal from (needs {MIN_TARGET_BALANCE}+ sobs).")
        if await self._target_immunity_left(guild_id, target_id) > 0:
            raise StealError("This target has Steal immunity right now (recently stolen from).")

        planned = await self.planned_steal(guild_id, target_id)
        # cap to remaining daily victim loss
        lost = await self._target_lost_today(guild_id, target_id)
        cap = await self._target_daily_cap(guild_id, target_id)
        remaining = cap - lost
        if remaining < planned:
            raise StealError("This target has reached their daily Steal protection limit.")

        # cap to current balance and protected floor
        cur = int((await self.repo.get_user_stats(guild_id, target_id))["sobs_alltime"])
        if cur - planned < PROTECTED_FLOOR:
            planned = max(0, cur - PROTECTED_FLOOR)
        if planned < STEAL_MIN:
            raise StealError("This target doesn't have enough stealable sobs right now.")

        # chance: base + lockpick (if owned & requested) - safe lock (if target has)
        chance = await self.base_chance(guild_id)
        has_lock = False
        if use_lockpick and self.shop is not None:
            inv = await self.shop.get_inventory(guild_id, attacker_id)
            if inv.get("lockpick", 0) > 0:
                has_lock = True
                chance += LOCKPICK_BONUS
        safelock = False
        if self.shop is not None and await self.shop.has_effect(guild_id, target_id, "safelock"):
            safelock = True
            chance -= SAFELOCK_REDUCTION
        chance = max(CHANCE_FLOOR, min(CHANCE_CEIL, chance))

        # attacker must afford the fail fee
        fail_fee = int(planned * FAIL_FEE_PCT)
        atk_bal = int((await self.repo.get_user_stats(guild_id, attacker_id))["sobs_alltime"])
        if atk_bal < fail_fee:
            raise StealError(f"You need at least {fail_fee} sobs to cover the risk of a failed steal.")

        return {
            "planned": planned, "chance": chance, "fail_fee": fail_fee,
            "use_lockpick": has_lock, "safelock": safelock,
            "hunter_gets": int(planned * HUNTER_SHARE),
            "tax": planned - int(planned * HUNTER_SHARE),
            "attempts_left": ATTACKER_DAILY_ATTEMPTS - await self._attacker_attempts_today(guild_id, attacker_id),
        }

    # ---- the actual attempt (atomic) ----
    async def attempt(self, guild_id: int, attacker_id: int, target_id: int,
                      use_lockpick: bool = False) -> dict:
        """Validate + roll + settle, all in one atomic transaction. Returns a
        result dict for the embed. Raises StealError (no state changed) if the
        attempt is invalid."""
        # Validate first (no mutation). Re-validated inside the txn too.
        pv = await self.preview(guild_id, attacker_id, target_id, use_lockpick)
        planned = pv["planned"]; chance = pv["chance"]; fee = pv["fail_fee"]
        use_lock = pv["use_lockpick"]; safelock = pv["safelock"]

        db = await self._db()
        ts = int(time.time())
        tx = ledger.new_tx_id()
        # secure server-side roll
        roll = secrets.randbelow(100)
        success = roll < chance

        # lock both users in a stable order
        a, b = sorted((attacker_id, target_id))
        async with db.key_lock("sob", guild_id, a):
            async with db.key_lock("sob", guild_id, b):
                async with db.transaction() as conn:
                    # re-check the most important caps INSIDE the txn (race-proof)
                    cur_t = await self.repo._balance(conn, guild_id, target_id)
                    cur_a = await self.repo._balance(conn, guild_id, attacker_id)
                    if success:
                        move = min(planned, max(0, cur_t - PROTECTED_FLOOR))
                        if move < STEAL_MIN:
                            # target balance dropped under us — treat as a clean miss,
                            # no fee (invalid outcome, refund nothing taken)
                            raise StealError("Target no longer has enough stealable sobs.")
                        # consume lockpick (only now that it's valid + succeeding/rolling)
                        if use_lock:
                            await self.shop._take_from_inventory(conn, guild_id, attacker_id, "lockpick", 1, ts)
                        # target loses `move`
                        tb, ta = await self.repo._apply_delta(conn, guild_id=guild_id, user_id=target_id, delta=-move, ts=ts)
                        tax = move - int(move * HUNTER_SHARE)
                        gain = move - tax
                        # attacker gains gain
                        ab, aa = await self.repo._apply_delta(conn, guild_id=guild_id, user_id=attacker_id, delta=gain, ts=ts)
                        await ledger.record(conn, guild_id=guild_id, event_type=ledger.EVT_STEAL_SUCCESS,
                            transaction_id=tx, subject_id=target_id, actor_id=attacker_id,
                            counterparty_id=attacker_id, delta=-move, balance_before=tb, balance_after=ta,
                            tax_amount=tax, metadata={"roll": roll, "chance": chance, "lockpick": use_lock})
                        await ledger.record(conn, guild_id=guild_id, event_type=ledger.EVT_STEAL_SUCCESS,
                            transaction_id=tx, subject_id=attacker_id, actor_id=attacker_id,
                            counterparty_id=target_id, delta=gain, balance_before=ab, balance_after=aa,
                            tax_amount=tax, metadata={"roll": roll, "chance": chance})
                        result = {"success": True, "moved": move, "gain": gain, "tax": tax,
                                  "fee": 0, "burned": 0, "chance": chance, "roll": roll}
                    else:
                        # failure: attacker pays fee (half tax, half burn); target untouched
                        if use_lock:
                            await self.shop._take_from_inventory(conn, guild_id, attacker_id, "lockpick", 1, ts)
                        pay = min(fee, cur_a)   # never go negative
                        ab, aa = await self.repo._apply_delta(conn, guild_id=guild_id, user_id=attacker_id, delta=-pay, ts=ts)
                        tax = pay // 2
                        burn = pay - tax
                        await ledger.record(conn, guild_id=guild_id, event_type=ledger.EVT_STEAL_FAIL_FEE,
                            transaction_id=tx, subject_id=attacker_id, actor_id=attacker_id,
                            counterparty_id=target_id, delta=-pay, balance_before=ab, balance_after=aa,
                            tax_amount=tax, burned_amount=burn, metadata={"roll": roll, "chance": chance})
                        result = {"success": False, "moved": 0, "gain": 0, "tax": tax,
                                  "fee": pay, "burned": burn, "chance": chance, "roll": roll}

                    # always log the attempt row (cooldowns/caps read from here)
                    await conn.execute(
                        "INSERT INTO steal_events (guild_id, attacker_id, target_id, planned, "
                        "chance, roll, success, moved, fee, tax, burned, lockpick, safelock, day, created_at, tx_id) "
                        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        (guild_id, attacker_id, target_id, planned, chance, roll,
                         1 if result["success"] else 0, result["moved"], result["fee"],
                         result["tax"], result["burned"], 1 if use_lock else 0,
                         1 if safelock else 0, _today(), ts, tx))

        # route tax to treasury + record burn (outside the balance txn)
        try:
            if result["tax"] > 0:
                await self.eco.add_treasury(guild_id, result["tax"], payer_id=attacker_id)
            if result["burned"] > 0:
                await self.eco.add_burned(guild_id, result["burned"])
        except Exception:
            pass

        # success applies 30-min target immunity automatically (read from events).
        result["attempts_left"] = ATTACKER_DAILY_ATTEMPTS - await self._attacker_attempts_today(guild_id, attacker_id)
        result["planned"] = planned
        return result

    # ---- stats for !steal stats and !sob stats ----
    async def stats(self, guild_id: int, user_id: int) -> dict:
        db = await self._db()
        prof = await db.fetchone(
            "SELECT COALESCE(SUM(CASE WHEN success=1 THEN moved-tax ELSE 0 END),0) AS profit, "
            "COALESCE(SUM(fee),0) AS fees, COUNT(*) AS attempts "
            "FROM steal_events WHERE guild_id=? AND attacker_id=?", (guild_id, user_id))
        lost = await db.fetchone(
            "SELECT COALESCE(SUM(moved),0) AS lost FROM steal_events "
            "WHERE guild_id=? AND target_id=? AND success=1", (guild_id, user_id))
        return {
            "profit": int(prof["profit"]) - int(prof["fees"]),
            "stolen": int(prof["profit"]),
            "fees_paid": int(prof["fees"]),
            "lost": int(lost["lost"]),
            "attempts_today": await self._attacker_attempts_today(guild_id, user_id),
            "attempts_cap": ATTACKER_DAILY_ATTEMPTS,
            "cooldown_left": await self._attacker_cooldown_left(guild_id, user_id),
            "immunity_left": await self._target_immunity_left(guild_id, user_id),
            "lost_today": await self._target_lost_today(guild_id, user_id),
            "daily_cap": await self._target_daily_cap(guild_id, user_id),
        }


def _fmt(secs: int) -> str:
    secs = max(0, int(secs)); h, r = divmod(secs, 3600); m, s = divmod(r, 60)
    if h: return f"{h}h {m}m"
    if m: return f"{m}m"
    return f"{s}s"
