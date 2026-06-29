"""Verify the !sob stats data path (breakdown + card) works on real data and empty users."""
import asyncio, json, os, tempfile, sys
sys.path.insert(0,'.')
from core.db import Database, DatabaseManager
from core.sob.repo import SobRepo
from core.economy import Economy
from core import transfer, ledger
from core.profile.small_cards import stats_card
GID=1477356380443902013

class _Mgr(DatabaseManager):
    def __init__(s,db): s._db_obj=db
    async def get(s): return s._db_obj

async def main():
    print("[test_stats_cmd]")
    d=tempfile.mkdtemp(); db=Database(os.path.join(d,'t.sqlite3')); await db.connect()
    await transfer.import_guild(db, json.load(open('/mnt/user-data/uploads/ignio_export_1477356380443902013__4_.json')), mode='replace')
    sob=SobRepo(_Mgr(db)); eco=Economy(sob)

    # Rip (has lots of ledger activity)
    RIP=785478983834664991
    bd=await ledger.stats_breakdown(db,GID,RIP)
    print("  Rip earned:",bd["earned"])
    print("  Rip spent:",bd["spent"])
    assert bd["earned"]["audit"]>0, "audit earnings should show"
    cap=await eco.audit_daily_cap(GID); done=await eco.audits_done_today(GID,RIP)
    img=stats_card("Rip", 25690, bd["earned"], bd["spent"],
        {"sob_value":50,"snitch_steal_pct":50,"audit_basic_pct":0.03,"audit_heist_pct":0.08,"audit_cap":cap},
        {"audit_left":await eco.audit_cooldown_left(GID,RIP),"audits_left":max(0,cap-done)})
    img.save("/tmp/rip_stats.png")
    print("  ✅ Rip stats card rendered from real data")

    # empty user (no ledger) shouldn't crash
    bd2=await ledger.stats_breakdown(db,GID,999999999)
    assert all(v==0 for v in bd2["earned"].values())
    stats_card("Nobody",0,bd2["earned"],bd2["spent"],
        {"sob_value":1,"snitch_steal_pct":50,"audit_basic_pct":0.03,"audit_heist_pct":0.08,"audit_cap":8},
        {"audit_left":0,"audits_left":8}).save("/tmp/empty_stats.png")
    print("  ✅ empty user stats card renders (no crash)")
    print("  RESULT: stats command path PASSED")
    await db.close()

asyncio.run(main())
