-- Migration 007: Universal OS Operations Action History
-- Adds the os_action_history table for structured recording of all
-- OS-level operations executed by the Universal OS Gateway.
--
-- Design:
--   - User-isolated audit trail of all computer control operations
--   - Stores interpreted goal, operation type, capability, target, parameters
--   - Captures verification status, outcome, before/after states
--   - Enables natural references ("what did you do?", "undo that", "where did you put that file?")
--
-- SAFE: Additive only. Does not modify any existing table or column.

BEGIN;

CREATE TABLE IF NOT EXISTS os_action_history (
    id                  BIGSERIAL PRIMARY KEY,
    user_id             INTEGER REFERENCES users(id) ON DELETE CASCADE,
    operation_id        TEXT NOT NULL,
    capability          TEXT NOT NULL,
    operation_type      TEXT NOT NULL,
    target              TEXT,
    parameters          JSONB DEFAULT '{}'::jsonb,
    execution_method    TEXT,
    risk_level          TEXT DEFAULT 'LOW_RISK',
    status              TEXT NOT NULL DEFAULT 'PENDING',
    verified            BOOLEAN DEFAULT FALSE,
    result_message      TEXT,
    result_data         JSONB DEFAULT '{}'::jsonb,
    error_message       TEXT,
    before_state        JSONB DEFAULT '{}'::jsonb,
    after_state         JSONB DEFAULT '{}'::jsonb,
    created_at          TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_os_actions_user_ts
    ON os_action_history (user_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_os_actions_capability
    ON os_action_history (user_id, capability);

CREATE INDEX IF NOT EXISTS idx_os_actions_op_type
    ON os_action_history (user_id, operation_type);

COMMIT;
