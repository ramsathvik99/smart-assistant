-- =============================================================================
-- MIGRATION 004: EXECUTION EXPERIENCE MEMORY ARCHITECTURE (PHASE 5)
-- =============================================================================
-- Persists structured, user-isolated execution experience across restarts.
-- Enables the assistant to learn from verified outcomes, strategies, and failures
-- without unrestricted autonomous learning or modifying user preferences.
-- =============================================================================

CREATE TABLE IF NOT EXISTS execution_experiences (
    id SERIAL PRIMARY KEY,
    experience_id VARCHAR(64) UNIQUE NOT NULL,
    execution_id VARCHAR(64) NOT NULL,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    intent VARCHAR(100) NOT NULL,
    command_signature VARCHAR(255) NOT NULL,
    action_signature VARCHAR(255) NOT NULL,
    environment_context JSONB DEFAULT '{}',
    expected_outcome JSONB DEFAULT '{}',
    observed_outcome JSONB DEFAULT '{}',
    verification_status VARCHAR(50) NOT NULL,
    confidence VARCHAR(50) DEFAULT 'HIGH',
    failure_classification VARCHAR(100),
    strategy_id VARCHAR(100),
    strategy_type VARCHAR(50),
    attempts JSONB DEFAULT '[]',
    adaptation_attempts INTEGER DEFAULT 0,
    final_status VARCHAR(50) NOT NULL,
    duration_ms INTEGER DEFAULT 0,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    metadata JSONB DEFAULT '{}'
);

-- Targeted performance indexes for experience retrieval
CREATE INDEX IF NOT EXISTS idx_exec_exp_user_intent ON execution_experiences(user_id, intent);
CREATE INDEX IF NOT EXISTS idx_exec_exp_user_signature ON execution_experiences(user_id, command_signature);
CREATE INDEX IF NOT EXISTS idx_exec_exp_user_time ON execution_experiences(user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_exec_exp_user_intent_sig ON execution_experiences(user_id, intent, command_signature);
