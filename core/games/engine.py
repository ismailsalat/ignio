# core/games/engine.py
"""Reusable PvP games foundation. Roulette is the first game; coinflip,
blackjack, slots, auctions can reuse this.

Responsibilities:
- Track who's currently in a match (so they can't be double-challenged).
- Per-user cooldowns to prevent spam.
- Validate wagers (both players can afford it).
- Settle a match: conserved transfer winner<-loser, optional house tax to treasury.
- Log every match for stats + !admin export.

No sobs are ever minted: the winner gains exactly what the loser loses (minus tax,
which is removed from the pot and sent to the treasury).
"""
from __future__ import annotations

import time


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

    # ---- settlement ----
    async def settle(self, guild_id: int, game: str, challenger: int, opponent: int,
                     winner: int, wager: int) -> dict:
        """Move `wager` from loser to winner, minus house tax to treasury.
        Returns a summary dict. Conserved: no sobs minted."""
        loser = opponent if winner == challenger else challenger

        # re-check the loser can still pay (balances may have shifted)
        loser_stats = await self.sob_repo.get_user_stats(guild_id, loser)
        pay = min(wager, int(loser_stats["sobs_alltime"]))

        tax = int(pay * HOUSE_TAX_PCT / 100)
        net = pay - tax

        # conserved transfer
        await self.sob_repo.adjust_received(guild_id, loser, -pay)
        await self.sob_repo.adjust_received(guild_id, winner, +net)
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
