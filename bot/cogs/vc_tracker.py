# bot/cogs/vc_tracker.py

import discord
from discord.ext import commands, tasks

from bot.core.state import VcRuntimeState
from bot.core.timecore import now_utc_ts, day_key_from_utc_ts
from bot.core.streak_engine import compute_streak_transition


class VcTrackerCog(commands.Cog):
    """
    Duo-only VC tracker:
    - Ignores bots
    - Only counts overlap when EXACTLY 2 real users are in the channel
    - 3+ real users => no tracking for that channel (prevents "every pair" farming)
    - Uses disconnect buffer: briefly leaving doesn't break duo if they rejoin quickly
    - Bootstraps state on startup by scanning voice channels

    NEW:
    - Temporary nickname suffix " 🔥" while duo is qualified (met min overlap today OR has active streak)
    - Restores original nick immediately when duo breaks
    - Memory-only (not saved to DB)
    """

    def __init__(self, bot: commands.Bot, settings, repos):
        self.bot = bot
        self.settings = settings
        self.repos = repos
        self.state = VcRuntimeState()
        self._bootstrapped = False

        # fire-nick runtime memory
        self._fire_active: dict[int, set[int]] = {}  # guild_id -> set(user_id) currently tagged
        self._fire_original_nick: dict[int, dict[int, str | None]] = {}  # guild_id -> {user_id: original nick}

        self.tick.start()

    def cog_unload(self):
        self.tick.cancel()

    # ---------------- fire nickname helpers ----------------

    def _fire_enabled(self) -> bool:
        return bool(getattr(self.settings, "nickname_fire_enabled", True))

    def _fire_suffix(self) -> str:
        return str(getattr(self.settings, "nickname_fire_suffix", " 🔥"))

    def _strip_fire_suffix(self, s: str) -> str:
        suf = self._fire_suffix()
        return s[:-len(suf)] if s.endswith(suf) else s

    async def _apply_fire(self, guild: discord.Guild, user_id: int) -> None:
        if not self._fire_enabled():
            return

        member = guild.get_member(user_id)
        if member is None or member.bot:
            return

        suf = self._fire_suffix()

        # Save original nickname once (can be None)
        self._fire_original_nick.setdefault(guild.id, {}).setdefault(user_id, member.nick)

        base = member.nick if member.nick else member.name
        base = self._strip_fire_suffix(base)
        new_nick = base + suf

        # Avoid spamming edits
        if member.nick == new_nick:
            self._fire_active.setdefault(guild.id, set()).add(user_id)
            return

        try:
            await member.edit(nick=new_nick, reason="Ignio: duo qualified (fire)")
            self._fire_active.setdefault(guild.id, set()).add(user_id)
        except (discord.Forbidden, discord.HTTPException):
            # Missing Manage Nicknames or role hierarchy issues
            return

    async def _remove_fire(self, guild: discord.Guild, user_id: int) -> None:
        if not self._fire_enabled():
            return

        member = guild.get_member(user_id)
        if member is None or member.bot:
            return

        orig = self._fire_original_nick.get(guild.id, {}).get(user_id, None)

        try:
            await member.edit(nick=orig, reason="Ignio: duo ended (remove fire)")
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

        # Add to desired
        for uid in (desired_users - active):
            await self._apply_fire(guild, uid)

        # Remove from no-longer-desired
        for uid in list(active - desired_users):
            await self._remove_fire(guild, uid)

    # ---------------- bootstrap ----------------

    async def bootstrap_voice_state(self):
        """
        Scan all voice channels in every guild and populate runtime state.
        """
        total_channels = 0
        total_tracked = 0

        for guild in self.bot.guilds:
            gid = guild.id
            for ch in guild.voice_channels:
                total_channels += 1

                # ignore AFK channels if configured
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

        # Mark leaving (disconnect buffer) if they left a channel completely
        if before.channel is not None and after.channel is None:
            self.state.mark_left(guild_id, member.id, before.channel.id, now_ts)

        # If connected anywhere now, clear recently_left (reconnect / channel switch)
        if after.channel is not None:
            self.state.clear_left(guild_id, member.id)

        # Refresh membership sets for affected channels
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

    # ---------------- core helpers ----------------

    def _compute_effective_members(self, guild_id: int, channel_id: int, now_ts: int, base_members: set[int]) -> set[int]:
        """
        Apply disconnect buffer: if someone left this channel recently, keep them as 'effective'
        for a short time so a brief disconnect doesn't break overlap tracking.
        """
        effective = set(base_members)

        for (g_id, u_id), (left_ch, left_ts) in list(self.state.recently_left.items()):
            if g_id != guild_id or left_ch != channel_id:
                continue

            age = now_ts - left_ts
            if age <= self.settings.disconnect_buffer_seconds:
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
        day_key = day_key_from_utc_ts(now_ts, self.settings.default_tz, self.settings.grace_hour_local)

        # Who should have 🔥 right now (per guild)
        desired_fire: dict[int, set[int]] = {}

        for guild_id, channels in list(self.state.channel_members.items()):
            for channel_id, members in list(channels.items()):

                if self.settings.ignore_afk_channels and channel_id in self.settings.afk_channel_ids:
                    continue

                base = set(members)
                if not base:
                    continue

                effective = self._compute_effective_members(guild_id, channel_id, now_ts, base)

                # ✅ DUO-ONLY: exactly 2 humans
                if len(effective) != 2:
                    continue

                a, b = sorted(effective)

                # Track overlap + streak updates
                duo_id, today_total, current_streak = await self._apply_overlap_tick(
                    guild_id, a, b, day_key, now_ts
                )

                # Fire tag condition:
                # - met today's required overlap OR already has active streak
                # Use effective config (DB overrides) so changes apply immediately
                cfg = await self.repos.get_effective_config(guild_id, self.settings)
                min_required = int(cfg.get("min_overlap_seconds", self.settings.min_overlap_seconds))

                if (today_total >= min_required) or (current_streak > 0):
                    desired_fire.setdefault(guild_id, set()).update({a, b})

        # Sync nicknames: add 🔥 to desired, remove from everyone else
        for gid in list(self.state.channel_members.keys()):
            await self._sync_fire_for_guild(gid, desired_fire.get(gid, set()))

    async def _apply_overlap_tick(self, guild_id: int, user_a: int, user_b: int, day_key: int, now_ts: int):
        """
        Adds overlap seconds for this duo and updates streak if day completed.
        Returns: (duo_id, today_total_seconds, current_streak_after)
        """
        duo_id = await self.repos.get_or_create_duo(guild_id, user_a, user_b, now_ts)

        today_total = await self.repos.add_duo_daily_seconds(
            guild_id=guild_id,
            duo_id=duo_id,
            day_key=day_key,
            seconds=self.settings.tick_seconds,
            now_ts=now_ts,
        )

        current, longest, last_completed = await self.repos.get_streak_row(guild_id, duo_id)

        became_completed, new_current, new_longest = compute_streak_transition(
            min_required_seconds=self.settings.min_overlap_seconds,
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
