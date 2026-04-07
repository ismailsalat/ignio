from __future__ import annotations

import calendar
from datetime import date, datetime, timedelta, timezone

import discord
from discord.ext import commands
from zoneinfo import ZoneInfo

from bot.core.timecore import now_utc_ts, day_key_from_utc_ts
from bot.ui.formatting import duo_status_embed
from bot.ui.help_embeds import streak_help_embed


class StreaksCog(commands.Cog):
    def __init__(self, bot: commands.Bot, settings, repos):
        self.bot = bot
        self.settings = settings
        self.repos = repos

    # ---------------- internal helpers ----------------

    def _get_prefix(self) -> str:
        try:
            p = getattr(self.bot, "command_prefix", None)
            if isinstance(p, str) and p.strip():
                return p.strip()
        except Exception:
            pass
        return "!"

    def _help_hint(self) -> str:
        return f"Need help? Use `{self._get_prefix()}streak help`."

    async def _soft_fail(self, ctx: commands.Context, msg: str):
        return await ctx.reply(f"{msg}\n{self._help_hint()}")

    async def _send_streak_help(self, ctx: commands.Context):
        return await ctx.reply(embed=streak_help_embed(ctx))

    async def _vc_requirements_fail(self, ctx: commands.Context, mode_label: str = "this command"):
        member = ctx.author if isinstance(ctx.author, discord.Member) else None
        if not member or not member.voice or not member.voice.channel:
            return await self._soft_fail(ctx, f"You're not in a voice channel, so I can't run {mode_label}.")

        ch = member.voice.channel
        humans = [m for m in ch.members if not m.bot]

        if len(humans) < 2:
            return await self._soft_fail(ctx, f"You need exactly **1 other real user** in VC to run {mode_label}.")
        if len(humans) > 2:
            return await self._soft_fail(ctx, f"Too many people in VC. You need **exactly 2 real users** to run {mode_label}.")

        return await self._soft_fail(ctx, f"I couldn't detect a valid duo for {mode_label}.")

    def _get_live_duo_from_vc(self, member: discord.Member) -> discord.Member | None:
        if not member or not member.voice or not member.voice.channel:
            return None

        humans = [m for m in member.voice.channel.members if not m.bot]
        if len(humans) != 2:
            return None

        other = humans[0] if humans[1].id == member.id else humans[1]
        if other.id == member.id:
            return None
        return other

    async def _duo_is_private(self, guild_id: int, u1: int, u2: int, default_private: bool) -> bool:
        v1 = await self.repos.get_user_setting_bool(
            guild_id=guild_id,
            user_id=u1,
            key="privacy_private",
            default=default_private,
        )
        v2 = await self.repos.get_user_setting_bool(
            guild_id=guild_id,
            user_id=u2,
            key="privacy_private",
            default=default_private,
        )
        return v1 or v2

    async def _can_view_duo(
        self,
        ctx: commands.Context,
        user_a: discord.Member,
        user_b: discord.Member,
        cfg: dict,
    ) -> bool:
        default_private = bool(cfg.get("privacy_default_private", 0))
        admin_can_view = bool(cfg.get("privacy_admin_can_view", 1))

        is_private = await self._duo_is_private(ctx.guild.id, user_a.id, user_b.id, default_private)
        if not is_private:
            return True

        if ctx.author.id in (user_a.id, user_b.id):
            return True

        if admin_can_view and ctx.author.guild_permissions.administrator:
            return True

        return False

    async def _get_month_day_map(self, streak_id: int, year: int, month: int) -> dict[int, int]:
        first_day_key = date(year, month, 1).toordinal()
        last_day_num = calendar.monthrange(year, month)[1]
        last_day_key = date(year, month, last_day_num).toordinal()

        day_map: dict[int, int] = {}
        for day_key in range(first_day_key, last_day_key + 1):
            row = await self.repos.get_progress_row(streak_id, day_key)
            if row is not None:
                day_map[day_key] = int(row["progress_seconds"])
        return day_map

    async def _get_recent_days_map(self, streak_id: int, days: int = 7) -> dict[int, int]:
        today = date.today()
        start = today - timedelta(days=max(1, days) - 1)

        day_map: dict[int, int] = {}
        cur = start
        while cur <= today:
            row = await self.repos.get_progress_row(streak_id, cur.toordinal())
            day_map[cur.toordinal()] = 0 if row is None else int(row["progress_seconds"])
            cur += timedelta(days=1)

        return day_map

    def _fmt_hms(self, seconds: int) -> str:
        seconds = max(0, int(seconds))
        h = seconds // 3600
        m = (seconds % 3600) // 60

        if h > 0 and m > 0:
            return f"{h}h {m}m"
        if h > 0:
            return f"{h}h"
        return f"{m}m"

    def _fmt_day_short(self, day_key: int) -> str:
        d = date.fromordinal(day_key)
        return d.strftime("%b %d")

    def _fmt_day_full(self, day_key: int) -> str:
        d = date.fromordinal(day_key)
        return d.strftime("%b %d, %Y")

    def _build_recent_summary(self, recent_map: dict[int, int]) -> str:
        parts: list[str] = []
        for day_key in sorted(recent_map.keys()):
            secs = int(recent_map[day_key])
            label = date.fromordinal(day_key).strftime("%a")
            if secs <= 0:
                parts.append(f"`{label}` — 0m")
            else:
                parts.append(f"`{label}` — {self._fmt_hms(secs)}")
        return "\n".join(parts)

    def _fmt_clock(self, dt_local: datetime) -> str:
        return dt_local.strftime("%b %d, %I:%M %p").replace(" 0", " ")

    def _compute_cycle_times(
        self,
        *,
        now_ts: int,
        default_tz: str,
        grace_hour_local: int,
        warning_minutes: int,
        restore_minutes: int,
    ) -> dict:
        tz = ZoneInfo(default_tz)
        now_local = datetime.fromtimestamp(now_ts, tz=timezone.utc).astimezone(tz)

        cutoff_today = now_local.replace(
            hour=int(grace_hour_local),
            minute=0,
            second=0,
            microsecond=0,
        )

        if now_local < cutoff_today:
            streak_end_local = cutoff_today
        else:
            streak_end_local = cutoff_today + timedelta(days=1)

        warning_start_local = streak_end_local - timedelta(minutes=max(0, int(warning_minutes)))
        restore_end_local = streak_end_local + timedelta(minutes=max(0, int(restore_minutes)))

        return {
            "now_local": now_local,
            "streak_end_local": streak_end_local,
            "warning_start_local": warning_start_local,
            "restore_end_local": restore_end_local,
            "seconds_until_streak_end": int((streak_end_local - now_local).total_seconds()),
            "seconds_until_warning": int((warning_start_local - now_local).total_seconds()),
            "seconds_until_restore_end": int((restore_end_local - now_local).total_seconds()),
        }

    async def _get_time_status_data(self, guild_id: int) -> dict:
        cfg = await self.repos.get_effective_config(guild_id, self.settings)

        default_tz = str(cfg.get("default_tz", self.settings.default_tz))
        grace_hour_local = int(cfg.get("grace_hour_local", self.settings.grace_hour_local))
        warning_minutes = int(
            cfg.get(
                "streak_end_warning_minutes",
                getattr(self.settings, "streak_end_warning_minutes", 60),
            )
        )
        restore_minutes = int(
            cfg.get(
                "streak_restore_window_minutes",
                getattr(self.settings, "streak_restore_window_minutes", 120),
            )
        )
        restore_enabled = bool(cfg.get("streak_restore_enabled", 1))

        info = self._compute_cycle_times(
            now_ts=now_utc_ts(),
            default_tz=default_tz,
            grace_hour_local=grace_hour_local,
            warning_minutes=warning_minutes,
            restore_minutes=restore_minutes,
        )

        return {
            "default_tz": default_tz,
            "restore_enabled": restore_enabled,
            "now_local": info["now_local"],
            "streak_end_local": info["streak_end_local"],
            "warning_start_local": info["warning_start_local"],
            "restore_end_local": info["restore_end_local"],
            "seconds_until_streak_end": max(0, int(info["seconds_until_streak_end"])),
            "seconds_until_warning": int(info["seconds_until_warning"]),
            "seconds_until_restore_end": max(0, int(info["seconds_until_restore_end"])),
        }

    async def _send_time_only(self, ctx: commands.Context):
        data = await self._get_time_status_data(ctx.guild.id)

        lines = [
            "**Streak Time**",
            f"• ends at `{self._fmt_clock(data['streak_end_local'])}`",
            f"• ends in `{self._fmt_hms(data['seconds_until_streak_end'])}`",
        ]

        if data["restore_enabled"]:
            lines.append(
                f"• restore ends `{self._fmt_clock(data['restore_end_local'])}` "
                f"(`{self._fmt_hms(data['seconds_until_restore_end'])}` left)"
            )

        await ctx.reply("\n".join(lines))

    async def _build_duo_profile_embed(
        self,
        ctx: commands.Context,
        *,
        user_a: discord.Member,
        user_b: discord.Member,
        streak_id: int,
        today_seconds: int,
        min_required: int,
        current: int,
        longest: int,
        total_completed_days: int,
        today_key: int,
        bar_width: int,
        heat_met: str,
        heat_empty: str,
    ) -> discord.Embed:
        today = date.today()
        month_map = await self._get_month_day_map(streak_id, today.year, today.month)
        recent_map = await self._get_recent_days_map(streak_id, days=7)

        connection_score_seconds = await self.repos.get_connection_score_seconds(streak_id)

        first_active_key = min(month_map.keys()) if month_map else None
        last_active_key = max(month_map.keys()) if month_map else None

        embed = duo_status_embed(
            user_a=user_a,
            user_b=user_b,
            today_seconds=today_seconds,
            min_required=min_required,
            current_streak=current,
            longest_streak=longest,
            bar_width=bar_width,
            status="active" if current > 0 else "idle",
            connection_score_seconds=connection_score_seconds,
            heatmap_day_to_secs=month_map,
            heatmap_met_emoji=heat_met,
            heatmap_empty_emoji=heat_empty,
            ends_in_text=None,
            restore_in_text=None,
        )

        if first_active_key is not None or last_active_key is not None:
            started_text = self._fmt_day_short(first_active_key) if first_active_key is not None else "—"
            last_text = self._fmt_day_short(last_active_key) if last_active_key is not None else "—"

            embed.add_field(
                name="Profile",
                value=(
                    f"**Current streak:** `{current}`\n"
                    f"**Longest streak:** `{longest}`\n"
                    f"**Completed days:** `{total_completed_days}`\n"
                    f"**First day this month:** `{started_text}`\n"
                    f"**Last active day this month:** `{last_text}`"
                ),
                inline=False,
            )
        else:
            embed.add_field(
                name="Profile",
                value=(
                    f"**Current streak:** `{current}`\n"
                    f"**Longest streak:** `{longest}`\n"
                    f"**Completed days:** `{total_completed_days}`"
                ),
                inline=False,
            )

        remaining_today = max(0, min_required - today_seconds)
        embed.add_field(
            name="Today",
            value=(
                f"**Progress:** `{self._fmt_hms(today_seconds)}` / `{self._fmt_hms(min_required)}`\n"
                f"**Left today:** `{self._fmt_hms(remaining_today)}`\n"
                f"**Connection score:** `{self._fmt_hms(connection_score_seconds)}`"
            ),
            inline=False,
        )

        embed.add_field(
            name="Last 7 Days",
            value=self._build_recent_summary(recent_map),
            inline=False,
        )

        embed.set_footer(text=f"Duo profile • Day key {today_key}")
        return embed

    async def _build_history_embed(
        self,
        ctx: commands.Context,
        *,
        user_a: discord.Member,
        user_b: discord.Member,
        streak_id: int,
    ) -> discord.Embed:
        state = await self.repos.get_streak_state(streak_id)
        current = 0 if state is None else int(state["current_streak"])
        longest = 0 if state is None else int(state["longest_streak"])
        total_completed_days = 0 if state is None else int(state["total_completed_days"])
        last_completed = -1 if state is None else int(state["last_completed_day_key"])

        recent_days = []
        if hasattr(self.repos, "get_recent_progress_days"):
            recent_days = await self.repos.get_recent_progress_days(streak_id, limit=10)
        else:
            recent_map = await self._get_recent_days_map(streak_id, days=10)
            recent_days = [
                {
                    "day_key": dk,
                    "progress_seconds": secs,
                    "qualified": 0,
                    "updated_at": 0,
                }
                for dk, secs in sorted(recent_map.items(), reverse=True)
            ]

        logs = []
        if hasattr(self.repos, "get_recent_activity_logs"):
            logs = await self.repos.get_recent_activity_logs(streak_id, limit=10)

        embed = discord.Embed(
            title="📜 Duo History",
            description=f"**{user_a.display_name} + {user_b.display_name}**",
        )

        embed.add_field(
            name="Summary",
            value=(
                f"**Current streak:** `{current}`\n"
                f"**Longest streak:** `{longest}`\n"
                f"**Completed days:** `{total_completed_days}`\n"
                f"**Last completed day:** `{self._fmt_day_full(last_completed) if last_completed > 0 else '—'}`"
            ),
            inline=False,
        )

        if recent_days:
            lines: list[str] = []
            for row in recent_days[:10]:
                day_key = int(row["day_key"])
                secs = int(row["progress_seconds"])
                qualified = int(row.get("qualified", 0))
                status = "✅" if qualified else "•"
                lines.append(f"{status} `{self._fmt_day_short(day_key)}` — `{self._fmt_hms(secs)}`")
            embed.add_field(
                name="Recent Days",
                value="\n".join(lines),
                inline=False,
            )
        else:
            embed.add_field(
                name="Recent Days",
                value="No history yet.",
                inline=False,
            )

        if logs:
            log_lines: list[str] = []
            for row in logs[:10]:
                event_type = str(row.get("event_type", "event"))
                seconds_delta = int(row.get("seconds_delta", 0))
                day_key = int(row.get("day_key", 0))

                if event_type == "vc_add":
                    label = "VC progress"
                elif event_type == "manual_add":
                    label = "Admin add"
                elif event_type == "admin_add":
                    label = "Admin add"
                else:
                    label = event_type.replace("_", " ").title()

                log_lines.append(
                    f"• `{self._fmt_day_short(day_key)}` — {label} `{self._fmt_hms(seconds_delta)}`"
                )

            embed.add_field(
                name="Recent Activity",
                value="\n".join(log_lines),
                inline=False,
            )

        embed.set_footer(text="Ignio history view")
        return embed

    async def _send_duo_embed(
        self,
        ctx: commands.Context,
        user_a: discord.Member,
        user_b: discord.Member,
        *,
        profile_mode: bool = False,
        history_mode: bool = False,
    ):
        if user_a.id == user_b.id:
            return await self._soft_fail(ctx, "You need two different users.")

        gid = ctx.guild.id
        now_ts = now_utc_ts()
        cfg = await self.repos.get_effective_config(gid, self.settings)

        if not await self._can_view_duo(ctx, user_a, user_b, cfg):
            return await ctx.reply("🔒 This duo streak is private.")

        default_tz = str(cfg.get("default_tz", self.settings.default_tz))
        grace_hour = int(cfg.get("grace_hour_local", self.settings.grace_hour_local))
        min_required = int(cfg.get("min_overlap_seconds", self.settings.min_overlap_seconds))
        bar_width = int(cfg.get("progress_bar_width", self.settings.progress_bar_width))

        heat_met = str(cfg.get("heatmap_met_emoji", "🟥"))
        heat_empty = str(cfg.get("heatmap_empty_emoji", "⬜"))

        today_key = day_key_from_utc_ts(now_ts, default_tz, grace_hour)

        streak = await self.repos.get_streak_by_member_hash(
            guild_id=gid,
            member_ids=[user_a.id, user_b.id],
            only_active=True,
        )

        if streak is None:
            return await ctx.reply(
                "No streak yet for this duo.\n"
                "Join a VC with exactly 2 real users to start tracking."
            )

        streak_id = int(streak["streak_id"])

        progress_row = await self.repos.get_progress_row(streak_id, today_key)
        today_seconds = 0 if progress_row is None else int(progress_row["progress_seconds"])

        state = await self.repos.get_streak_state(streak_id)
        if state is None:
            current = 0
            longest = 0
            total_completed_days = 0
        else:
            current = int(state["current_streak"])
            longest = int(state["longest_streak"])
            total_completed_days = int(state["total_completed_days"])

        if history_mode:
            embed = await self._build_history_embed(
                ctx,
                user_a=user_a,
                user_b=user_b,
                streak_id=streak_id,
            )
            return await ctx.reply(embed=embed)

        if profile_mode:
            embed = await self._build_duo_profile_embed(
                ctx,
                user_a=user_a,
                user_b=user_b,
                streak_id=streak_id,
                today_seconds=today_seconds,
                min_required=min_required,
                current=current,
                longest=longest,
                total_completed_days=total_completed_days,
                today_key=today_key,
                bar_width=bar_width,
                heat_met=heat_met,
                heat_empty=heat_empty,
            )
            return await ctx.reply(embed=embed)

        today = date.today()
        day_map = await self._get_month_day_map(streak_id, today.year, today.month)
        connection_score_seconds = sum(day_map.values())

        time_data = await self._get_time_status_data(gid)

        ends_in_text = self._fmt_hms(time_data["seconds_until_streak_end"])
        restore_in_text = None
        if time_data["restore_enabled"]:
            restore_in_text = self._fmt_hms(time_data["seconds_until_restore_end"])

        embed = duo_status_embed(
            user_a=user_a,
            user_b=user_b,
            today_seconds=today_seconds,
            min_required=min_required,
            current_streak=current,
            longest_streak=longest,
            bar_width=bar_width,
            status="active",
            connection_score_seconds=connection_score_seconds,
            heatmap_day_to_secs=day_map,
            heatmap_met_emoji=heat_met,
            heatmap_empty_emoji=heat_empty,
            ends_in_text=ends_in_text,
            restore_in_text=restore_in_text,
        )
        await ctx.reply(embed=embed)

    # ---------------- command ----------------

    @commands.command(name="streak", aliases=["duo"])
    @commands.guild_only()
    async def streak(self, ctx: commands.Context, *args: str):
        """
        !streak
        !streak live
        !streak time
        !streak help
        !streak @user
        !streak @user1 @user2
        !streak profile @user
        !streak card @user
        !streak history @user
        !streak logs @user
        !streak recent @user
        """

        if not args:
            other = self._get_live_duo_from_vc(ctx.author)
            if other is None:
                return await self._vc_requirements_fail(ctx, mode_label="`streak`")
            return await self._send_duo_embed(ctx, ctx.author, other)

        text = " ".join(args).strip().lower()

        if text in ("help", "h", "?"):
            return await self._send_streak_help(ctx)

        if text == "live":
            other = self._get_live_duo_from_vc(ctx.author)
            if other is None:
                return await self._vc_requirements_fail(ctx, mode_label="`streak live`")
            return await self._send_duo_embed(ctx, ctx.author, other)

        if text == "time":
            return await self._send_time_only(ctx)

        mentions = ctx.message.mentions
        head = args[0].lower()

        if head in ("profile", "card"):
            if len(mentions) == 1:
                return await self._send_duo_embed(ctx, ctx.author, mentions[0], profile_mode=True)

            if len(mentions) == 2:
                return await self._send_duo_embed(ctx, mentions[0], mentions[1], profile_mode=True)

            return await ctx.reply(
                f"Use `{self._get_prefix()}streak profile @user` or `{self._get_prefix()}streak profile @user1 @user2`."
            )

        if head in ("history", "logs", "recent"):
            if len(mentions) == 1:
                return await self._send_duo_embed(ctx, ctx.author, mentions[0], history_mode=True)

            if len(mentions) == 2:
                return await self._send_duo_embed(ctx, mentions[0], mentions[1], history_mode=True)

            return await ctx.reply(
                f"Use `{self._get_prefix()}streak history @user` or `{self._get_prefix()}streak history @user1 @user2`."
            )

        if len(mentions) == 1:
            return await self._send_duo_embed(ctx, ctx.author, mentions[0])

        if len(mentions) == 2:
            return await self._send_duo_embed(ctx, mentions[0], mentions[1])

        return await self._send_streak_help(ctx)


async def setup(bot: commands.Bot):
    settings = getattr(bot, "settings", None)
    repos = getattr(bot, "repos", None)
    await bot.add_cog(StreaksCog(bot, settings, repos))