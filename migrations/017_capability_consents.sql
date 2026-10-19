-- Migration 017: Capability Consents and System Control Permissions
-- Adds user_capability_consents table for centralized, persistent capability permission management.
-- SAFE: Additive only. Preserves all existing tables and records.

BEGIN;

CREATE TABLE IF NOT EXISTS user_capability_consents (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    category TEXT NOT NULL,
    is_granted BOOLEAN NOT NULL DEFAULT TRUE,
    granted_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    revoked_at TIMESTAMP WITH TIME ZONE,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (user_id, category)
);

CREATE INDEX IF NOT EXISTS idx_user_capability_consents_user
    ON user_capability_consents (user_id);

CREATE INDEX IF NOT EXISTS idx_user_capability_consents_category
    ON user_capability_consents (user_id, category);

CREATE INDEX IF NOT EXISTS idx_user_capability_consents_active
    ON user_capability_consents (user_id, is_granted);

COMMIT;
