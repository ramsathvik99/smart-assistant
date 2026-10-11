-- =============================================================================
-- MIGRATION 010: DOCUMENT INTELLIGENCE AND REFERENCE PERSISTENCE
-- =============================================================================
-- Adds persistent tables for:
--   1. Document References (resolved documents with resolution evidence & confidence)
--   2. Document Tasks (document intelligence tasks: SUMMARIZE, COMPARE, READ_ALOUD)
--   3. Document Reading States (page, section, paragraph, paused state)
--   4. Document Summaries & Big-Picture Syntheses (structured summaries with source traceability)
--
-- SAFE: Additive only.
-- =============================================================================

BEGIN;

-- 1. Document References Table
CREATE TABLE IF NOT EXISTS document_references (
    id TEXT PRIMARY KEY,
    user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
    document_path TEXT NOT NULL,
    filename TEXT NOT NULL,
    file_type TEXT NOT NULL,
    resolution_source TEXT NOT NULL,
    evidence JSONB DEFAULT '{}'::jsonb,
    confidence TEXT DEFAULT 'high',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_doc_refs_user_ts ON document_references (user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_doc_refs_filename ON document_references (user_id, filename);

-- 2. Document Tasks Table
CREATE TABLE IF NOT EXISTS document_tasks (
    task_id TEXT PRIMARY KEY,
    user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
    operation TEXT NOT NULL,
    source_documents JSONB DEFAULT '[]'::jsonb,
    output_format TEXT DEFAULT 'PDF',
    summary_style TEXT DEFAULT 'normal',
    scope TEXT DEFAULT 'comprehensive',
    status TEXT NOT NULL DEFAULT 'QUEUED',
    progress TEXT DEFAULT '0%',
    artifact_path TEXT,
    result JSONB DEFAULT '{}'::jsonb,
    error TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    completed_at TIMESTAMP WITH TIME ZONE
);

CREATE INDEX IF NOT EXISTS idx_doc_tasks_user_status ON document_tasks (user_id, status);
CREATE INDEX IF NOT EXISTS idx_doc_tasks_created ON document_tasks (user_id, created_at DESC);

-- 3. Document Reading States Table
CREATE TABLE IF NOT EXISTS document_reading_states (
    reading_id TEXT PRIMARY KEY,
    user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
    document_path TEXT NOT NULL,
    document_title TEXT,
    current_page INTEGER DEFAULT 1,
    total_pages INTEGER DEFAULT 1,
    current_section TEXT,
    current_paragraph INTEGER DEFAULT 0,
    is_paused BOOLEAN DEFAULT FALSE,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_doc_reading_user ON document_reading_states (user_id, updated_at DESC);
CREATE UNIQUE INDEX IF NOT EXISTS idx_doc_reading_user_path ON document_reading_states (user_id, document_path);

-- 4. Document Summaries Table
CREATE TABLE IF NOT EXISTS document_summaries (
    summary_id TEXT PRIMARY KEY,
    task_id TEXT REFERENCES document_tasks(task_id) ON DELETE CASCADE,
    user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    mode TEXT DEFAULT 'normal',
    summary_text TEXT NOT NULL,
    key_concepts JSONB DEFAULT '[]'::jsonb,
    source_traceability JSONB DEFAULT '[]'::jsonb,
    artifact_path TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_doc_summaries_user ON document_summaries (user_id, created_at DESC);

COMMIT;
