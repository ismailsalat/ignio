# Ignio Security + Economy Audit — Fix Report (v1.0.0)

This release closes every confirmed exploit from the audit and adds a permanent
audit trail. All changes are **additive and backwards-compatible**: existing
databases upgrade in place (migrations 210–214), and existing per-guild exports
import without modification.

Everything below is covered by the automated tests in `test_*.py`
(`test_exploits.py` alone has 31 assertions; all suites pass against the real
production export of guild `1477356380443902013`, 514 users / 143,826 reactions).

---

## How the exploits were possible

The bot uses a single shared SQLite connection. SQLite serialises the actual
writes, but the async handlers have many `await` points between *reading* a
balance and *writing* the new one. Two commands could interleave there — the
classic check-then-act race behind almost every exploit. On top of that, a sob
reaction credited a *scaled* amount but only stored a reaction row, so removal
subtracted 1 and snitch subtracted the reaction *count*, never the real value.

The two structural fixes:

1. **`Database.transaction()`** opens a `BEGIN IMMEDIATE` (write lock taken
   up-front) so a unit of work commits or rolls back atomically. The connection
   runs in autocommit mode so these explicit transactions are the only ones.
2. **Per-subject async locks** (`Database.key_lock(...)`) serialise a whole
   "read then conditionally write" sequence per user/guild/effect/game.
3. **Conditional writes** (`UPDATE ... WHERE balance >= cost`, row-count
   checked) make spends impossible to race even without the lock.

---

## Audit section → fix

### 1. Sob reaction duplication
- `sob_events` now stores `credited_amount` and `multiplier_ref` (migration 210).
- `add_sob` computes the final value **once** (sob value × multiplier, adjusted
  for the target's slow/lucky effects) and stores it.
- `remove_sob` refunds exactly `credited_amount`.
- `snitch_message` removes `SUM(credited_amount)`, not the reaction count.
- Add / remove / snitch are single atomic transactions.
- *Tests:* add↔remove nets zero; 50 toggles can't mint; snitch wipes the exact total.

### 2. Concurrent command exploits
- `buy`, `use`, `daily`, snitch, audit and escrow all run in `BEGIN IMMEDIATE`
  transactions with conditional updates and row-count checks.
- New `SobRepo.spend()` (guarded), `transfer()` (conserved, double-entry) and an
  atomic `adjust_received()` replace every "check then subtract".
- Inventory take is now `UPDATE ... WHERE quantity >= n` — never negative.
- Per-user locks add a second safety layer.
- *Tests:* 20 parallel buys → 1 success; 20 parallel uses → 1 consume; no negatives.

### 3. Roulette escrow
- New `game_matches` table (migration 214). `open_match` atomically debits both
  wagers into escrow and stores the match `pending`.
- Escrowed sobs leave both balances, so they can't be spent during the animation.
- `settle_match` pays the winner the pot minus tax; `refund_match` returns both
  wagers on timeout/decline/error; `recover_pending()` refunds orphaned matches
  on bot startup.
- *Tests:* escrow lock, can't-spend-escrow, settle, refund, restart recovery,
  and clean abort when a player can't cover the wager.

### 4. Broken / unlimited shop effects
- `active_effects.charges_remaining` (migration 213). Hunter's Blessing, Guardian
  and Reflect now decrement per use and are removed at 0.
- Guardian, Reflect, King's Decree (pierce), Marked (bounty), Slow Curse and
  Lucky Day are all enforced in the reaction-credit and snitch paths.
- `ENFORCED_MECHANICS` auto-disables any built-in whose effect isn't enforced.
- Every use / block / activation / consumed charge is logged.
- *Test:* Hunter expires after exactly 10 snitches.

### 5. Real alt-block
- Configurable in `guild_settings`: minimum account age, server-join age,
  per-reactor rate limit, per-pair flood cap, and reciprocal-farm detection.
- Blocked reactions are written to the `security_log` (migration 212) with the
  reason, so admins can see why a reaction didn't count.

### 6. Permanent audit ledger
- New append-only `economy_ledger` (migration 211) with every required field:
  `ledger_id`, `transaction_id`, guild, timestamp, event type, subject/actor/
  counterparty, sob delta, balance before/after, item details, message/game id,
  tax/treasury/burn amounts, multiplier ref, and a metadata JSON.
- Double-entry: a transfer/spend writes paired rows under one `transaction_id`
  that sum to zero (intentional mints — daily, admin grants — are the exception).
- Rows are never updated or deleted in normal operation.

### 7. Admin audit tools
- `!admin audit @user` — balance, faucets, flags, **ledger earned/spent by
  source**, and reconciliation status.
- `!admin audit @user <page>` — chronological ledger entries.
- `!admin audit tx <id>` — every row of one transaction (shows it nets to zero).
- `!admin suspicious @user` — flags rapid toggles, blocked reactions, negative
  inventory, abnormal daily totals, and reconciliation mismatches.

### 8. Upgraded `!admin export`
- Now includes `economy_ledger`, `security_log`, `game_matches`, plus a
  `per_user_summary` and a guild-wide `reconciliation` report.

### 9. Tests
- `test_migrations.py` — fresh build + in-place upgrade of an existing DB.
- `test_import_real_export.py` — imports the real 143k-row export.
- `test_exploits.py` — 31 assertions covering every required scenario.
- `test_stress.py` — mixed concurrency storm; full reconciliation + conservation.
- `test_legacy_continuity.py` — legacy balances preserved; new activity tracked.
- `test_boot_sim.py` — full bot wiring against the real DB.

---

## Database / migration safety

- Migrations 210–214 are additive (`ALTER ADD COLUMN` + `CREATE TABLE IF NOT
  EXISTS`). The runner tolerates a re-applied `ADD COLUMN` ("duplicate column")
  so re-connecting is idempotent.
- Verified: the shipped DB at migration 209 upgrades to 214 with all data
  intact, and the real production export imports with every row count preserved.
- **Reconciliation note:** balances that existed *before* this release won't sum
  to the (initially empty) ledger — that history predates it. Every change from
  now on is fully tracked, so going forward all balances reconcile. The export's
  reconciliation report makes this explicit per user.
