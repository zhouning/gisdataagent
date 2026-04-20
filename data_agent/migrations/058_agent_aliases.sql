-- Migration 058: Agent aliases for @mention routing (v24.0)
-- Per-user aliases, display names, pin/hide flags for mention targets.

CREATE TABLE IF NOT EXISTS agent_aliases (
    id SERIAL PRIMARY KEY,
    handle VARCHAR(100) NOT NULL,
    aliases TEXT[] DEFAULT '{}',
    display_name VARCHAR(100),
    pinned BOOLEAN DEFAULT false,
    hidden BOOLEAN DEFAULT false,
    user_id VARCHAR(100) NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_agent_aliases_handle_user UNIQUE (handle, user_id)
);

CREATE INDEX IF NOT EXISTS idx_agent_aliases_user ON agent_aliases(user_id);
CREATE INDEX IF NOT EXISTS idx_agent_aliases_handle ON agent_aliases(handle);
