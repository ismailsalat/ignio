# core/gating_cog.py
from __future__ import annotations

import discord
from discord.ext import commands

from core import gating

ACCENT = 0xF0B132


def _is_admin(member, settings) -> bool:
    owner_ids = set(getattr(settings, "owner_ids", ()) or ())
    if member.id in owner_ids:
        return True
    perms = getattr(member, "guild_permissions", None)
    return bool(perms and (perms.administrator or perms.manage_guild))


class GatingCog(commands.Cog):
    """Admin: disable/enable commands or whole categories, per channel or server-wide."""

    def __init__(self, bot, settings, gate: gating.Gating):
        self.bot = bot
        self.settings = settings
        self.gate = gate

    def _err(self, d): return discord.Embed(title="⚠️ Error", description=d, color=ACCENT)
    def _ok(self, t, d): return discord.Embed(title=f"✅ {t}", description=d, color=ACCENT)

    def _resolve(self, name: str):
        """Return ('category', name) or ('command', name) or (None, None)."""
        name = name.lower().strip()
        if name in gating.CATEGORIES:
            return "category", name
        if name in gating.COMMAND_CATEGORY:
            return "command", name
        return None, None

    @commands.command(name="disable")
    @commands.guild_only()
    async def disable_cmd(self, ctx, target: str | None = None, channel: discord.TextChannel | None = None):
        await self._toggle(ctx, target, channel, disable=True)

    @commands.command(name="enable")
    @commands.guild_only()
    async def enable_cmd(self, ctx, target: str | None = None, channel: discord.TextChannel | None = None):
        await self._toggle(ctx, target, channel, disable=False)

    async def _toggle(self, ctx, target, channel, disable: bool):
        if not _is_admin(ctx.author, self.settings):
            await ctx.reply(embed=self._err("Only admins can change command settings."))
            return
        if not target:
            cats = ", ".join(c for c in gating.CATEGORIES if c not in gating.PROTECTED_CATEGORIES)
            await ctx.reply(embed=self._err(
                f"Usage: `{ctx.prefix}{'disable' if disable else 'enable'} <category|command> [#channel]`\n"
                f"Categories: {cats}"))
            return

        scope, name = self._resolve(target)
        if scope is None:
            await ctx.reply(embed=self._err(f"Unknown category or command: `{target}`."))
            return
        if name in gating.PROTECTED_CATEGORIES or gating.category_of(name) in gating.PROTECTED_CATEGORIES:
            await ctx.reply(embed=self._err("Admin commands can't be disabled (safety)."))
            return

        gid = ctx.guild.id
        chan_id = channel.id if channel else None
        where = f"in {channel.mention}" if channel else "server-wide"

        if scope == "category":
            if disable:
                await self.gate.disable_category(gid, name, chan_id)
            else:
                await self.gate.enable_category(gid, name, chan_id)
        else:
            if disable:
                await self.gate.disable_command(gid, name, chan_id)
            else:
                await self.gate.enable_command(gid, name, chan_id)

        verb = "disabled" if disable else "enabled"
        await ctx.reply(embed=self._ok(f"{scope.title()} {verb}",
                                       f"**{name}** is now {verb} {where}."))

    @commands.command(name="commandconfig", aliases=["cmdconfig", "gateconfig"])
    @commands.guild_only()
    async def command_config(self, ctx):
        if not _is_admin(ctx.author, self.settings):
            await ctx.reply(embed=self._err("Only admins can view command config."))
            return
        rules = await self.gate.list_rules(ctx.guild.id)
        e = discord.Embed(title="🚦 Command Config", color=ACCENT)
        if not rules:
            e.description = "Everything is enabled everywhere. ✅"
        else:
            lines = []
            for r in rules:
                where = f"<#{r['channel_id']}>" if r["channel_id"] else "server-wide"
                lines.append(f"🚫 {r['scope']} **{r['name']}** — {where}")
            e.description = "\n".join(lines)
        e.add_field(name="Manage", value=(
            f"`{ctx.prefix}disable <category|command> [#channel]`\n"
            f"`{ctx.prefix}enable <category|command> [#channel]`\n"
            f"Categories: {', '.join(c for c in gating.CATEGORIES if c not in gating.PROTECTED_CATEGORIES)}"
        ), inline=False)
        await ctx.reply(embed=e)
