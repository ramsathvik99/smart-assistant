-- =============================================================================
-- MIGRATION 008: EXECUTION GRAPHS AND PERSISTENT ACTION RECORDS
-- =============================================================================
-- Adds persistent tables for:
--   1. Goals (structured user work objectives)
--   2. Execution Graphs (multi-step dependency graphs)
--   3. Execution Nodes (individual operations with preconditions & verification)
--   4. Action Records (pre/post execution tracking linked to nodes and context)
--
-- SAFE: Additive only. Extends existing schema without dropping or altering existing columns.
-- =============================================================================

BEGIN;

-- 1. Goals Table
CREATE TABLE IF NOT EXISTS goals (
    goal_id TEXT PRIMARY KEY,
    user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    objective TEXT,
    purpose TEXT DEFAULT 'general',
    priority TEXT DEFAULT 'normal',
    status TEXT NOT NULL DEFAULT 'PENDING',
    progress TEXT DEFAULT '0%',
    metadata JSONB DEFAULT '{}'::jsonb,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_goals_user_ts ON goals (user_id, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_goals_status ON goals (user_id, status);

-- 2. Execution Graphs Table
CREATE TABLE IF NOT EXISTS execution_graphs (
    graph_id TEXT PRIMARY KEY,
    goal_id TEXT,
    user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'PENDING',
    metadata JSONB DEFAULT '{}'::jsonb,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_exec_graphs_user_ts ON execution_graphs (user_id, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_exec_graphs_goal ON execution_graphs (goal_id);

-- 3. Execution Nodes Table
CREATE TABLE IF NOT EXISTS execution_nodes (
    node_id TEXT PRIMARY KEY,
    graph_id TEXT REFERENCES execution_graphs(graph_id) ON DELETE CASCADE,
    goal_id TEXT,
    user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
    capability TEXT NOT NULL,
    operation TEXT NOT NULL,
    parent_node_id TEXT,
    dependencies JSONB DEFAULT '[]'::jsonb,
    inputs JSONB DEFAULT '{}'::jsonb,
    preconditions JSONB DEFAULT '{}'::jsonb,
    expected_result JSONB DEFAULT '{}'::jsonb,
    execution_method TEXT,
    status TEXT NOT NULL DEFAULT 'PENDING',
    actual_result JSONB DEFAULT '{}'::jsonb,
    error TEXT,
    verification_result JSONB DEFAULT '{}'::jsonb,
    retry_count INTEGER DEFAULT 0,
    start_time TIMESTAMP WITH TIME ZONE,
    end_time TIMESTAMP WITH TIME ZONE,
    metadata JSONB DEFAULT '{}'::jsonb,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_exec_nodes_graph ON execution_nodes (graph_id);
CREATE INDEX IF NOT EXISTS idx_exec_nodes_user ON execution_nodes (user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_exec_nodes_goal ON execution_nodes (goal_id);

-- 4. Extend os_action_history with graph/node relationship columns
ALTER TABLE os_action_history ADD COLUMN IF NOT EXISTS execution_node_id TEXT;
ALTER TABLE os_action_history ADD COLUMN IF NOT EXISTS goal_id TEXT;
ALTER TABLE os_action_history ADD COLUMN IF NOT EXISTS completed_at TIMESTAMP WITH TIME ZONE;
CREATE INDEX IF NOT EXISTS idx_os_actions_node ON os_action_history (execution_node_id);
CREATE INDEX IF NOT EXISTS idx_os_actions_goal ON os_action_history (goal_id);

-- 5. General Action Records Table
CREATE TABLE IF NOT EXISTS action_records (
    action_id TEXT PRIMARY KEY,
    user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
    goal_id TEXT,
    execution_node_id TEXT,
    capability TEXT NOT NULL,
    operation TEXT NOT NULL,
    intended_action TEXT NOT NULL,
    target TEXT,
    parameters JSONB DEFAULT '{}'::jsonb,
    execution_method TEXT,
    status TEXT NOT NULL DEFAULT 'PENDING',
    actual_result JSONB DEFAULT '{}'::jsonb,
    verified BOOLEAN DEFAULT FALSE,
    verification_result JSONB DEFAULT '{}'::jsonb,
    error_message TEXT,
    related_environment_state JSONB DEFAULT '{}'::jsonb,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    completed_at TIMESTAMP WITH TIME ZONE
);

CREATE INDEX IF NOT EXISTS idx_action_records_user_ts ON action_records (user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_action_records_node ON action_records (execution_node_id);
CREATE INDEX IF NOT EXISTS idx_action_records_goal ON action_records (goal_id);

COMMIT;
