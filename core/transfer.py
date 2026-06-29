# core/transfer.py
"""
Per-server (per-guild) data export / import.

Goal: make it trivial to pull ONE server's complete sob data out into a single
portable file, and to load it back into the same or a different database. This
is the safe, idiomatic version of "organize by server" — the data lives in one
shared DB partitioned by guild_id, and this module gives you a clean seam to
move a single guild around when you want to.

Format: a self-describing JSON document.
    {
      "ignio_export_version": 1,
      "guild_id": 1440226442012262534,
      "exported_at": 1719000000,
      "tables": {
          "sob_users":   [ {...}, ... ],
          "sob_events":  [ {...}, ... ],
          "sob_periods": [ {...}, ... ],
          "guild_settings": [ {...}, ... ]
      }
    }

Design notes
------------
- Export is read-only: it never modifies the source DB.
- Import is idempotent (INSERT OR IGNORE) and scoped to a single guild_id, so
  re-running it won't duplicate rows. Use mode="replace" to wipe that guild's
  rows first if you want a clean overwrite.
- Only sob tables + that guild's settings are moved. Streak tables are ignored.
"""

from __future__ import annotations

import json
import time
from typing import Any

from core.db import Database

EXPORT_VERSION = 1

# Tables that hold per-guild sob data, all keyed by guild_id.
_GUILD_TABLES = ("sob_users", "sob_events", "sob_periods", "guild_settings",
                 "economy_snapshots", "daily_claims", "tax_events", "audit_events",
                 "shop_items", "shop_inventory", "active_effects")


async def export_guild(db: Database, guild_id: int) -> dict[str, Any]:
    """Return a JSON-serializable dict containing all sob data for one guild."""
    tables: dict[str, list[dict[str, Any]]] = {}
    for table in _GUILD_TABLES:
        try:
            rows = await db.fetchall(
                f"SELECT * FROM {table} WHERE guild_id = ?", (guild_id,)
            )
            tables[table] = [dict(r) for r in rows]
        except Exception:
            # table may not exist yet on older DBs — skip gracefully
            tables[table] = []

    return {
        "ignio_export_version": EXPORT_VERSION,
        "guild_id": int(guild_id),
        "exported_at": int(time.time()),
        "tables": tables,
    }


async def export_guild_to_file(db: Database, guild_id: int, path: str) -> dict[str, int]:
    """Export one guild to a JSON file. Returns per-table row counts."""
    payload = await export_guild(db, guild_id)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    return {t: len(rows) for t, rows in payload["tables"].items()}


async def import_guild(
    db: Database,
    payload: dict[str, Any],
    *,
    mode: str = "merge",
    target_guild_id: int | None = None,
) -> dict[str, int]:
    """
    Load a previously-exported guild payload into this DB.

    mode:
      "merge"   -> INSERT OR IGNORE (keeps existing rows; safe, idempotent)
      "replace" -> delete this guild's rows in each table first, then insert

    target_guild_id: if given, the data is re-homed under this guild id instead
    of the one in the file (useful for cloning a server's data elsewhere).

    Returns per-table inserted-row counts.
    """
    if int(payload.get("ignio_export_version", 0)) != EXPORT_VERSION:
        raise ValueError(
            f"Unsupported export version: {payload.get('ignio_export_version')}"
        )

    src_guild = int(payload["guild_id"])
    dst_guild = int(target_guild_id) if target_guild_id is not None else src_guild
    tables = payload.get("tables", {})

    inserted: dict[str, int] = {}
    await db.begin()
    try:
        for table in _GUILD_TABLES:
            rows = tables.get(table, [])

            if mode == "replace":
                await db.execute(f"DELETE FROM {table} WHERE guild_id = ?", (dst_guild,))

            count = 0
            for row in rows:
                row = dict(row)
                row["guild_id"] = dst_guild  # re-home if cloning
                cols = list(row.keys())
                placeholders = ", ".join("?" for _ in cols)
                col_list = ", ".join(cols)
                cur = await db.execute(
                    f"INSERT OR IGNORE INTO {table} ({col_list}) VALUES ({placeholders})",
                    tuple(row[c] for c in cols),
                )
                count += cur.rowcount if cur.rowcount and cur.rowcount > 0 else 0
            inserted[table] = count

        await db.commit()
    except Exception:
        await db.rollback()
        raise

    return inserted


async def import_guild_from_file(
    db: Database,
    path: str,
    *,
    mode: str = "merge",
    target_guild_id: int | None = None,
) -> dict[str, int]:
    """Import one guild from a JSON file produced by export_guild_to_file."""
    with open(path, "r", encoding="utf-8") as f:
        payload = json.load(f)
    return await import_guild(db, payload, mode=mode, target_guild_id=target_guild_id)


async def list_guilds(db: Database) -> list[dict[str, int]]:
    """List guild ids that have any sob data, with a user count each."""
    rows = await db.fetchall(
        """
        SELECT guild_id, COUNT(*) AS users
        FROM sob_users
        GROUP BY guild_id
        ORDER BY users DESC
        """
    )
    return [{"guild_id": int(r["guild_id"]), "users": int(r["users"])} for r in rows]
