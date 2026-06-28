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

    async def _db(self):
        return await self.db_manager.get()

    # ------------------------------------------------------------------
    # catalog (built-in merged with per-guild custom/overrides)
    # ------------------------------------------------------------------

    async def get_catalog(self, guild_id: int, economy=None) -> list[dict[str, Any]]:
        """Built-in items plus any enabled custom guild items. Built-in prices
        auto-scale to the server economy unless an admin override row exists.
        Uses self.economy by default so the displayed price always matches what
        buy() actually charges."""
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
        # built-ins first (with any overrides applied)
        for key, base in BUILTIN_ITEMS.items():
            item = dict(base)
            item["stock"] = -1
            item["enabled"] = True
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
            # tax-included total (built-in PvP items are taxed on top)
            item["_final_price"] = item["price"] + int(item["price"] * tax_pct / 100)
            catalog.append(item)

        # purely custom guild items (keys not in built-ins)
        for key, o in overrides.items():
            if key in BUILTIN_ITEMS:
                continue
            catalog.append({
                "key": key,
                "name": o["name"],
                "icon": o["icon"] or "📦",
                "category": o["category"] or "server",
                "price": int(o["price"]),
                "stock": int(o["stock"]),
                "enabled": bool(o["enabled"]),
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

    async def get_inventory(self, guild_id: int, user_id: int) -> dict[str, int]:
        db = await self._db()
        rows = await db.fetchall(
            "SELECT item_key, quantity FROM shop_inventory WHERE guild_id = ? AND user_id = ? AND quantity > 0",
            (guild_id, user_id),
        )
        return {str(r["item_key"]): int(r["quantity"]) for r in rows}

    async def _add_to_inventory(self, db, guild_id: int, user_id: int, item_key: str, qty: int, ts: int) -> None:
        await db.execute(
            """
            INSERT INTO shop_inventory (guild_id, user_id, item_key, quantity, updated_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(guild_id, user_id, item_key) DO UPDATE SET
                quantity = quantity + excluded.quantity, updated_at = excluded.updated_at
            """,
            (guild_id, user_id, item_key, qty, ts),
        )

    async def _take_from_inventory(self, db, guild_id: int, user_id: int, item_key: str, qty: int, ts: int) -> bool:
        row = await db.fetchone(
            "SELECT quantity FROM shop_inventory WHERE guild_id = ? AND user_id = ? AND item_key = ?",
            (guild_id, user_id, item_key),
        )
        if row is None or int(row["quantity"]) < qty:
            return False
        await db.execute(
            "UPDATE shop_inventory SET quantity = quantity - ?, updated_at = ? WHERE guild_id = ? AND user_id = ? AND item_key = ?",
            (qty, ts, guild_id, user_id, item_key),
        )
        return True

    # ------------------------------------------------------------------
    # buying
    # ------------------------------------------------------------------

    async def buy(self, guild_id: int, user_id: int, item_key: str, qty: int = 1) -> tuple[bool, str, dict | None]:
        """Spend sobs to add an item to inventory.
        Returns (success, reason, item). reason in:
        ok, no_item, disabled, out_of_stock, not_enough_sobs."""
        qty = max(1, int(qty))
        item = await self.get_item(guild_id, item_key)
        if item is None:
            return False, "no_item", None
        if not item["enabled"]:
            return False, "disabled", item

        cost = int(item["price"]) * qty

        # Tax is added ON TOP for built-in PvP items (server items are untaxed).
        # The base price is burned (sink); the tax goes to the server treasury.
        tax_amount = 0
        is_builtin = item["key"] in BUILTIN_ITEMS
        if self.economy is not None and is_builtin:
            try:
                tax_pct = await self.economy.get_tax_pct(guild_id)
                tax_amount = int(cost * tax_pct / 100)
            except Exception:
                tax_amount = 0
        total_charge = cost + tax_amount

        stats = await self.sob_repo.get_user_stats(guild_id, user_id)
        if stats["sobs_alltime"] < total_charge:
            return False, "not_enough_sobs", item

        db = await self._db()
        ts = now_ts()
        canonical_key = item["key"]  # always store under the real key, not raw input

        # stock check + decrement (custom items only; built-ins are unlimited)
        if item["stock"] is not None and item["stock"] >= 0:
            if item["stock"] < qty:
                return False, "out_of_stock", item
            await db.execute(
                "UPDATE shop_items SET stock = stock - ?, updated_at = ? WHERE guild_id = ? AND item_key = ?",
                (qty, ts, guild_id, canonical_key),
            )

        # charge sobs (base + tax) — lowers leaderboard — then grant item
        await self.sob_repo.adjust_received(guild_id, user_id, -total_charge)
        await self._add_to_inventory(db, guild_id, user_id, canonical_key, qty, ts)
        await db.commit()

        # Split the charge: base is burned (sink), tax goes to the treasury pot.
        if self.economy is not None and is_builtin:
            try:
                await self.economy.add_burned(guild_id, cost)
                if tax_amount > 0:
                    await self.economy.add_treasury(guild_id, tax_amount, payer_id=user_id)
            except Exception:
                pass

        # expose what was charged so the buy embed can show it
        item = dict(item)
        item["_charged"] = total_charge
        item["_tax"] = tax_amount
        return True, "ok", item

    # ------------------------------------------------------------------
    # active effects
    # ------------------------------------------------------------------

    async def add_effect(self, guild_id: int, target_user_id: int, effect_key: str,
                         *, source_user_id: int = 0, expires_at: int = 0) -> None:
        db = await self._db()
        ts = now_ts()
        await db.execute(
            """
            INSERT INTO active_effects (guild_id, target_user_id, effect_key, source_user_id, expires_at, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (guild_id, target_user_id, effect_key, source_user_id, expires_at, ts),
        )
        await db.commit()

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
            "SELECT effect_id, effect_key, source_user_id, expires_at, created_at FROM active_effects WHERE guild_id = ? AND target_user_id = ?",
            (guild_id, user_id),
        )
        return [dict(r) for r in rows]

    async def has_effect(self, guild_id: int, user_id: int, effect_key: str) -> bool:
        for e in await self.get_effects(guild_id, user_id):
            if e["effect_key"] == effect_key:
                return True
        return False

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

        Returns the number of sobs actually transferred.
        """
        if sobs_wiped <= 0:
            return 0
        mult = multiplier if multiplier is not None else await self.get_boost_multiplier(guild_id)
        desired = int(round(sobs_wiped * mult))

        # cap by what the target currently has (conserved transfer)
        target_stats = await self.sob_repo.get_user_stats(guild_id, target_id)
        available = int(target_stats["sobs_alltime"])
        transfer = min(desired, available)
        if transfer <= 0:
            return 0

        # drain target, credit snitcher (adjust_received floors at 0 and updates day/week)
        await self.sob_repo.adjust_received(guild_id, target_id, -transfer)
        await self.sob_repo.adjust_received(guild_id, snitcher_id, +transfer)
        return transfer

    async def apply_tax_audit(self, guild_id: int, auditor_id: int, target_id: int,
                              pct: float = 0.05, cap: int = 5000) -> int:
        """Instantly steal pct of the target's sobs (capped). Conserved transfer —
        the auditor gains exactly what the target loses; nothing is minted."""
        target_stats = await self.sob_repo.get_user_stats(guild_id, target_id)
        bal = int(target_stats["sobs_alltime"])
        amount = min(int(bal * pct), cap, bal)
        if amount <= 0:
            return 0
        await self.sob_repo.adjust_received(guild_id, target_id, -amount)
        await self.sob_repo.adjust_received(guild_id, auditor_id, +amount)
        return amount