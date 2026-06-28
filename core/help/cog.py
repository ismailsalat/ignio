# core/help/cog.py
from __future__ import annotations

import io
import discord
from discord.ext import commands

from core import commands_registry as R
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


def category_embed(cat: str, prefix: str, is_admin: bool, is_owner: bool) -> discord.Embed:
    emoji, label = R.CATEGORIES.get(cat, ("", cat.title()))
    cmds = R.for_category(cat, is_admin=is_admin, is_owner=is_owner)
    e = discord.Embed(title=f"{emoji} {label}", color=ACCENT)
    if not cmds:
        e.description = "Nothing here."
        return e
    lines = []
    for c in cmds:
        usage = c.get("usage") or c["name"]
        tag = " 🛡️" if c.get("admin") or c.get("owner") else ""
        lines.append(f"`{prefix}{usage}`{tag} — {c['desc']}")
    e.description = "\n".join(lines)
    if cat == "admin":
        e.set_footer(text="🛡️ = admin only · everyone can use the rest")
    elif any(c.get("admin") for c in cmds):
        e.set_footer(text="🛡️ = admin only")
    return e


def about_embed(prefix, bot, uptime_str):
    latest = V.latest()
    e = discord.Embed(title="ℹ️ About Ignio",
                      description="A sob-tracking bot with a snitch economy, shop, and profiles.",
                      color=ACCENT)
    e.add_field(name="Version", value=f"v{V.VERSION} — {V.CODENAME}", inline=True)
    e.add_field(name="Released", value=V.RELEASED, inline=True)
    e.add_field(name="Uptime", value=uptime_str, inline=True)
    e.add_field(name="Servers", value=str(len(bot.guilds)), inline=True)
    try:
        ping = round(bot.latency * 1000)
        ping_txt = f"{ping} ms" if ping == ping else "—"
    except (ValueError, TypeError):
        ping_txt = "—"
    e.add_field(name="Ping", value=ping_txt, inline=True)
    e.add_field(name="\u200b", value="\u200b", inline=True)
    notes = "\n".join(f"• {n}" for n in latest.get("notes", [])[:10])
    e.add_field(name=f"Latest — v{latest['version']} ({latest['date']})", value=notes or "—", inline=False)
    return e


class HelpView(discord.ui.View):
    def __init__(self, cog, ctx, is_admin, is_owner):
        super().__init__(timeout=120)
        self.cog = cog
        self.ctx = ctx
        self.prefix = ctx.prefix
        self.is_admin = is_admin
        self.is_owner = is_owner
        for cat in R.visible_categories(is_admin):
            emoji, label = R.CATEGORIES[cat]
            self.add_item(_CatButton(cat, label.split(" ")[0], emoji))

    async def interaction_check(self, interaction):
        if interaction.user.id != self.ctx.author.id:
            await interaction.response.send_message("Run `help` yourself to use this menu.", ephemeral=True)
            return False
        return True


class _CatButton(discord.ui.Button):
    def __init__(self, cat, label, emoji):
        super().__init__(label=label, emoji=emoji, style=discord.ButtonStyle.primary)
        self.cat = cat

    async def callback(self, interaction):
        v = self.view
        if self.cat == "info":
            emb = about_embed(v.prefix, v.cog.bot, v.cog._uptime())
        else:
            emb = category_embed(self.cat, v.prefix, v.is_admin, v.is_owner)
        await interaction.response.edit_message(embed=emb, view=v)


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

    # kept so !sob help can mirror the sobs page
    def _sobs_help(self, p):
        return category_embed("sobs", p, False, False)

    def _overview_image(self, is_admin):
        from core.profile.help_render import make_help_overview
        cats = []
        for cat in R.visible_categories(is_admin):
            emoji, label = R.CATEGORIES[cat]
            count = len(R.for_category(cat, is_admin=is_admin, is_owner=is_admin))
            # short desc per category
            desc = {
                "sobs": "Stats, leaderboard, snitch",
                "profile": "Customize your card",
                "shop": "Buy items & daily sobs",
                "economy": "Rates & conversions",
                "info": "Version & updates",
                "admin": "Server management",
            }.get(cat, "")
            cats.append({"label": label, "desc": desc, "count": count})
        return make_help_overview(cats)

    @commands.command(name="help", aliases=["commands", "cmds"])
    async def help_cmd(self, ctx, section: str | None = None):
        p = ctx.prefix
        is_admin = _is_admin(ctx.author, self.settings)
        is_owner = _is_owner(ctx.author, self.settings)
        section = (section or "").lower().strip()

        # text shortcuts
        alias = {"sob": "sobs", "sobs": "sobs", "profile": "profile", "shop": "shop",
                 "economy": "economy", "eco": "economy", "info": "info", "about": "info"}
        if section in alias:
            cat = alias[section]
            if cat == "info":
                await ctx.reply(embed=about_embed(p, self.bot, self._uptime()))
            else:
                await ctx.reply(embed=category_embed(cat, p, is_admin, is_owner))
            return
        if section == "admin" and is_admin:
            await ctx.reply(embed=category_embed("admin", p, is_admin, is_owner))
            return

        # default: image overview + buttons (with text fallback)
        try:
            img = self._overview_image(is_admin)
            buf = io.BytesIO(); img.save(buf, format="PNG"); buf.seek(0)
            await ctx.reply(file=discord.File(buf, filename="help.png"),
                            view=HelpView(self, ctx, is_admin, is_owner))
            return
        except Exception as e:
            print(f"[Ignio][Help] overview image failed, using embed: {e}")
        # fallback overview embed
        e = discord.Embed(title="Ignio — Help",
                          description="Tap a button to explore each area.", color=ACCENT)
        for cat in R.visible_categories(is_admin):
            emoji, label = R.CATEGORIES[cat]
            n = len(R.for_category(cat, is_admin=is_admin, is_owner=is_owner))
            e.add_field(name=f"{emoji} {label}", value=f"{n} commands · `{p}help {cat}`", inline=True)
        await ctx.reply(embed=e, view=HelpView(self, ctx, is_admin, is_owner))
