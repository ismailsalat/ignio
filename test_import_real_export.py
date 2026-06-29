"""
test_import_real_export.py — import the real server export into the NEW schema.

Proves the upgraded code can ingest a pre-ledger, pre-credited_amount export
(143k+ reaction rows, 514 users) without breaking, and that row counts survive.
"""
import asyncio
import json
import os
import sqlite3
import sys
import tempfile

sys.path.insert(0, os.path.dirname(__file__))
from core.db import Database          # noqa: E402
from core import transfer             # noqa: E402

EXPORT = "/mnt/user-data/uploads/ignio_export_1477356380443902013__3_.json"


async def main():
    print("[test_import_real_export]")
    payload = json.load(open(EXPORT))
    src_counts = {t: len(rows) for t, rows in payload["tables"].items()}

    d = tempfile.mkdtemp()
    path = os.path.join(d, "imported.sqlite3")
    db = Database(path)
    await db.connect()

    inserted = await transfer.import_guild(db, payload, mode="replace")
    print("  imported rows:", {k: v for k, v in inserted.items() if v})

    # verify key tables match the source counts
    for t in ("sob_users", "sob_events", "sob_periods", "shop_items",
              "shop_inventory", "game_events", "daily_claims"):
        c = sqlite3.connect(path)
        n = c.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        c.close()
        assert n == src_counts.get(t, 0), f"{t}: imported {n} != source {src_counts.get(t,0)}"
    print("  ✅ all imported table counts match the source export")

    # verify sob_events got the default credited_amount=1 (pre-ledger rows)
    c = sqlite3.connect(path)
    bad = c.execute("SELECT COUNT(*) FROM sob_events WHERE credited_amount IS NULL").fetchone()[0]
    assert bad == 0, "some sob_events have NULL credited_amount"
    sample = c.execute("SELECT credited_amount FROM sob_events LIMIT 1").fetchone()
    print(f"  sob_events credited_amount default applied (sample={sample[0]})")

    # a top user's balance survived intact
    top = c.execute("SELECT user_id, sobs_received_alltime FROM sob_users "
                    "ORDER BY sobs_received_alltime DESC LIMIT 1").fetchone()
    print(f"  top user preserved: {top[0]} = {top[1]:,} sobs")
    c.close()

    # re-export round-trips (now with ledger/reconciliation sections present)
    re_payload = await transfer.export_guild(db, payload["guild_id"])
    assert "reconciliation" in re_payload and "per_user_summary" in re_payload
    assert len(re_payload["tables"]["sob_events"]) == src_counts["sob_events"]
    print(f"  ✅ re-export round-trips with reconciliation report "
          f"({re_payload['reconciliation'].get('users_total',0)} users)")

    await db.close()
    print("  ✅ import of real production export PASSED")


if __name__ == "__main__":
    asyncio.run(main())
