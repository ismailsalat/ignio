# core/version.py
"""
Bot version + patch notes. EDIT THIS FILE EACH RELEASE.

- Bump VERSION.
- Add a new entry to the TOP of CHANGELOG (newest first).
Used by !version (simple) and !about (full).
"""
from __future__ import annotations

VERSION = "2.0.0"
RELEASED = "2026-06-29"        # date of this version (YYYY-MM-DD)
CODENAME = "Caption via source page"

# Newest first. Keep each entry short. 'notes' is a list of bullet lines.
CHANGELOG = [
    {
        "version": "2.0.0",
        "date": "2026-06-30",
        "title": "Caption via source page + Discord proxy",
        "notes": [
            "Root cause nailed: the embed thumbnail/video were 840-byte PREVIEW STUBS,",
            "  and Klipy tier-swaps all 404. The real animation is on the Klipy PAGE.",
            "Now resolves the embed page url (klipy.com/gifs/...) to real og:video/og:image",
            "Also tries Discord's proxy_url (its cached full copy) before the raw stub",
            "Removed the tier-guessing that produced 404 spam",
        ],
    },
    {
        "version": "1.9.9",
        "date": "2026-06-30",
        "title": "Caption: Klipy tiers + full embed debug",
        "notes": [
            "Root cause found: the embed URLs were tiny Klipy PREVIEW stubs (840 bytes),",
            "  not the real animation — ffmpeg correctly reported no video packets",
            "Now expands Klipy static URLs to larger tiers (hd/gif/lg) + .gif/.mp4 variants",
            "Added a FULL embed dump (every field + raw dict) so remaining cases are clear",
        ],
    },
    {
        "version": "1.9.8",
        "date": "2026-06-30",
        "title": "Caption conversion diagnostics + robustness",
        "notes": [
            "video->gif now logs downloaded bytes/content-type and ffmpeg errors",
            "detects HTML error pages (blocked downloads) instead of feeding ffmpeg junk",
            "even dimensions (scale -2), no audio, and a simpler retry pass",
            "sends a Referer/Accept header to fetch Klipy/Tenor media reliably",
        ],
    },
    {
        "version": "1.9.7",
        "date": "2026-06-30",
        "title": "Caption webp/mp4 + host diagnostics",
        "notes": [
            "!caption: animated webp (Klipy/Tenor) that Pillow cannot decode is now",
            "  routed through the ffmpeg mp4->gif fallback as well",
            "Boot log prints host caps: ffmpeg / pillow_webp / yt_dlp so missing tools",
            "  are obvious (a missing ffmpeg is the usual caption+download blocker)",
            "Clear logs when ffmpeg is absent or a conversion produces no output",
        ],
    },
    {
        "version": "1.9.6",
        "date": "2026-06-30",
        "title": "Tenor caption via ffmpeg",
        "notes": [
            "!caption on Tenor GIFs now works even when Tenor serves a format PIL",
            "  cannot read: it downloads the mp4 Tenor always provides and converts",
            "  it to a GIF with ffmpeg, then captions that",
            "Added per-candidate logging so any remaining case is fully diagnosable",
        ],
    },
    {
        "version": "1.9.5",
        "date": "2026-06-30",
        "title": "Tenor GIF caption fix",
        "notes": [
            "!caption now works on Tenor / GIF-picker GIFs (the common case!)",
            "Resolves the Tenor page to the real animated .gif; never tries the .mp4",
            "(the .mp4 was causing the OSError/UnidentifiedImageError in your logs)",
            "Constructs c.tenor.com/<id>/tenor.gif as a reliable fallback; follows redirects",
        ],
    },
    {
        "version": "1.9.4",
        "date": "2026-06-30",
        "title": "Media trigger fix + aliases",
        "notes": [
            "Video download now triggers ONLY on '@Ignio <one-url>' (strict, anchored)",
            "Replies, mid-sentence mentions, extra text, and 2+ urls never trigger it",
            "Reply commands (!tldr/!song/!caption/!xray) still work as before",
            "Added short aliases: !w (weather) !cap (caption) !x (xray) !tl (tldr) !q (quote)",
        ],
    },
    {
        "version": "1.9.3",
        "date": "2026-06-30",
        "title": "Caption fix",
        "notes": [
            "!caption now ONLY uses the message you replied to (no channel scanning)",
            "Fixes captioning the wrong image and stacking captions on bot output",
            "More robust attachment detection (width/height) + clear debug logging",
        ],
    },
    {
        "version": "1.9.2",
        "date": "2026-06-30",
        "title": "Caption + map + quote polish",
        "notes": [
            "!caption: more robust image/GIF finder (resolved reply, attachment bytes,",
            "  Tenor resolve, nearby-message fallback) with full debug logging",
            "!quote: now a clean Twitter/X-style card with verified badge, @handle,",
            "  and realistic engagement (reposts/likes/views)",
            "!map: fixed white left border at low zoom (tiles wrap the globe; ocean bg)",
            "Video download: faster + more formats (concurrent fragments, browser UA,",
            "  more fallbacks) — still public-only, no proxies/bypasses/cookies",
            "!tldr: now uses the post caption/title from embeds when there's no transcript",
        ],
    },
    {
        "version": "1.9.1",
        "date": "2026-06-30",
        "title": "Utilities Polish",
        "notes": [
            "!caption now works on Tenor GIFs + GIF-picker embeds; preserves animation",
            "  (clean first-frame fallback when a GIF is too large to render safely)",
            "!map: zoom now matches the place (country/state/city) using the result bounds;",
            "  cleaner info card (Located in / Coordinates / Requested by), no Open-in-Maps",
            "Media download: clean message when TikTok blocks the server IP (no crash/spam);",
            "  success now posts a compact source card with creator + Original post link",
            "!tldr + !catchup: rewritten prompts — natural, specific, no Main/Key/Why filler",
            "AFK: cuter, cleaner confirmation + away notice with friendly duration",
        ],
    },
    {
        "version": "1.9.0",
        "date": "2026-06-30",
        "title": "Media Download",
        "notes": [
            "NEW @Ignio (reply to a video link) downloads the public video as an attachment",
            "Works for TikTok, Instagram, X/Twitter, Reddit, YouTube, Facebook, Streamable, direct mp4",
            "Only runs on an explicit @mention; never auto-downloads links",
            "yt-dlp powered; public media only (no logins/cookies/private/DRM/age-gated)",
            "Per-user cooldown + 1 active/user + guild concurrency cap; temp files always deleted",
            "SSRF-guarded; URLs redacted in logs; respects the Discord upload-size limit",
            "Also fixed: !caption now reads GIFs/attachments directly; clearer media errors",
        ],
    },
    {
        "version": "1.8.3",
        "date": "2026-06-29",
        "title": "Utilities bug fixes",
        "notes": [
            "!map: pin + map now perfectly centered on the place (was off-center)",
            "!caption: now works on GIFs, embeds, and image URLs (not just attachments)",
            "!xray: actually follows redirects now, counts them, shows final destination",
            "!catchup: filters command spam, clean empty message, logs real errors safely",
            "!translate: defaults to English; smart parsing of language vs text",
            "!quote: added qoute misspelling alias",
            "Clearer usage errors for !caption and !song (reply directly to media)",
        ],
    },
    {
        "version": "1.8.2",
        "date": "2026-06-29",
        "title": "env template fix",
        "notes": [
            "Fixed .env.example to match the real config (IGNIO_ENV, DISCORD_TOKEN_DEV,",
            "  COMMAND_PREFIX_DEV) instead of wrong names",
            "All keys live in ONE .env file — the LLM key goes alongside your bot token",
            "No second env file is needed",
        ],
    },
    {
        "version": "1.8.1",
        "date": "2026-06-29",
        "title": "OpenAI support",
        "notes": [
            "!tldr, !catchup, and !translate explain now support OpenAI keys",
            "Provider auto-detected from your key (sk-proj = OpenAI, sk-ant = Anthropic)",
            "Reads UTIL_LLM_API_KEY or the standard OPENAI_API_KEY / ANTHROPIC_API_KEY",
            "Added .env.example template; keys always live in .env (never committed)",
        ],
    },
    {
        "version": "1.8.0",
        "date": "2026-06-29",
        "title": "Utilities go live",
        "notes": [
            "!weather now works out of the box (Open-Meteo, no API key needed)",
            "!map now renders a real OSM map with a pin (no API key needed)",
            "!translate now works (MyMemory), with !translate explain for slang",
            "!xray now follows redirects for real and reports the final destination",
            "!tldr + !catchup summaries work when UTIL_LLM_API_KEY is set (Anthropic)",
            "!song works when UTIL_SONG_API_KEY is set (AudD)",
            "All providers are optional and fail gracefully; nothing is ever stored",
        ],
    },
    {
        "version": "1.7.2",
        "date": "2026-06-29",
        "title": "Utilities in help fix",
        "notes": [
            "Fixed: the Utilities category now shows in !help and the help menu buttons",
            "The menu had a hardcoded list that forgot the new category",
            "!admin utilities on/off disables the whole category (verified)",
            "Added a test so a category can never silently go missing from help again",
        ],
    },
    {
        "version": "1.7.1",
        "date": "2026-06-29",
        "title": "Utilities load fix",
        "notes": [
            "Fixed UtilitiesCog failing to load: !map collided with the mapgame alias",
            "!map now belongs to Utilities (place lookup); !mapgame keeps geo/guesscountry",
            "Added a collision test so two commands can never share a name again",
        ],
    },
    {
        "version": "1.7.0",
        "date": "2026-06-29",
        "title": "Utilities Update",
        "notes": [
            "NEW lightweight Utilities category: catchup, tldr, song, xray, map,",
            "  weather, translate, caption, quote, afk (see !help utilities)",
            "Quote + caption image cards, AFK with auto-clear + anti-spam notices",
            "Link X-ray with strong SSRF protection (blocks private/loopback/metadata)",
            "Shared job manager: cooldowns, per-guild caps, dedup, temp-file cleanup",
            "Privacy-first: no messages/media/URLs/transcripts are ever stored",
            "Every response uses AllowedMentions.none() — the bot never pings anyone",
            "External providers are optional via env; missing ones fail gracefully",
            "Whole category is admin-toggleable: !admin utilities on/off",
        ],
    },
    {
        "version": "1.6.0",
        "date": "2026-06-29",
        "title": "Flag Games Update",
        "notes": [
            "NEW !mapflag — server flag RACE: first to name the flag wins sob (daily cap)",
            "  one winner per round, claimed atomically (no double-pay exploits)",
            "NEW !flag — Red Flag / Green Flag voting game with buttons + live tally",
            "  spicy/funny scenarios, can be aimed at someone with !flag @user, no sob",
            "Anti-spam: big games (map/flag) are 12s per-CHANNEL and only one runs at a time",
            "Channels won't flood — a new round can't start until the current one ends",
            "Both games are in the Games category, in !help, and admin-toggleable",
        ],
    },
    {
        "version": "1.5.0",
        "date": "2026-06-29",
        "title": "Map Game Update",
        "notes": [
            "NEW !mapgame — guess the country the arrow points to on a world map",
            "68 well-known countries including island nations like Fiji (no obscure micro-states)",
            "Correct guesses pay sob (3-8 by difficulty) up to a 60/day cap, then free for fun",
            "Clean cream-and-blue world map with a glowing red target + arrow",
            "Accepts aliases (usa, america, uk, nz...) and is case-insensitive",
            "Admins: !admin mapgame on/off; it's in the Games category and !help",
        ],
    },
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
