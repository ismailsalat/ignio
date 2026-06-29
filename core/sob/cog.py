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

    async def _consume_token(self, guild_id: int, user_id: int, now: int) -> None:
        """Atomically clear a user's snitch token (used when a snitch is blocked)."""
        db = await self.sob_repo._db()
        async with db.key_lock("snitch", guild_id, user_id):
            async with db.transaction() as conn:
                await conn.execute(
                    "UPDATE sob_users SET token_available = 0, updated_at = ? WHERE guild_id = ? AND user_id = ?",
                    (now, guild_id, user_id),
                )

    # ----- reaction listeners -------------------------------------------

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        # Track real message activity (for alt/farm detection). Bots & DMs ignored.
        if message.guild is None or message.author.bot:
            return
        try:
            db = await self.sob_repo._db()
            import time as _t
            now = int(_t.time())
            await db.execute(
                "INSERT INTO user_activity (guild_id, user_id, last_msg_at, msg_count) "
                "VALUES (?,?,?,1) ON CONFLICT(guild_id, user_id) DO UPDATE SET "
                "last_msg_at=excluded.last_msg_at, msg_count=msg_count+1",
                (message.guild.id, message.author.id, now),
            )
            await db.commit()
        except Exception:
            pass

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

        gid = payload.guild_id

        # Economy frozen by admin (exploit response): nothing is credited.
        if self.economy is not None:
            try:
                if await self.economy.is_frozen(gid):
                    await self.sob_repo.log_security(
                        gid, "blocked_reaction", actor_id=payload.user_id,
                        target_id=target_id, message_id=payload.message_id,
                        reason="economy_frozen")
                    return
            except Exception:
                pass

        # Alt-block: if enabled, suspicious reactors don't give sobs.
        if self.economy is not None:
            blocked_reason = await self._altblock_reason(guild, gid, payload.user_id, target_id)
            if blocked_reason is not None:
                await self.sob_repo.log_security(
                    gid, "blocked_reaction", actor_id=payload.user_id,
                    target_id=target_id, message_id=payload.message_id,
                    reason=blocked_reason)
                return

        # Compute the FINAL credited value ONCE (so removal/snitch refund it
        # exactly, even if the multiplier changes later). Store the multiplier
        # reference on the event.
        credited = 1
        mult_ref = ""
        if self.economy is not None:
            try:
                value = await self.economy.sob_value(gid)
                mult = await self.economy.get_sob_multiplier(gid)
                # slow curse on the TARGET halves their earnings; lucky day boosts.
                if self.shop_repo is not None:
                    if await self.shop_repo.has_effect(gid, target_id, "slow"):
                        mult *= 0.5
                    if await self.shop_repo.has_effect(gid, target_id, "lucky"):
                        mult *= 1.5
                credited = max(1, int(round(value * mult)))
                mult_ref = f"{value}x{mult:.3f}"
            except Exception:
                credited = 1

        threshold = await self.sob_repo.get_snitch_threshold(gid)
        try:
            await self.sob_repo.add_sob(
                guild_id=gid,
                message_id=payload.message_id,
                reactor_id=payload.user_id,
                target_id=target_id,
                snitch_threshold=threshold,
                credited_amount=credited,
                multiplier_ref=mult_ref,
            )
        except Exception as e:
            print(f"[Ignio][Sob] add_sob failed: {e}")

    async def _altblock_reason(self, guild, gid: int, reactor_id: int, target_id: int) -> str | None:
        """Return a reason string if this reaction should be blocked by the
        anti-alt protection, or None if it's allowed. Configurable per guild."""
        try:
            if (await self.sob_repo.get_guild_setting(gid, "economy:altblock")) != "1":
                return None
        except Exception:
            return None

        import time as _t
        from core.economy import score_member_suspicion
        now = int(_t.time())

        async def _setting_int(key, default):
            raw = await self.sob_repo.get_guild_setting(gid, key)
            try:
                return int(raw)
            except (TypeError, ValueError):
                return default

        # account age / join age / inactivity (via score_member_suspicion)
        reactor = guild.get_member(reactor_id)
        if reactor is not None:
            la = await (await self.sob_repo._db()).fetchone(
                "SELECT last_msg_at FROM user_activity WHERE guild_id=? AND user_id=?",
                (gid, reactor_id))
            last_msg = int(la["last_msg_at"]) if la else 0
            score = score_member_suspicion(reactor, last_msg)
            if score["suspicious"]:
                return "suspicious_account:" + ",".join(score["reasons"])

        # configurable reaction-rate limit per reactor (default 60/min)
        per_min_cap = await _setting_int("economy:altblock_rate_per_min", 60)
        if per_min_cap > 0:
            recent = await self.sob_repo.recent_reaction_count(gid, reactor_id, now - 60)
            if recent >= per_min_cap:
                return f"rate_limited:{recent}/min"

        # per-target cap: how many reactions this reactor gave THIS target recently
        pair_cap = await _setting_int("economy:altblock_pair_per_hour", 30)
        if pair_cap > 0:
            db = await self.sob_repo._db()
            row = await db.fetchone(
                "SELECT COUNT(*) AS n FROM sob_events WHERE guild_id=? AND reactor_id=? AND target_id=? AND created_at>=?",
                (gid, reactor_id, target_id, now - 3600))
            if row and int(row["n"]) >= pair_cap:
                return f"pair_flood:{int(row['n'])}/hr"

        # reciprocal farming: target has reacted back to reactor a lot recently
        recip_cap = await _setting_int("economy:altblock_reciprocal", 20)
        if recip_cap > 0:
            recip = await self.sob_repo.reciprocal_count(gid, reactor_id, target_id, now - 3600)
            if recip >= recip_cap:
                return f"reciprocal_farm:{recip}/hr"

        return None

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

        # Safety net: if the first word is actually a subcommand (stats, lb, set,
        # ...), don't treat it as a @user for the profile card. discord.py
        # normally routes these to the subcommand, but if anything quirky leaves
        # us here, dispatch to the right subcommand instead of showing !sob.
        if target:
            first = target.strip().split()[0].lower()
            sub = self.sob_group.get_command(first)
            if sub is not None:
                rest = target.strip()[len(first):].strip() or None
                # call the subcommand callback directly with the remaining args
                if sub.name == "stats":
                    return await self.sob_stats(ctx, target=rest)
                if sub.name == "lb":
                    return await self.sob_lb(ctx)
                if sub.name == "set":
                    return await ctx.invoke(self.sob_set)
                if sub.name == "tips":
                    return await self.sob_tips(ctx)
                if sub.name == "backgrounds":
                    return await self.sob_backgrounds(ctx)
                if sub.name == "colors":
                    return await self.sob_colors(ctx)
                if sub.name == "help":
                    return await self.sob_help(ctx)

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

    @sob_group.command(name="stats", aliases=["mystats", "income"])
    @commands.guild_only()
    async def sob_stats(self, ctx: commands.Context, *, target: str | None = None):
        """Picture breakdown of where your sobs come from + your audit allowance."""
        guild = ctx.guild
        user = ctx.author
        if target:
            if ctx.message.mentions:
                user = ctx.message.mentions[0]
            else:
                m = guild.get_member_named(target.strip())
                if m:
                    user = m

        gid, uid = guild.id, user.id
        try:
            from core import ledger
            from core.profile.small_cards import stats_card
            import io

            db = await self.sob_repo._db()
            stats = await self.sob_repo.get_user_stats(gid, uid)
            balance = int(stats["sobs_alltime"])
            bd = await ledger.stats_breakdown(db, gid, uid)

            rates = {"sob_value": 1, "snitch_steal_pct": 50,
                     "audit_basic_pct": 0.03, "audit_heist_pct": 0.08, "audit_cap": 8}
            cds = {"audit_left": 0, "audits_left": 8}
            if self.economy is not None:
                from core.economy import (SNITCH_STEAL_PCT, AUDIT_BASIC_PCT,
                                          AUDIT_HEIST_PCT)
                try:
                    rates["sob_value"] = await self.economy.sob_value(gid)
                except Exception:
                    pass
                rates["snitch_steal_pct"] = int(SNITCH_STEAL_PCT * 100)
                rates["audit_basic_pct"] = AUDIT_BASIC_PCT
                rates["audit_heist_pct"] = AUDIT_HEIST_PCT
                cap = await self.economy.audit_daily_cap(gid)
                done = await self.economy.audits_done_today(gid, uid)
                rates["audit_cap"] = cap
                cds["audits_left"] = max(0, cap - done)
                cds["audit_left"] = await self.economy.audit_cooldown_left(gid, uid)

            # Protection risk: only show when the player has enough at stake for
            # the loss to matter, OR they've been audited recently. Keeps the
            # card simple for tiny/new players.
            protection = None
            prot = getattr(self.shop_repo, "protection", None) if self.shop_repo else None
            if prot is not None:
                try:
                    ro = await prot.risk_readout(gid, uid)
                    matters = ro["basic"] >= 25 or ro["lost_today"] > 0
                    ro["show"] = bool(matters)
                    protection = ro
                    # keep the 24h high-water mark fresh while we're here
                    await prot.note_balance(gid, uid, balance)
                except Exception as e:
                    print(f"[Ignio][Sob] protection readout failed: {e}")

            name = getattr(user, "display_name", "You")
            img = stats_card(name, balance, bd["earned"], bd["spent"], rates, cds,
                             protection=protection)
            buf = io.BytesIO(); img.save(buf, format="PNG"); buf.seek(0)
            await ctx.reply(file=discord.File(buf, filename="stats.png"))
            return
        except Exception as e:
            print(f"[Ignio][Sob] stats card failed: {e}")
            await ctx.reply(embed=embeds.error_embed("Couldn't build your stats right now."))

    @sob_group.command(name="tips", aliases=["tip"])
    @commands.guild_only()
    async def sob_tips(self, ctx: commands.Context, state: str | None = None):
        """Turn the occasional shield reminder on or off, just for you."""
        gid, uid = ctx.guild.id, ctx.author.id
        key = f"shieldtip:off:{uid}"
        if state is None:
            off = (await self.sob_repo.get_guild_setting(gid, key)) == "1"
            await ctx.reply(
                f"Shield tips are **{'OFF' if off else 'ON'}** for you. "
                f"Use `{ctx.prefix}sob tips on` or `{ctx.prefix}sob tips off`.")
            return
        on = state.lower() in ("on", "yes", "enable", "enabled", "1", "true")
        await self.sob_repo.set_guild_setting(gid, key, "0" if on else "1")
        if on:
            await ctx.reply("✅ Shield tips are back on. I'll only mention them once in a while.")
        else:
            await ctx.reply("✅ Shield tips are off for you. Re-enable any time with `!sob tips on`.")

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

        # Shop effects gate. Order matters:
        #  - freeze stops the snitcher entirely
        #  - king's decree on the snitcher pierces shields (except reflect)
        #  - reflect on the target bounces the snitch back at the snitcher
        #  - guardian (charge-based) and shield (time-based) block & consume token
        king_pierce = False
        if self.shop_repo is not None:
            if await self.shop_repo.has_effect(guild.id, user.id, "freeze"):
                await ctx.reply("❄️ You're **frozen** — you can't snitch right now.", mention_author=False)
                return

            king_pierce = await self.shop_repo.has_effect(guild.id, user.id, "king")

            # Reflect always beats everything (even King's Decree): bounce it back.
            if await self.shop_repo.has_effect(guild.id, target_msg.author.id, "reflect"):
                snitch_row = await self.sob_repo.get_snitch_row(guild.id, user.id)
                if not (snitch_row and snitch_row["token_available"] == 1):
                    await ctx.reply(f"{embeds.ANTI} You don't have a snitch token.", mention_author=False)
                    return
                await self.shop_repo.consume_charge(guild.id, target_msg.author.id, "reflect")
                # consume the snitcher's token (the reflected attempt uses it up)
                await self._consume_token(guild.id, user.id, now)
                await self.sob_repo.log_security(
                    guild.id, "shield_block", actor_id=user.id,
                    target_id=target_msg.author.id, message_id=target_msg.id,
                    reason="reflect")
                await ctx.reply(
                    f"🪞 {target_msg.author.mention} had a **Reflect Shield** — your snitch bounced back and your token is gone.",
                    mention_author=False)
                return

            if not king_pierce:
                # Guardian Angel: charge-based block.
                if await self.shop_repo.has_effect(guild.id, target_msg.author.id, "guardian"):
                    snitch_row = await self.sob_repo.get_snitch_row(guild.id, user.id)
                    if snitch_row and snitch_row["token_available"] == 1:
                        await self.shop_repo.consume_charge(guild.id, target_msg.author.id, "guardian")
                        await self._consume_token(guild.id, user.id, now)
                        left = await self.shop_repo.charges_left(guild.id, target_msg.author.id, "guardian")
                        await self.sob_repo.log_security(
                            guild.id, "shield_block", actor_id=user.id,
                            target_id=target_msg.author.id, message_id=target_msg.id,
                            reason="guardian", metadata={"charges_left": left})
                        await ctx.reply(
                            f"😇 {target_msg.author.mention} is guarded — snitch blocked, your token is gone. "
                            f"(Guardian charges left: {left})",
                            mention_author=False)
                    else:
                        await ctx.reply(f"{embeds.ANTI} You don't have a snitch token.", mention_author=False)
                    return

                # Time-based Shield.
                if await self.shop_repo.has_effect(guild.id, target_msg.author.id, "shield"):
                    snitch_row = await self.sob_repo.get_snitch_row(guild.id, user.id)
                    if snitch_row and snitch_row["token_available"] == 1:
                        await self._consume_token(guild.id, user.id, now)
                        await self.sob_repo.log_security(
                            guild.id, "shield_block", actor_id=user.id,
                            target_id=target_msg.author.id, message_id=target_msg.id,
                            reason="shield")
                        await ctx.reply(
                            f"🛡️ {target_msg.author.mention} is **shielded** — your snitch was blocked and your token is gone.",
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
            target_uid = target_msg.author.id

            # --- Snitch reward + steal + tax (the competitive engine) ---
            reward = 0
            stolen = 0
            snitch_tax = 0
            if self.economy is not None:
                try:
                    from core import ledger as _ledger
                    from core.economy import SNITCH_STEAL_PCT, SNITCH_TAX_PCT
                    tx = _ledger.new_tx_id()
                    reward = await self.economy.snitch_reward(guild.id)

                    # Highest applicable steal multiplier from active buffs.
                    # Charge-based buffs (hunter) are consumed; king pierces.
                    boost_mult = 1.0
                    consumed_charge_item = None
                    if self.shop_repo is not None:
                        from core.shop.catalog import BUILTIN_ITEMS
                        for ik, it in BUILTIN_ITEMS.items():
                            mech = it.get("mechanic", "")
                            if not mech.startswith("steal_mult"):
                                continue
                            eff = it.get("effect_key") or ik
                            if await self.shop_repo.has_effect(guild.id, user.id, eff):
                                m = float(it.get("multiplier", 1.5))
                                if m > boost_mult:
                                    boost_mult = m
                                    if "charges" in mech:
                                        consumed_charge_item = (eff, ik)
                        # marked bounty on the target adds a bonus to the steal
                        if await self.shop_repo.has_effect(guild.id, target_uid, "marked"):
                            bounty = float(BUILTIN_ITEMS.get("marked", {}).get("bounty_pct", 0.20))
                            boost_mult *= (1.0 + bounty)

                    # consume one hunter charge if it was the buff used
                    if consumed_charge_item is not None:
                        eff, _ik = consumed_charge_item
                        ok_c, left_c = await self.shop_repo.consume_charge(guild.id, user.id, eff)

                    # steal 50% of wiped (×boost), capped at target's balance —
                    # conserved, ledgered transfer (no minting).
                    stolen = await self.sob_repo.transfer(
                        guild.id, target_uid, user.id,
                        int(removed * SNITCH_STEAL_PCT * boost_mult),
                        event_type=_ledger.EVT_SNITCH_STEAL, actor_id=user.id,
                        transaction_id=tx, cap_to_balance=True,
                        message_id=target_msg.id,
                        metadata={"boost_mult": boost_mult, "wiped": removed},
                    )

                    # base reward is minted to the snitcher, then taxed.
                    gross = reward + stolen
                    snitch_tax = int(gross * SNITCH_TAX_PCT / 100)
                    # credit the base reward (mint) + ledger
                    if reward > 0:
                        await self.sob_repo.adjust_received(
                            guild.id, user.id, reward,
                            event_type=_ledger.EVT_SNITCH_REWARD, actor_id=user.id,
                            counterparty_id=target_uid, transaction_id=tx,
                            message_id=target_msg.id)
                    # remove the tax from the snitcher and route to treasury
                    if snitch_tax > 0:
                        ok_t, _bal = await self.sob_repo.spend(
                            guild.id, user.id, snitch_tax,
                            event_type=_ledger.EVT_SNITCH_TAX, actor_id=user.id,
                            transaction_id=tx, treasury_amount=snitch_tax,
                            metadata={"of": gross})
                        if ok_t:
                            await self.economy.add_treasury(guild.id, snitch_tax, payer_id=user.id)
                        else:
                            snitch_tax = 0
                except Exception as e:
                    print(f"[Ignio][Snitch] reward/steal failed: {e}")

            snitch_row = await self.sob_repo.get_snitch_row(guild.id, user.id)
            stats = await self.sob_repo.get_user_stats(guild.id, user.id)
            sobs_at_last = snitch_row["sobs_at_last_grant"] if snitch_row else 0
            left = embeds.sobs_until_next(stats["sobs_alltime"], threshold, sobs_at_last)

            embed = embeds.snitch_success_embed(
                snitcher=user, target=target_msg.author,
                sobs_removed=removed, sobs_left_until_next=left, threshold=threshold,
            )
            gained = reward + stolen - snitch_tax
            if gained > 0:
                parts = [f"+{reward} reward"]
                if stolen > 0:
                    parts.append(f"+{stolen} stolen")
                if snitch_tax > 0:
                    parts.append(f"−{snitch_tax} tax")
                embed.add_field(
                    name="😈 Snitch payout",
                    value=f"**+{gained} sobs** ({', '.join(parts)})",
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