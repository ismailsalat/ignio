# core/ledger.py
"""
Append-only economy ledger.

Every sob that is earned, lost, spent, transferred, or received is recorded
here as one or more rows. Rows are NEVER updated or deleted in normal
operation, so:

* the full history of how every balance came to be can be reconstructed, and
* every user's balance can be reconciled from the sum of their ledger deltas.

A logical action (a snitch, a purchase, a roulette settlement, ...) writes all
its rows under a single ``transaction_id``. Where an action is a pure transfer
or spend, the rows of one transaction sum to zero across subject + treasury +
burn (double-entry). Intentional minting (daily rewards, admin grants) is the
deliberate exception and is recorded as a single positive entry.

This module never opens its own transaction: callers pass the live connection
from an open :meth:`Database.transaction` so the ledger writes commit/roll back
together with the balance change they describe. That atomicity is the whole
point — a balance can never move without a matching ledger row, and a ledger
row can never exist without the balance having moved.
"""
from __future__ import annotations

import json
import time
import uuid


def new_tx_id() -> str:
    """A short unique id grouping the rows of one logical action."""
    return uuid.uuid4().hex


# Canonical event types (kept as constants so call sites can't typo them).
EVT_REACTION_ADD = "sob_reaction_added"
EVT_REACTION_REMOVE = "sob_reaction_removed"
EVT_REACTION_BLOCKED = "blocked_sob_reaction"
EVT_SNITCH_WIPE = "snitch_wipe"
EVT_SNITCH_REWARD = "snitch_reward"
EVT_SNITCH_STEAL = "snitch_steal"
EVT_SNITCH_TAX = "snitch_tax"
EVT_DAILY = "daily_claim"
EVT_ADMIN_GIVE = "admin_givesob"
EVT_ADMIN_REMOVE = "admin_sob_removal"
EVT_TREASURY_PAYOUT = "treasury_payout"
EVT_SHOP_BASE = "shop_purchase_base_cost"
EVT_SHOP_TAX = "shop_tax"
EVT_SHOP_BURN = "shop_burn"
EVT_INV_ADD = "inventory_added"
EVT_INV_CONSUME = "inventory_consumed"
EVT_SERVER_CLAIM = "server_item_claim"
EVT_AUDIT_STEAL = "audit_steal"
EVT_SHIELD_BLOCK = "shield_block"
EVT_EFFECT_ACTIVATE = "effect_activation"
EVT_EFFECT_EXPIRE = "effect_expiration"
EVT_EFFECT_CHARGE = "effect_charge_consumed"
EVT_ROULETTE_ESCROW = "roulette_escrow_deposit"
EVT_ROULETTE_PAYOUT = "roulette_payout"
EVT_ROULETTE_REFUND = "roulette_refund"
EVT_IMPORT = "import"
EVT_RESET = "reset"
EVT_RECOUNT = "recount"
EVT_CORRECTION = "manual_correction"


async def record(
    conn,
    *,
    guild_id: int,
    event_type: str,
    transaction_id: str,
    subject_id: int = 0,
    actor_id: int = 0,
    counterparty_id: int = 0,
    delta: int = 0,
    balance_before: int = 0,
    balance_after: int = 0,
    item_key: str = "",
    item_name: str = "",
    quantity: int = 0,
    price: int = 0,
    message_id: int = 0,
    game_id: str = "",
    tax_amount: int = 0,
    treasury_amount: int = 0,
    burned_amount: int = 0,
    multiplier_ref: str = "",
    metadata: dict | None = None,
    created_at: int | None = None,
) -> None:
    """Append one ledger row on the given (already-open-transaction) connection.

    Never call this outside a Database.transaction() — it must commit together
    with the balance change it records.
    """
    ts = int(time.time()) if created_at is None else int(created_at)
    meta = json.dumps(metadata, ensure_ascii=False, default=str) if metadata else ""
    await conn.execute(
        """
        INSERT INTO economy_ledger (
            transaction_id, guild_id, created_at, event_type,
            subject_id, actor_id, counterparty_id,
            delta, balance_before, balance_after,
            item_key, item_name, quantity, price,
            message_id, game_id,
            tax_amount, treasury_amount, burned_amount, multiplier_ref,
            metadata
        ) VALUES (?,?,?,?, ?,?,?, ?,?,?, ?,?,?,?, ?,?, ?,?,?,?, ?)
        """,
        (
            transaction_id, int(guild_id), ts, event_type,
            int(subject_id), int(actor_id), int(counterparty_id),
            int(delta), int(balance_before), int(balance_after),
            item_key, item_name, int(quantity), int(price),
            int(message_id), game_id,
            int(tax_amount), int(treasury_amount), int(burned_amount), multiplier_ref,
            meta,
        ),
    )


# ----------------------------------------------------------------------
# read helpers (used by !admin audit and the export)
# ----------------------------------------------------------------------

async def user_summary(db, guild_id: int, user_id: int) -> dict:
    """Total earned/spent by event type for one user, from the ledger."""
    rows = await db.fetchall(
        "SELECT event_type, "
        "COALESCE(SUM(CASE WHEN delta > 0 THEN delta ELSE 0 END),0) AS earned, "
        "COALESCE(SUM(CASE WHEN delta < 0 THEN -delta ELSE 0 END),0) AS spent, "
        "COUNT(*) AS n "
        "FROM economy_ledger WHERE guild_id=? AND subject_id=? GROUP BY event_type",
        (guild_id, user_id),
    )
    by_event = {
        str(r["event_type"]): {
            "earned": int(r["earned"]),
            "spent": int(r["spent"]),
            "count": int(r["n"]),
        }
        for r in rows
    }
    totals = await db.fetchone(
        "SELECT COALESCE(SUM(CASE WHEN delta>0 THEN delta ELSE 0 END),0) AS earned, "
        "COALESCE(SUM(CASE WHEN delta<0 THEN -delta ELSE 0 END),0) AS spent, "
        "COALESCE(SUM(delta),0) AS net "
        "FROM economy_ledger WHERE guild_id=? AND subject_id=?",
        (guild_id, user_id),
    )
    return {
        "by_event": by_event,
        "total_earned": int(totals["earned"]) if totals else 0,
        "total_spent": int(totals["spent"]) if totals else 0,
        "ledger_net": int(totals["net"]) if totals else 0,
    }


async def user_entries(db, guild_id: int, user_id: int, *, page: int = 0, per_page: int = 15) -> list[dict]:
    rows = await db.fetchall(
        "SELECT * FROM economy_ledger WHERE guild_id=? AND subject_id=? "
        "ORDER BY ledger_id DESC LIMIT ? OFFSET ?",
        (guild_id, user_id, per_page, page * per_page),
    )
    return [dict(r) for r in rows]


async def transaction_entries(db, transaction_id: str) -> list[dict]:
    rows = await db.fetchall(
        "SELECT * FROM economy_ledger WHERE transaction_id=? ORDER BY ledger_id ASC",
        (transaction_id,),
    )
    return [dict(r) for r in rows]


async def reconcile_user(db, guild_id: int, user_id: int, live_balance: int) -> dict:
    """Compare a user's live balance against the sum of their ledger deltas."""
    row = await db.fetchone(
        "SELECT COALESCE(SUM(delta),0) AS net FROM economy_ledger WHERE guild_id=? AND subject_id=?",
        (guild_id, user_id),
    )
    ledger_net = int(row["net"]) if row else 0
    return {
        "user_id": int(user_id),
        "live_balance": int(live_balance),
        "ledger_net": ledger_net,
        "delta": int(live_balance) - ledger_net,
        "reconciled": int(live_balance) == ledger_net,
    }


async def stats_breakdown(db, guild_id: int, user_id: int) -> dict:
    """Earned/spent grouped into the buckets the !sob stats card shows.

    Earned (positive deltas) and spent (negative deltas) are mapped from the
    ledger event types into player-facing categories.
    """
    rows = await db.fetchall(
        "SELECT event_type, "
        "COALESCE(SUM(CASE WHEN delta>0 THEN delta ELSE 0 END),0) AS earned, "
        "COALESCE(SUM(CASE WHEN delta<0 THEN -delta ELSE 0 END),0) AS spent "
        "FROM economy_ledger WHERE guild_id=? AND subject_id=? GROUP BY event_type",
        (guild_id, user_id),
    )
    e = {"reactions": 0, "snitch": 0, "audit": 0, "daily": 0, "games": 0}
    s = {"shop": 0, "tax": 0, "audits": 0, "games": 0}
    for r in rows:
        ev = str(r["event_type"]); earned = int(r["earned"]); spent = int(r["spent"])
        if ev in (EVT_REACTION_ADD,):
            e["reactions"] += earned
        elif ev in (EVT_SNITCH_REWARD, EVT_SNITCH_STEAL):
            e["snitch"] += earned
        elif ev in (EVT_AUDIT_STEAL,):
            e["audit"] += earned
            s["audits"] += spent          # being audited = lost sobs
        elif ev in (EVT_DAILY, EVT_ADMIN_GIVE, EVT_TREASURY_PAYOUT):
            e["daily"] += earned
        elif ev in (EVT_ROULETTE_PAYOUT, EVT_ROULETTE_REFUND):
            e["games"] += earned
            s["games"] += spent
        elif ev in (EVT_ROULETTE_ESCROW,):
            s["games"] += spent
        elif ev in (EVT_SHOP_BASE,):
            s["shop"] += spent
        elif ev in (EVT_SHOP_TAX, EVT_SNITCH_TAX):
            s["tax"] += spent
    return {"earned": e, "spent": s}
