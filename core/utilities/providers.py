# core/utilities/providers.py
"""
Real provider integrations for the Utilities commands.

Defaults are chosen to need NO API key so they work out of the box:
  - weather   : Open-Meteo (free, no key) + Open-Meteo geocoding
  - map       : Nominatim geocoding (free) + OSM static map tile
  - translate : MyMemory translation API (free, no key)
  - xray      : aiohttp redirect-following (no key)
Optional, key-gated (no free no-key option exists):
  - summarize : OpenAI or Anthropic if a key is set (auto-detected)
  - song      : AudD if UTIL_SONG_API_KEY set (also needs audio extraction)

Every call is wrapped so a network/parse failure returns a clean None/!error
instead of throwing. Nothing is cached to disk; the cog uses the in-memory
dedup cache from jobs.py.
"""
from __future__ import annotations

import os
import io
import asyncio

import aiohttp

from core.utilities.safety import is_safe_url

_TIMEOUT = aiohttp.ClientTimeout(total=12)
_UA = {"User-Agent": "IgnioBot/1.0 (Discord utility; contact server admin)"}
_MAX_BYTES = 4 * 1024 * 1024


async def _get_json(url: str, params: dict | None = None, headers: dict | None = None):
    async with aiohttp.ClientSession(timeout=_TIMEOUT) as s:
        async with s.get(url, params=params, headers={**_UA, **(headers or {})}) as r:
            if r.status != 200:
                return None
            return await r.json(content_type=None)


# --------------------------------------------------------------------------- #
# WEATHER — Open-Meteo (no key)
# --------------------------------------------------------------------------- #
async def geocode(place: str):
    """Return up to 3 candidates: [{name, lat, lon, country, admin1}]."""
    data = await _get_json(
        "https://geocoding-api.open-meteo.com/v1/search",
        {"name": place, "count": 3, "language": "en", "format": "json"})
    if not data or not data.get("results"):
        return []
    out = []
    for r in data["results"][:3]:
        out.append({
            "name": r.get("name"),
            "lat": r.get("latitude"),
            "lon": r.get("longitude"),
            "country": r.get("country"),
            "admin1": r.get("admin1"),
        })
    return out


async def weather(place: str, us_units_default: bool = True):
    """Return a compact weather dict, or None."""
    spots = await geocode(place)
    if not spots:
        return None
    spot = spots[0]
    # US places -> Fahrenheit, else Celsius
    is_us = (spot.get("country") == "United States")
    unit = "fahrenheit" if is_us else "celsius"
    data = await _get_json(
        "https://api.open-meteo.com/v1/forecast",
        {
            "latitude": spot["lat"], "longitude": spot["lon"],
            "current": "temperature_2m,apparent_temperature,weather_code",
            "daily": "temperature_2m_max,temperature_2m_min",
            "temperature_unit": unit,
            "timezone": "auto", "forecast_days": 2,
        })
    if not data:
        return None
    cur = data.get("current", {})
    daily = data.get("daily", {})
    deg = "°F" if is_us else "°C"
    label = spot["name"]
    if spot.get("admin1"):
        label += f", {spot['admin1']}"
    return {
        "label": label,
        "now": cur.get("temperature_2m"),
        "feels": cur.get("apparent_temperature"),
        "code": cur.get("weather_code"),
        "today_max": (daily.get("temperature_2m_max") or [None])[0],
        "today_min": (daily.get("temperature_2m_min") or [None])[0],
        "tom_max": (daily.get("temperature_2m_max") or [None, None])[1],
        "tom_min": (daily.get("temperature_2m_min") or [None, None])[1],
        "deg": deg,
        "candidates": spots,
    }


WEATHER_CODES = {
    0: "Clear", 1: "Mainly clear", 2: "Partly cloudy", 3: "Overcast",
    45: "Fog", 48: "Rime fog", 51: "Light drizzle", 53: "Drizzle",
    55: "Heavy drizzle", 61: "Light rain", 63: "Rain", 65: "Heavy rain",
    71: "Light snow", 73: "Snow", 75: "Heavy snow", 80: "Showers",
    81: "Showers", 82: "Violent showers", 95: "Thunderstorm",
    96: "Thunderstorm + hail", 99: "Thunderstorm + hail",
}


def weather_desc(code) -> str:
    return WEATHER_CODES.get(code, "—")


# --------------------------------------------------------------------------- #
# MAP — Nominatim geocode + OSM static map image
# --------------------------------------------------------------------------- #
async def geocode_osm(place: str):
    """Nominatim geocoding; returns up to 3 {display_name, lat, lon, type}."""
    data = await _get_json(
        "https://nominatim.openstreetmap.org/search",
        {"q": place, "format": "json", "limit": 3, "addressdetails": 0},
        headers={"Accept-Language": "en"})
    if not data:
        return []
    return [{
        "display_name": d.get("display_name"),
        "lat": float(d["lat"]), "lon": float(d["lon"]),
        "type": d.get("type", "place"),
        "importance": d.get("importance", 0),
        "bbox": d.get("boundingbox"),
    } for d in data]


def _zoom_for_type(t: str, bbox=None) -> int:
    # if we have a bounding box, compute a zoom that frames it
    if bbox and len(bbox) == 4:
        try:
            south, north = float(bbox[0]), float(bbox[1])
            west, east = float(bbox[2]), float(bbox[3])
            import math
            lat_span = abs(north - south)
            lon_span = abs(east - west)
            span = max(lat_span, lon_span, 0.0005)
            # 360 deg at zoom 0 across the world; pick zoom so span ~fills the view
            z = int(math.log2(360.0 / span)) - 1
            return max(2, min(15, z))
        except Exception:
            pass
    # fallback by place type
    if t in ("country",):
        return 4
    if t in ("state", "administrative", "region", "province"):
        return 6
    if t in ("county", "metropolitan"):
        return 8
    if t in ("city", "town"):
        return 11
    if t in ("village", "suburb", "neighbourhood", "hamlet"):
        return 13
    if t in ("road", "house", "building", "address", "shop", "amenity"):
        return 15
    return 11


async def static_map_png(lat: float, lon: float, zoom: int) -> bytes | None:
    """Build a small static map centered exactly on (lat, lon) with a pin.

    Stitches a 3x3 block of OSM tiles, then crops a window centered on the
    EXACT fractional pixel position of the point (not the tile corner), so the
    marker and the map are both perfectly centered.
    """
    import math
    try:
        from PIL import Image, ImageDraw
    except Exception:
        return None
    n = 2 ** zoom
    xt = (lon + 180.0) / 360.0 * n
    yt = (1.0 - math.log(math.tan(math.radians(lat)) + 1 / math.cos(math.radians(lat))) / math.pi) / 2.0 * n
    cx, cy = int(xt), int(yt)
    fx, fy = xt - cx, yt - cy  # fractional position inside the center tile

    # 5x4 tile grid; center tile (cx,cy) is pasted at (512,256) so there's
    # always slack to center the crop on the point without clamping.
    # background = ocean color so any uncovered area blends in (not white).
    OCEAN = (170, 211, 223)
    canvas = Image.new("RGB", (1280, 1024), OCEAN)
    base_x, base_y = 2, 2  # center tile offset in the grid
    async with aiohttp.ClientSession(timeout=_TIMEOUT) as s:
        for dx in (-2, -1, 0, 1, 2):
            for dy in (-2, -1, 0, 1):
                tx, ty = cx + dx, cy + dy
                # longitude wraps around the globe, so wrap tx instead of skipping
                tx = tx % n
                if not (0 <= ty < n):
                    continue
                url = f"https://tile.openstreetmap.org/{zoom}/{tx}/{ty}.png"
                try:
                    async with s.get(url, headers=_UA) as r:
                        if r.status != 200:
                            continue
                        raw = await r.read()
                    tile = Image.open(io.BytesIO(raw)).convert("RGB")
                    canvas.paste(tile, ((dx + base_x) * 256, (dy + base_y) * 256))
                except Exception:
                    continue

    # exact pixel of the point on the canvas
    point_x = base_x * 256 + fx * 256
    point_y = base_y * 256 + fy * 256
    cw, ch = 640, 400
    left = int(point_x - cw / 2)
    top = int(point_y - ch / 2)
    left = max(0, min(1280 - cw, left))
    top = max(0, min(1024 - ch, top))
    crop = canvas.crop((left, top, left + cw, top + ch))

    # marker at the point's position within the crop
    mx = int(point_x - left)
    my = int(point_y - top)
    d = ImageDraw.Draw(crop)
    # pin: teardrop-ish (circle + stem) so it clearly marks the spot
    d.ellipse([mx - 9, my - 9, mx + 9, my + 9], fill=(228, 70, 70), outline=(255, 255, 255), width=3)
    d.ellipse([mx - 3, my - 3, mx + 3, my + 3], fill=(255, 255, 255))
    buf = io.BytesIO()
    crop.save(buf, format="PNG")
    buf.seek(0)
    return buf.read()


# --------------------------------------------------------------------------- #
# TRANSLATE — MyMemory (no key)
# --------------------------------------------------------------------------- #
_LANG = {
    "en": "en", "english": "en", "somali": "so", "so": "so", "arabic": "ar",
    "ar": "ar", "spanish": "es", "es": "es", "french": "fr", "fr": "fr",
    "german": "de", "de": "de", "turkish": "tr", "tr": "tr", "urdu": "ur",
    "hindi": "hi", "russian": "ru", "ru": "ru", "chinese": "zh", "zh": "zh",
    "japanese": "ja", "ja": "ja", "korean": "ko", "portuguese": "pt",
    "italian": "it", "dutch": "nl", "swedish": "sv", "polish": "pl",
}


def norm_lang(s: str) -> str | None:
    return _LANG.get((s or "").strip().lower())


async def translate(text: str, target_lang: str):
    """MyMemory translate. Auto-detects source. Returns {translated, detected}."""
    tgt = norm_lang(target_lang)
    if not tgt:
        return None
    data = await _get_json(
        "https://api.mymemory.translated.net/get",
        {"q": text[:480], "langpair": f"autodetect|{tgt}"})
    if not data or "responseData" not in data:
        return None
    rd = data["responseData"]
    return {"translated": rd.get("translatedText", ""), "match": rd.get("match", 0)}


# --------------------------------------------------------------------------- #
# XRAY — follow redirects with aiohttp (no key)
# --------------------------------------------------------------------------- #
async def xray(url: str):
    """Follow HTTP redirects safely and report the final destination.

    Uses manual redirect following so every hop (including the final one) is
    re-validated against the SSRF guard before we ever connect to it. Counts
    redirects accurately and never claims a redirect that didn't happen.
    """
    from urllib.parse import urljoin
    safe, reason = is_safe_url(url)
    if not safe:
        return {"blocked": reason}

    REDIRECT_CODES = (301, 302, 303, 307, 308)
    MAX_REDIRECTS = 5
    cur = url
    history = []          # URLs we were redirected FROM
    ctype = "unknown"
    status = None
    try:
        async with aiohttp.ClientSession(timeout=_TIMEOUT) as s:
            for _ in range(MAX_REDIRECTS + 1):
                # re-validate EVERY hop before connecting (SSRF / DNS rebinding)
                ok, why = is_safe_url(cur)
                if not ok:
                    return {"blocked": why, "hops": len(history), "final": cur}
                async with s.get(cur, allow_redirects=False, headers=_UA) as r:
                    status = r.status
                    ctype = (r.headers.get("Content-Type") or "unknown").split(";")[0].strip()
                    loc = r.headers.get("Location")
                    if status in REDIRECT_CODES and loc:
                        nxt = urljoin(cur, loc)   # handles relative AND absolute
                        if nxt == cur:
                            break                  # self-redirect guard
                        history.append(cur)
                        cur = nxt
                        continue
                    break
            else:
                # hit the redirect cap
                return {"final": cur, "hops": len(history), "content_type": ctype,
                        "kind": _ctype_kind(ctype), "status": status, "capped": True}
    except Exception:
        # network error — report what we have, don't crash
        return {"final": cur, "hops": len(history), "content_type": ctype,
                "kind": _ctype_kind(ctype), "status": status, "error": True}

    return {"final": cur, "hops": len(history), "content_type": ctype,
            "kind": _ctype_kind(ctype), "status": status}


def _ctype_kind(ctype: str) -> str:
    ctype = (ctype or "").lower()
    if "video" in ctype:
        return "Video"
    if "image" in ctype:
        return "Image"
    if "html" in ctype:
        return "Web page"
    if "json" in ctype or "text" in ctype:
        return "Text/Data"
    return "Unknown"


# --------------------------------------------------------------------------- #
# SUMMARIZE / TRANSLATE-EXPLAIN — OpenAI or Anthropic (optional key)
# --------------------------------------------------------------------------- #
def llm_key() -> str | None:
    """Either provider's key enables LLM features."""
    return (os.environ.get("UTIL_LLM_API_KEY")
            or os.environ.get("OPENAI_API_KEY")
            or os.environ.get("ANTHROPIC_API_KEY")
            or None)


def _llm_provider() -> str:
    """Decide which API to call based on which key/env is set.
    Force with UTIL_LLM_PROVIDER=openai|anthropic; otherwise auto-detect:
    an 'sk-' key is OpenAI, 'sk-ant-' is Anthropic."""
    forced = (os.environ.get("UTIL_LLM_PROVIDER") or "").lower()
    if forced in ("openai", "anthropic"):
        return forced
    if os.environ.get("OPENAI_API_KEY"):
        return "openai"
    if os.environ.get("ANTHROPIC_API_KEY"):
        return "anthropic"
    k = os.environ.get("UTIL_LLM_API_KEY", "")
    if k.startswith("sk-ant-"):
        return "anthropic"
    if k.startswith("sk-"):
        return "openai"
    return "openai"  # sensible default


async def llm_complete(system: str, user: str, max_tokens: int = 400) -> str | None:
    key = llm_key()
    if not key:
        return None
    provider = _llm_provider()
    try:
        if provider == "anthropic":
            model = os.environ.get("UTIL_LLM_MODEL", "claude-3-5-haiku-20241022")
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30)) as s:
                async with s.post(
                    "https://api.anthropic.com/v1/messages",
                    headers={"x-api-key": key, "anthropic-version": "2023-06-01",
                             "content-type": "application/json"},
                    json={"model": model, "max_tokens": max_tokens, "system": system,
                          "messages": [{"role": "user", "content": user}]},
                ) as r:
                    if r.status != 200:
                        return None
                    data = await r.json()
                    parts = data.get("content", [])
                    return "".join(p.get("text", "") for p in parts
                                   if p.get("type") == "text").strip()
        else:  # openai
            model = os.environ.get("UTIL_LLM_MODEL", "gpt-4o-mini")
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30)) as s:
                async with s.post(
                    "https://api.openai.com/v1/chat/completions",
                    headers={"Authorization": f"Bearer {key}",
                             "content-type": "application/json"},
                    json={"model": model, "max_tokens": max_tokens,
                          "messages": [{"role": "system", "content": system},
                                       {"role": "user", "content": user}]},
                ) as r:
                    if r.status != 200:
                        # log status + short body (NEVER the key/headers) for debugging
                        try:
                            body = (await r.text())[:300]
                        except Exception:
                            body = ""
                        print(f"[Ignio][LLM] OpenAI {r.status} for model '{model}': {body}")
                        return None
                    data = await r.json()
                    choices = data.get("choices", [])
                    if not choices:
                        print("[Ignio][LLM] OpenAI returned no choices.")
                        return None
                    return (choices[0].get("message", {}).get("content") or "").strip()
    except Exception:
        return None


# --------------------------------------------------------------------------- #
# TENOR — resolve a tenor.com/view page to its direct GIF/MP4 media URL
# --------------------------------------------------------------------------- #
import re as _re

_TENOR_VIEW = _re.compile(r"https?://(?:www\.)?tenor\.com/view/[^\s]+", _re.I)


def is_tenor_url(url: str) -> bool:
    return bool(url) and "tenor.com/view/" in url.lower()


async def resolve_tenor(url: str) -> dict | None:
    """Fetch a Tenor view page and pull the direct media URL from its meta tags.
    Returns {gif, mp4} (either may be None) or None on failure. No API key."""
    ok, _ = is_safe_url(url)
    if not ok:
        return None
    try:
        async with aiohttp.ClientSession(timeout=_TIMEOUT) as s:
            async with s.get(url, headers=_UA) as r:
                if r.status != 200:
                    return None
                html = await r.text()
    except Exception:
        return None

    def _meta(prop):
        m = _re.search(
            r'<meta[^>]+(?:property|name)=["\']%s["\'][^>]+content=["\']([^"\']+)["\']' % _re.escape(prop),
            html, _re.I)
        if not m:
            m = _re.search(
                r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+(?:property|name)=["\']%s["\']' % _re.escape(prop),
                html, _re.I)
        return m.group(1) if m else None

    gif = _meta("og:image")
    mp4 = _meta("og:video") or _meta("og:video:secure_url")
    # tenor og:image is usually the direct .gif on media.tenor.com
    if gif and not gif.lower().endswith((".gif", ".png", ".jpg", ".jpeg", ".webp")):
        # sometimes og:image is a preview; still usable as a still frame
        pass
    if not gif and not mp4:
        return None
    return {"gif": gif, "mp4": mp4}
def song_key() -> str | None:
    return os.environ.get("UTIL_SONG_API_KEY") or None


async def song_recognize(audio_url: str):
    key = song_key()
    if not key:
        return None
    try:
        async with aiohttp.ClientSession(timeout=_TIMEOUT) as s:
            async with s.post("https://api.audd.io/",
                              data={"api_token": key, "url": audio_url,
                                    "return": "spotify"}) as r:
                if r.status != 200:
                    return None
                data = await r.json()
                res = data.get("result")
                if not res:
                    return None
                return {"title": res.get("title"), "artist": res.get("artist"),
                        "url": (res.get("spotify") or {}).get("external_urls", {}).get("spotify")}
    except Exception:
        return None
