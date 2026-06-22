# core/db.py
from __future__ import annotations

from pathlib import Path

import aiosqlite

from core.schema import MIGRATIONS, LEGACY_SOURCE_TABLES


class Database:
    """Thin async wrapper around a single aiosqlite connection."""

    def __init__(self, db_path: str):
        self.db_path = db_path
        self.conn: aiosqlite.Connection | None = None

    # ----- lifecycle -----------------------------------------------------

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

    async def _table_exists(self, name: str) -> bool:
        conn = self._require_conn()
        cur = await conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
            (name,),
        )
        row = await cur.fetchone()
        await cur.close()
        return row is not None

    async def _run_migrations(self) -> None:
        conn = self._require_conn()

        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version    INTEGER PRIMARY KEY,
                name       TEXT NOT NULL,
                applied_at INTEGER NOT NULL
            )
            """
        )
        await conn.commit()

        cur = await conn.execute("SELECT version FROM schema_migrations")
        rows = await cur.fetchall()
        await cur.close()
        done = {row["version"] for row in rows}

        # The legacy backfill only makes sense if the legacy source tables are
        # present. On a fresh install they aren't, so we skip it entirely (and
        # still record it as applied, so it never re-checks).
        legacy_present = all(
            [await self._table_exists(t) for t in LEGACY_SOURCE_TABLES]
        )

        for version, name, sql in MIGRATIONS:
            if version in done:
                continue

            is_backfill = name == "backfill_legacy_sob"

            try:
                if is_backfill and not legacy_present:
                    # Nothing to copy on a fresh DB — record as a no-op.
                    pass
                else:
                    await conn.executescript(sql)

                await conn.execute(
                    """
                    INSERT INTO schema_migrations (version, name, applied_at)
                    VALUES (?, ?, CAST(strftime('%s','now') AS INTEGER))
                    """,
                    (version, name),
                )
                await conn.commit()

            except Exception:
                await conn.rollback()
                raise

    # ----- query helpers -------------------------------------------------

    def _require_conn(self) -> aiosqlite.Connection:
        if self.conn is None:
            raise RuntimeError("Database not connected")
        return self.conn

    @property
    def is_connected(self) -> bool:
        return self.conn is not None

    async def execute(self, sql: str, params: tuple = ()) -> aiosqlite.Cursor:
        return await self._require_conn().execute(sql, params)

    async def executemany(self, sql: str, params_list: list[tuple]) -> aiosqlite.Cursor:
        return await self._require_conn().executemany(sql, params_list)

    async def executescript(self, sql: str) -> None:
        await self._require_conn().executescript(sql)

    async def fetchone(self, sql: str, params: tuple = ()) -> aiosqlite.Row | None:
        cur = await self.execute(sql, params)
        row = await cur.fetchone()
        await cur.close()
        return row

    async def fetchall(self, sql: str, params: tuple = ()) -> list[aiosqlite.Row]:
        cur = await self.execute(sql, params)
        rows = await cur.fetchall()
        await cur.close()
        return rows

    async def commit(self) -> None:
        await self._require_conn().commit()

    async def rollback(self) -> None:
        await self._require_conn().rollback()

    async def begin(self) -> None:
        await self._require_conn().execute("BEGIN")

    async def close(self) -> None:
        if self.conn is not None:
            await self.conn.close()
            self.conn = None


class DatabaseManager:
    """Lazy singleton holder for the Database connection."""

    def __init__(self, path: str = "database/ignio.sqlite3"):
        self.path = path
        self.db: Database | None = None

    async def get(self) -> Database:
        if self.db is None:
            self.db = Database(self.path)
            await self.db.connect()
        return self.db

    async def close(self) -> None:
        if self.db is not None:
            await self.db.close()
            self.db = None
