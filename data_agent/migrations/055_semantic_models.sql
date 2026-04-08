-- Migration 055: MetricFlow-compatible semantic models with GIS extensions (v19.0)
-- Stores YAML semantic model definitions for ContextEngine MetricDefinitionProvider

CREATE TABLE IF NOT EXISTS agent_semantic_models (
    id BIGSERIAL PRIMARY KEY,
    name VARCHAR(200) UNIQUE NOT NULL,
    description TEXT DEFAULT '',
    yaml_content TEXT NOT NULL,
    parsed JSONB,
    source_table VARCHAR(200),
    srid INTEGER,
    geometry_type VARCHAR(30),
    entities JSONB DEFAULT '[]'::jsonb,
    dimensions JSONB DEFAULT '[]'::jsonb,
    measures JSONB DEFAULT '[]'::jsonb,
    metrics JSONB DEFAULT '[]'::jsonb,
    version INTEGER DEFAULT 1,
    is_active BOOLEAN DEFAULT TRUE,
    created_by VARCHAR(100),
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_semmod_active
    ON agent_semantic_models (is_active, name);
CREATE INDEX IF NOT EXISTS idx_semmod_source
    ON agent_semantic_models (source_table);
