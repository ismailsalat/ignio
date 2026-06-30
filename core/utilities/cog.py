# core/utilities/cog.py
"""
Utilities cog for Ignio — lightweight tools for content already in chat.

Design rules (enforced here):
- AllowedMentions.none() on every response; never pings.
- No permanent storage of messages, media, URLs, transcripts, or summaries.
  (Only !afk persists a per-user status row — never message content.)
- External providers are optional via env; missing provider => graceful message.
- Cooldowns + per-guild concurrency via the shared job manager.
- Compact embeds / single attachments; "working..." then edit, never spam.
"""
from __future__ import annotations

import io
import os
import re
import time

import discord
from discord.ext import commands

from core.utilities.jobs import manager, CooldownError, BusyError
from core.utilities import resolver, safety, cards
from core.utilities import providers as P
from core.utilities import media

NONE = discord.AllowedMentions.none()
ACCENT = 0x6FB7B0
WARN = 0xE0A042

# ---- time-window parsing for catchup ----
_WINDOWS = {"5m": 5, "15m": 15, "30m": 30, "1h": 60, "2h": 120, "4h": 240}


def _compact(title: str, body: str, color=ACCENT) -> discord.Embed:
    e = discord.Embed(color=color)
    e.description = f"**{title}**\n{body}" if title else body
    return e


class UtilitiesCog(commands.Cog):
    def __init__(self, bot, settings, sob_repo=None):
        self.bot = bot
        self.settings = settings
        self.repo = sob_repo
        self._afk_notice: dict[tuple[int, int, int], float] = {}  # (g,ch,target)->ts

    async def _enabled(self, gid: int) -> bool:
        if self.repo is None:
            return True
        return (await self.repo.get_guild_setting(gid, "utilities:enabled")) != "0"

    async def cog_check(self, ctx):
        # gate the whole category by the per-guild toggle
        if ctx.guild and not await self._enabled(ctx.guild.id):
            return False
        return True

    # ------------------------------------------------------------------ #
    # !catchup
    # ------------------------------------------------------------------ #
    @commands.command(name="catchup", aliases=["context", "catcup"])
    @commands.guild_only()
    async def catchup(self, ctx: commands.Context, window: str = "30m"):
        try:
            manager.check_cooldown("catchup", ctx.author.id, 45)
        except CooldownError as e:
            await ctx.reply(embed=_compact("Slow down", f"Try again in {e.retry_after:.0f}s.", WARN),
                            allowed_mentions=NONE)
            return

        ref = ctx.message.reference
        try:
            async with manager.slot("catchup", ctx.guild.id, 1):
                manager.arm_cooldown("catchup", ctx.author.id, 45)
                working = await ctx.reply(embed=_compact("Catching up…", "Reading the channel…"),
                                          allowed_mentions=NONE)
                if ref is not None:
                    await self._catchup_reply(ctx, working)
                else:
                    await self._catchup_window(ctx, working, window)
        except BusyError:
            await ctx.reply(embed=_compact("Busy", "A catchup is already running here — one sec.", WARN),
                            allowed_mentions=NONE)

    async def _read_recent(self, channel, minutes: int, cap: int):
        """Fetch recent messages WITHOUT storing them anywhere."""
        after = discord.utils.utcnow() - __import__("datetime").timedelta(minutes=minutes)
        msgs = []
        async for m in channel.history(limit=cap, after=after, oldest_first=True):
            if m.author.bot or not m.content:
                continue
            c = m.content.strip()
            # skip obvious command spam (any common prefix) so it doesn't pollute the summary
            if c[:1] in "!?./$%&>" and len(c) < 40:
                continue
            msgs.append(c)
        return msgs

    async def _catchup_window(self, ctx, working, window):
        minutes = _WINDOWS.get((window or "").lower())
        if minutes is None:
            await working.edit(embed=_compact(
                "Pick a window", "Use one of: 5m, 15m, 30m, 1h, 2h, 4h.", WARN))
            return
        msgs = await self._read_recent(ctx.channel, minutes, 120)
        if not msgs:
            await working.edit(embed=_compact(f"Catchup — last {window}",
                                              f"Nothing important was said in the last {window}."))
            return
        summary = await self._summarize_chat(msgs, window)
        if summary is None:
            await working.edit(embed=_compact("Catchup",
                "Catchup could not run right now. An admin can check the bot logs.", WARN))
            return
        await working.edit(embed=_compact(f"Catchup — last {window}", summary))

    async def _catchup_reply(self, ctx, working):
        try:
            target = await ctx.channel.fetch_message(ctx.message.reference.message_id)
        except Exception:
            await working.edit(embed=_compact("Hmm", "I couldn't read that message.", WARN))
            return
        age = (discord.utils.utcnow() - target.created_at).total_seconds()
        if age > 4 * 3600:
            await working.edit(embed=_compact("Too old",
                "That message is outside the short context window, so I cannot safely pull "
                "the full story anymore.", WARN))
            return
        # ±10 min around the target, max 60 messages
        import datetime as _dt
        lo = target.created_at - _dt.timedelta(minutes=10)
        hi = target.created_at + _dt.timedelta(minutes=10)
        msgs = []
        async for m in ctx.channel.history(limit=60, after=lo, before=hi, oldest_first=True):
            if m.author.bot or not m.content:
                continue
            msgs.append(m.content)
        if not msgs:
            await working.edit(embed=_compact("What happened here", "Not enough nearby context to tell."))
            return
        summary = await self._summarize_chat(msgs, "around that message", reply=True)
        if summary is None:
            await working.edit(embed=_compact("Catchup",
                "Catchup could not run right now. An admin can check the bot logs.", WARN))
            return
        await working.edit(embed=_compact("What happened here", summary))

    async def _summarize_chat(self, msgs, window, reply=False):
        """Summarize via the configured LLM. Returns the summary text, or None on
        failure (the caller shows a clean error + we log the real reason)."""
        if not P.llm_key():
            return ("• Smart summaries need an AI provider that isn't set up yet.\n"
                    "• Ask an admin to set `UTIL_LLM_API_KEY` to enable this.\n"
                    f"• (I read {len(msgs)} recent messages but won't store them.)")
        joined = "\n".join(m[:300] for m in msgs)[:6000]
        if reply:
            system = ("You explain what led to a specific Discord message, in 2-4 short bullets. "
                      "Be natural and neutral. Explain how it started, the misunderstanding if any, "
                      "and what it became. No usernames unless needed, no slurs, no filler.")
            prompt = f"Messages around the target (oldest first):\n{joined}"
        else:
            system = ("You catch a friend up on a Discord channel in AT MOST 4 short bullets — fewer is "
                      "better. Only mention things that ACTUALLY happened: a decision, an event time, a "
                      "question people are answering, an argument, or what a discussed link/clip was about. "
                      "If it was mostly memes/chat, say that plainly and name the funniest bit. "
                      "If nothing meaningful happened, say so in one line. "
                      "NEVER force sections. NEVER write 'Main Topic', 'What Changed', 'Important Link', "
                      "'Current Joke/Debate', 'Unanswered Question', 'none currently present', or 'no ongoing "
                      "joke noted'. Don't call every TikTok/GIF/link important. No raw URLs, no usernames "
                      "unless needed to explain an update. Sound casual, not like a meeting summary.")
            prompt = f"Recent messages (last {window}, oldest first):\n{joined}"
        try:
            out = await P.llm_complete(system, prompt, max_tokens=380)
        except Exception as ex:
            # log the real reason WITHOUT any keys/headers (llm_complete never logs them)
            print(f"[Ignio][Catchup] LLM call raised: {type(ex).__name__}: {ex}")
            return None
        if not out:
            print(f"[Ignio][Catchup] LLM returned no text "
                  f"(provider={P._llm_provider()}, msgs={len(msgs)}). "
                  f"Check UTIL_LLM_API_KEY / model name / quota.")
            return None
        return out

    # ------------------------------------------------------------------ #
    # !tldr
    # ------------------------------------------------------------------ #
    @commands.command(name="tldr")
    @commands.guild_only()
    async def tldr(self, ctx: commands.Context, *, text: str = None):
        try:
            manager.check_cooldown("tldr", ctx.author.id, 30)
        except CooldownError as e:
            await ctx.reply(embed=_compact("Slow down", f"Try again in {e.retry_after:.0f}s.", WARN),
                            allowed_mentions=NONE)
            return
        manager.arm_cooldown("tldr", ctx.author.id, 30)
        src = await self._gather_source_text(ctx, text)
        if not src:
            await ctx.reply(embed=_compact("TL;DR",
                "Reply to a message/link/video, or give me some text to shorten.", WARN),
                allowed_mentions=NONE)
            return
        if not P.llm_key():
            await ctx.reply(embed=_compact("TL;DR",
                "Smart summaries need an AI provider (`UTIL_LLM_API_KEY`) that isn't configured yet."),
                allowed_mentions=NONE)
            return
        working = await ctx.reply(embed=_compact("TL;DR", "Reading this…"), allowed_mentions=NONE)
        out = await P.llm_complete(
            "Summarize what the user gives you in AT MOST 3 short bullets — often 1 or 2 is better. "
            "Sound like a friend who actually read it and is telling you the point in 5 seconds. "
            "Be specific to THIS content. NEVER use vague filler like 'relatable experience', "
            "'chaotic nature', 'fostering community', 'why it matters', 'main point', or 'key claim'. "
            "If you only have a title/caption (no transcript), START with 'Based on the caption,' and "
            "don't pretend you watched it. If there's not enough to summarize, reply with exactly: "
            "I found the post, but I couldn't access enough audio or text to summarize it accurately. "
            "No preamble, no labels, no URLs.",
            src[:6000], max_tokens=220)
        if not out:
            await working.edit(embed=_compact("TL;DR",
                "I couldn't summarize that right now.", WARN))
            return
        await working.edit(embed=_compact("TL;DR", out))

    async def _gather_source_text(self, ctx, text):
        if text:
            return text[:8000]
        ref = ctx.message.reference
        if ref:
            try:
                t = await ctx.channel.fetch_message(ref.message_id)
                return (t.content or "")[:8000]
            except Exception:
                return None
        return None

    # ------------------------------------------------------------------ #
    # !song
    # ------------------------------------------------------------------ #
    @commands.command(name="song")
    @commands.guild_only()
    async def song(self, ctx: commands.Context, *, url: str = None):
        try:
            manager.check_cooldown("song", ctx.author.id, 90)
        except CooldownError as e:
            await ctx.reply(embed=_compact("Slow down", f"Try again in {e.retry_after:.0f}s.", WARN),
                            allowed_mentions=NONE)
            return
        manager.arm_cooldown("song", ctx.author.id, 90)
        if not P.song_key():
            await ctx.reply(embed=_compact("Song ID",
                "Song matching needs a provider (`UTIL_SONG_API_KEY`) that isn't configured yet."),
                allowed_mentions=NONE)
            return
        # find a media URL from the arg or the replied message
        target = url
        if not target and ctx.message.reference:
            try:
                t = await ctx.channel.fetch_message(ctx.message.reference.message_id)
                target = resolver.first_video_target(t)
            except Exception:
                target = None
        if not target:
            await ctx.reply(embed=_compact("Song",
                "Reply **directly to a video, audio file, or supported clip** "
                "(or pass a link) so I can listen for the song.", WARN),
                allowed_mentions=NONE)
            return
        working = await ctx.reply(embed=_compact("Song", "Listening…"), allowed_mentions=NONE)
        try:
            async with manager.slot("song", ctx.guild.id, 1):
                res = await P.song_recognize(target)
        except BusyError:
            await working.edit(embed=_compact("Song", "Busy with another track — try again shortly.", WARN))
            return
        except Exception:
            res = None
        if not res or not res.get("title"):
            await working.edit(embed=_compact("Song", "I could not access usable audio from this post."))
            return
        body = f"**{res['title']}** — {res.get('artist','?')}"
        if res.get("url"):
            body += f"\n[Open source]({res['url']})"
        await working.edit(embed=_compact("Song found", body))

    # ------------------------------------------------------------------ #
    # !xray
    # ------------------------------------------------------------------ #
    @commands.command(name="xray")
    @commands.guild_only()
    async def xray(self, ctx: commands.Context, url: str = None):
        try:
            manager.check_cooldown("xray", ctx.author.id, 45)
        except CooldownError as e:
            await ctx.reply(embed=_compact("Slow down", f"Try again in {e.retry_after:.0f}s.", WARN),
                            allowed_mentions=NONE)
            return
        if not url and ctx.message.reference:
            try:
                t = await ctx.channel.fetch_message(ctx.message.reference.message_id)
                urls = resolver.resolve_targets(t)["urls"]
                url = urls[0] if urls else None
            except Exception:
                url = None
        if not url:
            await ctx.reply(embed=_compact("Link X-ray", "Give me a link, or reply to one.", WARN),
                            allowed_mentions=NONE)
            return
        safe, reason = safety.is_safe_url(url)
        manager.arm_cooldown("xray", ctx.author.id, 45)
        if not safe:
            await ctx.reply(embed=_compact("Link X-ray",
                f"• That link is blocked: {reason}\n• I won't open private or unsafe addresses."),
                allowed_mentions=NONE)
            return
        working = await ctx.reply(embed=_compact("Link X-ray", "Inspecting the link…"),
                                  allowed_mentions=NONE)
        try:
            async with manager.slot("xray", ctx.guild.id, 2):
                res = await P.xray(url)
        except BusyError:
            await working.edit(embed=_compact("Link X-ray", "Busy scanning other links — try again shortly.", WARN))
            return
        except Exception:
            res = None
        from urllib.parse import urlparse
        if not res:
            await working.edit(embed=_compact("Link X-ray", "I couldn't inspect that link.", WARN))
            return
        if res.get("blocked"):
            await working.edit(embed=_compact("Link X-ray",
                f"• Blocked: {res['blocked']}\n• I won't follow that link."))
            return
        opens = urlparse(url).hostname or "unknown"
        dest = urlparse(res["final"]).hostname or opens
        body = (f"• Opens to: `{opens}`\n"
                f"• Final destination: `{dest}`\n"
                f"• Redirects: {res['hops']}\n"
                f"• Content: {res['kind']}\n"
                f"• Risk signals: none obvious — *“no known warning” is not a safety guarantee.*")
        await working.edit(embed=_compact("Link X-ray", body))

    # ------------------------------------------------------------------ #
    # !map
    # ------------------------------------------------------------------ #
    @commands.command(name="map")
    @commands.guild_only()
    async def map_cmd(self, ctx: commands.Context, *, place: str = None):
        try:
            manager.check_cooldown("map", ctx.author.id, 15)
        except CooldownError as e:
            await ctx.reply(embed=_compact("Slow down", f"Try again in {e.retry_after:.0f}s.", WARN),
                            allowed_mentions=NONE)
            return
        if not place:
            await ctx.reply(embed=_compact("Map", "Give me a place: `!map seattle`", WARN),
                            allowed_mentions=NONE)
            return
        manager.arm_cooldown("map", ctx.author.id, 15)
        working = await ctx.reply(embed=_compact("Map", "Finding that place…"), allowed_mentions=NONE)
        try:
            spots = await P.geocode_osm(place)
        except Exception:
            spots = []
        if not spots:
            await working.edit(embed=_compact("Map",
                f"I couldn't find **{place[:60]}**. Try a more specific name.", WARN))
            return
        # ambiguous: show up to 3 choices
        if len(spots) > 1 and spots[0].get("importance", 0) < 0.55:
            opts = "\n".join(f"• {s['display_name'][:80]}" for s in spots[:3])
            await working.edit(embed=_compact("Did you mean…",
                f"{opts}\n\nTry a more specific name like `{place}, country`."))
            return
        spot = spots[0]
        zoom = P._zoom_for_type(spot.get("type", "place"), spot.get("bbox"))
        try:
            png = await P.static_map_png(spot["lat"], spot["lon"], zoom)
        except Exception:
            png = None

        # build a clean info card: name + located-in + coords + requester
        parts = [p.strip() for p in spot["display_name"].split(",")]
        name = parts[0]
        located_in = ", ".join(parts[1:4]) if len(parts) > 1 else None
        lat = f"{spot['lat']:.4f}"
        lon = f"{spot['lon']:.4f}"
        body = f"**{name}**"
        if located_in:
            body += f"\nLocated in: {located_in}"
        body += f"\nCoordinates: {lat}, {lon}"
        body += f"\nRequested by: {ctx.author.display_name}"

        if png:
            import io as _io
            try:
                await working.delete()
            except Exception:
                pass
            await ctx.send(embed=_compact("", body),
                           file=discord.File(_io.BytesIO(png), filename="map.png"),
                           allowed_mentions=NONE)
        else:
            await working.edit(embed=_compact("Map", body))

    # ------------------------------------------------------------------ #
    # !weather
    # ------------------------------------------------------------------ #
    @commands.command(name="weather")
    @commands.guild_only()
    async def weather(self, ctx: commands.Context, *, place: str = None):
        try:
            manager.check_cooldown("weather", ctx.author.id, 15)
        except CooldownError as e:
            await ctx.reply(embed=_compact("Slow down", f"Try again in {e.retry_after:.0f}s.", WARN),
                            allowed_mentions=NONE)
            return
        if not place:
            await ctx.reply(embed=_compact("Weather", "Give me a place: `!weather seattle`", WARN),
                            allowed_mentions=NONE)
            return
        manager.arm_cooldown("weather", ctx.author.id, 15)
        working = await ctx.reply(embed=_compact("Weather", "Checking the sky…"), allowed_mentions=NONE)
        try:
            data = await P.weather(place)
        except Exception:
            data = None
        if not data:
            await working.edit(embed=_compact("Weather",
                f"I couldn't find weather for **{place[:60]}**. Try a city name.", WARN))
            return
        deg = data["deg"]
        def _t(v): return f"{round(v)}{deg}" if v is not None else "—"
        body = (f"**{data['label']}**\n\n"
                f"Now: {_t(data['now'])} · {P.weather_desc(data['code'])}\n"
                f"Feels like: {_t(data['feels'])}\n"
                f"Today: {_t(data['today_max'])} / {_t(data['today_min'])}\n"
                f"Tomorrow: {_t(data['tom_max'])} / {_t(data['tom_min'])}")
        await working.edit(embed=_compact("", body))

    # ------------------------------------------------------------------ #
    # !translate
    # ------------------------------------------------------------------ #
    @commands.command(name="translate", aliases=["tr"])
    @commands.guild_only()
    async def translate(self, ctx: commands.Context, *, args: str = None):
        """Translate a message. Defaults to English.
        `!translate` (reply) -> English · `!translate french` (reply) -> French
        `!translate somali hello` -> 'hello' to Somali · `!translate explain` (reply)"""
        try:
            manager.check_cooldown("translate", ctx.author.id, 5)
        except CooldownError as e:
            await ctx.reply(embed=_compact("Slow down", f"Try again in {e.retry_after:.0f}s.", WARN),
                            allowed_mentions=NONE)
            return

        tokens = (args or "").split()
        lang = "en"          # default target language
        text = None
        explain = False

        # is the first token a language (or 'explain')? then it sets the mode.
        if tokens:
            first = tokens[0].lower()
            if first == "explain":
                explain = True
                text = " ".join(tokens[1:]).strip() or None
            elif P.norm_lang(first):
                lang = first
                text = " ".join(tokens[1:]).strip() or None
            else:
                # no language given -> the whole thing is the text, target English
                text = args.strip()

        # if no inline text, use the replied-to message
        if not text and ctx.message.reference:
            try:
                t = await ctx.channel.fetch_message(ctx.message.reference.message_id)
                text = t.content
            except Exception:
                text = None

        # strip pings from the source
        import re as _re
        text = _re.sub(r"<@[!&]?\d+>|@everyone|@here", "", text or "").strip()
        if not text:
            await ctx.reply(embed=_compact("Translate",
                "Try `!translate en` (reply to a message) or `!translate somali hello`.", WARN),
                allowed_mentions=NONE)
            return

        manager.arm_cooldown("translate", ctx.author.id, 5)

        # explain mode -> needs the LLM
        if explain:
            if not P.llm_key():
                await ctx.reply(embed=_compact("Translate",
                    "Explain mode needs an AI provider (`UTIL_LLM_API_KEY`)."), allowed_mentions=NONE)
                return
            out = await P.llm_complete(
                "You explain slang, tone, and meaning of messages in plain English. Be brief (2-3 lines).",
                text[:1500], max_tokens=220)
            await ctx.reply(embed=_compact("Explain", out or "I couldn't explain that right now."),
                            allowed_mentions=NONE)
            return

        try:
            res = await P.translate(text, lang)
        except Exception:
            res = None
        if not res or not res.get("translated"):
            await ctx.reply(embed=_compact("Translate", "I couldn't translate that right now.", WARN),
                            allowed_mentions=NONE)
            return
        await ctx.reply(embed=_compact(f"→ {lang.title()}", res["translated"][:1500]),
                        allowed_mentions=NONE)

    # ------------------------------------------------------------------ #
    # !caption
    # ------------------------------------------------------------------ #
    @commands.command(name="caption")
    @commands.guild_only()
    async def caption(self, ctx: commands.Context, *, text: str = None):
        # base cooldown check (image rate); GIF gets a longer arm below
        try:
            manager.check_cooldown("caption", ctx.author.id, 30)
        except CooldownError as e:
            await ctx.reply(embed=_compact("Slow down", f"Try again in {e.retry_after:.0f}s.", WARN),
                            allowed_mentions=NONE)
            return
        if not text:
            await ctx.reply(embed=_compact("Caption",
                "Add caption text: reply **directly to an image or GIF** and run `!caption your text`.", WARN),
                allowed_mentions=NONE)
            return
        if not ctx.message.reference:
            await ctx.reply(embed=_compact("Caption",
                "You must **reply directly to an image or GIF** to caption it.", WARN),
                allowed_mentions=NONE)
            return
        img, animated = await self._fetch_replied_image(ctx)
        if img is None:
            await ctx.reply(embed=_compact("Caption",
                "I couldn't find an image or GIF on that message. Reply directly to one.", WARN),
                allowed_mentions=NONE)
            return

        working = await ctx.reply(embed=_compact("Caption", "Working…"), allowed_mentions=NONE)
        with manager.temp_files():
            try:
                if animated:
                    manager.arm_cooldown("caption", ctx.author.id, 120)  # GIF: 2 min
                    buf, kept = cards.caption_gif(img, text)
                    fname = "caption.gif" if kept else "caption.png"
                    note = None if kept else "Caption made from the first frame because the GIF was too large to render safely."
                    await working.delete()
                    await ctx.reply(
                        content=note if note else None,
                        file=discord.File(buf, filename=fname), allowed_mentions=NONE)
                else:
                    manager.arm_cooldown("caption", ctx.author.id, 30)
                    buf = cards.caption_image(img.convert("RGBA"), text)
                    await working.delete()
                    await ctx.reply(file=discord.File(buf, filename="caption.png"), allowed_mentions=NONE)
            except Exception as ex:
                print(f"[Ignio][Caption] render failed: {type(ex).__name__}: {ex}")
                try:
                    await working.edit(embed=_compact("Caption", "I couldn't make that caption right now.", WARN))
                except Exception:
                    pass

    async def _fetch_replied_image(self, ctx):
        """Find an image/GIF on the replied message and return (PIL.Image, is_animated).
        Handles: image/gif attachments, Tenor links + embeds, GIF-picker embeds,
        and direct image URLs. Returns (None, False) if nothing usable."""
        ref = ctx.message.reference
        if not ref:
            return None, False
        try:
            t = await ctx.channel.fetch_message(ref.message_id)
        except Exception as ex:
            print(f"[Ignio][Caption] couldn't fetch replied message: {type(ex).__name__}")
            return None, False

        from PIL import Image

        # 1) attachments — read bytes directly via discord (most reliable)
        for att in t.attachments:
            ct = (att.content_type or "").lower()
            fn = (att.filename or "").lower()
            if ct.startswith("image") or fn.endswith((".png", ".jpg", ".jpeg", ".gif", ".webp")):
                try:
                    data = await att.read()
                    im = Image.open(io.BytesIO(data))
                    animated = getattr(im, "is_animated", False)
                    return im, animated
                except Exception as ex:
                    print(f"[Ignio][Caption] attachment read failed: {type(ex).__name__}")
                    continue

        # 2) collect candidate URLs from text + embeds, resolving Tenor pages
        candidates: list[str] = []

        # any tenor.com/view link in the message text
        for u in resolver.extract_urls(t.content or ""):
            if P.is_tenor_url(u):
                tn = await P.resolve_tenor(u)
                if tn and tn.get("gif"):
                    candidates.append(tn["gif"])
            else:
                base = u.lower().split("?")[0]
                if base.endswith((".png", ".jpg", ".jpeg", ".gif", ".webp")):
                    candidates.append(u)

        # embeds: Tenor/GIF-picker embeds + image/thumbnail/video fields
        for emb in t.embeds:
            emb_url = getattr(emb, "url", None)
            if emb_url and P.is_tenor_url(emb_url):
                tn = await P.resolve_tenor(emb_url)
                if tn and tn.get("gif"):
                    candidates.append(tn["gif"])
            # gifv/video embeds: the image/thumbnail is usually the .gif still or anim
            for obj_attr in ("image", "thumbnail", "video"):
                obj = getattr(emb, obj_attr, None)
                u = getattr(obj, "url", None) if obj else None
                if u:
                    candidates.append(u)

        # 3) try each candidate; only keep what PIL can actually open as an image
        for url in candidates:
            data = await self._download_image_bytes(url)
            if not data:
                continue
            try:
                im = Image.open(io.BytesIO(data))
                im.load()  # force-decode so we know it's valid
                animated = getattr(im, "is_animated", False)
                im2 = Image.open(io.BytesIO(data))  # fresh handle (load consumed frames)
                return im2, animated
            except Exception:
                continue

        if not candidates and not t.attachments:
            print("[Ignio][Caption] replied message had no image/GIF attachment, Tenor link, or embed")
        return None, False

    async def _download_image_bytes(self, url: str) -> bytes | None:
        """Safely download an image URL (size-capped, SSRF-guarded)."""
        ok, _ = safety.is_safe_url(url)
        if not ok:
            return None
        try:
            import aiohttp
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=12)) as s:
                async with s.get(url, headers={"User-Agent": "IgnioBot/1.0"}) as r:
                    if r.status != 200:
                        return None
                    data = await r.content.read(12 * 1024 * 1024 + 1)
                    if len(data) > 12 * 1024 * 1024:
                        return None
                    return data
        except Exception:
            return None

    # ------------------------------------------------------------------ #
    # !quote
    # ------------------------------------------------------------------ #
    @commands.command(name="quote", aliases=["qoute"])
    @commands.guild_only()
    async def quote(self, ctx: commands.Context):
        try:
            manager.check_cooldown("quote", ctx.author.id, 10)
        except CooldownError as e:
            await ctx.reply(embed=_compact("Slow down", f"Try again in {e.retry_after:.0f}s.", WARN),
                            allowed_mentions=NONE)
            return
        ref = ctx.message.reference
        if not ref:
            await ctx.reply(embed=_compact("Quote", "Reply to a message to quote it.", WARN),
                            allowed_mentions=NONE)
            return
        try:
            t = await ctx.channel.fetch_message(ref.message_id)
        except Exception:
            await ctx.reply(embed=_compact("Quote", "I couldn't read that message.", WARN),
                            allowed_mentions=NONE)
            return
        if not (t.content or "").strip():
            await ctx.reply(embed=_compact("Quote", "That message has no text to quote.", WARN),
                            allowed_mentions=NONE)
            return
        manager.arm_cooldown("quote", ctx.author.id, 10)
        avatar = None
        try:
            data = await t.author.display_avatar.read()
            from PIL import Image
            avatar = Image.open(io.BytesIO(data))
        except Exception:
            avatar = None
        ts = t.created_at.strftime("%b %d, %Y")
        with manager.temp_files():
            buf = cards.quote_card(t.author.display_name, t.content, ts, avatar)
            await ctx.reply(file=discord.File(buf, filename="quote.png"), allowed_mentions=NONE)

    # ------------------------------------------------------------------ #
    # !afk
    # ------------------------------------------------------------------ #
    @commands.command(name="afk")
    @commands.guild_only()
    async def afk(self, ctx: commands.Context, *, reason: str = ""):
        reason = (reason or "").strip()[:200]
        # strip mentions from the stored reason
        reason = re.sub(r"<@[!&]?\d+>|@everyone|@here", "", reason).strip()
        if self.repo is not None:
            db = await self.repo._db()
            await db.execute(
                "INSERT INTO afk_status(guild_id,user_id,reason,since_ts) VALUES(?,?,?,?) "
                "ON CONFLICT(guild_id,user_id) DO UPDATE SET reason=excluded.reason, since_ts=excluded.since_ts",
                (ctx.guild.id, ctx.author.id, reason, int(time.time())))
        await ctx.reply(embed=_compact("💤 You're AFK",
            (reason if reason else "I'll let people know you're away."),
            ACCENT), allowed_mentions=NONE)

    # ------------------------------------------------------------------ #
    # mention-to-download:  @Ignio (reply to a video link)  /  @Ignio <link>
    # ------------------------------------------------------------------ #
    @commands.Cog.listener("on_message")
    async def media_mention_listener(self, message: discord.Message):
        # only real users, only when the bot is explicitly @mentioned
        if not message.guild or message.author.bot:
            return
        if self.bot.user is None or self.bot.user not in message.mentions:
            return
        # @everyone/@here shouldn't count as a mention of us
        if message.mention_everyone:
            return
        if not media.ENABLED():
            return
        # category gate (so admins can disable utilities entirely)
        if self.repo is not None and not await self._enabled(message.guild.id):
            return

        # find a URL by priority: replied message -> this message -> embeds
        url = await self._find_media_url(message)
        if not url:
            # only nudge if they actually just pinged us with nothing usable
            await message.reply(embed=_compact("Download",
                "Reply to a message with a supported public video link, then mention me.", WARN),
                allowed_mentions=NONE)
            return

        if not media.looks_supported(url):
            await message.reply(embed=_compact("Download", "I could not download media from that link.", WARN),
                                allowed_mentions=NONE)
            return
        if not media.is_available():
            print("[Ignio][Media] yt-dlp is not installed — run: pip install yt-dlp")
            await message.reply(embed=_compact("Download",
                "Media downloading isn't set up on this bot yet. An admin can check the logs.", WARN),
                allowed_mentions=NONE)
            return

        # per-user cooldown
        try:
            manager.check_cooldown("media", message.author.id, media.USER_COOLDOWN())
        except CooldownError as e:
            await message.reply(embed=_compact("Slow down",
                f"Give it {e.retry_after:.0f}s before the next download.", WARN), allowed_mentions=NONE)
            return

        loading = None
        try:
            # one active download per user + per-guild concurrency cap
            async with manager.slot("media:user", message.author.id, 1):
                async with manager.slot("media", message.guild.id, media.MAX_CONCURRENT()):
                    manager.arm_cooldown("media", message.author.id, media.USER_COOLDOWN())
                    try:
                        await message.add_reaction("⏳")
                        loading = True
                    except Exception:
                        loading = False
                    await self._do_media_download(message, url)
        except BusyError:
            await message.reply(embed=_compact("Busy",
                "I'm downloading other videos right now — try again in a moment.", WARN),
                allowed_mentions=NONE)
        finally:
            if loading:
                try:
                    await message.remove_reaction("⏳", self.bot.user)
                except Exception:
                    pass

    async def _find_media_url(self, message) -> str | None:
        # 1) replied-to message
        if message.reference:
            try:
                t = await message.channel.fetch_message(message.reference.message_id)
                u = resolver.first_video_target(t)
                if not u:
                    urls = resolver.resolve_targets(t)["urls"]
                    u = next((x for x in urls if media.looks_supported(x)), None)
                if u:
                    return u
            except Exception:
                pass
        # 2) the mention message itself (strip the bot mention text first)
        urls = resolver.extract_urls(message.content or "")
        u = next((x for x in urls if media.looks_supported(x)), None)
        if u:
            return u
        return None

    async def _do_media_download(self, message, url: str):
        res = await media.download(url)
        try:
            if res.ok and res.path:
                limit_mb = self._guild_upload_limit_mb(message.guild)
                import os as _os
                size_mb = _os.path.getsize(res.path) / (1024 * 1024)
                if size_mb > limit_mb:
                    await message.reply(embed=_compact("Download",
                        f"This video is too large to upload here. Discord allows up to "
                        f"{limit_mb:.0f} MB in this server."), allowed_mentions=NONE)
                    return
                # compact Katana-style source card under the video
                src = res.source or "the web"
                bits = [f"**Downloaded from {src}**"]
                meta = []
                if res.uploader:
                    u = res.uploader if str(res.uploader).startswith("@") else f"@{res.uploader}"
                    meta.append(u)
                if res.duration:
                    m, s = divmod(int(res.duration), 60)
                    meta.append(f"{m}:{s:02d}")
                if meta:
                    bits.append(" · ".join(meta))
                bits.append(f"Requested by {message.author.display_name}")
                if res.url:
                    bits.append(f"[Original post]({res.url})")
                e = _compact("", "\n".join(bits))
                fname = "video" + _os.path.splitext(res.path)[1]
                await message.reply(embed=e, file=discord.File(res.path, filename=fname),
                                    allowed_mentions=NONE)
            else:
                # on failure, still show a compact card if we at least know the source
                body = _media_error(res.error)
                src = media._source_name(url)
                if src != "the web":
                    body += f"\nSource: {src} · [Original post]({url})"
                await message.reply(embed=_compact("Download", body), allowed_mentions=NONE)
        finally:
            media.cleanup(res.path)

    @staticmethod
    def _guild_upload_limit_mb(guild) -> float:
        # Discord boost tiers: 10MB (none/1), 50MB (tier 2), 100MB (tier 3)
        tier = getattr(guild, "premium_tier", 0) or 0
        if tier >= 3:
            return 100.0
        if tier >= 2:
            return 50.0
        # discord.py exposes filesize_limit on the guild in bytes when available
        raw = getattr(guild, "filesize_limit", None)
        if raw:
            return raw / (1024 * 1024)
        return 10.0

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if not message.guild or message.author.bot or self.repo is None:
            return
        try:
            db = await self.repo._db()
            # 1) clear the author's own AFK when they talk
            row = await db.fetchone(
                "SELECT since_ts FROM afk_status WHERE guild_id=? AND user_id=?",
                (message.guild.id, message.author.id))
            if row and not (message.content or "").startswith(("!afk", "?afk")):
                await db.execute("DELETE FROM afk_status WHERE guild_id=? AND user_id=?",
                                 (message.guild.id, message.author.id))
                try:
                    await message.channel.send(
                        embed=_compact("👋 Welcome back", f"{message.author.display_name}, I cleared your AFK.", ACCENT),
                        allowed_mentions=NONE, delete_after=8)
                except Exception:
                    pass
            # 2) notify when a real user mentions an AFK person (once per 10 min per channel)
            for user in message.mentions:
                if user.bot or user.id == message.author.id:
                    continue
                arow = await db.fetchone(
                    "SELECT reason, since_ts FROM afk_status WHERE guild_id=? AND user_id=?",
                    (message.guild.id, user.id))
                if not arow:
                    continue
                key = (message.guild.id, message.channel.id, user.id)
                now = time.time()
                if now - self._afk_notice.get(key, 0) < 600:
                    continue
                self._afk_notice[key] = now
                since = int(arow["since_ts"])
                ago = _ago(int(now) - since)
                rsn = arow["reason"] or "AFK"
                await message.channel.send(
                    embed=_compact(f"💤 {user.display_name} is away",
                                   f"{rsn}\nAway for {ago.replace(' ago', '')}"),
                    allowed_mentions=NONE)
        except Exception:
            pass


def _ago(secs: int) -> str:
    if secs < 60:
        return "less than a minute ago"
    if secs < 3600:
        m = secs // 60
        return f"{m} minute{'s' if m != 1 else ''} ago"
    if secs < 86400:
        h = secs // 3600
        return f"{h} hour{'s' if h != 1 else ''} ago"
    d = secs // 86400
    return f"{d} day{'s' if d != 1 else ''} ago"


def _media_error(code: str) -> str:
    return {
        "unsupported": "I could not download media from that link.",
        "private": "That content is private, login-only, deleted, or unavailable.",
        "timeout": "That download took too long. Try a shorter video or another link.",
        "too_large": "This video is too large to upload here.",
        "temporarily_blocked": "I could not access a downloadable public video from that post right now.",
        "ffmpeg": "I couldn't process that video right now. An admin can check the bot logs.",
        "failed": "I could not download that video right now. An admin can check the bot logs.",
    }.get(code or "failed", "I could not download that video right now. An admin can check the bot logs.")


async def setup(bot):  # pragma: no cover
    pass
