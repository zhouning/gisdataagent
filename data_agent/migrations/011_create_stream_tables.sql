-- Migration 011: Create stream tables for real-time data processing
-- ============================================================================

-- Stream configurations
CREATE TABLE IF NOT EXISTS stream_configs (
    id VARCHAR(100) PRIMARY KEY,
    name VARCHAR(200) NOT NULL,
    geofence GEOMETRY(Polygon, 4326),
    window_seconds INT DEFAULT 60,
    status VARCHAR(20) DEFAULT 'active',
    owner_username VARCHAR(100),
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Stream location events (time-series)
CREATE TABLE IF NOT EXISTS stream_locations (
    time TIMESTAMPTZ NOT NULL,
    device_id VARCHAR(100) NOT NULL,
    stream_id VARCHAR(100) NOT NULL,
    geom GEOMETRY(Point, 4326),
    speed FLOAT,
    heading FLOAT,
    payload JSONB DEFAULT '{}',
    owner_username VARCHAR(100)
);

-- Index for time-range queries
CREATE INDEX IF NOT EXISTS idx_stream_locations_time
    ON stream_locations (stream_id, time DESC);

-- Index for device lookups
CREATE INDEX IF NOT EXISTS idx_stream_locations_device
    ON stream_locations (device_id, time DESC);

-- Optional: Convert to TimescaleDB hypertable if available
-- Uncomment if TimescaleDB extension is installed:
-- CREATE EXTENSION IF NOT EXISTS timescaledb CASCADE;
-- SELECT create_hypertable('stream_locations', 'time', if_not_exists => TRUE);

-- Stream alerts
CREATE TABLE IF NOT EXISTS stream_alerts (
    id SERIAL PRIMARY KEY,
    stream_id VARCHAR(100) REFERENCES stream_configs(id) ON DELETE CASCADE,
    alert_type VARCHAR(50) NOT NULL,
    geofence GEOMETRY(Polygon, 4326),
    triggered_at TIMESTAMPTZ DEFAULT NOW(),
    device_id VARCHAR(100),
    details JSONB DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_stream_alerts_stream
    ON stream_alerts (stream_id, triggered_at DESC);
