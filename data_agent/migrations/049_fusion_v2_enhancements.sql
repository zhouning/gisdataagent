-- Migration 049: Fusion v2.0 Enhancement columns
-- Extends agent_fusion_operations for temporal, semantic, conflict, explainability metadata
-- Adds ontology cache table for GIS domain ontology

ALTER TABLE agent_fusion_operations
ADD COLUMN IF NOT EXISTS temporal_alignment_log TEXT,
ADD COLUMN IF NOT EXISTS semantic_enhancement_log TEXT,
ADD COLUMN IF NOT EXISTS conflict_resolution_log TEXT,
ADD COLUMN IF NOT EXISTS explainability_metadata JSONB;

CREATE INDEX IF NOT EXISTS idx_fusion_ops_explainability
ON agent_fusion_operations USING GIN (explainability_metadata);

CREATE TABLE IF NOT EXISTS agent_fusion_ontology_cache (
    id SERIAL PRIMARY KEY,
    field_name VARCHAR(255) NOT NULL,
    equivalent_fields JSONB DEFAULT '[]'::jsonb,
    derivation_rules JSONB DEFAULT '[]'::jsonb,
    semantic_type VARCHAR(100),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(field_name)
);

CREATE INDEX IF NOT EXISTS idx_ontology_cache_field
ON agent_fusion_ontology_cache (field_name);
