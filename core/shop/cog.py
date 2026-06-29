# core/shop/cog.py
from __future__ import annotations

import discord
from discord.ext import commands

from core.shop import embeds
from core.shop.catalog import (
    BUILTIN_ITEMS, CATEGORIES, TARGETED_EFFECTS, item_icon,
)
from core.time_utils import now_ts


def _dur_text(seconds: int) -> str:
    """Human duration like '5 minutes' / '30 minutes' / '1 hour'. Always matches
    the real effect length so messages can never be wrong again."""
    if not seconds:
        return "a while"
    m = seconds // 60
    if m < 60:
        return f"{m} minute" + ("s" if m != 1 else "")
    h = m // 60
    return f"{h} hour" + ("s" if h != 1 else "")


def _is_admin(ctx: commands.Context, settings) -> bool:
    owner_ids = set(getattr(settings, "owner_ids", ()) or ())
    if ctx.author.id in owner_ids:
        return True
    perms = getattr(ctx.author, "guild_permissions", None)
    return bool(perms and (perms.administrator or perms.manage_guild))


# ======================================================================
# shared action helpers (used by both text commands and buttons)
# ======================================================================

def _grouped_from_catalog(catalog, only_category=None):
    """Turn the catalog into {category: [ {key,name,price,stackable} ]} for the
    picture renderer."""
    from core.shop.catalog import BUILTIN_ITEMS
    order = [only_category] if only_category else ["protection", "debuff", "buff", "server"]
    grouped = {}
    for cat in order:
        items = []
        for c in catalog:
            if c["category"] == cat and c["enabled"]:
                base = BUILTIN_ITEMS.get(c["key"], {})
                items.append({
                    "key": c["key"],
                    "name": c["name"],
                    "price": c.get("_final_price", c["price"]),
                    "stackable": bool(base.get("stackable")),
                })
        if items:
            grouped[cat] = items
    return grouped


def _shop_picture(balance, catalog, only_category=None):
    """Render the shop as a Discord file, or None if it fails (embed fallback)."""
    try:
        from core.profile.shop_render import make_shop_card
        import io
        grouped = _grouped_from_catalog(catalog, only_category)
        if not grouped:
            return None
        img = make_shop_card(balance, grouped, only_category=only_category)
        buf = io.BytesIO(); img.save(buf, format="PNG"); buf.seek(0)
        return discord.File(buf, filename="shop.png")
    except Exception as e:
        print(f"[Ignio][Shop] picture render failed, using embed: {e}")
        return None


async def do_buy(shop, sob_repo, guild_id, user_id, item_key, qty=1):
    return await shop.buy(guild_id, user_id, item_key.lower(), qty)


async def do_use(shop, guild_id, user, item_key, target=None, amount=1, economy=None):
    """Returns (ok, embed). Handles built-in + custom (claim) items.
    item_key may be a key or a display name. `amount` is used for stackable
    items like the per-second Shield."""
    resolved = await shop.get_item(guild_id, item_key)
    key = resolved["key"] if resolved else item_key.lower()
    inv = await shop.get_inventory(guild_id, user.id)
    owned = inv.get(key, 0)
    if owned < 1:
        return False, embeds.error_embed(f"You don't own a `{key}`.")

    builtin = BUILTIN_ITEMS.get(key)
    db = await shop._db()

    # custom server item -> claim
    if builtin is None:
        await shop._take_from_inventory(db, guild_id, user.id, key, 1, now_ts())
        await db.commit()
        catalog = await shop.get_catalog(guild_id)
        it = next((c for c in catalog if c["key"] == key), {"name": key, "icon": "🎁", "key": key})
        return "claim", it

    effect_key = builtin["effect_key"]
    duration = builtin.get("duration", 0)
    mechanic = builtin.get("mechanic", "")
    is_targeted = key in TARGETED_EFFECTS
    eco = economy if economy is not None else getattr(shop, "economy", None)

    # jailed? can't use items
    if await shop.has_effect(guild_id, user.id, "jail"):
        return False, embeds.error_embed("You're jailed — you can't use items right now.")

    # ---- AUDIT (basic + heist): instant steal, blockable, crit, daily cap ----
    if mechanic in ("audit_basic", "audit_heist"):
        if target is None:
            return False, embeds.error_embed(f"`{key}` needs a target. Use `!use {key} @user`.")
        if target.id == user.id:
            return False, embeds.error_embed("You can't audit yourself.")
        if getattr(target, "bot", False):
            return False, embeds.error_embed("You can't target a bot.")
        if eco is None:
            return False, embeds.error_embed("Audits aren't available right now.")

        import random
        from core.economy import AUDIT_BASIC_PCT, AUDIT_HEIST_PCT, AUDIT_HEIST_CRIT

        tgt_stats = await shop.sob_repo.get_user_stats(guild_id, target.id)
        tgt_bal = int(tgt_stats["sobs_alltime"])

        # daily anti-gang-up immunity
        if await eco.is_audit_immune(guild_id, target.id, tgt_bal):
            return False, embeds.error_embed(
                f"{target.mention} has already been audited heavily today — they're protected until tomorrow.")

        is_heist = mechanic == "audit_heist"
        pct = AUDIT_HEIST_PCT if is_heist else AUDIT_BASIC_PCT

        # shield / ward check
        crit = False
        blocked = False
        if is_heist:
            # heist: 20% crit pierces & breaks a shield; otherwise blocked by shield
            if await shop.has_effect(guild_id, target.id, "shield"):
                if random.random() < AUDIT_HEIST_CRIT:
                    crit = True
                    await shop.clear_effect(guild_id, target.id, "shield")
                else:
                    blocked = True
        else:
            # basic: blocked by a shield OR an audit ward
            if await shop.has_effect(guild_id, target.id, "shield") or \
               await shop.has_effect(guild_id, target.id, "audit_ward"):
                blocked = True

        if blocked:
            await shop._take_from_inventory(db, guild_id, user.id, key, 1, now_ts())
            await db.commit()
            return True, embeds.error_embed(
                f"🛡️ {target.mention}'s shield blocked your {builtin['name']}! (item consumed)")

        # daily cap: don't let one audit exceed remaining immunity room
        already = await eco.audit_loss_today(guild_id, target.id)
        from core.economy import AUDIT_DAILY_IMMUNE_PCT
        day_cap = int((tgt_bal + already) * AUDIT_DAILY_IMMUNE_PCT)
        room = max(0, day_cap - already)
        steal = min(int(tgt_bal * pct), room if room > 0 else int(tgt_bal * pct), tgt_bal)
        if steal <= 0:
            return False, embeds.error_embed(f"{target.mention} is protected from more audits today.")

        await shop._take_from_inventory(db, guild_id, user.id, key, 1, now_ts())
        await db.commit()
        await shop.sob_repo.adjust_received(guild_id, target.id, -steal)
        await shop.sob_repo.adjust_received(guild_id, user.id, +steal)
        await eco.log_audit(guild_id, user.id, target.id, steal)

        extra = " 💥 **CRIT — smashed their shield!**" if crit else ""
        return True, embeds.used_embed(
            f"{builtin['icon']} {builtin['name']}",
            f"{user.mention} audited {target.mention} and seized **{steal:,} sobs**!{extra}")

    # ---- targeted, duration-based debuffs (freeze, slow, marked, jail) ----
    if is_targeted:
        if target is None:
            return False, embeds.error_embed(f"`{key}` needs a target. Use `!use {key} @user`.")
        if target.id == user.id:
            return False, embeds.error_embed("You can't target yourself.")
        if getattr(target, "bot", False):
            return False, embeds.error_embed("You can't target a bot.")
        if effect_key and await shop.has_effect(guild_id, target.id, effect_key):
            return False, embeds.error_embed(f"{target.mention} already has that effect active.")
        await shop._take_from_inventory(db, guild_id, user.id, key, 1, now_ts())
        await db.commit()
        await shop.add_effect(guild_id, target.id, effect_key, source_user_id=user.id, expires_at=now_ts() + duration)
        verbs = {
            "block_tokens": f"froze {target.mention} — no snitching",
            "halve_earnings": f"cursed {target.mention} — half sob earnings",
            "mark_bounty": f"marked {target.mention} — snitching them pays more",
            "lock_items": f"jailed {target.mention} — no items",
        }
        return True, embeds.used_embed(
            f"{builtin['icon']} {builtin['name']} used",
            f"{user.mention} {verbs.get(mechanic, f'hit {target.mention}')} for {_dur_text(duration)}.")

    # ---- STACKABLE shield: !use shield <seconds> ----
    if builtin.get("stackable"):
        secs = max(1, int(amount))
        if secs > owned:
            return False, embeds.error_embed(
                f"You only have **{owned}** {builtin['name']} units. Buy more or use fewer.")
        await shop._take_from_inventory(db, guild_id, user.id, key, secs, now_ts())
        # extend existing shield if active, else start fresh
        cur_exp = await shop.effect_expiry(guild_id, user.id, effect_key)
        base = max(cur_exp, now_ts())
        await shop.add_effect(guild_id, user.id, effect_key, source_user_id=user.id, expires_at=base + secs)
        await db.commit()
        return True, embeds.used_embed(
            f"{builtin['icon']} {builtin['name']} active",
            f"You're protected from snitches for **{_dur_text(secs)}** ({secs} units used).")

    # ---- self effects (guardian, reflect, boosts, buffs) ----
    if effect_key and await shop.has_effect(guild_id, user.id, effect_key):
        return False, embeds.error_embed("You already have that effect active.")
    await shop._take_from_inventory(db, guild_id, user.id, key, 1, now_ts())
    await db.commit()
    expires_at = now_ts() + duration if duration else 0
    await shop.add_effect(guild_id, user.id, effect_key, source_user_id=user.id, expires_at=expires_at)
    if mechanic in ("block_snitch", "block_charges"):
        msg = "You're protected from snitches"
    elif mechanic == "reflect_next":
        msg = "Your next attacker gets reflected"
    elif mechanic == "earn_bonus":
        msg = "Your sob earnings are boosted"
    else:
        msg = "Your snitches are boosted"
    tail = f" for {_dur_text(duration)}." if duration else "."
    return True, embeds.used_embed(f"{builtin['icon']} {builtin['name']} active", f"{msg}{tail}")


# ======================================================================
# interactive views
# ======================================================================

class ShopView(discord.ui.View):
    """Top level: one button per category, plus My stuff."""

    def __init__(self, cog, ctx, catalog):
        super().__init__(timeout=180)
        self.cog = cog
        self.ctx = ctx
        self.catalog = catalog
        # a button per category that actually has enabled items (server always shown)
        for cat_key, (icon, label) in CATEGORIES.items():
            has_items = any(c["category"] == cat_key and c["enabled"] for c in catalog)
            if has_items or cat_key == "server":
                self.add_item(CategoryButton(cat_key, icon, label, disabled=not has_items))
        self.add_item(MyStuffButton())

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.ctx.author.id:
            await interaction.response.send_message("This menu isn't yours — run `!shop` yourself.", ephemeral=True)
            return False
        return True


class CategoryButton(discord.ui.Button):
    def __init__(self, cat_key, icon, label, disabled=False):
        super().__init__(
            label=label,
            emoji=icon if len(icon) <= 2 else None,
            style=discord.ButtonStyle.secondary,
            disabled=disabled,
        )
        self.cat_key = cat_key

    async def callback(self, interaction: discord.Interaction):
        view = self.view
        items = [c for c in view.catalog if c["category"] == self.cat_key and c["enabled"]]
        cat_view = CategoryView(view.cog, view.ctx, view.catalog, self.cat_key, items)
        stats = await view.cog.sob_repo.get_user_stats(interaction.guild.id, interaction.user.id)
        bal = stats["sobs_alltime"]
        pic = _shop_picture(bal, view.catalog, only_category=self.cat_key)
        if pic is not None:
            await interaction.response.edit_message(
                attachments=[pic], embed=None, view=cat_view)
        else:
            await interaction.response.edit_message(
                embed=embeds.category_embed(self.cat_key, items), attachments=[], view=cat_view)


class CategoryView(discord.ui.View):
    """Inside a category: a buy button per item + Back."""

    def __init__(self, cog, ctx, catalog, cat_key, items):
        super().__init__(timeout=180)
        self.cog = cog
        self.ctx = ctx
        self.catalog = catalog
        for item in items[:23]:  # leave room for Back
            self.add_item(BuyButton(item))
        self.add_item(BackButton())

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.ctx.author.id:
            await interaction.response.send_message("This menu isn't yours — run `!shop` yourself.", ephemeral=True)
            return False
        return True


class BackButton(discord.ui.Button):
    def __init__(self):
        super().__init__(label="Back", emoji="◀️", style=discord.ButtonStyle.secondary, row=4)

    async def callback(self, interaction: discord.Interaction):
        view = self.view
        stats = await view.cog.sob_repo.get_user_stats(interaction.guild.id, interaction.user.id)
        bal = stats["sobs_alltime"]
        top = ShopView(view.cog, view.ctx, view.catalog)
        pic = _shop_picture(bal, view.catalog)
        if pic is not None:
            await interaction.response.edit_message(attachments=[pic], embed=None, view=top)
        else:
            await interaction.response.edit_message(
                embed=embeds.shop_embed(interaction.guild.name, view.catalog, bal),
                attachments=[], view=top)


def _bulk_presets(item):
    """Time presets for a duration/stackable item -> list of (label, qty).
    For a per-second shield, qty = seconds. For fixed-duration items, qty = count."""
    from core.shop.catalog import BUILTIN_ITEMS
    base = BUILTIN_ITEMS.get(item.get("key"), {})
    if base.get("stackable"):
        # per-second item: presets are seconds
        return [("1 min", 60), ("5 min", 300), ("15 min", 900), ("30 min", 1800)]
    dur = base.get("duration", 0)
    if dur and dur > 0:
        # fixed-duration item: presets are multiples (stack several uses)
        return [("×1", 1), ("×3", 3), ("×5", 5), ("×10", 10)]
    return None


class _BulkBuyButton(discord.ui.Button):
    def __init__(self, label, qty, item_key, unit_price):
        cost = qty * unit_price
        super().__init__(label=f"{label} ({cost:,})", style=discord.ButtonStyle.success)
        self.qty = qty
        self.item_key = item_key

    async def callback(self, interaction):
        cog = self.view.cog
        ok, reason, item = await do_buy(cog.shop, cog.sob_repo, interaction.guild.id,
                                        interaction.user.id, self.item_key, self.qty)
        if not ok:
            msgs = {"no_item": "That item doesn't exist.", "disabled": "That item is disabled.",
                    "out_of_stock": "Out of stock.", "not_enough_sobs": "Not enough sobs."}
            if reason == "not_enough_sobs" and item is not None:
                final = item.get("_final_price", item["price"]) * self.qty
                bal = (await cog.sob_repo.get_user_stats(interaction.guild.id, interaction.user.id))["sobs_alltime"]
                await interaction.response.send_message(
                    embed=embeds.error_embed(f"You need **{final:,}** sobs but have **{bal:,}**."), ephemeral=True)
                return
            await interaction.response.send_message(
                embed=embeds.error_embed(msgs.get(reason, "Couldn't buy that.")), ephemeral=True)
            return
        stats = await cog.sob_repo.get_user_stats(interaction.guild.id, interaction.user.id)
        await interaction.response.send_message(
            embed=embeds.buy_success_embed(interaction.user, item, self.qty, stats["sobs_alltime"]),
            ephemeral=True,
        )


class BulkBuyView(discord.ui.View):
    def __init__(self, cog, item, presets):
        super().__init__(timeout=60)
        self.cog = cog
        unit = item.get("_final_price", item["price"])
        for label, qty in presets:
            self.add_item(_BulkBuyButton(label, qty, item["key"], unit))


class BuyButton(discord.ui.Button):
    def __init__(self, item):
        super().__init__(
            label=f"{item['name']} ({item['price']})",
            emoji=item["icon"] if len(item["icon"]) <= 2 else None,
            style=discord.ButtonStyle.success,
        )
        self.item_key = item["key"]
        self.item = item

    async def callback(self, interaction: discord.Interaction):
        cog = self.view.cog
        presets = _bulk_presets(self.item)
        # duration/stackable item -> show bulk time presets instead of buying 1
        if presets:
            from core.shop.catalog import BUILTIN_ITEMS
            base = BUILTIN_ITEMS.get(self.item_key, {})
            kind = "seconds of protection" if base.get("stackable") else "uses"
            e = discord.Embed(
                title=f"{self.item['icon']} {self.item['name']}",
                description=f"How much do you want? Pick an amount below.\nUnit price: `{self.item.get('_final_price', self.item['price'])}` sobs.",
                color=embeds.ACCENT,
            )
            await interaction.response.send_message(
                embed=e, view=BulkBuyView(cog, self.item, presets), ephemeral=True)
            return
        # normal one-shot item
        ok, reason, item = await do_buy(cog.shop, cog.sob_repo, interaction.guild.id, interaction.user.id, self.item_key)
        if not ok:
            msgs = {
                "no_item": "That item doesn't exist.",
                "disabled": "That item is disabled.",
                "out_of_stock": "Out of stock.",
                "not_enough_sobs": "Not enough sobs.",
            }
            await interaction.response.send_message(embed=embeds.error_embed(msgs.get(reason, "Couldn't buy that.")), ephemeral=True)
            return
        stats = await cog.sob_repo.get_user_stats(interaction.guild.id, interaction.user.id)
        await interaction.response.send_message(
            embed=embeds.buy_success_embed(interaction.user, item, 1, stats["sobs_alltime"]),
            ephemeral=True,
        )


class MyStuffButton(discord.ui.Button):
    def __init__(self):
        super().__init__(label="My stuff", emoji="🎒", style=discord.ButtonStyle.primary)

    async def callback(self, interaction: discord.Interaction):
        cog = self.view.cog
        gid = interaction.guild.id
        inv = await cog.shop.get_inventory(gid, interaction.user.id)
        effs = await cog.shop.get_effects(gid, interaction.user.id)
        catalog = await cog.shop.get_catalog(gid)
        kwargs = dict(
            embed=embeds.my_stuff_embed(interaction.user, inv, effs, catalog),
            ephemeral=True,
        )
        if inv:  # only attach a view when there are items to show Use buttons for
            kwargs["view"] = MyStuffView(cog, interaction.user, inv)
        await interaction.response.send_message(**kwargs)


class MyStuffView(discord.ui.View):
    """Use buttons for each owned item."""

    def __init__(self, cog, user, inventory):
        super().__init__(timeout=120)
        self.cog = cog
        self.user = user
        for key, qty in list(inventory.items())[:20]:
            if qty > 0:
                self.add_item(UseButton(cog, key))


class UseButton(discord.ui.Button):
    def __init__(self, cog, item_key):
        builtin = BUILTIN_ITEMS.get(item_key)
        label = builtin["name"] if builtin else item_key
        icon = item_icon(item_key)
        super().__init__(label=f"Use {label}", emoji=icon if len(icon) <= 2 else None, style=discord.ButtonStyle.success)
        self.cog = cog
        self.item_key = item_key

    async def callback(self, interaction: discord.Interaction):
        builtin = BUILTIN_ITEMS.get(self.item_key)
        # targeted items can't be used from a button (need a target) -> tell them
        if builtin and builtin["effect_key"] in TARGETED_EFFECTS:
            await interaction.response.send_message(
                embed=embeds.error_embed(f"Use `!use {self.item_key} @user` to target someone."),
                ephemeral=True,
            )
            return
        # custom server items need channel/DM notification logic -> route to text command
        if builtin is None:
            await interaction.response.send_message(
                embed=embeds.error_embed(f"To claim this item, use `!use {self.item_key}` in a channel."),
                ephemeral=True,
            )
            return
        result, emb = await do_use(self.cog.shop, interaction.guild.id, interaction.user, self.item_key)
        await interaction.response.send_message(embed=emb, ephemeral=True)


# ======================================================================
# cog
# ======================================================================

class ShopCog(commands.Cog):
    def __init__(self, bot: commands.Bot, settings, shop_repo, sob_repo, economy=None):
        self.bot = bot
        self.settings = settings
        self.shop = shop_repo
        self.sob_repo = sob_repo
        self.economy = economy

    async def _can_manage(self, ctx) -> bool:
        from core import perms as _perms
        return await _perms.member_has_perm(self.sob_repo, ctx.author, self.settings, "manageshop")

    # ---- shop browse (with buttons) ----

    @commands.group(name="shop", aliases=["store"], invoke_without_command=True)
    @commands.guild_only()
    async def shop_group(self, ctx: commands.Context):
        catalog = await self.shop.get_catalog(ctx.guild.id)
        stats = await self.sob_repo.get_user_stats(ctx.guild.id, ctx.author.id)
        bal = stats["sobs_alltime"]
        view = ShopView(self, ctx, catalog)
        pic = _shop_picture(bal, catalog)
        if pic is not None:
            await ctx.reply(file=pic, view=view)
        else:
            await ctx.reply(embed=embeds.shop_embed(ctx.guild.name, catalog, bal), view=view)

    # ---- buy (text, forgiving) ----

    @commands.command(name="buy")
    @commands.guild_only()
    async def buy_cmd(self, ctx: commands.Context, *, args: str | None = None):
        await self._handle_buy(ctx, args)

    @shop_group.command(name="buy")
    @commands.guild_only()
    async def shop_buy(self, ctx: commands.Context, *, args: str | None = None):
        await self._handle_buy(ctx, args)

    async def _handle_buy(self, ctx, args):
        if not args or not args.strip():
            await ctx.reply(embed=embeds.error_embed(f"What do you want to buy? Try `{ctx.prefix}shop` to see items."))
            return
        # Allow "Basic Shield" or "shield" optionally followed by a quantity:
        # "shield 3", "basic shield 2". Pull a trailing integer as qty if present.
        parts = args.strip().split()
        n = 1
        if len(parts) > 1 and parts[-1].isdigit():
            n = max(1, int(parts[-1]))
            name = " ".join(parts[:-1])
        else:
            name = args.strip()

        ok, reason, item = await do_buy(self.shop, self.sob_repo, ctx.guild.id, ctx.author.id, name, n)
        if not ok:
            if reason == "not_enough_sobs" and item is not None:
                final = item.get("_final_price", item["price"])
                bal = (await self.sob_repo.get_user_stats(ctx.guild.id, ctx.author.id))["sobs_alltime"]
                extra = ""
                if final != item["price"]:
                    extra = f" ({item['price']} + tax)"
                await ctx.reply(embed=embeds.error_embed(
                    f"You need **{final}** sobs{extra} but have **{bal}**."))
                return
            msgs = {
                "no_item": f"No item called `{name}`. Try `{ctx.prefix}shop` to see what's available.",
                "disabled": "That item is disabled right now.",
                "out_of_stock": "That item is out of stock.",
                "not_enough_sobs": "You don't have enough sobs for that.",
            }
            await ctx.reply(embed=embeds.error_embed(msgs.get(reason, "Couldn't buy that.")))
            return
        stats = await self.sob_repo.get_user_stats(ctx.guild.id, ctx.author.id)
        await ctx.reply(embed=embeds.buy_success_embed(ctx.author, item, n, stats["sobs_alltime"]))

    # ---- my stuff: inventory + effects merged ----

    @commands.command(name="me", aliases=["inventory", "inv", "effects", "mystuff"])
    @commands.guild_only()
    async def me_cmd(self, ctx: commands.Context, member: discord.Member | None = None):
        member = member or ctx.author
        inv = await self.shop.get_inventory(ctx.guild.id, member.id)
        effs = await self.shop.get_effects(ctx.guild.id, member.id)
        catalog = await self.shop.get_catalog(ctx.guild.id)
        kwargs = {"embed": embeds.my_stuff_embed(member, inv, effs, catalog)}
        if member.id == ctx.author.id and inv:
            kwargs["view"] = MyStuffView(self, member, inv)
        await ctx.reply(**kwargs)

    # ---- use (text) ----

    @commands.command(name="use")
    @commands.guild_only()
    async def use_cmd(self, ctx: commands.Context, *, args: str | None = None):
        if not args or not args.strip():
            await ctx.reply(embed=embeds.error_embed(f"What do you want to use? Check `{ctx.prefix}me`."))
            return

        # A trailing mention is the target; the rest is the item name.
        target = ctx.message.mentions[0] if ctx.message.mentions else None
        name = args
        if target is not None:
            for token in (f"<@{target.id}>", f"<@!{target.id}>"):
                name = name.replace(token, "")
        name = name.strip()

        # A trailing number is an amount (e.g. "shield 300" -> 300 seconds).
        amount = 1
        parts = name.rsplit(" ", 1)
        if len(parts) == 2 and parts[1].isdigit():
            amount = int(parts[1])
            name = parts[0].strip()

        if not name:
            await ctx.reply(embed=embeds.error_embed(f"Which item? e.g. `{ctx.prefix}use shield 300`."))
            return

        item = await self.shop.get_item(ctx.guild.id, name)
        key = item["key"] if item else name
        result, emb = await do_use(self.shop, ctx.guild.id, ctx.author, key, target,
                                   amount=amount, economy=self.economy)

        # custom server item claim -> notify channel/role or DM the buyer
        if result == "claim":
            await self._handle_claim(ctx, emb)  # emb is actually the item dict here
            return

        await ctx.reply(embed=emb)

    async def _handle_claim(self, ctx, item: dict):
        import datetime
        when = datetime.datetime.now(datetime.timezone.utc).strftime("%b %d, %Y · %H:%M UTC")
        icon = item.get("icon", "🎁")
        iname = item.get("name", item.get("key", "item"))

        chan_id = await self.shop.sob_repo.get_guild_setting(ctx.guild.id, "fulfillment_channel_id")
        role_id = await self.shop.sob_repo.get_guild_setting(ctx.guild.id, "fulfillment_role_id")

        # build the small horizontal claim embed
        claim = discord.Embed(color=embeds.ACCENT)
        claim.description = f"{icon} **{iname}** · {ctx.author.mention} · `{when}`"
        claim.set_author(name="Item claim")

        channel = None
        if chan_id:
            try:
                channel = ctx.guild.get_channel(int(chan_id))
            except (ValueError, TypeError):
                channel = None

        if channel is not None:
            ping = ""
            if role_id:
                ping = f"<@&{role_id}> "
            try:
                await channel.send(
                    content=f"{ping}new claim",
                    embed=claim,
                    allowed_mentions=discord.AllowedMentions(roles=True),
                )
                await ctx.reply(embed=embeds.used_embed("Claim submitted", f"Your claim for **{iname}** was sent to the team. They'll deliver it soon."))
                return
            except discord.Forbidden:
                pass  # fall through to DM if we can't post there

        # no channel (or failed) -> DM the buyer
        try:
            await ctx.author.send(
                embed=embeds.used_embed(
                    "Claim submitted",
                    f"You claimed **{icon} {iname}** in **{ctx.guild.name}**.\nPlease contact a server admin to receive it.",
                )
            )
            await ctx.reply(embed=embeds.used_embed("Claim submitted", "Check your DMs — contact an admin to receive your item."))
        except discord.Forbidden:
            # DMs closed -> just reply in channel
            await ctx.reply(embed=embeds.used_embed(
                "Claim submitted",
                f"{ctx.author.mention} claimed **{icon} {iname}** — please contact an admin to receive it.",
            ))

    # ---- help ----

    @shop_group.command(name="help")
    @commands.guild_only()
    async def shop_help(self, ctx: commands.Context):
        p = ctx.prefix
        e = discord.Embed(title="🛒 Sob Shop — Help", color=embeds.ACCENT)
        e.add_field(name="The easy way", value=(
            f"`{p}shop` — open the shop and **tap buttons** to buy & use"
        ), inline=False)
        e.add_field(name="Text commands", value=(
            f"`{p}buy <item>` — buy something\n"
            f"`{p}me` — your items + active effects (with Use buttons)\n"
            f"`{p}use <item> [@user]` — use an item"
        ), inline=False)
        e.add_field(name="Server owners", value=(
            f"`{p}shop additem <key> <price> <name>` — add a Server Item\n"
            f"`{p}shop setstock <key> <n>` · `{p}shop removeitem <key>`\n"
            f"`{p}shop setchannel #channel` — where claims are posted\n"
            f"`{p}shop setrole @role` — who gets pinged on a claim\n"
            f"`{p}shop boostmult <n>` — set boost multiplier"
        ), inline=False)
        await ctx.reply(embed=e)

    # ---- owner item management ----

    @shop_group.command(name="boostmult", aliases=["boostmultiplier"])
    @commands.guild_only()
    async def shop_boostmult(self, ctx: commands.Context, value: float | None = None):
        if value is None:
            current = await self.shop.get_boost_multiplier(ctx.guild.id)
            await ctx.reply(embed=embeds.used_embed("Boost multiplier", f"Currently **{current}×**.\nSet with `{ctx.prefix}shop boostmult <number>`."))
            return
        if not await self._can_manage(ctx):
            await ctx.reply(embed=embeds.error_embed("Only server admins can change the boost multiplier."))
            return
        if value < 1:
            await ctx.reply(embed=embeds.error_embed("Multiplier must be at least 1."))
            return
        new = await self.shop.set_boost_multiplier(ctx.guild.id, value)
        await ctx.reply(embed=embeds.used_embed("Boost multiplier updated", f"Boosted snitches now drain **{new}×** the message's sobs."))

    @shop_group.command(name="setchannel")
    @commands.guild_only()
    async def shop_setchannel(self, ctx: commands.Context, channel: discord.TextChannel | None = None):
        if not await self._can_manage(ctx):
            await ctx.reply(embed=embeds.error_embed("Only server admins can set the claim channel."))
            return
        if channel is None:
            # clear it
            await self.shop.sob_repo.set_guild_setting(ctx.guild.id, "fulfillment_channel_id", "")
            await ctx.reply(embed=embeds.used_embed("Claim channel cleared", "Server-item claims will now DM the buyer instead."))
            return
        await self.shop.sob_repo.set_guild_setting(ctx.guild.id, "fulfillment_channel_id", str(channel.id))
        await ctx.reply(embed=embeds.used_embed("Claim channel set", f"Server-item claims will post in {channel.mention}."))

    @shop_group.command(name="setrole")
    @commands.guild_only()
    async def shop_setrole(self, ctx: commands.Context, role: discord.Role | None = None):
        if not await self._can_manage(ctx):
            await ctx.reply(embed=embeds.error_embed("Only server admins can set the claim role."))
            return
        if role is None:
            await self.shop.sob_repo.set_guild_setting(ctx.guild.id, "fulfillment_role_id", "")
            await ctx.reply(embed=embeds.used_embed("Claim role cleared", "Claims will no longer ping a role."))
            return
        await self.shop.sob_repo.set_guild_setting(ctx.guild.id, "fulfillment_role_id", str(role.id))
        await ctx.reply(embed=embeds.used_embed("Claim role set", f"Claims will ping {role.mention}."))

    @shop_group.command(name="additem")
    @commands.guild_only()
    async def shop_additem(self, ctx: commands.Context, key: str, price: str, *, name: str):
        if not await self._can_manage(ctx):
            await ctx.reply(embed=embeds.error_embed("Only server admins can add items."))
            return
        if key.lower() in BUILTIN_ITEMS:
            await ctx.reply(embed=embeds.error_embed("That key is reserved by a built-in item."))
            return

        # Price can be a plain sob number ("250000") OR a dollar value ("$10"),
        # which the bot auto-converts using this server's exchange rate.
        price_str = price.strip()
        converted_note = ""
        if price_str.startswith("$"):
            if self.economy is None:
                await ctx.reply(embed=embeds.error_embed("Dollar pricing isn't available right now — use a sob number."))
                return
            try:
                usd = float(price_str[1:])
            except ValueError:
                await ctx.reply(embed=embeds.error_embed("Bad dollar amount. Try `$10`."))
                return
            sob_price = await self.economy.usd_to_sobs(ctx.guild.id, usd)
            rate = await self.economy.get_rate(ctx.guild.id)
            converted_note = f"\n💱 ${usd:,.2f} → **{sob_price:,} sobs** (at {rate:,}/$1)"
        else:
            try:
                sob_price = int(price_str)
            except ValueError:
                await ctx.reply(embed=embeds.error_embed(
                    f"Price must be a number of sobs (e.g. `5000`) or a dollar value (e.g. `$10`)."))
                return

        sob_price = max(0, sob_price)
        await self.shop.upsert_custom_item(
            ctx.guild.id, item_key=key.lower(), name=name, category="server",
            price=sob_price, icon="🎁", stock=-1, enabled=True,
            description="Custom server reward — claim with !use, an admin delivers it.",
        )
        await ctx.reply(embed=embeds.used_embed(
            "Server item added",
            f"🎁 **{name}** — `{sob_price:,}` sobs (key `{key.lower()}`){converted_note}\n"
            f"Unlimited stock. Limit it with `{ctx.prefix}shop setstock {key.lower()} <n>`.",
        ))

    @shop_group.command(name="setstock")
    @commands.guild_only()
    async def shop_setstock(self, ctx: commands.Context, key: str, stock: int):
        if not await self._can_manage(ctx):
            await ctx.reply(embed=embeds.error_embed("Only server admins can change stock."))
            return
        catalog = await self.shop.get_catalog(ctx.guild.id)
        it = next((c for c in catalog if c["key"] == key.lower()), None)
        if it is None:
            await ctx.reply(embed=embeds.error_embed(f"No item `{key}`."))
            return
        await self.shop.upsert_custom_item(
            ctx.guild.id, item_key=key.lower(), name=it["name"], category=it["category"],
            price=it["price"], icon=it["icon"], stock=stock, enabled=it["enabled"],
            description=it.get("description", ""),
        )
        txt = "unlimited" if stock < 0 else str(stock)
        await ctx.reply(embed=embeds.used_embed("Stock updated", f"**{it['name']}** stock set to `{txt}`."))

    @shop_group.command(name="removeitem")
    @commands.guild_only()
    async def shop_removeitem(self, ctx: commands.Context, key: str):
        if not await self._can_manage(ctx):
            await ctx.reply(embed=embeds.error_embed("Only server admins can remove items."))
            return
        catalog = await self.shop.get_catalog(ctx.guild.id)
        it = next((c for c in catalog if c["key"] == key.lower()), None)
        if it is None:
            await ctx.reply(embed=embeds.error_embed(f"No item `{key}`."))
            return
        await self.shop.upsert_custom_item(
            ctx.guild.id, item_key=key.lower(), name=it["name"], category=it["category"],
            price=it["price"], icon=it["icon"], stock=it.get("stock", -1), enabled=False,
            description=it.get("description", ""),
        )
        await ctx.reply(embed=embeds.used_embed("Item disabled", f"**{it['name']}** is no longer buyable."))