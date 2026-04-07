from __future__ import annotations

import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import discord
from discord.ext import commands, tasks

from bot.core.state import VcRuntimeState
from bot.core.timecore import now_utc_ts, day_key_from_utc_ts
from bot.core.streak_engine import compute_streak_transition
from bot.ui.help_embeds import (
    end_of_day_warning_embed,
    restore_success_embed,
    streak_lost_embed,
    streak_restore_available_embed,
)


class VcTrackerCog(commands.Cog):
    """
    Duo-only VC tracker + fire nickname sync + restore/reminder flow.

    Fire rule:
    - fire shows only if user is in a valid duo VC
    - and that duo still has current_streak > 0

    Reminder / restore flow:
    - end-of-day reminder: warns active streak duos before the streak day ends
    - restore window: if a streak misses a day, users can still save it for a short window
    - lost / ice: once restore expires, current_streak becomes 0
    """

    def __init__(self, bot: commands.Bot, settings, repos, vc_state: VcRuntimeState | None = None):
        self.bot = bot
        self.settings = settings
        self.repos = repos
        self.state = vc_state or VcRuntimeState()
        self._bootstrapped = False

        self._fire_active: dict[int, set[int]] = {}
        self._fire_snapshot: dict[int, dict[int, dict[str, str | None]]] = {}
        self._nick_edit_last_ts: dict[tuple[int, int], float] = {}

        # anti-spam memory guards
        self._warning_sent: set[tuple[int, int, int]] = set()          # (streak_id, day_key, user_id)
        self._restore_sent: set[tuple[int, int, int]] = set()          # (streak_id, day_key, user_id)
        self._restore_success_sent: set[tuple[int, int, int]] = set()  # (streak_id, day_key, user_id)
        self._ice_sent: set[tuple[int, int, int]] = set()              # (streak_id, day_key, user_id)

        self.tick.start()

    def cog_unload(self):
        self.tick.cancel()

    # ---------------- config helpers ----------------

    def _fire_enabled(self) -> bool:
        return bool(getattr(self.settings, "nickname_fire_enabled", True))

    def _fire_suffix(self) -> str:
        return str(getattr(self.settings, "nickname_fire_suffix", " 🔥"))

    def _nick_edit_min_interval(self) -> float:
        return float(getattr(self.settings, "nickname_edit_min_interval_seconds", 20))

    def _restore_enabled(self) -> bool:
        return bool(getattr(self.settings, "streak_restore_enabled", True))

    def _restore_window_minutes(self) -> int:
        return int(getattr(self.settings, "streak_restore_window_minutes", 120))

    def _day_warning_minutes(self) -> int:
        return int(getattr(self.settings, "streak_end_warning_minutes", 60))

    # ---------------- fire helpers ----------------

    def _has_fire_text(self, text: str | None) -> bool:
        return bool(text and text.endswith(self._fire_suffix()))

    def _strip_fire(self, text: str) -> str:
        suffix = self._fire_suffix()
        return text[:-len(suffix)] if text.endswith(suffix) else text

    def _can_try_edit_now(self, guild_id: int, user_id: int) -> bool:
        key = (guild_id, user_id)
        last = self._nick_edit_last_ts.get(key, 0.0)
        return (time.time() - last) >= self._nick_edit_min_interval()

    def _mark_edit_now(self, guild_id: int, user_id: int) -> None:
        self._nick_edit_last_ts[(guild_id, user_id)] = time.time()

    def _remember_original_state(self, member: discord.Member) -> None:
        guild_map = self._fire_snapshot.setdefault(member.guild.id, {})
        if member.id in guild_map:
            return

        guild_map[member.id] = {
            "orig_nick": member.nick,
            "orig_display_name": member.display_name,
        }

    def _get_me(self, guild: discord.Guild) -> discord.Member | None:
        me = guild.me
        if me is not None:
            return me
        if self.bot.user is None:
            return None
        return guild.get_member(self.bot.user.id)

    def _can_edit_member_nick(self, member: discord.Member) -> bool:
        me = self._get_me(member.guild)
        if me is None:
            return False

        if not me.guild_permissions.manage_nicknames:
            return False

        if member == member.guild.owner:
            return False

        if member.top_role >= me.top_role:
            return False

        return True

    async def _apply_fire(self, guild: discord.Guild, user_id: int) -> None:
        if not self._fire_enabled():
            return

        if not self._can_try_edit_now(guild.id, user_id):
            return

        member = guild.get_member(user_id)
        if member is None or member.bot:
            return

        if not self._can_edit_member_nick(member):
            return

        if self._has_fire_text(member.display_name):
            self._fire_active.setdefault(guild.id, set()).add(user_id)
            return

        self._remember_original_state(member)

        base = self._strip_fire(member.nick if member.nick is not None else member.display_name)
        new_nick = base + self._fire_suffix()

        if member.nick == new_nick:
            self._fire_active.setdefault(guild.id, set()).add(user_id)
            return

        try:
            self._mark_edit_now(guild.id, user_id)
            await member.edit(nick=new_nick, reason="Ignio: active streak")
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

        if not self._can_edit_member_nick(member):
            return

        snap = self._fire_snapshot.get(guild.id, {}).get(user_id)

        if snap is None:
            if member.nick is None:
                self._fire_active.get(guild.id, set()).discard(user_id)
                return
            desired_nick = self._strip_fire(member.nick)
        else:
            orig_nick = snap.get("orig_nick")
            orig_display_name = str(snap.get("orig_display_name") or "")

            if orig_nick is not None:
                desired_nick = orig_nick
            else:
                current_base = self._strip_fire(member.display_name)
                if current_base == orig_display_name:
                    desired_nick = None
                else:
                    desired_nick = orig_display_name

        try:
            if member.nick != desired_nick:
                self._mark_edit_now(guild.id, user_id)
                await member.edit(nick=desired_nick, reason="Ignio: streak fire removed")
        except (discord.Forbidden, discord.HTTPException):
            return
        finally:
            self._fire_active.get(guild.id, set()).discard(user_id)
            if guild.id in self._fire_snapshot:
                self._fire_snapshot[guild.id].pop(user_id, None)

    async def _sync_fire_for_guild(self, guild_id: int, desired_users: set[int]) -> None:
        if not self._fire_enabled():
            return

        guild = self.bot.get_guild(guild_id)
        if guild is None:
            return

        active = self._fire_active.setdefault(guild_id, set())

        for user_id in (desired_users - active):
            await self._apply_fire(guild, user_id)

        for user_id in list(active - desired_users):
            await self._remove_fire(guild, user_id)

    # ---------------- bootstrap ----------------

    async def bootstrap_voice_state(self) -> None:
        if self._bootstrapped:
            return

        ignore_afk = bool(getattr(self.settings, "ignore_afk_channels", False))
        afk_ids = set(getattr(self.settings, "afk_channel_ids", ()))

        for guild in self.bot.guilds:
            gid = guild.id

            for ch in guild.voice_channels:
                if ignore_afk and ch.id in afk_ids:
                    self.state.remove_channel(gid, ch.id)
                    continue

                members = {m.id for m in ch.members if not m.bot}
                if members:
                    self.state.set_channel_members(gid, ch.id, members)
                else:
                    self.state.remove_channel(gid, ch.id)

        self._bootstrapped = True
        print("[Ignio] VC bootstrap done")

    @commands.Cog.listener()
    async def on_ready(self):
        await self.bootstrap_voice_state()

    # ---------------- voice updates ----------------

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

        ignore_afk = bool(getattr(self.settings, "ignore_afk_channels", False))
        afk_ids = set(getattr(self.settings, "afk_channel_ids", ()))

        for ch in (before.channel, after.channel):
            if ch is None:
                continue

            if ignore_afk and ch.id in afk_ids:
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

    # ---------------- streak day time helpers ----------------

    def _get_day_timing(self, default_tz: str, grace_hour: int) -> tuple[int, int]:
        """
        Returns:
        - current streak-day start unix ts
        - next streak-day boundary unix ts
        """
        tz = ZoneInfo(default_tz)
        local_now = datetime.now(tz)

        shifted = local_now - timedelta(hours=grace_hour)
        shifted_day_start = shifted.replace(hour=0, minute=0, second=0, microsecond=0)
        current_day_start = shifted_day_start + timedelta(hours=grace_hour)
        next_day_start = current_day_start + timedelta(days=1)

        return int(current_day_start.timestamp()), int(next_day_start.timestamp())

    def _seconds_until_day_end(self, default_tz: str, grace_hour: int) -> int:
        _, next_day_ts = self._get_day_timing(default_tz, grace_hour)
        return max(0, int(next_day_ts - now_utc_ts()))

    def _minutes_since_day_start(self, default_tz: str, grace_hour: int) -> int:
        current_day_ts, _ = self._get_day_timing(default_tz, grace_hour)
        return max(0, int((now_utc_ts() - current_day_ts) // 60))

    # ---------------- DM helpers ----------------

    async def _user_dm_enabled(
        self,
        guild_id: int,
        user_id: int,
        *,
        specific_key: str | None = None,
    ) -> bool:
        defaults = await self.repos.get_effective_config(guild_id, self.settings)

        master_on = await self.repos.get_user_setting_bool(
            guild_id=guild_id,
            user_id=user_id,
            key="dm_reminders_enabled",
            default=bool(defaults.get("dm_reminders_enabled", True)),
        )
        if not master_on:
            return False

        if specific_key is None:
            return True

        default_map = {
            "dm_streak_end_enabled": bool(defaults.get("dm_streak_end_enabled", True)),
            "dm_streak_end_restore_enabled": bool(defaults.get("dm_streak_end_restore_enabled", True)),
            "dm_streak_end_ice_enabled": bool(defaults.get("dm_streak_end_ice_enabled", True)),
        }

        return await self.repos.get_user_setting_bool(
            guild_id=guild_id,
            user_id=user_id,
            key=specific_key,
            default=default_map.get(specific_key, True),
        )

    def _other_member_label(self, guild: discord.Guild, target_user_id: int) -> str | None:
        member = guild.get_member(target_user_id)
        if member is None:
            return None
        return member.display_name

    async def _send_embed_dm(
        self,
        guild: discord.Guild,
        user_id: int,
        embed: discord.Embed,
        *,
        specific_key: str | None = None,
    ) -> None:
        if not await self._user_dm_enabled(guild.id, user_id, specific_key=specific_key):
            return

        member = guild.get_member(user_id)
        if member is None or member.bot:
            return

        try:
            await member.send(embed=embed)
        except (discord.Forbidden, discord.HTTPException):
            return

    async def _send_restore_available_dm(
        self,
        guild: discord.Guild,
        streak_id: int,
        current_day_key: int,
        user_a: int,
        user_b: int,
        minutes_left: int,
    ) -> None:
        for user_id, other_id in ((user_a, user_b), (user_b, user_a)):
            dm_key = (streak_id, current_day_key, user_id)
            if dm_key in self._restore_sent:
                continue

            duo_label = self._other_member_label(guild, other_id)
            embed = streak_restore_available_embed(
                guild,
                duo_label=duo_label,
                minutes_left=minutes_left,
            )
            await self._send_embed_dm(
                guild,
                user_id,
                embed,
                specific_key="dm_streak_end_restore_enabled",
            )
            self._restore_sent.add(dm_key)

    async def _send_restore_success_dm(
        self,
        guild: discord.Guild,
        streak_id: int,
        current_day_key: int,
        user_a: int,
        user_b: int,
        current_streak: int,
    ) -> None:
        for user_id, other_id in ((user_a, user_b), (user_b, user_a)):
            dm_key = (streak_id, current_day_key, user_id)
            if dm_key in self._restore_success_sent:
                continue

            duo_label = self._other_member_label(guild, other_id)
            embed = restore_success_embed(
                guild,
                duo_label=duo_label,
                current_streak=current_streak,
            )
            await self._send_embed_dm(
                guild,
                user_id,
                embed,
                specific_key="dm_streak_end_restore_enabled",
            )
            self._restore_success_sent.add(dm_key)

    async def _send_ice_dm(
        self,
        guild: discord.Guild,
        streak_id: int,
        current_day_key: int,
        user_a: int,
        user_b: int,
    ) -> None:
        for user_id, other_id in ((user_a, user_b), (user_b, user_a)):
            dm_key = (streak_id, current_day_key, user_id)
            if dm_key in self._ice_sent:
                continue

            duo_label = self._other_member_label(guild, other_id)
            embed = streak_lost_embed(
                guild,
                duo_label=duo_label,
            )
            await self._send_embed_dm(
                guild,
                user_id,
                embed,
                specific_key="dm_streak_end_ice_enabled",
            )
            self._ice_sent.add(dm_key)

    async def _send_end_of_day_warning_dm(
        self,
        guild: discord.Guild,
        streak_id: int,
        current_day_key: int,
        user_a: int,
        user_b: int,
        remaining_seconds: int,
    ) -> None:
        for user_id, other_id in ((user_a, user_b), (user_b, user_a)):
            dm_key = (streak_id, current_day_key, user_id)
            if dm_key in self._warning_sent:
                continue

            duo_label = self._other_member_label(guild, other_id)
            embed = end_of_day_warning_embed(
                guild,
                duo_label=duo_label,
                remaining_seconds=remaining_seconds,
            )
            await self._send_embed_dm(
                guild,
                user_id,
                embed,
                specific_key=None,
            )
            self._warning_sent.add(dm_key)

    # ---------------- fire state ----------------

    async def _duo_has_active_streak(self, guild_id: int, user_a: int, user_b: int) -> bool:
        streak = await self.repos.get_streak_by_member_hash(
            guild_id=guild_id,
            member_ids=[user_a, user_b],
            only_active=True,
        )
        if streak is None:
            return False

        state = await self.repos.get_streak_state(int(streak["streak_id"]))
        if state is None:
            return False

        return int(state["current_streak"]) > 0

    async def _get_desired_fire_users_for_guild(self, guild_id: int) -> set[int]:
        cfg = await self.repos.get_effective_config(guild_id, self.settings)
        disconnect_buf = int(cfg.get("disconnect_buffer_seconds", self.settings.disconnect_buffer_seconds))
        ignore_afk = bool(cfg.get("ignore_afk_channels", 0))
        afk_ids = set(getattr(self.settings, "afk_channel_ids", ()))
        now_ts = now_utc_ts()

        channels = self.state.channel_members.get(guild_id, {})
        result: set[int] = set()

        for channel_id, members in list(channels.items()):
            if ignore_afk and channel_id in afk_ids:
                continue

            if not members:
                continue

            effective = self._compute_effective_members(
                guild_id=guild_id,
                channel_id=channel_id,
                now_ts=now_ts,
                base_members=set(members),
                disconnect_buffer_seconds=disconnect_buf,
            )

            if len(effective) != 2:
                continue

            user_a, user_b = sorted(effective)

            if await self._duo_has_active_streak(guild_id, user_a, user_b):
                result.add(user_a)
                result.add(user_b)

        return result

    # ---------------- reminder / restore sweep ----------------

    async def _process_streak_notifications_for_guild(self, guild: discord.Guild) -> None:
        guild_id = guild.id
        cfg = await self.repos.get_effective_config(guild_id, self.settings)

        default_tz = str(cfg.get("default_tz", self.settings.default_tz))
        grace_hour = int(cfg.get("grace_hour_local", self.settings.grace_hour_local))
        min_required = int(cfg.get("min_overlap_seconds", self.settings.min_overlap_seconds))

        today_key = day_key_from_utc_ts(now_utc_ts(), default_tz, grace_hour)
        seconds_left_today = self._seconds_until_day_end(default_tz, grace_hour)
        minutes_since_day_start = self._minutes_since_day_start(default_tz, grace_hour)
        restore_window_minutes = self._restore_window_minutes()
        warning_seconds = self._day_warning_minutes() * 60

        rows = await self.repos.top_by_current_streak(
            guild_id=guild_id,
            limit=1000,
            streak_type="duo",
        )

        for row in rows:
            current = int(row["current_streak"])
            if current <= 0:
                continue

            streak_id = int(row["streak_id"])
            member_ids = await self.repos.get_streak_members(streak_id)
            if len(member_ids) != 2:
                continue

            user_a, user_b = sorted(int(x) for x in member_ids)

            state = await self.repos.get_streak_state(streak_id)
            if state is None:
                continue

            current = int(state["current_streak"])
            longest = int(state["longest_streak"])
            total_completed_days = int(state["total_completed_days"])
            last_completed = int(state["last_completed_day_key"])

            progress_row = await self.repos.get_progress_row(streak_id, today_key)
            today_seconds = 0 if progress_row is None else int(progress_row["progress_seconds"])

            # normal active day: they qualified yesterday, still need today
            if last_completed == today_key - 1:
                if 0 < seconds_left_today <= warning_seconds and today_seconds < min_required:
                    remaining_seconds = max(0, min_required - today_seconds)
                    await self._send_end_of_day_warning_dm(
                        guild,
                        streak_id,
                        today_key,
                        user_a,
                        user_b,
                        remaining_seconds,
                    )
                continue

            # restore-pending day:
            # they missed the previous streak day, but can still rescue during restore window
            if self._restore_enabled() and last_completed == today_key - 2:
                within_restore = minutes_since_day_start < restore_window_minutes

                if today_seconds >= min_required and within_restore:
                    new_current = current + 1
                    new_longest = max(longest, new_current)

                    await self.repos.set_day_qualified(
                        streak_id=streak_id,
                        guild_id=guild_id,
                        day_key=today_key,
                        qualified=True,
                        now_ts=now_utc_ts(),
                    )

                    await self.repos.save_streak_state(
                        streak_id=streak_id,
                        guild_id=guild_id,
                        current_streak=new_current,
                        longest_streak=new_longest,
                        total_completed_days=total_completed_days + 1,
                        last_completed_day_key=today_key,
                        now_ts=now_utc_ts(),
                    )

                    await self._send_restore_success_dm(
                        guild,
                        streak_id,
                        today_key,
                        user_a,
                        user_b,
                        new_current,
                    )
                    continue

                if within_restore:
                    minutes_left = max(1, restore_window_minutes - minutes_since_day_start)
                    await self._send_restore_available_dm(
                        guild,
                        streak_id,
                        today_key,
                        user_a,
                        user_b,
                        minutes_left,
                    )
                    continue

                # restore expired -> streak dies
                await self.repos.save_streak_state(
                    streak_id=streak_id,
                    guild_id=guild_id,
                    current_streak=0,
                    longest_streak=longest,
                    total_completed_days=total_completed_days,
                    last_completed_day_key=last_completed,
                    now_ts=now_utc_ts(),
                )

                await self._send_ice_dm(
                    guild,
                    streak_id,
                    today_key,
                    user_a,
                    user_b,
                )
                continue

            # stale old streak safety cleanup
            if last_completed <= today_key - 3 and current > 0:
                await self.repos.save_streak_state(
                    streak_id=streak_id,
                    guild_id=guild_id,
                    current_streak=0,
                    longest_streak=longest,
                    total_completed_days=total_completed_days,
                    last_completed_day_key=last_completed,
                    now_ts=now_utc_ts(),
                )

                await self._send_ice_dm(
                    guild,
                    streak_id,
                    today_key,
                    user_a,
                    user_b,
                )

    # ---------------- tick loop ----------------

    @tasks.loop(seconds=15)
    async def tick(self):
        if not self.bot.is_ready():
            return

        now_ts = now_utc_ts()
        guild_ids_seen = set(self.state.channel_members.keys())

        for guild_id, channels in list(self.state.channel_members.items()):
            cfg = await self.repos.get_effective_config(guild_id, self.settings)

            default_tz = str(cfg.get("default_tz", self.settings.default_tz))
            grace_hour = int(cfg.get("grace_hour_local", self.settings.grace_hour_local))
            tick_seconds = int(cfg.get("tick_seconds", self.settings.tick_seconds))
            min_required = int(cfg.get("min_overlap_seconds", self.settings.min_overlap_seconds))
            disconnect_buf = int(cfg.get("disconnect_buffer_seconds", self.settings.disconnect_buffer_seconds))
            ignore_afk = bool(cfg.get("ignore_afk_channels", 0))
            daily_cap_seconds = int(cfg.get("daily_cap_seconds", getattr(self.settings, "daily_cap_seconds", 0)))

            afk_ids = set(getattr(self.settings, "afk_channel_ids", ()))
            day_key = day_key_from_utc_ts(now_ts, default_tz, grace_hour)

            for channel_id, members in list(channels.items()):
                if ignore_afk and channel_id in afk_ids:
                    continue

                if not members:
                    continue

                effective = self._compute_effective_members(
                    guild_id=guild_id,
                    channel_id=channel_id,
                    now_ts=now_ts,
                    base_members=set(members),
                    disconnect_buffer_seconds=disconnect_buf,
                )

                if len(effective) != 2:
                    continue

                user_a, user_b = sorted(effective)

                await self._apply_overlap_tick(
                    guild_id=guild_id,
                    user_a=user_a,
                    user_b=user_b,
                    day_key=day_key,
                    now_ts=now_ts,
                    tick_seconds=tick_seconds,
                    min_required_seconds=min_required,
                    daily_cap_seconds=daily_cap_seconds,
                )

        # process reminder/restore/lost flow after progress updates
        for guild in self.bot.guilds:
            await self._process_streak_notifications_for_guild(guild)

        guild_ids_to_sync = guild_ids_seen | set(self._fire_active.keys()) | {g.id for g in self.bot.guilds}

        for guild_id in guild_ids_to_sync:
            desired_users = await self._get_desired_fire_users_for_guild(guild_id)
            await self._sync_fire_for_guild(guild_id, desired_users)

    async def _apply_overlap_tick(
        self,
        guild_id: int,
        user_a: int,
        user_b: int,
        day_key: int,
        now_ts: int,
        tick_seconds: int,
        min_required_seconds: int,
        daily_cap_seconds: int = 0,
    ) -> tuple[int, int, int]:
        streak_id = await self.repos.get_or_create_duo(guild_id, user_a, user_b, now_ts)

        today_total = await self.repos.add_progress_seconds(
            streak_id=streak_id,
            guild_id=guild_id,
            day_key=day_key,
            seconds=tick_seconds,
            now_ts=now_ts,
            event_type="vc_add",
            meta_json=None,
            daily_cap_seconds=daily_cap_seconds,
        )

        state = await self.repos.get_streak_state(streak_id)
        if state is None:
            current = 0
            longest = 0
            total_completed_days = 0
            last_completed = -1
        else:
            current = int(state["current_streak"])
            longest = int(state["longest_streak"])
            total_completed_days = int(state["total_completed_days"])
            last_completed = int(state["last_completed_day_key"])

        became_completed, new_current, new_longest = compute_streak_transition(
            min_required_seconds=min_required_seconds,
            today_seconds=today_total,
            today_day_key=day_key,
            last_completed_day_key=last_completed,
            current_streak=current,
            longest_streak=longest,
        )

        if became_completed:
            await self.repos.set_day_qualified(
                streak_id=streak_id,
                guild_id=guild_id,
                day_key=day_key,
                qualified=True,
                now_ts=now_ts,
            )

            await self.repos.save_streak_state(
                streak_id=streak_id,
                guild_id=guild_id,
                current_streak=new_current,
                longest_streak=new_longest,
                total_completed_days=total_completed_days + 1,
                last_completed_day_key=day_key,
                now_ts=now_ts,
            )

            current = new_current
            print(f"[Ignio] ✅ duo complete: guild={guild_id} users={user_a}+{user_b} streak={new_current}")

        return streak_id, today_total, current

    @tick.before_loop
    async def before_tick(self):
        await self.bot.wait_until_ready()
        await self.bootstrap_voice_state()