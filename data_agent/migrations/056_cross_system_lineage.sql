-- Migration 056: Cross-system lineage tracking (v21.0)
-- Extends agent_data_assets with external system fields + dedicated lineage edge table

-- 1. Add external system fields to agent_data_assets
ALTER TABLE agent_data_assets
    ADD COLUMN IF NOT EXISTS external_system VARCHAR(100),
    ADD COLUMN IF NOT EXISTS external_id VARCHAR(500),
    ADD COLUMN IF NOT EXISTS external_url TEXT,
    ADD COLUMN IF NOT EXISTS external_metadata JSONB DEFAULT '{}'::jsonb;

CREATE INDEX IF NOT EXISTS idx_assets_external
    ON agent_data_assets (external_system, external_id);

-- 2. Dedicated lineage edge table (supports internal↔external any combination)
CREATE TABLE IF NOT EXISTS agent_asset_lineage (
    id BIGSERIAL PRIMARY KEY,
    source_asset_id INTEGER REFERENCES agent_data_assets(id) ON DELETE CASCADE,
    source_external_system VARCHAR(100),
    source_external_id VARCHAR(500),
    target_asset_id INTEGER REFERENCES agent_data_assets(id) ON DELETE CASCADE,
    target_external_system VARCHAR(100),
    target_external_id VARCHAR(500),
    relationship VARCHAR(50) DEFAULT 'derives_from',
    tool_name VARCHAR(200),
    pipeline_run_id VARCHAR(100),
    metadata JSONB DEFAULT '{}'::jsonb,
    created_by VARCHAR(100),
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_lineage_source ON agent_asset_lineage (source_asset_id);
CREATE INDEX IF NOT EXISTS idx_lineage_target ON agent_asset_lineage (target_asset_id);
CREATE INDEX IF NOT EXISTS idx_lineage_ext_src ON agent_asset_lineage (source_external_system, source_external_id);
CREATE INDEX IF NOT EXISTS idx_lineage_ext_tgt ON agent_asset_lineage (target_external_system, target_external_id);
