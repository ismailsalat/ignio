import discord
from discord.ext import commands

class ErrorHandlerCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_command_error(self, ctx: commands.Context, error: Exception):
        if isinstance(error, commands.CommandNotFound):
            return

        if isinstance(error, commands.MissingRequiredArgument):
            return await ctx.reply(
                f"Missing argument: `{error.param.name}`\n"
                f"Try: `!{ctx.command} {ctx.command.signature}`"
            )

        if isinstance(error, commands.BadArgument):
            return await ctx.reply("Bad argument. Mention a valid user like `@milk`.")

        if isinstance(error, commands.MissingPermissions):
            return await ctx.reply("You don’t have permission to use that command.")

        if isinstance(error, discord.Forbidden):
            return await ctx.reply("I’m missing permissions (Send Messages / Embed Links) in this channel.")

        await ctx.reply(f"Command error: `{type(error).__name__}`")
        raise error
