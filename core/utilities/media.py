# core/utilities/media.py
"""
Mention-to-download: fetch a public video with yt-dlp and return a temp file path.

Everything here is import-optional and provider-optional:
  - if yt-dlp isn't installed, is_available() is False and callers degrade.
  - if ffmpeg is missing, merging is skipped and we log an admin-facing note.

Privacy/safety:
  - public http(s) only; SSRF-guarded before download.
  - temp files live in a dedicated dir and are ALWAYS deleted by the caller.
  - logs never include full URLs with query tokens (we redact query strings).
"""
from __future__ import annotations

import os
import shutil
import asyncio
import tempfile
from urllib.parse import urlsplit, urlunsplit

from core.utilities.safety import is_safe_url

# ---- config (env, with safe defaults) ----
def _env_bool(name, default):
    v = os.environ.get(name)
    if v is None:
        return default
    return v.strip().lower() in ("1", "true", "yes", "on")

def _env_int(name, default):
    try:
        return int(os.environ.get(name, ""))
    except (TypeError, ValueError):
        return default

ENABLED = lambda: _env_bool("MEDIA_DOWNLOAD_ENABLED", True)
MAX_MB = lambda: _env_int("MEDIA_DOWNLOAD_MAX_MB", 100)
TIMEOUT = lambda: _env_int("MEDIA_DOWNLOAD_TIMEOUT_SECONDS", 90)
USER_COOLDOWN = lambda: _env_int("MEDIA_DOWNLOAD_USER_COOLDOWN_SECONDS", 25)
MAX_CONCURRENT = lambda: _env_int("MEDIA_DOWNLOAD_MAX_CONCURRENT", 2)

TEMP_DIR = os.path.join(tempfile.gettempdir(), "ignio_media")

# domains yt-dlp commonly supports (used only for a friendly "supported?" hint;
# yt-dlp itself decides what it can actually pull)
SUPPORTED_HINTS = (
    "instagram.com", "tiktok.com", "vm.tiktok.com", "twitter.com", "x.com",
    "reddit.com", "v.redd.it", "youtube.com", "youtu.be", "facebook.com",
    "fb.watch", "streamable.com",
)
DIRECT_EXT = (".mp4", ".webm", ".mov")


def redact(url: str) -> str:
    """Strip the query string so logs never leak signed tokens."""
    try:
        s = urlsplit(url)
        return urlunsplit((s.scheme, s.netloc, s.path, "", ""))
    except Exception:
        return "<url>"


def is_available() -> bool:
    try:
        import yt_dlp  # noqa
        return True
    except Exception:
        return False


def ffmpeg_available() -> bool:
    return shutil.which("ffmpeg") is not None


def looks_supported(url: str) -> bool:
    lu = url.lower()
    return any(h in lu for h in SUPPORTED_HINTS) or lu.split("?")[0].endswith(DIRECT_EXT)


class DownloadResult:
    def __init__(self, ok, path=None, title=None, source=None, error=None,
                 too_large=False, url=None, uploader=None, duration=None):
        self.ok = ok
        self.path = path
        self.title = title
        self.source = source
        self.error = error          # unsupported|private|timeout|too_large|temporarily_blocked|ffmpeg|failed
        self.too_large = too_large
        self.url = url              # original post URL (for the source card)
        self.uploader = uploader    # @creator
        self.duration = duration    # seconds


def _source_name(url: str) -> str:
    lu = url.lower()
    table = {
        "instagram.com": "Instagram", "tiktok.com": "TikTok", "vm.tiktok.com": "TikTok",
        "twitter.com": "X/Twitter", "x.com": "X/Twitter", "reddit.com": "Reddit",
        "v.redd.it": "Reddit", "youtube.com": "YouTube", "youtu.be": "YouTube",
        "facebook.com": "Facebook", "fb.watch": "Facebook", "streamable.com": "Streamable",
    }
    for k, v in table.items():
        if k in lu:
            return v
    return "the web"


def _blocking_download(url: str, max_mb: int) -> DownloadResult:
    """Runs in a thread. Downloads with yt-dlp into TEMP_DIR. Caller cleans up."""
    import yt_dlp

    os.makedirs(TEMP_DIR, exist_ok=True)
    out_tmpl = os.path.join(TEMP_DIR, "%(id)s.%(ext)s")
    # prefer a single progressive mp4 <=720p; fall back through to anything playable
    fmt = ("best[ext=mp4][height<=720]/best[ext=mp4]/"
           "best[ext=webm][height<=720]/best[height<=720]/best")
    has_ffmpeg = ffmpeg_available()
    ydl_opts = {
        "format": fmt,
        "outtmpl": out_tmpl,
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "logtostderr": False,
        "verbose": False,
        "max_filesize": max_mb * 1024 * 1024,
        "socket_timeout": 15,
        "retries": 2,
        "fragment_retries": 2,
        "concurrent_fragment_downloads": 4,   # faster multi-fragment pulls
        "nocheckcertificate": False,
        "cookiefile": None,                   # never use cookies / credentials
        "age_limit": 0,
        # a normal browser UA improves success on some public CDNs (not a bypass)
        "http_headers": {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                                       "AppleWebKit/537.36 (KHTML, like Gecko) "
                                       "Chrome/120.0 Safari/537.36"},
    }
    if not has_ffmpeg:
        # don't attempt merges that need ffmpeg
        ydl_opts["format"] = "best[ext=mp4]/best"

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            if info is None:
                return DownloadResult(False, error="unsupported")
            # find the produced file
            path = None
            if "requested_downloads" in info and info["requested_downloads"]:
                path = info["requested_downloads"][0].get("filepath")
            if not path:
                vid = info.get("id", "")
                ext = info.get("ext", "mp4")
                cand = os.path.join(TEMP_DIR, f"{vid}.{ext}")
                if os.path.exists(cand):
                    path = cand
            if not path or not os.path.exists(path):
                return DownloadResult(False, error="failed")
            if os.path.getsize(path) > max_mb * 1024 * 1024:
                return DownloadResult(False, path=path, error="too_large", too_large=True, url=url)
            uploader = info.get("uploader") or info.get("uploader_id") or info.get("channel")
            return DownloadResult(True, path=path,
                                  title=info.get("title"), source=_source_name(url),
                                  url=url, uploader=uploader,
                                  duration=info.get("duration"))
    except Exception as ex:
        msg = str(ex).lower()
        if any(w in msg for w in ("ip address is blocked", "blocked from accessing",
                                  "rate-limit", "rate limit", "429", "forbidden", "403")):
            return DownloadResult(False, error="temporarily_blocked")
        if any(w in msg for w in ("private", "login", "log in", "sign in",
                                  "not available", "members-only", "age", "deleted",
                                  "unavailable", "removed", "this post may not")):
            return DownloadResult(False, error="private")
        if "filesize" in msg or "too large" in msg:
            return DownloadResult(False, error="too_large", too_large=True)
        if "timed out" in msg or "timeout" in msg:
            return DownloadResult(False, error="timeout")
        if "unsupported url" in msg or "no video" in msg or "extractor" in msg:
            return DownloadResult(False, error="unsupported")
        return DownloadResult(False, error="failed")


async def download(url: str, max_mb: int | None = None, timeout: int | None = None) -> DownloadResult:
    """Async wrapper: SSRF-check, then run yt-dlp in a thread with a timeout."""
    # SSRF / safety check FIRST — internal URLs are rejected even if yt-dlp is absent
    ok, _why = is_safe_url(url)
    if not ok:
        return DownloadResult(False, error="unsupported")
    if not is_available():
        return DownloadResult(False, error="failed")
    mb = max_mb or MAX_MB()
    to = timeout or TIMEOUT()
    try:
        return await asyncio.wait_for(
            asyncio.to_thread(_blocking_download, url, mb), timeout=to)
    except asyncio.TimeoutError:
        return DownloadResult(False, error="timeout")
    except Exception:
        return DownloadResult(False, error="failed")


def cleanup(path: str | None):
    """Delete a temp file (and ignore errors)."""
    try:
        if path and os.path.exists(path):
            os.remove(path)
    except Exception:
        pass


async def video_url_to_gif_bytes(url: str, max_seconds: int = 8) -> bytes | None:
    """Download a short public video URL (e.g. a Tenor .mp4) and convert it to a
    GIF with ffmpeg. Returns GIF bytes, or None. Used as a caption fallback when
    the image URL isn't a PIL-openable format."""
    if not ffmpeg_available():
        return None
    from core.utilities.safety import is_safe_url
    ok, _ = is_safe_url(url)
    if not ok:
        return None
    import asyncio as _asyncio
    os.makedirs(TEMP_DIR, exist_ok=True)
    src = os.path.join(TEMP_DIR, f"tsrc_{abs(hash(url)) % 10**8}")
    dst = src + ".gif"
    try:
        # download the video bytes (cap ~20MB)
        import aiohttp
        ua = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15)) as s:
            async with s.get(url, headers={"User-Agent": ua}) as r:
                if r.status != 200:
                    return None
                data = await r.content.read(20 * 1024 * 1024 + 1)
                if not data or len(data) > 20 * 1024 * 1024:
                    return None
        with open(src, "wb") as f:
            f.write(data)
        # ffmpeg: first N seconds, scale to <=400px wide, 12fps, palette for clean gif
        vf = f"fps=12,scale=400:-1:flags=lanczos"
        proc = await _asyncio.create_subprocess_exec(
            "ffmpeg", "-y", "-t", str(max_seconds), "-i", src,
            "-vf", vf, "-loop", "0", dst,
            stdout=_asyncio.subprocess.DEVNULL, stderr=_asyncio.subprocess.DEVNULL)
        try:
            await _asyncio.wait_for(proc.communicate(), timeout=25)
        except _asyncio.TimeoutError:
            proc.kill()
            return None
        if os.path.exists(dst) and os.path.getsize(dst) > 0:
            with open(dst, "rb") as f:
                return f.read()
        return None
    except Exception:
        return None
    finally:
        cleanup(src)
        cleanup(dst)
