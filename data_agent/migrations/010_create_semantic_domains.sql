-- Migration 010: Custom semantic domain registration
-- Allows users to define business-specific domain hierarchies at runtime.

CREATE TABLE IF NOT EXISTS agent_semantic_domains (
    id SERIAL PRIMARY KEY,
    domain_name VARCHAR(100) NOT NULL,
    parent_category VARCHAR(200),
    children JSONB DEFAULT '[]',
    aliases TEXT[] DEFAULT '{}',
    unit VARCHAR(50) DEFAULT '',
    description TEXT DEFAULT '',
    owner_username VARCHAR(100),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(domain_name, owner_username)
);

CREATE INDEX IF NOT EXISTS idx_semantic_domains_owner
    ON agent_semantic_domains(owner_username);
