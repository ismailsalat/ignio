"""Mixed concurrent storm: many ops on overlapping users; verify no deadlock,
no negative balances/inventory, and the ledger reconciles for all touched users."""
import asyncio, os, tempfile, sys
sys.path.insert(0, '.')
from core.db import Database, DatabaseManager
from core.sob.repo import SobRepo
from core.shop.repo import ShopRepo
from core.economy import Economy
from core.games.engine import GamesEngine
from core import ledger
GID = 7777

class _Mgr(DatabaseManager):
    def __init__(self, db): self._db_obj = db
    async def get(self): return self._db_obj

async def main():
    d = tempfile.mkdtemp(); db = Database(os.path.join(d, 's.sqlite3')); await db.connect()
    mgr = _Mgr(db); sob = SobRepo(mgr); eco = Economy(sob); shop = ShopRepo(mgr, sob, eco)
    games = GamesEngine(sob, eco)

    users = list(range(1, 9))
    # seed each user with a known amount via ledgered grants (all post-ledger)
    for u in users:
        await sob.adjust_received(GID, u, 5000, event_type=ledger.EVT_ADMIN_GIVE)
        dbo = await shop._db()
        await shop._add_to_inventory(dbo, GID, u, "boost", 5, 1)
        await dbo.commit()

    async def storm():
        tasks = []
        for u in users:
            tasks.append(sob.adjust_received(GID, u, 10, event_type=ledger.EVT_DAILY))
            tasks.append(sob.spend(GID, u, 7, event_type=ledger.EVT_SHOP_BASE))
            tasks.append(sob.add_sob(guild_id=GID, message_id=1000+u, reactor_id=(u%8)+1, target_id=u, credited_amount=5))
            # transfers between adjacent users
            v = (u % 8) + 1
            if v != u:
                tasks.append(sob.transfer(GID, u, v, 3, event_type=ledger.EVT_AUDIT_STEAL))
        await asyncio.gather(*tasks, return_exceptions=False)

    # run several waves concurrently
    await asyncio.gather(*[storm() for _ in range(10)])

    # checks
    bad_bal = []
    for u in users:
        b = int((await sob.get_user_stats(GID, u))['sobs_alltime'])
        if b < 0: bad_bal.append((u, b))
        r = await ledger.reconcile_user(db, GID, u, b)
        if not r['reconciled']:
            bad_bal.append((u, 'UNRECONCILED', r['delta']))
    neg_inv = await db.fetchone("SELECT COUNT(*) AS n FROM shop_inventory WHERE quantity < 0")

    print('users:', len(users), '| negative/unreconciled:', bad_bal or 'NONE')
    print('negative inventory rows:', int(neg_inv['n']))
    assert not bad_bal, bad_bal
    assert int(neg_inv['n']) == 0
    # global conservation: total minted (daily+grants+reactions) must equal sum of balances
    total = await db.fetchone("SELECT COALESCE(SUM(sobs_received_alltime),0) AS s FROM sob_users WHERE guild_id=?", (GID,))
    minted = await db.fetchone(
        "SELECT COALESCE(SUM(delta),0) AS s FROM economy_ledger WHERE guild_id=?", (GID,))
    print(f'sum balances={int(total["s"]):,}  ledger net total={int(minted["s"]):,}')
    assert int(total['s']) == int(minted['s']), "global ledger does not match total supply"
    print('✅ STRESS TEST PASSED — no deadlock, no negatives, full reconciliation')
    await db.close()

asyncio.run(main())
