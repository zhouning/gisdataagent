-- Migration 045: Prompt Registry
-- Adds version control for built-in agent prompts with environment isolation

CREATE TABLE IF NOT EXISTS agent_prompt_versions (
    id SERIAL PRIMARY KEY,
    domain VARCHAR(50) NOT NULL,
    prompt_key VARCHAR(100) NOT NULL,
    version INTEGER NOT NULL,
    environment VARCHAR(20) NOT NULL DEFAULT 'prod',
    prompt_text TEXT NOT NULL,
    change_reason TEXT,
    created_by VARCHAR(100),
    created_at TIMESTAMP DEFAULT NOW(),
    deployed_at TIMESTAMP,
    is_active BOOLEAN DEFAULT false,
    CONSTRAINT unique_prompt_version UNIQUE(domain, prompt_key, environment, version)
);

CREATE INDEX IF NOT EXISTS idx_prompt_versions_active
ON agent_prompt_versions(domain, prompt_key, environment, is_active)
WHERE is_active = true;

COMMENT ON TABLE agent_prompt_versions IS 'Version control for built-in agent prompts with environment isolation';
