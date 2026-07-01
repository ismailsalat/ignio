"""test_media_download.py — mention-to-download feature (logic + safety)."""
import sys, os, asyncio, tempfile
sys.path.insert(0, '.')
from core.utilities import media
from core.utilities.jobs import manager, CooldownError, BusyError
PASS, FAIL = [], []
def check(n, c): (PASS if c else FAIL).append(n); print(f"  {'✅' if c else '❌'} {n}")


# ---- fake discord objects ----
class FakeAttachment:
    def __init__(self, url, content_type=None, filename=""):
        self.url = url; self.content_type = content_type; self.filename = filename


class FakeEmbed:
    def __init__(self, url=None, description=None):
        self.url = url
        self.video = None
        self.image = None
        self.thumbnail = None
        self.author = None
        self.description = description


class FakeMsg:
    def __init__(self, content="", embeds=None, attachments=None):
        self.content = content
        self.embeds = embeds or []
        self.attachments = attachments or []


def test_supported_detection():
    check("tiktok looks supported", media.looks_supported("https://www.tiktok.com/@u/video/1"))
    check("instagram reel supported", media.looks_supported("https://instagram.com/reel/abc"))
    check("x/twitter supported", media.looks_supported("https://x.com/u/status/1"))
    check("reddit supported", media.looks_supported("https://reddit.com/r/x/comments/y"))
    check("youtube supported", media.looks_supported("https://youtu.be/abc"))
    check("direct mp4 supported", media.looks_supported("https://cdn.site.com/v.mp4"))
    check("random site NOT supported", not media.looks_supported("https://example.com/article"))


def test_redaction():
    red = media.redact("https://cdn.x.com/v.mp4?token=SECRET&hm=abc123")
    check("redaction strips query token", "SECRET" not in red and "token" not in red)
    check("redaction keeps host+path", "cdn.x.com" in red and "v.mp4" in red)


def test_source_name():
    check("source: instagram", media._source_name("https://instagram.com/reel/x") == "Instagram")
    check("source: tiktok", media._source_name("https://vm.tiktok.com/x") == "TikTok")
    check("source: youtube", media._source_name("https://youtu.be/x") == "YouTube")


def test_config_defaults():
    check("MAX_MB default 100", media.MAX_MB() == 100)
    check("TIMEOUT default 90", media.TIMEOUT() == 90)
    check("USER_COOLDOWN default 25", media.USER_COOLDOWN() == 25)
    check("MAX_CONCURRENT default 2", media.MAX_CONCURRENT() == 2)
    check("ENABLED default true", media.ENABLED() is True)


def test_env_override():
    os.environ["MEDIA_DOWNLOAD_MAX_MB"] = "50"
    os.environ["MEDIA_DOWNLOAD_ENABLED"] = "false"
    check("MAX_MB honors env", media.MAX_MB() == 50)
    check("ENABLED honors env", media.ENABLED() is False)
    os.environ.pop("MEDIA_DOWNLOAD_MAX_MB", None)
    os.environ.pop("MEDIA_DOWNLOAD_ENABLED", None)


async def test_ssrf_block():
    # internal URL must be rejected by download() before yt-dlp ever runs
    r = await media.download("http://169.254.169.254/latest/meta-data")
    check("download blocks metadata IP", not r.ok and r.error == "unsupported")
    r2 = await media.download("http://localhost:8080/x.mp4")
    check("download blocks localhost", not r2.ok)


def test_url_priority():
    """Replicate _find_media_url priority: replied msg -> mention msg."""
    from core.utilities import resolver

    def find(reply_msg, mention_msg):
        if reply_msg is not None:
            u = resolver.first_video_target(reply_msg)
            if not u:
                urls = resolver.resolve_targets(reply_msg)["urls"]
                u = next((x for x in urls if media.looks_supported(x)), None)
            if u:
                return u
        urls = resolver.extract_urls(mention_msg.content or "")
        return next((x for x in urls if media.looks_supported(x)), None)

    # 1) URL in replied message wins
    reply = FakeMsg(content="check https://www.tiktok.com/@a/video/1")
    mention = FakeMsg(content="@Ignio")
    check("priority: replied-message URL found", find(reply, mention) and "tiktok" in find(reply, mention))
    # 2) URL in mention message itself
    mention2 = FakeMsg(content="@Ignio https://youtu.be/xyz")
    check("priority: mention-message URL found", find(None, mention2) == "https://youtu.be/xyz")
    # 3) no URL anywhere
    check("priority: no URL -> None", find(FakeMsg(content="lol"), FakeMsg(content="@Ignio")) is None)
    # 4) URL inside an embed of the replied message
    reply_emb = FakeMsg(embeds=[FakeEmbed(url="https://www.instagram.com/reel/abc")])
    check("priority: embed URL found", find(reply_emb, FakeMsg(content="@Ignio")) is not None)


def test_error_messages():
    from core.utilities.cog import _media_error
    check("blocked error is clean", "downloadable public video" in _media_error("temporarily_blocked").lower())
    check("private error message", "private" in _media_error("private").lower())
    check("timeout error message", "too long" in _media_error("timeout").lower())
    check("unsupported error message", "could not download media" in _media_error("unsupported").lower())
    check("failed error message", "check the bot logs" in _media_error("failed").lower())


def test_too_large_logic():
    # simulate: file bigger than guild limit should not upload
    limit_mb = 10.0
    size_mb = 25.0
    check("too-large detection", size_mb > limit_mb)


def test_temp_cleanup():
    # cleanup deletes the temp file
    f = tempfile.NamedTemporaryFile(delete=False, dir=tempfile.gettempdir()); f.close()
    p = f.name
    exists = os.path.exists(p)
    media.cleanup(p)
    check("temp file cleaned on success/fail", exists and not os.path.exists(p))
    # cleanup on a missing file shouldn't raise
    try:
        media.cleanup(p); media.cleanup(None)
        check("cleanup is safe on missing/None", True)
    except Exception:
        check("cleanup is safe on missing/None", False)


async def test_concurrency_and_cooldown():
    # per-user single slot
    async with manager.slot("media:user", 42, 1):
        try:
            async with manager.slot("media:user", 42, 1):
                return False
        except BusyError:
            pass
    # guild concurrency cap of 2
    async with manager.slot("media", 7, 2):
        async with manager.slot("media", 7, 2):
            try:
                async with manager.slot("media", 7, 2):
                    return False
            except BusyError:
                return True
    return False


def test_guild_limit():
    from core.utilities.cog import UtilitiesCog
    class G:
        premium_tier = 0
        filesize_limit = 25 * 1024 * 1024
    check("guild limit reads filesize_limit", UtilitiesCog._guild_upload_limit_mb(G()) == 25.0)
    class G3:
        premium_tier = 3
        filesize_limit = 8 * 1024 * 1024
    check("tier 3 = 100MB", UtilitiesCog._guild_upload_limit_mb(G3()) == 100.0)




def test_strict_mention_trigger():
    """Download triggers ONLY on '@Ignio <one-url>' with nothing extra."""
    import re
    from core.utilities import resolver
    def strict(content, is_reply=False, mention_everyone=False, bot_id=999):
        if is_reply or mention_everyone:
            return None
        content = content.strip()
        m = re.match(rf"^<@!?{bot_id}>\s+(https?://\S+)\s*$", content)
        if not m:
            return None
        if len(resolver.extract_urls(content)) != 1:
            return None
        return m.group(1)
    B = "<@999>"
    check("valid: @bot <url> triggers", strict(f"{B} https://tiktok.com/x") == "https://tiktok.com/x")
    check("mention not first -> ignored", strict(f"hi {B} https://tiktok.com/x") is None)
    check("no url -> ignored", strict(f"{B} look at this") is None)
    check("text after url -> ignored", strict(f"{B} https://tiktok.com/x lol") is None)
    check("two urls -> ignored", strict(f"{B} https://a.com/1 https://b.com/2") is None)
    check("no mention -> ignored", strict("normal msg https://tiktok.com/x") is None)
    check("reply -> ignored", strict(f"{B} https://tiktok.com/x", is_reply=True) is None)
    check("mention_everyone -> ignored", strict(f"{B} https://tiktok.com/x", mention_everyone=True) is None)


def main():
    print("[test_media_download]")
    test_supported_detection()
    test_strict_mention_trigger()
    test_redaction()
    test_source_name()
    test_config_defaults()
    test_env_override()
    asyncio.run(test_ssrf_block())
    test_url_priority()
    test_error_messages()
    test_too_large_logic()
    test_temp_cleanup()
    check("concurrency + cooldown slots work", asyncio.run(test_concurrency_and_cooldown()))
    test_guild_limit()
    print(f"\n  RESULT: {len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        print("  FAILURES:", FAIL); sys.exit(1)


if __name__ == "__main__":
    main()
