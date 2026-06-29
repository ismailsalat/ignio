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

    def __init__(self, bot: commands.Bot, settings, db_manager, sob_repo, profile_service=None):
        self.bot = bot
        self.settings = settings
        self.db_manager = db_manager
        self.repo = sob_repo
        self.profile = profile_service

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
        new_total = await self.repo.adjust_received(ctx.guild.id, member.id, amount)
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

    @admin_group.command(name="audit")
    async def admin_audit(self, ctx: commands.Context, member: discord.Member = None):
        """Trace where a user's sobs came from — to spot exploits."""
        if not await self._require(ctx, "managesobs"):
            return
        if member is None:
            await ctx.reply(embed=_err(f"Usage: `{ctx.prefix}admin audit @user`."))
            return
        gid = ctx.guild.id
        uid = member.id
        db = await self.db_manager.get()

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

        e.set_footer(text="High 24h reactions or one dominant/suspicious reactor = likely alt/farm exploit.")
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