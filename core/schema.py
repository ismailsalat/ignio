# core/schema.py
"""
Database schema + migrations for Ignio (sob-only edition).

Design goals
------------
1. Clean, sob-focused table layout. Two logical groups:
     - "people" data    -> sob_users        (per-user totals & snitch state)
     - "sob info" data  -> sob_events        (one row per individual sob reaction)
                           sob_periods       (rolled-up daily/weekly counts)
   Plus the shared infra tables we keep: guilds, users, guild_settings.

2. Cross-compatible with the OLD Railway database. The legacy DB has tables
   named sob_stats / sob_daily / sob_weekly / sob_reactions / sob_snitch.
   Migration 100 copies that data into the new tables IF the legacy tables
   exist. It is:
     - idempotent  (INSERT OR IGNORE; safe to run more than once)
     - additive    (never drops or alters legacy tables)
     - a no-op     on fresh installs (legacy tables simply aren't there)

   The legacy tables are left completely untouched, so the old bot could in
   theory still read them. Nothing is destroyed.

Migration runner contract (see core/db.py):
    MIGRATIONS is a list of (version:int, name:str, sql:str).
    Each runs once, tracked in schema_migrations. Versions only ever go up.
"""

# ---------------------------------------------------------------------------
# Migration 1: shared infrastructure we keep from the old schema.
# Same table definitions as before so an existing DB sees them as already
# present (CREATE TABLE IF NOT EXISTS = no-op there).
# ---------------------------------------------------------------------------

_INFRA = """
CREATE TABLE IF NOT EXISTS guilds (
    guild_id   INTEGER PRIMARY KEY,
    name       TEXT,
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS users (
    user_id    INTEGER PRIMARY KEY,
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS guild_settings (
    guild_id   INTEGER NOT NULL,
    key        TEXT NOT NULL,
    value      TEXT NOT NULL,
    updated_at INTEGER NOT NULL,

    PRIMARY KEY (guild_id, key)
);
"""

# ---------------------------------------------------------------------------
# Migration 2: the clean sob tables (the new home for all sob data).
# ---------------------------------------------------------------------------

_SOB_CORE = """
-- Per-user, per-guild rollup: lifetime totals + snitch token state.
-- This is the "people" table.
CREATE TABLE IF NOT EXISTS sob_users (
    guild_id              INTEGER NOT NULL,
    user_id               INTEGER NOT NULL,

    sobs_received_alltime INTEGER NOT NULL DEFAULT 0,
    sobs_given_alltime    INTEGER NOT NULL DEFAULT 0,

    -- snitch token state
    token_available       INTEGER NOT NULL DEFAULT 0,
    sobs_at_last_grant    INTEGER NOT NULL DEFAULT 0,
    token_granted_at      INTEGER NOT NULL DEFAULT 0,
    total_snitches        INTEGER NOT NULL DEFAULT 0,

    updated_at            INTEGER NOT NULL,

    PRIMARY KEY (guild_id, user_id)
);

-- One row per individual sob reaction currently live on a message.
-- This is the raw "sob info" / event log used for removal + snitching.
CREATE TABLE IF NOT EXISTS sob_events (
    guild_id   INTEGER NOT NULL,
    message_id INTEGER NOT NULL,
    reactor_id INTEGER NOT NULL,
    target_id  INTEGER NOT NULL,
    created_at INTEGER NOT NULL,

    PRIMARY KEY (guild_id, message_id, reactor_id)
);

-- Rolled-up counts per user per time bucket. period_type is 'day' or 'week'.
-- period_key is an ordinal day (date.toordinal) or week key (ISO yyyy*100+ww).
-- Combining daily + weekly into one table keeps the schema small.
CREATE TABLE IF NOT EXISTS sob_periods (
    guild_id      INTEGER NOT NULL,
    user_id       INTEGER NOT NULL,
    period_type   TEXT NOT NULL CHECK (period_type IN ('day','week')),
    period_key    INTEGER NOT NULL,
    sobs_received INTEGER NOT NULL DEFAULT 0,
    updated_at    INTEGER NOT NULL,

    PRIMARY KEY (guild_id, user_id, period_type, period_key)
);

CREATE INDEX IF NOT EXISTS idx_sob_users_received
    ON sob_users(guild_id, sobs_received_alltime DESC);
CREATE INDEX IF NOT EXISTS idx_sob_users_given
    ON sob_users(guild_id, sobs_given_alltime DESC);
CREATE INDEX IF NOT EXISTS idx_sob_users_snitch
    ON sob_users(guild_id, total_snitches DESC);

CREATE INDEX IF NOT EXISTS idx_sob_events_message
    ON sob_events(guild_id, message_id);

CREATE INDEX IF NOT EXISTS idx_sob_periods_lookup
    ON sob_periods(guild_id, period_type, period_key, sobs_received DESC);
"""

# ---------------------------------------------------------------------------
# Migration 100: one-time, safe copy of legacy data into the new tables.
#
# Each statement is guarded by the legacy table existing. SQLite can't do
# "INSERT ... SELECT FROM maybe_missing_table" conditionally in pure SQL, so
# the runner checks for the table first (see core/db.py _run_migrations,
# which tolerates "no such table" inside a migration by skipping that stmt).
#
# To keep this purely declarative AND safe, we instead rely on the legacy
# tables being present together (they always are on Railway, since migrations
# 2 & 3 of the OLD schema created all of them in one shot). On a fresh DB none
# exist and the whole block is skipped by the runner's table-existence guard.
# ---------------------------------------------------------------------------

_LEGACY_BACKFILL = """
-- received/given lifetime totals  ->  sob_users
INSERT OR IGNORE INTO sob_users
    (guild_id, user_id, sobs_received_alltime, sobs_given_alltime,
     token_available, sobs_at_last_grant, token_granted_at, total_snitches, updated_at)
SELECT
    s.guild_id,
    s.user_id,
    s.sobs_received_alltime,
    s.sobs_given_alltime,
    0, 0, 0, 0,
    s.updated_at
FROM sob_stats AS s;

-- fold legacy snitch state onto the same sob_users rows
UPDATE sob_users
SET token_available    = COALESCE((SELECT sn.token_available    FROM sob_snitch sn
                                    WHERE sn.guild_id = sob_users.guild_id
                                      AND sn.user_id  = sob_users.user_id), token_available),
    sobs_at_last_grant = COALESCE((SELECT sn.sobs_at_last_grant FROM sob_snitch sn
                                    WHERE sn.guild_id = sob_users.guild_id
                                      AND sn.user_id  = sob_users.user_id), sobs_at_last_grant),
    token_granted_at   = COALESCE((SELECT sn.token_granted_at   FROM sob_snitch sn
                                    WHERE sn.guild_id = sob_users.guild_id
                                      AND sn.user_id  = sob_users.user_id), token_granted_at),
    total_snitches     = COALESCE((SELECT sn.total_snitches     FROM sob_snitch sn
                                    WHERE sn.guild_id = sob_users.guild_id
                                      AND sn.user_id  = sob_users.user_id), total_snitches)
WHERE EXISTS (SELECT 1 FROM sob_snitch sn
              WHERE sn.guild_id = sob_users.guild_id
                AND sn.user_id  = sob_users.user_id);

-- snitch rows that had no matching sob_stats row (edge case): insert them too
INSERT OR IGNORE INTO sob_users
    (guild_id, user_id, sobs_received_alltime, sobs_given_alltime,
     token_available, sobs_at_last_grant, token_granted_at, total_snitches, updated_at)
SELECT
    sn.guild_id, sn.user_id, 0, 0,
    sn.token_available, sn.sobs_at_last_grant, sn.token_granted_at, sn.total_snitches,
    sn.updated_at
FROM sob_snitch AS sn;

-- live reactions  ->  sob_events
INSERT OR IGNORE INTO sob_events
    (guild_id, message_id, reactor_id, target_id, created_at)
SELECT guild_id, message_id, reactor_id, target_id, created_at
FROM sob_reactions;

-- daily rollups  ->  sob_periods (period_type='day')
INSERT OR IGNORE INTO sob_periods
    (guild_id, user_id, period_type, period_key, sobs_received, updated_at)
SELECT guild_id, user_id, 'day', day_key, sobs_received, updated_at
FROM sob_daily;

-- weekly rollups  ->  sob_periods (period_type='week')
INSERT OR IGNORE INTO sob_periods
    (guild_id, user_id, period_type, period_key, sobs_received, updated_at)
SELECT guild_id, user_id, 'week', week_key, sobs_received, updated_at
FROM sob_weekly;
"""


# ---------------------------------------------------------------------------
# Migration 203: shop system (inventory + active effects + per-guild catalog).
# Purely additive — only CREATE TABLE IF NOT EXISTS, never touches existing data.
# ---------------------------------------------------------------------------

_SHOP = """
-- What each user currently owns (held, not yet used). Quantity per item.
CREATE TABLE IF NOT EXISTS shop_inventory (
    guild_id   INTEGER NOT NULL,
    user_id    INTEGER NOT NULL,
    item_key   TEXT NOT NULL,
    quantity   INTEGER NOT NULL DEFAULT 0,
    updated_at INTEGER NOT NULL,

    PRIMARY KEY (guild_id, user_id, item_key)
);

-- Live buffs/debuffs. effect_key e.g. 'shield','freeze','boost'.
-- expires_at = 0 means "until consumed" (one-shot, e.g. shield).
-- target_user_id is who the effect is ON (the shielded/frozen/boosted user).
CREATE TABLE IF NOT EXISTS active_effects (
    effect_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id       INTEGER NOT NULL,
    target_user_id INTEGER NOT NULL,
    effect_key     TEXT NOT NULL,
    source_user_id INTEGER NOT NULL DEFAULT 0,
    expires_at     INTEGER NOT NULL DEFAULT 0,
    created_at     INTEGER NOT NULL
);

-- Per-guild custom catalog overrides / additions (Server Items live here).
-- Built-in items (shield/freeze/boost) are defined in code; this table lets
-- owners add their own products and override price/stock later.
CREATE TABLE IF NOT EXISTS shop_items (
    guild_id   INTEGER NOT NULL,
    item_key   TEXT NOT NULL,
    name       TEXT NOT NULL,
    category   TEXT NOT NULL,
    icon       TEXT NOT NULL DEFAULT '',
    price      INTEGER NOT NULL,
    stock      INTEGER NOT NULL DEFAULT -1,  -- -1 = unlimited
    enabled    INTEGER NOT NULL DEFAULT 1,
    description TEXT NOT NULL DEFAULT '',
    updated_at INTEGER NOT NULL,

    PRIMARY KEY (guild_id, item_key)
);

CREATE INDEX IF NOT EXISTS idx_active_effects_lookup
    ON active_effects(guild_id, target_user_id, effect_key);
CREATE INDEX IF NOT EXISTS idx_shop_inventory_user
    ON shop_inventory(guild_id, user_id);
"""


# NOTE on version numbers:
# The OLD database already has schema_migrations rows for versions 1, 2, 3
# (the legacy streak + sob migrations). To avoid colliding with those — which
# would make these get skipped as "already applied" — the new schema starts at
# 200. On a fresh DB these simply run in order; on the old DB they run *after*
# the legacy 1/2/3, creating the clean tables and backfilling from legacy data.

# Economy snapshots: one row per guild per day, recording total sob supply so the
# !economy command can show an inflation trend graph. Purely additive.
_ECONOMY = """
CREATE TABLE IF NOT EXISTS economy_snapshots (
    guild_id   INTEGER NOT NULL,
    day        TEXT    NOT NULL,          -- YYYY-MM-DD (UTC)
    total_sobs INTEGER NOT NULL DEFAULT 0,
    players    INTEGER NOT NULL DEFAULT 0,
    created_at INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (guild_id, day)
);
"""


# Daily claim tracking: last claim time + streak per user per guild. Additive.
_DAILY = """
CREATE TABLE IF NOT EXISTS daily_claims (
    guild_id    INTEGER NOT NULL,
    user_id     INTEGER NOT NULL,
    last_claim  INTEGER NOT NULL DEFAULT 0,
    streak      INTEGER NOT NULL DEFAULT 0,
    total_claimed INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (guild_id, user_id)
);
"""


# Tax events: log of each tax payment for the treasury stats card. Additive.
_TAX_LOG = """
CREATE TABLE IF NOT EXISTS tax_events (
    guild_id   INTEGER NOT NULL,
    user_id    INTEGER NOT NULL,
    amount     INTEGER NOT NULL,
    created_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_tax_events_guild ON tax_events(guild_id, created_at);
"""


# Audit log: tracks audit steals per target per day for anti-gang-up immunity,
# and feeds the upgraded export. Additive.
_AUDIT_LOG = """
CREATE TABLE IF NOT EXISTS audit_events (
    guild_id   INTEGER NOT NULL,
    target_id  INTEGER NOT NULL,
    auditor_id INTEGER NOT NULL,
    amount     INTEGER NOT NULL,
    day        TEXT    NOT NULL,
    created_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_audit_target_day ON audit_events(guild_id, target_id, day);
"""


# Game matches: logs every PvP game (roulette, future coinflip/blackjack/etc).
# Additive. Powers stats + !admin export.
_GAME_LOG = """
CREATE TABLE IF NOT EXISTS game_events (
    guild_id    INTEGER NOT NULL,
    game        TEXT    NOT NULL,
    challenger  INTEGER NOT NULL,
    opponent    INTEGER NOT NULL,
    wager       INTEGER NOT NULL,
    winner      INTEGER NOT NULL,
    loser       INTEGER NOT NULL,
    tax         INTEGER NOT NULL DEFAULT 0,
    created_at  INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_game_events_guild ON game_events(guild_id, created_at);
"""

MIGRATIONS = [
    (200, "infra_keep", _INFRA),
    (201, "sob_clean_tables", _SOB_CORE),
    (202, "backfill_legacy_sob", _LEGACY_BACKFILL),
    (203, "shop_system", _SHOP),
    (204, "economy_snapshots", _ECONOMY),
    (205, "daily_claims", _DAILY),
    (206, "tax_events", _TAX_LOG),
    (207, "audit_events", _AUDIT_LOG),
    (208, "game_events", _GAME_LOG),
]

# Legacy tables the backfill reads from. The migration runner skips the
# backfill statements gracefully if these don't exist (fresh install).
LEGACY_SOURCE_TABLES = (
    "sob_stats",
    "sob_snitch",
    "sob_reactions",
    "sob_daily",
    "sob_weekly",
)
