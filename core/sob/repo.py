# core/sob/repo.py
from __future__ import annotations

from typing import Any

from core import ledger
from core.db import DatabaseManager
from core.time_utils import now_ts, today_keys

# Emoji names that count as a sob reaction.
SOB_EMOJIS: set[str] = {
    "4612win11emojisob",  # <:4612win11emojisob:1493190644221480960>
    "handsob",            # <:handsob:1493198316299747419>
}

DEFAULT_SNITCH_THRESHOLD = 10
SNITCH_EXPIRY_SECONDS = 7 * 24 * 3600


class SobRepo:
    """All sob database access. Tables: sob_users, sob_events, sob_periods.

    Every balance-changing method runs inside a single ``BEGIN IMMEDIATE``
    transaction and writes a matching ``economy_ledger`` row, so a balance can
    never move without an audit trail and the whole unit either fully succeeds
    or fully rolls back. Spends use conditional ``UPDATE ... WHERE balance >=
    cost`` and check the affected row count, so two concurrent commands can't
    both pass a balance check before either writes.
    """

    def __init__(self, db_manager: DatabaseManager):
        self.db_manager = db_manager

    async def _db(self):
        return await self.db_manager.get()

    # ------------------------------------------------------------------
    # internal helpers (operate on an already-open transaction connection)
    # ------------------------------------------------------------------

    async def _ensure_user_row(self, db, guild_id: int, user_id: int, ts: int) -> None:
        await db.execute(
            """
            INSERT OR IGNORE INTO sob_users
                (guild_id, user_id, sobs_received_alltime, sobs_given_alltime,
                 token_available, sobs_at_last_grant, token_granted_at,
                 total_snitches, updated_at)
            VALUES (?, ?, 0, 0, 0, 0, 0, 0, ?)
            """,
            (guild_id, user_id, ts),
        )

    async def _balance(self, conn, guild_id: int, user_id: int) -> int:
        cur = await conn.execute(
            "SELECT sobs_received_alltime FROM sob_users WHERE guild_id = ? AND user_id = ?",
            (guild_id, user_id),
        )
        row = await cur.fetchone()
        await cur.close()
        return int(row["sobs_received_alltime"]) if row else 0

    async def _apply_delta(
        self, conn, *, guild_id: int, user_id: int, delta: int, ts: int,
        update_periods: bool = True, allow_negative_floor: bool = True,
    ) -> tuple[int, int]:
        """Apply a signed delta to a user's received totals INSIDE an open
        transaction. Returns (balance_before, balance_after).

        For a positive delta this always adds. For a negative delta it floors
        the result at 0 (so a balance can never go negative) — callers that
        must not partially spend should pre-check with a conditional update.
        Day/week period rollups are kept in step when update_periods is True.
        """
        await self._ensure_user_row(conn, guild_id, user_id, ts)
        before = await self._balance(conn, guild_id, user_id)
        if allow_negative_floor:
            after = max(0, before + int(delta))
        else:
            after = before + int(delta)
        await conn.execute(
            "UPDATE sob_users SET sobs_received_alltime = ?, updated_at = ? WHERE guild_id = ? AND user_id = ?",
            (after, ts, guild_id, user_id),
        )
        if update_periods:
            applied = after - before
            day_k, week_k = today_keys()
            for ptype, pkey in (("day", day_k), ("week", week_k)):
                await conn.execute(
                    """
                    INSERT INTO sob_periods (guild_id, user_id, period_type, period_key, sobs_received, updated_at)
                    VALUES (?, ?, ?, ?, MAX(0, ?), ?)
                    ON CONFLICT(guild_id, user_id, period_type, period_key) DO UPDATE SET
                        sobs_received = MAX(0, sobs_received + ?), updated_at = excluded.updated_at
                    """,
                    (guild_id, user_id, ptype, pkey, int(applied), ts, int(applied)),
                )
        return before, after

    # ------------------------------------------------------------------
    # reaction add / remove
    # ------------------------------------------------------------------

    async def add_sob(
        self,
        *,
        guild_id: int,
        message_id: int,
        reactor_id: int,
        target_id: int,
        snitch_threshold: int = DEFAULT_SNITCH_THRESHOLD,
        credited_amount: int = 1,
        multiplier_ref: str = "",
    ) -> tuple[bool, int]:
        """Credit a sob reaction.

        ``credited_amount`` is the FINAL value of this reaction (already scaled
        by sob-value * multiplier), computed once by the caller and stored on
        the event so removal/snitch refund exactly this amount even if the
        multiplier later changes. Returns (added, credited_amount). added is
        False if the reactor already reacted to this message.

        The event insert, the target/reactor balance updates and the ledger row
        all happen in one atomic transaction, serialised per (guild, target).
        """
        ts = now_ts()
        credited_amount = max(1, int(credited_amount))
        db = await self._db()

        lock = db.key_lock("sob", guild_id, target_id)
        async with lock:
            async with db.transaction() as conn:
                cur = await conn.execute(
                    """
                    INSERT OR IGNORE INTO sob_events
                        (guild_id, message_id, reactor_id, target_id, created_at,
                         credited_amount, multiplier_ref)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (guild_id, message_id, reactor_id, target_id, ts,
                     credited_amount, multiplier_ref),
                )
                if cur.rowcount == 0:
                    return False, 0  # already reacted

                # target: + credited_amount received (alltime + day + week)
                before, after = await self._apply_delta(
                    conn, guild_id=guild_id, user_id=target_id,
                    delta=credited_amount, ts=ts,
                )

                # reactor: +1 given
                await self._ensure_user_row(conn, guild_id, reactor_id, ts)
                await conn.execute(
                    """
                    UPDATE sob_users
                    SET sobs_given_alltime = sobs_given_alltime + 1, updated_at = ?
                    WHERE guild_id = ? AND user_id = ?
                    """,
                    (ts, guild_id, reactor_id),
                )

                tx = ledger.new_tx_id()
                await ledger.record(
                    conn, guild_id=guild_id, event_type=ledger.EVT_REACTION_ADD,
                    transaction_id=tx, subject_id=target_id, actor_id=reactor_id,
                    counterparty_id=reactor_id, delta=credited_amount,
                    balance_before=before, balance_after=after,
                    message_id=message_id, multiplier_ref=multiplier_ref,
                    created_at=ts,
                )

        await self._maybe_grant_snitch_token(
            guild_id=guild_id, user_id=target_id,
            snitch_threshold=snitch_threshold, ts=ts,
        )
        return True, credited_amount

    async def remove_sob(self, *, guild_id: int, message_id: int, reactor_id: int) -> bool:
        """Remove a sob reaction, refunding EXACTLY the amount it credited.

        Reads credited_amount from the stored event so the refund matches the
        original credit regardless of any later multiplier change. Atomic.
        """
        ts = now_ts()
        db = await self._db()

        # we need target first to lock the right user
        row = await db.fetchone(
            "SELECT target_id, credited_amount FROM sob_events "
            "WHERE guild_id = ? AND message_id = ? AND reactor_id = ?",
            (guild_id, message_id, reactor_id),
        )
        if row is None:
            return False
        target_id = int(row["target_id"])

        lock = db.key_lock("sob", guild_id, target_id)
        async with lock:
            async with db.transaction() as conn:
                # re-read inside the transaction (could have been snitched away)
                cur = await conn.execute(
                    "SELECT target_id, credited_amount FROM sob_events "
                    "WHERE guild_id = ? AND message_id = ? AND reactor_id = ?",
                    (guild_id, message_id, reactor_id),
                )
                ev = await cur.fetchone()
                await cur.close()
                if ev is None:
                    return False
                credited = int(ev["credited_amount"])

                await conn.execute(
                    "DELETE FROM sob_events WHERE guild_id = ? AND message_id = ? AND reactor_id = ?",
                    (guild_id, message_id, reactor_id),
                )
                before, after = await self._apply_delta(
                    conn, guild_id=guild_id, user_id=target_id,
                    delta=-credited, ts=ts,
                )
                await conn.execute(
                    "UPDATE sob_users SET sobs_given_alltime = MAX(0, sobs_given_alltime - 1), "
                    "updated_at = ? WHERE guild_id = ? AND user_id = ?",
                    (ts, guild_id, reactor_id),
                )
                tx = ledger.new_tx_id()
                await ledger.record(
                    conn, guild_id=guild_id, event_type=ledger.EVT_REACTION_REMOVE,
                    transaction_id=tx, subject_id=target_id, actor_id=reactor_id,
                    counterparty_id=reactor_id, delta=(after - before),
                    balance_before=before, balance_after=after,
                    message_id=message_id, created_at=ts,
                )
        return True

    # ------------------------------------------------------------------
    # snitch — wipe ALL sobs from a message
    # ------------------------------------------------------------------

    async def snitch_message(
        self,
        *,
        guild_id: int,
        message_id: int,
        snitcher_id: int,
        target_id: int,
        now: int | None = None,
    ) -> tuple[bool, str, int]:
        """
        Use a snitch token to wipe all sobs from a message.
        Returns (success, reason, sobs_removed) where sobs_removed is the EXACT
        SUM(credited_amount) that was on the message (not the reaction count).
        Failure reasons: no_token, expired, own_message, no_sobs.

        Token consumption, the balance wipe and the ledger row are one atomic
        transaction, serialised per (guild, snitcher) so a token can't be spent
        twice by two concurrent snitches.
        """
        ts = now_ts() if now is None else now

        if snitcher_id == target_id:
            return False, "own_message", 0

        db = await self._db()
        # lock the snitcher so the token can't be double-spent, plus the target.
        async with db.key_lock("snitch", guild_id, snitcher_id):
            async with db.transaction() as conn:
                cur = await conn.execute(
                    "SELECT token_available, token_granted_at FROM sob_users "
                    "WHERE guild_id = ? AND user_id = ?",
                    (guild_id, snitcher_id),
                )
                srow = await cur.fetchone()
                await cur.close()

                if srow is None or int(srow["token_available"]) == 0:
                    return False, "no_token", 0

                if (ts - int(srow["token_granted_at"])) > SNITCH_EXPIRY_SECONDS:
                    await conn.execute(
                        "UPDATE sob_users SET token_available = 0, updated_at = ? "
                        "WHERE guild_id = ? AND user_id = ?",
                        (ts, guild_id, snitcher_id),
                    )
                    return False, "expired", 0

                cur = await conn.execute(
                    "SELECT reactor_id, credited_amount FROM sob_events "
                    "WHERE guild_id = ? AND message_id = ?",
                    (guild_id, message_id),
                )
                reaction_rows = await cur.fetchall()
                await cur.close()
                if not reaction_rows:
                    return False, "no_sobs", 0

                sob_total = sum(int(r["credited_amount"]) for r in reaction_rows)

                # reactors lose 1 "given" each
                for r in reaction_rows:
                    await conn.execute(
                        "UPDATE sob_users SET sobs_given_alltime = MAX(0, sobs_given_alltime - 1), "
                        "updated_at = ? WHERE guild_id = ? AND user_id = ?",
                        (ts, guild_id, int(r["reactor_id"])),
                    )

                # target loses the EXACT credited total (floored at 0)
                before, after = await self._apply_delta(
                    conn, guild_id=guild_id, user_id=target_id,
                    delta=-sob_total, ts=ts,
                )

                await conn.execute(
                    "DELETE FROM sob_events WHERE guild_id = ? AND message_id = ?",
                    (guild_id, message_id),
                )
                await conn.execute(
                    "UPDATE sob_users SET token_available = 0, total_snitches = total_snitches + 1, "
                    "updated_at = ? WHERE guild_id = ? AND user_id = ?",
                    (ts, guild_id, snitcher_id),
                )

                tx = ledger.new_tx_id()
                await ledger.record(
                    conn, guild_id=guild_id, event_type=ledger.EVT_SNITCH_WIPE,
                    transaction_id=tx, subject_id=target_id, actor_id=snitcher_id,
                    counterparty_id=snitcher_id, delta=(after - before),
                    balance_before=before, balance_after=after,
                    message_id=message_id, created_at=ts,
                    metadata={"reactions": len(reaction_rows), "wiped": sob_total},
                )
        return True, "ok", sob_total

    # ------------------------------------------------------------------
    # snitch token logic
    # ------------------------------------------------------------------

    async def _maybe_grant_snitch_token(
        self, *, guild_id: int, user_id: int, snitch_threshold: int, ts: int
    ) -> None:
        db = await self._db()
        async with db.key_lock("snitch", guild_id, user_id):
            async with db.transaction() as conn:
                cur = await conn.execute(
                    "SELECT sobs_received_alltime, token_available, sobs_at_last_grant "
                    "FROM sob_users WHERE guild_id = ? AND user_id = ?",
                    (guild_id, user_id),
                )
                row = await cur.fetchone()
                await cur.close()
                if row is None:
                    return

                alltime = int(row["sobs_received_alltime"])
                if int(row["token_available"]) == 1:
                    return

                sobs_at_last = int(row["sobs_at_last_grant"])
                next_grant = snitch_threshold if sobs_at_last == 0 else sobs_at_last + snitch_threshold
                if alltime < next_grant:
                    return

                await conn.execute(
                    """
                    UPDATE sob_users
                    SET token_available = 1, sobs_at_last_grant = ?, token_granted_at = ?, updated_at = ?
                    WHERE guild_id = ? AND user_id = ?
                    """,
                    (alltime, ts, ts, guild_id, user_id),
                )

    async def get_snitch_row(self, guild_id: int, user_id: int) -> dict[str, Any] | None:
        db = await self._db()
        row = await db.fetchone(
            "SELECT token_available, sobs_at_last_grant, token_granted_at, total_snitches FROM sob_users WHERE guild_id = ? AND user_id = ?",
            (guild_id, user_id),
        )
        if row is None:
            return None
        return {
            "token_available": int(row["token_available"]),
            "sobs_at_last_grant": int(row["sobs_at_last_grant"]),
            "token_granted_at": int(row["token_granted_at"]),
            "total_snitches": int(row["total_snitches"]),
        }

    async def get_snitch_threshold(self, guild_id: int) -> int:
        value = await self.get_guild_setting(guild_id, "sob_snitch_threshold")
        if value is None:
            return DEFAULT_SNITCH_THRESHOLD
        try:
            return max(1, int(value))
        except (ValueError, TypeError):
            return DEFAULT_SNITCH_THRESHOLD

    async def set_snitch_threshold(self, guild_id: int, value: int) -> int:
        value = max(1, int(value))
        await self.set_guild_setting(guild_id, "sob_snitch_threshold", str(value))
        return value

    # ------------------------------------------------------------------
    # guild settings (generic key/value)
    # ------------------------------------------------------------------

    async def get_guild_setting(self, guild_id: int, key: str) -> str | None:
        db = await self._db()
        row = await db.fetchone(
            "SELECT value FROM guild_settings WHERE guild_id = ? AND key = ?",
            (guild_id, key),
        )
        return str(row["value"]) if row is not None else None

    async def set_guild_setting(self, guild_id: int, key: str, value: str) -> None:
        db = await self._db()
        ts = now_ts()
        await db.execute(
            """
            INSERT INTO guild_settings (guild_id, key, value, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(guild_id, key) DO UPDATE SET
                value = excluded.value, updated_at = excluded.updated_at
            """,
            (guild_id, key, value, ts),
        )
        await db.commit()

    # ------------------------------------------------------------------
    # accepted sob emojis (per-server, falls back to global defaults)
    # ------------------------------------------------------------------

    async def get_accepted_emojis(self, guild_id: int) -> set[str]:
        """Per-server accepted emoji names, or the global defaults if unset."""
        raw = await self.get_guild_setting(guild_id, "sob_emojis")
        if not raw:
            return set(SOB_EMOJIS)
        names = {part.strip() for part in raw.split(",") if part.strip()}
        return names or set(SOB_EMOJIS)

    async def add_accepted_emoji(self, guild_id: int, name: str) -> set[str]:
        current = await self.get_accepted_emojis(guild_id)
        current.add(name.strip())
        await self.set_guild_setting(guild_id, "sob_emojis", ",".join(sorted(current)))
        return current

    async def remove_accepted_emoji(self, guild_id: int, name: str) -> set[str]:
        current = await self.get_accepted_emojis(guild_id)
        current.discard(name.strip())
        await self.set_guild_setting(guild_id, "sob_emojis", ",".join(sorted(current)))
        return current

    # ------------------------------------------------------------------
    # admin data ops
    # ------------------------------------------------------------------

    async def adjust_received(
        self, guild_id: int, user_id: int, delta: int,
        *, event_type: str = ledger.EVT_CORRECTION, actor_id: int | None = None,
        counterparty_id: int = 0, transaction_id: str | None = None,
        message_id: int = 0, game_id: str = "", item_key: str = "",
        item_name: str = "", quantity: int = 0, price: int = 0,
        tax_amount: int = 0, treasury_amount: int = 0, burned_amount: int = 0,
        multiplier_ref: str = "", metadata: dict | None = None,
    ) -> int:
        """Add (or subtract, if negative) sobs to a user's all-time + today +
        week. Returns the new all-time total. Floors at 0. Atomic + ledgered.

        This is the generic balance primitive used by daily, admin grants,
        snitch reward/steal, audits and games. Each call is its own atomic
        transaction and writes one ledger row. For a conserved transfer between
        two users use :meth:`transfer`; for a guarded spend that must reject if
        the balance is too low use :meth:`spend`.
        """
        ts = now_ts()
        db = await self._db()
        tx = transaction_id or ledger.new_tx_id()
        async with db.key_lock("sob", guild_id, user_id):
            async with db.transaction() as conn:
                before, after = await self._apply_delta(
                    conn, guild_id=guild_id, user_id=user_id, delta=int(delta), ts=ts,
                )
                await ledger.record(
                    conn, guild_id=guild_id, event_type=event_type,
                    transaction_id=tx,
                    subject_id=user_id,
                    actor_id=user_id if actor_id is None else actor_id,
                    counterparty_id=counterparty_id, delta=(after - before),
                    balance_before=before, balance_after=after,
                    message_id=message_id, game_id=game_id, item_key=item_key,
                    item_name=item_name, quantity=quantity, price=price,
                    tax_amount=tax_amount, treasury_amount=treasury_amount,
                    burned_amount=burned_amount, multiplier_ref=multiplier_ref,
                    metadata=metadata, created_at=ts,
                )
        return after

    async def spend(
        self, guild_id: int, user_id: int, cost: int,
        *, event_type: str, actor_id: int | None = None, counterparty_id: int = 0,
        transaction_id: str | None = None, item_key: str = "", item_name: str = "",
        quantity: int = 0, price: int = 0, tax_amount: int = 0,
        treasury_amount: int = 0, burned_amount: int = 0, metadata: dict | None = None,
    ) -> tuple[bool, int]:
        """Atomically subtract ``cost`` from a user ONLY if they can afford it.

        Uses a conditional ``UPDATE ... WHERE sobs_received_alltime >= cost`` and
        checks the affected row count: if 0 rows changed the balance was too
        low and nothing is spent (returns (False, current_balance)). This is the
        race-proof replacement for "check balance, then later subtract".
        Returns (success, balance_after).
        """
        cost = int(cost)
        if cost < 0:
            cost = 0
        ts = now_ts()
        db = await self._db()
        tx = transaction_id or ledger.new_tx_id()
        async with db.key_lock("sob", guild_id, user_id):
            async with db.transaction() as conn:
                await self._ensure_user_row(conn, guild_id, user_id, ts)
                before = await self._balance(conn, guild_id, user_id)
                cur = await conn.execute(
                    "UPDATE sob_users SET sobs_received_alltime = sobs_received_alltime - ?, "
                    "updated_at = ? WHERE guild_id = ? AND user_id = ? AND sobs_received_alltime >= ?",
                    (cost, ts, guild_id, user_id, cost),
                )
                if cur.rowcount == 0:
                    # too poor — conditional update matched no row. Nothing spent.
                    return False, before
                after = before - cost
                # keep period rollups in step with the spend
                day_k, week_k = today_keys()
                for ptype, pkey in (("day", day_k), ("week", week_k)):
                    await conn.execute(
                        "UPDATE sob_periods SET sobs_received = MAX(0, sobs_received - ?), "
                        "updated_at = ? WHERE guild_id = ? AND user_id = ? AND period_type = ? AND period_key = ?",
                        (cost, ts, guild_id, user_id, ptype, pkey),
                    )
                await ledger.record(
                    conn, guild_id=guild_id, event_type=event_type,
                    transaction_id=tx, subject_id=user_id,
                    actor_id=user_id if actor_id is None else actor_id,
                    counterparty_id=counterparty_id, delta=-cost,
                    balance_before=before, balance_after=after,
                    item_key=item_key, item_name=item_name, quantity=quantity,
                    price=price, tax_amount=tax_amount, treasury_amount=treasury_amount,
                    burned_amount=burned_amount, metadata=metadata, created_at=ts,
                )
        return True, after

    async def transfer(
        self, guild_id: int, from_id: int, to_id: int, amount: int,
        *, event_type: str, actor_id: int | None = None, transaction_id: str | None = None,
        cap_to_balance: bool = True, tax_amount: int = 0, game_id: str = "",
        message_id: int = 0, metadata: dict | None = None,
    ) -> int:
        """Conserved transfer of ``amount`` from one user to another, atomically.

        No sobs are minted: the receiver gains exactly what the sender loses
        (minus optional ``tax_amount``, which the caller routes to the treasury
        and which is recorded as a separate ledger row by the caller). If
        ``cap_to_balance`` the transfer is capped at the sender's current
        balance. Writes two ledger rows under one transaction_id (double-entry).
        Returns the amount actually transferred to the receiver (net of tax).
        """
        amount = int(amount)
        if amount <= 0:
            return 0
        ts = now_ts()
        db = await self._db()
        tx = transaction_id or ledger.new_tx_id()
        # lock both users in a stable order to avoid deadlocks
        a, b = sorted((from_id, to_id))
        async with db.key_lock("sob", guild_id, a):
            async with db.key_lock("sob", guild_id, b):
                async with db.transaction() as conn:
                    await self._ensure_user_row(conn, guild_id, from_id, ts)
                    await self._ensure_user_row(conn, guild_id, to_id, ts)
                    sender_bal = await self._balance(conn, guild_id, from_id)
                    moved = min(amount, sender_bal) if cap_to_balance else amount
                    if moved <= 0:
                        return 0
                    net = moved - int(tax_amount)
                    if net < 0:
                        net = 0
                    sb_before, sb_after = await self._apply_delta(
                        conn, guild_id=guild_id, user_id=from_id, delta=-moved, ts=ts,
                    )
                    rb_before, rb_after = await self._apply_delta(
                        conn, guild_id=guild_id, user_id=to_id, delta=net, ts=ts,
                    )
                    await ledger.record(
                        conn, guild_id=guild_id, event_type=event_type,
                        transaction_id=tx, subject_id=from_id,
                        actor_id=from_id if actor_id is None else actor_id,
                        counterparty_id=to_id, delta=(sb_after - sb_before),
                        balance_before=sb_before, balance_after=sb_after,
                        game_id=game_id, message_id=message_id, tax_amount=tax_amount,
                        metadata=metadata, created_at=ts,
                    )
                    await ledger.record(
                        conn, guild_id=guild_id, event_type=event_type,
                        transaction_id=tx, subject_id=to_id,
                        actor_id=from_id if actor_id is None else actor_id,
                        counterparty_id=from_id, delta=(rb_after - rb_before),
                        balance_before=rb_before, balance_after=rb_after,
                        game_id=game_id, message_id=message_id, tax_amount=tax_amount,
                        metadata=metadata, created_at=ts,
                    )
        return net

    async def grant_tokens(self, guild_id: int, user_id: int, count: int = 1) -> int:
        """Give a user snitch token(s). The model holds one token flag, so this
        sets token_available=1 and refreshes the grant time. Returns 1 if a
        token is now available."""
        ts = now_ts()
        db = await self._db()
        await self._ensure_user_row(db, guild_id, user_id, ts)
        await db.execute(
            "UPDATE sob_users SET token_available = 1, token_granted_at = ?, updated_at = ? WHERE guild_id = ? AND user_id = ?",
            (ts, ts, guild_id, user_id),
        )
        await db.commit()
        return 1

    async def reset_user(self, guild_id: int, user_id: int) -> None:
        """Zero out a single user's sob data in this guild (received/given/periods/token).
        Records a ledger correction entry so the wipe itself is auditable."""
        ts = now_ts()
        db = await self._db()
        async with db.key_lock("sob", guild_id, user_id):
            async with db.transaction() as conn:
                before = await self._balance(conn, guild_id, user_id)
                await conn.execute(
                    "UPDATE sob_users SET sobs_received_alltime = 0, sobs_given_alltime = 0, token_available = 0, total_snitches = 0, sobs_at_last_grant = 0, token_granted_at = 0, updated_at = ? WHERE guild_id = ? AND user_id = ?",
                    (ts, guild_id, user_id),
                )
                await conn.execute(
                    "DELETE FROM sob_periods WHERE guild_id = ? AND user_id = ?",
                    (guild_id, user_id),
                )
                if before:
                    await ledger.record(
                        conn, guild_id=guild_id, event_type=ledger.EVT_RESET,
                        transaction_id=ledger.new_tx_id(), subject_id=user_id,
                        actor_id=user_id, delta=-before, balance_before=before,
                        balance_after=0, created_at=ts,
                    )

    async def recount(self, guild_id: int) -> dict[str, int]:
        """Rebuild received totals from the raw sob_events log using the EXACT
        SUM(credited_amount) per user (not a flat reaction count), so a recount
        reproduces the same balances the events credited. Records a correction
        ledger entry per user whose total changed. Returns a small summary."""
        ts = now_ts()
        db = await self._db()
        async with db.transaction() as conn:
            cur = await conn.execute(
                "SELECT target_id, COALESCE(SUM(credited_amount),0) AS c, COUNT(*) AS n "
                "FROM sob_events WHERE guild_id = ? GROUP BY target_id",
                (guild_id,),
            )
            rows = await cur.fetchall()
            await cur.close()
            counts = {int(r["target_id"]): int(r["c"]) for r in rows}
            scanned = sum(int(r["n"]) for r in rows)

            # snapshot current balances for ledger before/after
            cur = await conn.execute(
                "SELECT user_id, sobs_received_alltime FROM sob_users WHERE guild_id = ?",
                (guild_id,),
            )
            existing = {int(r["user_id"]): int(r["sobs_received_alltime"]) for r in await cur.fetchall()}
            await cur.close()

            await conn.execute(
                "UPDATE sob_users SET sobs_received_alltime = 0, updated_at = ? WHERE guild_id = ?",
                (ts, guild_id),
            )
            for uid, c in counts.items():
                await self._ensure_user_row(conn, guild_id, uid, ts)
                await conn.execute(
                    "UPDATE sob_users SET sobs_received_alltime = ?, updated_at = ? WHERE guild_id = ? AND user_id = ?",
                    (c, ts, guild_id, uid),
                )
            # ledger corrections for everyone whose total changed
            all_uids = set(counts) | set(existing)
            for uid in all_uids:
                before = existing.get(uid, 0)
                after = counts.get(uid, 0)
                if before != after:
                    await ledger.record(
                        conn, guild_id=guild_id, event_type=ledger.EVT_RECOUNT,
                        transaction_id=ledger.new_tx_id(), subject_id=uid,
                        actor_id=0, delta=(after - before), balance_before=before,
                        balance_after=after, created_at=ts,
                        metadata={"source": "recount"},
                    )
            return {"users_recounted": len(counts), "events_scanned": scanned}

    # ------------------------------------------------------------------
    # security log (blocked / suspicious actions)
    # ------------------------------------------------------------------

    async def log_security(
        self, guild_id: int, event_type: str, *, actor_id: int = 0, target_id: int = 0,
        message_id: int = 0, reason: str = "", metadata: dict | None = None,
    ) -> None:
        import json as _json
        db = await self._db()
        meta = _json.dumps(metadata, ensure_ascii=False, default=str) if metadata else ""
        await db.execute(
            "INSERT INTO security_log (guild_id, created_at, event_type, actor_id, target_id, message_id, reason, metadata) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (guild_id, now_ts(), event_type, actor_id, target_id, message_id, reason, meta),
        )
        await db.commit()

    async def recent_reaction_count(self, guild_id: int, reactor_id: int, since_ts: int) -> int:
        """How many reactions this reactor has given since since_ts (rate limit)."""
        db = await self._db()
        row = await db.fetchone(
            "SELECT COUNT(*) AS n FROM sob_events WHERE guild_id=? AND reactor_id=? AND created_at>=?",
            (guild_id, reactor_id, since_ts),
        )
        return int(row["n"]) if row else 0

    async def reciprocal_count(self, guild_id: int, reactor_id: int, target_id: int, since_ts: int) -> int:
        """How many times target_id has reacted back to reactor_id recently —
        a high count between a small pair signals reciprocal farming."""
        db = await self._db()
        row = await db.fetchone(
            "SELECT COUNT(*) AS n FROM sob_events WHERE guild_id=? AND reactor_id=? AND target_id=? AND created_at>=?",
            (guild_id, target_id, reactor_id, since_ts),
        )
        return int(row["n"]) if row else 0

    # ------------------------------------------------------------------
    # stat fetchers
    # ------------------------------------------------------------------

    async def get_user_stats(self, guild_id: int, user_id: int) -> dict[str, int]:
        day_k, week_k = today_keys()
        db = await self._db()

        alltime = await db.fetchone(
            "SELECT sobs_received_alltime, sobs_given_alltime FROM sob_users WHERE guild_id = ? AND user_id = ?",
            (guild_id, user_id),
        )
        daily = await db.fetchone(
            "SELECT sobs_received FROM sob_periods WHERE guild_id = ? AND user_id = ? AND period_type = 'day' AND period_key = ?",
            (guild_id, user_id, day_k),
        )
        weekly = await db.fetchone(
            "SELECT sobs_received FROM sob_periods WHERE guild_id = ? AND user_id = ? AND period_type = 'week' AND period_key = ?",
            (guild_id, user_id, week_k),
        )
        return {
            "sobs_today": int(daily["sobs_received"]) if daily else 0,
            "sobs_week": int(weekly["sobs_received"]) if weekly else 0,
            "sobs_alltime": int(alltime["sobs_received_alltime"]) if alltime else 0,
            "sobs_given": int(alltime["sobs_given_alltime"]) if alltime else 0,
        }

    async def _period_leader(self, guild_id: int, period_type: str, period_key: int) -> dict[str, Any] | None:
        db = await self._db()
        row = await db.fetchone(
            """
            SELECT user_id, sobs_received FROM sob_periods
            WHERE guild_id = ? AND period_type = ? AND period_key = ?
            ORDER BY sobs_received DESC, user_id ASC LIMIT 1
            """,
            (guild_id, period_type, period_key),
        )
        if row is None or int(row["sobs_received"]) == 0:
            return None
        return {"user_id": int(row["user_id"]), "count": int(row["sobs_received"])}

    async def get_daily_leader(self, guild_id: int) -> dict[str, Any] | None:
        day_k, _ = today_keys()
        return await self._period_leader(guild_id, "day", day_k)

    async def get_weekly_leader(self, guild_id: int) -> dict[str, Any] | None:
        _, week_k = today_keys()
        return await self._period_leader(guild_id, "week", week_k)

    async def _top_user(self, guild_id: int, column: str) -> dict[str, Any] | None:
        db = await self._db()
        row = await db.fetchone(
            f"SELECT user_id, {column} AS c FROM sob_users WHERE guild_id = ? ORDER BY {column} DESC, user_id ASC LIMIT 1",
            (guild_id,),
        )
        if row is None or int(row["c"]) == 0:
            return None
        return {"user_id": int(row["user_id"]), "count": int(row["c"])}

    async def get_alltime_leader(self, guild_id: int) -> dict[str, Any] | None:
        return await self._top_user(guild_id, "sobs_received_alltime")

    async def get_top_alltime(self, guild_id: int, n: int = 10) -> list[dict[str, Any]]:
        """Top N users by all-time sobs received (for the leaderboard card)."""
        db = await self._db()
        rows = await db.fetchall(
            "SELECT user_id, sobs_received_alltime AS c FROM sob_users "
            "WHERE guild_id = ? AND sobs_received_alltime > 0 "
            "ORDER BY sobs_received_alltime DESC, user_id ASC LIMIT ?",
            (guild_id, n),
        )
        return [{"user_id": int(r["user_id"]), "count": int(r["c"])} for r in rows]

    async def get_top_giver(self, guild_id: int) -> dict[str, Any] | None:
        return await self._top_user(guild_id, "sobs_given_alltime")

    async def get_top_snitch(self, guild_id: int) -> dict[str, Any] | None:
        return await self._top_user(guild_id, "total_snitches")

    async def _period_rank(self, guild_id: int, user_id: int, period_type: str, period_key: int) -> int:
        db = await self._db()
        row = await db.fetchone(
            """
            SELECT COUNT(*) + 1 AS rank FROM sob_periods
            WHERE guild_id = ? AND period_type = ? AND period_key = ?
              AND sobs_received > (
                  SELECT COALESCE(sobs_received, 0) FROM sob_periods
                  WHERE guild_id = ? AND user_id = ? AND period_type = ? AND period_key = ?
              )
            """,
            (guild_id, period_type, period_key, guild_id, user_id, period_type, period_key),
        )
        return int(row["rank"]) if row else 1

    async def get_user_daily_rank(self, guild_id: int, user_id: int) -> int:
        day_k, _ = today_keys()
        return await self._period_rank(guild_id, user_id, "day", day_k)

    async def get_user_weekly_rank(self, guild_id: int, user_id: int) -> int:
        _, week_k = today_keys()
        return await self._period_rank(guild_id, user_id, "week", week_k)

    async def get_user_alltime_rank(self, guild_id: int, user_id: int) -> int:
        db = await self._db()
        row = await db.fetchone(
            """
            SELECT COUNT(*) + 1 AS rank FROM sob_users
            WHERE guild_id = ?
              AND sobs_received_alltime > (
                  SELECT COALESCE(sobs_received_alltime, 0) FROM sob_users
                  WHERE guild_id = ? AND user_id = ?
              )
            """,
            (guild_id, guild_id, user_id),
        )
        return int(row["rank"]) if row else 1
