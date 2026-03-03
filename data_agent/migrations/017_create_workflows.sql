-- Migration 017: Create workflow tables for workflow builder (v5.4)
-- Supports multi-step pipeline workflows with scheduling and webhook push.

CREATE TABLE IF NOT EXISTS agent_workflows (
    id SERIAL PRIMARY KEY,
    workflow_name VARCHAR(200) NOT NULL,
    description TEXT DEFAULT '',
    owner_username VARCHAR(100) NOT NULL,
    is_shared BOOLEAN DEFAULT FALSE,
    pipeline_type VARCHAR(30) DEFAULT 'general',
    steps JSONB NOT NULL DEFAULT '[]',
    parameters JSONB DEFAULT '{}',
    graph_data JSONB DEFAULT '{}',
    cron_schedule VARCHAR(100) DEFAULT NULL,
    webhook_url TEXT DEFAULT NULL,
    use_count INT DEFAULT 0,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(owner_username, workflow_name)
);

CREATE INDEX IF NOT EXISTS idx_workflows_owner ON agent_workflows (owner_username);
CREATE INDEX IF NOT EXISTS idx_workflows_shared ON agent_workflows (is_shared, created_at DESC);

CREATE TABLE IF NOT EXISTS agent_workflow_runs (
    id SERIAL PRIMARY KEY,
    workflow_id INT REFERENCES agent_workflows(id) ON DELETE CASCADE,
    run_by VARCHAR(100) NOT NULL,
    status VARCHAR(20) DEFAULT 'running',
    parameters_used JSONB DEFAULT '{}',
    step_results JSONB DEFAULT '[]',
    total_duration FLOAT DEFAULT 0,
    total_input_tokens INT DEFAULT 0,
    total_output_tokens INT DEFAULT 0,
    error_message TEXT DEFAULT NULL,
    webhook_sent BOOLEAN DEFAULT FALSE,
    started_at TIMESTAMP DEFAULT NOW(),
    completed_at TIMESTAMP DEFAULT NULL
);

CREATE INDEX IF NOT EXISTS idx_workflow_runs_wf ON agent_workflow_runs (workflow_id, started_at DESC);
