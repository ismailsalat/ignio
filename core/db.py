# core/db.py
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

import aiosqlite

from core.schema import MIGRATIONS, LEGACY_SOURCE_TABLES


class Database:
    """Thin async wrapper around a single aiosqlite connection.

    Concurrency model
    ------------------
    The whole bot shares ONE aiosqlite connection. aiosqlite serialises the
    actual SQLite calls, but our async command handlers have many ``await``
    points, so two commands can interleave between a read ("check balance") and
    a later write ("subtract balance"). That is the classic check-then-act race
    every economy exploit in this codebase relied on.

    Two layers defend against it now:

    1. ``transaction()`` opens a ``BEGIN IMMEDIATE`` so the write lock is taken
       up-front and the whole unit of work commits or rolls back atomically.
       Because there is a single connection, only one ``transaction()`` may be
       open at a time — ``_tx_lock`` enforces that and prevents nested/688
       interleaved BEGINs on the shared connection.

    2. Callers also take a per-subject :meth:`key_lock` (e.g. per user) so the
       higher-level "read current balance, then conditionally update" sequence
       is serialised per user even across separate transactions.
    """

    def __init__(self, db_path: str):
        self.db_path = db_path
        self.conn: aiosqlite.Connection | None = None
        # Serialises transactions on the single shared connection.
        self._tx_lock = asyncio.Lock()
        # Named locks for per-subject critical sections (e.g. per user/guild).
        self._key_locks: dict[str, asyncio.Lock] = {}

    # ----- lifecycle -----------------------------------------------------

    async def connect(self) -> None:
        if self.conn is not None:
            return

        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)

        # Use autocommit mode (isolation_level=None) so the ONLY transactions are
        # the explicit BEGIN IMMEDIATE ones we open in transaction(). Without
        # this, the sqlite3 driver auto-opens an implicit transaction before our
        # BEGIN, causing "cannot start a transaction within a transaction".
        # Must be passed to connect() so it's applied on the worker thread.
        self.conn = await aiosqlite.connect(self.db_path, isolation_level=None)
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
                    await self._apply_migration_sql(conn, sql)

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

    async def _apply_migration_sql(self, conn, sql: str) -> None:
        """Run a migration script. ``ALTER TABLE ... ADD COLUMN`` is not
        idempotent in SQLite (it errors if the column already exists), so we
        run statements individually and skip a "duplicate column" error. Every
        other error still propagates and rolls back the migration."""
        statements = [s.strip() for s in sql.split(";") if s.strip()]
        # If there are no ALTERs, the fast path keeps behaviour identical.
        if not any(s.upper().startswith("ALTER TABLE") for s in statements):
            await conn.executescript(sql)
            return
        for stmt in statements:
            try:
                await conn.execute(stmt)
            except Exception as exc:
                if "duplicate column name" in str(exc).lower():
                    continue
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

    # ----- locking + atomic transactions --------------------------------

    def key_lock(self, *parts) -> asyncio.Lock:
        """Return a process-wide lock for an arbitrary key (e.g. a user id).

        Use this to serialise a whole "read then conditionally write" sequence
        for one subject so two concurrent commands can't both pass a check
        before either writes.
        """
        name = ":".join(str(p) for p in parts)
        lock = self._key_locks.get(name)
        if lock is None:
            lock = asyncio.Lock()
            self._key_locks[name] = lock
        return lock

    @asynccontextmanager
    async def transaction(self):
        """Atomic unit of work using ``BEGIN IMMEDIATE``.

        ``BEGIN IMMEDIATE`` takes SQLite's write lock immediately, so the unit
        of work is isolated from the moment it starts. Only one transaction may
        be open at a time on the shared connection (``_tx_lock``). On any
        exception everything rolls back — nothing is half-applied.

        Yields the live connection; run all statements for the unit of work on
        it, then it commits on clean exit.
        """
        conn = self._require_conn()
        async with self._tx_lock:
            await conn.execute("BEGIN IMMEDIATE")
            try:
                yield conn
            except BaseException:
                try:
                    await conn.rollback()
                except Exception:
                    pass
                raise
            else:
                await conn.commit()

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
