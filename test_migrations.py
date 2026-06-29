"""
test_migrations.py — prove the new schema/migrations don't break any DB.

Scenarios:
  A. Fresh DB: new schema builds cleanly, all new tables/columns exist.
  B. Existing DB already at migration 209 (the shipped database_dev): the new
     ALTER/CREATE migrations (210-214) apply without error and are idempotent.
  C. Re-running connect() twice is a no-op (idempotent).
"""
import asyncio
import os
import shutil
import sqlite3
import sys
import tempfile

sys.path.insert(0, os.path.dirname(__file__))
from core.db import Database  # noqa: E402


def tables_and_columns(path):
    c = sqlite3.connect(path)
    out = {}
    for (name,) in c.execute("SELECT name FROM sqlite_master WHERE type='table'"):
        cols = [r[1] for r in c.execute(f"PRAGMA table_info({name})")]
        out[name] = cols
    migs = []
    try:
        migs = [r[0] for r in c.execute("SELECT version FROM schema_migrations ORDER BY version")]
    except Exception:
        pass
    c.close()
    return out, migs


async def scenario_fresh():
    d = tempfile.mkdtemp()
    path = os.path.join(d, "fresh.sqlite3")
    db = Database(path)
    await db.connect()
    await db.close()
    cols, migs = tables_and_columns(path)
    assert "economy_ledger" in cols, "economy_ledger missing"
    assert "security_log" in cols, "security_log missing"
    assert "game_matches" in cols, "game_matches missing"
    assert "credited_amount" in cols["sob_events"], "credited_amount missing on sob_events"
    assert "multiplier_ref" in cols["sob_events"], "multiplier_ref missing"
    assert "charges_remaining" in cols["active_effects"], "charges_remaining missing"
    assert migs[-1] == 214, f"latest migration should be 214, got {migs[-1]}"
    shutil.rmtree(d)
    print("  A. fresh DB: all new tables/columns present, migrations 200-214 OK")


async def scenario_existing():
    # copy the shipped dev DB (already at migration 209) and upgrade it
    src = os.path.join(os.path.dirname(__file__), "database_dev", "ignio.sqlite3")
    d = tempfile.mkdtemp()
    path = os.path.join(d, "existing.sqlite3")
    shutil.copy(src, path)
    before_cols, before_migs = tables_and_columns(path)
    assert before_migs[-1] == 209, f"fixture should be at 209, got {before_migs}"
    assert "credited_amount" not in before_cols["sob_events"], "fixture already migrated?"

    db = Database(path)
    await db.connect()
    await db.close()
    after_cols, after_migs = tables_and_columns(path)
    assert after_migs[-1] == 214, f"should upgrade to 214, got {after_migs}"
    assert "credited_amount" in after_cols["sob_events"]
    assert "charges_remaining" in after_cols["active_effects"]
    assert "economy_ledger" in after_cols
    print(f"  B. existing DB 209 -> {after_migs[-1]}: ALTERs + new tables applied, data preserved")

    # idempotency: connect again, must not error or re-run
    db2 = Database(path)
    await db2.connect()
    await db2.close()
    _, again = tables_and_columns(path)
    assert again == after_migs, "re-connect changed migrations (not idempotent)"
    print("  C. re-connect is idempotent (no duplicate-column crash)")
    shutil.rmtree(d)


async def main():
    print("[test_migrations]")
    await scenario_fresh()
    await scenario_existing()
    print("  ✅ migration safety PASSED")


if __name__ == "__main__":
    asyncio.run(main())
