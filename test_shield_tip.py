"""Verify the shield tip is quiet & non-bothering: off-switch, rate-limit, skips."""
import asyncio, os, tempfile, sys, time
sys.path.insert(0, '.')
from core.db import Database, DatabaseManager
from core.sob.repo import SobRepo
from core.shop.repo import ShopRepo
from core.economy import Economy
GID = 77
PASS=[]; FAIL=[]
def check(n,c): (PASS if c else FAIL).append(n); print(f"  {'✅' if c else '❌'} {n}")

class _Mgr(DatabaseManager):
    def __init__(s,db): s._db_obj=db
    async def get(s): return s._db_obj

# minimal fake ctx/channel to capture whether a message was sent
class FakeChannel:
    def __init__(s): s.sent=0
    async def send(s, *a, **k): s.sent+=1; return FakeMsg()
class FakeMsg:
    async def edit(s,*a,**k): pass
    async def delete(s): pass
class FakeGuild:
    def __init__(s,gid): s.id=gid
    def get_member(s,i): return None
class FakeCtx:
    def __init__(s,gid): s.guild=FakeGuild(gid); s.channel=FakeChannel()

async def main():
    print("[test_shield_tip]")
    d=tempfile.mkdtemp(); db=Database(os.path.join(d,'t.sqlite3')); await db.connect()
    mgr=_Mgr(db); sob=SobRepo(mgr); eco=Economy(sob); shop=ShopRepo(mgr,sob,eco)
    # build a ShopCog-like shim with just what _maybe_suggest_shield needs
    from core.shop.cog import ShopCog
    cog = ShopCog.__new__(ShopCog)
    cog.shop = shop; cog.economy = eco

    vid = 5
    info = {"victim_id": vid, "lost_today": 3000, "victim_balance": 7000}  # 30% lost -> eligible

    ctx = FakeCtx(GID)
    await cog._maybe_suggest_shield(ctx, info)
    check("shows once on a real hit", ctx.channel.sent == 1)

    # immediate second hit -> rate-limited (6h), no new message
    ctx2 = FakeCtx(GID)
    await cog._maybe_suggest_shield(ctx2, info)
    check("rate-limited: not shown again right away", ctx2.channel.sent == 0)

    # user turns tips off -> never shown even after rate window
    await sob.set_guild_setting(GID, f"shieldtip:off:{vid}", "1")
    await sob.set_guild_setting(GID, f"shieldtip:last:{vid}", "0")  # clear rate limit
    ctx3 = FakeCtx(GID)
    await cog._maybe_suggest_shield(ctx3, info)
    check("user off-switch suppresses it", ctx3.channel.sent == 0)

    # re-enable + small hit -> not shown (below 10% threshold)
    await sob.set_guild_setting(GID, f"shieldtip:off:{vid}", "0")
    await sob.set_guild_setting(GID, f"shieldtip:last:{vid}", "0")
    small = {"victim_id": vid, "lost_today": 100, "victim_balance": 9900}  # 1%
    ctx4 = FakeCtx(GID)
    await cog._maybe_suggest_shield(ctx4, small)
    check("tiny hits never trigger it", ctx4.channel.sent == 0)

    # already shielded -> not shown
    await sob.set_guild_setting(GID, f"shieldtip:last:{vid}", "0")
    await shop.add_effect(GID, vid, "shield", source_user_id=vid, expires_at=int(time.time())+999)
    ctx5 = FakeCtx(GID)
    await cog._maybe_suggest_shield(ctx5, info)
    check("not shown if already protected", ctx5.channel.sent == 0)

    print(f"\n  RESULT: {len(PASS)} passed, {len(FAIL)} failed")
    if FAIL: print("  FAIL:",FAIL); sys.exit(1)
    await db.close()

asyncio.run(main())
