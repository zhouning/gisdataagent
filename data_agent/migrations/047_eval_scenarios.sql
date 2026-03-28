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

-- Enhance existing eval_history table
ALTER TABLE agent_eval_history
ADD COLUMN IF NOT EXISTS scenario VARCHAR(100),
ADD COLUMN IF NOT EXISTS dataset_id INTEGER REFERENCES agent_eval_datasets(id),
ADD COLUMN IF NOT EXISTS metrics JSONB;

COMMENT ON TABLE agent_eval_datasets IS 'Golden test datasets per scenario';
COMMENT ON COLUMN agent_eval_history.scenario IS 'Scenario identifier for scenario-specific evaluation';
COMMENT ON COLUMN agent_eval_history.metrics IS 'Scenario-specific metrics (e.g., defect_f1, fix_success_rate)';
