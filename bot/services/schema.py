# bot/services/schema.py

MIGRATIONS = [
    (
        1,
        "init_v2",
        """
        CREATE TABLE IF NOT EXISTS guilds (
            guild_id INTEGER PRIMARY KEY,
            name TEXT,
            created_at INTEGER NOT NULL,
            updated_at INTEGER NOT NULL
        );

        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            created_at INTEGER NOT NULL,
            updated_at INTEGER NOT NULL
        );

        CREATE TABLE IF NOT EXISTS streak_entities (
            streak_id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER NOT NULL,

            streak_type TEXT NOT NULL CHECK (streak_type IN ('duo','group')),
            name TEXT,

            size INTEGER NOT NULL CHECK (size >= 2 AND size <= 5),
            required_count INTEGER NOT NULL CHECK (required_count >= 2 AND required_count <= size),

            member_hash TEXT, -- prevents duplicate groups

            is_active INTEGER NOT NULL DEFAULT 1,
            created_at INTEGER NOT NULL,
            updated_at INTEGER NOT NULL,

            UNIQUE(guild_id, member_hash),

            FOREIGN KEY (guild_id) REFERENCES guilds(guild_id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS streak_members (
            streak_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            joined_at INTEGER NOT NULL,

            PRIMARY KEY (streak_id, user_id),

            FOREIGN KEY (streak_id) REFERENCES streak_entities(streak_id) ON DELETE CASCADE,
            FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS streak_daily_progress (
            streak_id INTEGER NOT NULL,
            guild_id INTEGER NOT NULL,
            day_key INTEGER NOT NULL,

            progress_seconds INTEGER NOT NULL DEFAULT 0,
            qualified INTEGER NOT NULL DEFAULT 0,
            updated_at INTEGER NOT NULL,

            PRIMARY KEY (streak_id, day_key),

            FOREIGN KEY (streak_id) REFERENCES streak_entities(streak_id) ON DELETE CASCADE,
            FOREIGN KEY (guild_id) REFERENCES guilds(guild_id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS streak_state (
            streak_id INTEGER PRIMARY KEY,
            guild_id INTEGER NOT NULL,

            current_streak INTEGER NOT NULL DEFAULT 0,
            longest_streak INTEGER NOT NULL DEFAULT 0,
            total_completed_days INTEGER NOT NULL DEFAULT 0,
            last_completed_day_key INTEGER NOT NULL DEFAULT -1,

            updated_at INTEGER NOT NULL,

            FOREIGN KEY (streak_id) REFERENCES streak_entities(streak_id) ON DELETE CASCADE,
            FOREIGN KEY (guild_id) REFERENCES guilds(guild_id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS streak_activity_logs (
            log_id INTEGER PRIMARY KEY AUTOINCREMENT,

            streak_id INTEGER NOT NULL,
            guild_id INTEGER NOT NULL,
            day_key INTEGER NOT NULL,

            event_type TEXT NOT NULL,
            seconds_delta INTEGER NOT NULL DEFAULT 0,
            meta_json TEXT,

            created_at INTEGER NOT NULL,

            FOREIGN KEY (streak_id) REFERENCES streak_entities(streak_id) ON DELETE CASCADE,
            FOREIGN KEY (guild_id) REFERENCES guilds(guild_id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS guild_settings (
            guild_id INTEGER NOT NULL,
            key TEXT NOT NULL,
            value TEXT NOT NULL,
            updated_at INTEGER NOT NULL,

            PRIMARY KEY (guild_id, key),

            FOREIGN KEY (guild_id) REFERENCES guilds(guild_id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS user_settings (
            guild_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            key TEXT NOT NULL,
            value TEXT NOT NULL,
            updated_at INTEGER NOT NULL,

            PRIMARY KEY (guild_id, user_id, key),

            FOREIGN KEY (guild_id) REFERENCES guilds(guild_id) ON DELETE CASCADE,
            FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS streak_notifications (
            streak_id INTEGER NOT NULL,
            guild_id INTEGER NOT NULL,
            day_key INTEGER NOT NULL,

            last_reminder_ts INTEGER NOT NULL DEFAULT 0,
            ended_warning_ts INTEGER NOT NULL DEFAULT 0,
            ended_final_ts INTEGER NOT NULL DEFAULT 0,
            updated_at INTEGER NOT NULL,

            PRIMARY KEY (streak_id, day_key),

            FOREIGN KEY (streak_id) REFERENCES streak_entities(streak_id) ON DELETE CASCADE,
            FOREIGN KEY (guild_id) REFERENCES guilds(guild_id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS admin_actions (
            action_id INTEGER PRIMARY KEY AUTOINCREMENT,

            guild_id INTEGER NOT NULL,
            admin_user_id INTEGER NOT NULL,
            streak_id INTEGER,

            action_type TEXT NOT NULL,
            amount INTEGER,
            note TEXT,

            created_at INTEGER NOT NULL,

            FOREIGN KEY (guild_id) REFERENCES guilds(guild_id) ON DELETE CASCADE,
            FOREIGN KEY (admin_user_id) REFERENCES users(user_id) ON DELETE CASCADE,
            FOREIGN KEY (streak_id) REFERENCES streak_entities(streak_id) ON DELETE SET NULL
        );

        CREATE INDEX IF NOT EXISTS idx_streak_entities_guild
        ON streak_entities(guild_id);

        CREATE INDEX IF NOT EXISTS idx_streak_entities_type
        ON streak_entities(guild_id, streak_type, is_active);

        CREATE INDEX IF NOT EXISTS idx_streak_members_user
        ON streak_members(user_id);

        CREATE INDEX IF NOT EXISTS idx_streak_daily_progress_guild_day
        ON streak_daily_progress(guild_id, day_key);

        CREATE INDEX IF NOT EXISTS idx_streak_state_guild_current
        ON streak_state(guild_id, current_streak DESC);

        CREATE INDEX IF NOT EXISTS idx_streak_state_guild_longest
        ON streak_state(guild_id, longest_streak DESC);

        CREATE INDEX IF NOT EXISTS idx_streak_logs_streak_day
        ON streak_activity_logs(streak_id, day_key);

        CREATE INDEX IF NOT EXISTS idx_streak_logs_guild_type
        ON streak_activity_logs(guild_id, event_type);
        """
    )
]