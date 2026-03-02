-- Migration 015: Add email column to agent_app_users for future verification
-- Safe to run multiple times (IF NOT EXISTS)

ALTER TABLE agent_app_users ADD COLUMN IF NOT EXISTS email VARCHAR(255) DEFAULT '';

CREATE INDEX IF NOT EXISTS idx_agent_app_users_email
    ON agent_app_users (email) WHERE email != '';
