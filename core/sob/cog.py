# core/sob/cog.py
from __future__ import annotations

import time

import discord
from discord.ext import commands

from core.sob import embeds
from core.sob.repo import SobRepo


class SobCog(commands.Cog):
    def __init__(self, bot: commands.Bot, settings, sob_repo: SobRepo, shop_repo=None, profile_service=None, economy=None):
        self.bot = bot
        self.settings = settings
        self.sob_repo = sob_repo
        self.shop_repo = shop_repo
        self.profile = profile_service
        self.economy = economy

    # ----- helpers -------------------------------------------------------

    async def _is_sob_emoji(self, guild_id: int, emoji) -> bool:
        name = emoji if isinstance(emoji, str) else getattr(emoji, "name", str(emoji))
        accepted = await self.sob_repo.get_accepted_emojis(guild_id)
        return name in accepted or str(emoji) in accepted

    async def _resolve_message(self, channel, message_id: int) -> discord.Message | None:
        if channel is None:
            return None
        try:
            return await channel.fetch_message(message_id)
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            return None

    # ----- reaction listeners -------------------------------------------

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload: discord.RawReactionActionEvent):
        if payload.guild_id is None:
            return
        if not await self._is_sob_emoji(payload.guild_id, payload.emoji):
            return

        guild = self.bot.get_guild(payload.guild_id)
        if guild is None:
            return

        reactor = guild.get_member(payload.user_id)
        if reactor is None or reactor.bot:
            return

        channel = guild.get_channel(payload.channel_id)
        message = await self._resolve_message(channel, payload.message_id)
        if message is None or message.author.bot:
            return

        target_id = message.author.id
        if target_id == payload.user_id:
            return

        threshold = await self.sob_repo.get_snitch_threshold(payload.guild_id)
        added = await self.sob_repo.add_sob(
            guild_id=payload.guild_id,
            message_id=payload.message_id,
            reactor_id=payload.user_id,
            target_id=target_id,
            snitch_threshold=threshold,
        )

        # Sob multiplier: base add_sob gives 1; if the server's multiplier is >1,
        # credit the extra. <1 isn't applied to a single reaction (can't give
        # fractional sobs), so the multiplier floors at giving the base 1.
        if added and self.economy is not None:
            try:
                mult = await self.economy.get_sob_multiplier(payload.guild_id)
                extra = int(round(mult)) - 1
                if extra > 0:
                    await self.sob_repo.adjust_received(payload.guild_id, target_id, extra)
            except Exception:
                pass

    @commands.Cog.listener()
    async def on_raw_reaction_remove(self, payload: discord.RawReactionActionEvent):
        if payload.guild_id is None:
            return
        if not await self._is_sob_emoji(payload.guild_id, payload.emoji):
            return
        await self.sob_repo.remove_sob(
            guild_id=payload.guild_id,
            message_id=payload.message_id,
            reactor_id=payload.user_id,
        )

    # ----- commands ------------------------------------------------------

    @commands.group(name="sob", invoke_without_command=True)
    @commands.guild_only()
    async def sob_group(self, ctx: commands.Context, *, target: str | None = None):
        guild, now = ctx.guild, int(time.time())

        # Resolve an optional @user / name without swallowing subcommands.
        user = ctx.author
        if target:
            target = target.strip()
            member = None
            if ctx.message.mentions:
                member = ctx.message.mentions[0]
            else:
                member = guild.get_member_named(target)
                if member is None:
                    try:
                        member = await commands.MemberConverter().convert(ctx, target)
                    except commands.BadArgument:
                        member = None
            if member is not None:
                user = member

        threshold = await self.sob_repo.get_snitch_threshold(guild.id)
        stats = await self.sob_repo.get_user_stats(guild.id, user.id)
        rank_today = await self.sob_repo.get_user_daily_rank(guild.id, user.id)
        rank_week = await self.sob_repo.get_user_weekly_rank(guild.id, user.id)
        rank_alltime = await self.sob_repo.get_user_alltime_rank(guild.id, user.id)
        snitch_row = await self.sob_repo.get_snitch_row(guild.id, user.id)

        # Try the new profile card first (with owner kill-switch). If it's
        # disabled or fails for any reason, fall back to the classic embed.
        if self.profile is not None and await self.profile.profile_enabled(guild.id):
            card = await self.profile.build_profile_card(guild, user)
            if card is not None:
                await ctx.reply(file=card)
                return

        await ctx.reply(embed=embeds.personal_embed(
            user=user, stats=stats,
            rank_today=rank_today, rank_week=rank_week, rank_alltime=rank_alltime,
            snitch_row=snitch_row, snitch_threshold=threshold, now_ts=now,
        ))

    @sob_group.command(name="set")
    @commands.guild_only()
    async def sob_set(self, ctx: commands.Context, what: str | None = None, *, value: str | None = None):
        """Change your profile: !sob set background <name> | !sob set color <name>"""
        from core.profile.cog import FREE_BACKGROUNDS, FREE_COLORS
        from core.sob import embeds as e
        if self.profile is None:
            await ctx.reply("Profiles aren't available right now.")
            return

        gid, uid = ctx.guild.id, ctx.author.id
        what = (what or "").lower().strip()

        if what in ("bg", "background", "wallpaper"):
            if not value:
                cur = await self.profile.get_user_background(gid, uid)
                await ctx.reply(embed=e.profile_options_embed(
                    "🖼️ Backgrounds", sorted(FREE_BACKGROUNDS), cur,
                    f"{ctx.prefix}sob set background <name>"))
                return
            ok, res = await self.profile.set_user_background(gid, uid, value)
            if ok:
                await ctx.reply(f"✅ Background set to **{res}**. Run `{ctx.prefix}sob` to see it.")
            else:
                await ctx.reply(f"⚠️ You can't use `{value}`. Free options: {', '.join(sorted(FREE_BACKGROUNDS))}.")

        elif what in ("color", "colour", "theme"):
            if not value:
                cur = await self.profile.get_user_color(gid, uid)
                await ctx.reply(embed=e.profile_options_embed(
                    "🎨 Colors", sorted(FREE_COLORS), cur,
                    f"{ctx.prefix}sob set color <name>"))
                return
            ok, res = await self.profile.set_user_color(gid, uid, value)
            if ok:
                await ctx.reply(f"✅ Color set to **{res}**. Run `{ctx.prefix}sob` to see it.")
            else:
                await ctx.reply(f"⚠️ `{value}` isn't available. Options: {', '.join(sorted(FREE_COLORS))}.")

        else:
            cur_bg = await self.profile.get_user_background(gid, uid)
            cur_color = await self.profile.get_user_color(gid, uid)
            emb = discord.Embed(title="🎴 Customize your profile", color=embeds.COLOR)
            emb.add_field(name="Background",
                          value=f"Now: **{cur_bg}**\n`{ctx.prefix}sob set background <name>`", inline=True)
            emb.add_field(name="Color",
                          value=f"Now: **{cur_color}**\n`{ctx.prefix}sob set color <name>`", inline=True)
            emb.set_footer(text="Run a command above to see all the options.")
            await ctx.reply(embed=emb)

    @sob_group.command(name="lb", aliases=["leaderboard"])
    @commands.guild_only()
    async def sob_lb(self, ctx: commands.Context):
        guild = ctx.guild

        # Try the leaderboard card first (with kill-switch), fall back to embed.
        if self.profile is not None and await self.profile.profile_enabled(guild.id):
            card = await self.profile.build_leaderboard_card(guild, self.sob_repo)
            if card is not None:
                await ctx.reply(file=card)
                return

        await ctx.reply(embed=embeds.leaderboard_embed(
            guild=guild,
            daily_leader=await self.sob_repo.get_daily_leader(guild.id),
            weekly_leader=await self.sob_repo.get_weekly_leader(guild.id),
            alltime_leader=await self.sob_repo.get_alltime_leader(guild.id),
            top_giver=await self.sob_repo.get_top_giver(guild.id),
            top_snitch=await self.sob_repo.get_top_snitch(guild.id),
        ))

    @sob_group.command(name="backgrounds", aliases=["bgs", "wallpapers"])
    @commands.guild_only()
    async def sob_backgrounds(self, ctx: commands.Context):
        from core.profile.cog import FREE_BACKGROUNDS, _all_wallpapers
        if self.profile is None:
            await ctx.reply("Profiles aren't available right now.")
            return
        cur = await self.profile.get_user_background(ctx.guild.id, ctx.author.id)
        free = sorted(FREE_BACKGROUNDS)
        locked = sorted(_all_wallpapers() - FREE_BACKGROUNDS)
        e = discord.Embed(title="🖼️ Backgrounds", color=embeds.COLOR)
        e.add_field(
            name="Free (everyone)",
            value="\n".join(f"• **{b}**" + (" ✅" if b == cur else "") for b in free) or "—",
            inline=False,
        )
        if locked:
            e.add_field(
                name="🔒 Premium (owner only for now)",
                value="\n".join(f"• {b}" for b in locked),
                inline=False,
            )
        e.set_footer(text=f"Set one with {ctx.prefix}sob set background <name>")
        await ctx.reply(embed=e)

    @sob_group.command(name="colors", aliases=["colours"])
    @commands.guild_only()
    async def sob_colors(self, ctx: commands.Context):
        from core.profile.cog import FREE_COLORS
        if self.profile is None:
            await ctx.reply("Profiles aren't available right now.")
            return
        cur = await self.profile.get_user_color(ctx.guild.id, ctx.author.id)
        e = discord.Embed(title="🎨 Colors", color=embeds.COLOR)
        e.description = "\n".join(f"• **{c}**" + (" ✅" if c == cur else "") for c in sorted(FREE_COLORS))
        e.set_footer(text=f"Set one with {ctx.prefix}sob set color <name>")
        await ctx.reply(embed=e)

    @sob_group.command(name="help")
    @commands.guild_only()
    async def sob_help(self, ctx: commands.Context):
        # Mirror the main help's sob page so there's one source of truth.
        help_cog = self.bot.get_cog("HelpCog")
        if help_cog is not None and hasattr(help_cog, "_sobs_help"):
            await ctx.reply(embed=help_cog._sobs_help(ctx.prefix))
        else:
            prefix = ctx.prefix
            await ctx.reply(embed=embeds.snitch_help_embed(prefix))

    @commands.command(name="ss", aliases=["sobsnitch"])
    @commands.guild_only()
    async def sob_snitch(self, ctx: commands.Context):
        guild, user, now = ctx.guild, ctx.author, int(time.time())

        ref = ctx.message.reference
        if ref is None:
            await ctx.reply(f"{embeds.ANTI} You need to **reply** to a message to snitch it.", mention_author=False)
            return

        target_msg = ref.resolved
        if not isinstance(target_msg, discord.Message):
            target_msg = await self._resolve_message(ctx.channel, ref.message_id)

        if target_msg is None:
            await ctx.reply(f"{embeds.ANTI} Couldn't find that message.", mention_author=False)
            return
        if target_msg.author.bot:
            await ctx.reply(f"{embeds.ANTI} You can't snitch a bot's message.", mention_author=False)
            return
        if target_msg.author.id == user.id:
            await ctx.reply(f"{embeds.ANTI} You can't snitch your own message.", mention_author=False)
            return

        # Shop effects: freeze stops the snitcher; shield protects the target.
        if self.shop_repo is not None:
            if await self.shop_repo.has_effect(guild.id, user.id, "freeze"):
                await ctx.reply("❄️ You're **frozen** — you can't snitch right now.", mention_author=False)
                return

            if await self.shop_repo.has_effect(guild.id, target_msg.author.id, "shield"):
                # target is shielded: block the snitch AND consume the snitcher's token
                snitch_row = await self.sob_repo.get_snitch_row(guild.id, user.id)
                if snitch_row and snitch_row["token_available"] == 1:
                    db = await self.sob_repo._db()
                    await db.execute(
                        "UPDATE sob_users SET token_available = 0, updated_at = ? WHERE guild_id = ? AND user_id = ?",
                        (now, guild.id, user.id),
                    )
                    await db.commit()
                    await self.shop_repo.consume_effect(guild.id, target_msg.author.id, "shield")
                    await ctx.reply(
                        f"🛡️ {target_msg.author.mention} was **shielded** — your snitch was blocked and your token is gone.",
                        mention_author=False,
                    )
                else:
                    await ctx.reply(f"{embeds.ANTI} You don't have a snitch token.", mention_author=False)
                return

        success, reason, removed = await self.sob_repo.snitch_message(
            guild_id=guild.id,
            message_id=target_msg.id,
            snitcher_id=user.id,
            target_id=target_msg.author.id,
            now=now,
        )

        if success:
            threshold = await self.sob_repo.get_snitch_threshold(guild.id)

            # Boost family: if the snitcher has any boost-type effect active,
            # steal (removed × that item's multiplier), capped by target balance.
            boosted_amount = 0
            if self.shop_repo is not None:
                from core.shop.catalog import BUILTIN_ITEMS
                active_mult = None
                for ik, it in BUILTIN_ITEMS.items():
                    if it.get("mechanic", "").startswith("steal_mult"):
                        eff = it.get("effect_key") or ik
                        if await self.shop_repo.has_effect(guild.id, user.id, eff):
                            m = float(it.get("multiplier", 1.5))
                            active_mult = max(active_mult or 0, m)
                if active_mult is not None:
                    boosted_amount = await self.shop_repo.apply_boost_steal(
                        guild.id, user.id, target_msg.author.id, removed, multiplier=active_mult,
                    )

            snitch_row = await self.sob_repo.get_snitch_row(guild.id, user.id)
            stats = await self.sob_repo.get_user_stats(guild.id, user.id)
            sobs_at_last = snitch_row["sobs_at_last_grant"] if snitch_row else 0
            left = embeds.sobs_until_next(stats["sobs_alltime"], threshold, sobs_at_last)

            embed = embeds.snitch_success_embed(
                snitcher=user, target=target_msg.author,
                sobs_removed=removed, sobs_left_until_next=left, threshold=threshold,
            )
            if boosted_amount > 0:
                embed.add_field(
                    name="⚡ Boost",
                    value=f"You stole **{boosted_amount}** sobs from {target_msg.author.mention}!",
                    inline=False,
                )
            await ctx.reply(embed=embed, mention_author=False)
        else:
            threshold = await self.sob_repo.get_snitch_threshold(guild.id)
            messages = {
                "no_token": f"{embeds.ANTI} You don't have a snitch token. Receive **{threshold}** sobs to earn one.",
                "expired": f"{embeds.ANTI} Your snitch token expired (unused for 7 days). Earn a new one.",
                "no_sobs": f"{embeds.ANTI} That message has no sob reactions to remove.",
                "own_message": f"{embeds.ANTI} You can't snitch your own message.",
            }
            await ctx.reply(messages.get(reason, f"{embeds.ANTI} Something went wrong."), mention_author=False)