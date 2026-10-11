-- =============================================================================
-- MIGRATION 005: STRATEGY LEARNING SIGNALS ARCHITECTURE (PHASE 9)
-- =============================================================================
-- Persists structured, user-isolated continuous learning signals derived from
-- verified execution experiences. Enables controlled long-term adaptation
-- while respecting policy boundaries, user isolation, and strategy versioning.
-- =============================================================================

CREATE TABLE IF NOT EXISTS strategy_learning_signals (
    id SERIAL PRIMARY KEY,
    signal_id VARCHAR(64) UNIQUE NOT NULL,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    strategy_id VARCHAR(100) NOT NULL,
    strategy_version VARCHAR(50) DEFAULT 'v1',
    intent VARCHAR(100) NOT NULL,
    context_signature VARCHAR(255) NOT NULL,
    evidence_type VARCHAR(50) NOT NULL,
    evidence_strength FLOAT NOT NULL DEFAULT 1.0,
    outcome VARCHAR(50) NOT NULL,
    verification_status VARCHAR(50) NOT NULL,
    confidence VARCHAR(50) DEFAULT 'LOW',
    provenance JSONB DEFAULT '{}',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    expires_at TIMESTAMP WITH TIME ZONE
);

-- Targeted performance indexes for learning retrieval
CREATE INDEX IF NOT EXISTS idx_strat_learn_user_intent ON strategy_learning_signals(user_id, intent);
CREATE INDEX IF NOT EXISTS idx_strat_learn_user_strat ON strategy_learning_signals(user_id, strategy_id, strategy_version);
CREATE INDEX IF NOT EXISTS idx_strat_learn_user_sig ON strategy_learning_signals(user_id, context_signature);
CREATE INDEX IF NOT EXISTS idx_strat_learn_user_time ON strategy_learning_signals(user_id, created_at DESC);
