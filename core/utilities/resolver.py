# core/utilities/resolver.py
"""
Shared media resolver. Extracts candidate targets (URLs, attachments) from a
message or a replied-to message, including all the embed fields a video bot
might use. Pure logic — does NOT fetch anything. The caller decides what to do.

Never auto-processes another bot's message: a real user must run the command.
"""
from __future__ import annotations

import re

URL_RE = re.compile(r"https?://[^\s<>\"]+", re.IGNORECASE)

VIDEO_HOST_HINTS = (
    "tiktok.com", "vm.tiktok.com", "twitter.com", "x.com", "fxtwitter.com",
    "youtube.com/shorts", "youtu.be", "youtube.com/watch", "instagram.com/reel",
    "cdn.discordapp.com", "media.discordapp.net",
)
DIRECT_MEDIA_EXT = (".mp4", ".webm", ".mov", ".gif", ".gifv")


def extract_urls(text: str) -> list[str]:
    if not text:
        return []
    return URL_RE.findall(text)


def _embed_urls(embed) -> list[str]:
    """Pull every URL-ish field off a discord.Embed."""
    out = []
    for attr in ("url",):
        v = getattr(embed, attr, None)
        if v:
            out.append(v)
    for obj_attr in ("author", "video", "image", "thumbnail"):
        obj = getattr(embed, obj_attr, None)
        if obj is not None:
            u = getattr(obj, "url", None)
            if u:
                out.append(u)
    desc = getattr(embed, "description", None)
    if desc:
        out.extend(extract_urls(desc))
    return out


def resolve_targets(message) -> dict:
    """
    Inspect one message and return:
      {"urls": [...], "attachments": [...], "video_urls": [...]}
    Attachments are discord.Attachment objects (kept only transiently by caller).
    """
    urls: list[str] = []
    attachments = []
    video_urls: list[str] = []

    # message text
    content = getattr(message, "content", "") or ""
    urls.extend(extract_urls(content))

    # attachments
    for att in getattr(message, "attachments", []) or []:
        ct = (getattr(att, "content_type", None) or "").lower()
        fn = (getattr(att, "filename", "") or "").lower()
        attachments.append(att)
        if ct.startswith("video") or fn.endswith(DIRECT_MEDIA_EXT):
            if getattr(att, "url", None):
                video_urls.append(att.url)

    # embeds (covers other bots' link/video embeds)
    for emb in getattr(message, "embeds", []) or []:
        for u in _embed_urls(emb):
            urls.append(u)

    # classify which urls look like fetchable video
    for u in urls:
        lu = u.lower()
        if any(h in lu for h in VIDEO_HOST_HINTS) or lu.endswith(DIRECT_MEDIA_EXT):
            video_urls.append(u)

    # de-dupe preserving order
    def _uniq(seq):
        seen = set(); out = []
        for x in seq:
            if x not in seen:
                seen.add(x); out.append(x)
        return out

    return {
        "urls": _uniq(urls),
        "attachments": attachments,
        "video_urls": _uniq(video_urls),
    }


def first_video_target(message) -> str | None:
    r = resolve_targets(message)
    return r["video_urls"][0] if r["video_urls"] else None
