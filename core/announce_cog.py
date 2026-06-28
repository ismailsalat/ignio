# core/announce_cog.py
from __future__ import annotations

import discord
from discord.ext import commands

from core import perms

ACCENT = 0xF0B132


class AnnounceCog(commands.Cog):
    """Post a clean announcement embed to a chosen channel, with optional ping."""

    def __init__(self, bot: commands.Bot, settings, sob_repo):
        self.bot = bot
        self.settings = settings
        self.sob_repo = sob_repo

    def _err(self, desc: str) -> discord.Embed:
        return discord.Embed(title="⚠️ Error", description=desc, color=ACCENT)

    @commands.command(name="announce", aliases=["announcement"])
    @commands.guild_only()
    async def announce(self, ctx: commands.Context, channel: discord.TextChannel | None = None, *, rest: str | None = None):
        # permission: admins/owner always; others need the 'announce' perm
        if not await perms.member_has_perm(self.sob_repo, ctx.author, self.settings, "announce"):
            await ctx.reply(embed=self._err("You need the `announce` permission to use this."))
            return

        if channel is None:
            await ctx.reply(embed=self._err(
                f"Usage: `{ctx.prefix}announce #channel [@role] Title | Body`\n"
                f"Example: `{ctx.prefix}announce #news @everyone New item! | A limited edition Shield just dropped in the shop.`"
            ))
            return

        if not rest or not rest.strip():
            await ctx.reply(embed=self._err("Add a message: `Title | Body` (or just a body)."))
            return

        # pull out a ping (role mention or @everyone/@here) from the front
        ping = ""
        text = rest.strip()

        if ctx.message.role_mentions:
            role = ctx.message.role_mentions[0]
            ping = role.mention
            for token in (f"<@&{role.id}>",):
                text = text.replace(token, "")
        elif text.startswith("@everyone"):
            ping = "@everyone"
            text = text[len("@everyone"):]
        elif text.startswith("@here"):
            ping = "@here"
            text = text[len("@here"):]

        text = text.strip()
        if not text:
            await ctx.reply(embed=self._err("Add a message after the ping."))
            return

        # split title | body
        if "|" in text:
            title, body = text.split("|", 1)
            title = title.strip() or "📢 Announcement"
            body = body.strip()
        else:
            title = "📢 Announcement"
            body = text

        if not body:
            await ctx.reply(embed=self._err("The body can't be empty."))
            return

        # build the embed
        embed = discord.Embed(title=title, description=body, color=ACCENT)
        embed.set_footer(text=f"Announced by {ctx.author.display_name}")
        embed.timestamp = discord.utils.utcnow()

        # check we can post there
        me = ctx.guild.me
        if not channel.permissions_for(me).send_messages:
            await ctx.reply(embed=self._err(f"I don't have permission to post in {channel.mention}."))
            return

        allowed = discord.AllowedMentions(everyone=True, roles=True)
        try:
            await channel.send(content=ping or None, embed=embed, allowed_mentions=allowed)
        except discord.Forbidden:
            await ctx.reply(embed=self._err(f"I couldn't post in {channel.mention} (missing permissions)."))
            return

        await ctx.reply(embed=discord.Embed(
            title="✅ Announcement sent",
            description=f"Posted in {channel.mention}" + (f" · pinged {ping}" if ping else ""),
            color=ACCENT,
        ))