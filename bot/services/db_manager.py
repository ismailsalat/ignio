# bot/services/db_manager.py
from bot.services.db import Database

class DatabaseManager:
    """
    One SQLite file per guild:
      database/<guild_id>.sqlite3
    Keeps connections cached so we don't reconnect every command.
    """

    def __init__(self, folder: str = "database"):
        self.folder = folder
        self._dbs: dict[int, Database] = {}

    async def get(self, guild_id: int) -> Database:
        if guild_id not in self._dbs:
            path = f"{self.folder}/{guild_id}.sqlite3"
            db = Database(path)
            await db.connect()
            self._dbs[guild_id] = db
        return self._dbs[guild_id]

    async def close_all(self) -> None:
        for db in self._dbs.values():
            await db.close()
        self._dbs.clear()
