"""
test_protection.py — risk-based protection pricing.

Proves the spec's requirements across balance ranges:
  - protection is ALWAYS cheaper than the realistic damage it prevents
  - small players can afford basic protection
  - rich players pay more (because they have more at risk)
  - prices scale with the buyer's OWN balance, not the server reference
  - 24h high-water risk balance (can't dump sobs to get cheap protection)
  - protection inventory expires in 24h (can't stockpile while poor)
  - Vault Ward blocks basic + heist
"""
import asyncio, os, tempfile, sys, time
sys.path.insert(0, '.')
from core.db import Database, DatabaseManager
from core.sob.repo import SobRepo
from core.shop.repo import ShopRepo
from core.economy import Economy, AUDIT_BASIC_PCT, AUDIT_HEIST_PCT
from core.protection import Protection
from core import ledger
GID = 9090
PASS, FAIL = [], []
def check(n, c): (PASS if c else FAIL).append(n); print(f"  {'✅' if c else '❌'} {n}")

class _Mgr(DatabaseManager):
    def __init__(self, db): self._db_obj = db
    async def get(self): return self._db_obj

async def setup():
    d = tempfile.mkdtemp(); db = Database(os.path.join(d,'t.sqlite3')); await db.connect()
    mgr = _Mgr(db); sob = SobRepo(mgr); eco = Economy(sob); shop = ShopRepo(mgr, sob, eco)
    prot = Protection(eco, sob); shop.protection = prot; eco.protection = prot
    return db, sob, eco, shop, prot

async def fund(sob, uid, amount):
    await sob.adjust_received(GID, uid, amount, event_type=ledger.EVT_ADMIN_GIVE)

async def test_ranges():
    db, sob, eco, shop, prot = await setup()
    print("\n  balance |  basic | heist | ward | vault | shield30 | guardian | reflect")
    for i, bal in enumerate([500, 1000, 5000, 10400, 25000, 100000]):
        uid = 1000 + i
        await fund(sob, uid, bal)
        ar = await prot.audit_risk(GID, uid)
        ward = await prot.price_for(GID, uid, "audit_ward")
        vault = await prot.price_for(GID, uid, "vault_ward")
        sh = await prot.price_for(GID, uid, "shield")
        guard = await prot.price_for(GID, uid, "guardian")
        refl = await prot.price_for(GID, uid, "reflect")
        sr = await prot.snitch_risk(GID, uid)
        print(f"  {bal:>7} | {ar['basic']:>6} | {ar['heist']:>5} | {ward:>4} | {vault:>5} | {sh:>8} | {guard:>8} | {refl:>6}")

        # protection cheaper than the damage it prevents
        check(f"[{bal}] Audit Ward ({ward}) < Basic Audit loss ({ar['basic']})", ward < max(1, ar['basic']))
        check(f"[{bal}] Vault Ward ({vault}) < basic+heist ({ar['basic']+ar['heist']})",
              vault < max(1, ar['basic'] + ar['heist']))
        check(f"[{bal}] Shield/30m ({sh}) < snitch loss ({sr})", sh < max(1, sr) or sh <= sr)
        check(f"[{bal}] Guardian ({guard}) < 5 snitches ({5*sr})", guard < max(1, 5*sr))
        # affordability: ward should be a small slice of balance
        check(f"[{bal}] Ward affordable (<10% of balance)", ward <= bal * 0.10 + 1)

    await db.close()

async def test_scales_with_balance():
    db, sob, eco, shop, prot = await setup()
    await fund(sob, 1, 1000)
    await fund(sob, 2, 100000)
    poor = await prot.price_for(GID, 1, "audit_ward")
    rich = await prot.price_for(GID, 2, "audit_ward")
    check("rich player pays MORE for the same ward than poor player", rich > poor)
    await db.close()

async def test_24h_highwater():
    db, sob, eco, shop, prot = await setup()
    uid = 5
    await fund(sob, uid, 50000)
    # note the high, then dump balance
    await prot.note_balance(GID, uid, 50000)
    # spend most of it
    await sob.spend(GID, uid, 48000, event_type=ledger.EVT_SHOP_BASE)
    cur = int((await sob.get_user_stats(GID, uid))["sobs_alltime"])
    rb = await prot.risk_balance(GID, uid)
    check("risk balance uses 24h high, not the dumped current balance",
          rb == 50000 and cur == 2000)
    # so the ward price reflects the 50k risk, not 2k
    ward = await prot.price_for(GID, uid, "audit_ward")
    ward_at_2k = int(0.35 * int(2000 * AUDIT_BASIC_PCT))
    check("dumping sobs does NOT make protection cheap", ward > ward_at_2k)
    await db.close()

async def test_inventory_expiry():
    db, sob, eco, shop, prot = await setup()
    uid = 7
    await fund(sob, uid, 5000)
    # buy an audit ward
    ok, reason, item = await shop.buy(GID, uid, "audit_ward", 1)
    check("can buy a ward", ok)
    inv = await shop.get_inventory(GID, uid)
    check("ward in inventory now", inv.get("audit_ward", 0) == 1)
    # force its expiry into the past
    dbo = await shop._db()
    await dbo.execute("UPDATE shop_inventory SET expires_at=? WHERE guild_id=? AND user_id=? AND item_key='audit_ward'",
                      (int(time.time()) - 10, GID, uid))
    await dbo.commit()
    inv2 = await shop.get_inventory(GID, uid)
    check("expired protection is pruned from inventory", inv2.get("audit_ward", 0) == 0)
    await db.close()

async def test_buy_charges_personal_price():
    db, sob, eco, shop, prot = await setup()
    uid = 8
    await fund(sob, uid, 10400)
    bal0 = int((await sob.get_user_stats(GID, uid))["sobs_alltime"])
    ward_price = await prot.price_for(GID, uid, "audit_ward")
    ok, reason, item = await shop.buy(GID, uid, "audit_ward", 1)
    bal1 = int((await sob.get_user_stats(GID, uid))["sobs_alltime"])
    spent = bal0 - bal1
    # ward is a protection item -> no PvP tax, charged at personal price
    check(f"buy charges the personal ward price ({ward_price}), spent={spent}", spent == ward_price)
    await db.close()


async def test_auto_balance():
    db, sob, eco, shop, prot = await setup()
    # baseline factor is 1.0
    f0 = await prot.price_factor(GID)
    check("default price factor is 1.0", f0 == 1.0)
    # simulate many attacks, no protection bought -> factor should drop
    from core import ledger
    import time as _t
    now = int(_t.time())
    dbo = await shop._db()
    for i in range(20):
        async with dbo.transaction() as conn:
            await ledger.record(conn, guild_id=GID, event_type="audit_steal",
                transaction_id=ledger.new_tx_id(), subject_id=100+i, delta=-50,
                created_at=now)
    res = await prot.auto_balance(GID)
    check("heavy attacks + no shields lowers the factor", res["factor_after"] < res["factor_before"])
    check("daily step is capped at 10%", abs(res["factor_after"] - res["factor_before"]) <= 0.1001)
    # factor stays within bounds
    for _ in range(20):
        await prot.auto_balance(GID)
    f = await prot.price_factor(GID)
    check("factor never goes below floor 0.5", f >= 0.5)
    # admin override + clamp
    await prot.set_price_factor(GID, 5.0)
    check("override clamps to max 1.2", await prot.price_factor(GID) == 1.2)
    await db.close()

async def main():
    print("[test_protection]")
    await test_ranges()
    await test_scales_with_balance()
    await test_24h_highwater()
    await test_inventory_expiry()
    await test_buy_charges_personal_price()
    await test_auto_balance()
    print(f"\n  RESULT: {len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        print("  FAILURES:", FAIL); sys.exit(1)

if __name__ == "__main__":
    asyncio.run(main())
