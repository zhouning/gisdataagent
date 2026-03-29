-- Migration 039: Workflow SLA and QC template support
-- Adds SLA/timeout tracking to workflows and runs

ALTER TABLE agent_workflows ADD COLUMN IF NOT EXISTS sla_total_seconds INTEGER;
ALTER TABLE agent_workflows ADD COLUMN IF NOT EXISTS priority VARCHAR(20) DEFAULT 'normal';
ALTER TABLE agent_workflows ADD COLUMN IF NOT EXISTS template_source VARCHAR(100);

ALTER TABLE agent_workflow_runs ADD COLUMN IF NOT EXISTS sla_violated BOOLEAN DEFAULT FALSE;
ALTER TABLE agent_workflow_runs ADD COLUMN IF NOT EXISTS timeout_steps JSONB DEFAULT '[]'::jsonb;
