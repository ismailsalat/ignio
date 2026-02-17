# bot/cogs/vc_tracker.py

from __future__ import annotations

import time
import discord
from discord.ext import commands, tasks

from bot.core.state import VcRuntimeState
from bot.core.timecore import now_utc_ts, day_key_from_utc_ts
from bot.core.streak_engine import compute_streak_transition


class VcTrackerCog(commands.Cog):
    """
    Duo-only VC tracker (exactly 2 humans) + Smart 🔥 nickname suffix.

    Core:
    - Ignores bots
    - Counts overlap only when EXACTLY 2 real users are in the channel (after disconnect buffer)
    - 1 user => ignore
    - 3+ users => ignore (prevents pairwise farming)
    - Bootstraps VC state on startup
    - Disconnect buffer keeps effective duo for short reconnects

    Fire Nicknames (smart):
    - Adds suffix " 🔥" ONLY when duo is "qualified":
        (today_total >= min_overlap_seconds) OR (current_streak > 0)
    - Removes suffix immediately when duo breaks
    - Stores original nick in memory for perfect restore
    - Restart-safe fallback: if we don't know original, we strip suffix instead of guessing
    - Rate-limit guard per user to avoid API spam
    """

    def __init__(self, bot: commands.Bot, settings, repos):
        self.bot = bot
        self.settings = settings
        self.repos = repos
        self.state = VcRuntimeState()
        self._bootstrapped = False

        # 🔥 runtime memory (NOT DB)
        self._fire_active: dict[int, set[int]] = {}  # guild_id -> users currently expected to have fire
        self._fire_original_nick: dict[int, dict[int, str | None]] = {}  # guild_id -> user_id -> original nick

        # rate-limit guard: don't attempt edit too frequently per user
        self._nick_edit_last_ts: dict[tuple[int, int], float] = {}  # (guild_id, user_id) -> unix seconds

        self.tick.start()

    def cog_unload(self):
        self.tick.cancel()

    # ---------------- fire nickname config ----------------

    def _fire_enabled(self) -> bool:
        return bool(getattr(self.settings, "nickname_fire_enabled", True))

    def _fire_suffix(self) -> str:
        return str(getattr(self.settings, "nickname_fire_suffix", " 🔥"))

    def _nick_edit_min_interval(self) -> float:
        # seconds between nickname edits per user (guard)
        return float(getattr(self.settings, "nickname_edit_min_interval_seconds", 20))

    def _has_fire(self, nick: str | None) -> bool:
        if not nick:
            return False
        return nick.endswith(self._fire_suffix())

    def _strip_fire(self, nick: str) -> str:
        suf = self._fire_suffix()
        return nick[:-len(suf)] if nick.endswith(suf) else nick

    def _can_try_edit_now(self, guild_id: int, user_id: int) -> bool:
        key = (guild_id, user_id)
        last = self._nick_edit_last_ts.get(key, 0.0)
        return (time.time() - last) >= self._nick_edit_min_interval()

    def _mark_edit_now(self, guild_id: int, user_id: int) -> None:
        self._nick_edit_last_ts[(guild_id, user_id)] = time.time()

    async def _apply_fire(self, guild: discord.Guild, user_id: int) -> None:
        if not self._fire_enabled():
            return
        if not self._can_try_edit_now(guild.id, user_id):
            return

        member = guild.get_member(user_id)
        if member is None or member.bot:
            return

        # Already has fire? mark active and stop
        if self._has_fire(member.nick):
            self._fire_active.setdefault(guild.id, set()).add(user_id)
            return

        # Save original nick exactly once
        self._fire_original_nick.setdefault(guild.id, {}).setdefault(user_id, member.nick)

        base = member.nick if member.nick else member.name
        base = self._strip_fire(base)
        new_nick = base + self._fire_suffix()

        # If nickname already equals new_nick, no edit needed
        if member.nick == new_nick:
            self._fire_active.setdefault(guild.id, set()).add(user_id)
            return

        try:
            self._mark_edit_now(guild.id, user_id)
            await member.edit(nick=new_nick, reason="Ignio: duo qualified (fire)")
            self._fire_active.setdefault(guild.id, set()).add(user_id)
        except (discord.Forbidden, discord.HTTPException):
            return

    async def _remove_fire(self, guild: discord.Guild, user_id: int) -> None:
        if not self._fire_enabled():
            return
        if not self._can_try_edit_now(guild.id, user_id):
            return

        member = guild.get_member(user_id)
        if member is None or member.bot:
            return

        # Prefer perfect restore if we have it
        orig = self._fire_original_nick.get(guild.id, {}).get(user_id, None)

        # Restart-safe fallback: if we don't have orig, strip suffix if present
        if orig is None:
            if member.nick is None:
                # no nick to strip; nothing to do
                self._fire_active.get(guild.id, set()).discard(user_id)
                return
            desired = self._strip_fire(member.nick)
        else:
            desired = orig  # can be None

        # If already correct, just clean memory
        if member.nick == desired:
            self._fire_active.get(guild.id, set()).discard(user_id)
            if guild.id in self._fire_original_nick:
                self._fire_original_nick[guild.id].pop(user_id, None)
            return

        try:
            self._mark_edit_now(guild.id, user_id)
            await member.edit(nick=desired, reason="Ignio: duo ended (remove fire)")
        except (discord.Forbidden, discord.HTTPException):
            return
        finally:
            self._fire_active.get(guild.id, set()).discard(user_id)
            if guild.id in self._fire_original_nick:
                self._fire_original_nick[guild.id].pop(user_id, None)

    async def _sync_fire_for_guild(self, guild_id: int, desired_users: set[int]) -> None:
        if not self._fire_enabled():
            return

        guild = self.bot.get_guild(guild_id)
        if guild is None:
            return

        active = self._fire_active.setdefault(guild_id, set())

        # Add fire to those who should have it
        for uid in (desired_users - active):
            await self._apply_fire(guild, uid)

        # Remove fire from those who should not have it
        for uid in list(active - desired_users):
            await self._remove_fire(guild, uid)

    # ---------------- bootstrap ----------------

    async def bootstrap_voice_state(self):
        total_channels = 0
        total_tracked = 0

        for guild in self.bot.guilds:
            gid = guild.id
            for ch in guild.voice_channels:
                total_channels += 1

                if self.settings.ignore_afk_channels and ch.id in self.settings.afk_channel_ids:
                    if gid in self.state.channel_members:
                        self.state.channel_members[gid].pop(ch.id, None)
                    continue

                members = {m.id for m in ch.members if not m.bot}
                if members:
                    self.state.set_channel_members(gid, ch.id, members)
                    total_tracked += 1
                else:
                    self.state.remove_channel(gid, ch.id)

        self._bootstrapped = True
        print(f"[Ignio] VC bootstrap ✅ channels={total_channels} tracked={total_tracked}")

    @commands.Cog.listener()
    async def on_ready(self):
        await self.bootstrap_voice_state()

    # ---------------- voice state updates ----------------

    @commands.Cog.listener()
    async def on_voice_state_update(
        self,
        member: discord.Member,
        before: discord.VoiceState,
        after: discord.VoiceState,
    ):
        if member.bot:
            return

        guild_id = member.guild.id
        now_ts = now_utc_ts()

        if before.channel is not None and after.channel is None:
            self.state.mark_left(guild_id, member.id, before.channel.id, now_ts)

        if after.channel is not None:
            self.state.clear_left(guild_id, member.id)

        for ch in (before.channel, after.channel):
            if ch is None:
                continue
            if self.settings.ignore_afk_channels and ch.id in self.settings.afk_channel_ids:
                continue

            humans = {m.id for m in ch.members if not m.bot}
            if humans:
                self.state.set_channel_members(guild_id, ch.id, humans)
            else:
                self.state.remove_channel(guild_id, ch.id)

    # ---------------- effective members ----------------

    def _compute_effective_members(
        self,
        guild_id: int,
        channel_id: int,
        now_ts: int,
        base_members: set[int],
        disconnect_buffer_seconds: int,
    ) -> set[int]:
        effective = set(base_members)

        for (g_id, u_id), (left_ch, left_ts) in list(self.state.recently_left.items()):
            if g_id != guild_id or left_ch != channel_id:
                continue

            age = now_ts - left_ts
            if age <= disconnect_buffer_seconds:
                effective.add(u_id)
            else:
                self.state.clear_left(guild_id, u_id)

        return effective

    # ---------------- tick loop ----------------

    @tasks.loop(seconds=15)
    async def tick(self):
        if not self.bot.is_ready():
            return

        now_ts = now_utc_ts()

        # who should have 🔥 right now (per guild)
        desired_fire: dict[int, set[int]] = {}

        for guild_id, channels in list(self.state.channel_members.items()):
            # use DB-effective config so changes apply live
            cfg = await self.repos.get_effective_config(guild_id, self.settings)

            default_tz = str(cfg.get("default_tz", self.settings.default_tz))
            grace_hour = int(cfg.get("grace_hour_local", self.settings.grace_hour_local))
            tick_seconds = int(cfg.get("tick_seconds", self.settings.tick_seconds))
            min_required = int(cfg.get("min_overlap_seconds", self.settings.min_overlap_seconds))
            disconnect_buf = int(cfg.get("disconnect_buffer_seconds", self.settings.disconnect_buffer_seconds))

            day_key = day_key_from_utc_ts(now_ts, default_tz, grace_hour)

            for channel_id, members in list(channels.items()):
                if self.settings.ignore_afk_channels and channel_id in self.settings.afk_channel_ids:
                    continue

                base = set(members)
                if not base:
                    continue

                effective = self._compute_effective_members(
                    guild_id, channel_id, now_ts, base, disconnect_buf
                )

                # ✅ DUO ONLY
                if len(effective) != 2:
                    continue

                a, b = sorted(effective)

                duo_id, today_total, current_streak = await self._apply_overlap_tick(
                    guild_id=guild_id,
                    user_a=a,
                    user_b=b,
                    day_key=day_key,
                    now_ts=now_ts,
                    tick_seconds=tick_seconds,
                    min_required_seconds=min_required,
                )

                # 🔥 qualify rule (your request)
                if today_total >= min_required or current_streak > 0:
                    desired_fire.setdefault(guild_id, set()).update({a, b})

        # sync nicknames per guild: only edits on state changes
        for gid in list(self.state.channel_members.keys()):
            await self._sync_fire_for_guild(gid, desired_fire.get(gid, set()))

    async def _apply_overlap_tick(
        self,
        guild_id: int,
        user_a: int,
        user_b: int,
        day_key: int,
        now_ts: int,
        tick_seconds: int,
        min_required_seconds: int,
    ) -> tuple[int, int, int]:
        """
        Adds overlap seconds for this duo and updates streak if day completed.

        Returns:
            (duo_id, today_total_seconds, current_streak_after)
        """
        duo_id = await self.repos.get_or_create_duo(guild_id, user_a, user_b, now_ts)

        today_total = await self.repos.add_duo_daily_seconds(
            guild_id=guild_id,
            duo_id=duo_id,
            day_key=day_key,
            seconds=tick_seconds,
            now_ts=now_ts,
        )

        current, longest, last_completed = await self.repos.get_streak_row(guild_id, duo_id)

        became_completed, new_current, new_longest = compute_streak_transition(
            min_required_seconds=min_required_seconds,
            today_seconds=today_total,
            today_day_key=day_key,
            last_completed_day_key=last_completed,
            current_streak=current,
            longest_streak=longest,
        )

        if became_completed:
            await self.repos.save_streak_row(
                guild_id=guild_id,
                duo_id=duo_id,
                current_streak=new_current,
                longest_streak=new_longest,
                last_completed_day_key=day_key,
                now_ts=now_ts,
            )
            current = new_current
            print(f"[Ignio] ✅ duo complete: guild={guild_id} users={user_a}+{user_b} streak={new_current}")

        return duo_id, today_total, current

    @tick.before_loop
    async def before_tick(self):
        await self.bot.wait_until_ready()
        await self.bootstrap_voice_state()
