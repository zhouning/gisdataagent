-- Migration 048: Unify Data Asset Tables (TD-001 fix)
-- Migrate remaining data from agent_data_catalog to agent_data_assets and deprecate old table

-- Step 1: Migrate any new records created after migration 044
INSERT INTO agent_data_assets (
    asset_name, display_name, owner_username, is_shared,
    technical_metadata, business_metadata, operational_metadata, lineage_metadata,
    created_at, updated_at
)
SELECT
    asset_name,
    asset_name as display_name,
    owner_username,
    is_shared,
    -- Technical metadata
    jsonb_build_object(
        'storage', jsonb_build_object(
            'backend', COALESCE(storage_backend, 'local'),
            'path', COALESCE(local_path, cloud_key, ''),
            'cloud_key', cloud_key,
            'postgis_table', postgis_table,
            'size_bytes', file_size_bytes,
            'format', format
        ),
        'spatial', jsonb_build_object(
            'extent', spatial_extent,
            'crs', crs,
            'srid', srid
        ),
        'structure', jsonb_build_object(
            'feature_count', feature_count
        )
    ),
    -- Business metadata
    jsonb_build_object(
        'semantic', jsonb_build_object(
            'description', description,
            'keywords', tags
        ),
        'classification', jsonb_build_object(
            'category', asset_type
        )
    ),
    -- Operational metadata
    jsonb_build_object(
        'creation', jsonb_build_object(
            'tool', creation_tool,
            'params', creation_params
        ),
        'version', jsonb_build_object(
            'version', COALESCE(version, 1),
            'is_latest', true
        )
    ),
    -- Lineage metadata
    jsonb_build_object(
        'upstream', jsonb_build_object(
            'asset_ids', source_assets
        )
    ),
    created_at,
    updated_at
FROM agent_data_catalog
WHERE NOT EXISTS (
    SELECT 1 FROM agent_data_assets
    WHERE agent_data_assets.asset_name = agent_data_catalog.asset_name
    AND agent_data_assets.owner_username = agent_data_catalog.owner_username
)
ON CONFLICT DO NOTHING;

-- Step 2: Rename old table for backup (don't drop yet for safety)
ALTER TABLE agent_data_catalog RENAME TO agent_data_catalog_deprecated;

-- Step 3: Create view with old table name for backward compatibility during transition
CREATE OR REPLACE VIEW agent_data_catalog AS
SELECT
    id,
    asset_name,
    (business_metadata->'classification'->>'category') as asset_type,
    (technical_metadata->'storage'->>'format') as format,
    (technical_metadata->'storage'->>'backend') as storage_backend,
    (technical_metadata->'storage'->>'cloud_key') as cloud_key,
    (technical_metadata->'storage'->>'path') as local_path,
    (technical_metadata->'storage'->>'postgis_table') as postgis_table,
    (technical_metadata->'spatial'->'extent') as spatial_extent,
    (technical_metadata->'spatial'->>'crs') as crs,
    CAST((technical_metadata->'spatial'->>'srid') AS INTEGER) as srid,
    CAST((technical_metadata->'structure'->>'feature_count') AS INTEGER) as feature_count,
    CAST((technical_metadata->'storage'->>'size_bytes') AS BIGINT) as file_size_bytes,
    (operational_metadata->'creation'->>'tool') as creation_tool,
    (operational_metadata->'creation'->'params') as creation_params,
    (lineage_metadata->'upstream'->'asset_ids') as source_assets,
    (business_metadata->'semantic'->'keywords') as tags,
    (business_metadata->'semantic'->>'description') as description,
    owner_username,
    is_shared,
    CAST((operational_metadata->'version'->>'version') AS INTEGER) as version,
    created_at,
    updated_at
FROM agent_data_assets;
