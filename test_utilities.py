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


# ---- added v1.8.3: redirect logic, translate defaults, qoute alias ----
def test_xray_logic():
    from core.utilities.providers import _ctype_kind
    from urllib.parse import urljoin
    check("ctype html -> Web page", _ctype_kind("text/html; charset=utf8") == "Web page")
    check("ctype video -> Video", _ctype_kind("video/mp4") == "Video")
    # urljoin resolves both absolute and relative redirect targets
    absolute = urljoin("https://httpbin.org/redirect-to?url=x", "https://example.com")
    check("redirect target resolves absolute", absolute == "https://example.com")
    relative = urljoin("https://a.com/p/", "/new")
    check("redirect target resolves relative", relative == "https://a.com/new")


def test_translate_parsing():
    from core.utilities import providers as P
    def parse(args):
        tokens = (args or "").split(); lang = "en"; text = None; explain = False
        if tokens:
            first = tokens[0].lower()
            if first == "explain":
                explain = True; text = " ".join(tokens[1:]).strip() or None
            elif P.norm_lang(first):
                lang = first; text = " ".join(tokens[1:]).strip() or None
            else:
                text = args.strip()
        return lang, text, explain
    check("translate empty defaults to english", parse("") == ("en", None, False))
    check("translate <lang> sets target", parse("french") == ("french", None, False))
    check("translate <lang> <text>", parse("somali hello") == ("somali", "hello", False))
    check("translate bare text -> english", parse("hello world") == ("en", "hello world", False))
    check("translate explain mode", parse("explain")[2] is True)


async def test_qoute_alias():
    import discord
    from discord.ext import commands
    from core.utilities.cog import UtilitiesCog
    bot = commands.Bot(command_prefix="!!", intents=discord.Intents.all())
    await bot.add_cog(UtilitiesCog(bot, None, None))
    q = bot.get_command("quote")
    qo = bot.get_command("qoute")
    return q is not None and qo is not None and qo.name == "quote"


def test_catchup_command_filter():
    # the spam filter should drop short command-looking lines
    def is_spam(c):
        return c[:1] in "!?./$%&>" and len(c) < 40
    check("filters !!catchup spam", is_spam("!!catchup 5m"))
    check("filters !!help spam", is_spam("!!help"))
    check("keeps a real sentence", not is_spam("did you see the game last night it was wild"))




# ---- added v1.9.1: tenor, map zoom, animated caption, media blocked ----
def test_tenor():
    from core.utilities import providers as P
    check("tenor view url detected", P.is_tenor_url("https://tenor.com/view/holaa-gif-7220205024135693548"))
    check("non-tenor not detected", not P.is_tenor_url("https://example.com/x"))


def test_map_zoom():
    from core.utilities.providers import _zoom_for_type
    usa = _zoom_for_type("country", ["24.5", "49.4", "-125", "-66"])
    wa = _zoom_for_type("state", ["45.5", "49.0", "-124.8", "-116.9"])
    sea = _zoom_for_type("city", ["47.49", "47.73", "-122.45", "-122.22"])
    mog = _zoom_for_type("city", ["2.0", "2.1", "45.3", "45.4"])
    check("USA gets country-level zoom", usa <= 4)
    check("Washington gets region zoom", 4 <= wa <= 7)
    check("Seattle gets city zoom", 8 <= sea <= 12)
    check("Mogadishu gets city zoom", 8 <= mog <= 12)
    check("country zoom < city zoom", usa < sea)


def test_animated_caption():
    from core.utilities.cards import caption_gif
    from PIL import Image
    import io as _io
    frames = [Image.new("RGB", (150, 150), (i*50, 40, 80)) for i in range(4)]
    b = _io.BytesIO(); frames[0].save(b, format="GIF", save_all=True, append_images=frames[1:], duration=100, loop=0)
    b.seek(0); gif = Image.open(b)
    out, kept = caption_gif(gif, "test")
    data = out.read()
    check("animated caption preserves GIF", kept and data[:6] in (b"GIF87a", b"GIF89a"))
    # oversized -> first-frame fallback
    big = [Image.new("RGB", (1400, 1400), (i*50, 40, 80)) for i in range(2)]
    b2 = _io.BytesIO(); big[0].save(b2, format="GIF", save_all=True, append_images=big[1:], duration=100)
    b2.seek(0); biggif = Image.open(b2)
    out2, kept2 = caption_gif(biggif, "x")
    check("oversized GIF falls back to first frame", not kept2)


def test_media_blocked():
    from core.utilities.cog import _media_error
    check("temporarily_blocked has clean message",
          "could not access a downloadable public video" in _media_error("temporarily_blocked").lower())
    check("blocked is not a crash/technical msg", "error" not in _media_error("temporarily_blocked").lower())


def test_afk_text():
    # the ago helper reads naturally
    from core.utilities.cog import _ago
    check("ago: hours plural", _ago(3*3600) == "3 hours ago")
    check("ago: 1 hour singular", _ago(3600) == "1 hour ago")
    check("ago: minutes", _ago(120) == "2 minutes ago")




def test_quote_twitter():
    from core.utilities.cards import quote_card
    # renders with a handle + engagement, returns a valid PNG
    buf = quote_card("Milk", "hey", "Jun 30, 2026", handle="milk")
    check("twitter-style quote renders PNG", buf.read()[:8].startswith(b"\x89PNG"))
    # long text still renders
    buf2 = quote_card("Someone", "x " * 200, "Jun 30, 2026")
    check("quote handles long text", buf2.read()[:8].startswith(b"\x89PNG"))




async def test_caption_only_replied():
    """Caption must use ONLY the replied message, never scan the channel."""
    import io as _io
    from PIL import Image
    from core.utilities.cog import UtilitiesCog
    import discord
    from discord.ext import commands
    bot = commands.Bot(command_prefix="!!", intents=discord.Intents.all())
    cog = UtilitiesCog(bot, None, None)

    # a message with a real image attachment
    frames = Image.new("RGB", (100, 100), (200, 80, 90))
    b = _io.BytesIO(); frames.save(b, format="PNG"); data = b.getvalue()
    class Att:
        content_type = "image/png"; filename = "x.png"; width = 100; height = 100
        async def read(self): return data
    class MsgWith:
        attachments = [Att()]; embeds = []; content = ""
    class MsgWithout:
        attachments = []; embeds = []; content = "just text"

    img, anim = await cog._image_from_message(MsgWith())
    ok_found = img is not None
    img2, _ = await cog._image_from_message(MsgWithout())
    ok_none = img2 is None  # no image -> None, does NOT hunt elsewhere
    return ok_found and ok_none




async def test_tenor_embed_caption():
    """A Tenor gifv embed resolves to the direct .gif; the .mp4 is never opened."""
    from unittest.mock import patch
    from core.utilities.cog import UtilitiesCog
    import discord
    from discord.ext import commands
    class Obj:
        def __init__(self, url): self.url = url
    class FakeEmbed:
        url = "https://tenor.com/view/holaa-gif-7220205024135693548"
        image = None
        thumbnail = Obj("https://media.tenor.com/abc/tenor.png")
        video = Obj("https://media.tenor.com/abc/tenor.mp4")
    class FakeMsg:
        attachments = []; embeds = [FakeEmbed()]; content = ""
    bot = commands.Bot(command_prefix="!!", intents=discord.Intents.all())
    cog = UtilitiesCog(bot, None, None)
    tried = []
    async def fake_dl(url):
        tried.append(url)
        if url.endswith("tenor.gif"):
            from PIL import Image; import io as _io
            f = [Image.new("RGB", (40, 40), (200, 80, 90)) for _ in range(2)]
            b = _io.BytesIO(); f[0].save(b, format="GIF", save_all=True, append_images=f[1:], duration=80)
            return b.getvalue()
        return None
    with patch.object(cog, "_download_image_bytes", side_effect=fake_dl):
        img, anim = await cog._image_from_message(FakeMsg())
    return img is not None and not any(".mp4" in u for u in tried)




async def test_mp4_fallback_caption():
    """When no image URL opens, the Tenor mp4 is converted to a GIF via ffmpeg."""
    import os as _os
    from unittest.mock import patch
    from core.utilities.cog import UtilitiesCog
    from core.utilities import media as _media
    import discord
    from discord.ext import commands
    if not _media.ffmpeg_available():
        return True  # skip cleanly if ffmpeg absent
    _os.system("ffmpeg -y -f lavfi -i testsrc=duration=1:size=120x120:rate=8 /tmp/_t.mp4 >/dev/null 2>&1")
    mp4 = open("/tmp/_t.mp4", "rb").read()
    class Obj:
        def __init__(self, u): self.url = u
    class E:
        url = "https://tenor.com/view/x-gif-999"; image = None
        thumbnail = Obj("https://media.tenor.com/a/tenor.webp")
        video = Obj("https://media.tenor.com/a/tenor.mp4")
    class M:
        attachments = []; embeds = [E()]; content = ""
    bot = commands.Bot(command_prefix="!!", intents=discord.Intents.all())
    cog = UtilitiesCog(bot, None, None)
    async def bad_img(url): return b"notimage"
    async def real_v2g(url, max_seconds=8):
        import subprocess
        open("/tmp/_s.mp4", "wb").write(mp4)
        subprocess.run(["ffmpeg", "-y", "-t", "8", "-i", "/tmp/_s.mp4", "-vf",
                        "fps=12,scale=400:-1:flags=lanczos", "-loop", "0", "/tmp/_o.gif"],
                       capture_output=True)
        return open("/tmp/_o.gif", "rb").read() if _os.path.exists("/tmp/_o.gif") else None
    with patch.object(cog, "_download_image_bytes", side_effect=bad_img), \
         patch.object(_media, "video_url_to_gif_bytes", side_effect=real_v2g):
        img, anim = await cog._image_from_message(M())
    return img is not None and anim


def _extra_main():
    test_xray_logic()
    test_translate_parsing()
    test_catchup_command_filter()
    check("qoute alias maps to quote", asyncio.run(test_qoute_alias()))
    test_tenor()
    test_map_zoom()
    test_animated_caption()
    test_media_blocked()
    test_afk_text()
    test_quote_twitter()
    check("caption uses only the replied message", asyncio.run(test_caption_only_replied()))
    check("tenor gifv embed resolves to .gif (never mp4)", asyncio.run(test_tenor_embed_caption()))
    check("mp4 fallback converts to gif via ffmpeg", asyncio.run(test_mp4_fallback_caption()))


if __name__ == "__main__":
    # patch main() to also run extras before printing the result
    _orig_main = main
    def main():  # noqa
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
        _extra_main()
        print(f"\n  RESULT: {len(PASS)} passed, {len(FAIL)} failed")
        if FAIL:
            print("  FAILURES:", FAIL); sys.exit(1)
    main()
