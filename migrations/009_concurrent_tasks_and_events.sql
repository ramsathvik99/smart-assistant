-- =============================================================================
-- MIGRATION 009: CONCURRENT TASKS AND PROGRESSIVE EVENT STREAM
-- =============================================================================
-- Supports multi-task concurrency, dependency tracking, resource locking,
-- progressive execution event streaming, and state reconciliation.
--
-- SAFE: Additive only.
-- =============================================================================

BEGIN;

-- 1. Concurrent Tasks Table
CREATE TABLE IF NOT EXISTS concurrent_tasks (
    task_id TEXT PRIMARY KEY,
    user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
    conversation_id TEXT,
    user_request TEXT NOT NULL,
    normalized_goal TEXT,
    status TEXT NOT NULL DEFAULT 'QUEUED',
    priority TEXT NOT NULL DEFAULT 'NORMAL',
    progress TEXT DEFAULT '0%',
    current_step TEXT,
    execution_graph_id TEXT REFERENCES execution_graphs(graph_id) ON DELETE SET NULL,
    parent_task_id TEXT,
    dependencies JSONB DEFAULT '[]'::jsonb,
    resources JSONB DEFAULT '[]'::jsonb,
    result JSONB DEFAULT '{}'::jsonb,
    error TEXT,
    cancellation_state TEXT DEFAULT 'NONE',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    started_at TIMESTAMP WITH TIME ZONE,
    completed_at TIMESTAMP WITH TIME ZONE,
    metadata JSONB DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS idx_tasks_user_status ON concurrent_tasks (user_id, status);
CREATE INDEX IF NOT EXISTS idx_tasks_user_created ON concurrent_tasks (user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_tasks_priority ON concurrent_tasks (priority);

-- 2. Task Events Table (Progressive Event Bus Persistence)
CREATE TABLE IF NOT EXISTS task_events (
    event_id TEXT PRIMARY KEY,
    task_id TEXT REFERENCES concurrent_tasks(task_id) ON DELETE CASCADE,
    user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
    event_type TEXT NOT NULL,
    payload JSONB DEFAULT '{}'::jsonb,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_task_events_task ON task_events (task_id, created_at ASC);
CREATE INDEX IF NOT EXISTS idx_task_events_user_type ON task_events (user_id, event_type);

COMMIT;
