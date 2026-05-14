-- =============================================================================
-- Migration 070: enable ltree extension for std_clause.ordinal_path
-- =============================================================================
-- The standards_platform subsystem stores hierarchical clause paths
-- (e.g. "5.2.3") as ltree to enable subtree queries (<@, @>, ~).
-- pgvector is asserted as a system requirement (already installed 0.8.0).
-- =============================================================================

CREATE EXTENSION IF NOT EXISTS ltree;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'vector') THEN
        RAISE EXCEPTION 'pgvector extension is required but not installed. Install with: CREATE EXTENSION vector;';
    END IF;
END $$;
