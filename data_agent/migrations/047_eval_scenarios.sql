-- Migration 047: Eval Scenarios
-- Adds scenario-based evaluation datasets and enhances eval_history

CREATE TABLE IF NOT EXISTS agent_eval_datasets (
    id SERIAL PRIMARY KEY,
    scenario VARCHAR(100) NOT NULL,
    name VARCHAR(200) NOT NULL,
    version VARCHAR(50) DEFAULT '1.0',
    description TEXT,
    test_cases JSONB NOT NULL,
    created_by VARCHAR(100),
    created_at TIMESTAMP DEFAULT NOW(),
    CONSTRAINT unique_dataset UNIQUE(scenario, name, version)
);

CREATE INDEX IF NOT EXISTS idx_eval_datasets_scenario
ON agent_eval_datasets(scenario);

-- Ensure eval_history table exists (normally created lazily by eval_history.py)
CREATE TABLE IF NOT EXISTS agent_eval_history (
    id SERIAL PRIMARY KEY,
    run_id VARCHAR(100) NOT NULL,
    pipeline VARCHAR(50) NOT NULL,
    model VARCHAR(100) DEFAULT '',
    git_commit VARCHAR(50) DEFAULT '',
    git_branch VARCHAR(100) DEFAULT '',
    overall_score REAL DEFAULT 0,
    pass_rate REAL DEFAULT 0,
    verdict VARCHAR(20) DEFAULT 'UNKNOWN',
    num_tests INTEGER DEFAULT 0,
    num_passed INTEGER DEFAULT 0,
    details JSONB DEFAULT '{}',
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_eval_history_pipeline
ON agent_eval_history (pipeline, created_at DESC);

-- Enhance existing eval_history table with scenario columns
ALTER TABLE agent_eval_history
ADD COLUMN IF NOT EXISTS scenario VARCHAR(100),
ADD COLUMN IF NOT EXISTS dataset_id INTEGER REFERENCES agent_eval_datasets(id),
ADD COLUMN IF NOT EXISTS metrics JSONB;

COMMENT ON TABLE agent_eval_datasets IS 'Golden test datasets per scenario';
