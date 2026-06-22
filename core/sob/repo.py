# core/sob/repo.py
from __future__ import annotations

from typing import Any

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
    """All sob database access. Tables: sob_users, sob_events, sob_periods."""

    def __init__(self, db_manager: DatabaseManager):
        self.db_manager = db_manager

    async def _db(self):
        return await self.db_manager.get()

    # ------------------------------------------------------------------
    # internal upserts
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
        ts = now_ts()
        day_k, week_k = today_keys()
        db = await self._db()

        cur = await db.execute(
            """
            INSERT OR IGNORE INTO sob_events
                (guild_id, message_id, reactor_id, target_id, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (guild_id, message_id, reactor_id, target_id, ts),
        )
        if cur.rowcount == 0:
            return False  # already reacted

        # target: +1 received (alltime + day + week)
        await self._ensure_user_row(db, guild_id, target_id, ts)
        await db.execute(
            """
            UPDATE sob_users
            SET sobs_received_alltime = sobs_received_alltime + 1, updated_at = ?
            WHERE guild_id = ? AND user_id = ?
            """,
            (ts, guild_id, target_id),
        )
        await db.execute(
            """
            INSERT INTO sob_periods (guild_id, user_id, period_type, period_key, sobs_received, updated_at)
            VALUES (?, ?, 'day', ?, 1, ?)
            ON CONFLICT(guild_id, user_id, period_type, period_key) DO UPDATE SET
                sobs_received = sobs_received + 1, updated_at = excluded.updated_at
            """,
            (guild_id, target_id, day_k, ts),
        )
        await db.execute(
            """
            INSERT INTO sob_periods (guild_id, user_id, period_type, period_key, sobs_received, updated_at)
            VALUES (?, ?, 'week', ?, 1, ?)
            ON CONFLICT(guild_id, user_id, period_type, period_key) DO UPDATE SET
                sobs_received = sobs_received + 1, updated_at = excluded.updated_at
            """,
            (guild_id, target_id, week_k, ts),
        )

        # reactor: +1 given
        await self._ensure_user_row(db, guild_id, reactor_id, ts)
        await db.execute(
            """
            UPDATE sob_users
            SET sobs_given_alltime = sobs_given_alltime + 1, updated_at = ?
            WHERE guild_id = ? AND user_id = ?
            """,
            (ts, guild_id, reactor_id),
        )
        await db.commit()

        await self._maybe_grant_snitch_token(
            guild_id=guild_id, user_id=target_id,
            snitch_threshold=snitch_threshold, ts=ts,
        )
        return True

    async def remove_sob(self, *, guild_id: int, message_id: int, reactor_id: int) -> bool:
        ts = now_ts()
        day_k, week_k = today_keys()
        db = await self._db()

        row = await db.fetchone(
            "SELECT target_id FROM sob_events WHERE guild_id = ? AND message_id = ? AND reactor_id = ?",
            (guild_id, message_id, reactor_id),
        )
        if row is None:
            return False

        target_id = int(row["target_id"])

        await db.execute(
            "DELETE FROM sob_events WHERE guild_id = ? AND message_id = ? AND reactor_id = ?",
            (guild_id, message_id, reactor_id),
        )
        await db.execute(
            "UPDATE sob_users SET sobs_received_alltime = MAX(0, sobs_received_alltime - 1), updated_at = ? WHERE guild_id = ? AND user_id = ?",
            (ts, guild_id, target_id),
        )
        await db.execute(
            "UPDATE sob_periods SET sobs_received = MAX(0, sobs_received - 1), updated_at = ? WHERE guild_id = ? AND user_id = ? AND period_type = 'day' AND period_key = ?",
            (ts, guild_id, target_id, day_k),
        )
        await db.execute(
            "UPDATE sob_periods SET sobs_received = MAX(0, sobs_received - 1), updated_at = ? WHERE guild_id = ? AND user_id = ? AND period_type = 'week' AND period_key = ?",
            (ts, guild_id, target_id, week_k),
        )
        await db.execute(
            "UPDATE sob_users SET sobs_given_alltime = MAX(0, sobs_given_alltime - 1), updated_at = ? WHERE guild_id = ? AND user_id = ?",
            (ts, guild_id, reactor_id),
        )
        await db.commit()
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
        Returns (success, reason, sobs_removed).
        Failure reasons: no_token, expired, own_message, no_sobs.
        """
        ts = now_ts() if now is None else now

        if snitcher_id == target_id:
            return False, "own_message", 0

        db = await self._db()
        snitch = await self.get_snitch_row(guild_id, snitcher_id)

        if snitch is None or snitch["token_available"] == 0:
            return False, "no_token", 0

        if (ts - snitch["token_granted_at"]) > SNITCH_EXPIRY_SECONDS:
            await db.execute(
                "UPDATE sob_users SET token_available = 0, updated_at = ? WHERE guild_id = ? AND user_id = ?",
                (ts, guild_id, snitcher_id),
            )
            await db.commit()
            return False, "expired", 0

        reaction_rows = await db.fetchall(
            "SELECT reactor_id FROM sob_events WHERE guild_id = ? AND message_id = ?",
            (guild_id, message_id),
        )
        if not reaction_rows:
            return False, "no_sobs", 0

        sob_count = len(reaction_rows)
        day_k, week_k = today_keys()

        # reactors lose 1 "given" each
        for r in reaction_rows:
            await db.execute(
                "UPDATE sob_users SET sobs_given_alltime = MAX(0, sobs_given_alltime - 1), updated_at = ? WHERE guild_id = ? AND user_id = ?",
                (ts, guild_id, int(r["reactor_id"])),
            )

        # target loses sob_count "received" (floored at 0)
        await db.execute(
            "UPDATE sob_users SET sobs_received_alltime = MAX(0, sobs_received_alltime - ?), updated_at = ? WHERE guild_id = ? AND user_id = ?",
            (sob_count, ts, guild_id, target_id),
        )
        await db.execute(
            "UPDATE sob_periods SET sobs_received = MAX(0, sobs_received - ?), updated_at = ? WHERE guild_id = ? AND user_id = ? AND period_type = 'day' AND period_key = ?",
            (sob_count, ts, guild_id, target_id, day_k),
        )
        await db.execute(
            "UPDATE sob_periods SET sobs_received = MAX(0, sobs_received - ?), updated_at = ? WHERE guild_id = ? AND user_id = ? AND period_type = 'week' AND period_key = ?",
            (sob_count, ts, guild_id, target_id, week_k),
        )

        await db.execute(
            "DELETE FROM sob_events WHERE guild_id = ? AND message_id = ?",
            (guild_id, message_id),
        )
        await db.execute(
            "UPDATE sob_users SET token_available = 0, total_snitches = total_snitches + 1, updated_at = ? WHERE guild_id = ? AND user_id = ?",
            (ts, guild_id, snitcher_id),
        )
        await db.commit()
        return True, "ok", sob_count

    # ------------------------------------------------------------------
    # snitch token logic
    # ------------------------------------------------------------------

    async def _maybe_grant_snitch_token(
        self, *, guild_id: int, user_id: int, snitch_threshold: int, ts: int
    ) -> None:
        db = await self._db()
        row = await db.fetchone(
            "SELECT sobs_received_alltime, token_available, sobs_at_last_grant FROM sob_users WHERE guild_id = ? AND user_id = ?",
            (guild_id, user_id),
        )
        if row is None:
            return

        alltime = int(row["sobs_received_alltime"])
        if int(row["token_available"]) == 1:
            return

        sobs_at_last = int(row["sobs_at_last_grant"])
        next_grant = snitch_threshold if sobs_at_last == 0 else sobs_at_last + snitch_threshold
        if alltime < next_grant:
            return

        await db.execute(
            """
            UPDATE sob_users
            SET token_available = 1, sobs_at_last_grant = ?, token_granted_at = ?, updated_at = ?
            WHERE guild_id = ? AND user_id = ?
            """,
            (alltime, ts, ts, guild_id, user_id),
        )
        await db.commit()

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

    async def adjust_received(self, guild_id: int, user_id: int, delta: int) -> int:
        """Add (or subtract, if negative) sobs to a user's all-time + today + week.
        Returns the new all-time total. Floors every counter at 0."""
        ts = now_ts()
        day_k, week_k = today_keys()
        db = await self._db()
        await self._ensure_user_row(db, guild_id, user_id, ts)

        await db.execute(
            "UPDATE sob_users SET sobs_received_alltime = MAX(0, sobs_received_alltime + ?), updated_at = ? WHERE guild_id = ? AND user_id = ?",
            (int(delta), ts, guild_id, user_id),
        )
        for ptype, pkey in (("day", day_k), ("week", week_k)):
            await db.execute(
                """
                INSERT INTO sob_periods (guild_id, user_id, period_type, period_key, sobs_received, updated_at)
                VALUES (?, ?, ?, ?, MAX(0, ?), ?)
                ON CONFLICT(guild_id, user_id, period_type, period_key) DO UPDATE SET
                    sobs_received = MAX(0, sobs_received + ?), updated_at = excluded.updated_at
                """,
                (guild_id, user_id, ptype, pkey, int(delta), ts, int(delta)),
            )
        await db.commit()
        row = await db.fetchone(
            "SELECT sobs_received_alltime FROM sob_users WHERE guild_id = ? AND user_id = ?",
            (guild_id, user_id),
        )
        return int(row["sobs_received_alltime"]) if row else 0

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
        """Zero out a single user's sob data in this guild (received/given/periods/token)."""
        ts = now_ts()
        db = await self._db()
        await db.begin()
        try:
            await db.execute(
                "UPDATE sob_users SET sobs_received_alltime = 0, sobs_given_alltime = 0, token_available = 0, total_snitches = 0, sobs_at_last_grant = 0, token_granted_at = 0, updated_at = ? WHERE guild_id = ? AND user_id = ?",
                (ts, guild_id, user_id),
            )
            await db.execute(
                "DELETE FROM sob_periods WHERE guild_id = ? AND user_id = ?",
                (guild_id, user_id),
            )
            await db.commit()
        except Exception:
            await db.rollback()
            raise

    async def recount(self, guild_id: int) -> dict[str, int]:
        """Rebuild received totals + period rollups from the raw sob_events log.
        'given' counts and snitch state are left as-is (events don't carry dates,
        so daily/weekly are rebuilt as all-into-current is NOT done — instead we
        recompute all-time received from events and clear stale period rows).
        Returns a small summary."""
        ts = now_ts()
        db = await self._db()
        await db.begin()
        try:
            # recompute all-time received per user from events
            rows = await db.fetchall(
                "SELECT target_id, COUNT(*) AS c FROM sob_events WHERE guild_id = ? GROUP BY target_id",
                (guild_id,),
            )
            counts = {int(r["target_id"]): int(r["c"]) for r in rows}

            # zero received for everyone in this guild, then set from events
            await db.execute(
                "UPDATE sob_users SET sobs_received_alltime = 0, updated_at = ? WHERE guild_id = ?",
                (ts, guild_id),
            )
            for uid, c in counts.items():
                await self._ensure_user_row(db, guild_id, uid, ts)
                await db.execute(
                    "UPDATE sob_users SET sobs_received_alltime = ?, updated_at = ? WHERE guild_id = ? AND user_id = ?",
                    (c, ts, guild_id, uid),
                )
            await db.commit()
            return {"users_recounted": len(counts), "events_scanned": sum(counts.values())}
        except Exception:
            await db.rollback()
            raise

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
