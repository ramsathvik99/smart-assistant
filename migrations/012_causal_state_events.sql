-- =============================================================================
-- MIGRATION 012: CAUSAL STATE EVENTS & ATTRIBUTION
-- =============================================================================
-- Connects action records, environment state transitions, and user requests
-- into a formal causal attribution model.
--
-- SAFE: Additive only.
-- =============================================================================

BEGIN;

CREATE TABLE IF NOT EXISTS causal_state_events (
    causal_id           TEXT PRIMARY KEY,
    user_id             INTEGER REFERENCES users(id) ON DELETE CASCADE,
    cause_action_id     TEXT REFERENCES action_records(action_id) ON DELETE SET NULL,
    task_id             TEXT,
    effect_transition_id BIGINT REFERENCES environment_state_transitions(id) ON DELETE SET NULL,
    event_type          TEXT NOT NULL,
    relationship        TEXT NOT NULL DEFAULT 'CAUSED', -- 'CAUSED', 'LIKELY_CAUSED', 'OBSERVED_AFTER', 'NOT_CAUSALLY_RELATED'
    confidence          FLOAT NOT NULL DEFAULT 1.0,
    cause_description   TEXT NOT NULL,
    effect_summary      TEXT NOT NULL,
    previous_state      JSONB DEFAULT '{}'::jsonb,
    new_state           JSONB DEFAULT '{}'::jsonb,
    evidence            JSONB DEFAULT '{}'::jsonb,
    created_at          TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_causal_events_user ON causal_state_events (user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_causal_events_action ON causal_state_events (cause_action_id);
CREATE INDEX IF NOT EXISTS idx_causal_events_type ON causal_state_events (user_id, event_type);

COMMIT;
