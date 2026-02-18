# bot/cogs/streaks.py

import calendar
import discord
from discord.ext import commands
from datetime import date

from bot.core.timecore import now_utc_ts, day_key_from_utc_ts
from bot.ui.formatting import duo_status_embed


class StreaksCog(commands.Cog):
    def __init__(self, bot: commands.Bot, settings, repos):
        self.bot = bot
        self.settings = settings
        self.repos = repos

    # ---------------- internal helpers ----------------

    def _get_live_duo_from_vc(self, member: discord.Member):
        """Return other user if VC has exactly 2 humans."""
        if not member or not member.voice or not member.voice.channel:
            return None

        humans = [m for m in member.voice.channel.members if not m.bot]
        if len(humans) != 2:
            return None

        other = humans[0] if humans[1].id == member.id else humans[1]
        return other

    async def _duo_is_private(self, guild_id: int, u1: int, u2: int, default_private: bool):
        try:
            conn = await self.repos.raw_conn(guild_id)
            fallback = "1" if default_private else "0"

            cur = await conn.execute(
                """
                SELECT user_id, value
                FROM user_settings
                WHERE key='privacy_private' AND user_id IN (?, ?)
                """,
                (int(u1), int(u2)),
            )
            rows = await cur.fetchall()
            vals = {int(uid): str(val) for uid, val in rows}

            v1 = vals.get(int(u1), fallback)
            v2 = vals.get(int(u2), fallback)
            return (v1 == "1") or (v2 == "1")
        except Exception:
            return False

    async def _can_view_duo(self, ctx, user_a, user_b, cfg):
        default_private = bool(cfg.get("privacy_default_private", False))
        admin_can_view = bool(cfg.get("privacy_admin_can_view", True))

        is_private = await self._duo_is_private(ctx.guild.id, user_a.id, user_b.id, default_private)
        if not is_private:
            return True

        if ctx.author.id in (user_a.id, user_b.id):
            return True

        if admin_can_view and ctx.author.guild_permissions.administrator:
            return True

        return False

    def _streak_help_embed(self, ctx: commands.Context) -> discord.Embed:
        """
        Help embed for streak command.
        Kept as a helper so you can later move it into bot/ui/help_embeds.py if you want.
        """
        prefix = "!"
        # Try to pull prefix from bot if available (dev/prod prefix support)
        try:
            if isinstance(getattr(self.bot, "command_prefix", None), str):
                prefix = self.bot.command_prefix
        except Exception:
            pass

        embed = discord.Embed(
            title="🔥 Ignio — Streak Help",
            description="Everything streak-related lives under one command.",
        )

        embed.add_field(
            name="Quick Commands",
            value=(
                f"`{prefix}streak` → **quick check** with the person you’re in VC with (2 humans)\n"
                f"`{prefix}streak live` → **live VC check** (same idea, explicit)\n"
                f"`{prefix}streak @user` → your streak with someone\n"
                f"`{prefix}streak @user1 @user2` → streak between two people (privacy applies)"
            ),
            inline=False,
        )

        embed.add_field(
            name="How to start tracking",
            value="Join a VC with **exactly 2 real users**. Ignio starts tracking overlap automatically.",
            inline=False,
        )

        embed.add_field(
            name="Common issues",
            value=(
                "• If you’re alone in VC → invite 1 person\n"
                "• If there are 3+ people → it won’t count as a duo\n"
                "• Bots don’t count\n"
                "• If a duo is private → only the duo (and admins if enabled) can view"
            ),
            inline=False,
        )

        # Optional footer hint
        embed.set_footer(text="Tip: Use !streak help anytime you’re confused.")
        return embed

    async def _send_streak_help(self, ctx: commands.Context):
        return await ctx.reply(embed=self._streak_help_embed(ctx))

    async def _send_duo_embed(self, ctx, user_a, user_b):

        gid = ctx.guild.id
        now = now_utc_ts()
        cfg = await self.repos.get_effective_config(gid, self.settings)

        if not await self._can_view_duo(ctx, user_a, user_b, cfg):
            return await ctx.reply("🔒 This duo streak is private.")

        default_tz = str(cfg["default_tz"])
        grace_hour = int(cfg["grace_hour_local"])
        min_required = int(cfg["min_overlap_seconds"])
        bar_width = int(cfg["progress_bar_width"])

        heat_met = str(cfg.get("heatmap_met_emoji", "🟥"))
        heat_empty = str(cfg.get("heatmap_empty_emoji", "⬜"))

        today_key = day_key_from_utc_ts(now, default_tz, grace_hour)

        duo_id = await self.repos.get_duo_id(gid, user_a.id, user_b.id)
        if duo_id is None:
            return await ctx.reply(
                "No streak yet for this duo.\n"
                "Join a VC with exactly 2 real users to start tracking."
            )

        today_seconds = await self.repos.add_duo_daily_seconds(gid, duo_id, today_key, 0, now)
        current, longest, _ = await self.repos.get_streak_row(gid, duo_id)

        today = date.today()
        first_day_key = date(today.year, today.month, 1).toordinal()
        last_day_num = calendar.monthrange(today.year, today.month)[1]
        last_day_key = date(today.year, today.month, last_day_num).toordinal()

        day_map = await self.repos.get_duo_day_map(gid, duo_id, first_day_key, last_day_key)
        cs = await self.repos.get_connection_score_seconds(gid, duo_id)

        embed = duo_status_embed(
            user_a=user_a,
            user_b=user_b,
            today_seconds=today_seconds,
            min_required=min_required,
            current_streak=current,
            longest_streak=longest,
            bar_width=bar_width,
            status="active",
            connection_score_seconds=cs,
            heatmap_day_to_secs=day_map,
            heatmap_met_emoji=heat_met,
            heatmap_empty_emoji=heat_empty,
        )

        await ctx.reply(embed=embed)

    # ---------------- command ----------------

    @commands.command(name="streak", aliases=["duo"])
    @commands.guild_only()
    async def streak(self, ctx, arg1=None, arg2: discord.Member = None):
        """
        !streak
          -> quick check with VC duo (2 humans)
        !streak live
          -> explicit live VC check
        !streak help
          -> help embed
        !streak @user
          -> your streak with @user
        !streak @user1 @user2
          -> streak between two users (privacy applies)
        """

        # !streak help
        if isinstance(arg1, str) and arg1.lower() in ("help", "h", "?"):
            return await self._send_streak_help(ctx)

        # !streak live
        if isinstance(arg1, str) and arg1.lower() == "live":
            other = self._get_live_duo_from_vc(ctx.author)
            if other is None:
                # redirect to help instead of a confusing message
                return await self._send_streak_help(ctx)
            return await self._send_duo_embed(ctx, ctx.author, other)

        # !streak  (quick VC check)
        if arg1 is None:
            other = self._get_live_duo_from_vc(ctx.author)
            if other is None:
                # redirect to help embed
                return await self._send_streak_help(ctx)
            return await self._send_duo_embed(ctx, ctx.author, other)

        # !streak @user
        if isinstance(arg1, discord.Member) and arg2 is None:
            return await self._send_duo_embed(ctx, ctx.author, arg1)

        # !streak @user1 @user2
        if isinstance(arg1, discord.Member) and isinstance(arg2, discord.Member):
            return await self._send_duo_embed(ctx, arg1, arg2)

        # anything else -> help
        return await self._send_streak_help(ctx)
