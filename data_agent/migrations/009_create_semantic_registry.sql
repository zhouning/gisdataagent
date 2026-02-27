-- =============================================================================
-- Migration 009: Create Spatial Semantic Registry tables
-- Stores per-table and per-column semantic annotations.
-- =============================================================================

-- Column-level semantic annotations
CREATE TABLE IF NOT EXISTS agent_semantic_registry (
    id SERIAL PRIMARY KEY,
    table_name VARCHAR(255) NOT NULL,
    column_name VARCHAR(255) NOT NULL,
    semantic_domain VARCHAR(100),
    aliases JSONB DEFAULT '[]',
    unit VARCHAR(50),
    description TEXT DEFAULT '',
    is_geometry BOOLEAN DEFAULT FALSE,
    owner_username VARCHAR(100) NOT NULL,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(table_name, column_name)
);

CREATE INDEX IF NOT EXISTS idx_semantic_registry_table
    ON agent_semantic_registry(table_name);
CREATE INDEX IF NOT EXISTS idx_semantic_registry_domain
    ON agent_semantic_registry(semantic_domain);

-- Table-level semantic metadata
CREATE TABLE IF NOT EXISTS agent_semantic_sources (
    id SERIAL PRIMARY KEY,
    table_name VARCHAR(255) UNIQUE NOT NULL,
    display_name VARCHAR(255) DEFAULT '',
    description TEXT DEFAULT '',
    geometry_type VARCHAR(50),
    srid INTEGER,
    synonyms JSONB DEFAULT '[]',
    suggested_analyses JSONB DEFAULT '[]',
    owner_username VARCHAR(100) NOT NULL,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_semantic_sources_owner
    ON agent_semantic_sources(owner_username);
