-- =============================================================================
-- MIGRATION 001: MULTI-USER HARDENING & CHATGPT-STYLE MEMORY ARCHITECTURE
-- =============================================================================
-- Safe, non-destructive migration for production environments.
-- NEVER drops existing tables or columns.
-- Adds necessary columns, tables, and performance indexes.
-- =============================================================================

-- 1. Ensure pgvector extension if available in PostgreSQL
DO $$
BEGIN
    CREATE EXTENSION IF NOT EXISTS vector;
EXCEPTION
    WHEN OTHERS THEN
        RAISE NOTICE 'pgvector extension not installed on this server; semantic vectors will fallback to jsonb storage';
END $$;

-- 2. USERS: Add password_hash, status, and updated_at
ALTER TABLE IF EXISTS users ADD COLUMN IF NOT EXISTS password_hash TEXT;
ALTER TABLE IF EXISTS users ADD COLUMN IF NOT EXISTS status TEXT DEFAULT 'active';
ALTER TABLE IF EXISTS users ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP;

-- 3. CONVERSATIONS: Ensure canonical table exists with session tracking
CREATE TABLE IF NOT EXISTS conversations (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    user_input TEXT NOT NULL,
    assistant_response TEXT NOT NULL,
    timestamp TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    session_id VARCHAR(100),
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- 4. MESSAGES: Add conversation_id and metadata if missing
ALTER TABLE IF EXISTS messages ADD COLUMN IF NOT EXISTS conversation_id INTEGER REFERENCES conversations(id) ON DELETE SET NULL;
ALTER TABLE IF EXISTS messages ADD COLUMN IF NOT EXISTS metadata JSONB DEFAULT '{}';

-- 5. MEMORY_FACTS: Ensure semantic fact extraction table exists with access tracking
CREATE TABLE IF NOT EXISTS memory_facts (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    fact_key VARCHAR(100) NOT NULL,
    fact_value TEXT NOT NULL,
    confidence FLOAT DEFAULT 0.0,
    source VARCHAR(50) DEFAULT 'conversation',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    last_accessed TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- 6. MEMORY_EMBEDDINGS: Vector storage for semantic search
CREATE TABLE IF NOT EXISTS memory_embeddings (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    memory_id INTEGER,
    content_hash VARCHAR(64) NOT NULL,
    content_text TEXT NOT NULL,
    embedding_vector JSONB,
    model VARCHAR(100) DEFAULT 'text-embedding-3-small',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- 7. PERFORMANCE INDEXES (Idempotent)
CREATE INDEX IF NOT EXISTS idx_users_username ON users(username);
CREATE INDEX IF NOT EXISTS idx_user_memory_user ON user_memory(user_id);
CREATE INDEX IF NOT EXISTS idx_user_preferences_user ON user_preferences(user_id);
CREATE INDEX IF NOT EXISTS idx_system_memory_user ON system_memory(user_id);
CREATE INDEX IF NOT EXISTS idx_conversations_user_time ON conversations(user_id, timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_conversations_session ON conversations(session_id);
CREATE INDEX IF NOT EXISTS idx_messages_user_time ON messages(user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_messages_conv ON messages(conversation_id);
CREATE INDEX IF NOT EXISTS idx_memory_facts_user_key ON memory_facts(user_id, fact_key);
CREATE INDEX IF NOT EXISTS idx_memory_facts_last_access ON memory_facts(user_id, last_accessed DESC);
CREATE INDEX IF NOT EXISTS idx_memory_embeddings_user ON memory_embeddings(user_id);
CREATE INDEX IF NOT EXISTS idx_memory_embeddings_hash ON memory_embeddings(content_hash);
CREATE INDEX IF NOT EXISTS idx_reminders_user_due ON reminders(user_id, due_at);
CREATE INDEX IF NOT EXISTS idx_reminders_notified ON reminders(user_id, is_notified);
CREATE INDEX IF NOT EXISTS idx_notes_user_pinned ON notes(user_id, pinned, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_active_contexts_user ON active_contexts(user_id);
CREATE INDEX IF NOT EXISTS idx_security_audit_user_time ON security_audit_logs(user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_plugin_logs_user_time ON plugin_logs(user_id, created_at DESC);
