-- Migration 002: Create agent_user_memories table for Spatial Memory System (PRD 5.2.1)

CREATE TABLE IF NOT EXISTS agent_user_memories (
    id SERIAL PRIMARY KEY,
    username VARCHAR(100) NOT NULL,
    memory_type VARCHAR(30) NOT NULL,
    memory_key VARCHAR(200) NOT NULL,
    memory_value JSONB NOT NULL,
    description TEXT DEFAULT '',
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(username, memory_type, memory_key)
);

CREATE INDEX IF NOT EXISTS idx_agent_user_memories_user ON agent_user_memories (username);
CREATE INDEX IF NOT EXISTS idx_agent_user_memories_type ON agent_user_memories (username, memory_type);
