# Ignio (Sob Edition)

A focused Discord bot for the **sob** system: sob reactions, leaderboards, and snitch tokens.

## What it does
- React to a message with a sob emoji to give that person a sob.
- Track daily / weekly / all-time sob counts and ranks.
- Earn **snitch tokens** (one per N sobs received); reply `!ss` to wipe all sobs from a message.
- Leaderboards: top sob receivers (today / week / all-time), top giver, top snitch.

## Commands
User:
- `!sob` — your personal stats
- `!sob lb` — server leaderboard
- `!sob help` — help
- `!ss` (reply to a message) — use a snitch token

Owner-only admin (IDs in `DEV_OWNER_IDS` / `OWNER_IDS`), all replies are embeds:
- `!admin` / `!admin whoami` — menu / confirm your access
- `!admin stats` — database overview
- `!admin config` — this server's settings (threshold, emojis, tracked users)
- `!admin servers` — list servers with data
- `!admin givesob @user <n>` (`gs`) — add/remove sobs (negative removes)
- `!admin givetoken @user [n]` (`gt`) — grant a snitch token
- `!admin reset @user` — wipe a user's sobs in this server
- `!admin recount` — rebuild all-time totals from raw reactions (recovery tool)
- `!admin threshold [n]` — view or set snitch threshold (per server)
- `!admin emoji list|add <name>|remove <name>` — manage accepted sob emojis (per server)
- `!admin export [guild_id]` — export a server's data to a JSON file
- `!admin import merge|replace [guild_id]` — import an attached export file

(Dev prefix is `!!`, prod prefix is `!`.)

## Layout
```
ignio/
├── main.py             # entry point
├── bot.py              # bot setup, events, run()
├── config.py           # settings + emoji map (dev/prod tokens & prefix)
├── requirements.txt
└── core/
    ├── db.py           # aiosqlite wrapper + migration runner
    ├── schema.py       # clean sob tables + safe legacy backfill
    ├── backup.py       # automatic timestamped DB backup on startup
    ├── transfer.py     # per-server export / import tooling
    ├── time_utils.py   # day_key / week_key helpers
    ├── sob/
    │   ├── repo.py     # all sob DB access
    │   ├── cog.py      # commands + reaction listeners
    │   └── embeds.py   # embed builders
    └── admin/
        └── cog.py      # owner-only export/import/stats commands
```

## Database
ONE database, shared tables, partitioned by `guild_id` (idiomatic SQL). Query a
single server with `WHERE guild_id = ?`. Tables:
- `sob_users`   — per-user totals + snitch token state ("people")
- `sob_events`  — live sob reactions (for removal + snitching)
- `sob_periods` — daily/weekly rollups (one table, `period_type` = 'day'|'week')
- plus shared `guilds`, `users`, `guild_settings`

### Moving one server's data
Use `core/transfer.py` (or the `!admin export` / `!admin import` commands) to
pull a single guild's complete sob data into a portable JSON file and load it
back into the same or a different database. Import is idempotent (`merge`) or
can wipe-and-replace that guild's rows (`replace`), and can re-home data under a
different guild id for cloning. This is the safe "per-server" workflow without
fragmenting the schema into one-table-per-server.

## Migrating from the OLD (streak+sob) database
On first boot against the legacy Railway DB, migrations 200/201/202 run:
- 200: ensure shared infra tables exist
- 201: create the clean sob tables
- 202: copy legacy `sob_stats` / `sob_daily` / `sob_weekly` / `sob_reactions` /
  `sob_snitch` into the new tables

The backfill is **idempotent**, **non-destructive** (legacy tables are never
dropped or altered), and a **no-op on fresh installs**. New migration versions
start at 200 so they never collide with the legacy 1/2/3 already recorded.

Verified against real production data (619 users / 130,300 sobs): every per-user
count, snitch token, and leaderboard position matched exactly, zero mismatches.

## Env vars
- `IGNIO_ENV` = `dev` | `prod`
- `DISCORD_TOKEN_DEV`, `DISCORD_TOKEN_PROD` (or `DISCORD_TOKEN` fallback)
- `COMMAND_PREFIX_DEV` (default `!!`), `COMMAND_PREFIX_PROD` (default `!`)
- `DB_DIR` (e.g. `/data/database` on Railway) — **must point at the volume in prod**
- `SNITCH_THRESHOLD` (default 10)
- `DB_BACKUP_ON_START` (default on in prod) — auto-backup DB before migrations

## Sob Shop
A competitive shop built around the snitch system. Spend sobs (which lowers
your leaderboard score — a real tradeoff) on items you hold in inventory and
activate when the moment is right.

Categories & basic items (all 30-minute effects):
- 🛡️ **Protection — Basic Shield** (50 sobs): protects you from snitches.
- ❄️ **Debuff — Basic Freeze** (75 sobs): target a rival; they can't snitch.
- ⚡ **Buff — Basic Boost** (40 sobs): your snitches push you toward your next token.
- 🎁 **Server Items**: custom rewards (Nitro, gift cards, roles…) that owners/admins
  add. Buying puts the item in the user's inventory; using it submits a claim for
  an admin to fulfill.

Interactions: shield blocks an incoming snitch and the attacker still loses their
token (snitching is a gamble); freeze blocks the frozen user from snitching; same
effect doesn't stack, different effects coexist.

User commands: `!shop`, `!shop buy <item> [qty]`, `!inventory` (`!inv`),
`!use <item> [@user]`, `!effects [@user]`, `!shop help`.

Owner/admin commands: `!shop additem <key> <price> <name...>`,
`!shop setstock <key> <n>` (-1 = unlimited), `!shop removeitem <key>`.

Storage: new tables `shop_inventory`, `active_effects`, `shop_items` (migration
203, purely additive — existing data untouched).
