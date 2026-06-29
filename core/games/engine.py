# core/games/engine.py
"""Reusable PvP games foundation. Roulette is the first game; coinflip,
blackjack, slots, auctions can reuse this.

Responsibilities:
- Track who's currently in a match (so they can't be double-challenged).
- Per-user cooldowns to prevent spam.
- Validate wagers (both players can afford it).
- ESCROW: atomically lock both wagers into a pending match so neither player
  can spend escrowed sobs during the animation; pay out or refund on settle.
- Settle a match: conserved transfer winner<-loser, optional house tax to treasury.
- Log every match for stats + !admin export.

No sobs are ever minted: the winner gains exactly what the loser loses (minus tax,
which is removed from the pot and sent to the treasury).
"""
from __future__ import annotations

import time
import uuid

from core import ledger


HOUSE_TAX_PCT = 5          # % of the winnings that goes to the treasury
COOLDOWN_SECONDS = 20      # per-user cooldown between starting games


class GamesEngine:
    def __init__(self, sob_repo, economy=None):
        self.sob_repo = sob_repo
        self.economy = economy
        self._busy: set[tuple[int, int]] = set()        # (guild_id, user_id) in a match
        self._cooldowns: dict[tuple[int, int], float] = {}

    # ---- player state ----
    def is_busy(self, guild_id: int, user_id: int) -> bool:
        return (guild_id, user_id) in self._busy

    def mark_busy(self, guild_id: int, *user_ids: int) -> None:
        for uid in user_ids:
            self._busy.add((guild_id, uid))

    def clear_busy(self, guild_id: int, *user_ids: int) -> None:
        for uid in user_ids:
            self._busy.discard((guild_id, uid))

    def on_cooldown(self, guild_id: int, user_id: int) -> int:
        """Seconds left on cooldown, or 0 if ready."""
        until = self._cooldowns.get((guild_id, user_id), 0)
        left = int(until - time.time())
        return max(0, left)

    def set_cooldown(self, guild_id: int, user_id: int) -> None:
        self._cooldowns[(guild_id, user_id)] = time.time() + COOLDOWN_SECONDS

    # ---- wager checks ----
    async def can_afford(self, guild_id: int, user_id: int, amount: int) -> bool:
        stats = await self.sob_repo.get_user_stats(guild_id, user_id)
        return int(stats["sobs_alltime"]) >= amount

    # ---- escrow -----------------------------------------------------------
    async def open_match(self, guild_id: int, game: str, challenger: int,
                         opponent: int, wager: int) -> tuple[bool, str, str | None]:
        """Atomically lock BOTH wagers into escrow and persist a pending match.

        Uses conditional spends (UPDATE ... WHERE balance >= wager) on a single
        transaction: if either player can't cover the wager, nothing is taken
        and the match is not created. Once this returns ok, the escrowed sobs
        are out of both players' balances — they can't be spent during the
        animation. Returns (ok, reason, game_id).
        """
        db = await self.sob_repo._db()
        ts = int(time.time())
        game_id = uuid.uuid4().hex
        # lock both players in a stable order
        a, b = sorted((challenger, opponent))
        try:
            async with db.key_lock("sob", guild_id, a):
                async with db.key_lock("sob", guild_id, b):
                    async with db.transaction() as conn:
                        for uid in (challenger, opponent):
                            await self.sob_repo._ensure_user_row(conn, guild_id, uid, ts)
                            before = await self.sob_repo._balance(conn, guild_id, uid)
                            cur = await conn.execute(
                                "UPDATE sob_users SET sobs_received_alltime = sobs_received_alltime - ?, "
                                "updated_at = ? WHERE guild_id = ? AND user_id = ? AND sobs_received_alltime >= ?",
                                (wager, ts, guild_id, uid, wager),
                            )
                            if cur.rowcount == 0:
                                # abort: rolling back the whole transaction returns
                                # any already-debited wager.
                                raise _Insufficient(uid)
                            # keep period rollups in step with the escrow debit
                            from core.time_utils import today_keys
                            day_k, week_k = today_keys()
                            for ptype, pkey in (("day", day_k), ("week", week_k)):
                                await conn.execute(
                                    "UPDATE sob_periods SET sobs_received = MAX(0, sobs_received - ?), "
                                    "updated_at = ? WHERE guild_id = ? AND user_id = ? AND period_type = ? AND period_key = ?",
                                    (wager, ts, guild_id, uid, ptype, pkey),
                                )
                            await ledger.record(
                                conn, guild_id=guild_id, event_type=ledger.EVT_ROULETTE_ESCROW,
                                transaction_id=game_id, subject_id=uid, actor_id=uid,
                                counterparty_id=(opponent if uid == challenger else challenger),
                                delta=-wager, balance_before=before, balance_after=before - wager,
                                game_id=game_id, metadata={"game": game},
                            )
                        await conn.execute(
                            "INSERT INTO game_matches (game_id, guild_id, game, challenger_id, "
                            "opponent_id, wager, challenger_escrow, opponent_escrow, status, created_at, updated_at) "
                            "VALUES (?,?,?,?,?,?,?,?,'pending',?,?)",
                            (game_id, guild_id, game, challenger, opponent, wager, wager, wager, ts, ts),
                        )
        except _Insufficient as exc:
            return False, f"insufficient:{exc.user_id}", None
        return True, "ok", game_id

    async def _get_match(self, conn, game_id: str):
        cur = await conn.execute("SELECT * FROM game_matches WHERE game_id = ?", (game_id,))
        row = await cur.fetchone()
        await cur.close()
        return row

    async def settle_match(self, game_id: str, winner: int) -> dict | None:
        """Resolve a pending escrowed match: the winner gets the whole pot
        (both wagers) minus house tax; the loser gets nothing back. Conserved —
        the pot already left both balances at open_match. Idempotent: a match
        that isn't 'pending' is ignored. Returns a summary or None."""
        db = await self.sob_repo._db()
        ts = int(time.time())
        async with db.key_lock("game", game_id):
            async with db.transaction() as conn:
                m = await self._get_match(conn, game_id)
                if m is None or m["status"] != "pending":
                    return None
                guild_id = int(m["guild_id"])
                challenger = int(m["challenger_id"])
                opponent = int(m["opponent_id"])
                wager = int(m["wager"])
                loser = opponent if winner == challenger else challenger
                pot = int(m["challenger_escrow"]) + int(m["opponent_escrow"])
                tax = int(pot * HOUSE_TAX_PCT / 100)
                net = pot - tax

                await self.sob_repo._ensure_user_row(conn, guild_id, winner, ts)
                before = await self.sob_repo._balance(conn, guild_id, winner)
                bw, aw = await self.sob_repo._apply_delta(
                    conn, guild_id=guild_id, user_id=winner, delta=net, ts=ts,
                )
                await conn.execute(
                    "UPDATE game_matches SET status='settled', updated_at=? WHERE game_id=?",
                    (ts, game_id),
                )
                await ledger.record(
                    conn, guild_id=guild_id, event_type=ledger.EVT_ROULETTE_PAYOUT,
                    transaction_id=game_id, subject_id=winner, actor_id=winner,
                    counterparty_id=loser, delta=net, balance_before=bw, balance_after=aw,
                    game_id=game_id, tax_amount=tax, treasury_amount=tax,
                    metadata={"pot": pot, "wager": wager},
                )

        # log + treasury outside the balance transaction
        await self._log(guild_id, m["game"], challenger, opponent, wager, winner, loser, tax)
        if tax > 0 and self.economy is not None:
            try:
                await self.economy.add_treasury(guild_id, tax, payer_id=loser)
            except Exception:
                pass
        return {"winner": winner, "loser": loser, "wager": wager,
                "pot": pot, "paid": net, "tax": tax, "net": net}

    async def refund_match(self, game_id: str, *, reason: str = "refund") -> bool:
        """Return both escrowed wagers to their owners. Idempotent — only acts
        on a 'pending' match. Used on timeout, decline, error, or restart."""
        db = await self.sob_repo._db()
        ts = int(time.time())
        async with db.key_lock("game", game_id):
            async with db.transaction() as conn:
                m = await self._get_match(conn, game_id)
                if m is None or m["status"] != "pending":
                    return False
                guild_id = int(m["guild_id"])
                for uid, esc in ((int(m["challenger_id"]), int(m["challenger_escrow"])),
                                 (int(m["opponent_id"]), int(m["opponent_escrow"]))):
                    if esc <= 0:
                        continue
                    b, a = await self.sob_repo._apply_delta(
                        conn, guild_id=guild_id, user_id=uid, delta=esc, ts=ts,
                    )
                    await ledger.record(
                        conn, guild_id=guild_id, event_type=ledger.EVT_ROULETTE_REFUND,
                        transaction_id=game_id, subject_id=uid, actor_id=uid,
                        delta=esc, balance_before=b, balance_after=a,
                        game_id=game_id, metadata={"reason": reason},
                    )
                await conn.execute(
                    "UPDATE game_matches SET status='refunded', updated_at=? WHERE game_id=?",
                    (ts, game_id),
                )
        return True

    async def recover_pending(self) -> int:
        """On startup, refund any matches left 'pending' (e.g. the bot crashed
        or restarted mid-animation) so escrowed sobs are never lost. Returns the
        number of matches refunded."""
        db = await self.sob_repo._db()
        rows = await db.fetchall("SELECT game_id FROM game_matches WHERE status='pending'")
        n = 0
        for r in rows:
            try:
                if await self.refund_match(str(r["game_id"]), reason="restart_recovery"):
                    n += 1
            except Exception as e:
                print(f"[Ignio][Games] recover_pending failed for {r['game_id']}: {e}")
        return n

    # ---- legacy settlement (kept for non-escrow callers; not used by roulette) ----
    async def settle(self, guild_id: int, game: str, challenger: int, opponent: int,
                     winner: int, wager: int) -> dict:
        """Direct (non-escrow) settlement: move `wager` from loser to winner,
        minus house tax. Conserved. Retained for compatibility; new games use
        open_match/settle_match for true escrow."""
        loser = opponent if winner == challenger else challenger
        tx = ledger.new_tx_id()
        loser_stats = await self.sob_repo.get_user_stats(guild_id, loser)
        pay = min(wager, int(loser_stats["sobs_alltime"]))
        tax = int(pay * HOUSE_TAX_PCT / 100)
        net = await self.sob_repo.transfer(
            guild_id, loser, winner, pay,
            event_type=ledger.EVT_ROULETTE_PAYOUT, actor_id=winner,
            transaction_id=tx, tax_amount=tax, game_id=game,
        )
        if tax > 0 and self.economy is not None:
            try:
                await self.economy.add_treasury(guild_id, tax, payer_id=loser)
            except Exception:
                pass
        await self._log(guild_id, game, challenger, opponent, wager, winner, loser, tax)
        return {"winner": winner, "loser": loser, "wager": wager,
                "paid": pay, "tax": tax, "net": net}

    async def _log(self, guild_id, game, challenger, opponent, wager, winner, loser, tax):
        db = await self.sob_repo._db()
        try:
            await db.execute(
                "INSERT INTO game_events (guild_id, game, challenger, opponent, wager, "
                "winner, loser, tax, created_at) VALUES (?,?,?,?,?,?,?,?,?)",
                (guild_id, game, challenger, opponent, wager, winner, loser, tax, int(time.time())),
            )
            await db.commit()
        except Exception:
            pass

    async def game_stats(self, guild_id: int, game: str | None = None) -> dict:
        db = await self.sob_repo._db()
        where = "WHERE guild_id=?"
        params = [guild_id]
        if game:
            where += " AND game=?"
            params.append(game)
        row = await db.fetchone(
            f"SELECT COUNT(*) AS n, COALESCE(SUM(wager),0) AS vol, COALESCE(SUM(tax),0) AS tax "
            f"FROM game_events {where}", tuple(params))
        return {"matches": int(row["n"]), "volume": int(row["vol"]), "tax": int(row["tax"])}


class _Insufficient(Exception):
    """Raised inside open_match to roll back when a player can't cover the wager."""
    def __init__(self, user_id: int):
        super().__init__(f"user {user_id} cannot cover wager")
        self.user_id = user_id
