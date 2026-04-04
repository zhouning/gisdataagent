-- Migration 051: Data Asset Coding System
-- Adds structured asset_code to agent_data_assets and links fusion operations to assets

-- 1. Add asset_code column to agent_data_assets
ALTER TABLE agent_data_assets
ADD COLUMN IF NOT EXISTS asset_code VARCHAR(50) UNIQUE;

CREATE INDEX IF NOT EXISTS idx_data_assets_code
ON agent_data_assets (asset_code);

-- 2. Add output asset linkage to fusion operations
ALTER TABLE agent_fusion_operations
ADD COLUMN IF NOT EXISTS output_asset_id INTEGER,
ADD COLUMN IF NOT EXISTS output_asset_code VARCHAR(50);

-- 3. Backfill existing assets with codes
-- Format: DA-{TYPE}-{OWNER_3}-{YEAR}-{HEX_ID}
UPDATE agent_data_assets
SET asset_code = 'DA-'
    || CASE
        WHEN business_metadata->'classification'->>'category' = 'vector' THEN 'VEC'
        WHEN business_metadata->'classification'->>'category' = 'raster' THEN 'RAS'
        WHEN business_metadata->'classification'->>'category' = 'tabular' THEN 'TAB'
        ELSE 'OTH'
    END
    || '-'
    || UPPER(SUBSTRING(owner_username FROM 1 FOR 3))
    || '-'
    || EXTRACT(YEAR FROM created_at)::TEXT
    || '-'
    || LPAD(UPPER(TO_HEX(id)), 4, '0')
WHERE asset_code IS NULL;
