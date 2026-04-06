# bot/services/db_manager.py
from bot.services.db import Database


class DatabaseManager:
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