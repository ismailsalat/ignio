# bot/cogs/errors.py
import discord
from discord.ext import commands


class ErrorHandlerCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    def _prefix(self, ctx: commands.Context) -> str:
        try:
            p = getattr(self.bot, "command_prefix", None)
            if isinstance(p, str) and p.strip():
                return p.strip()
        except Exception:
            pass
        return "!"

    @commands.Cog.listener()
    async def on_command_error(self, ctx: commands.Context, error: Exception):
        # ignore commands not found
        if isinstance(error, commands.CommandNotFound):
            return

        # unwrap original error
        if hasattr(error, "original"):
            error = error.original

        prefix = self._prefix(ctx)

        # ---------------- common errors ----------------

        if isinstance(error, commands.MissingRequiredArgument):
            return await ctx.reply(
                f"Missing: `{error.param.name}`\n"
                f"Use: `{prefix}{ctx.command} {ctx.command.signature}`"
            )

        if isinstance(error, commands.BadArgument):
            return await ctx.reply("Invalid input. Try mentioning a user like `@milk`.")

        if isinstance(error, commands.MissingPermissions):
            return await ctx.reply("You don’t have permission to use this.")

        if isinstance(error, commands.BotMissingPermissions):
            return await ctx.reply("I’m missing permissions to do that.")

        if isinstance(error, commands.CommandOnCooldown):
            return await ctx.reply(
                f"Slow down. Try again in `{round(error.retry_after)}s`."
            )

        if isinstance(error, commands.CheckFailure):
            return await ctx.reply("You can’t use this command.")

        if isinstance(error, discord.Forbidden):
            return await ctx.reply("I can’t do that (missing permissions).")

        # ---------------- fallback ----------------

        # log error (console)
        print(f"[Ignio][Error] {type(error).__name__}: {error}")

        # simple message to user
        try:
            await ctx.reply("Something went wrong.")
        except Exception:
            pass