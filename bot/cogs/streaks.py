from __future__ import annotations

import calendar
from datetime import date

import discord
from discord.ext import commands

from bot.core.timecore import now_utc_ts, day_key_from_utc_ts
from bot.ui.formatting import duo_status_embed
from bot.ui.help_embeds import streak_help_embed


class StreaksCog(commands.Cog):
    def __init__(self, bot: commands.Bot, settings, repos):
        self.bot = bot
        self.settings = settings
        self.repos = repos

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

    async def _send_duo_embed(
        self,
        ctx: commands.Context,
        user_a: discord.Member,
        user_b: discord.Member,
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
        else:
            current = int(state["current_streak"])
            longest = int(state["longest_streak"])

        today = date.today()
        day_map = await self._get_month_day_map(streak_id, today.year, today.month)
        connection_score_seconds = sum(day_map.values())

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
        )
        await ctx.reply(embed=embed)

    @commands.command(name="streak", aliases=["duo"])
    @commands.guild_only()
    async def streak(self, ctx: commands.Context, *args: str):
        """
        !streak
        !streak live
        !streak help
        !streak @user
        !streak @user1 @user2
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

        members = ctx.message.mentions

        if len(members) == 1:
            return await self._send_duo_embed(ctx, ctx.author, members[0])

        if len(members) == 2:
            return await self._send_duo_embed(ctx, members[0], members[1])

        return await self._send_streak_help(ctx)