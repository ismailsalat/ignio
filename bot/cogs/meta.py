# bot/cogs/meta.py
from __future__ import annotations

import discord
from discord.ext import commands


class MetaCog(commands.Cog):
    def __init__(self, bot: commands.Bot, settings):
        self.bot = bot
        self.settings = settings

    def _prefix(self) -> str:
        try:
            p = getattr(self.bot, "command_prefix", None)
            if isinstance(p, str) and p.strip():
                return p.strip()
        except Exception:
            pass
        return "!"

    @commands.command(name="ignio", aliases=["about", "bot"])
    @commands.guild_only()
    async def ignio(self, ctx: commands.Context):
        """
        Product-style bot info command.
        Usage:
          !ignio
        """
        prefix = self._prefix()
        env = getattr(self.settings, "env", "prod")
        app_name = getattr(self.settings, "app_name", "Ignio")
        version = getattr(self.settings, "version", "")

        support_name = getattr(self.settings, "support_server_name", "Ignio Support")
        support_invite = getattr(self.settings, "support_server_invite", "")

        main_name = getattr(self.settings, "main_server_name", "")
        main_id = int(getattr(self.settings, "main_server_id", 0) or 0)

        repo_url = getattr(self.settings, "repo_url", "")

        title = f"🤖 {app_name} ({'DEV' if env == 'dev' else 'PROD'})"
        embed = discord.Embed(title=title)

        # Top info
        desc = []
        if version:
            desc.append(f"**Build:** `{version}`")
        desc.append(f"**Prefix:** `{prefix}`")
        embed.description = "\n".join(desc)

        # Main server
        if main_name or main_id:
            main_line = main_name if main_name else "Main server"
            if main_id:
                main_line += f" (`{main_id}`)"
            embed.add_field(name="Main Server", value=main_line, inline=False)

        # Support server
        if support_invite:
            embed.add_field(name="Support Server", value=f"[{support_name}]({support_invite})", inline=False)
        else:
            embed.add_field(name="Support Server", value=support_name, inline=False)

        # Extra / links
        links = []
        if repo_url:
            links.append(f"[Source]({repo_url})")
        if links:
            embed.add_field(name="Links", value=" • ".join(links), inline=False)

        embed.set_footer(text=f"Tip: Try {prefix}help for commands")
        await ctx.reply(embed=embed)


async def setup(bot: commands.Bot):
    # support both patterns: injected settings or bot.settings
    settings = getattr(bot, "settings", None)
    await bot.add_cog(MetaCog(bot, settings))
