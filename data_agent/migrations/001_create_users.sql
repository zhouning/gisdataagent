-- Migration 001: Create agent_app_users table for authentication
-- Run against your PostgreSQL database:
--   psql -h <host> -U <user> -d <database> -f 001_create_users.sql

CREATE TABLE IF NOT EXISTS agent_app_users (
    id SERIAL PRIMARY KEY,
    username VARCHAR(100) UNIQUE NOT NULL,
    password_hash VARCHAR(500),
    display_name VARCHAR(200),
    role VARCHAR(20) DEFAULT 'analyst',       -- admin / analyst / viewer
    auth_provider VARCHAR(20) DEFAULT 'password',  -- password / google / github
    created_at TIMESTAMP DEFAULT NOW()
);

-- Note: The default admin user (admin/admin123) is auto-seeded by auth.py
-- on first startup if the table is empty. Change the password immediately.

-- Index for fast login lookups
CREATE INDEX IF NOT EXISTS idx_agent_app_users_username ON agent_app_users (username);
