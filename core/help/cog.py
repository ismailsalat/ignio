# core/help/cog.py
from __future__ import annotations

import discord
from discord.ext import commands

ACCENT = 0xF0B132


def _is_admin(ctx, settings) -> bool:
    owner_ids = set(getattr(settings, "owner_ids", ()) or ())
    if ctx.author.id in owner_ids:
        return True
    perms = getattr(ctx.author, "guild_permissions", None)
    return bool(perms and (perms.administrator or perms.manage_guild))


class HelpCog(commands.Cog):
    """Custom, clean help. Replaces discord.py's default help command."""

    def __init__(self, bot: commands.Bot, settings):
        self.bot = bot
        self.settings = settings
        # remove the built-in help so ours takes over
        bot.remove_command("help")

    @commands.command(name="help")
    async def help_cmd(self, ctx: commands.Context):
        p = ctx.prefix
        e = discord.Embed(
            title="😭 Ignio — Help",
            description="A sob-tracking bot with a competitive snitch economy.",
            color=ACCENT,
        )

        e.add_field(
            name="📊 Sobs",
            value=(
                f"`{p}sob` — your stats\n"
                f"`{p}sob lb` — leaderboard\n"
                f"`{p}ss` — (reply to a message) use a snitch token"
            ),
            inline=False,
        )

        e.add_field(
            name="🛒 Shop",
            value=(
                f"`{p}shop` — browse & buy (with buttons)\n"
                f"`{p}buy <item>` — buy something\n"
                f"`{p}me` — your items + active effects\n"
                f"`{p}use <item> [@user]` — use an item"
            ),
            inline=False,
        )

        e.add_field(
            name="❓ How it works",
            value=(
                "React with a sob emoji to give someone a sob. Earn snitch "
                "tokens to wipe sobs off a message. Spend sobs in the shop on "
                "🛡️ shields, ❄️ freezes, and ⚡ boosts to outplay rivals."
            ),
            inline=False,
        )

        if _is_admin(ctx, self.settings):
            e.add_field(
                name="🛡️ Admin",
                value=(
                    f"`{p}admin` — admin menu\n"
                    f"`{p}admin config` — server settings\n"
                    f"`{p}perms` — role permissions (let other roles give sobs/tokens)\n"
                    f"`{p}announce #channel Title | Body` — post an announcement\n"
                    f"`{p}shop additem` · `{p}shop boostmult` — shop config"
                ),
                inline=False,
            )

        e.set_footer(text=f"Tip: {p}shop help for shop details · {p}sob help for sob details")
        await ctx.reply(embed=e)