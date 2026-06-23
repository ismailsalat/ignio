# core/perms_cog.py
from __future__ import annotations

import discord
from discord.ext import commands

from core import perms

ACCENT = 0xF0B132


class PermsCog(commands.Cog):
    """View and manage which roles can do what. Managed by admins/owner only."""

    def __init__(self, bot: commands.Bot, settings, sob_repo):
        self.bot = bot
        self.settings = settings
        self.sob_repo = sob_repo

    @commands.group(name="perms", aliases=["permissions"], invoke_without_command=True)
    @commands.guild_only()
    async def perms_group(self, ctx: commands.Context):
        gid = ctx.guild.id
        e = discord.Embed(
            title="🔑 Role Permissions",
            description="Roles below can use these actions. **Admins always can, regardless.**",
            color=ACCENT,
        )

        any_set = False
        for perm, desc in perms.PERMISSIONS.items():
            role_ids = await perms.get_role_ids_for_perm(self.sob_repo, gid, perm)
            if role_ids:
                any_set = True
                mentions = []
                for rid in role_ids:
                    role = ctx.guild.get_role(rid)
                    mentions.append(role.mention if role else f"`{rid}`")
                roles_txt = ", ".join(mentions)
            else:
                roles_txt = "*admins only*"
            e.add_field(name=f"`{perm}` — {desc}", value=roles_txt, inline=False)

        p = ctx.prefix
        e.set_footer(text=f"{p}perms grant @role <perm>  ·  {p}perms revoke @role <perm>")
        await ctx.reply(embed=e)

    @perms_group.command(name="grant")
    @commands.guild_only()
    async def perms_grant(self, ctx: commands.Context, role: discord.Role, perm: str):
        if not perms.is_admin(ctx.author, self.settings):
            await ctx.reply(embed=self._err("Only admins can manage permissions."))
            return
        perm = perm.lower().strip()
        if perm == "all":
            for pk in perms.PERMISSIONS:
                await perms.grant(self.sob_repo, ctx.guild.id, pk, role.id)
            await ctx.reply(embed=self._ok("Granted ALL", f"{role.mention} can now use every action."))
            return
        if perm not in perms.PERMISSIONS:
            await ctx.reply(embed=self._err(f"Unknown permission `{perm}`. Valid: {', '.join(perms.PERMISSIONS)}"))
            return
        await perms.grant(self.sob_repo, ctx.guild.id, perm, role.id)
        await ctx.reply(embed=self._ok("Permission granted", f"{role.mention} can now use `{perm}`."))

    @perms_group.command(name="revoke")
    @commands.guild_only()
    async def perms_revoke(self, ctx: commands.Context, role: discord.Role, perm: str):
        if not perms.is_admin(ctx.author, self.settings):
            await ctx.reply(embed=self._err("Only admins can manage permissions."))
            return
        perm = perm.lower().strip()
        if perm == "all":
            for pk in perms.PERMISSIONS:
                await perms.revoke(self.sob_repo, ctx.guild.id, pk, role.id)
            await ctx.reply(embed=self._ok("Revoked ALL", f"{role.mention} no longer has any actions."))
            return
        if perm not in perms.PERMISSIONS:
            await ctx.reply(embed=self._err(f"Unknown permission `{perm}`. Valid: {', '.join(perms.PERMISSIONS)}"))
            return
        await perms.revoke(self.sob_repo, ctx.guild.id, perm, role.id)
        await ctx.reply(embed=self._ok("Permission revoked", f"{role.mention} can no longer use `{perm}`."))

    @perms_group.command(name="help")
    @commands.guild_only()
    async def perms_help(self, ctx: commands.Context):
        p = ctx.prefix
        e = discord.Embed(title="🔑 Permissions — Help", color=ACCENT)
        e.add_field(
            name="View",
            value=f"`{p}perms` — show every role and what it can do",
            inline=False,
        )
        e.add_field(
            name="Manage (admins only)",
            value=(
                f"`{p}perms grant @role <perm>`\n"
                f"`{p}perms revoke @role <perm>`\n"
                f"`{p}perms grant @role all` — grant everything"
            ),
            inline=False,
        )
        e.add_field(
            name="Permissions",
            value="\n".join(f"`{k}` — {v}" for k, v in perms.PERMISSIONS.items()),
            inline=False,
        )
        await ctx.reply(embed=e)

    def _ok(self, title, desc):
        return discord.Embed(title=f"✅ {title}", description=desc, color=ACCENT)

    def _err(self, desc):
        return discord.Embed(title="⚠️ Error", description=desc, color=ACCENT)