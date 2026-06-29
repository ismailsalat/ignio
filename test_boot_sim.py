"""Simulate the bot's setup_hook wiring against the real DB (no Discord gateway)."""
import asyncio, json, os, tempfile, sys
sys.path.insert(0, '.')
from core.db import DatabaseManager
from core.sob.repo import SobRepo
from core.economy import Economy
from core.games.engine import GamesEngine
from core.shop.repo import ShopRepo
from core import transfer

async def main():
    d = tempfile.mkdtemp()
    path = os.path.join(d, 'boot.sqlite3')
    # seed from real export the way a live DB would already hold data
    mgr = DatabaseManager(path=path)
    db = await mgr.get()                       # runs migrations 200-214
    await transfer.import_guild(db, json.load(open('/mnt/user-data/uploads/ignio_export_1477356380443902013__3_.json')), mode='replace')

    sob = SobRepo(mgr)
    eco = Economy(sob)
    games = GamesEngine(sob, eco)
    shop = ShopRepo(mgr, sob, eco)
    print('repos constructed OK')

    gid = 1477356380443902013
    # exercise read paths that cogs hit on common commands
    cat = await shop.get_catalog(gid)
    enabled = [c['key'] for c in cat if c['enabled']]
    disabled = [c['key'] for c in cat if not c['enabled']]
    print(f'catalog: {len(cat)} items, {len(enabled)} enabled')
    print(f'  builtin enabled sample: {[k for k in enabled if k in ("shield","freeze","guardian","hunter","reflect","king")]}')

    # economy reads
    print('rate:', await eco.get_rate(gid), '| mult:', round(await eco.get_sob_multiplier(gid),3),
          '| tax%:', await eco.get_tax_pct(gid), '| treasury:', await eco.get_treasury(gid))

    # leaderboard + stats (top user from the real data)
    top = await sob.get_top_alltime(gid, 3)
    print('top3:', [(t['user_id'], t['count']) for t in top])

    # escrow recovery sweep (should be 0 pending in a clean import)
    n = await games.recover_pending()
    print('pending escrow recovered on boot:', n)

    # a full reconciliation report over the whole guild
    rep = await transfer.reconciliation_report(db, gid)
    print(f"reconciliation: {rep['users_reconciled']}/{rep['users_total']} reconcile, "
          f"{rep['users_mismatched']} mismatched (expected: legacy pre-ledger balances)")

    await mgr.close()
    print('BOOT SIMULATION OK')

asyncio.run(main())
