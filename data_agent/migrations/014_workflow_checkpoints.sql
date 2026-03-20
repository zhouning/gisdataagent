-- v14.0: Workflow checkpoint support for pause/resume
ALTER TABLE agent_workflow_runs ADD COLUMN IF NOT EXISTS node_checkpoints JSONB DEFAULT '{}'::jsonb;
