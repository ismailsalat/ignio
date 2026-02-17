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
    """

    def __init__(self, bot: commands.Bot, settings, repos):
        self.bot = bot
        self.settings = settings
        self.repos = repos
        self.state = VcRuntimeState()
        self._bootstrapped = False
        self.tick.start()

    def cog_unload(self):
        self.tick.cancel()

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
        # On some setups, before_loop runs but cache isn't fully ready.
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

        # 1) Mark leaving (for disconnect buffer) ONLY if they were in a channel and now aren't
        if before.channel is not None and after.channel is None:
            self.state.mark_left(guild_id, member.id, before.channel.id, now_ts)

        # 2) If they are connected anywhere now, clear "recently_left"
        #    (covers reconnects + channel switching)
        if after.channel is not None:
            self.state.clear_left(guild_id, member.id)

        # 3) Refresh membership sets for affected channels (before + after)
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

        # Apply disconnect buffer: include people who recently left THIS channel in THIS guild
        for (g_id, u_id), (left_ch, left_ts) in list(self.state.recently_left.items()):
            if g_id != guild_id or left_ch != channel_id:
                continue

            age = now_ts - left_ts
            if age <= self.settings.disconnect_buffer_seconds:
                effective.add(u_id)
            else:
                # buffer expired
                self.state.clear_left(guild_id, u_id)

        return effective

    # ---------------- tick loop ----------------

    @tasks.loop(seconds=15)
    async def tick(self):
        # If bot not ready yet, do nothing (before_loop also handles this)
        if not self.bot.is_ready():
            return

        now_ts = now_utc_ts()
        day_key = day_key_from_utc_ts(now_ts, self.settings.default_tz, self.settings.grace_hour_local)

        # Iterate over tracked guild/channel membership
        for guild_id, channels in list(self.state.channel_members.items()):
            for channel_id, members in list(channels.items()):

                # ignore AFK channels if configured
                if self.settings.ignore_afk_channels and channel_id in self.settings.afk_channel_ids:
                    continue

                # base "humans currently in channel" set (already non-bot in state)
                base = set(members)
                if not base:
                    continue

                # apply disconnect buffer
                effective = self._compute_effective_members(guild_id, channel_id, now_ts, base)

                # ✅ DUO-ONLY RULE:
                # must be exactly 2 real users (after buffer) to count
                # - 1 user => ignore
                # - 3+ users => ignore (prevents pairwise farming)
                if len(effective) != 2:
                    continue

                a, b = sorted(effective)
                await self._apply_overlap_tick(guild_id, a, b, day_key, now_ts)

    async def _apply_overlap_tick(self, guild_id: int, user_a: int, user_b: int, day_key: int, now_ts: int):
        """
        Adds overlap seconds for this duo and updates streak if day completed.
        NOTE: This will auto-create a duo row if it doesn't exist yet.
        If you want "only after command", tell me and I’ll swap to get_duo_id + gate.
        """
        duo_id = await self.repos.get_or_create_duo(guild_id, user_a, user_b, now_ts)

        # Add seconds for today (repo should clamp/cap if you support daily caps)
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
            print(f"[Ignio] ✅ duo complete: guild={guild_id} users={user_a}+{user_b} streak={new_current}")

    @tick.before_loop
    async def before_tick(self):
        await self.bot.wait_until_ready()
        await self.bootstrap_voice_state()
