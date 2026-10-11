-- =============================================================================
-- MIGRATION 013: CONTENT ARTIFACTS, MULTI-ARTIFACT MEMORY, AND INSERTION TRACKING
-- =============================================================================
-- Adds persistent tables for:
--   1. Content Artifacts (contextual content items with topic, type, content, hash)
--   2. Artifact Lineage & Transformations (parent/child relationships, lineage operations)
--   3. Artifact Insertions (audit history of content insertions into targets: VS Code, Notepad, Browser, etc.)
--
-- SAFE: Additive only.
-- =============================================================================

BEGIN;

-- 1. Content Artifacts Table
CREATE TABLE IF NOT EXISTS content_artifacts (
    artifact_id TEXT PRIMARY KEY,
    user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
    topic TEXT NOT NULL,
    subtopic TEXT,
    content TEXT NOT NULL,
    content_type TEXT NOT NULL,
    programming_language TEXT,
    original_user_request TEXT,
    task_id TEXT,
    parent_id TEXT REFERENCES content_artifacts(artifact_id) ON DELETE SET NULL,
    root_id TEXT REFERENCES content_artifacts(artifact_id) ON DELETE SET NULL,
    transformation_history JSONB DEFAULT '[]'::jsonb,
    source_info JSONB DEFAULT '{}'::jsonb,
    content_hash TEXT NOT NULL,
    status TEXT DEFAULT 'active',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    metadata JSONB DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS idx_content_artifacts_user_ts ON content_artifacts (user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_content_artifacts_user_topic ON content_artifacts (user_id, topic);
CREATE INDEX IF NOT EXISTS idx_content_artifacts_user_type ON content_artifacts (user_id, content_type);
CREATE INDEX IF NOT EXISTS idx_content_artifacts_user_hash ON content_artifacts (user_id, content_hash);
CREATE INDEX IF NOT EXISTS idx_content_artifacts_parent ON content_artifacts (parent_id);

-- 2. Artifact Insertions Audit Table
CREATE TABLE IF NOT EXISTS artifact_insertions (
    id SERIAL PRIMARY KEY,
    artifact_id TEXT REFERENCES content_artifacts(artifact_id) ON DELETE CASCADE,
    user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
    target_app TEXT NOT NULL,
    target_window TEXT,
    target_file TEXT,
    target_control TEXT,
    execution_method TEXT NOT NULL,
    success BOOLEAN NOT NULL,
    verification_result JSONB DEFAULT '{}'::jsonb,
    failure_reason TEXT,
    timestamp TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_artifact_insertions_user_ts ON artifact_insertions (user_id, timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_artifact_insertions_art ON artifact_insertions (artifact_id);

COMMIT;
