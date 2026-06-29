# core/shop/repo.py
from __future__ import annotations

from typing import Any

from core.db import DatabaseManager
from core.time_utils import now_ts
from core.shop.catalog import BUILTIN_ITEMS, DEFAULT_BOOST_MULTIPLIER


class ShopRepo:
    """Shop data: catalog, inventory, purchases, active effects.

    Spends sobs via SobRepo so the leaderboard reflects the cost.
    """

    def __init__(self, db_manager: DatabaseManager, sob_repo, economy=None):
        self.db_manager = db_manager
        self.sob_repo = sob_repo
        self.economy = economy
        # Risk-based protection pricing. Set by the bot after construction so
        # protection items are priced from the BUYER'S personal risk, not the
        # whole-server reference. Optional: falls back to economy tiers if None.
        self.protection = None

    PROTECTION_KEYS = ("shield", "guardian", "reflect", "audit_ward", "vault_ward")

    async def personal_price(self, guild_id: int, user_id: int, item: dict) -> int:
        """The price THIS user pays for an item: risk-based for protection,
        otherwise the catalog's economy-scaled price. Per-unit (qty handled by
        the caller)."""
        key = item["key"]
        if self.protection is not None and key in self.PROTECTION_KEYS:
            try:
                p = await self.protection.price_for(guild_id, user_id, key)
                if p is not None:
                    return int(p)
            except Exception:
                pass
        return int(item["price"])

    async def _db(self):
        return await self.db_manager.get()

    # ------------------------------------------------------------------
    # catalog (built-in merged with per-guild custom/overrides)
    # ------------------------------------------------------------------

    async def get_catalog(self, guild_id: int, economy=None, user_id: int | None = None) -> list[dict[str, Any]]:
        """Built-in items plus any enabled custom guild items. Built-in prices
        auto-scale to the server economy unless an admin override row exists.
        Uses self.economy by default so the displayed price always matches what
        buy() actually charges. When user_id is given, protection items show
        that buyer's personal risk-based price."""
        if economy is None:
            economy = self.economy
        db = await self._db()
        rows = await db.fetchall(
            "SELECT item_key, name, category, icon, price, stock, enabled, description FROM shop_items WHERE guild_id = ?",
            (guild_id,),
        )
        overrides = {str(r["item_key"]): dict(r) for r in rows}

        # auto-scaled prices for built-in items (median-based, whale-proof)
        auto_prices = {}
        tax_pct = 0
        if economy is not None:
            try:
                auto_prices = await economy.all_item_prices(guild_id)
                tax_pct = await economy.get_tax_pct(guild_id)
            except Exception:
                auto_prices = {}
                tax_pct = 0

        catalog: list[dict[str, Any]] = []
        # admin disable controls (comma-separated lists in guild_settings)
        dis_items_raw = await self.sob_repo.get_guild_setting(guild_id, "shop:disabled_items") or ""
        dis_cats_raw = await self.sob_repo.get_guild_setting(guild_id, "shop:disabled_categories") or ""
        disabled_items = {x.strip().lower() for x in dis_items_raw.split(",") if x.strip()}
        disabled_cats = {x.strip().lower() for x in dis_cats_raw.split(",") if x.strip()}
        shop_off = (await self.sob_repo.get_guild_setting(guild_id, "shop:enabled")) == "0"

        # built-ins first (with any overrides applied)
        from core.shop.catalog import ENFORCED_MECHANICS
        for key, base in BUILTIN_ITEMS.items():
            item = dict(base)
            item["stock"] = -1
            item["enabled"] = True
            # Safety: if an item's advertised mechanic isn't actually enforced
            # in code yet, it must not be buyable (requirement: disable broken
            # effects until they work).
            if base.get("mechanic", "") not in ENFORCED_MECHANICS:
                item["enabled"] = False
            # auto-price unless admin overrode it
            if key in auto_prices and key not in overrides:
                item["price"] = auto_prices[key]
            if key in overrides:
                o = overrides[key]
                item["price"] = int(o["price"])
                item["stock"] = int(o["stock"])
                item["enabled"] = bool(o["enabled"])
                if o["name"]:
                    item["name"] = o["name"]
                if o["icon"]:
                    item["icon"] = o["icon"]
                if o["description"]:
                    item["description"] = o["description"]
            # admin disable: whole shop, this category, or this specific item
            if shop_off or key in disabled_items or str(item.get("category", "")).lower() in disabled_cats:
                item["enabled"] = False
            # personal risk-based price for protection items (shield = 30-min quote)
            if user_id is not None and self.protection is not None and key in self.PROTECTION_KEYS:
                try:
                    pp = await self.protection.price_for(guild_id, user_id, key)
                    if pp is not None:
                        item["price"] = int(pp)
                        if key == "shield":
                            item["_per_30min"] = int(pp)  # shield shown per 30 min
                except Exception:
                    pass
            # tax-included total (built-in PvP items are taxed on top)
            item["_final_price"] = item["price"] + int(item["price"] * tax_pct / 100)
            catalog.append(item)

        # purely custom guild items (keys not in built-ins)
        for key, o in overrides.items():
            if key in BUILTIN_ITEMS:
                continue
            cat = (o["category"] or "server")
            enabled = bool(o["enabled"])
            if shop_off or key.lower() in disabled_items or cat.lower() in disabled_cats:
                enabled = False
            catalog.append({
                "key": key,
                "name": o["name"],
                "icon": o["icon"] or "📦",
                "category": cat,
                "price": int(o["price"]),
                "stock": int(o["stock"]),
                "enabled": enabled,
                "description": o["description"] or "",
            })
        return catalog

    async def get_item(self, guild_id: int, item_key: str) -> dict[str, Any] | None:
        """Resolve an item by its key OR its display name, case-insensitively.
        So 'shield', 'Shield', 'basic shield', 'Basic Shield' all work."""
        query = item_key.strip().lower()
        catalog = await self.get_catalog(guild_id, economy=self.economy)
        # exact key match first
        for item in catalog:
            if item["enabled"] and item["key"].lower() == query:
                return item
        # then display-name match
        for item in catalog:
            if item["enabled"] and item["name"].lower() == query:
                return item
        return None

    async def upsert_custom_item(
        self, guild_id: int, *, item_key: str, name: str, category: str,
        price: int, icon: str = "", stock: int = -1, enabled: bool = True,
        description: str = "",
    ) -> None:
        db = await self._db()
        ts = now_ts()
        await db.execute(
            """
            INSERT INTO shop_items (guild_id, item_key, name, category, icon, price, stock, enabled, description, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(guild_id, item_key) DO UPDATE SET
                name=excluded.name, category=excluded.category, icon=excluded.icon,
                price=excluded.price, stock=excluded.stock, enabled=excluded.enabled,
                description=excluded.description, updated_at=excluded.updated_at
            """,
            (guild_id, item_key, name, category, icon, int(price), int(stock),
             1 if enabled else 0, description, ts),
        )
        await db.commit()

    # ------------------------------------------------------------------
    # inventory
    # ------------------------------------------------------------------

    # Protection items can't be stockpiled while poor and used later when rich:
    # they expire from inventory if not used within this window.
    PROTECTION_INV_TTL = 86400  # 24h

    async def _prune_expired(self, db, guild_id: int, user_id: int, ts: int) -> None:
        """Drop protection inventory that has passed its 24h expiry."""
        await db.execute(
            "DELETE FROM shop_inventory WHERE guild_id=? AND user_id=? "
            "AND expires_at > 0 AND expires_at <= ?",
            (guild_id, user_id, ts),
        )

    async def get_inventory(self, guild_id: int, user_id: int) -> dict[str, int]:
        db = await self._db()
        await self._prune_expired(db, guild_id, user_id, now_ts())
        rows = await db.fetchall(
            "SELECT item_key, quantity FROM shop_inventory WHERE guild_id = ? AND user_id = ? AND quantity > 0",
            (guild_id, user_id),
        )
        return {str(r["item_key"]): int(r["quantity"]) for r in rows}

    async def _add_to_inventory(self, db, guild_id: int, user_id: int, item_key: str, qty: int, ts: int) -> None:
        # Protection AND steal items get a 24h expiry; everything else stays (0).
        from core.shop.catalog import BUILTIN_ITEMS
        _cat = BUILTIN_ITEMS.get(item_key, {}).get("category")
        is_expiring = _cat in ("protection", "steal")
        expires = (ts + self.PROTECTION_INV_TTL) if is_expiring else 0
        await db.execute(
            """
            INSERT INTO shop_inventory (guild_id, user_id, item_key, quantity, updated_at, expires_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(guild_id, user_id, item_key) DO UPDATE SET
                quantity = quantity + excluded.quantity, updated_at = excluded.updated_at,
                expires_at = CASE WHEN excluded.expires_at > 0 THEN excluded.expires_at ELSE shop_inventory.expires_at END
            """,
            (guild_id, user_id, item_key, qty, ts, expires),
        )

    async def _take_from_inventory(self, db, guild_id: int, user_id: int, item_key: str, qty: int, ts: int) -> bool:
        """Atomically remove `qty` of an item ONLY if the user holds at least
        that many. Uses a conditional UPDATE and checks the row count, so it
        can never drive a quantity negative and two concurrent uses can't both
        consume the same unit. `db` may be the shared connection or an open
        transaction connection."""
        cur = await db.execute(
            "UPDATE shop_inventory SET quantity = quantity - ?, updated_at = ? "
            "WHERE guild_id = ? AND user_id = ? AND item_key = ? AND quantity >= ?",
            (qty, ts, guild_id, user_id, item_key, qty),
        )
        return cur.rowcount > 0

    # ------------------------------------------------------------------
    # buying
    # ------------------------------------------------------------------

    async def buy(self, guild_id: int, user_id: int, item_key: str, qty: int = 1) -> tuple[bool, str, dict | None]:
        """Spend sobs to add an item to inventory.
        Returns (success, reason, item). reason in:
        ok, no_item, disabled, out_of_stock, not_enough_sobs.

        The charge (base + tax) is taken with a conditional spend that rejects
        if the balance is too low, the inventory grant, the stock decrement and
        all ledger rows happen in one atomic transaction, and the whole thing is
        serialised per user. Two concurrent !buy can't both pass on one balance.
        """
        from core import ledger
        qty = max(1, int(qty))
        item = await self.get_item(guild_id, item_key)
        if item is None:
            return False, "no_item", None
        if not item["enabled"]:
            return False, "disabled", item

        # Per-unit price THIS buyer pays. Protection is risk-priced from the
        # buyer's own exposure. The shield is sold per-second, so we price the
        # whole purchase as a fraction of the 30-min risk price (computing the
        # block total avoids per-second rounding inflating the cost).
        if item["key"] == "shield" and self.protection is not None:
            try:
                from core.protection import SHIELD_WINDOW_SECONDS
                price30 = await self.protection.price_for(guild_id, user_id, "shield")
                if price30 is None:
                    raise ValueError
                cost = max(1, int(round(price30 * qty / SHIELD_WINDOW_SECONDS)))
            except Exception:
                cost = max(1, int(item["price"]) * qty)
        else:
            unit_price = await self.personal_price(guild_id, user_id, item)
            cost = unit_price * qty

        # Tax is added ON TOP for built-in PvP/offensive items only. Protection
        # items (shields, wards) are defensive and NOT taxed — their risk-based
        # price is the final price, so it always stays below the damage prevented.
        tax_amount = 0
        is_builtin = item["key"] in BUILTIN_ITEMS
        is_protection = item.get("category") == "protection" or item["key"] in self.PROTECTION_KEYS
        if self.economy is not None and is_builtin and not is_protection:
            try:
                tax_pct = await self.economy.get_tax_pct(guild_id)
                tax_amount = int(cost * tax_pct / 100)
            except Exception:
                tax_amount = 0
        total_charge = cost + tax_amount

        db = await self._db()
        ts = now_ts()
        canonical_key = item["key"]
        tx = ledger.new_tx_id()

        async with db.key_lock("sob", guild_id, user_id):
            async with db.transaction() as conn:
                # stock check + decrement (custom items only; built-ins unlimited)
                if item["stock"] is not None and item["stock"] >= 0:
                    cur = await conn.execute(
                        "UPDATE shop_items SET stock = stock - ?, updated_at = ? "
                        "WHERE guild_id = ? AND item_key = ? AND stock >= ?",
                        (qty, ts, guild_id, canonical_key, qty),
                    )
                    if cur.rowcount == 0:
                        return False, "out_of_stock", item

                # conditional spend: rejects atomically if too poor
                await self.sob_repo._ensure_user_row(conn, guild_id, user_id, ts)
                before = await self.sob_repo._balance(conn, guild_id, user_id)
                cur = await conn.execute(
                    "UPDATE sob_users SET sobs_received_alltime = sobs_received_alltime - ?, "
                    "updated_at = ? WHERE guild_id = ? AND user_id = ? AND sobs_received_alltime >= ?",
                    (total_charge, ts, guild_id, user_id, total_charge),
                )
                if cur.rowcount == 0:
                    return False, "not_enough_sobs", item
                after = before - total_charge

                # keep period rollups in step
                from core.time_utils import today_keys
                day_k, week_k = today_keys()
                for ptype, pkey in (("day", day_k), ("week", week_k)):
                    await conn.execute(
                        "UPDATE sob_periods SET sobs_received = MAX(0, sobs_received - ?), "
                        "updated_at = ? WHERE guild_id = ? AND user_id = ? AND period_type = ? AND period_key = ?",
                        (total_charge, ts, guild_id, user_id, ptype, pkey),
                    )

                # grant the item
                await self._add_to_inventory(conn, guild_id, user_id, canonical_key, qty, ts)

                # ledger: base cost (burn for built-ins), tax, inventory add
                burn = cost if is_builtin else 0
                await ledger.record(
                    conn, guild_id=guild_id, event_type=ledger.EVT_SHOP_BASE,
                    transaction_id=tx, subject_id=user_id, actor_id=user_id,
                    delta=-total_charge, balance_before=before, balance_after=after,
                    item_key=canonical_key, item_name=item.get("name", canonical_key),
                    quantity=qty, price=int(item["price"]),
                    tax_amount=tax_amount, burned_amount=burn,
                    metadata={"builtin": is_builtin}, created_at=ts,
                )
                if tax_amount > 0:
                    await ledger.record(
                        conn, guild_id=guild_id, event_type=ledger.EVT_SHOP_TAX,
                        transaction_id=tx, subject_id=user_id, actor_id=user_id,
                        delta=0, balance_before=after, balance_after=after,
                        item_key=canonical_key, treasury_amount=tax_amount, created_at=ts,
                    )
                if burn > 0:
                    await ledger.record(
                        conn, guild_id=guild_id, event_type=ledger.EVT_SHOP_BURN,
                        transaction_id=tx, subject_id=user_id, actor_id=user_id,
                        delta=0, balance_before=after, balance_after=after,
                        item_key=canonical_key, burned_amount=burn, created_at=ts,
                    )
                await ledger.record(
                    conn, guild_id=guild_id, event_type=ledger.EVT_INV_ADD,
                    transaction_id=tx, subject_id=user_id, actor_id=user_id,
                    delta=0, balance_before=after, balance_after=after,
                    item_key=canonical_key, item_name=item.get("name", canonical_key),
                    quantity=qty, created_at=ts,
                )

        # Split the charge into the sinks AFTER the balance change committed.
        if self.economy is not None and is_builtin:
            try:
                await self.economy.add_burned(guild_id, cost)
                if tax_amount > 0:
                    await self.economy.add_treasury(guild_id, tax_amount, payer_id=user_id)
            except Exception:
                pass

        item = dict(item)
        item["_charged"] = total_charge
        item["_tax"] = tax_amount
        return True, "ok", item

    # ------------------------------------------------------------------
    # active effects
    # ------------------------------------------------------------------

    async def add_effect(self, guild_id: int, target_user_id: int, effect_key: str,
                         *, source_user_id: int = 0, expires_at: int = 0,
                         charges: int = 0) -> None:
        db = await self._db()
        ts = now_ts()
        await db.execute(
            """
            INSERT INTO active_effects (guild_id, target_user_id, effect_key, source_user_id, expires_at, created_at, charges_remaining)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (guild_id, target_user_id, effect_key, source_user_id, expires_at, ts, int(charges)),
        )
        await db.commit()

    async def consume_charge(self, guild_id: int, user_id: int, effect_key: str) -> tuple[bool, int]:
        """Decrement one charge of a charge-based effect (guardian, hunter,
        reflect, ...). Removes the effect row when it hits 0. Returns
        (consumed, charges_left). Atomic per (guild, user, effect)."""
        db = await self._db()
        async with db.key_lock("effect", guild_id, user_id, effect_key):
            async with db.transaction() as conn:
                cur = await conn.execute(
                    "SELECT effect_id, charges_remaining FROM active_effects "
                    "WHERE guild_id=? AND target_user_id=? AND effect_key=? "
                    "ORDER BY created_at ASC LIMIT 1",
                    (guild_id, user_id, effect_key),
                )
                row = await cur.fetchone()
                await cur.close()
                if row is None:
                    return False, 0
                left = int(row["charges_remaining"]) - 1
                if left <= 0:
                    await conn.execute("DELETE FROM active_effects WHERE effect_id = ?", (int(row["effect_id"]),))
                    return True, 0
                await conn.execute(
                    "UPDATE active_effects SET charges_remaining = ? WHERE effect_id = ?",
                    (left, int(row["effect_id"])),
                )
                return True, left

    async def charges_left(self, guild_id: int, user_id: int, effect_key: str) -> int:
        db = await self._db()
        row = await db.fetchone(
            "SELECT COALESCE(SUM(charges_remaining),0) AS c FROM active_effects "
            "WHERE guild_id=? AND target_user_id=? AND effect_key=?",
            (guild_id, user_id, effect_key),
        )
        return int(row["c"]) if row else 0

    async def log_effect(self, guild_id: int, event_type: str, subject_id: int,
                         *, actor_id: int = 0, item_key: str = "", quantity: int = 0,
                         metadata: dict | None = None) -> None:
        """Append a zero-delta ledger row recording an item/effect lifecycle
        event (use, block, activation, expiration, consumed charge, claim) so
        the export can show exactly what happened without a balance change."""
        from core import ledger
        db = await self._db()
        async with db.transaction() as conn:
            await ledger.record(
                conn, guild_id=guild_id, event_type=event_type,
                transaction_id=ledger.new_tx_id(), subject_id=subject_id,
                actor_id=actor_id or subject_id, counterparty_id=actor_id,
                delta=0, item_key=item_key, quantity=quantity, metadata=metadata,
            )

    async def get_effects(self, guild_id: int, user_id: int) -> list[dict[str, Any]]:
        """Active (non-expired) effects on a user. Cleans up expired rows."""
        db = await self._db()
        ts = now_ts()
        # purge expired (expires_at > 0 and passed)
        await db.execute(
            "DELETE FROM active_effects WHERE guild_id = ? AND target_user_id = ? AND expires_at > 0 AND expires_at <= ?",
            (guild_id, user_id, ts),
        )
        await db.commit()
        rows = await db.fetchall(
            "SELECT effect_id, effect_key, source_user_id, expires_at, created_at, charges_remaining FROM active_effects WHERE guild_id = ? AND target_user_id = ?",
            (guild_id, user_id),
        )
        return [dict(r) for r in rows]

    async def has_effect(self, guild_id: int, user_id: int, effect_key: str) -> bool:
        for e in await self.get_effects(guild_id, user_id):
            if e["effect_key"] == effect_key:
                return True
        return False

    async def effect_expiry(self, guild_id: int, user_id: int, effect_key: str) -> int:
        """Latest expiry timestamp for an active effect (0 if none). Used to
        extend a stacking shield instead of replacing it."""
        best = 0
        for e in await self.get_effects(guild_id, user_id):
            if e["effect_key"] == effect_key:
                best = max(best, int(e.get("expires_at", 0) or 0))
        return best

    async def clear_effect(self, guild_id: int, user_id: int, effect_key: str) -> bool:
        """Remove all instances of an effect (e.g. a shield smashed by a crit)."""
        db = await self._db()
        await db.execute(
            "DELETE FROM active_effects WHERE guild_id = ? AND target_user_id = ? AND effect_key = ?",
            (guild_id, user_id, effect_key),
        )
        await db.commit()
        return True

    async def consume_effect(self, guild_id: int, user_id: int, effect_key: str) -> bool:
        """Remove one instance of a one-shot effect (e.g. shield). Returns True if consumed."""
        db = await self._db()
        row = await db.fetchone(
            "SELECT effect_id FROM active_effects WHERE guild_id = ? AND target_user_id = ? AND effect_key = ? ORDER BY created_at ASC LIMIT 1",
            (guild_id, user_id, effect_key),
        )
        if row is None:
            return False
        await db.execute("DELETE FROM active_effects WHERE effect_id = ?", (int(row["effect_id"]),))
        await db.commit()
        return True

    # ------------------------------------------------------------------
    # boost mechanic
    # ------------------------------------------------------------------

    async def get_boost_multiplier(self, guild_id: int) -> float:
        """Per-server boost multiplier; falls back to the catalog default."""
        raw = await self.sob_repo.get_guild_setting(guild_id, "boost_multiplier")
        if raw is None:
            return DEFAULT_BOOST_MULTIPLIER
        try:
            return max(1.0, float(raw))
        except (ValueError, TypeError):
            return DEFAULT_BOOST_MULTIPLIER

    async def set_boost_multiplier(self, guild_id: int, value: float) -> float:
        value = max(1.0, float(value))
        await self.sob_repo.set_guild_setting(guild_id, "boost_multiplier", str(value))
        return value

    async def apply_boost_steal(self, guild_id: int, snitcher_id: int, target_id: int,
                                sobs_wiped: int, multiplier: float | None = None) -> int:
        """
        Boosted snitch: drain (sobs_wiped * multiplier) from the target and give
        the same amount to the snitcher — but never more than the target actually
        has (so the economy is conserved; no sobs are created).

        Returns the number of sobs actually transferred. Atomic + ledgered.
        """
        from core import ledger
        if sobs_wiped <= 0:
            return 0
        mult = multiplier if multiplier is not None else await self.get_boost_multiplier(guild_id)
        desired = int(round(sobs_wiped * mult))
        return await self.sob_repo.transfer(
            guild_id, target_id, snitcher_id, desired,
            event_type=ledger.EVT_SNITCH_STEAL, actor_id=snitcher_id,
            cap_to_balance=True, metadata={"boost_mult": mult, "wiped": sobs_wiped})

    async def apply_tax_audit(self, guild_id: int, auditor_id: int, target_id: int,
                              pct: float = 0.05, cap: int = 5000) -> int:
        """Instantly steal pct of the target's sobs (capped). Conserved transfer —
        the auditor gains exactly what the target loses; nothing is minted.
        Atomic + ledgered."""
        from core import ledger
        target_stats = await self.sob_repo.get_user_stats(guild_id, target_id)
        bal = int(target_stats["sobs_alltime"])
        amount = min(int(bal * pct), cap, bal)
        if amount <= 0:
            return 0
        return await self.sob_repo.transfer(
            guild_id, target_id, auditor_id, amount,
            event_type=ledger.EVT_AUDIT_STEAL, actor_id=auditor_id,
            cap_to_balance=True, metadata={"pct": pct, "cap": cap})
