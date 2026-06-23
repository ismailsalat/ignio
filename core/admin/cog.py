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

    def __init__(self, bot: commands.Bot, settings, db_manager, sob_repo):
        self.bot = bot
        self.settings = settings
        self.db_manager = db_manager
        self.repo = sob_repo

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