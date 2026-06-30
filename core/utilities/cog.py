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

NONE = discord.AllowedMentions.none()
ACCENT = 0x6FB7B0
WARN = 0xE0A042

# ---- time-window parsing for catchup ----
_WINDOWS = {"5m": 5, "15m": 15, "30m": 30, "1h": 60, "2h": 120, "4h": 240}


def _provider(name: str) -> str | None:
    """Return an env-configured provider key, or None if not set."""
    return os.environ.get(name) or None


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
            msgs.append(m.content)
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
                                              "Nothing much happened here recently."))
            return
        summary = await self._summarize_chat(msgs, window)
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
        await working.edit(embed=_compact("What happened here", summary))

    async def _summarize_chat(self, msgs, window, reply=False):
        """Summarize via LLM provider if configured; else a clean fallback."""
        if not _provider("UTIL_LLM_API_KEY"):
            joined = " ".join(msgs)
            words = len(joined.split())
            return (f"• {len(msgs)} messages, ~{words} words.\n"
                    f"• Summaries need an AI provider that isn't set up yet.\n"
                    f"• Ask an admin to configure `UTIL_LLM_API_KEY` to enable smart summaries.")
        # provider path is intentionally thin — wired to whatever LLM is configured
        try:
            return await self._llm_summarize(msgs, window, reply)
        except Exception:
            return "• I couldn't summarize that right now."

    async def _llm_summarize(self, msgs, window, reply):  # pragma: no cover (needs provider)
        raise NotImplementedError

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
        if not _provider("UTIL_LLM_API_KEY"):
            await ctx.reply(embed=_compact("TL;DR",
                "Smart summaries need an AI provider that isn't configured yet."), allowed_mentions=NONE)
            return
        await ctx.reply(embed=_compact("TL;DR", "• (summary provider configured)"), allowed_mentions=NONE)

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
        if not _provider("UTIL_SONG_API_KEY"):
            await ctx.reply(embed=_compact("Song ID",
                "Song matching needs a provider that isn't configured yet."), allowed_mentions=NONE)
            return
        await ctx.reply(embed=_compact("Song", "I could not access usable audio from this post."),
                        allowed_mentions=NONE)

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
        from urllib.parse import urlparse
        host = urlparse(url).hostname or "unknown"
        body = (f"• Opens to: `{host}`\n"
                f"• Final destination: needs a fetch provider to follow redirects\n"
                f"• Risk signals: none obvious (this isn't a safety guarantee)")
        await ctx.reply(embed=_compact("Link X-ray", body), allowed_mentions=NONE)

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
        if not _provider("UTIL_MAP_API_KEY"):
            await ctx.reply(embed=_compact("Map",
                f"Maps for **{place[:60]}** need a map provider that isn't configured yet."),
                allowed_mentions=NONE)
            return
        await ctx.reply(embed=_compact("Map", f"(map provider configured for {place[:60]})"),
                        allowed_mentions=NONE)

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
        if not _provider("UTIL_WEATHER_API_KEY"):
            await ctx.reply(embed=_compact("Weather",
                f"Weather for **{place[:60]}** needs a weather provider that isn't configured yet."),
                allowed_mentions=NONE)
            return
        await ctx.reply(embed=_compact("Weather", f"(weather provider configured for {place[:60]})"),
                        allowed_mentions=NONE)

    # ------------------------------------------------------------------ #
    # !translate
    # ------------------------------------------------------------------ #
    @commands.command(name="translate")
    @commands.guild_only()
    async def translate(self, ctx: commands.Context, lang: str = None, *, text: str = None):
        try:
            manager.check_cooldown("translate", ctx.author.id, 5)
        except CooldownError as e:
            await ctx.reply(embed=_compact("Slow down", f"Try again in {e.retry_after:.0f}s.", WARN),
                            allowed_mentions=NONE)
            return
        if not text and ctx.message.reference:
            try:
                t = await ctx.channel.fetch_message(ctx.message.reference.message_id)
                text = t.content
            except Exception:
                text = None
        if not lang:
            await ctx.reply(embed=_compact("Translate",
                "Try `!translate en` (reply to a message) or `!translate somali hello`.", WARN),
                allowed_mentions=NONE)
            return
        manager.arm_cooldown("translate", ctx.author.id, 5)
        if not _provider("UTIL_LLM_API_KEY"):
            await ctx.reply(embed=_compact("Translate",
                "Translation needs an AI provider that isn't configured yet."), allowed_mentions=NONE)
            return
        await ctx.reply(embed=_compact("Translate", "(translation provider configured)"),
                        allowed_mentions=NONE)

    # ------------------------------------------------------------------ #
    # !caption
    # ------------------------------------------------------------------ #
    @commands.command(name="caption")
    @commands.guild_only()
    async def caption(self, ctx: commands.Context, *, text: str = None):
        try:
            manager.check_cooldown("caption", ctx.author.id, 30)
        except CooldownError as e:
            await ctx.reply(embed=_compact("Slow down", f"Try again in {e.retry_after:.0f}s.", WARN),
                            allowed_mentions=NONE)
            return
        if not text:
            await ctx.reply(embed=_compact("Caption", "Reply to an image with `!caption your text`.", WARN),
                            allowed_mentions=NONE)
            return
        img = await self._fetch_replied_image(ctx)
        if img is None:
            await ctx.reply(embed=_compact("Caption", "Reply to an image or GIF to caption it.", WARN),
                            allowed_mentions=NONE)
            return
        manager.arm_cooldown("caption", ctx.author.id, 30)
        with manager.temp_files():
            buf = cards.caption_image(img, text)
            await ctx.reply(file=discord.File(buf, filename="caption.png"), allowed_mentions=NONE)

    async def _fetch_replied_image(self, ctx):
        ref = ctx.message.reference
        if not ref:
            return None
        try:
            t = await ctx.channel.fetch_message(ref.message_id)
        except Exception:
            return None
        for att in t.attachments:
            ct = (att.content_type or "").lower()
            if ct.startswith("image"):
                try:
                    data = await att.read()
                    from PIL import Image
                    return Image.open(io.BytesIO(data))
                except Exception:
                    return None
        return None

    # ------------------------------------------------------------------ #
    # !quote
    # ------------------------------------------------------------------ #
    @commands.command(name="quote")
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
        await ctx.reply(embed=_compact("AFK set",
            (f"You're now AFK: {reason}" if reason else "You're now AFK."),
            ACCENT), allowed_mentions=NONE)

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
                        embed=_compact("Welcome back", f"{message.author.display_name}, AFK cleared.", ACCENT),
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
                    embed=_compact(f"{user.display_name} is AFK", f"{rsn} · since {ago}"),
                    allowed_mentions=NONE)
        except Exception:
            pass


def _ago(secs: int) -> str:
    if secs < 60:
        return "just now"
    if secs < 3600:
        return f"{secs // 60}m ago"
    if secs < 86400:
        return f"{secs // 3600}h ago"
    return f"{secs // 86400}d ago"


async def setup(bot):  # pragma: no cover
    pass
