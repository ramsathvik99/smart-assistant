-- Migration 006: Continuous Environment Awareness
-- Adds the environment_state_transitions table for recording meaningful
-- state transitions observed by the ContinuousEnvironmentObserver.
--
-- Design:
--   - Stores only MEANINGFUL transitions (not every poll tick)
--   - Per-user isolation via user_id FK
--   - JSONB before/after state and entity diffs for full reconstruction
--   - Retained for 30 days by default (set up a cron for cleanup if needed)
--
-- SAFE: Additive only. Does not modify any existing table or column.

BEGIN;

CREATE TABLE IF NOT EXISTS environment_state_transitions (
    id                  BIGSERIAL PRIMARY KEY,
    user_id             INTEGER REFERENCES users(id) ON DELETE CASCADE,
    timestamp           TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    change_type         TEXT NOT NULL DEFAULT 'GENERAL_CHANGE',
    transition_summary  TEXT NOT NULL DEFAULT '',
    before_state        JSONB DEFAULT '{}'::jsonb,
    after_state         JSONB DEFAULT '{}'::jsonb,
    entities_changed    JSONB DEFAULT '{}'::jsonb,
    created_at          TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_env_transitions_user
    ON environment_state_transitions (user_id);

CREATE INDEX IF NOT EXISTS idx_env_transitions_user_ts
    ON environment_state_transitions (user_id, timestamp DESC);

CREATE INDEX IF NOT EXISTS idx_env_transitions_change_type
    ON environment_state_transitions (user_id, change_type);

COMMIT;
