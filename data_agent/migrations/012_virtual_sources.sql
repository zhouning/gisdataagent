-- v13.0: Virtual data sources — remote WFS/STAC/OGC API/custom API connectors
CREATE TABLE IF NOT EXISTS agent_virtual_sources (
    id SERIAL PRIMARY KEY,
    source_name VARCHAR(200) NOT NULL,
    source_type VARCHAR(30) NOT NULL,
    endpoint_url VARCHAR(1000) NOT NULL,
    auth_config JSONB DEFAULT '{}',
    query_config JSONB DEFAULT '{}',
    schema_mapping JSONB DEFAULT '{}',
    default_crs VARCHAR(50) DEFAULT 'EPSG:4326',
    spatial_extent JSONB DEFAULT NULL,
    refresh_policy VARCHAR(30) DEFAULT 'on_demand',
    enabled BOOLEAN DEFAULT TRUE,
    owner_username VARCHAR(100) NOT NULL,
    is_shared BOOLEAN DEFAULT FALSE,
    last_health_check TIMESTAMP DEFAULT NULL,
    health_status VARCHAR(20) DEFAULT 'unknown',
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    CONSTRAINT uq_vsource UNIQUE (source_name, owner_username)
);

CREATE INDEX IF NOT EXISTS idx_vsource_owner ON agent_virtual_sources (owner_username);
CREATE INDEX IF NOT EXISTS idx_vsource_type ON agent_virtual_sources (source_type);
