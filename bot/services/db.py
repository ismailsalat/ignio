# bot/services/db.py
import aiosqlite
from pathlib import Path

SCHEMA_SQL = """
PRAGMA journal_mode=WAL;

-- Stores duo pairs (within this guild DB file)
CREATE TABLE IF NOT EXISTS duos(
  duo_id INTEGER PRIMARY KEY AUTOINCREMENT,
  user1_id INTEGER NOT NULL,
  user2_id INTEGER NOT NULL,
  created_at INTEGER NOT NULL,
  UNIQUE(user1_id, user2_id)
);

-- Stores today's progress by day_key
CREATE TABLE IF NOT EXISTS duo_daily(
  duo_id INTEGER NOT NULL,
  day_key INTEGER NOT NULL,
  overlap_seconds INTEGER NOT NULL DEFAULT 0,
  updated_at INTEGER NOT NULL,
  PRIMARY KEY(duo_id, day_key)
);

-- Stores streak counters
CREATE TABLE IF NOT EXISTS duo_streaks(
  duo_id INTEGER PRIMARY KEY,
  current_streak INTEGER NOT NULL DEFAULT 0,
  longest_streak INTEGER NOT NULL DEFAULT 0,
  last_completed_day_key INTEGER NOT NULL DEFAULT -1,
  updated_at INTEGER NOT NULL
);

-- ✅ Guild config stored in DB (per server file)
CREATE TABLE IF NOT EXISTS guild_settings(
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL,
  updated_at INTEGER NOT NULL
);
"""

class Database:
    def __init__(self, db_path: str):
        self.db_path = db_path
        self.conn: aiosqlite.Connection | None = None

    async def connect(self) -> None:
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = await aiosqlite.connect(self.db_path)
        await self.conn.executescript(SCHEMA_SQL)
        await self.conn.commit()

    async def close(self) -> None:
        if self.conn:
            await self.conn.close()
            self.conn = None
