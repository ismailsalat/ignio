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
TREASURY_KEY = "economy:treasury"
REF_KEY = "economy:ref_cached"

DEFAULT_TAX_PCT = 30        # % of a built-in purchase that is burned

# Item tier multipliers — price = reference_balance * tier (auto-scales per server).
# Power-weighted: stronger items cost more. Shield is per-second (tiny base).
ITEM_TIERS = {
    "shield": 0.02,        # per SECOND of protection (stackable)
    "guardian": 8.0, "audit_ward": 4.0, "vault_ward": 10.0, "reflect": 50.0,
    "freeze": 0.5, "freeze_deep": 1.7,
    "audit": 1.2, "heist": 45.0,
    "slow_curse": 8.0, "marked": 16.0, "jail": 65.0,
    "boost": 0.3, "boost_adv": 1.2, "hunter": 2.5, "lucky": 4.0, "king": 80.0,
    "lockpick": 0.01, "safelock": 0.02,
}
REF_FLOOR = 50              # reference never below this (new-server safety)

# --- Earning formulas (tuned against real /plat data, economy stays ~flat) ---
SOB_VALUE_PCT = 0.03       # a sob reaction is worth ~3% of reference...
SOB_VALUE_FLOOR = 3        # ...but never less than 3 (so sobs always matter)
SNITCH_REWARD_PCT = 0.06   # snitch base reward ~6% of reference
SNITCH_REWARD_FLOOR = 6
SNITCH_STEAL_PCT = 0.50    # steal 50% of the wiped sobs (×boost if active)
SNITCH_TAX_PCT = 10        # % of snitch winnings -> treasury

# --- Audit (two-tier, anti-gang-up) ---
AUDIT_BASIC_PCT = 0.03     # basic audit steals 3% of target
AUDIT_HEIST_PCT = 0.08     # grand heist steals 8%
AUDIT_HEIST_CRIT = 0.20    # 20% chance heist pierces & breaks a shield
AUDIT_DAILY_IMMUNE_PCT = 0.15  # once you've lost 15% of balance to audits today, immune

# Per-AUDITOR limits (the thing players asked for: cap the attacker, not just
# the victim). Both are admin-configurable per guild via guild_settings:
#   economy:audit_daily_cap      -> max audits one person may perform per day
#   economy:audit_cooldown_secs  -> minimum seconds between a person's audits
AUDIT_DAILY_CAP_DEFAULT = 8       # audits per auditor per day
AUDIT_COOLDOWN_DEFAULT = 1800     # 30 minutes between audits


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
        """Cached reference balance used for pricing. Stays stable between
        rebalances (set by !rebalance or the daily loop) so prices don't drift
        mid-day. Falls back to a live compute if nothing's cached yet."""
        raw = await self.repo.get_guild_setting(guild_id, REF_KEY)
        try:
            v = int(raw)
            if v > 0:
                return max(REF_FLOOR, v)
        except (TypeError, ValueError):
            pass
        # nothing cached yet — compute and cache it now
        return await self.recompute_reference(guild_id)

    async def recompute_reference(self, guild_id: int) -> int:
        """Recalculate the median-of-active reference and CACHE it. Returns it.
        Called by !rebalance and the daily auto-rebalance."""
        db = await self._db()
        rows = await db.fetchall(
            "SELECT sobs_received_alltime AS s FROM sob_users "
            "WHERE guild_id = ? AND sobs_received_alltime >= 10 "
            "ORDER BY sobs_received_alltime",
            (guild_id,),
        )
        vals = [int(r["s"]) for r in rows]
        if not vals:
            ref = REF_FLOOR
        else:
            mid = len(vals) // 2
            median = vals[mid] if len(vals) % 2 else (vals[mid - 1] + vals[mid]) / 2
            ref = max(REF_FLOOR, int(median))
        await self.repo.set_guild_setting(guild_id, REF_KEY, str(ref))
        return ref

    async def item_price(self, guild_id: int, item_key: str) -> int | None:
        """Auto-scaled price for a built-in item, or None if not a tiered item."""
        tier = ITEM_TIERS.get(item_key)
        if tier is None:
            return None
        ref = await self.reference_balance(guild_id)
        raw = ref * tier
        if raw < 20:
            return max(1, int(round(raw)))
        return max(10, int(round(raw / 10) * 10))

    async def all_item_prices(self, guild_id: int) -> dict:
        ref = await self.reference_balance(guild_id)
        out = {}
        for k, t in ITEM_TIERS.items():
            raw = ref * t
            out[k] = max(1, int(round(raw))) if raw < 20 else max(10, int(round(raw / 10) * 10))
        return out

    async def audit_loss_today(self, guild_id: int, target_id: int) -> int:
        """How many sobs the target has lost to audits today (UTC)."""
        db = await self._db()
        row = await db.fetchone(
            "SELECT COALESCE(SUM(amount),0) AS s FROM audit_events "
            "WHERE guild_id=? AND target_id=? AND day=?",
            (guild_id, target_id, _today()),
        )
        return int(row["s"])

    async def is_audit_immune(self, guild_id: int, target_id: int, target_balance: int) -> bool:
        """True if the target has already lost >=15% of their balance to audits today."""
        lost = await self.audit_loss_today(guild_id, target_id)
        cap = int((target_balance + lost) * AUDIT_DAILY_IMMUNE_PCT)
        return lost >= cap and cap > 0

    async def log_audit(self, guild_id: int, auditor_id: int, target_id: int, amount: int) -> None:
        db = await self._db()
        await db.execute(
            "INSERT INTO audit_events (guild_id, target_id, auditor_id, amount, day, created_at) "
            "VALUES (?,?,?,?,?,?)",
            (guild_id, target_id, auditor_id, int(amount), _today(), int(time.time())),
        )
        await db.commit()

    # ----- per-auditor limits (cap the attacker, not just the victim) -----
    async def _setting_int(self, guild_id: int, key: str, default: int) -> int:
        raw = await self.repo.get_guild_setting(guild_id, key)
        try:
            return int(raw)
        except (TypeError, ValueError):
            return default

    async def audit_daily_cap(self, guild_id: int) -> int:
        return await self._setting_int(guild_id, "economy:audit_daily_cap", AUDIT_DAILY_CAP_DEFAULT)

    async def audit_cooldown_secs(self, guild_id: int) -> int:
        return await self._setting_int(guild_id, "economy:audit_cooldown_secs", AUDIT_COOLDOWN_DEFAULT)

    async def audits_done_today(self, guild_id: int, auditor_id: int) -> int:
        """How many audits this person has PERFORMED today (UTC)."""
        db = await self._db()
        row = await db.fetchone(
            "SELECT COUNT(*) AS n FROM audit_events WHERE guild_id=? AND auditor_id=? AND day=?",
            (guild_id, auditor_id, _today()),
        )
        return int(row["n"])

    async def audit_cooldown_left(self, guild_id: int, auditor_id: int) -> int:
        """Seconds left before this auditor may audit again (0 = ready)."""
        db = await self._db()
        row = await db.fetchone(
            "SELECT MAX(created_at) AS last FROM audit_events WHERE guild_id=? AND auditor_id=?",
            (guild_id, auditor_id),
        )
        last = int(row["last"]) if row and row["last"] is not None else 0
        if last == 0:
            return 0
        cd = await self.audit_cooldown_secs(guild_id)
        left = (last + cd) - int(time.time())
        return max(0, left)

    async def can_audit(self, guild_id: int, auditor_id: int) -> tuple[bool, str, dict]:
        """Gate an auditor: returns (allowed, reason, info).
        reason in: ok, daily_cap, cooldown. info carries numbers for the UX card."""
        cap = await self.audit_daily_cap(guild_id)
        done = await self.audits_done_today(guild_id, auditor_id)
        info = {"cap": cap, "done": done, "remaining": max(0, cap - done)}
        if cap > 0 and done >= cap:
            return False, "daily_cap", info
        cd_left = await self.audit_cooldown_left(guild_id, auditor_id)
        info["cooldown_left"] = cd_left
        info["cooldown_total"] = await self.audit_cooldown_secs(guild_id)
        if cd_left > 0:
            return False, "cooldown", info
        return True, "ok", info

    async def is_frozen(self, guild_id: int) -> bool:
        """Emergency economy freeze (admin sets via !admin freeze on)."""
        return (await self.repo.get_guild_setting(guild_id, "economy:frozen")) == "1"

    async def sob_value(self, guild_id: int) -> int:
        """How many sobs a single reaction is worth (before the multiplier).
        Floor-based so sobs always matter, scales up on richer servers."""
        ref = await self.reference_balance(guild_id)
        return max(SOB_VALUE_FLOOR, int(ref * SOB_VALUE_PCT))

    async def snitch_reward(self, guild_id: int) -> int:
        """Base reward for a successful snitch (before steal)."""
        ref = await self.reference_balance(guild_id)
        return max(SNITCH_REWARD_FLOOR, int(ref * SNITCH_REWARD_PCT))

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
        """Sob multiplier (how much each reaction is worth, times sob_value).

        The 2×/3× "bootstrap" boost is ONLY for genuinely new servers — ones
        with very few active earners. On an established server the median balance
        can look low simply because snitches/audits/steals keep draining people,
        and we must NOT mistake that for a new server and over-inflate reactions.
        So the boost is gated on the number of ACTIVE users, not just the median.
        """
        ref = await self.reference_balance(guild_id)
        sig = await self.inflation_signal(guild_id)
        active = await self._active_user_count(guild_id)

        # New, small server -> boost to get the economy moving.
        if active < 15:
            if ref < 100:
                return 3.0
            if ref < 300:
                return 2.0
        elif active < 40:
            # small-but-growing: a gentle nudge at most
            if ref < 100:
                return 1.5

        # Established server: keep reactions sane and let inflation control it.
        if sig["status"] == "red":
            return 0.5
        if sig["status"] == "yellow":
            return 0.75
        return 1.0

    async def _active_user_count(self, guild_id: int) -> int:
        """How many users have a meaningful balance (>= 10 sobs). Used to tell a
        brand-new server from an established one whose median looks low due to
        PvP draining."""
        db = await self._db()
        row = await db.fetchone(
            "SELECT COUNT(*) AS n FROM sob_users WHERE guild_id=? AND sobs_received_alltime >= 10",
            (guild_id,))
        return int(row["n"]) if row else 0

    async def get_tax_pct(self, guild_id: int) -> int:
        """Tax % added ON TOP of a built-in item's price. Auto-suggested from the
        economy unless an admin pinned a fixed value."""
        raw = await self.repo.get_guild_setting(guild_id, TAX_KEY)
        if raw not in (None, ""):
            try:
                return max(0, min(50, int(raw)))
            except (TypeError, ValueError):
                pass
        return await self.suggest_tax(guild_id)

    async def set_tax_pct(self, guild_id: int, pct: int | None) -> None:
        if pct is None:
            await self.repo.set_guild_setting(guild_id, TAX_KEY, "")  # back to auto
        else:
            await self.repo.set_guild_setting(guild_id, TAX_KEY, str(max(0, min(50, int(pct)))))

    async def suggest_tax(self, guild_id: int) -> int:
        """Auto tax rate: gentle on new/small economies, higher when inflating."""
        ref = await self.reference_balance(guild_id)
        sig = await self.inflation_signal(guild_id)
        if ref < 100:
            base = 5
        elif ref < 500:
            base = 10
        else:
            base = 15
        if sig["status"] == "red":
            base += 10
        elif sig["status"] == "yellow":
            base += 5
        return min(base, 30)

    # ---- burned (anti-inflation sink: the base price is destroyed) ----
    async def add_burned(self, guild_id: int, amount: int) -> None:
        # serialise the read-modify-write of the burned counter per guild so
        # concurrent purchases can't lose a burn increment to a race.
        db = await self._db()
        async with db.key_lock("burned", guild_id):
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

    # ---- treasury (the tax pot admins spend on events) ----
    async def get_treasury(self, guild_id: int) -> int:
        raw = await self.repo.get_guild_setting(guild_id, TREASURY_KEY)
        try:
            return int(raw)
        except (TypeError, ValueError):
            return 0

    async def add_treasury(self, guild_id: int, amount: int, *, payer_id: int | None = None) -> None:
        """Add tax to the treasury and log the payment for stats. The treasury
        counter update is serialised per guild so concurrent tax payments can't
        race and lose a deposit."""
        db = await self._db()
        async with db.key_lock("treasury", guild_id):
            cur = await self.get_treasury(guild_id)
            await self.repo.set_guild_setting(guild_id, TREASURY_KEY, str(cur + max(0, amount)))
        if payer_id is not None and amount > 0:
            await db.execute(
                "INSERT INTO tax_events (guild_id, user_id, amount, created_at) VALUES (?,?,?,?)",
                (guild_id, payer_id, int(amount), int(time.time())),
            )
            await db.commit()

    async def spend_treasury(self, guild_id: int, amount: int) -> bool:
        """Remove sobs from the treasury (admin payout). Returns False if short.
        Serialised per guild so the pot can't be double-spent by two concurrent
        payouts."""
        db = await self._db()
        async with db.key_lock("treasury", guild_id):
            cur = await self.get_treasury(guild_id)
            if amount > cur:
                return False
            await self.repo.set_guild_setting(guild_id, TREASURY_KEY, str(cur - amount))
            return True

    async def treasury_stats(self, guild_id: int) -> dict:
        """Stats for the treasury card: pot, taxed today/week/all, recent, top."""
        db = await self._db()
        now = int(time.time())
        day_ago, week_ago = now - 86400, now - 604800

        async def _sum(since=None):
            if since is None:
                r = await db.fetchone("SELECT COALESCE(SUM(amount),0) AS s FROM tax_events WHERE guild_id=?", (guild_id,))
            else:
                r = await db.fetchone("SELECT COALESCE(SUM(amount),0) AS s FROM tax_events WHERE guild_id=? AND created_at>=?", (guild_id, since))
            return int(r["s"])

        recent_rows = await db.fetchall(
            "SELECT user_id, amount, created_at FROM tax_events WHERE guild_id=? ORDER BY created_at DESC LIMIT 5",
            (guild_id,))
        top_rows = await db.fetchall(
            "SELECT user_id, SUM(amount) AS total FROM tax_events WHERE guild_id=? GROUP BY user_id ORDER BY total DESC LIMIT 1",
            (guild_id,))
        payers = await db.fetchone("SELECT COUNT(DISTINCT user_id) AS c FROM tax_events WHERE guild_id=?", (guild_id,))

        return {
            "treasury": await self.get_treasury(guild_id),
            "today": await _sum(day_ago),
            "week": await _sum(week_ago),
            "alltime": await _sum(),
            "payers": int(payers["c"]) if payers else 0,
            "recent": [{"user_id": int(r["user_id"]), "amount": int(r["amount"])} for r in recent_rows],
            "top": ({"user_id": int(top_rows[0]["user_id"]), "total": int(top_rows[0]["total"])}
                    if top_rows else None),
        }

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
        """Inflation = RECENT rate of change (last ~day of snapshots vs the day
        before), NOT growth from the first-ever snapshot. A one-time event no
        longer reads as permanent inflation."""
        hist = await self.supply_history(guild_id, 48)   # ~last day at 30-min slots
        if len(hist) < 4:
            cur = hist[-1]["total"] if hist else (await self.total_supply(guild_id))[0]
            return {"status": "new", "pct": 0.0, "points": [h["total"] for h in hist] or [cur],
                    "labels": [h.get("slot", "") for h in hist]}
        # compare the average of the most recent quarter vs the prior quarter
        q = max(1, len(hist) // 4)
        recent = sum(h["total"] for h in hist[-q:]) / q
        prior = sum(h["total"] for h in hist[-2 * q:-q]) / q
        pct = ((recent - prior) / prior * 100) if prior else 0.0
        if pct <= 3:
            status = "green"
        elif pct <= 12:
            status = "yellow"
        else:
            status = "red"
        return {"status": status, "pct": pct,
                "points": [h["total"] for h in hist],
                "labels": [h.get("slot", "") for h in hist]}


# ---- alt / farm detection helpers (module-level, reusable) ----
ALT_ACCOUNT_AGE_DAYS = 7      # account younger than this = suspicious
ALT_JOIN_HOURS = 24          # joined the server within this = suspicious
ALT_INACTIVE_MINUTES = 10    # no message in this long (while reacting) = suspicious


def score_member_suspicion(member, last_msg_at: int) -> dict:
    """Score how 'alt-like' a member is. Returns {suspicious, reasons[]}.
    member: a discord.Member (has created_at, joined_at). last_msg_at: unix ts (0 if never)."""
    import time as _t
    from datetime import timezone
    now = _t.time()
    reasons = []

    try:
        age_days = (now - member.created_at.replace(tzinfo=timezone.utc).timestamp()) / 86400
        if age_days < ALT_ACCOUNT_AGE_DAYS:
            reasons.append(f"account {age_days:.0f}d old")
    except Exception:
        pass

    try:
        if member.joined_at is not None:
            join_hrs = (now - member.joined_at.replace(tzinfo=timezone.utc).timestamp()) / 3600
            if join_hrs < ALT_JOIN_HOURS:
                reasons.append(f"joined {join_hrs:.0f}h ago")
    except Exception:
        pass

    # inactivity: never messaged, or not in the last N minutes
    if last_msg_at == 0:
        reasons.append("never messaged")
    elif (now - last_msg_at) > ALT_INACTIVE_MINUTES * 60:
        mins = (now - last_msg_at) / 60
        reasons.append(f"inactive {mins:.0f}m")

    return {"suspicious": len(reasons) > 0, "reasons": reasons}
