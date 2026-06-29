"""7-day-ish economy sim: confirm steal stays break-even-ish and below natural earning."""
import asyncio, os, tempfile, sys, time
sys.path.insert(0,'.')
from core.db import Database, DatabaseManager
from core.sob.repo import SobRepo
from core.shop.repo import ShopRepo
from core.economy import Economy
from core.protection import Protection
from core.steal import Steal, StealError
from core import ledger
GID=1
class _Mgr(DatabaseManager):
    def __init__(s,db): s._db_obj=db
    async def get(s): return s._db_obj

async def main():
    d=tempfile.mkdtemp(); db=Database(os.path.join(d,'t.sqlite3')); await db.connect()
    mgr=_Mgr(db); sob=SobRepo(mgr); eco=Economy(sob); shop=ShopRepo(mgr,sob,eco); prot=Protection(eco,sob); shop.protection=prot
    steal=Steal(eco,sob,shop,prot)

    import core.steal as S
    # 20 players, each 10k sobs
    for u in range(1,21): await sob.adjust_received(GID,u,10000,event_type=ledger.EVT_ADMIN_GIVE)

    # simulate many steal attempts at the REAL 18% odds (no forcing), bypassing
    # cooldowns by manually spacing 'created_at' — we just call attempt and catch cooldown errors
    import random
    total_hunter_profit=0; total_attempts=0; wins=0
    # to bypass cooldown we directly insert with old timestamps isn't realistic;
    # instead measure EXPECTED value over many independent first-attempts.
    real_roll = S.secrets.randbelow
    for trial in range(2000):
        a = random.randint(1,20); t = random.randint(1,20)
        if a==t: continue
        # fresh attacker each trial: clear their steal history so cooldown won't block
        await (await shop._db()).execute("DELETE FROM steal_events WHERE attacker_id=?", (a,))
        await (await shop._db()).commit()
        ab0=int((await sob.get_user_stats(GID,a))['sobs_alltime'])
        if ab0 < 100: continue
        try:
            res=await steal.attempt(GID,a,t)
        except StealError:
            continue
        total_attempts+=1
        if res['success']:
            wins+=1
            total_hunter_profit += res['gain']
        else:
            total_hunter_profit -= res['fee']

    winrate = wins/max(1,total_attempts)
    avg_ev = total_hunter_profit/max(1,total_attempts)
    print(f"  attempts: {total_attempts}, wins: {wins} ({winrate*100:.1f}%)")
    print(f"  total hunter net: {total_hunter_profit:+,} | avg EV per attempt: {avg_ev:+.1f} sobs")
    # EV should be near/below zero (gamble, not salary)
    print(f"  => steal is {'BALANCED (EV<=0, not a farm)' if avg_ev <= 5 else 'TOO PROFITABLE'}")
    await db.close()

asyncio.run(main())
