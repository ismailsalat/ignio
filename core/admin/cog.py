# core/admin/cog.py
from __future__ import annotations

import io
import json

import discord
from discord.ext import commands

from core import transfer

ACCENT = 0xF0B132  # ignio amber, matches sob embeds


def _embed(title: str, desc: str | None = None) -> discord.Embed:
    e = discord.Embed(title=title, color=ACCENT)
    if desc:
        e.description = desc
    return e


def _ok(title: str, desc: str | None = None) -> discord.Embed:
    return _embed(f"✅ {title}", desc)


def _err(desc: str) -> discord.Embed:
    return _embed("⚠️ Error", desc)


class AdminCog(commands.Cog):
    """Owner-only maintenance: server config, data ops, export/import."""

    def __init__(self, bot: commands.Bot, settings, db_manager, sob_repo, profile_service=None, shop_repo=None):
        self.bot = bot
        self.settings = settings
        self.db_manager = db_manager
        self.repo = sob_repo
        self.profile = profile_service
        self.shop_repo = shop_repo

    async def _require(self, ctx, perm: str) -> bool:
        """Permission gate: admins/owner always pass; others need the role perm.
        Replies with an error and returns False if not allowed."""
        from core import perms as _perms
        if await _perms.member_has_perm(self.repo, ctx.author, self.settings, perm):
            return True
        await ctx.reply(embed=_err(f"You need the `{perm}` permission to use this."))
        return False

    async def _require_owner(self, ctx) -> bool:
        """Strict gate for sensitive data ops (export/import/stats/servers)."""
        owner_ids = set(getattr(self.settings, "owner_ids", ()) or ())
        if ctx.author.id in owner_ids or await self.bot.is_owner(ctx.author):
            return True
        await ctx.reply(embed=_err("This command is owner-only."))
        return False

    def _prefix(self) -> str:
        p = self.bot.command_prefix
        return p if isinstance(p, str) else "!"

    # ======================================================================
    # hub
    # ======================================================================

    @commands.group(name="admin", invoke_without_command=True)
    async def admin_group(self, ctx: commands.Context):
        p = self._prefix()
        e = _embed("🛡️ Ignio Admin", "Owner-only controls. Everything below replies with an embed.")
        e.add_field(
            name="📊 Info",
            value=(
                f"`{p}admin stats` — database overview\n"
                f"`{p}admin config` — this server's settings\n"
                f"`{p}admin servers` — servers with data"
            ),
            inline=False,
        )
        e.add_field(
            name="🛠️ Data",
            value=(
                f"`{p}admin givesob @user <n>` *(gs)* — add/remove sobs\n"
                f"`{p}admin givetoken @user [n]` *(gt)* — grant a snitch token\n"
                f"`{p}admin reset @user` — wipe a user's sobs here\n"
                f"`{p}admin recount` — rebuild totals from raw reactions"
            ),
            inline=False,
        )
        e.add_field(
            name="⚙️ Settings",
            value=(
                f"`{p}admin threshold [n]` — view/set snitch threshold\n"
                f"`{p}admin emoji list` — show accepted sob emojis\n"
                f"`{p}admin emoji add <name>` — accept an emoji\n"
                f"`{p}admin emoji remove <name>` — stop accepting one"
            ),
            inline=False,
        )
        e.add_field(
            name="📦 Transfer",
            value=(
                f"`{p}admin export [guild_id]` — export a server to a file\n"
                f"`{p}admin import merge|replace [guild_id]` — import attached file"
            ),
            inline=False,
        )
        await ctx.reply(embed=e)

    @admin_group.command(name="whoami")
    async def admin_whoami(self, ctx: commands.Context):
        is_app_owner = await self.bot.is_owner(ctx.author)
        in_list = ctx.author.id in set(getattr(self.settings, "owner_ids", ()) or ())
        e = _embed("🪪 Who am I", ctx.author.mention)
        e.add_field(name="User ID", value=f"`{ctx.author.id}`", inline=True)
        e.add_field(name="App owner", value="Yes" if is_app_owner else "No", inline=True)
        e.add_field(name="In OWNER_IDS", value="Yes" if in_list else "No", inline=True)
        await ctx.reply(embed=e)

    @admin_group.command(name="profile")
    async def admin_profile(self, ctx: commands.Context, state: str | None = None):
        """Owner kill-switch for the image profile card.
        !admin profile off  -> everyone gets the classic embed
        !admin profile on   -> re-enable the card"""
        if not await self._require_owner(ctx):
            return
        if self.profile is None:
            await ctx.reply(embed=_err("Profile system isn't loaded."))
            return
        if state is None:
            on = await self.profile.profile_enabled(ctx.guild.id)
            await ctx.reply(embed=_embed("🖼️ Profile card",
                f"Currently **{'ON' if on else 'OFF'}**.\nUse `{ctx.prefix}admin profile on|off`."))
            return
        state = state.lower().strip()
        if state in ("on", "enable", "enabled", "1"):
            await self.profile.set_profile_enabled(ctx.guild.id, True)
            await ctx.reply(embed=_embed("🖼️ Profile card", "Profile cards are now **ON**."))
        elif state in ("off", "disable", "disabled", "0"):
            await self.profile.set_profile_enabled(ctx.guild.id, False)
            await ctx.reply(embed=_embed("🖼️ Profile card", "Profile cards are **OFF** — `!sob` now shows the classic embed."))
        else:
            await ctx.reply(embed=_err("Use `on` or `off`."))

    # ======================================================================
    # info
    # ======================================================================

    @admin_group.command(name="stats")
    async def admin_stats(self, ctx: commands.Context):
        if not await self._require_owner(ctx):
            return
        db = await self.db_manager.get()
        async def c(sql):
            row = await db.fetchone(sql)
            return int(row[0]) if row and row[0] is not None else 0

        guilds = await c("SELECT COUNT(DISTINCT guild_id) FROM sob_users")
        users = await c("SELECT COUNT(*) FROM sob_users")
        received = await c("SELECT SUM(sobs_received_alltime) FROM sob_users")
        events = await c("SELECT COUNT(*) FROM sob_events")
        snitches = await c("SELECT SUM(total_snitches) FROM sob_users")
        tokens = await c("SELECT COUNT(*) FROM sob_users WHERE token_available = 1")

        e = _embed("🗄️ Ignio Database")
        e.add_field(name="Servers", value=f"`{guilds}`", inline=True)
        e.add_field(name="Users", value=f"`{users}`", inline=True)
        e.add_field(name="Total sobs", value=f"`{received}`", inline=True)
        e.add_field(name="Live reactions", value=f"`{events}`", inline=True)
        e.add_field(name="Total snitches", value=f"`{snitches}`", inline=True)
        e.add_field(name="Tokens out", value=f"`{tokens}`", inline=True)
        await ctx.reply(embed=e)

    @admin_group.command(name="config")
    async def admin_config(self, ctx: commands.Context):
        if ctx.guild is None:
            await ctx.reply(embed=_err("Run this in a server."))
            return
        gid = ctx.guild.id

        threshold = await self.repo.get_snitch_threshold(gid)
        emojis = sorted(await self.repo.get_accepted_emojis(gid))
        custom_emoji_set = await self.repo.get_guild_setting(gid, "sob_emojis")
        db = await self.db_manager.get()
        urow = await db.fetchone("SELECT COUNT(*) FROM sob_users WHERE guild_id = ?", (gid,))
        users_here = int(urow[0]) if urow and urow[0] is not None else 0

        emoji_display = ", ".join(f"`{x}`" for x in emojis) if emojis else "—"

        e = _embed("⚙️ Server Config", f"{ctx.guild.name}")
        e.add_field(name="Snitch threshold", value=f"`{threshold}` sobs / token", inline=True)
        e.add_field(name="Tracked users", value=f"`{users_here}`", inline=True)
        e.add_field(
            name="Emoji source",
            value="Custom (server)" if custom_emoji_set else "Default (global)",
            inline=True,
        )
        e.add_field(name="Accepted sob emojis", value=emoji_display, inline=False)
        e.set_footer(text=f"Change with {self._prefix()}admin threshold / emoji")
        await ctx.reply(embed=e)

    @admin_group.command(name="servers")
    async def admin_servers(self, ctx: commands.Context):
        if not await self._require_owner(ctx):
            return
        db = await self.db_manager.get()
        rows = await transfer.list_guilds(db)
        if not rows:
            await ctx.reply(embed=_embed("🌐 Servers", "No server data yet."))
            return
        lines = []
        for r in rows[:25]:
            g = self.bot.get_guild(r["guild_id"])
            name = g.name if g else "unknown"
            lines.append(f"`{r['guild_id']}` · **{name}** — {r['users']} users")
        e = _embed("🌐 Servers with data", "\n".join(lines))
        if len(rows) > 25:
            e.set_footer(text=f"Showing 25 of {len(rows)}")
        await ctx.reply(embed=e)

    # ======================================================================
    # data ops
    # ======================================================================

    @admin_group.command(name="givesob", aliases=["gs"])
    async def admin_givesob(self, ctx: commands.Context, member: discord.Member, amount: int):
        if ctx.guild is None:
            await ctx.reply(embed=_err("Run this in a server."))
            return
        if not await self._require(ctx, "givesob"): return
        if amount == 0:
            await ctx.reply(embed=_err("Amount can't be zero."))
            return
        from core import ledger as _ledger
        evt = _ledger.EVT_ADMIN_GIVE if amount > 0 else _ledger.EVT_ADMIN_REMOVE
        new_total = await self.repo.adjust_received(
            ctx.guild.id, member.id, amount,
            event_type=evt, actor_id=ctx.author.id, counterparty_id=ctx.author.id,
            metadata={"admin": ctx.author.id})
        verb = "Added" if amount > 0 else "Removed"
        e = _ok(f"{verb} {abs(amount)} sob{'s' if abs(amount) != 1 else ''}")
        e.add_field(name="User", value=member.mention, inline=True)
        e.add_field(name="New all-time", value=f"`{new_total}`", inline=True)
        await ctx.reply(embed=e)

    @admin_group.command(name="givetoken", aliases=["gt"])
    async def admin_givetoken(self, ctx: commands.Context, member: discord.Member, count: int = 1):
        if ctx.guild is None:
            await ctx.reply(embed=_err("Run this in a server."))
            return
        if not await self._require(ctx, "givetoken"): return
        await self.repo.grant_tokens(ctx.guild.id, member.id, max(1, count))
        e = _ok("Snitch token granted")
        e.add_field(name="User", value=member.mention, inline=True)
        e.add_field(name="Status", value="Token ready", inline=True)
        e.set_footer(text="Note: a user holds at most one active token at a time.")
        await ctx.reply(embed=e)

    @admin_group.command(name="reset")
    async def admin_reset(self, ctx: commands.Context, member: discord.Member):
        if ctx.guild is None:
            await ctx.reply(embed=_err("Run this in a server."))
            return
        if not await self._require(ctx, "manageconfig"): return
        await self.repo.reset_user(ctx.guild.id, member.id)
        e = _ok("User reset", f"All sob data wiped for {member.mention} in this server.")
        await ctx.reply(embed=e)

    @admin_group.command(name="recount")
    async def admin_recount(self, ctx: commands.Context):
        if ctx.guild is None:
            await ctx.reply(embed=_err("Run this in a server."))
            return
        if not await self._require(ctx, "manageconfig"): return
        summary = await self.repo.recount(ctx.guild.id)
        e = _ok("Recount complete", "Rebuilt all-time received totals from raw reactions.")
        e.add_field(name="Users recounted", value=f"`{summary['users_recounted']}`", inline=True)
        e.add_field(name="Reactions scanned", value=f"`{summary['events_scanned']}`", inline=True)
        await ctx.reply(embed=e)

    # ======================================================================
    # settings
    # ======================================================================

    @admin_group.command(name="threshold")
    async def admin_threshold(self, ctx: commands.Context, value: int | None = None):
        if ctx.guild is None:
            await ctx.reply(embed=_err("Run this in a server."))
            return
        if value is None:
            current = await self.repo.get_snitch_threshold(ctx.guild.id)
            e = _embed("⚙️ Snitch threshold", f"Currently `{current}` sobs per token.")
            e.set_footer(text=f"Set with {self._prefix()}admin threshold <number>")
            await ctx.reply(embed=e)
            return
        if value < 1:
            await ctx.reply(embed=_err("Threshold must be at least 1."))
            return
        if not await self._require(ctx, "manageconfig"):
            return
        new = await self.repo.set_snitch_threshold(ctx.guild.id, value)
        await ctx.reply(embed=_ok("Threshold updated", f"Now `{new}` sobs per snitch token."))

    @admin_group.group(name="emoji", invoke_without_command=True)
    async def admin_emoji(self, ctx: commands.Context):
        await self.admin_emoji_list(ctx)

    @admin_emoji.command(name="list")
    async def admin_emoji_list(self, ctx: commands.Context):
        if ctx.guild is None:
            await ctx.reply(embed=_err("Run this in a server."))
            return
        emojis = sorted(await self.repo.get_accepted_emojis(ctx.guild.id))
        custom = await self.repo.get_guild_setting(ctx.guild.id, "sob_emojis")
        display = ", ".join(f"`{x}`" for x in emojis) if emojis else "—"
        e = _embed("😭 Accepted sob emojis", display)
        e.set_footer(text=("Custom for this server" if custom else "Using global defaults"))
        await ctx.reply(embed=e)

    @admin_emoji.command(name="add")
    async def admin_emoji_add(self, ctx: commands.Context, *, name: str):
        if ctx.guild is None:
            await ctx.reply(embed=_err("Run this in a server."))
            return
        if not await self._require(ctx, "manageconfig"):
            return
        # accept either a raw emoji or a name; store the name if it's custom
        clean = name.strip()
        if clean.startswith("<") and clean.endswith(">"):
            # <:handsob:123> -> handsob
            parts = clean.strip("<>").split(":")
            if len(parts) >= 2:
                clean = parts[1]
        current = await self.repo.add_accepted_emoji(ctx.guild.id, clean)
        display = ", ".join(f"`{x}`" for x in sorted(current))
        await ctx.reply(embed=_ok("Emoji added", f"Now accepting: {display}"))

    @admin_emoji.command(name="remove")
    async def admin_emoji_remove(self, ctx: commands.Context, *, name: str):
        if ctx.guild is None:
            await ctx.reply(embed=_err("Run this in a server."))
            return
        if not await self._require(ctx, "manageconfig"):
            return
        clean = name.strip()
        if clean.startswith("<") and clean.endswith(">"):
            parts = clean.strip("<>").split(":")
            if len(parts) >= 2:
                clean = parts[1]
        current = await self.repo.remove_accepted_emoji(ctx.guild.id, clean)
        display = ", ".join(f"`{x}`" for x in sorted(current)) if current else "—"
        await ctx.reply(embed=_ok("Emoji removed", f"Now accepting: {display}"))

    # ======================================================================
    # transfer
    # ======================================================================

    @admin_group.command(name="altblock")
    async def admin_altblock(self, ctx: commands.Context, state: str = None):
        """Toggle whether suspicious (alt-like) reactions are blocked from giving sobs."""
        if not await self._require(ctx, "managesobs"):
            return
        gid = ctx.guild.id
        if state is None:
            cur = await self.repo.get_guild_setting(gid, "economy:altblock")
            on = cur == "1"
            await ctx.reply(embed=_embed(
                "Alt-block status",
                f"Suspicious reactions are currently **{'BLOCKED 🚫' if on else 'flagged only 🚩'}**.\n\n"
                f"`{ctx.prefix}admin altblock on` — don't give sobs for alt-like reactions\n"
                f"`{ctx.prefix}admin altblock off` — count them, just flag in `{ctx.prefix}admin audit`"))
            return
        on = state.lower() in ("on", "yes", "true", "1", "block")
        await self.repo.set_guild_setting(gid, "economy:altblock", "1" if on else "0")
        if on:
            await ctx.reply(embed=_embed(
                "🚫 Alt-block ON",
                "Reactions from new/inactive accounts (≤7d old, joined ≤24h, or no recent messages) "
                "no longer give sobs. Real members are unaffected."))
        else:
            await ctx.reply(embed=_embed(
                "🚩 Alt-block OFF",
                "Suspicious reactions count again, but are still flagged in `audit`."))

    @admin_group.command(name="freeze", aliases=["lockdown"])
    async def admin_freeze(self, ctx: commands.Context, state: str = None):
        """Emergency: freeze all sob earning/economy server-wide (exploit response)."""
        if not await self._require(ctx, "managesobs"):
            return
        gid = ctx.guild.id
        if state is None:
            cur = await self.repo.get_guild_setting(gid, "economy:frozen")
            is_frozen = cur == "1"
            await ctx.reply(embed=_embed(
                "Economy status",
                f"The economy is currently **{'FROZEN ❄️' if is_frozen else 'active ✅'}**.\n"
                f"Use `{ctx.prefix}admin freeze on` or `{ctx.prefix}admin freeze off`."))
            return
        on = state.lower() in ("on", "yes", "true", "1", "freeze")
        await self.repo.set_guild_setting(gid, "economy:frozen", "1" if on else "0")
        if on:
            await ctx.reply(embed=_embed(
                "❄️ Economy FROZEN",
                "All sob earning, snitching, audits, and games are paused server-wide.\n"
                f"Investigate with `{ctx.prefix}admin audit @user`, then `{ctx.prefix}admin freeze off` to resume."))
        else:
            await ctx.reply(embed=_embed("✅ Economy resumed", "Sob earning and games are active again."))

    @admin_group.command(name="tips", aliases=["shieldtips"])
    async def admin_tips(self, ctx: commands.Context, state: str = None):
        """Turn the occasional shield reminder on/off for the WHOLE server."""
        if not await self._require(ctx, "managesobs"):
            return
        gid = ctx.guild.id
        if state is None:
            off = (await self.repo.get_guild_setting(gid, "shieldtip:enabled")) == "0"
            await ctx.reply(embed=_embed(
                "Shield tips",
                f"Server-wide shield reminders are **{'OFF' if off else 'ON'}**.\n"
                f"They're quiet (no ping), only after a real hit, and at most once every 6h per person.\n"
                f"`{ctx.prefix}admin tips on|off`. (Each member can also use `{ctx.prefix}sob tips off`.)"))
            return
        on = state.lower() in ("on", "yes", "enable", "enabled", "1", "true")
        await self.repo.set_guild_setting(gid, "shieldtip:enabled", "1" if on else "0")
        await ctx.reply(embed=_embed(
            "✅ Shield tips " + ("on" if on else "off"),
            "Members may still get an occasional quiet reminder." if on
            else "Nobody will be shown shield reminders."))

    # ------------------------------------------------------------------
    # Economy / shop controls (disable items, categories, whole shop)
    # ------------------------------------------------------------------
    def _csv_set(self, raw):
        return {x.strip().lower() for x in (raw or "").split(",") if x.strip()}

    async def _save_csv(self, gid, key, items):
        await self.repo.set_guild_setting(gid, key, ",".join(sorted(items)))

    @admin_group.command(name="shop")
    async def admin_shop(self, ctx: commands.Context, state: str = None):
        """Turn the WHOLE shop on/off. `!admin shop off` hides every item from buying."""
        if not await self._require(ctx, "managesobs"):
            return
        gid = ctx.guild.id
        if state is None:
            off = (await self.repo.get_guild_setting(gid, "shop:enabled")) == "0"
            await ctx.reply(embed=_embed(
                "Shop status",
                f"The shop is currently **{'OFF 🔒' if off else 'ON ✅'}**.\n"
                f"`{ctx.prefix}admin shop off` to close · `{ctx.prefix}admin shop on` to open."))
            return
        on = state.lower() in ("on", "open", "yes", "1", "enable", "enabled")
        await self.repo.set_guild_setting(gid, "shop:enabled", "1" if on else "0")
        await ctx.reply(embed=_embed(
            "🛒 Shop " + ("opened ✅" if on else "closed 🔒"),
            "Players can buy again." if on else "Nobody can buy any item until you reopen it."))

    @admin_group.command(name="item", aliases=["disableitem"])
    async def admin_item(self, ctx: commands.Context, state: str = None, *, rest: str = None):
        """Disable/enable a shop item, or give/take items from someone's bag.
        `!admin item disable audit` · `!admin item enable audit` · `!admin item list`
        `!admin item give @user shield 3` · `!admin item take @user lockpick 1`"""
        if not await self._require(ctx, "managesobs"):
            return
        gid = ctx.guild.id

        # ---- give / take to a user's inventory ----
        if state and state.lower() in ("give", "grant", "add", "take", "remove"):
            taking = state.lower() in ("take", "remove")
            # parse: @user <item> [qty]   (mention may already be resolved in ctx)
            member = ctx.message.mentions[0] if ctx.message.mentions else None
            tokens = (rest or "").split()
            # drop the mention token
            tokens = [t for t in tokens if not t.startswith("<@")]
            if member is None or not tokens:
                await ctx.reply(embed=_err(
                    f"Usage: `{ctx.prefix}admin item {state} @user <item> [qty]`."))
                return
            key = tokens[0].strip().lower()
            qty = 1
            if len(tokens) > 1:
                try:
                    qty = max(1, int(tokens[1]))
                except ValueError:
                    qty = 1
            from core.shop.catalog import BUILTIN_ITEMS
            if key not in BUILTIN_ITEMS:
                await ctx.reply(embed=_err(
                    f"Unknown item `{key}`. Built-in keys: {', '.join(sorted(BUILTIN_ITEMS))}"))
                return
            try:
                if taking:
                    removed = await self.shop_repo.admin_take_item(gid, member.id, key, qty)
                    await ctx.reply(embed=_embed("✅ Item removed",
                        f"Took **{removed}× {BUILTIN_ITEMS[key]['name']}** from {member.mention}."))
                else:
                    await self.shop_repo.admin_give_item(gid, member.id, key, qty)
                    await ctx.reply(embed=_embed("✅ Item granted",
                        f"Gave **{qty}× {BUILTIN_ITEMS[key]['name']}** to {member.mention}."))
            except AttributeError:
                await ctx.reply(embed=_err("Inventory admin tools aren't wired — update the shop repo."))
            return

        # ---- disable / enable / list ----
        disabled = self._csv_set(await self.repo.get_guild_setting(gid, "shop:disabled_items"))
        if state in (None, "list"):
            txt = ", ".join(sorted(disabled)) if disabled else "none"
            await ctx.reply(embed=_embed(
                "Shop item controls",
                f"Disabled items: **{txt}**\n"
                f"`{ctx.prefix}admin item disable <key>` · `{ctx.prefix}admin item enable <key>`\n"
                f"`{ctx.prefix}admin item give @user <key> [qty]` · `{ctx.prefix}admin item take @user <key> [qty]`"))
            return
        item = rest
        if not item:
            await ctx.reply(embed=_err(f"Usage: `{ctx.prefix}admin item disable <item key>`."))
            return
        key = item.strip().lower()
        if state.lower() in ("disable", "off", "hide", "0"):
            disabled.add(key)
            await self._save_csv(gid, "shop:disabled_items", disabled)
            await ctx.reply(embed=_embed("🚫 Item disabled", f"**{key}** can no longer be bought or used."))
        elif state.lower() in ("enable", "on", "show", "1"):
            disabled.discard(key)
            await self._save_csv(gid, "shop:disabled_items", disabled)
            await ctx.reply(embed=_embed("✅ Item enabled", f"**{key}** is buyable again."))
        else:
            await ctx.reply(embed=_err(f"Use `disable`, `enable`, `give`, or `take`. Example: `{ctx.prefix}admin item disable audit`."))

    @admin_group.command(name="category", aliases=["cat", "disablecat"])
    async def admin_category(self, ctx: commands.Context, state: str = None, *, category: str = None):
        """Disable/enable a whole shop category (protection, debuff, buff, server).
        `!admin category disable debuff` turns off all audits/freezes/etc at once."""
        if not await self._require(ctx, "managesobs"):
            return
        gid = ctx.guild.id
        disabled = self._csv_set(await self.repo.get_guild_setting(gid, "shop:disabled_categories"))
        if state in (None, "list"):
            txt = ", ".join(sorted(disabled)) if disabled else "none"
            await ctx.reply(embed=_embed(
                "Disabled categories", f"Currently disabled: **{txt}**\n"
                f"Categories: protection, debuff, buff, server\n"
                f"`{ctx.prefix}admin category disable <name>`"))
            return
        if not category:
            await ctx.reply(embed=_err(f"Usage: `{ctx.prefix}admin category disable <name>`."))
            return
        cat = category.strip().lower()
        if state.lower() in ("disable", "off", "hide", "0"):
            disabled.add(cat)
            await self._save_csv(gid, "shop:disabled_categories", disabled)
            await ctx.reply(embed=_embed("🚫 Category disabled",
                f"All **{cat}** items are now off (can't be bought or used)."))
        elif state.lower() in ("enable", "on", "show", "1"):
            disabled.discard(cat)
            await self._save_csv(gid, "shop:disabled_categories", disabled)
            await ctx.reply(embed=_embed("✅ Category enabled", f"**{cat}** items are back."))
        else:
            await ctx.reply(embed=_err("Use `disable` or `enable`."))

    @admin_group.command(name="auditcap")
    async def admin_auditcap(self, ctx: commands.Context, value: int = None):
        """Max audits ONE person can perform per day. `!admin auditcap 5` (0 = unlimited)."""
        if not await self._require(ctx, "managesobs"):
            return
        gid = ctx.guild.id
        if value is None:
            from core.economy import AUDIT_DAILY_CAP_DEFAULT
            cur = await self.repo.get_guild_setting(gid, "economy:audit_daily_cap")
            cur = cur if cur is not None else str(AUDIT_DAILY_CAP_DEFAULT)
            await ctx.reply(embed=_embed("Audit daily cap",
                f"Each person can do **{cur}** audits/day.\n"
                f"`{ctx.prefix}admin auditcap <number>` to change (0 = unlimited)."))
            return
        await self.repo.set_guild_setting(gid, "economy:audit_daily_cap", str(max(0, value)))
        msg = "unlimited" if value <= 0 else f"{value} per day"
        await ctx.reply(embed=_embed("✅ Audit cap set", f"Each person can now do **{msg}** audits."))

    @admin_group.command(name="auditcd", aliases=["auditcooldown"])
    async def admin_auditcd(self, ctx: commands.Context, seconds: int = None):
        """Cooldown between a person's audits, in seconds. `!admin auditcd 1800` = 30 min."""
        if not await self._require(ctx, "managesobs"):
            return
        gid = ctx.guild.id
        if seconds is None:
            from core.economy import AUDIT_COOLDOWN_DEFAULT
            cur = await self.repo.get_guild_setting(gid, "economy:audit_cooldown_secs")
            cur = int(cur) if cur is not None else AUDIT_COOLDOWN_DEFAULT
            await ctx.reply(embed=_embed("Audit cooldown",
                f"Currently **{cur//60}m {cur%60}s** between audits.\n"
                f"`{ctx.prefix}admin auditcd <seconds>` to change (0 = no cooldown)."))
            return
        await self.repo.set_guild_setting(gid, "economy:audit_cooldown_secs", str(max(0, seconds)))
        msg = "no cooldown" if seconds <= 0 else f"{seconds//60}m {seconds%60}s"
        await ctx.reply(embed=_embed("✅ Audit cooldown set", f"Now **{msg}** between audits."))

    @admin_group.command(name="protection", aliases=["protect", "shieldprice"])
    async def admin_protection(self, ctx: commands.Context, factor: str = None):
        """View or override the protection price factor (auto-tuned daily).
        `!admin protection` shows it; `!admin protection 1.0` sets it; `auto` resets."""
        if not await self._require(ctx, "managesobs"):
            return
        gid = ctx.guild.id
        from core.protection import Protection
        prot = Protection(self.economy, self.repo) if getattr(self, "economy", None) else None
        if prot is None:
            # economy may live on a sibling; build from repo + a fresh Economy
            from core.economy import Economy
            prot = Protection(Economy(self.repo), self.repo)
        if factor is None:
            f = await prot.price_factor(gid)
            await ctx.reply(embed=_embed("Protection pricing",
                f"Current price factor: **{f:.2f}×** (1.00 = normal).\n"
                f"Protection is auto-priced from each player's own risk and can never "
                f"cost more than the damage it prevents.\n"
                f"`{ctx.prefix}admin protection <0.5–1.2>` to override · `auto` to reset to 1.0."))
            return
        if factor.lower() in ("auto", "reset", "default"):
            await prot.set_price_factor(gid, 1.0)
            await ctx.reply(embed=_embed("✅ Protection reset", "Price factor back to **1.00×** (auto-tuning resumes)."))
            return
        try:
            f = float(factor)
        except ValueError:
            await ctx.reply(embed=_err("Give a number between 0.5 and 1.2, or `auto`."))
            return
        await prot.set_price_factor(gid, f)
        applied = await prot.price_factor(gid)
        await ctx.reply(embed=_embed("✅ Protection factor set",
            f"Protection now priced at **{applied:.2f}×**. (Clamped to 0.5–1.2 for safety.)"))

    @admin_group.group(name="steal", invoke_without_command=True)
    async def admin_steal(self, ctx: commands.Context, state: str = None):
        """Turn !steal on/off, or `!admin steal config` to see/tune the numbers."""
        if not await self._require(ctx, "managesobs"):
            return
        gid = ctx.guild.id
        if state is None:
            off = (await self.repo.get_guild_setting(gid, "steal:enabled")) == "0"
            await ctx.reply(embed=_embed("Steal status",
                f"!steal is **{'OFF 🔒' if off else 'ON ✅'}**.\n"
                f"`{ctx.prefix}admin steal on|off` · `{ctx.prefix}admin steal config`"))
            return
        on = state.lower() in ("on", "yes", "enable", "enabled", "1", "true")
        await self.repo.set_guild_setting(gid, "steal:enabled", "1" if on else "0")
        await ctx.reply(embed=_embed("🦝 Steal " + ("enabled ✅" if on else "disabled 🔒"),
            "Players can use !steal again." if on else "Nobody can !steal until you re-enable it."))

    @admin_steal.command(name="config")
    async def admin_steal_config(self, ctx: commands.Context, chance: int = None):
        """Show steal config, or set the base success chance: `!admin steal config 18`."""
        if not await self._require(ctx, "managesobs"):
            return
        gid = ctx.guild.id
        from core import steal as S
        if chance is None:
            base = await self.repo.get_guild_setting(gid, "steal:base_chance")
            base = int(base) if base is not None else S.BASE_CHANCE
            await ctx.reply(embed=_embed("🦝 Steal config",
                f"Base chance: **{base}%** (clamped {S.CHANCE_FLOOR}–{S.CHANCE_CEIL}% after items)\n"
                f"Steal amount: **{S.STEAL_PCT*100:.2f}%** of risk balance (cap {S.STEAL_HARD_CAP:,})\n"
                f"Success split: hunter {int(S.HUNTER_SHARE*100)}% · treasury {S.TAX_PCT}%\n"
                f"Fail fee: {int(S.FAIL_FEE_PCT*100)}% of planned (half tax / half burned)\n"
                f"Attacker: {S.ATTACKER_DAILY_ATTEMPTS}/day · {S.ATTACKER_COOLDOWN//60}m cooldown · "
                f"{S.PER_TARGET_LOCKOUT//60}m per-target lockout\n"
                f"Target: max {S.DAILY_VICTIM_PCT*100:.0f}%/day lost · {S.TARGET_IMMUNITY//60}m immunity after a hit\n"
                f"`{ctx.prefix}admin steal config <chance>` to set base chance."))
            return
        c = max(S.CHANCE_FLOOR, min(S.CHANCE_CEIL, chance))
        await self.repo.set_guild_setting(gid, "steal:base_chance", str(c))
        await ctx.reply(embed=_embed("✅ Steal chance set",
            f"Base steal success chance is now **{c}%** (clamped to {S.CHANCE_FLOOR}–{S.CHANCE_CEIL}%)."))

    @admin_group.group(name="audit", invoke_without_command=True)
    async def admin_audit(self, ctx: commands.Context, member: discord.Member = None, page: int = 0):
        """Trace where a user's sobs came from — to spot exploits.
        `!admin audit @user`           — full summary (faucets, flags, ledger totals)
        `!admin audit @user <page>`    — chronological ledger entries (page 1+)
        `!admin audit tx <id>`         — every entry from one transaction"""
        if not await self._require(ctx, "managesobs"):
            return
        if member is None:
            await ctx.reply(embed=_err(
                f"Usage: `{ctx.prefix}admin audit @user` · `{ctx.prefix}admin audit @user <page>` · "
                f"`{ctx.prefix}admin audit tx <id>`."))
            return
        gid = ctx.guild.id
        uid = member.id
        db = await self.db_manager.get()

        # Page mode: show the chronological ledger for this user.
        if page and page > 0:
            await self._audit_ledger_page(ctx, member, page)
            return

        stats = await self.repo.get_user_stats(gid, uid)
        balance = int(stats["sobs_alltime"])

        # 1. reactions RECEIVED (the main faucet) — count + who gave them
        recv = await db.fetchone(
            "SELECT COUNT(*) AS n FROM sob_events WHERE guild_id=? AND target_id=?", (gid, uid))
        recv_n = int(recv["n"]) if recv else 0
        # top reactors who gave THIS user sobs (alt/farm detector)
        top_givers = await db.fetchall(
            "SELECT reactor_id, COUNT(*) AS n FROM sob_events WHERE guild_id=? AND target_id=? "
            "GROUP BY reactor_id ORDER BY n DESC LIMIT 5", (gid, uid))
        # reactions in the last 24h (burst detector)
        import time as _t
        day_ago = int(_t.time()) - 86400
        recent = await db.fetchone(
            "SELECT COUNT(*) AS n FROM sob_events WHERE guild_id=? AND target_id=? AND created_at>=?",
            (gid, uid, day_ago))
        recent_n = int(recent["n"]) if recent else 0

        # 2. snitch income
        snitch_row = await self.repo.get_snitch_row(gid, uid)
        snitches = int(snitch_row["total_snitches"]) if snitch_row else 0

        # 3. games + audits + tax paid (from logs, may not exist on old DBs)
        async def _safe(q, p):
            try:
                r = await db.fetchone(q, p); return r
            except Exception:
                return None
        game_won = await _safe("SELECT COUNT(*) AS n, COALESCE(SUM(wager),0) AS v FROM game_events WHERE guild_id=? AND winner=?", (gid, uid))
        audit_did = await _safe("SELECT COUNT(*) AS n, COALESCE(SUM(amount),0) AS v FROM audit_events WHERE guild_id=? AND auditor_id=?", (gid, uid))
        daily = await _safe("SELECT total_claimed FROM daily_claims WHERE guild_id=? AND user_id=?", (gid, uid))

        # build report
        e = discord.Embed(title=f"🔍 Audit — {member.display_name}", color=ACCENT)
        e.description = f"Balance: **{balance:,}** sobs"

        # reactions block with burst + top givers
        giver_lines = []
        for g in top_givers:
            gm = ctx.guild.get_member(int(g["reactor_id"]))
            gname = gm.display_name if gm else f"user {g['reactor_id']}"
            giver_lines.append(f"  {gname}: {int(g['n'])}")
        e.add_field(
            name="Reactions received (main faucet)",
            value=(f"Total: **{recv_n:,}**  ·  last 24h: **{recent_n:,}**\n"
                   f"Top reactors who fed them:\n" + ("\n".join(giver_lines) or "  none")),
            inline=False)

        # flags
        flags = []
        if recent_n > 200:
            flags.append(f"⚠️ {recent_n} reactions in 24h — possible farming")
        if top_givers:
            top_share = int(top_givers[0]["n"]) / max(1, recv_n)
            if top_share > 0.5 and recv_n > 50:
                tm = ctx.guild.get_member(int(top_givers[0]["reactor_id"]))
                tn = tm.display_name if tm else "one account"
                flags.append(f"⚠️ {int(top_share*100)}% of their sobs came from **{tn}** — possible alt/farm")
        if game_won and int(game_won["n"]) > 0:
            flags.append(f"🎲 won {int(game_won['n'])} games (+{int(game_won['v']):,} wagered)")

        other = []
        other.append(f"Snitches done: {snitches}")
        if audit_did and int(audit_did["n"]):
            other.append(f"Audits/heists: {int(audit_did['n'])} (+{int(audit_did['v']):,})")
        if daily and daily["total_claimed"]:
            other.append(f"Daily claimed total: {int(daily['total_claimed']):,}")
        e.add_field(name="Other income", value="\n".join(other), inline=False)

        if flags:
            e.add_field(name="🚩 Flags", value="\n".join(flags), inline=False)
        else:
            e.add_field(name="Flags", value="Nothing obviously abnormal.", inline=False)

        # alt/farm scoring on the top reactors who fed this user
        from core.economy import score_member_suspicion
        sus_lines = []
        sus_total = 0
        for g in top_givers:
            rid = int(g["reactor_id"])
            gm = ctx.guild.get_member(rid)
            if gm is None:
                continue
            la = await db.fetchone(
                "SELECT last_msg_at FROM user_activity WHERE guild_id=? AND user_id=?", (gid, rid))
            last_msg = int(la["last_msg_at"]) if la else 0
            score = score_member_suspicion(gm, last_msg)
            if score["suspicious"]:
                sus_total += int(g["n"])
                sus_lines.append(f"  ⚠️ {gm.display_name}: {int(g['n'])} reactions ({', '.join(score['reasons'])})")

        if sus_lines:
            pct = int(100 * sus_total / max(1, recv_n))
            e.add_field(
                name=f"🚩 Suspicious reactors ({pct}% of their sobs)",
                value="\n".join(sus_lines) + "\n*New/inactive accounts feeding them sobs = likely alts.*",
                inline=False)

        # Ledger-derived earned/spent by source + reconciliation.
        from core import ledger as _ledger
        try:
            summ = await _ledger.user_summary(db, gid, uid)
            recon = await _ledger.reconcile_user(db, gid, uid, balance)
            top_sources = sorted(summ["by_event"].items(),
                                 key=lambda kv: kv[1]["earned"], reverse=True)[:6]
            src_lines = []
            for ev, agg in top_sources:
                if agg["earned"] or agg["spent"]:
                    src_lines.append(f"  {ev}: +{agg['earned']:,} / -{agg['spent']:,} ({agg['count']})")
            if src_lines:
                e.add_field(
                    name=f"📒 Ledger (earned {summ['total_earned']:,} · spent {summ['total_spent']:,})",
                    value="\n".join(src_lines), inline=False)
            recon_txt = ("✅ reconciles" if recon["reconciled"]
                         else f"⚠️ off by {recon['delta']:,} (live {recon['live_balance']:,} vs ledger {recon['ledger_net']:,})")
            e.add_field(name="Reconciliation", value=recon_txt, inline=False)
        except Exception as exc:
            e.add_field(name="Ledger", value=f"(unavailable: {exc})", inline=False)

        e.set_footer(text=f"High 24h reactions or one dominant/suspicious reactor = likely alt/farm. "
                          f"Page the ledger with {ctx.prefix}admin audit @user 1")
        await ctx.reply(embed=e)

    async def _audit_ledger_page(self, ctx, member, page):
        """Chronological ledger entries for one user (page 1+)."""
        from core import ledger as _ledger
        gid, uid = ctx.guild.id, member.id
        db = await self.db_manager.get()
        per = 12
        entries = await _ledger.user_entries(db, gid, uid, page=page - 1, per_page=per)
        if not entries:
            await ctx.reply(embed=_embed("📒 Ledger", f"No entries on page {page} for {member.mention}."))
            return
        lines = []
        for r in entries:
            sign = "+" if int(r["delta"]) >= 0 else ""
            extra = ""
            if r["item_key"]:
                extra += f" [{r['item_key']}]"
            if int(r["counterparty_id"]):
                extra += f" ↔{r['counterparty_id']}"
            lines.append(
                f"`#{r['ledger_id']}` {r['event_type']} {sign}{int(r['delta']):,} "
                f"(→{int(r['balance_after']):,}){extra}")
        e = _embed(f"📒 Ledger — {member.display_name} (page {page})", "\n".join(lines))
        e.set_footer(text=f"tx ids via {ctx.prefix}admin audit tx <id> · next: {ctx.prefix}admin audit @user {page+1}")
        await ctx.reply(embed=e)

    @admin_audit.command(name="tx")
    async def admin_audit_tx(self, ctx: commands.Context, transaction_id: str = None):
        """Show every ledger entry from one transaction (proves it nets to zero)."""
        if not await self._require(ctx, "managesobs"):
            return
        if not transaction_id:
            await ctx.reply(embed=_err(f"Usage: `{ctx.prefix}admin audit tx <transaction_id>`."))
            return
        from core import ledger as _ledger
        db = await self.db_manager.get()
        rows = await _ledger.transaction_entries(db, transaction_id)
        if not rows:
            await ctx.reply(embed=_err(f"No ledger entries for transaction `{transaction_id}`."))
            return
        lines = []
        net = 0
        for r in rows:
            net += int(r["delta"])
            sign = "+" if int(r["delta"]) >= 0 else ""
            lines.append(
                f"`#{r['ledger_id']}` {r['event_type']} · subj `{r['subject_id']}` "
                f"{sign}{int(r['delta']):,} (→{int(r['balance_after']):,})"
                + (f" · tax {int(r['tax_amount'])}" if int(r['tax_amount']) else "")
                + (f" · burn {int(r['burned_amount'])}" if int(r['burned_amount']) else ""))
        e = _embed(f"🧾 Transaction {transaction_id[:12]}…", "\n".join(lines))
        e.add_field(name="Net delta", value=f"`{net:,}` "
                    + ("(balanced ✅)" if net == 0 else "(intentional mint/burn)"), inline=False)
        await ctx.reply(embed=e)

    @admin_group.command(name="suspicious", aliases=["sus"])
    async def admin_suspicious(self, ctx: commands.Context, member: discord.Member = None):
        """Flag rapid reaction toggles, repeated failures, unusual daily claims,
        negative inventory, repeated shop attempts, altblock events, or abnormal
        source totals for one user."""
        if not await self._require(ctx, "managesobs"):
            return
        if member is None:
            await ctx.reply(embed=_err(f"Usage: `{ctx.prefix}admin suspicious @user`."))
            return
        gid, uid = ctx.guild.id, member.id
        db = await self.db_manager.get()
        import time as _t
        now = int(_t.time())
        flags = []

        async def _safe1(q, p):
            try:
                r = await db.fetchone(q, p)
                return int(r[0]) if r and r[0] is not None else 0
            except Exception:
                return 0

        # rapid reaction add/remove toggles (mint attempts) from the ledger
        adds = await _safe1("SELECT COUNT(*) FROM economy_ledger WHERE guild_id=? AND subject_id=? "
                            "AND event_type='sob_reaction_added' AND created_at>=?", (gid, uid, now - 3600))
        rems = await _safe1("SELECT COUNT(*) FROM economy_ledger WHERE guild_id=? AND subject_id=? "
                            "AND event_type='sob_reaction_removed' AND created_at>=?", (gid, uid, now - 3600))
        if rems > 10 and adds > 0 and rems >= adds * 0.5:
            flags.append(f"⚠️ {rems} reaction removals vs {adds} adds in 1h — toggle/mint probing")

        # blocked reactions (altblock / security log) where they were the reactor
        blocked = await _safe1("SELECT COUNT(*) FROM security_log WHERE guild_id=? AND actor_id=? "
                               "AND event_type='blocked_reaction'", (gid, uid))
        if blocked:
            flags.append(f"🚩 {blocked} reactions blocked by anti-alt protection")

        # negative inventory (should be impossible now — surfaces legacy/corrupt rows)
        neg_inv = await _safe1("SELECT COUNT(*) FROM shop_inventory WHERE guild_id=? AND user_id=? AND quantity<0",
                               (gid, uid))
        if neg_inv:
            flags.append(f"🛑 {neg_inv} inventory rows are NEGATIVE — investigate")

        # repeated shop 'not enough' attempts would be in security log if logged;
        # surface big audit/heist victim counts instead
        audited = await _safe1("SELECT COUNT(*) FROM audit_events WHERE guild_id=? AND auditor_id=?", (gid, uid))
        if audited > 50:
            flags.append(f"🎯 {audited} audits performed — unusually high")

        # unusual daily: streak/total mismatch
        try:
            drow = await db.fetchone("SELECT streak, total_claimed FROM daily_claims WHERE guild_id=? AND user_id=?",
                                     (gid, uid))
            if drow and int(drow["total_claimed"]) > int(drow["streak"]) * 80 + 1000:
                flags.append(f"📅 daily total {int(drow['total_claimed']):,} looks high for streak {int(drow['streak'])}")
        except Exception:
            pass

        # reconciliation mismatch is itself suspicious
        from core import ledger as _ledger
        stats = await self.repo.get_user_stats(gid, uid)
        recon = await _ledger.reconcile_user(db, gid, uid, int(stats["sobs_alltime"]))
        if not recon["reconciled"]:
            flags.append(f"⚠️ balance doesn't reconcile with ledger (off by {recon['delta']:,}) — "
                         f"normal for pre-ledger history, suspicious if recent")

        e = discord.Embed(title=f"🕵️ Suspicious check — {member.display_name}", color=ACCENT)
        e.description = "\n".join(flags) if flags else "✅ Nothing obviously abnormal in the logs."
        await ctx.reply(embed=e)

    @admin_group.command(name="auditexport", aliases=["auditjson"])
    async def admin_audit_export(self, ctx: commands.Context, member: discord.Member = None):
        """Full per-user JSON for AI/manual exploit analysis: every sob in/out,
        reactors, snitches, items bought, games, audits — with alt scoring."""
        if not await self._require(ctx, "managesobs"):
            return
        if member is None:
            await ctx.reply(embed=_err(f"Usage: `{ctx.prefix}admin auditexport @user`."))
            return
        gid, uid = ctx.guild.id, member.id
        db = await self.db_manager.get()
        import time as _t
        from core.economy import score_member_suspicion

        async def rows(q, p):
            try:
                return [dict(r) for r in await db.fetchall(q, p)]
            except Exception:
                return []

        stats = await self.repo.get_user_stats(gid, uid)

        # everyone who reacted to this user (with alt scoring)
        reactors = await rows(
            "SELECT reactor_id, COUNT(*) AS reactions, MIN(created_at) AS first, MAX(created_at) AS last "
            "FROM sob_events WHERE guild_id=? AND target_id=? GROUP BY reactor_id ORDER BY reactions DESC",
            (gid, uid))
        for r in reactors:
            rid = int(r["reactor_id"])
            gm = ctx.guild.get_member(rid)
            la = await db.fetchone("SELECT last_msg_at, msg_count FROM user_activity WHERE guild_id=? AND user_id=?", (gid, rid))
            last_msg = int(la["last_msg_at"]) if la else 0
            r["msg_count"] = int(la["msg_count"]) if la else 0
            if gm is not None:
                sc = score_member_suspicion(gm, last_msg)
                r["display_name"] = gm.display_name
                r["account_created"] = gm.created_at.isoformat() if gm.created_at else None
                r["joined_server"] = gm.joined_at.isoformat() if gm.joined_at else None
                r["suspicious"] = sc["suspicious"]
                r["suspicion_reasons"] = sc["reasons"]
            else:
                r["display_name"] = None
                r["suspicious"] = None

        payload = {
            "ignio_audit_version": 1,
            "guild_id": gid,
            "user_id": uid,
            "user_name": member.display_name,
            "exported_at": int(_t.time()),
            "balance": int(stats["sobs_alltime"]),
            "account_created": member.created_at.isoformat() if member.created_at else None,
            "joined_server": member.joined_at.isoformat() if member.joined_at else None,
            "reactors_who_fed_them": reactors,
            "reactions_given_by_them": await rows(
                "SELECT target_id, COUNT(*) AS n FROM sob_events WHERE guild_id=? AND reactor_id=? GROUP BY target_id ORDER BY n DESC",
                (gid, uid)),
            "snitches_done": await rows(
                "SELECT target_id, amount, created_at FROM audit_events WHERE guild_id=? AND auditor_id=? ORDER BY created_at DESC",
                (gid, uid)),
            "audited_by_others": await rows(
                "SELECT auditor_id, amount, created_at FROM audit_events WHERE guild_id=? AND target_id=? ORDER BY created_at DESC",
                (gid, uid)),
            "items_bought": await rows(
                "SELECT item_key, quantity, updated_at FROM shop_inventory WHERE guild_id=? AND user_id=?",
                (gid, uid)),
            "games_played": await rows(
                "SELECT game, challenger, opponent, wager, winner, loser, created_at FROM game_events "
                "WHERE guild_id=? AND (challenger=? OR opponent=?) ORDER BY created_at DESC",
                (gid, uid, uid)),
            "tax_paid": await rows(
                "SELECT amount, created_at FROM tax_events WHERE guild_id=? AND user_id=? ORDER BY created_at DESC",
                (gid, uid)),
        }
        buf = io.BytesIO(json.dumps(payload, ensure_ascii=False, indent=2, default=str).encode("utf-8"))
        file = discord.File(buf, filename=f"audit_{uid}.json")
        sus_count = sum(1 for r in reactors if r.get("suspicious"))
        e = _embed("🔍 Audit export ready",
                   f"Full breakdown for **{member.display_name}**.\n"
                   f"{len(reactors)} distinct reactors · {sus_count} flagged suspicious.\n"
                   f"Feed this JSON to an AI to hunt for exploits.")
        await ctx.reply(embed=e, file=file)

    @admin_group.command(name="weekly", aliases=["weekreport"])
    async def admin_weekly(self, ctx: commands.Context):
        """A week's activity report: top earners, top reactor pairs (farm pairs),
        biggest snitches, item buys — server-wide exploit overview."""
        if not await self._require(ctx, "managesobs"):
            return
        gid = ctx.guild.id
        db = await self.db_manager.get()
        import time as _t
        week_ago = int(_t.time()) - 604800

        async def rows(q, p):
            try:
                return [dict(r) for r in await db.fetchall(q, p)]
            except Exception:
                return []

        # top reactor->target PAIRS this week (the farm-pair detector)
        pairs = await rows(
            "SELECT reactor_id, target_id, COUNT(*) AS n FROM sob_events "
            "WHERE guild_id=? AND created_at>=? GROUP BY reactor_id, target_id "
            "ORDER BY n DESC LIMIT 10", (gid, week_ago))

        e = discord.Embed(title="📅 Weekly report", color=ACCENT)
        if pairs:
            lines = []
            for p in pairs:
                rm = ctx.guild.get_member(int(p["reactor_id"]))
                tm = ctx.guild.get_member(int(p["target_id"]))
                rn = rm.display_name if rm else f"user {p['reactor_id']}"
                tn = tm.display_name if tm else f"user {p['target_id']}"
                flag = " 🚩" if int(p["n"]) > 100 else ""
                lines.append(f"{rn} → {tn}: **{int(p['n'])}**{flag}")
            e.add_field(name="Top reactor → target pairs (farm detector)",
                        value="\n".join(lines), inline=False)
            e.set_footer(text="🚩 = one account reacting to another 100+ times this week = likely farm/alt.")
        else:
            e.description = "No reaction activity logged this week yet."
        await ctx.reply(embed=e)

    @admin_group.command(name="export")
    async def admin_export(self, ctx: commands.Context, guild_id: int | None = None):
        if not await self._require_owner(ctx):
            return
        gid = guild_id or (ctx.guild.id if ctx.guild else None)
        if gid is None:
            await ctx.reply(embed=_err("Provide a guild_id (or run this in a server)."))
            return
        db = await self.db_manager.get()
        payload = await transfer.export_guild(db, gid)
        total = sum(len(v) for v in payload["tables"].values())
        if total == 0:
            await ctx.reply(embed=_err(f"No data found for guild `{gid}`."))
            return
        buf = io.BytesIO(json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8"))
        file = discord.File(buf, filename=f"ignio_export_{gid}.json")
        counts = "\n".join(f"`{t}` — {len(v)}" for t, v in payload["tables"].items())
        e = _embed("📦 Export ready", f"Guild `{gid}`\n{counts}")
        await ctx.reply(embed=e, file=file)

    @admin_group.command(name="import")
    async def admin_import(self, ctx: commands.Context, mode: str = "merge", target_guild_id: int | None = None):
        if not await self._require_owner(ctx):
            return
        if mode not in ("merge", "replace"):
            await ctx.reply(embed=_err("Mode must be `merge` or `replace`."))
            return
        if not ctx.message.attachments:
            await ctx.reply(embed=_err("Attach the exported `.json` file to your message."))
            return
        raw = await ctx.message.attachments[0].read()
        try:
            payload = json.loads(raw.decode("utf-8"))
        except Exception as exc:
            await ctx.reply(embed=_err(f"Couldn't parse file: {exc}"))
            return
        db = await self.db_manager.get()
        try:
            inserted = await transfer.import_guild(db, payload, mode=mode, target_guild_id=target_guild_id)
        except Exception as exc:
            await ctx.reply(embed=_err(f"Import failed (no changes committed): {exc}"))
            return
        gid = target_guild_id or payload.get("guild_id")
        counts = "\n".join(f"`{t}` — +{n}" for t, n in inserted.items())
        await ctx.reply(embed=_ok(f"Imported into `{gid}` [{mode}]", counts))