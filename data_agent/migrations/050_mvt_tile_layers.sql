-- Migration 050: MVT tile layer management table
-- Tracks temporary PostGIS tables created for vector tile serving

CREATE TABLE IF NOT EXISTS agent_mvt_layers (
    id SERIAL PRIMARY KEY,
    layer_id VARCHAR(64) NOT NULL UNIQUE,
    table_name VARCHAR(63) NOT NULL,
    owner_username VARCHAR(255) NOT NULL,
    layer_name VARCHAR(255),
    srid INTEGER DEFAULT 4326,
    feature_count INTEGER DEFAULT 0,
    bounds DOUBLE PRECISION[4],        -- [west, south, east, north]
    columns TEXT[],
    source_file VARCHAR(512),
    created_at TIMESTAMP DEFAULT NOW(),
    expires_at TIMESTAMP DEFAULT (NOW() + INTERVAL '24 hours')
);

CREATE INDEX IF NOT EXISTS idx_mvt_layers_owner ON agent_mvt_layers(owner_username);
CREATE INDEX IF NOT EXISTS idx_mvt_layers_expires ON agent_mvt_layers(expires_at);
