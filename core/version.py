# core/version.py
"""
Bot version + patch notes. EDIT THIS FILE EACH RELEASE.

- Bump VERSION.
- Add a new entry to the TOP of CHANGELOG (newest first).
Used by !version (simple) and !about (full).
"""
from __future__ import annotations

VERSION = "1.4.3"
RELEASED = "2026-06-29"        # date of this version (YYYY-MM-DD)
CODENAME = "Steal & Ship Update"

# Newest first. Keep each entry short. 'notes' is a list of bullet lines.
CHANGELOG = [
    {
        "version": "1.4.3",
        "date": "2026-06-29",
        "title": "Sob-Ship is random + flavor",
        "notes": [
            "!sobship now rolls a fresh random score every time (no more same number)",
            "Each result gets a fun one-line flavor under the verdict",
            "Names stay in clean chips; no overlap at any length",
        ],
    },
    {
        "version": "1.4.2",
        "date": "2026-06-29",
        "title": "Sob-Ship layout polish",
        "notes": [
            "!sobship names now sit in clean side-by-side chips with a heart divider",
            "Names can never overlap the heart anymore, no matter how long they are",
            "Card is taller and more spacious; verdict pill sizes to fit its text",
        ],
    },
    {
        "version": "1.4.1",
        "date": "2026-06-29",
        "title": "Sob-Ship UI fix",
        "notes": [
            "!sobship now handles every name size cleanly — long Discord names are",
            "  truncated per-name and the font shrinks a step so two names always fit",
            "Very short names, emoji, and exotic glyphs all render without overflow",
        ],
    },
    {
        "version": "1.4.0",
        "date": "2026-06-29",
        "title": "Steal & Ship Update",
        "notes": [
            "Steal rebalanced to be FUN: ~45% win chance — you win and lose often",
            "Each steal is smaller (1%) so it's addictive but never a money farm",
            "10 attempts/day, 5-min cooldown, 90-min same-target lockout (spread the love)",
            "Steal can now be turned off with !disable games or !admin steal off",
            "Shop picture now shows the new STEAL category (Lockpick + Safe Lock)",
            "Safe Lock (the anti-steal item) is in the shop, risk-priced, expires in 24h",
            "NEW !admin item give/take @user <item> [qty] — manage anyone's bag",
            "NEW !sobship @user — a fun animated love-meter (no sobs involved!)",
            "All command categories fixed so everything shows in !help and can be disabled",
        ],
    },
    {
        "version": "1.3.2",
        "date": "2026-06-29",
        "title": "Earning rebalance + UI cleanup",
        "notes": [
            "Natural earning matters more: reactions now pay ~7 sobs (was 3), floor raised to 5",
            "Reference balance now tracks the ACTIVE economy (p65), not the PvP-drained median",
            "Snitch now steals 45% of a message pool (was 50%) - creators keep more",
            "Leaderboard & cards no longer show ☐ boxes for exotic-glyph names",
            "Long server nicknames are cleanly ellipsized instead of overlapping scores",
            "Emoji and unrenderable glyphs are stripped from names on every card",
            "!sob profile card is unchanged (it was already perfect)",
        ],
    },
    {
        "version": "1.3.1",
        "date": "2026-06-29",
        "title": "Earning balance fix",
        "notes": [
            "Fixed the 'extra sobs' issue: each reaction was worth 9 sobs, now worth 3",
            "Cause was the new-server multiplier boost misfiring on an established server",
            "The boost now only applies to genuinely new servers (few active earners),",
            "  not mature ones whose median looks low because of snitch/audit/steal draining",
            "The crying emoji stays a valid sob emoji - it was never the bug",
        ],
    },
    {
        "version": "1.3.0",
        "date": "2026-06-29",
        "title": "Steal Update (risky PvP gamble)",
        "notes": [
            "NEW !steal @user - a high-risk gamble to steal sobs (under Games)",
            "Low 18% odds, capped at 1.25% per hit and 4% of a target per day",
            "Win: take a slice of their sobs (90% to you, 10% treasury)",
            "Lose: pay a caught fee (half treasury, half burned) - target loses nothing",
            "Hard limits: 4 attempts/day, 15-min cooldown, 60-min per-target, 30-min victim immunity",
            "NEW Lockpick (+4% odds, one use) and Safe Lock (-5% incoming, 20 min) - risk-priced, expire in 24h",
            "!steal stats and steal profit/loss now shown in !sob stats",
            "Admins: !admin steal on/off and !admin steal config",
            "Balanced by a 7-day sim: steal stays break-even and never beats getting sobbed",
            "Guard added: can no longer accept everyday emojis (sob, the crying face) that minted sobs by accident",
        ],
    },
    {
        "version": "1.2.0",
        "date": "2026-06-29",
        "title": "Protection Update (risk-based shields)",
        "notes": [
            "Protection is now priced from YOUR own risk, never above the damage it prevents",
            "Audit Ward, Shield, Guardian, Reflect now cost a fair fraction of what you'd lose",
            "NEW Vault Ward - blocks Basic Audits AND Grand Heists (best for rich players)",
            "Protection prices scale with your balance: small players afford it, rich pay more",
            "Uses your 24h high balance, so you can't dump sobs to buy cheap protection",
            "Bulk-bought protection expires in 24h (no stockpiling cheap shields)",
            "!sob stats now shows your audit risk + the recommended ward to buy",
            "Protection isn't taxed (it's defensive); prices auto-tune daily within safe limits",
            "Admins: !admin protection to view/override the protection price factor",
        ],
    },
    {
        "version": "1.1.1",
        "date": "2026-06-29",
        "title": "Control Update hotfix",
        "notes": [
            "Fixed !sob stats showing the profile card instead of the stats picture",
            "Shield reminder is now quieter: opt-out button + !sob tips on/off, max once every 6h, no ping",
        ],
    },
    {
        "version": "1.1.0",
        "date": "2026-06-29",
        "title": "Control Update (audit limits, stats, admin controls)",
        "notes": [
            "NEW !sob stats - a picture showing where your sobs come from + your audit allowance",
            "Audit daily cap: each person can only audit a set number of times per day",
            "Audit cooldown: a wait between a person's audits (stops one player draining everyone)",
            "Get audited a lot? The bot nudges you (dismissible) to buy a Shield",
            "Admins: !admin auditcap <n> and !admin auditcd <seconds> to tune audits",
            "Admins: !admin shop on/off, !admin item disable/enable, !admin category disable/enable",
            "Rewrote !guide into a clear, actionable how-to (real commands + how to protect yourself)",
            "Every command now shows up in !help (admin help split into clean sections)",
            "New limit/suggestion screens are pictures, not embeds - simple and clean",
        ],
    },
    {
        "version": "1.0.0",
        "date": "2026-06-28",
        "title": "Integrity Update (security + economy audit)",
        "notes": [
            "Fixed sob duplication: reactions store their exact credited value; "
            "removal & snitch refund that exact amount (no more minting via toggles)",
            "All economy actions are now atomic DB transactions (BEGIN IMMEDIATE) "
            "with conditional updates — concurrent buy/use/daily/snitch can't double-spend",
            "Inventory can never go negative; balances can never go below zero",
            "Russian Roulette now uses real escrow — both wagers are locked, refunded "
            "on timeout/decline/error/restart, and can't be spent mid-match",
            "Hunter's Blessing, Guardian, Reflect, King, Marked, Slow & Lucky now "
            "actually enforced; any unenforceable item is auto-disabled in the shop",
            "Alt-block is real: configurable account-age/join-age/rate-limit and "
            "reciprocal-farm detection, with a security log of every blocked reaction",
            "NEW permanent append-only economy ledger — every sob earned/lost/spent/"
            "transferred is recorded with full double-entry detail",
            "NEW !admin audit @user <page> (ledger history), !admin audit tx <id> "
            "(one transaction), !admin suspicious @user (exploit flags)",
            "!admin export now includes the full ledger, security log, game escrow "
            "history and a balance-vs-ledger reconciliation report",
            "Treasury can't be double-spent; treasury/burn counters are race-safe",
            "Every balance can be reconciled from the ledger going forward",
        ],
    },
    {
        "version": "0.9.0",
        "date": "2026-06-28",
        "title": "Competitive Update",
        "notes": [
            "Snitching is now the main way to earn: reward + steal, scaled to economy",
            "Sobs are worth real value now (not just 1) — worth protecting",
            "Tax Audit reworked: Basic (blockable) + Grand Heist (crits through shields)",
            "Anti-gang-up: heavy audit losses make you immune for the day",
            "Shields are now per-second — buy in bulk, !use shield <seconds>",
            "Rich players are at real risk — must spend to stay protected",
            "Every item rebalanced & auto-priced by power and economy",
            "Fixed !eco inflation graph (recent change, not lifetime) + dates",
            "!admin export now includes all economy data for tuning",
            "NEW Games category — Russian Roulette PvP (!roulette @user <amount>)",
            "Anti-exploit: !admin audit traces where a user's sobs came from",
            "!admin freeze pauses all earning in emergencies",
            "!admin altblock flags/blocks alt-farm reactions (new/inactive accounts)",
            "!admin auditexport @user — full JSON for AI exploit analysis",
            "!admin weekly — weekly farm-pair report",
        ],
    },
    {
        "version": "0.8.2",
        "date": "2026-06-28",
        "title": "Treasury Update",
        "notes": [
            "Shop tax now adds ON TOP and feeds a server treasury (pot)",
            "Tax auto-adjusts to your economy (admins can override: !tax)",
            "!treasury shows the pot + stats; !treasury give pays players",
            "!rebalance refreshes shop prices on demand (locked between)",
            "Fixed shop showing wrong prices vs what was charged",
            "New !guide — explains how the bot works for newcomers",
        ],
    },
            {
        "version": "0.8.0",
        "date": "2026-06-28",
        "title": "Economy Update",
        "notes": [
            "!daily faucet with streak bonus + picture card",
            "Auto-balancing shop: prices scale to YOUR server economy",
            "Sob multiplier: reactions worth more on new/small servers",
            "30% shop tax burns sobs (anti-inflation sink) — !tax",
            "Exchange rate tools: !rate, !value, !worth, !economy",
            "16 PvP items: shields, freezes, boosts, Tax Audit, King & more",
            "Custom sob & fire icons, premium picture cards",
            "Cleaner image !help with admin tags, one-time update notice",
        ],
    },
    {
        "version": "0.7.2",
        "date": "2026-06-27",
        "title": "Cleaner Names",
        "notes": [
            "Profile & leaderboard cards no longer show boxes for emoji names",
            "Names with emojis are cleaned; non-Latin names use the @username",
        ],
    },
    {
        "version": "0.7.1",
        "date": "2026-06-27",
        "title": "Leaderboard Cards",
        "notes": [
            "!sob lb now shows an image leaderboard card (top 10 + leaders)",
            "Falls back to the classic embed if the card fails",
            "Admins get a heads-up when using a command thats disabled for others",
        ],
    },
    {
        "version": "0.7.0",
        "date": "2026-06-26",
        "title": "Profile Update",
        "notes": [
            "New image profile card on !sob and !sob @user",
            "Customize your card: !sob set background / color",
            "Browse options: !sob backgrounds and !sob colors",
            "Free backgrounds for all; premium ones owner-only (purchasable later)",
            "Owner kill-switch: !admin profile on/off (falls back to embed)",
            "Per-channel command control: !disable / !enable by category or command",
            "!commandconfig shows what's disabled where",
            "Interactive !help with buttons for each area",
            "!about and !version added",
        ],
    },
    {
        "version": "0.6.7",
        "date": "2026-06-20",
        "title": "Permissions & Announcements",
        "notes": [
            "Role permissions: grant sob/token/shop powers to roles (!perms)",
            "!announce for posting embed announcements with optional pings",
        ],
    },
    {
        "version": "0.6.5",
        "date": "2026-06-15",
        "title": "Shop & Snitch Economy",
        "notes": [
            "Sob shop with Shield, Freeze, Boost",
            "Claim notifications for server items",
        ],
    },
]


def latest() -> dict:
    return CHANGELOG[0] if CHANGELOG else {"version": VERSION, "date": RELEASED, "notes": []}
