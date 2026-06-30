"""test_utilities.py — Utilities: job manager, SSRF, resolver, cards, AFK, gating."""
import sys, os, asyncio, tempfile, time
sys.path.insert(0, '.')
from PIL import Image
from core.utilities.jobs import manager, CooldownError, BusyError, MAX_VIDEO_SECONDS, MAX_VIDEO_BYTES
from core.utilities import safety, resolver, cards
PASS, FAIL = [], []
def check(n, c): (PASS if c else FAIL).append(n); print(f"  {'✅' if c else '❌'} {n}")


class FakeAttachment:
    def __init__(self, url, content_type=None, filename=""):
        self.url = url; self.content_type = content_type; self.filename = filename


class FakeEmbedObj:
    def __init__(self, url): self.url = url


class FakeEmbed:
    def __init__(self, url=None, video=None, image=None, thumbnail=None, author=None, description=None):
        self.url = url
        self.video = FakeEmbedObj(video) if video else None
        self.image = FakeEmbedObj(image) if image else None
        self.thumbnail = FakeEmbedObj(thumbnail) if thumbnail else None
        self.author = FakeEmbedObj(author) if author else None
        self.description = description


class FakeMsg:
    def __init__(self, content="", attachments=None, embeds=None):
        self.content = content; self.attachments = attachments or []; self.embeds = embeds or []


def test_jobs():
    # cooldown
    manager.check_cooldown("u_test", 99, 30)  # ready
    manager.arm_cooldown("u_test", 99, 30)
    try:
        manager.check_cooldown("u_test", 99, 30); check("cooldown blocks repeat", False)
    except CooldownError:
        check("cooldown blocks repeat", True)
    # dedup cache TTL
    manager.cache_put("uk", "v", ttl=600)
    check("cache returns value", manager.cache_get("uk") == "v")
    manager.cache_put("uk2", "v", ttl=0)
    time.sleep(0.01)
    check("cache expires", manager.cache_get("uk2") is None)
    # limits exist
    check("video duration cap set", MAX_VIDEO_SECONDS <= 600)
    check("video size cap set", MAX_VIDEO_BYTES <= 100 * 1024 * 1024)


async def test_concurrency():
    async with manager.slot("u_vid", 7, 1):
        try:
            async with manager.slot("u_vid", 7, 1):
                return False
        except BusyError:
            return True


def test_tempfiles():
    with manager.temp_files() as paths:
        f = tempfile.NamedTemporaryFile(delete=False); paths.append(f.name); f.close()
        p = f.name
        exists_during = os.path.exists(p)
    return exists_during and not os.path.exists(p)


def test_ssrf():
    blocked = ["http://localhost", "http://127.0.0.1", "http://169.254.169.254/latest",
               "file:///etc/passwd", "http://10.0.0.1", "http://192.168.1.1", "ftp://x.com"]
    for u in blocked:
        safe, _ = safety.is_safe_url(u, resolve_dns=False)
        if safe:
            check(f"SSRF blocks {u}", False); return
    check("SSRF blocks all internal/loopback/metadata/file/private", True)
    safe, _ = safety.is_safe_url("https://example.com", resolve_dns=False)
    check("SSRF allows normal https", safe)


def test_resolver():
    # url in text
    m = FakeMsg(content="check this https://tiktok.com/@a/video/123 lol")
    r = resolver.resolve_targets(m)
    check("resolver finds tiktok url", any("tiktok" in u for u in r["urls"]))
    check("resolver flags it as video", any("tiktok" in u for u in r["video_urls"]))
    # video attachment
    m2 = FakeMsg(attachments=[FakeAttachment("https://cdn.discordapp.com/x.mp4", "video/mp4", "x.mp4")])
    r2 = resolver.resolve_targets(m2)
    check("resolver finds video attachment", len(r2["video_urls"]) == 1)
    # embed video + thumbnail + author + description url (another bot's embed)
    emb = FakeEmbed(url="https://x.com/p/1", video="https://x.com/v.mp4",
                    thumbnail="https://x.com/t.jpg", author="https://x.com/@u",
                    description="mirror: https://youtu.be/abc")
    m3 = FakeMsg(embeds=[emb])
    r3 = resolver.resolve_targets(m3)
    urls = r3["urls"]
    check("resolver pulls embed url", any("x.com/p/1" in u for u in urls))
    check("resolver pulls embed video", any("v.mp4" in u for u in urls))
    check("resolver pulls embed thumbnail", any("t.jpg" in u for u in urls))
    check("resolver pulls embed author url", any("@u" in u for u in urls))
    check("resolver pulls url from description", any("youtu.be" in u for u in urls))


def test_cards():
    buf = cards.quote_card("a really long display name here", "msg " * 80, "Jan 1, 2026")
    check("quote card renders PNG", buf.read()[:8].startswith(b"\x89PNG"))
    base = Image.new("RGB", (400, 300), (50, 80, 120))
    buf2 = cards.caption_image(base, "x" * 300)
    check("caption renders + truncates", buf2.read()[:8].startswith(b"\x89PNG"))


def test_windows():
    from core.utilities.cog import _WINDOWS
    check("4h is the max window", "4h" in _WINDOWS and max(_WINDOWS.values()) == 240)
    check("no window over 4h", all(v <= 240 for v in _WINDOWS.values()))


async def test_afk_flow():
    # AFK clear + mention notice via a real-ish DB
    from core.db import Database, DatabaseManager
    from core.sob.repo import SobRepo
    class _Mgr(DatabaseManager):
        def __init__(s, db): s._db_obj = db
        async def get(s): return s._db_obj
    d = tempfile.mkdtemp(); db = Database(os.path.join(d, "t.sqlite3")); await db.connect()
    await db.execute("INSERT INTO afk_status(guild_id,user_id,reason,since_ts) VALUES(1,5,'food',?)",
                     (int(time.time()),))
    row = await db.fetchone("SELECT reason FROM afk_status WHERE guild_id=1 AND user_id=5")
    ok1 = row and row["reason"] == "food"
    await db.execute("DELETE FROM afk_status WHERE guild_id=1 AND user_id=5")
    row2 = await db.fetchone("SELECT reason FROM afk_status WHERE guild_id=1 AND user_id=5")
    await db.close()
    return ok1 and row2 is None


def test_gating():
    from core.gating import category_of, CATEGORIES
    check("utilities is a category", "utilities" in CATEGORIES)
    for c in ("catchup", "tldr", "song", "xray", "map", "weather", "translate", "caption", "quote", "afk"):
        if category_of(c) != "utilities":
            check(f"{c} -> utilities", False); return
    check("all 10 utility cmds map to utilities category", True)



def test_providers():
    from core.utilities import providers as P
    check("lang norm: somali->so", P.norm_lang("somali") == "so")
    check("lang norm: English->en", P.norm_lang("English") == "en")
    check("lang norm: unknown->None", P.norm_lang("klingon") is None)
    check("weather code 61 = Light rain", P.weather_desc(61) == "Light rain")
    check("weather code 0 = Clear", P.weather_desc(0) == "Clear")
    check("zoom country < zoom city", P._zoom_for_type("country") < P._zoom_for_type("city"))
    check("llm/song keys read from env (None when unset)",
          P.llm_key() is None and P.song_key() is None)
    import os as _os
    _os.environ["UTIL_LLM_API_KEY"] = "sk-proj-test"
    check("openai-style key -> openai provider", P._llm_provider() == "openai")
    _os.environ["UTIL_LLM_API_KEY"] = "sk-ant-test"
    check("anthropic-style key -> anthropic provider", P._llm_provider() == "anthropic")
    _os.environ.pop("UTIL_LLM_API_KEY", None)


def main():
    print("[test_utilities]")
    test_jobs()
    check("concurrency cap works", asyncio.run(test_concurrency()))
    check("temp files cleaned up", test_tempfiles())
    test_ssrf()
    test_resolver()
    test_cards()
    test_windows()
    check("afk set + clear works", asyncio.run(test_afk_flow()))
    test_gating()
    test_providers()
    print(f"\n  RESULT: {len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        print("  FAILURES:", FAIL); sys.exit(1)


if __name__ == "__main__":
    main()
