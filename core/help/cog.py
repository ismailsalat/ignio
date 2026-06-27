# core/help/cog.py
from __future__ import annotations

import discord
from discord.ext import commands

from core import version as V

ACCENT = 0xF0B132


def _is_admin(member, settings) -> bool:
    owner_ids = set(getattr(settings, "owner_ids", ()) or ())
    if member.id in owner_ids:
        return True
    perms = getattr(member, "guild_permissions", None)
    return bool(perms and (perms.administrator or perms.manage_guild))


def _is_owner(member, settings) -> bool:
    return member.id in set(getattr(settings, "owner_ids", ()) or ())


# ======================================================================
# embed builders (also used by !help <section> text fallback)
# ======================================================================

def overview_embed(p, show_admin):
    e = discord.Embed(
        title="😭 Ignio — Help",
        description="A sob-tracking bot with a competitive snitch economy.\n"
                    "Tap a button below to see commands for each area.",
        color=ACCENT,
    )
    e.add_field(name="📊 Sobs & Profile", value=(
        f"`{p}sob` — your profile card · `{p}sob @user` — someone else's\n"
        f"`{p}sob lb` — leaderboard · `{p}ss` — snitch (reply)"
    ), inline=False)
    e.add_field(name="🛒 Shop", value=(
        f"`{p}shop` — browse & buy · `{p}me` — your stuff"
    ), inline=False)
    e.add_field(name="🎴 Profile", value=(
        f"`{p}sob set` · `{p}sob backgrounds` · `{p}sob colors`"
    ), inline=False)
    e.add_field(name="ℹ️ Info", value=(
        f"`{p}about` — bot info & updates · `{p}version`"
    ), inline=False)
    if show_admin:
        e.add_field(name="🛡️ Admin", value="Tap **Admin** below for the full list.", inline=False)
    e.set_footer(text="Buttons time out after 2 minutes — run !help again anytime.")
    return e


def sobs_embed(p):
    e = discord.Embed(title="📊 Sobs & Profile", color=ACCENT)
    e.add_field(name="Stats", value=(
        f"`{p}sob` — your profile card\n"
        f"`{p}sob @user` — another member's card\n"
        f"`{p}sob lb` — server leaderboard"
    ), inline=False)
    e.add_field(name="Snitch", value=(
        f"`{p}ss` — reply to a message to wipe its sobs (needs a token)"
    ), inline=False)
    e.set_footer(text="Tap Profile for card customization")
    return e


def profile_embed(p):
    e = discord.Embed(title="🎴 Profile customization", color=ACCENT)
    e.add_field(name="See what's available", value=(
        f"`{p}sob backgrounds` — all backgrounds (free & premium)\n"
        f"`{p}sob colors` — all colors\n"
        f"`{p}sob set` — your current background & color"
    ), inline=False)
    e.add_field(name="Change it", value=(
        f"`{p}sob set background <name>`\n"
        f"`{p}sob set color <name>`"
    ), inline=False)
    e.set_footer(text="Free backgrounds: sunset, lowpoly, cloud, amber, midnight, sky")
    return e


def shop_embed(p):
    e = discord.Embed(title="🛒 Shop", color=ACCENT)
    e.add_field(name="Browse & buy", value=(
        f"`{p}shop` — open the shop (category buttons)\n"
        f"`{p}buy <item> [qty]` — buy by name or key"
    ), inline=False)
    e.add_field(name="Your stuff", value=(
        f"`{p}me` (`{p}inv`, `{p}effects`) — items + active effects\n"
        f"`{p}use <item> [@user]` — use an item"
    ), inline=False)
    e.add_field(name="Owner / admin (manageshop)", value=(
        f"`{p}shop additem <key> <price> <name>`\n"
        f"`{p}shop setstock <key> <n>` · `{p}shop removeitem <key>`\n"
        f"`{p}shop setchannel #channel` · `{p}shop setrole @role`\n"
        f"`{p}shop boostmult <n>`"
    ), inline=False)
    return e


def admin_embed(p, is_owner):
    e = discord.Embed(title="🛡️ Admin", color=ACCENT)
    e.add_field(name="Profile", value=f"`{p}admin profile on|off` — toggle image cards", inline=False)
    e.add_field(name="Sobs & tokens", value=(
        f"`{p}admin givesob @user <n>` (`gs`) · `{p}admin givetoken @user <n>` (`gt`)\n"
        f"`{p}admin reset @user` · `{p}admin recount` · `{p}admin threshold <n>`"
    ), inline=False)
    e.add_field(name="Emojis", value=(
        f"`{p}admin emoji list` · `{p}admin emoji add <name>` · `{p}admin emoji remove <name>`"
    ), inline=False)
    e.add_field(name="Command control", value=(
        f"`{p}disable <category|command> [#channel]`\n"
        f"`{p}enable <category|command> [#channel]`\n"
        f"`{p}commandconfig` — what's disabled where\n"
        f"Categories: sobs, shop, profile"
    ), inline=False)
    e.add_field(name="Permissions & announce", value=(
        f"`{p}perms` · `{p}perms grant @role <perm>` · `{p}perms revoke @role <perm>`\n"
        f"`{p}announce #channel Title | Body`"
    ), inline=False)
    if is_owner:
        e.add_field(name="Owner only", value=(
            f"`{p}admin stats` · `{p}admin servers` · `{p}admin config`\n"
            f"`{p}admin export` · `{p}admin import` · `{p}admin whoami`"
        ), inline=False)
    return e


def about_embed(p, bot, uptime_str):
    latest = V.latest()
    e = discord.Embed(title="😭 About Ignio",
                      description="A sob-tracking bot with a competitive snitch economy, shop, and profiles.",
                      color=ACCENT)
    e.add_field(name="Version", value=f"v{V.VERSION} — {V.CODENAME}", inline=True)
    e.add_field(name="Released", value=V.RELEASED, inline=True)
    e.add_field(name="Uptime", value=uptime_str, inline=True)
    e.add_field(name="Servers", value=str(len(bot.guilds)), inline=True)
    try:
        ping = round(bot.latency * 1000)
        ping_txt = f"{ping} ms" if ping == ping else "—"  # NaN check
    except (ValueError, TypeError):
        ping_txt = "—"
    e.add_field(name="Ping", value=ping_txt, inline=True)
    e.add_field(name="\u200b", value="\u200b", inline=True)
    notes = "\n".join(f"• {n}" for n in latest.get("notes", [])[:10])
    e.add_field(name=f"🆕 v{latest['version']} ({latest['date']})", value=notes or "—", inline=False)
    return e


# ======================================================================
# interactive view
# ======================================================================

class HelpView(discord.ui.View):
    def __init__(self, cog, ctx, show_admin):
        super().__init__(timeout=120)
        self.cog = cog
        self.ctx = ctx
        self.p = ctx.prefix
        self.add_item(_NavButton("Sobs", "📊", "sobs"))
        self.add_item(_NavButton("Profile", "🎴", "profile"))
        self.add_item(_NavButton("Shop", "🛒", "shop"))
        self.add_item(_NavButton("About", "ℹ️", "about"))
        if show_admin:
            self.add_item(_NavButton("Admin", "🛡️", "admin"))
        self.add_item(_NavButton("Home", "🏠", "home", style=discord.ButtonStyle.secondary))

    async def interaction_check(self, interaction):
        if interaction.user.id != self.ctx.author.id:
            await interaction.response.send_message("Run `!help` yourself to use this menu.", ephemeral=True)
            return False
        return True


class _NavButton(discord.ui.Button):
    def __init__(self, label, emoji, key, style=discord.ButtonStyle.primary):
        super().__init__(label=label, emoji=emoji, style=style)
        self.key = key

    async def callback(self, interaction):
        v = self.view
        cog = v.cog
        p = v.p
        show_admin = _is_admin(v.ctx.author, cog.settings)
        is_owner = _is_owner(v.ctx.author, cog.settings)
        if self.key == "home":
            emb = overview_embed(p, show_admin)
        elif self.key == "sobs":
            emb = sobs_embed(p)
        elif self.key == "profile":
            emb = profile_embed(p)
        elif self.key == "shop":
            emb = shop_embed(p)
        elif self.key == "admin":
            emb = admin_embed(p, is_owner)
        elif self.key == "about":
            emb = about_embed(p, cog.bot, cog._uptime())
        else:
            emb = overview_embed(p, show_admin)
        await interaction.response.edit_message(embed=emb, view=v)


# ======================================================================
# cog
# ======================================================================

class HelpCog(commands.Cog):
    def __init__(self, bot: commands.Bot, settings):
        self.bot = bot
        self.settings = settings
        bot.remove_command("help")

    def _uptime(self):
        about = self.bot.get_cog("AboutCog")
        if about is not None:
            import time
            from core.about_cog import _fmt_uptime
            return _fmt_uptime(int(time.time() - about.start_time))
        return "—"

    # kept so !sob help can mirror this
    def _sobs_help(self, p):
        return sobs_embed(p)

    @commands.command(name="help", aliases=["commands", "cmds"])
    async def help_cmd(self, ctx: commands.Context, section: str | None = None):
        p = ctx.prefix
        show_admin = _is_admin(ctx.author, self.settings)
        is_owner = _is_owner(ctx.author, self.settings)
        section = (section or "").lower().strip()

        # text shortcuts still work
        if section in ("shop",):
            await ctx.reply(embed=shop_embed(p)); return
        if section in ("sob", "sobs"):
            await ctx.reply(embed=sobs_embed(p)); return
        if section in ("profile",):
            await ctx.reply(embed=profile_embed(p)); return
        if section in ("about", "info"):
            await ctx.reply(embed=about_embed(p, self.bot, self._uptime())); return
        if section in ("admin",) and show_admin:
            await ctx.reply(embed=admin_embed(p, is_owner)); return

        # default: overview WITH buttons
        await ctx.reply(embed=overview_embed(p, show_admin), view=HelpView(self, ctx, show_admin))
