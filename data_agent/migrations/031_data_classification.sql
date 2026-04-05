-- Data Classification: add sensitivity fields to data catalog (v15.0)
-- agent_data_catalog may be a VIEW (after migration 048), so target the underlying table.

DO $$
BEGIN
    -- Try the deprecated table first (after 048 runs, the real table is here)
    IF EXISTS (SELECT 1 FROM pg_tables WHERE schemaname='public' AND tablename='agent_data_catalog_deprecated') THEN
        ALTER TABLE agent_data_catalog_deprecated ADD COLUMN IF NOT EXISTS sensitivity_level VARCHAR(20) DEFAULT 'public';
        ALTER TABLE agent_data_catalog_deprecated ADD COLUMN IF NOT EXISTS field_classifications JSONB DEFAULT '{}';
    -- If 048 hasn't run yet, agent_data_catalog is still a table
    ELSIF EXISTS (SELECT 1 FROM pg_tables WHERE schemaname='public' AND tablename='agent_data_catalog') THEN
        ALTER TABLE agent_data_catalog ADD COLUMN IF NOT EXISTS sensitivity_level VARCHAR(20) DEFAULT 'public';
        ALTER TABLE agent_data_catalog ADD COLUMN IF NOT EXISTS field_classifications JSONB DEFAULT '{}';
    END IF;
END $$;
