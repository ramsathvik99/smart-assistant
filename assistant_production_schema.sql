-- =============================================================================
-- NOVA CANONICAL DATABASE SCHEMA
-- SCHEMA-CODE CONTRACT RECONCILIATION
-- =============================================================================
-- This schema matches the ACTUAL runtime expectations of legacy + intelligence code
-- 
-- CANONICAL DECISIONS:
-- 1. User ID Type: INTEGER (SERIAL PRIMARY KEY) - No UUID anywhere
-- 2. Memory Model: DUAL SUPPORT (legacy JSONB + intelligence fact-based)
-- 3. All FKs: INTEGER REFERENCES users(id)
-- =============================================================================

-- CLEAN SLATE: Drop everything to eliminate UUID/INTEGER conflicts
DROP SCHEMA IF EXISTS auth CASCADE;
DROP SCHEMA IF EXISTS extensions CASCADE;
DROP SCHEMA IF EXISTS task_agent CASCADE;
DROP SCHEMA IF EXISTS legacy CASCADE;
DROP SCHEMA IF EXISTS core CASCADE;
DROP TABLE IF EXISTS users CASCADE;
DROP TABLE IF EXISTS user_memory CASCADE;
DROP TABLE IF EXISTS user_preferences CASCADE;
DROP TABLE IF EXISTS system_memory CASCADE;
DROP TABLE IF EXISTS plugins CASCADE;
DROP TABLE IF EXISTS plugin_logs CASCADE;
DROP TABLE IF EXISTS decision_logs CASCADE;
DROP TABLE IF EXISTS security_audit_logs CASCADE;
DROP TABLE IF EXISTS reminders CASCADE;
DROP TABLE IF EXISTS messages CASCADE;
DROP TABLE IF EXISTS notes CASCADE;
DROP TABLE IF EXISTS active_contexts CASCADE;

-- =============================================================================
-- CANONICAL TABLES (No schema prefixes for backward compatibility)
-- =============================================================================

-- 1. USERS (Authority table - all FKs reference this)
CREATE TABLE users (
    id SERIAL PRIMARY KEY,
    username TEXT UNIQUE NOT NULL,
    password TEXT NOT NULL,
    voice_identity_hash TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- 2. USER_MEMORY (LEGACY JSONB MODEL - used by memory_manager.py)
-- Expects: INSERT INTO user_memory (user_id, memory) VALUES (%s, '{}'::jsonb)
CREATE TABLE user_memory (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    memory JSONB DEFAULT '{}'::jsonb,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- 3. USER_PREFERENCES
CREATE TABLE user_preferences (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    pref_key TEXT NOT NULL,
    pref_value TEXT NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (user_id, pref_key)
);

-- 4. SYSTEM_MEMORY (Intelligence layer - key-value store)
CREATE TABLE system_memory (
    id SERIAL PRIMARY KEY,
    user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
    key TEXT NOT NULL,
    value TEXT NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (user_id, key)
);

-- 5. PLUGINS
CREATE TABLE plugins (
    id SERIAL PRIMARY KEY,
    plugin_id TEXT UNIQUE NOT NULL,
    is_enabled BOOLEAN DEFAULT TRUE,
    permissions JSONB,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- 6. PLUGIN_LOGS
CREATE TABLE plugin_logs (
    id SERIAL PRIMARY KEY,
    user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
    plugin_id INTEGER REFERENCES plugins(id) ON DELETE CASCADE,
    action TEXT,
    status TEXT,
    error_message TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- 7. DECISION_LOGS
CREATE TABLE decision_logs (
    id SERIAL PRIMARY KEY,
    user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
    plugin_id INTEGER REFERENCES plugins(id) ON DELETE SET NULL,
    decision TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- 8. SECURITY_AUDIT_LOGS
CREATE TABLE security_audit_logs (
    id SERIAL PRIMARY KEY,
    user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
    action_name TEXT NOT NULL,
    params TEXT,
    status TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- 9. REMINDERS (Task Agent)
CREATE TABLE reminders (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    task_text TEXT NOT NULL,
    due_at TIMESTAMP NOT NULL,
    is_notified BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- 10. MESSAGES (Legacy chat history)
CREATE TABLE messages (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- 11. NOTES (Legacy notes system)
CREATE TABLE notes (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    note TEXT NOT NULL,
    pinned BOOLEAN DEFAULT FALSE,
    done BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- 12. ACTIVE_CONTEXTS (Runtime state)
CREATE TABLE active_contexts (
    id SERIAL PRIMARY KEY,
    user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
    context_data JSONB NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- =============================================================================
-- INDEXES FOR PERFORMANCE
-- =============================================================================
CREATE INDEX idx_users_username ON users(username);
CREATE INDEX idx_user_memory_user ON user_memory(user_id);
CREATE INDEX idx_system_memory_user_key ON system_memory(user_id, key);
CREATE INDEX idx_reminders_due ON reminders(due_at);
CREATE INDEX idx_reminders_user ON reminders(user_id);
CREATE INDEX idx_messages_user ON messages(user_id);
CREATE INDEX idx_notes_user ON notes(user_id);
CREATE INDEX idx_plugin_logs_user ON plugin_logs(user_id);
CREATE INDEX idx_decision_logs_user ON decision_logs(user_id);

-- =============================================================================
-- VERIFICATION QUERIES
-- =============================================================================
-- Run these after schema creation to verify correctness:
--
-- 1. Verify user_id types:
-- SELECT 
--     table_name, 
--     column_name, 
--     data_type 
-- FROM information_schema.columns 
-- WHERE column_name = 'user_id' 
-- ORDER BY table_name;
--
-- Expected: All should show "integer"
--
-- 2. Verify user_memory structure:
-- SELECT column_name, data_type 
-- FROM information_schema.columns 
-- WHERE table_name = 'user_memory';
--
-- Expected: id (integer), user_id (integer), memory (jsonb), created_at (timestamp)
--
-- 3. Verify foreign keys:
-- SELECT
--     tc.table_name,
--     kcu.column_name,
--     ccu.table_name AS foreign_table_name,
--     ccu.column_name AS foreign_column_name
-- FROM information_schema.table_constraints AS tc
-- JOIN information_schema.key_column_usage AS kcu
--     ON tc.constraint_name = kcu.constraint_name
-- JOIN information_schema.constraint_column_usage AS ccu
--     ON ccu.constraint_name = tc.constraint_name
-- WHERE tc.constraint_type = 'FOREIGN KEY';
--
-- Expected: All foreign_table_name should be 'users', all foreign_column_name should be 'id'
--
-- =============================================================================
-- END OF CANONICAL SCHEMA
-- =============================================================================


-- ================================
-- NEW TABLES: CALENDAR MODULE
-- ================================
-- These tables are newly created for the Calendar & Planning Intelligence module.
-- They handle events, reminders, recurring events, and user preferences.
-- Special days/holidays are fetched from Calendarific API and cached separately.
-- ================================

-- Calendar Events Table
-- Stores all user calendar events and reminders
CREATE TABLE calendar_events (
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

CREATE INDEX idx_calendar_events_user ON calendar_events(user_id);
CREATE INDEX idx_calendar_events_start ON calendar_events(start_datetime);
CREATE INDEX idx_calendar_events_user_start ON calendar_events(user_id, start_datetime);


-- Recurrence Rules Table
-- Stores recurrence data for repeating events
CREATE TABLE recurrence_rules (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    event_id UUID NOT NULL REFERENCES calendar_events(id) ON DELETE CASCADE,
    frequency TEXT CHECK (frequency IN ('daily', 'weekly', 'monthly', 'yearly')),
    interval INTEGER DEFAULT 1,
    days_of_week TEXT, -- e.g. 'mon,tue,fri' for weekly recurrence
    end_date DATE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_recurrence_rules_event ON recurrence_rules(event_id);


-- Calendar Settings Table
-- Stores per-user calendar preferences
CREATE TABLE calendar_settings (
    user_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    region TEXT DEFAULT 'IN',
    timezone TEXT DEFAULT 'Asia/Kolkata',
    end_of_day_prompt_enabled BOOLEAN DEFAULT TRUE,
    weekly_summary_enabled BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);


-- ================================
-- END OF CALENDAR MODULE TABLES
-- ================================

-- conversational_memory.sql

-- Create table for full conversational memory
CREATE TABLE IF NOT EXISTS conversations (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL,
    user_input TEXT NOT NULL,
    assistant_response TEXT NOT NULL,
    timestamp TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    session_id VARCHAR(100),
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Create index for faster queries
CREATE INDEX IF NOT EXISTS idx_conversations_user_timestamp ON conversations (user_id, timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_conversations_session ON conversations (session_id);

-- Create table for semantic memory extraction
CREATE TABLE IF NOT EXISTS memory_facts (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL,
    fact_key VARCHAR(100) NOT NULL,
    fact_value TEXT NOT NULL,
    confidence FLOAT DEFAULT 0.0,
    source VARCHAR(50) DEFAULT 'conversation',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    last_accessed TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Create indexes for semantic memory
CREATE INDEX IF NOT EXISTS idx_memory_facts_user_key ON memory_facts (user_id, fact_key);
CREATE INDEX IF NOT EXISTS idx_memory_facts_source ON memory_facts (source);
