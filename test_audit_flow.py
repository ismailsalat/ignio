"""End-to-end audit flow: cap + cooldown enforced in do_use, item not consumed when blocked."""
import asyncio, os, tempfile, sys
sys.path.insert(0, '.')
from core.db import Database, DatabaseManager
from core.sob.repo import SobRepo
from core.shop.repo import ShopRepo
from core.economy import Economy
from core.shop.cog import do_use
from core import ledger
GID = 42
PASS=[]; FAIL=[]
def check(n,c): (PASS if c else FAIL).append(n); print(f"  {'✅' if c else '❌'} {n}")

class _Mgr(DatabaseManager):
    def __init__(self, db): self._db_obj=db
    async def get(self): return self._db_obj
class U:
    def __init__(s,i): s.id=i; s.mention=f"<@{i}>"; s.display_name=f"u{i}"; s.bot=False

async def main():
    print("[test_audit_flow]")
    d=tempfile.mkdtemp(); db=Database(os.path.join(d,'t.sqlite3')); await db.connect()
    mgr=_Mgr(db); sob=SobRepo(mgr); eco=Economy(sob); shop=ShopRepo(mgr,sob,eco)
    attacker, victim = U(1), U(2)
    # fund victim so there's something to steal
    await sob.adjust_received(GID, victim.id, 10000, event_type=ledger.EVT_ADMIN_GIVE)
    # set a tiny cap and no cooldown for the test
    await sob.set_guild_setting(GID, "economy:audit_daily_cap", "2")
    await sob.set_guild_setting(GID, "economy:audit_cooldown_secs", "0")

    # give attacker 5 audit items
    dbo=await shop._db(); await shop._add_to_inventory(dbo,GID,attacker.id,"audit",5,1); await dbo.commit()

    # perform 2 audits (cap=2)
    r1=await do_use(shop,GID,attacker,"audit",target=victim,economy=eco)
    r2=await do_use(shop,GID,attacker,"audit",target=victim,economy=eco)
    check("first 2 audits succeed", r1[0]=="audit_done" and r2[0]=="audit_done")
    # 3rd should be capped
    r3=await do_use(shop,GID,attacker,"audit",target=victim,economy=eco)
    check("3rd audit blocked by daily cap", r3[0]=="audit_capped")
    inv=await shop.get_inventory(GID,attacker.id)
    check("blocked audit did NOT consume an item (3 left)", inv.get("audit",0)==3)

    # now test cooldown: reset cap high, set cooldown
    await sob.set_guild_setting(GID,"economy:audit_daily_cap","100")
    await sob.set_guild_setting(GID,"economy:audit_cooldown_secs","3600")
    r4=await do_use(shop,GID,attacker,"audit",target=victim,economy=eco)
    check("audit blocked by cooldown", r4[0]=="audit_cooldown")
    inv2=await shop.get_inventory(GID,attacker.id)
    check("cooldown-blocked audit not consumed (still 3)", inv2.get("audit",0)==3)

    # conserved: victim lost exactly what attacker gained across the 2 audits
    av=int((await sob.get_user_stats(GID,attacker.id))["sobs_alltime"])
    vv=int((await sob.get_user_stats(GID,victim.id))["sobs_alltime"])
    check("conserved transfer (attacker gain == victim loss)", av == 10000 - vv)
    print(f"\n  RESULT: {len(PASS)} passed, {len(FAIL)} failed")
    if FAIL: print("  FAIL:",FAIL); sys.exit(1)
    await db.close()

asyncio.run(main())
