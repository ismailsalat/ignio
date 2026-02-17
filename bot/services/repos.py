# bot/services/repos.py
from __future__ import annotations
from datetime import date

class Repos:
    def __init__(self, db_manager):
        self.db_manager = db_manager
        self._cfg_cache: dict[int, dict[str, int | str]] = {}

    # ---------- INTERNAL ----------

    def _normalize_pair(self, a: int, b: int) -> tuple[int, int]:
        return (a, b) if a < b else (b, a)

    async def _conn(self, guild_id: int):
        db = await self.db_manager.get(guild_id)
        if not db.conn:
            raise RuntimeError("Database not connected")
        return db.conn

    def _cfg_defaults(self, settings) -> dict[str, int | str]:
        return {
            "default_tz": settings.default_tz,
            "grace_hour_local": settings.grace_hour_local,
            "min_overlap_seconds": settings.min_overlap_seconds,
            "tick_seconds": settings.tick_seconds,
            "disconnect_buffer_seconds": settings.disconnect_buffer_seconds,
            "progress_bar_width": settings.progress_bar_width,
            "ignore_afk_channels": 1 if getattr(settings, "ignore_afk_channels", False) else 0,
        }

    async def invalidate_config_cache(self, guild_id: int) -> None:
        self._cfg_cache.pop(guild_id, None)

    async def get_effective_config(self, guild_id: int, settings) -> dict[str, int | str]:
        if guild_id in self._cfg_cache:
            merged = dict(self._cfg_cache[guild_id])
            for k, v in self._cfg_defaults(settings).items():
                merged.setdefault(k, v)
            return merged

        conn = await self._conn(guild_id)
        cur = await conn.execute("SELECT key, value FROM guild_settings")
        rows = await cur.fetchall()

        raw: dict[str, str] = {k: v for (k, v) in rows}
        merged = self._cfg_defaults(settings)

        for k, v in raw.items():
            if k in ("min_overlap_seconds", "tick_seconds", "disconnect_buffer_seconds", "grace_hour_local", "progress_bar_width", "ignore_afk_channels"):
                try:
                    merged[k] = int(v)
                except ValueError:
                    pass
            else:
                merged[k] = v

        self._cfg_cache[guild_id] = dict(merged)
        return merged

    async def set_config_int(self, guild_id: int, key: str, value: int, now_ts: int) -> None:
        conn = await self._conn(guild_id)
        await conn.execute(
            """
            INSERT INTO guild_settings(key, value, updated_at)
            VALUES(?, ?, ?)
            ON CONFLICT(key)
            DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at
            """,
            (key, str(int(value)), now_ts),
        )
        await conn.commit()
        await self.invalidate_config_cache(guild_id)

    async def set_config_str(self, guild_id: int, key: str, value: str, now_ts: int) -> None:
        conn = await self._conn(guild_id)
        await conn.execute(
            """
            INSERT INTO guild_settings(key, value, updated_at)
            VALUES(?, ?, ?)
            ON CONFLICT(key)
            DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at
            """,
            (key, value, now_ts),
        )
        await conn.commit()
        await self.invalidate_config_cache(guild_id)

    # ---------- DUO ----------

    async def get_duo_id(self, guild_id: int, user_a: int, user_b: int) -> int | None:
        """
        Return duo_id if duo exists; DO NOT create.
        (DB is per-guild, so no guild_id column needed.)
        """
        if user_a == user_b:
            return None

        conn = await self._conn(guild_id)
        u1, u2 = self._normalize_pair(int(user_a), int(user_b))

        cur = await conn.execute(
            """
            SELECT duo_id
            FROM duos
            WHERE user1_id=? AND user2_id=?
            """,
            (u1, u2),
        )
        row = await cur.fetchone()
        return int(row[0]) if row else None

    async def get_or_create_duo(self, guild_id: int, user_a: int, user_b: int, now_ts: int) -> int:
        if user_a == user_b:
            raise ValueError("Cannot create duo with same user")

        conn = await self._conn(guild_id)
        u1, u2 = self._normalize_pair(user_a, user_b)

        await conn.execute(
            """
            INSERT OR IGNORE INTO duos(user1_id, user2_id, created_at)
            VALUES (?, ?, ?)
            """,
            (u1, u2, now_ts),
        )
        await conn.commit()

        cur = await conn.execute(
            """
            SELECT duo_id
            FROM duos
            WHERE user1_id=? AND user2_id=?
            """,
            (u1, u2),
        )
        row = await cur.fetchone()
        return int(row[0])

    async def get_duo_users(self, guild_id: int, duo_id: int) -> tuple[int, int] | None:
        conn = await self._conn(guild_id)
        cur = await conn.execute(
            "SELECT user1_id, user2_id FROM duos WHERE duo_id=?",
            (duo_id,),
        )
        row = await cur.fetchone()
        if not row:
            return None
        return int(row[0]), int(row[1])

    # ---------- DAILY PROGRESS ----------

    async def add_duo_daily_seconds(self, guild_id: int, duo_id: int, day_key: int, seconds: int, now_ts: int) -> int:
        conn = await self._conn(guild_id)
        await conn.execute(
            """
            INSERT INTO duo_daily(duo_id, day_key, overlap_seconds, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(duo_id, day_key)
            DO UPDATE SET
                overlap_seconds = overlap_seconds + excluded.overlap_seconds,
                updated_at = excluded.updated_at
            """,
            (duo_id, day_key, seconds, now_ts),
        )
        await conn.commit()

        cur = await conn.execute(
            "SELECT overlap_seconds FROM duo_daily WHERE duo_id=? AND day_key=?",
            (duo_id, day_key),
        )
        row = await cur.fetchone()
        return int(row[0]) if row else 0

    async def get_duo_day_map(self, guild_id: int, duo_id: int, start_day_key: int, end_day_key: int) -> dict[int, int]:
        conn = await self._conn(guild_id)
        cur = await conn.execute(
            """
            SELECT day_key, overlap_seconds
            FROM duo_daily
            WHERE duo_id=? AND day_key BETWEEN ? AND ?
            """,
            (duo_id, start_day_key, end_day_key),
        )
        rows = await cur.fetchall()
        return {int(dk): int(secs) for (dk, secs) in rows}

    async def get_connection_score_seconds(self, guild_id: int, duo_id: int) -> int:
        conn = await self._conn(guild_id)
        cur = await conn.execute(
            "SELECT COALESCE(SUM(overlap_seconds), 0) FROM duo_daily WHERE duo_id=?",
            (duo_id,),
        )
        row = await cur.fetchone()
        return int(row[0]) if row else 0

    # ---------- STREAK ----------

    async def get_streak_row(self, guild_id: int, duo_id: int) -> tuple[int, int, int]:
        conn = await self._conn(guild_id)
        cur = await conn.execute(
            """
            SELECT current_streak, longest_streak, last_completed_day_key
            FROM duo_streaks
            WHERE duo_id=?
            """,
            (duo_id,),
        )
        row = await cur.fetchone()
        if not row:
            return 0, 0, -1
        return int(row[0]), int(row[1]), int(row[2])

    async def save_streak_row(
        self,
        guild_id: int,
        duo_id: int,
        current_streak: int,
        longest_streak: int,
        last_completed_day_key: int,
        now_ts: int,
    ) -> None:
        conn = await self._conn(guild_id)
        await conn.execute(
            """
            INSERT INTO duo_streaks(
                duo_id, current_streak, longest_streak, last_completed_day_key, updated_at
            )
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(duo_id)
            DO UPDATE SET
                current_streak=excluded.current_streak,
                longest_streak=excluded.longest_streak,
                last_completed_day_key=excluded.last_completed_day_key,
                updated_at=excluded.updated_at
            """,
            (duo_id, current_streak, longest_streak, last_completed_day_key, now_ts),
        )
        await conn.commit()

    # ---------- LEADERBOARDS ----------

    async def top_by_current_streak(self, guild_id: int, limit: int = 10):
        conn = await self._conn(guild_id)
        cur = await conn.execute(
            """
            SELECT d.duo_id, s.current_streak
            FROM duo_streaks s
            JOIN duos d ON d.duo_id = s.duo_id
            ORDER BY s.current_streak DESC, s.longest_streak DESC, d.duo_id ASC
            LIMIT ?
            """,
            (limit,),
        )
        return [(int(duo_id), int(val)) for (duo_id, val) in await cur.fetchall()]

    async def top_by_best_streak(self, guild_id: int, limit: int = 10):
        conn = await self._conn(guild_id)
        cur = await conn.execute(
            """
            SELECT d.duo_id, s.longest_streak
            FROM duo_streaks s
            JOIN duos d ON d.duo_id = s.duo_id
            ORDER BY s.longest_streak DESC, s.current_streak DESC, d.duo_id ASC
            LIMIT ?
            """,
            (limit,),
        )
        return [(int(duo_id), int(val)) for (duo_id, val) in await cur.fetchall()]

    async def top_by_connection_score(self, guild_id: int, limit: int = 10):
        conn = await self._conn(guild_id)
        cur = await conn.execute(
            """
            SELECT d.duo_id, COALESCE(SUM(dd.overlap_seconds), 0) AS cs
            FROM duos d
            LEFT JOIN duo_daily dd ON dd.duo_id = d.duo_id
            GROUP BY d.duo_id
            ORDER BY cs DESC, d.duo_id ASC
            LIMIT ?
            """,
            (limit,),
        )
        return [(int(duo_id), int(cs)) for (duo_id, cs) in await cur.fetchall()]

    # ---------- ADMIN HELPERS ----------

    async def raw_conn(self, guild_id: int):
        return await self._conn(guild_id)
