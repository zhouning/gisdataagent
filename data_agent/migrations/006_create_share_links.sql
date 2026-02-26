-- Migration 006: Create share_links table for public result sharing
-- Depends on: 001_create_users.sql

CREATE TABLE IF NOT EXISTS agent_share_links (
    id SERIAL PRIMARY KEY,
    token VARCHAR(16) UNIQUE NOT NULL,
    owner_username VARCHAR(100) NOT NULL,
    title VARCHAR(300) DEFAULT '',
    summary TEXT DEFAULT '',
    files JSONB NOT NULL DEFAULT '[]',
    pipeline_type VARCHAR(30),
    password_hash VARCHAR(500),
    expires_at TIMESTAMP,
    view_count INT DEFAULT 0,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_share_links_token ON agent_share_links (token);
CREATE INDEX IF NOT EXISTS idx_share_links_owner ON agent_share_links (owner_username);
