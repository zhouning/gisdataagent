-- Migration 040: MCP Tool Selection Rules
-- Declarative mapping from task types to MCP tools

CREATE TABLE IF NOT EXISTS agent_mcp_tool_rules (
    id SERIAL PRIMARY KEY,
    task_type VARCHAR(100) NOT NULL,
    tool_name VARCHAR(200) NOT NULL,
    server_name VARCHAR(100) NOT NULL,
    parameters JSONB DEFAULT '{}'::jsonb,
    priority INTEGER DEFAULT 0,
    fallback_tool VARCHAR(200),
    fallback_server VARCHAR(100),
    owner_username VARCHAR(100),
    is_shared BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_mcp_tool_rules_task
    ON agent_mcp_tool_rules (task_type);
CREATE INDEX IF NOT EXISTS idx_mcp_tool_rules_owner
    ON agent_mcp_tool_rules (owner_username);
