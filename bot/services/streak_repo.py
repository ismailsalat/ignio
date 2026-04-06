# bot/services/streak_repo.py
from __future__ import annotations

import time
from hashlib import sha256
from typing import Any

from bot.services.db_manager import DatabaseManager


class StreakRepo:
    def __init__(self, db_manager: DatabaseManager):
        self.db_manager = db_manager
        self._cfg_cache: dict[int, dict[str, int | str]] = {}

    async def _db(self):
        return await self.db_manager.get()

    # -------------------------
    # internal helpers
    # -------------------------

    def _normalize_members(self, member_ids: list[int] | tuple[int, ...]) -> list[int]:
        ids = sorted({int(x) for x in member_ids})
        if not ids:
            raise ValueError("Members cannot be empty")
        return ids

    def _build_member_hash(self, member_ids: list[int] | tuple[int, ...]) -> str:
        ids = self._normalize_members(member_ids)
        raw = ",".join(str(x) for x in ids)
        return sha256(raw.encode("utf-8")).hexdigest()

    def _default_required_count(self, size: int) -> int:
        if size == 2:
            return 2
        if size == 3:
            return 3
        if size == 4:
            return 3
        if size == 5:
            return 4
        raise ValueError("Size must be between 2 and 5")

    async def _ensure_guild_exists(self, guild_id: int, now_ts: int) -> None:
        db = await self._db()
        await db.execute(
            """
            INSERT INTO guilds (guild_id, name, created_at, updated_at)
            VALUES (?, NULL, ?, ?)
            ON CONFLICT(guild_id)
            DO UPDATE SET updated_at = excluded.updated_at
            """,
            (guild_id, now_ts, now_ts),
        )

    async def _ensure_users_exist(self, user_ids: list[int], now_ts: int) -> None:
        if not user_ids:
            return

        db = await self._db()
        params = [(int(user_id), now_ts, now_ts) for user_id in user_ids]
        await db.executemany(
            """
            INSERT INTO users (user_id, created_at, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(user_id)
            DO UPDATE SET updated_at = excluded.updated_at
            """,
            params,
        )

    async def _insert_members(self, streak_id: int, user_ids: list[int], now_ts: int) -> None:
        db = await self._db()
        params = [(streak_id, int(user_id), now_ts) for user_id in user_ids]
        await db.executemany(
            """
            INSERT OR IGNORE INTO streak_members (streak_id, user_id, joined_at)
            VALUES (?, ?, ?)
            """,
            params,
        )

    async def _create_empty_state(self, streak_id: int, guild_id: int, now_ts: int) -> None:
        db = await self._db()
        await db.execute(
            """
            INSERT OR IGNORE INTO streak_state (
                streak_id,
                guild_id,
                current_streak,
                longest_streak,
                total_completed_days,
                last_completed_day_key,
                updated_at
            )
            VALUES (?, ?, 0, 0, 0, -1, ?)
            """,
            (streak_id, guild_id, now_ts),
        )

    # -------------------------
    # guild config
    # -------------------------

    async def invalidate_config_cache(self, guild_id: int) -> None:
        self._cfg_cache.pop(guild_id, None)

    async def get_effective_config(self, guild_id: int, settings) -> dict[str, int | str]:
        if guild_id in self._cfg_cache:
            return dict(self._cfg_cache[guild_id])

        db = await self._db()

        defaults: dict[str, int | str] = {
            "default_tz": settings.default_tz,
            "grace_hour_local": settings.grace_hour_local,
            "min_overlap_seconds": settings.min_overlap_seconds,
            "tick_seconds": settings.tick_seconds,
            "disconnect_buffer_seconds": settings.disconnect_buffer_seconds,
            "daily_cap_seconds": getattr(settings, "daily_cap_seconds", 0),
            "progress_bar_width": settings.progress_bar_width,
            "ignore_afk_channels": 1 if getattr(settings, "ignore_afk_channels", False) else 0,
            "privacy_default_private": 1 if getattr(settings, "privacy_default_private", False) else 0,
            "privacy_admin_can_view": 1 if getattr(settings, "privacy_admin_can_view", True) else 0,
            "dm_reminders_enabled": 1 if getattr(settings, "dm_reminders_enabled", True) else 0,
            "dm_streak_end_enabled": 1 if getattr(settings, "dm_streak_end_enabled", True) else 0,
            "dm_streak_end_ice_enabled": 1 if getattr(settings, "dm_streak_end_ice_enabled", True) else 0,
            "dm_streak_end_restore_enabled": 1 if getattr(settings, "dm_streak_end_restore_enabled", True) else 0,
            "heatmap_met_emoji": getattr(settings, "heatmap_met_emoji", "🟥"),
            "heatmap_empty_emoji": getattr(settings, "heatmap_empty_emoji", "⬜"),
        }

        rows = await db.fetchall(
            """
            SELECT key, value
            FROM guild_settings
            WHERE guild_id = ?
            """,
            (guild_id,),
        )

        merged = dict(defaults)

        int_keys = {
            "grace_hour_local",
            "min_overlap_seconds",
            "tick_seconds",
            "disconnect_buffer_seconds",
            "daily_cap_seconds",
            "progress_bar_width",
            "ignore_afk_channels",
            "privacy_default_private",
            "privacy_admin_can_view",
            "dm_reminders_enabled",
            "dm_streak_end_enabled",
            "dm_streak_end_ice_enabled",
            "dm_streak_end_restore_enabled",
        }

        for row in rows:
            key = str(row["key"])
            value = str(row["value"])

            if key in int_keys:
                try:
                    merged[key] = int(value)
                except ValueError:
                    pass
            else:
                merged[key] = value

        self._cfg_cache[guild_id] = dict(merged)
        return merged

    async def set_guild_setting_int(
        self,
        guild_id: int,
        key: str,
        value: int,
        now_ts: int | None = None,
    ) -> None:
        if now_ts is None:
            now_ts = int(time.time())

        db = await self._db()
        await self._ensure_guild_exists(guild_id, now_ts)

        await db.execute(
            """
            INSERT INTO guild_settings (guild_id, key, value, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(guild_id, key)
            DO UPDATE SET
                value = excluded.value,
                updated_at = excluded.updated_at
            """,
            (guild_id, key, str(int(value)), now_ts),
        )
        await db.commit()
        await self.invalidate_config_cache(guild_id)

    async def set_guild_setting_str(
        self,
        guild_id: int,
        key: str,
        value: str,
        now_ts: int | None = None,
    ) -> None:
        if now_ts is None:
            now_ts = int(time.time())

        db = await self._db()
        await self._ensure_guild_exists(guild_id, now_ts)

        await db.execute(
            """
            INSERT INTO guild_settings (guild_id, key, value, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(guild_id, key)
            DO UPDATE SET
                value = excluded.value,
                updated_at = excluded.updated_at
            """,
            (guild_id, key, value, now_ts),
        )
        await db.commit()
        await self.invalidate_config_cache(guild_id)

    # -------------------------
    # user settings
    # -------------------------

    async def get_user_setting(self, guild_id: int, user_id: int, key: str) -> str | None:
        db = await self._db()
        row = await db.fetchone(
            """
            SELECT value
            FROM user_settings
            WHERE guild_id = ? AND user_id = ? AND key = ?
            """,
            (guild_id, user_id, key),
        )
        if row is None:
            return None
        return str(row["value"])

    async def get_user_setting_bool(
        self,
        guild_id: int,
        user_id: int,
        key: str,
        default: bool,
    ) -> bool:
        value = await self.get_user_setting(guild_id, user_id, key)
        if value is None:
            return bool(default)
        return value == "1"

    async def set_user_setting_bool(
        self,
        guild_id: int,
        user_id: int,
        key: str,
        value: bool,
        now_ts: int | None = None,
    ) -> None:
        if now_ts is None:
            now_ts = int(time.time())

        db = await self._db()
        await self._ensure_guild_exists(guild_id, now_ts)
        await self._ensure_users_exist([user_id], now_ts)

        await db.execute(
            """
            INSERT INTO user_settings (guild_id, user_id, key, value, updated_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(guild_id, user_id, key)
            DO UPDATE SET
                value = excluded.value,
                updated_at = excluded.updated_at
            """,
            (guild_id, user_id, key, "1" if value else "0", now_ts),
        )
        await db.commit()

    # -------------------------
    # streak getters
    # -------------------------

    async def get_streak_entity(self, streak_id: int) -> dict[str, Any] | None:
        db = await self._db()
        row = await db.fetchone(
            """
            SELECT streak_id, guild_id, streak_type, name, size, required_count,
                   member_hash, is_active, created_at, updated_at
            FROM streak_entities
            WHERE streak_id = ?
            """,
            (streak_id,),
        )
        if row is None:
            return None
        return dict(row)

    async def get_streak_members(self, streak_id: int) -> list[int]:
        db = await self._db()
        rows = await db.fetchall(
            """
            SELECT user_id
            FROM streak_members
            WHERE streak_id = ?
            ORDER BY user_id ASC
            """,
            (streak_id,),
        )
        return [int(row["user_id"]) for row in rows]

    async def get_streak_by_member_hash(
        self,
        guild_id: int,
        member_ids: list[int] | tuple[int, ...],
        only_active: bool = True,
    ) -> dict[str, Any] | None:
        db = await self._db()
        member_hash = self._build_member_hash(member_ids)

        sql = """
            SELECT streak_id, guild_id, streak_type, name, size, required_count,
                   member_hash, is_active, created_at, updated_at
            FROM streak_entities
            WHERE guild_id = ? AND member_hash = ?
        """
        params: list[Any] = [guild_id, member_hash]

        if only_active:
            sql += " AND is_active = 1"

        row = await db.fetchone(sql, tuple(params))
        if row is None:
            return None
        return dict(row)

    async def get_active_group_for_user(self, guild_id: int, user_id: int) -> dict[str, Any] | None:
        db = await self._db()
        row = await db.fetchone(
            """
            SELECT se.streak_id, se.guild_id, se.streak_type, se.name, se.size,
                   se.required_count, se.member_hash, se.is_active,
                   se.created_at, se.updated_at
            FROM streak_entities se
            JOIN streak_members sm
              ON sm.streak_id = se.streak_id
            WHERE se.guild_id = ?
              AND sm.user_id = ?
              AND se.streak_type = 'group'
              AND se.is_active = 1
            LIMIT 1
            """,
            (guild_id, user_id),
        )
        if row is None:
            return None
        return dict(row)

    async def get_streak_state(self, streak_id: int) -> dict[str, int] | None:
        db = await self._db()
        row = await db.fetchone(
            """
            SELECT current_streak, longest_streak, total_completed_days,
                   last_completed_day_key, updated_at
            FROM streak_state
            WHERE streak_id = ?
            """,
            (streak_id,),
        )
        if row is None:
            return None

        return {
            "current_streak": int(row["current_streak"]),
            "longest_streak": int(row["longest_streak"]),
            "total_completed_days": int(row["total_completed_days"]),
            "last_completed_day_key": int(row["last_completed_day_key"]),
            "updated_at": int(row["updated_at"]),
        }

    async def get_progress_row(self, streak_id: int, day_key: int) -> dict[str, int] | None:
        db = await self._db()
        row = await db.fetchone(
            """
            SELECT progress_seconds, qualified, updated_at
            FROM streak_daily_progress
            WHERE streak_id = ? AND day_key = ?
            """,
            (streak_id, day_key),
        )
        if row is None:
            return None

        return {
            "progress_seconds": int(row["progress_seconds"]),
            "qualified": int(row["qualified"]),
            "updated_at": int(row["updated_at"]),
        }

    async def get_progress_map_between(
        self,
        streak_id: int,
        start_day_key: int,
        end_day_key: int,
    ) -> dict[int, int]:
        db = await self._db()
        rows = await db.fetchall(
            """
            SELECT day_key, progress_seconds
            FROM streak_daily_progress
            WHERE streak_id = ?
              AND day_key BETWEEN ? AND ?
            ORDER BY day_key ASC
            """,
            (streak_id, start_day_key, end_day_key),
        )
        return {int(row["day_key"]): int(row["progress_seconds"]) for row in rows}

    async def get_connection_score_seconds(self, streak_id: int) -> int:
        db = await self._db()
        row = await db.fetchone(
            """
            SELECT COALESCE(SUM(progress_seconds), 0) AS total
            FROM streak_daily_progress
            WHERE streak_id = ?
            """,
            (streak_id,),
        )
        return 0 if row is None else int(row["total"])

    async def get_active_fire_user_ids(self, guild_id: int) -> set[int]:
        db = await self._db()
        rows = await db.fetchall(
            """
            SELECT DISTINCT sm.user_id
            FROM streak_state ss
            JOIN streak_entities se
              ON se.streak_id = ss.streak_id
            JOIN streak_members sm
              ON sm.streak_id = se.streak_id
            WHERE se.guild_id = ?
              AND se.is_active = 1
              AND se.streak_type = 'duo'
              AND ss.current_streak > 0
            """,
            (guild_id,),
        )
        return {int(row["user_id"]) for row in rows}

    # -------------------------
    # create duo / group
    # -------------------------

    async def get_or_create_duo(
        self,
        guild_id: int,
        user_a: int,
        user_b: int,
        now_ts: int,
    ) -> int:
        members = self._normalize_members([user_a, user_b])

        if len(members) != 2:
            raise ValueError("Duo must have exactly 2 unique users")

        db = await self._db()
        await db.begin()

        try:
            await self._ensure_guild_exists(guild_id, now_ts)
            await self._ensure_users_exist(members, now_ts)

            existing = await self.get_streak_by_member_hash(
                guild_id=guild_id,
                member_ids=members,
                only_active=True,
            )
            if existing is not None:
                if existing["streak_type"] != "duo":
                    raise ValueError("This member set already exists as a different streak type")
                await db.rollback()
                return int(existing["streak_id"])

            member_hash = self._build_member_hash(members)

            cur = await db.execute(
                """
                INSERT INTO streak_entities (
                    guild_id,
                    streak_type,
                    name,
                    size,
                    required_count,
                    member_hash,
                    is_active,
                    created_at,
                    updated_at
                )
                VALUES (?, 'duo', NULL, 2, 2, ?, 1, ?, ?)
                """,
                (guild_id, member_hash, now_ts, now_ts),
            )
            streak_id = int(cur.lastrowid)

            await self._insert_members(streak_id, members, now_ts)
            await self._create_empty_state(streak_id, guild_id, now_ts)

            await db.commit()
            return streak_id

        except Exception:
            await db.rollback()
            raise

    async def create_group(
        self,
        guild_id: int,
        member_ids: list[int] | tuple[int, ...],
        now_ts: int,
        name: str | None = None,
        required_count: int | None = None,
    ) -> int:
        members = self._normalize_members(member_ids)
        size = len(members)

        if size < 3 or size > 5:
            raise ValueError("Group must have between 3 and 5 unique users")

        if required_count is None:
            required_count = self._default_required_count(size)

        if required_count < 2 or required_count > size:
            raise ValueError("Invalid required_count for this group size")

        db = await self._db()
        await db.begin()

        try:
            await self._ensure_guild_exists(guild_id, now_ts)
            await self._ensure_users_exist(members, now_ts)

            for user_id in members:
                active_group = await self.get_active_group_for_user(guild_id, user_id)
                if active_group is not None:
                    raise ValueError(f"User {user_id} is already in an active group")

            existing = await self.get_streak_by_member_hash(
                guild_id=guild_id,
                member_ids=members,
                only_active=True,
            )
            if existing is not None:
                raise ValueError("This exact active roster already exists")

            member_hash = self._build_member_hash(members)

            cur = await db.execute(
                """
                INSERT INTO streak_entities (
                    guild_id,
                    streak_type,
                    name,
                    size,
                    required_count,
                    member_hash,
                    is_active,
                    created_at,
                    updated_at
                )
                VALUES (?, 'group', ?, ?, ?, ?, 1, ?, ?)
                """,
                (guild_id, name, size, required_count, member_hash, now_ts, now_ts),
            )
            streak_id = int(cur.lastrowid)

            await self._insert_members(streak_id, members, now_ts)
            await self._create_empty_state(streak_id, guild_id, now_ts)

            await db.commit()
            return streak_id

        except Exception:
            await db.rollback()
            raise

    async def deactivate_streak(self, streak_id: int, now_ts: int) -> None:
        db = await self._db()
        await db.execute(
            """
            UPDATE streak_entities
            SET is_active = 0,
                updated_at = ?
            WHERE streak_id = ?
            """,
            (now_ts, streak_id),
        )
        await db.commit()

    # -------------------------
    # progress / logs / state
    # -------------------------

    async def add_progress_seconds(
        self,
        streak_id: int,
        guild_id: int,
        day_key: int,
        seconds: int,
        now_ts: int,
        event_type: str = "vc_add",
        meta_json: str | None = None,
        daily_cap_seconds: int = 0,
    ) -> int:
        if seconds <= 0:
            raise ValueError("seconds must be > 0")

        db = await self._db()
        await db.begin()

        try:
            current_row = await db.fetchone(
                """
                SELECT progress_seconds
                FROM streak_daily_progress
                WHERE streak_id = ? AND day_key = ?
                """,
                (streak_id, day_key),
            )
            current_total = 0 if current_row is None else int(current_row["progress_seconds"])

            seconds_to_add = int(seconds)
            if daily_cap_seconds > 0:
                remaining = max(0, int(daily_cap_seconds) - current_total)
                seconds_to_add = min(seconds_to_add, remaining)

            if seconds_to_add <= 0:
                await db.rollback()
                return current_total

            await db.execute(
                """
                INSERT INTO streak_daily_progress (
                    streak_id,
                    guild_id,
                    day_key,
                    progress_seconds,
                    qualified,
                    updated_at
                )
                VALUES (?, ?, ?, ?, 0, ?)
                ON CONFLICT(streak_id, day_key)
                DO UPDATE SET
                    progress_seconds = progress_seconds + excluded.progress_seconds,
                    updated_at = excluded.updated_at
                """,
                (streak_id, guild_id, day_key, seconds_to_add, now_ts),
            )

            await db.execute(
                """
                INSERT INTO streak_activity_logs (
                    streak_id,
                    guild_id,
                    day_key,
                    event_type,
                    seconds_delta,
                    meta_json,
                    created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (streak_id, guild_id, day_key, event_type, seconds_to_add, meta_json, now_ts),
            )

            row = await db.fetchone(
                """
                SELECT progress_seconds
                FROM streak_daily_progress
                WHERE streak_id = ? AND day_key = ?
                """,
                (streak_id, day_key),
            )

            await db.commit()
            return int(row["progress_seconds"]) if row else current_total

        except Exception:
            await db.rollback()
            raise

    async def set_progress_seconds(
        self,
        streak_id: int,
        guild_id: int,
        day_key: int,
        seconds: int,
        now_ts: int,
        qualified: bool = False,
    ) -> None:
        db = await self._db()
        await db.execute(
            """
            INSERT INTO streak_daily_progress (
                streak_id,
                guild_id,
                day_key,
                progress_seconds,
                qualified,
                updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(streak_id, day_key)
            DO UPDATE SET
                progress_seconds = excluded.progress_seconds,
                qualified = excluded.qualified,
                updated_at = excluded.updated_at
            """,
            (streak_id, guild_id, day_key, int(seconds), 1 if qualified else 0, now_ts),
        )
        await db.commit()

    async def set_day_qualified(
        self,
        streak_id: int,
        guild_id: int,
        day_key: int,
        qualified: bool,
        now_ts: int,
    ) -> None:
        db = await self._db()
        await db.execute(
            """
            UPDATE streak_daily_progress
            SET qualified = ?,
                updated_at = ?
            WHERE streak_id = ? AND guild_id = ? AND day_key = ?
            """,
            (1 if qualified else 0, now_ts, streak_id, guild_id, day_key),
        )
        await db.commit()

    async def save_streak_state(
        self,
        streak_id: int,
        guild_id: int,
        current_streak: int,
        longest_streak: int,
        total_completed_days: int,
        last_completed_day_key: int,
        now_ts: int,
    ) -> None:
        db = await self._db()
        await db.execute(
            """
            INSERT INTO streak_state (
                streak_id,
                guild_id,
                current_streak,
                longest_streak,
                total_completed_days,
                last_completed_day_key,
                updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(streak_id)
            DO UPDATE SET
                current_streak = excluded.current_streak,
                longest_streak = excluded.longest_streak,
                total_completed_days = excluded.total_completed_days,
                last_completed_day_key = excluded.last_completed_day_key,
                updated_at = excluded.updated_at
            """,
            (
                streak_id,
                guild_id,
                current_streak,
                longest_streak,
                total_completed_days,
                last_completed_day_key,
                now_ts,
            ),
        )
        await db.commit()

    async def log_admin_action(
        self,
        guild_id: int,
        admin_user_id: int,
        action_type: str,
        now_ts: int,
        streak_id: int | None = None,
        amount: int | None = None,
        note: str | None = None,
    ) -> None:
        db = await self._db()
        await self._ensure_guild_exists(guild_id, now_ts)
        await self._ensure_users_exist([admin_user_id], now_ts)

        await db.execute(
            """
            INSERT INTO admin_actions (
                guild_id,
                admin_user_id,
                streak_id,
                action_type,
                amount,
                note,
                created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (guild_id, admin_user_id, streak_id, action_type, amount, note, now_ts),
        )
        await db.commit()

    async def delete_streak_completely(self, streak_id: int) -> None:
        db = await self._db()
        await db.begin()
        try:
            await db.execute("DELETE FROM streak_daily_progress WHERE streak_id = ?", (streak_id,))
            await db.execute("DELETE FROM streak_state WHERE streak_id = ?", (streak_id,))
            await db.execute("DELETE FROM streak_notifications WHERE streak_id = ?", (streak_id,))
            await db.execute("DELETE FROM streak_activity_logs WHERE streak_id = ?", (streak_id,))
            await db.execute("DELETE FROM streak_members WHERE streak_id = ?", (streak_id,))
            await db.execute("DELETE FROM streak_entities WHERE streak_id = ?", (streak_id,))
            await db.commit()
        except Exception:
            await db.rollback()
            raise

    async def counts_for_guild(self, guild_id: int) -> dict[str, int]:
        db = await self._db()

        rows = {}
        row = await db.fetchone(
            "SELECT COUNT(*) AS c FROM streak_entities WHERE guild_id = ?",
            (guild_id,),
        )
        rows["streak_entities"] = 0 if row is None else int(row["c"])

        row = await db.fetchone(
            """
            SELECT COUNT(*) AS c
            FROM streak_members sm
            JOIN streak_entities se ON se.streak_id = sm.streak_id
            WHERE se.guild_id = ?
            """,
            (guild_id,),
        )
        rows["streak_members"] = 0 if row is None else int(row["c"])

        row = await db.fetchone(
            "SELECT COUNT(*) AS c FROM streak_daily_progress WHERE guild_id = ?",
            (guild_id,),
        )
        rows["streak_daily_progress"] = 0 if row is None else int(row["c"])

        row = await db.fetchone(
            "SELECT COUNT(*) AS c FROM streak_state WHERE guild_id = ?",
            (guild_id,),
        )
        rows["streak_state"] = 0 if row is None else int(row["c"])

        row = await db.fetchone(
            "SELECT COUNT(*) AS c FROM streak_activity_logs WHERE guild_id = ?",
            (guild_id,),
        )
        rows["streak_activity_logs"] = 0 if row is None else int(row["c"])

        return rows

    # -------------------------
    # leaderboards
    # -------------------------

    async def top_by_current_streak(
        self,
        guild_id: int,
        limit: int = 10,
        streak_type: str | None = None,
    ) -> list[dict[str, Any]]:
        db = await self._db()

        sql = """
            SELECT se.streak_id, se.streak_type, se.name, se.size,
                   ss.current_streak, ss.longest_streak, ss.total_completed_days
            FROM streak_state ss
            JOIN streak_entities se
              ON se.streak_id = ss.streak_id
            WHERE se.guild_id = ?
              AND se.is_active = 1
        """
        params: list[Any] = [guild_id]

        if streak_type is not None:
            sql += " AND se.streak_type = ?"
            params.append(streak_type)

        sql += """
            ORDER BY ss.current_streak DESC,
                     ss.longest_streak DESC,
                     ss.total_completed_days DESC,
                     se.streak_id ASC
            LIMIT ?
        """
        params.append(limit)

        rows = await db.fetchall(sql, tuple(params))
        return [dict(row) for row in rows]

    async def top_by_longest_streak(
        self,
        guild_id: int,
        limit: int = 10,
        streak_type: str | None = None,
    ) -> list[dict[str, Any]]:
        db = await self._db()

        sql = """
            SELECT se.streak_id, se.streak_type, se.name, se.size,
                   ss.current_streak, ss.longest_streak, ss.total_completed_days
            FROM streak_state ss
            JOIN streak_entities se
              ON se.streak_id = ss.streak_id
            WHERE se.guild_id = ?
              AND se.is_active = 1
        """
        params: list[Any] = [guild_id]

        if streak_type is not None:
            sql += " AND se.streak_type = ?"
            params.append(streak_type)

        sql += """
            ORDER BY ss.longest_streak DESC,
                     ss.current_streak DESC,
                     ss.total_completed_days DESC,
                     se.streak_id ASC
            LIMIT ?
        """
        params.append(limit)

        rows = await db.fetchall(sql, tuple(params))
        return [dict(row) for row in rows]

    async def top_by_connection_score(
        self,
        guild_id: int,
        limit: int = 10,
        streak_type: str | None = None,
    ) -> list[dict[str, Any]]:
        db = await self._db()

        sql = """
            SELECT se.streak_id, se.streak_type, se.name, se.size,
                   COALESCE(SUM(sdp.progress_seconds), 0) AS connection_score
            FROM streak_entities se
            LEFT JOIN streak_daily_progress sdp
              ON sdp.streak_id = se.streak_id
            WHERE se.guild_id = ?
              AND se.is_active = 1
        """
        params: list[Any] = [guild_id]

        if streak_type is not None:
            sql += " AND se.streak_type = ?"
            params.append(streak_type)

        sql += """
            GROUP BY se.streak_id
            ORDER BY connection_score DESC,
                     se.streak_id ASC
            LIMIT ?
        """
        params.append(limit)

        rows = await db.fetchall(sql, tuple(params))
        return [dict(row) for row in rows]