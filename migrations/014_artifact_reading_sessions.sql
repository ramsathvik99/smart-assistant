-- =============================================================================
-- MIGRATION 014: ARTIFACT READING SESSIONS & PERSISTENT CURSORS
-- =============================================================================
-- Adds persistent tables for:
--   1. Artifact Reading Sessions (session tracking, status, chunk cursors, TTS states)
--   2. Reading Progress History (chunk delivery verification, character/word offsets)
--
-- SAFE: Additive only.
-- =============================================================================

BEGIN;

-- 1. Artifact Reading Sessions Table
CREATE TABLE IF NOT EXISTS artifact_reading_sessions (
    session_id TEXT PRIMARY KEY,
    user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
    artifact_id TEXT REFERENCES content_artifacts(artifact_id) ON DELETE CASCADE,
    status TEXT NOT NULL DEFAULT 'QUEUED',  -- QUEUED, READING, PAUSED, STOPPED, COMPLETED, CANCELLED, FAILED
    current_chunk_idx INTEGER NOT NULL DEFAULT 0,
    total_chunks INTEGER NOT NULL DEFAULT 0,
    last_completed_chunk_idx INTEGER NOT NULL DEFAULT -1,
    char_offset INTEGER NOT NULL DEFAULT 0,
    word_offset INTEGER NOT NULL DEFAULT 0,
    chunk_data JSONB DEFAULT '[]'::jsonb,
    artifact_version TEXT NOT NULL DEFAULT '',
    error TEXT,
    started_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    stopped_at TIMESTAMP WITH TIME ZONE,
    completed_at TIMESTAMP WITH TIME ZONE,
    metadata JSONB DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS idx_reading_sessions_user_ts ON artifact_reading_sessions (user_id, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_reading_sessions_user_status ON artifact_reading_sessions (user_id, status);
CREATE INDEX IF NOT EXISTS idx_reading_sessions_artifact ON artifact_reading_sessions (artifact_id);

COMMIT;
