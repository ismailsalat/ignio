# bot/services/db.py
from __future__ import annotations

from pathlib import Path

import aiosqlite

from bot.services.schema import MIGRATIONS


class Database:
    def __init__(self, db_path: str):
        self.db_path = db_path
        self.conn: aiosqlite.Connection | None = None

    async def connect(self) -> None:
        if self.conn is not None:
            return

        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)

        self.conn = await aiosqlite.connect(self.db_path)
        self.conn.row_factory = aiosqlite.Row

        await self._setup()
        await self._run_migrations()

    async def _setup(self) -> None:
        conn = self._require_conn()

        await conn.execute("PRAGMA journal_mode=WAL;")
        await conn.execute("PRAGMA foreign_keys=ON;")
        await conn.execute("PRAGMA synchronous=NORMAL;")
        await conn.commit()

    async def _run_migrations(self) -> None:
        conn = self._require_conn()

        await conn.execute("""
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                applied_at INTEGER NOT NULL
            )
        """)
        await conn.commit()

        cur = await conn.execute(
            "SELECT version FROM schema_migrations ORDER BY version"
        )
        rows = await cur.fetchall()
        await cur.close()

        done = {row["version"] for row in rows}

        for version, name, sql in MIGRATIONS:
            if version in done:
                continue

            try:
                await conn.executescript(sql)

                await conn.execute("""
                    INSERT INTO schema_migrations (version, name, applied_at)
                    VALUES (?, ?, CAST(strftime('%s','now') AS INTEGER))
                """, (version, name))

                await conn.commit()

            except Exception:
                await conn.rollback()
                raise

    def _require_conn(self) -> aiosqlite.Connection:
        if self.conn is None:
            raise RuntimeError("Database not connected")
        return self.conn

    @property
    def is_connected(self) -> bool:
        return self.conn is not None

    async def execute(
        self,
        sql: str,
        params: tuple = (),
    ) -> aiosqlite.Cursor:
        conn = self._require_conn()
        return await conn.execute(sql, params)

    async def executemany(
        self,
        sql: str,
        params_list: list[tuple],
    ) -> aiosqlite.Cursor:
        conn = self._require_conn()
        return await conn.executemany(sql, params_list)

    async def executescript(self, sql: str) -> None:
        conn = self._require_conn()
        await conn.executescript(sql)

    async def fetchone(
        self,
        sql: str,
        params: tuple = (),
    ) -> aiosqlite.Row | None:
        cur = await self.execute(sql, params)
        row = await cur.fetchone()
        await cur.close()
        return row

    async def fetchall(
        self,
        sql: str,
        params: tuple = (),
    ) -> list[aiosqlite.Row]:
        cur = await self.execute(sql, params)
        rows = await cur.fetchall()
        await cur.close()
        return rows

    async def commit(self) -> None:
        conn = self._require_conn()
        await conn.commit()

    async def rollback(self) -> None:
        conn = self._require_conn()
        await conn.rollback()

    async def begin(self) -> None:
        conn = self._require_conn()
        await conn.execute("BEGIN")

    async def close(self) -> None:
        if self.conn is not None:
            await self.conn.close()
            self.conn = None