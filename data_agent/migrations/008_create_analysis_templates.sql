-- Migration 008: Create analysis_templates table for PRD F6
-- Run: psql -U <user> -d <db> -f 008_create_analysis_templates.sql

CREATE TABLE IF NOT EXISTS agent_analysis_templates (
    id SERIAL PRIMARY KEY,
    template_name VARCHAR(200) NOT NULL,
    description TEXT DEFAULT '',
    owner_username VARCHAR(100) NOT NULL,
    is_shared BOOLEAN DEFAULT FALSE,
    pipeline_type VARCHAR(30) NOT NULL,
    intent VARCHAR(30) NOT NULL,
    tool_sequence JSONB NOT NULL,
    source_query TEXT DEFAULT '',
    use_count INT DEFAULT 0,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(owner_username, template_name)
);

CREATE INDEX IF NOT EXISTS idx_templates_owner
    ON agent_analysis_templates (owner_username);

CREATE INDEX IF NOT EXISTS idx_templates_shared
    ON agent_analysis_templates (is_shared, created_at DESC);
