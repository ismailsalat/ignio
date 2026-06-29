"""
test_multiplier_balance.py — the sob multiplier must not over-inflate an
established server. A new server gets the bootstrap boost; a mature one (many
active users) does not, even if its median balance is low from PvP draining.
"""
import asyncio, os, tempfile, sys
sys.path.insert(0, '.')
from core.db import Database, DatabaseManager
from core.sob.repo import SobRepo
from core.economy import Economy
from core import ledger
PASS, FAIL = [], []
def check(n, c): (PASS if c else FAIL).append(n); print(f"  {'✅' if c else '❌'} {n}")

class _Mgr(DatabaseManager):
    def __init__(self, db): self._db_obj = db
    async def get(self): return self._db_obj

async def setup(gid):
    d = tempfile.mkdtemp(); db = Database(os.path.join(d, 't.sqlite3')); await db.connect()
    mgr = _Mgr(db); sob = SobRepo(mgr); eco = Economy(sob)
    return db, sob, eco

async def test_new_server_boosts():
    db, sob, eco = await setup(1)
    # a brand-new server: only 5 active users with small balances
    for u in range(5):
        await sob.adjust_received(1, u, 30, event_type=ledger.EVT_DAILY)
    await eco.recompute_reference(1)
    mult = await eco.suggest_multiplier(1)
    check("new server (5 active) still gets a bootstrap boost (>1)", mult > 1.0)
    await db.close()

async def test_mature_server_no_overboost():
    db, sob, eco = await setup(2)
    # mature server: 300 active users, but most drained low (median ~96)
    import random
    for u in range(300):
        bal = random.choice([20, 50, 96, 96, 96, 120, 5000])  # low median, few rich
        await sob.adjust_received(2, u, bal, event_type=ledger.EVT_DAILY)
    await eco.recompute_reference(2)
    active = await eco._active_user_count(2)
    mult = await eco.suggest_multiplier(2)
    val = await eco.sob_value(2)
    check(f"mature server detected ({active} active users)", active >= 200)
    check(f"mature server NOT over-boosted (mult <= 1.0, got {mult})", mult <= 1.0)
    check(f"each reaction is a sane value (5-9 sobs, not over-inflated), got {int(val*mult)}", 5 <= int(val*mult) <= 9)
    await db.close()

async def test_real_server_value():
    # the actual production export: 330 active, was minting 9/reaction
    import json
    from core import transfer
    GID = 1477356380443902013
    db, sob, eco = await setup(GID)
    await transfer.import_guild(db, json.load(open(
        '/mnt/user-data/uploads/ignio_export_1477356380443902013__5_.json')), mode='replace')
    mult = await eco.suggest_multiplier(GID)
    val = await eco.sob_value(GID)
    check(f"real server reaction rebalanced to 5-9 (was 9 inflated), got {int(val*mult)}", 5 <= int(val*mult) <= 9)
    await db.close()

async def main():
    print("[test_multiplier_balance]")
    await test_new_server_boosts()
    await test_mature_server_no_overboost()
    await test_real_server_value()
    print(f"\n  RESULT: {len(PASS)} passed, {len(FAIL)} failed")
    if FAIL: print("  FAILURES:", FAIL); sys.exit(1)

if __name__ == "__main__":
    asyncio.run(main())
