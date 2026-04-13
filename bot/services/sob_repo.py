# bot/services/sob_repo.py
from __future__ import annotations

import time
from datetime import date
from typing import Any

from bot.services.db_manager import DatabaseManager

# Both emoji names that count as a sob reaction
SOB_EMOJIS: set[str] = {
    "4612win11emojisob",  # <:4612win11emojisob:1493190644221480960>
    "handsob",            # <:handsob:1493198316299747419>
}

DEFAULT_SNITCH_THRESHOLD = 10
SNITCH_EXPIRY_SECONDS    = 7 * 24 * 3600


def _today_keys() -> tuple[int, int]:
    today    = date.today()
    day_key  = today.toordinal()
    iso      = today.isocalendar()
    week_key = iso[0] * 100 + iso[1]
    return day_key, week_key


class SobRepo:
    def __init__(self, db_manager: DatabaseManager):
        self.db_manager = db_manager

    async def _db(self):
        return await self.db_manager.get()

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
    ) -> bool:
        now_ts            = int(time.time())
        day_key, week_key = _today_keys()
        db                = await self._db()

        cur = await db.execute(
            """
            INSERT OR IGNORE INTO sob_reactions
                (guild_id, message_id, reactor_id, target_id, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (guild_id, message_id, reactor_id, target_id, now_ts),
        )
        if cur.rowcount == 0:
            return False

        await db.execute(
            """
            INSERT INTO sob_stats (guild_id, user_id, sobs_received_alltime, sobs_given_alltime, updated_at)
            VALUES (?, ?, 1, 0, ?)
            ON CONFLICT(guild_id, user_id) DO UPDATE SET
                sobs_received_alltime = sobs_received_alltime + 1,
                updated_at = excluded.updated_at
            """,
            (guild_id, target_id, now_ts),
        )
        await db.execute(
            """
            INSERT INTO sob_daily (guild_id, user_id, day_key, sobs_received, updated_at)
            VALUES (?, ?, ?, 1, ?)
            ON CONFLICT(guild_id, user_id, day_key) DO UPDATE SET
                sobs_received = sobs_received + 1,
                updated_at = excluded.updated_at
            """,
            (guild_id, target_id, day_key, now_ts),
        )
        await db.execute(
            """
            INSERT INTO sob_weekly (guild_id, user_id, week_key, sobs_received, updated_at)
            VALUES (?, ?, ?, 1, ?)
            ON CONFLICT(guild_id, user_id, week_key) DO UPDATE SET
                sobs_received = sobs_received + 1,
                updated_at = excluded.updated_at
            """,
            (guild_id, target_id, week_key, now_ts),
        )
        await db.execute(
            """
            INSERT INTO sob_stats (guild_id, user_id, sobs_received_alltime, sobs_given_alltime, updated_at)
            VALUES (?, ?, 0, 1, ?)
            ON CONFLICT(guild_id, user_id) DO UPDATE SET
                sobs_given_alltime = sobs_given_alltime + 1,
                updated_at = excluded.updated_at
            """,
            (guild_id, reactor_id, now_ts),
        )
        await db.commit()

        await self._maybe_grant_snitch_token(
            guild_id=guild_id,
            user_id=target_id,
            snitch_threshold=snitch_threshold,
            now_ts=now_ts,
        )
        return True

    async def remove_sob(
        self,
        *,
        guild_id: int,
        message_id: int,
        reactor_id: int,
    ) -> bool:
        now_ts            = int(time.time())
        day_key, week_key = _today_keys()
        db                = await self._db()

        row = await db.fetchone(
            "SELECT target_id FROM sob_reactions WHERE guild_id = ? AND message_id = ? AND reactor_id = ?",
            (guild_id, message_id, reactor_id),
        )
        if row is None:
            return False

        target_id = int(row["target_id"])

        await db.execute(
            "DELETE FROM sob_reactions WHERE guild_id = ? AND message_id = ? AND reactor_id = ?",
            (guild_id, message_id, reactor_id),
        )
        await db.execute(
            "UPDATE sob_stats SET sobs_received_alltime = MAX(0, sobs_received_alltime - 1), updated_at = ? WHERE guild_id = ? AND user_id = ?",
            (now_ts, guild_id, target_id),
        )
        await db.execute(
            "UPDATE sob_daily SET sobs_received = MAX(0, sobs_received - 1), updated_at = ? WHERE guild_id = ? AND user_id = ? AND day_key = ?",
            (now_ts, guild_id, target_id, day_key),
        )
        await db.execute(
            "UPDATE sob_weekly SET sobs_received = MAX(0, sobs_received - 1), updated_at = ? WHERE guild_id = ? AND user_id = ? AND week_key = ?",
            (now_ts, guild_id, target_id, week_key),
        )
        await db.execute(
            "UPDATE sob_stats SET sobs_given_alltime = MAX(0, sobs_given_alltime - 1), updated_at = ? WHERE guild_id = ? AND user_id = ?",
            (now_ts, guild_id, reactor_id),
        )
        await db.commit()
        return True

    # ------------------------------------------------------------------
    # sob snitch — remove ALL sobs from a message
    # ------------------------------------------------------------------

    async def snitch_message(
        self,
        *,
        guild_id: int,
        message_id: int,
        snitcher_id: int,
        target_id: int,
        now_ts: int | None = None,
    ) -> tuple[bool, str, int]:
        """
        Use a snitch token to wipe all sobs from a message.

        Returns (success, reason, sobs_removed).

        Reasons on failure:
          no_token     — snitcher has no token
          expired      — token expired
          own_message  — can't snitch your own message
          bot_message  — can't snitch a bot's message
          no_sobs      — no sob reactions tracked on this message
          self_snitch  — snitcher is the message author (redundant safety)
        """
        if now_ts is None:
            now_ts = int(time.time())

        # Safety: can't snitch your own message
        if snitcher_id == target_id:
            return False, "own_message", 0

        db = await self._db()

        # ── token checks ──────────────────────────────────────────────
        snitch_row = await self.get_snitch_row(guild_id, snitcher_id)

        if snitch_row is None or snitch_row["token_available"] == 0:
            return False, "no_token", 0

        if (now_ts - snitch_row["token_granted_at"]) > SNITCH_EXPIRY_SECONDS:
            await db.execute(
                "UPDATE sob_snitch SET token_available = 0, updated_at = ? WHERE guild_id = ? AND user_id = ?",
                (now_ts, guild_id, snitcher_id),
            )
            await db.commit()
            return False, "expired", 0

        # ── find all sob reactions on this message ────────────────────
        reaction_rows = await db.fetchall(
            "SELECT reactor_id FROM sob_reactions WHERE guild_id = ? AND message_id = ?",
            (guild_id, message_id),
        )

        if not reaction_rows:
            return False, "no_sobs", 0

        sob_count  = len(reaction_rows)
        day_key, week_key = _today_keys()

        # ── decrement reactor "given" counts (floor at 0) ─────────────
        for r in reaction_rows:
            await db.execute(
                "UPDATE sob_stats SET sobs_given_alltime = MAX(0, sobs_given_alltime - 1), updated_at = ? WHERE guild_id = ? AND user_id = ?",
                (now_ts, guild_id, int(r["reactor_id"])),
            )

        # ── decrement target "received" counts (floor at 0) ───────────
        # Decrement by sob_count but never below 0 — done individually
        # to avoid a single bulk subtract going negative
        for _ in range(sob_count):
            await db.execute(
                "UPDATE sob_stats SET sobs_received_alltime = MAX(0, sobs_received_alltime - 1), updated_at = ? WHERE guild_id = ? AND user_id = ?",
                (now_ts, guild_id, target_id),
            )
        await db.execute(
            "UPDATE sob_daily SET sobs_received = MAX(0, sobs_received - ?) , updated_at = ? WHERE guild_id = ? AND user_id = ? AND day_key = ?",
            (sob_count, now_ts, guild_id, target_id, day_key),
        )
        await db.execute(
            "UPDATE sob_weekly SET sobs_received = MAX(0, sobs_received - ?), updated_at = ? WHERE guild_id = ? AND user_id = ? AND week_key = ?",
            (sob_count, now_ts, guild_id, target_id, week_key),
        )

        # ── delete all sob_reactions rows for this message ────────────
        await db.execute(
            "DELETE FROM sob_reactions WHERE guild_id = ? AND message_id = ?",
            (guild_id, message_id),
        )

        # ── consume token, increment total_snitches ───────────────────
        await db.execute(
            "UPDATE sob_snitch SET token_available = 0, total_snitches = total_snitches + 1, updated_at = ? WHERE guild_id = ? AND user_id = ?",
            (now_ts, guild_id, snitcher_id),
        )

        await db.commit()
        return True, "ok", sob_count

    # ------------------------------------------------------------------
    # snitch token logic
    # ------------------------------------------------------------------

    async def _maybe_grant_snitch_token(
        self,
        *,
        guild_id: int,
        user_id: int,
        snitch_threshold: int,
        now_ts: int,
    ) -> None:
        db = await self._db()

        stats_row = await db.fetchone(
            "SELECT sobs_received_alltime FROM sob_stats WHERE guild_id = ? AND user_id = ?",
            (guild_id, user_id),
        )
        if stats_row is None:
            return

        alltime = int(stats_row["sobs_received_alltime"])

        snitch_row = await db.fetchone(
            "SELECT token_available, sobs_at_last_grant FROM sob_snitch WHERE guild_id = ? AND user_id = ?",
            (guild_id, user_id),
        )

        token_available    = int(snitch_row["token_available"])    if snitch_row else 0
        sobs_at_last_grant = int(snitch_row["sobs_at_last_grant"]) if snitch_row else 0

        if token_available == 1:
            return

        next_grant = snitch_threshold if sobs_at_last_grant == 0 else sobs_at_last_grant + snitch_threshold
        if alltime < next_grant:
            return

        await db.execute(
            """
            INSERT INTO sob_snitch
                (guild_id, user_id, token_available, sobs_at_last_grant, token_granted_at, total_snitches, updated_at)
            VALUES (?, ?, 1, ?, ?, 0, ?)
            ON CONFLICT(guild_id, user_id) DO UPDATE SET
                token_available    = 1,
                sobs_at_last_grant = excluded.sobs_at_last_grant,
                token_granted_at   = excluded.token_granted_at,
                updated_at         = excluded.updated_at
            """,
            (guild_id, user_id, alltime, now_ts, now_ts),
        )
        await db.commit()

    async def get_snitch_row(self, guild_id: int, user_id: int) -> dict[str, Any] | None:
        db  = await self._db()
        row = await db.fetchone(
            "SELECT token_available, sobs_at_last_grant, token_granted_at, total_snitches FROM sob_snitch WHERE guild_id = ? AND user_id = ?",
            (guild_id, user_id),
        )
        if row is None:
            return None
        return {
            "token_available":    int(row["token_available"]),
            "sobs_at_last_grant": int(row["sobs_at_last_grant"]),
            "token_granted_at":   int(row["token_granted_at"]),
            "total_snitches":     int(row["total_snitches"]),
        }

    async def get_snitch_threshold(self, guild_id: int) -> int:
        db  = await self._db()
        row = await db.fetchone(
            "SELECT value FROM guild_settings WHERE guild_id = ? AND key = 'sob_snitch_threshold'",
            (guild_id,),
        )
        if row is None:
            return DEFAULT_SNITCH_THRESHOLD
        try:
            return max(1, int(row["value"]))
        except (ValueError, TypeError):
            return DEFAULT_SNITCH_THRESHOLD

    # ------------------------------------------------------------------
    # stat fetchers
    # ------------------------------------------------------------------

    async def get_user_stats(self, guild_id: int, user_id: int) -> dict[str, int]:
        day_key, week_key = _today_keys()
        db = await self._db()

        alltime_row = await db.fetchone(
            "SELECT sobs_received_alltime, sobs_given_alltime FROM sob_stats WHERE guild_id = ? AND user_id = ?",
            (guild_id, user_id),
        )
        daily_row = await db.fetchone(
            "SELECT sobs_received FROM sob_daily WHERE guild_id = ? AND user_id = ? AND day_key = ?",
            (guild_id, user_id, day_key),
        )
        weekly_row = await db.fetchone(
            "SELECT sobs_received FROM sob_weekly WHERE guild_id = ? AND user_id = ? AND week_key = ?",
            (guild_id, user_id, week_key),
        )
        return {
            "sobs_today":   int(daily_row["sobs_received"])           if daily_row   else 0,
            "sobs_week":    int(weekly_row["sobs_received"])          if weekly_row  else 0,
            "sobs_alltime": int(alltime_row["sobs_received_alltime"]) if alltime_row else 0,
            "sobs_given":   int(alltime_row["sobs_given_alltime"])    if alltime_row else 0,
        }

    async def get_daily_leader(self, guild_id: int) -> dict[str, Any] | None:
        day_key, _ = _today_keys()
        db  = await self._db()
        row = await db.fetchone(
            "SELECT user_id, sobs_received FROM sob_daily WHERE guild_id = ? AND day_key = ? ORDER BY sobs_received DESC, user_id ASC LIMIT 1",
            (guild_id, day_key),
        )
        if row is None or int(row["sobs_received"]) == 0:
            return None
        return {"user_id": int(row["user_id"]), "count": int(row["sobs_received"])}

    async def get_weekly_leader(self, guild_id: int) -> dict[str, Any] | None:
        _, week_key = _today_keys()
        db  = await self._db()
        row = await db.fetchone(
            "SELECT user_id, sobs_received FROM sob_weekly WHERE guild_id = ? AND week_key = ? ORDER BY sobs_received DESC, user_id ASC LIMIT 1",
            (guild_id, week_key),
        )
        if row is None or int(row["sobs_received"]) == 0:
            return None
        return {"user_id": int(row["user_id"]), "count": int(row["sobs_received"])}

    async def get_alltime_leader(self, guild_id: int) -> dict[str, Any] | None:
        db  = await self._db()
        row = await db.fetchone(
            "SELECT user_id, sobs_received_alltime FROM sob_stats WHERE guild_id = ? ORDER BY sobs_received_alltime DESC, user_id ASC LIMIT 1",
            (guild_id,),
        )
        if row is None or int(row["sobs_received_alltime"]) == 0:
            return None
        return {"user_id": int(row["user_id"]), "count": int(row["sobs_received_alltime"])}

    async def get_top_giver(self, guild_id: int) -> dict[str, Any] | None:
        db  = await self._db()
        row = await db.fetchone(
            "SELECT user_id, sobs_given_alltime FROM sob_stats WHERE guild_id = ? ORDER BY sobs_given_alltime DESC, user_id ASC LIMIT 1",
            (guild_id,),
        )
        if row is None or int(row["sobs_given_alltime"]) == 0:
            return None
        return {"user_id": int(row["user_id"]), "count": int(row["sobs_given_alltime"])}

    async def get_top_snitch(self, guild_id: int) -> dict[str, Any] | None:
        db  = await self._db()
        row = await db.fetchone(
            "SELECT user_id, total_snitches FROM sob_snitch WHERE guild_id = ? ORDER BY total_snitches DESC, user_id ASC LIMIT 1",
            (guild_id,),
        )
        if row is None or int(row["total_snitches"]) == 0:
            return None
        return {"user_id": int(row["user_id"]), "count": int(row["total_snitches"])}

    async def get_user_daily_rank(self, guild_id: int, user_id: int) -> int:
        day_key, _ = _today_keys()
        db  = await self._db()
        row = await db.fetchone(
            """
            SELECT COUNT(*) + 1 AS rank FROM sob_daily
            WHERE guild_id = ? AND day_key = ?
              AND sobs_received > (
                  SELECT COALESCE(sobs_received, 0) FROM sob_daily
                  WHERE guild_id = ? AND user_id = ? AND day_key = ?
              )
            """,
            (guild_id, day_key, guild_id, user_id, day_key),
        )
        return int(row["rank"]) if row else 1

    async def get_user_weekly_rank(self, guild_id: int, user_id: int) -> int:
        _, week_key = _today_keys()
        db  = await self._db()
        row = await db.fetchone(
            """
            SELECT COUNT(*) + 1 AS rank FROM sob_weekly
            WHERE guild_id = ? AND week_key = ?
              AND sobs_received > (
                  SELECT COALESCE(sobs_received, 0) FROM sob_weekly
                  WHERE guild_id = ? AND user_id = ? AND week_key = ?
              )
            """,
            (guild_id, week_key, guild_id, user_id, week_key),
        )
        return int(row["rank"]) if row else 1

    async def get_user_alltime_rank(self, guild_id: int, user_id: int) -> int:
        db  = await self._db()
        row = await db.fetchone(
            """
            SELECT COUNT(*) + 1 AS rank FROM sob_stats
            WHERE guild_id = ?
              AND sobs_received_alltime > (
                  SELECT COALESCE(sobs_received_alltime, 0) FROM sob_stats
                  WHERE guild_id = ? AND user_id = ?
              )
            """,
            (guild_id, guild_id, user_id),
        )
        return int(row["rank"]) if row else 1