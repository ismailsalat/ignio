"""Test the new per-auditor daily cap + cooldown and shop disable controls."""
import asyncio, os, tempfile, sys, time
sys.path.insert(0, '.')
from core.db import Database, DatabaseManager
from core.sob.repo import SobRepo
from core.shop.repo import ShopRepo
from core.economy import Economy
from core import ledger
GID = 555
PASS, FAIL = [], []
def check(n, c): (PASS if c else FAIL).append(n); print(f"  {'✅' if c else '❌'} {n}")

class _Mgr(DatabaseManager):
    def __init__(self, db): self._db_obj = db
    async def get(self): return self._db_obj

async def setup():
    d = tempfile.mkdtemp(); db = Database(os.path.join(d,'t.sqlite3')); await db.connect()
    mgr = _Mgr(db); sob = SobRepo(mgr); eco = Economy(sob); shop = ShopRepo(mgr, sob, eco)
    return db, sob, eco, shop

async def test_daily_cap():
    db, sob, eco, shop = await setup()
    await sob.set_guild_setting(GID, "economy:audit_daily_cap", "3")
    await sob.set_guild_setting(GID, "economy:audit_cooldown_secs", "0")  # isolate the cap
    auditor = 1
    # simulate 3 audits logged today
    for i in range(3):
        await eco.log_audit(GID, auditor, 100+i, 50)
    ok, why, info = await eco.can_audit(GID, auditor)
    check("daily cap blocks the 4th audit", (not ok) and why == "daily_cap")
    check("cap info reports 3/3 used", info["done"] == 3 and info["cap"] == 3)
    # a different auditor is unaffected
    ok2, _, _ = await eco.can_audit(GID, 999)
    check("cap is per-person (other auditor allowed)", ok2)
    await db.close()

async def test_cooldown():
    db, sob, eco, shop = await setup()
    await sob.set_guild_setting(GID, "economy:audit_daily_cap", "100")
    await sob.set_guild_setting(GID, "economy:audit_cooldown_secs", "1800")
    auditor = 2
    await eco.log_audit(GID, auditor, 200, 50)  # just audited now
    ok, why, info = await eco.can_audit(GID, auditor)
    check("cooldown blocks back-to-back audit", (not ok) and why == "cooldown")
    check("cooldown_left is ~30 min", 1700 <= info["cooldown_left"] <= 1800)
    await db.close()

async def test_defaults_allow():
    db, sob, eco, shop = await setup()
    ok, why, info = await eco.can_audit(GID, 3)
    check("fresh auditor allowed by default", ok and why == "ok")
    check("default cap is 8", info["cap"] == 8)
    await db.close()

async def test_disable_item():
    db, sob, eco, shop = await setup()
    # audit item enabled by default
    item = await shop.get_item(GID, "audit")
    check("audit item buyable by default", item is not None)
    await sob.set_guild_setting(GID, "shop:disabled_items", "audit")
    item2 = await shop.get_item(GID, "audit")
    check("disabled item is not buyable", item2 is None)
    # shield still works
    check("other items unaffected", (await shop.get_item(GID, "shield")) is not None)
    await db.close()

async def test_disable_category():
    db, sob, eco, shop = await setup()
    await sob.set_guild_setting(GID, "shop:disabled_categories", "debuff")
    check("debuff item (audit) disabled by category", (await shop.get_item(GID, "audit")) is None)
    check("debuff item (freeze) disabled by category", (await shop.get_item(GID, "freeze")) is None)
    check("protection item (shield) still enabled", (await shop.get_item(GID, "shield")) is not None)
    await db.close()

async def test_disable_shop():
    db, sob, eco, shop = await setup()
    await sob.set_guild_setting(GID, "shop:enabled", "0")
    cat = await shop.get_catalog(GID)
    enabled = [c for c in cat if c["enabled"]]
    check("whole shop off disables every item", len(enabled) == 0)
    check("buying a disabled-shop item fails", (await shop.get_item(GID, "shield")) is None)
    await db.close()

async def main():
    print("[test_audit_limits]")
    await test_daily_cap()
    await test_cooldown()
    await test_defaults_allow()
    await test_disable_item()
    await test_disable_category()
    await test_disable_shop()
    print(f"\n  RESULT: {len(PASS)} passed, {len(FAIL)} failed")
    if FAIL: print("  FAILURES:", FAIL); sys.exit(1)

if __name__ == "__main__":
    asyncio.run(main())
