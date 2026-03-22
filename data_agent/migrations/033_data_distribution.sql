-- Data Distribution: requests, reviews, access log (v15.0)

CREATE TABLE IF NOT EXISTS agent_data_requests (
    id SERIAL PRIMARY KEY,
    asset_id INTEGER NOT NULL,
    requester VARCHAR(100) NOT NULL,
    approver VARCHAR(100),
    status VARCHAR(20) DEFAULT 'pending',
    reason TEXT DEFAULT '',
    reject_reason TEXT DEFAULT '',
    approved_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_dreq_requester ON agent_data_requests (requester);
CREATE INDEX IF NOT EXISTS idx_dreq_status ON agent_data_requests (status);

CREATE TABLE IF NOT EXISTS agent_asset_reviews (
    id SERIAL PRIMARY KEY,
    asset_id INTEGER NOT NULL,
    username VARCHAR(100) NOT NULL,
    rating INTEGER CHECK (rating BETWEEN 1 AND 5),
    comment TEXT DEFAULT '',
    created_at TIMESTAMP DEFAULT NOW(),
    CONSTRAINT uq_asset_review UNIQUE (asset_id, username)
);

CREATE TABLE IF NOT EXISTS agent_asset_access_log (
    id BIGSERIAL PRIMARY KEY,
    asset_id INTEGER NOT NULL,
    username VARCHAR(100) NOT NULL,
    access_type VARCHAR(20) DEFAULT 'view',
    created_at TIMESTAMP DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_alog_asset ON agent_asset_access_log (asset_id);
CREATE INDEX IF NOT EXISTS idx_alog_time ON agent_asset_access_log (created_at);
