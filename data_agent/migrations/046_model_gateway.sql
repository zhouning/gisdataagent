-- Migration 046: Model Gateway
-- Adds scenario/project attribution to token usage for FinOps

ALTER TABLE agent_token_usage
ADD COLUMN IF NOT EXISTS scenario VARCHAR(100),
ADD COLUMN IF NOT EXISTS project_id VARCHAR(100),
ADD COLUMN IF NOT EXISTS task_type VARCHAR(50);

CREATE INDEX IF NOT EXISTS idx_token_usage_scenario
ON agent_token_usage(scenario, created_at DESC)
WHERE scenario IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_token_usage_project
ON agent_token_usage(project_id, created_at DESC)
WHERE project_id IS NOT NULL;

COMMENT ON COLUMN agent_token_usage.scenario IS 'Scenario identifier (e.g., surveying_qc, finance_audit)';
COMMENT ON COLUMN agent_token_usage.project_id IS 'Project identifier for cost attribution';
COMMENT ON COLUMN agent_token_usage.task_type IS 'Task type for routing analysis';
