"""Prove the ledger correctly tracks NEW activity on a legacy (pre-ledger) balance."""
import asyncio, json, os, tempfile, sys
sys.path.insert(0, '.')
from core.db import Database, DatabaseManager
from core.sob.repo import SobRepo
from core.economy import Economy
from core import transfer, ledger
GID = 1477356380443902013

class _Mgr(DatabaseManager):
    def __init__(self, db): self._db_obj = db
    async def get(self): return self._db_obj

async def main():
    d = tempfile.mkdtemp(); path = os.path.join(d, 't.sqlite3')
    db = Database(path); await db.connect()
    await transfer.import_guild(db, json.load(open('/mnt/user-data/uploads/ignio_export_1477356380443902013__3_.json')), mode='replace')
    sob = SobRepo(_Mgr(db))

    uid = 785478983834664991  # top user, legacy balance 56901
    start = int((await sob.get_user_stats(GID, uid))['sobs_alltime'])
    print(f'legacy starting balance: {start:,}')

    # new ledgered activity
    await sob.adjust_received(GID, uid, 500, event_type=ledger.EVT_DAILY)
    await sob.spend(GID, uid, 200, event_type=ledger.EVT_SHOP_BASE)
    await sob.add_sob(guild_id=GID, message_id=999999, reactor_id=111, target_id=uid, credited_amount=40)
    end = int((await sob.get_user_stats(GID, uid))['sobs_alltime'])

    # the DELTA from new activity must exactly match the ledger net
    r = await ledger.reconcile_user(db, GID, uid, end)
    new_delta_actual = end - start
    new_delta_ledger = r['ledger_net']   # ledger only contains the NEW rows
    print(f'new balance: {end:,}  (net change {new_delta_actual:+,})')
    print(f'ledger net of new activity: {new_delta_ledger:+,}')
    assert new_delta_actual == new_delta_ledger == 340, (new_delta_actual, new_delta_ledger)
    print('✅ legacy balance preserved AND all new activity perfectly tracked by ledger')
    await db.close()

asyncio.run(main())
