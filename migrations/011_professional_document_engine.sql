-- =============================================================================
-- MIGRATION 011: PROFESSIONAL DOCUMENT & PRESENTATION ENGINE PERSISTENCE
-- =============================================================================
-- Adds persistent storage for professional document & presentation artifacts:
--   1. Document Artifacts (PDF, DOCX, PPTX metadata, outline, theme, quality, revisions)
--   2. Artifact Quality Inspections (audit records, defect detections, revision history)
--
-- SAFE: Additive only.
-- =============================================================================

BEGIN;

-- 1. Document Artifacts Table
CREATE TABLE IF NOT EXISTS document_artifacts (
    artifact_id TEXT PRIMARY KEY,
    task_id TEXT REFERENCES document_tasks(task_id) ON DELETE SET NULL,
    user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
    artifact_type TEXT NOT NULL,          -- 'PDF', 'DOCX', 'PPTX', 'STUDY_GUIDE', 'REPORT'
    title TEXT NOT NULL,
    topic TEXT NOT NULL,
    theme TEXT DEFAULT 'tech_modern',
    purpose TEXT DEFAULT 'report',         -- 'report', 'presentation', 'study_guide', 'summary'
    depth TEXT DEFAULT 'normal',          -- 'brief', 'normal', 'detailed', 'comprehensive'
    outline JSONB DEFAULT '[]'::jsonb,
    sections_count INTEGER DEFAULT 0,
    slides_count INTEGER DEFAULT 0,
    source_documents JSONB DEFAULT '[]'::jsonb,
    source_traceability JSONB DEFAULT '[]'::jsonb,
    artifact_path TEXT NOT NULL,
    verification_status TEXT DEFAULT 'VERIFIED',
    quality_score JSONB DEFAULT '{}'::jsonb,
    revisions_count INTEGER DEFAULT 0,
    parent_artifact_id TEXT REFERENCES document_artifacts(artifact_id) ON DELETE SET NULL,
    metadata JSONB DEFAULT '{}'::jsonb,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_doc_art_user_type ON document_artifacts (user_id, artifact_type);
CREATE INDEX IF NOT EXISTS idx_doc_art_topic ON document_artifacts (user_id, topic);
CREATE INDEX IF NOT EXISTS idx_doc_art_created ON document_artifacts (user_id, created_at DESC);

-- 2. Artifact Quality Inspection Logs
CREATE TABLE IF NOT EXISTS document_artifact_inspections (
    inspection_id TEXT PRIMARY KEY,
    artifact_id TEXT REFERENCES document_artifacts(artifact_id) ON DELETE CASCADE,
    user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
    pass_status BOOLEAN DEFAULT TRUE,
    overall_score FLOAT DEFAULT 1.0,
    checks_performed JSONB DEFAULT '[]'::jsonb,
    defects_found JSONB DEFAULT '[]'::jsonb,
    revisions_applied JSONB DEFAULT '[]'::jsonb,
    inspected_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_doc_insp_art ON document_artifact_inspections (artifact_id);

COMMIT;
