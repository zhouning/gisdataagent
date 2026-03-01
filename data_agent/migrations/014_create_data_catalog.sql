-- Migration 014: Create Data Asset Catalog
-- Unified registry for data assets across local files, cloud storage, and PostGIS.
-- Run: psql -h <host> -U <admin> -d <db> -f 014_create_data_catalog.sql
-- Idempotent: safe to re-run.

-- ================================================================
-- PART 1: Create data catalog table
-- ================================================================
CREATE TABLE IF NOT EXISTS agent_data_catalog (
    id SERIAL PRIMARY KEY,
    asset_name VARCHAR(500) NOT NULL,
    asset_type VARCHAR(50) NOT NULL CHECK (asset_type IN
        ('raster','vector','tabular','map','report','script','other')),
    format VARCHAR(50) DEFAULT '',

    -- Storage location
    storage_backend VARCHAR(20) NOT NULL CHECK (storage_backend IN ('local','cloud','postgis')),
    cloud_key VARCHAR(1000) DEFAULT '',
    local_path VARCHAR(1000) DEFAULT '',
    postgis_table VARCHAR(255) DEFAULT '',

    -- Spatial metadata
    spatial_extent JSONB DEFAULT NULL,
    crs VARCHAR(50) DEFAULT '',
    srid INTEGER DEFAULT 0,
    feature_count INTEGER DEFAULT 0,
    file_size_bytes BIGINT DEFAULT 0,

    -- Data lineage
    creation_tool VARCHAR(200) DEFAULT '',
    creation_params JSONB DEFAULT '{}',
    source_assets JSONB DEFAULT '[]',

    -- Organization
    tags JSONB DEFAULT '[]',
    description TEXT DEFAULT '',

    -- Multi-tenancy
    owner_username VARCHAR(100) NOT NULL,
    is_shared BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),

    CONSTRAINT uq_asset_per_user UNIQUE (asset_name, owner_username, storage_backend)
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_data_catalog_owner ON agent_data_catalog (owner_username);
CREATE INDEX IF NOT EXISTS idx_data_catalog_type ON agent_data_catalog (asset_type);
CREATE INDEX IF NOT EXISTS idx_data_catalog_backend ON agent_data_catalog (storage_backend);
CREATE INDEX IF NOT EXISTS idx_data_catalog_shared ON agent_data_catalog (is_shared);
CREATE INDEX IF NOT EXISTS idx_data_catalog_tags ON agent_data_catalog USING GIN (tags);

-- ================================================================
-- PART 2: Enable RLS
-- ================================================================
ALTER TABLE agent_data_catalog ENABLE ROW LEVEL SECURITY;
ALTER TABLE agent_data_catalog FORCE ROW LEVEL SECURITY;

-- SELECT: own assets + shared + admin sees all
DROP POLICY IF EXISTS agent_data_catalog_select ON agent_data_catalog;
CREATE POLICY agent_data_catalog_select ON agent_data_catalog
    FOR SELECT
    USING (
        owner_username = current_setting('app.current_user', true)
        OR is_shared = TRUE
        OR current_setting('app.current_user_role', true) = 'admin'
    );

-- INSERT: own assets + admin
DROP POLICY IF EXISTS agent_data_catalog_insert ON agent_data_catalog;
CREATE POLICY agent_data_catalog_insert ON agent_data_catalog
    FOR INSERT
    WITH CHECK (
        owner_username = current_setting('app.current_user', true)
        OR current_setting('app.current_user_role', true) = 'admin'
    );

-- UPDATE: own assets + admin
DROP POLICY IF EXISTS agent_data_catalog_update ON agent_data_catalog;
CREATE POLICY agent_data_catalog_update ON agent_data_catalog
    FOR UPDATE
    USING (
        owner_username = current_setting('app.current_user', true)
        OR current_setting('app.current_user_role', true) = 'admin'
    );

-- DELETE: own assets + admin
DROP POLICY IF EXISTS agent_data_catalog_delete ON agent_data_catalog;
CREATE POLICY agent_data_catalog_delete ON agent_data_catalog
    FOR DELETE
    USING (
        owner_username = current_setting('app.current_user', true)
        OR current_setting('app.current_user_role', true) = 'admin'
    );

-- ================================================================
-- Verification
-- ================================================================
DO $$
DECLARE
    r RECORD;
BEGIN
    RAISE NOTICE '--- Data Catalog RLS Status ---';
    FOR r IN
        SELECT relname, relrowsecurity, relforcerowsecurity
        FROM pg_class WHERE relname = 'agent_data_catalog'
    LOOP
        RAISE NOTICE '  % : rls=%, force=%', r.relname, r.relrowsecurity, r.relforcerowsecurity;
    END LOOP;

    RAISE NOTICE '--- Data Catalog Policies ---';
    FOR r IN
        SELECT policyname, cmd FROM pg_policies
        WHERE tablename = 'agent_data_catalog' ORDER BY policyname
    LOOP
        RAISE NOTICE '  % (%)', r.policyname, r.cmd;
    END LOOP;
END $$;
