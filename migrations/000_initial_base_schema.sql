-- =============================================================================
-- MIGRATION 000: INITIAL CANONICAL BASE SCHEMA
-- =============================================================================
-- This migration establishes the baseline foundational tables for a clean/fresh
-- database instance, ensuring all migrations (001-013) can run sequentially.
-- 
-- IDEMPOTENCY GUARANTEE:
-- Uses `CREATE TABLE IF NOT EXISTS` and `CREATE INDEX IF NOT EXISTS`.
-- On existing production databases where these base tables already exist, this
-- migration is a safe, non-destructive no-op. It will not drop, alter, or
-- overwrite any existing tables or rows.
-- =============================================================================

-- 1. USERS (Authority table)
CREATE TABLE IF NOT EXISTS users (
    id SERIAL PRIMARY KEY,
    username TEXT UNIQUE NOT NULL,
    password TEXT,
    voice_identity_hash TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- 2. USER_MEMORY (Legacy JSONB model)
CREATE TABLE IF NOT EXISTS user_memory (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    memory JSONB DEFAULT '{}'::jsonb,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- 3. USER_PREFERENCES
CREATE TABLE IF NOT EXISTS user_preferences (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    pref_key TEXT NOT NULL,
    pref_value TEXT NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (user_id, pref_key)
);

-- 4. SYSTEM_MEMORY (Key-value store)
CREATE TABLE IF NOT EXISTS system_memory (
    id SERIAL PRIMARY KEY,
    user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
    key TEXT NOT NULL,
    value TEXT NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (user_id, key)
);

-- 5. PLUGINS
CREATE TABLE IF NOT EXISTS plugins (
    id SERIAL PRIMARY KEY,
    plugin_id TEXT UNIQUE NOT NULL,
    is_enabled BOOLEAN DEFAULT TRUE,
    permissions JSONB,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- 6. PLUGIN_LOGS
CREATE TABLE IF NOT EXISTS plugin_logs (
    id SERIAL PRIMARY KEY,
    user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
    plugin_id INTEGER REFERENCES plugins(id) ON DELETE CASCADE,
    action TEXT,
    status TEXT,
    error_message TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- 7. DECISION_LOGS
CREATE TABLE IF NOT EXISTS decision_logs (
    id SERIAL PRIMARY KEY,
    user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
    plugin_id INTEGER REFERENCES plugins(id) ON DELETE SET NULL,
    decision TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- 8. SECURITY_AUDIT_LOGS
CREATE TABLE IF NOT EXISTS security_audit_logs (
    id SERIAL PRIMARY KEY,
    user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
    action_name TEXT NOT NULL,
    params TEXT,
    status TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- 9. REMINDERS
CREATE TABLE IF NOT EXISTS reminders (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    task_text TEXT NOT NULL,
    due_at TIMESTAMP NOT NULL,
    is_notified BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- 10. MESSAGES
CREATE TABLE IF NOT EXISTS messages (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- 11. NOTES
CREATE TABLE IF NOT EXISTS notes (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    note TEXT NOT NULL,
    pinned BOOLEAN DEFAULT FALSE,
    done BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- 12. ACTIVE_CONTEXTS
CREATE TABLE IF NOT EXISTS active_contexts (
    id SERIAL PRIMARY KEY,
    user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
    context_data JSONB NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- 13. CALENDAR_EVENTS
CREATE TABLE IF NOT EXISTS calendar_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    description TEXT,
    start_datetime TIMESTAMP NOT NULL,
    end_datetime TIMESTAMP,
    is_all_day BOOLEAN DEFAULT FALSE,
    event_type TEXT CHECK (event_type IN ('event', 'reminder')),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 14. RECURRENCE_RULES
CREATE TABLE IF NOT EXISTS recurrence_rules (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    event_id UUID NOT NULL REFERENCES calendar_events(id) ON DELETE CASCADE,
    frequency TEXT CHECK (frequency IN ('daily', 'weekly', 'monthly', 'yearly')),
    interval INTEGER DEFAULT 1,
    days_of_week TEXT,
    end_date DATE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 15. CALENDAR_SETTINGS
CREATE TABLE IF NOT EXISTS calendar_settings (
    user_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    region TEXT DEFAULT 'IN',
    timezone TEXT DEFAULT 'Asia/Kolkata',
    end_of_day_prompt_enabled BOOLEAN DEFAULT TRUE,
    weekly_summary_enabled BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 16. REVOKED_TOKENS
CREATE TABLE IF NOT EXISTS revoked_tokens (
    token TEXT PRIMARY KEY,
    revoked_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 17. SPECIAL_DAYS_CACHE
CREATE TABLE IF NOT EXISTS special_days_cache (
    id SERIAL PRIMARY KEY,
    date DATE NOT NULL,
    name VARCHAR(255) NOT NULL,
    description TEXT,
    region VARCHAR(100) NOT NULL,
    holiday_type VARCHAR(100),
    fetched_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (date, name, region)
);

-- 18. NOVA_COMMAND_HISTORY
CREATE TABLE IF NOT EXISTS nova_command_history (
    id SERIAL PRIMARY KEY,
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    user_command TEXT NOT NULL,
    assistant_response TEXT NOT NULL
);

-- 19. NOVA_EMAIL_IDENTITY
CREATE TABLE IF NOT EXISTS nova_email_identity (
    id SERIAL PRIMARY KEY,
    sender_email VARCHAR(255) NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- BASE INDEXES
CREATE INDEX IF NOT EXISTS idx_users_username ON users(username);
CREATE INDEX IF NOT EXISTS idx_user_memory_user ON user_memory(user_id);
CREATE INDEX IF NOT EXISTS idx_system_memory_user_key ON system_memory(user_id, key);
CREATE INDEX IF NOT EXISTS idx_reminders_due ON reminders(due_at);
CREATE INDEX IF NOT EXISTS idx_reminders_user ON reminders(user_id);
CREATE INDEX IF NOT EXISTS idx_messages_user ON messages(user_id);
CREATE INDEX IF NOT EXISTS idx_notes_user ON notes(user_id);
CREATE INDEX IF NOT EXISTS idx_plugin_logs_user ON plugin_logs(user_id);
CREATE INDEX IF NOT EXISTS idx_decision_logs_user ON decision_logs(user_id);
CREATE INDEX IF NOT EXISTS idx_calendar_events_user ON calendar_events(user_id);
CREATE INDEX IF NOT EXISTS idx_calendar_events_start ON calendar_events(start_datetime);
CREATE INDEX IF NOT EXISTS idx_calendar_events_user_start ON calendar_events(user_id, start_datetime);
CREATE INDEX IF NOT EXISTS idx_recurrence_rules_event ON recurrence_rules(event_id);
