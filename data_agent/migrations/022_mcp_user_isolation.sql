-- v10.0.1: Per-User MCP Isolation
-- Adds owner_username and is_shared columns to agent_mcp_servers
-- for user-scoped MCP server management.
-- Existing rows remain globally visible (owner_username=NULL, is_shared=TRUE).

ALTER TABLE agent_mcp_servers ADD COLUMN IF NOT EXISTS owner_username VARCHAR(100);
ALTER TABLE agent_mcp_servers ADD COLUMN IF NOT EXISTS is_shared BOOLEAN DEFAULT TRUE;

CREATE INDEX IF NOT EXISTS idx_mcp_owner ON agent_mcp_servers(owner_username);
