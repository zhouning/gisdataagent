-- Data Versioning: version field + snapshot history (v15.0)

ALTER TABLE agent_data_catalog ADD COLUMN IF NOT EXISTS version INTEGER DEFAULT 1;
ALTER TABLE agent_data_catalog ADD COLUMN IF NOT EXISTS version_note TEXT DEFAULT '';

CREATE TABLE IF NOT EXISTS agent_asset_versions (
    id SERIAL PRIMARY KEY,
    asset_id INTEGER NOT NULL,
    version INTEGER NOT NULL,
    snapshot_path TEXT,
    file_size_bytes BIGINT DEFAULT 0,
    feature_count INTEGER DEFAULT 0,
    change_summary TEXT DEFAULT '',
    created_by VARCHAR(100),
    created_at TIMESTAMP DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_asset_ver_asset ON agent_asset_versions (asset_id);

CREATE TABLE IF NOT EXISTS agent_update_notifications (
    id SERIAL PRIMARY KEY,
    asset_id INTEGER NOT NULL,
    asset_name VARCHAR(300),
    update_type VARCHAR(30) DEFAULT 'version',
    message TEXT DEFAULT '',
    notified_users JSONB DEFAULT '[]',
    is_read BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_notif_time ON agent_update_notifications (created_at);
