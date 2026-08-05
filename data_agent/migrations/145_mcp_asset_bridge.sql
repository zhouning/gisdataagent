-- Governed execution receipts for catalog-asset MCP workflows.
-- Remote artifact IDs, job IDs, bearer tokens, and signed URLs are excluded.

CREATE TABLE IF NOT EXISTS agent_mcp_asset_runs (
    run_id UUID PRIMARY KEY,
    requested_by VARCHAR(100) NOT NULL,
    server_name VARCHAR(100) NOT NULL,
    operation VARCHAR(100) NOT NULL,
    status VARCHAR(30) NOT NULL DEFAULT 'queued',
    source_asset_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
    output_asset_id INTEGER REFERENCES agent_data_assets(id) ON DELETE SET NULL,
    input_sha256 VARCHAR(64),
    output_sha256 VARCHAR(64),
    stages JSONB NOT NULL DEFAULT '[]'::jsonb,
    error_code VARCHAR(100),
    error_message TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_mcp_asset_runs_requested_by
    ON agent_mcp_asset_runs (requested_by, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_mcp_asset_runs_output_asset
    ON agent_mcp_asset_runs (output_asset_id);
