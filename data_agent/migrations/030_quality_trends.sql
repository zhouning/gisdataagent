-- Quality Trends — historical quality inspection results for trend tracking (v14.5)
CREATE TABLE IF NOT EXISTS agent_quality_trends (
    id SERIAL PRIMARY KEY,
    asset_name VARCHAR(300),
    standard_id VARCHAR(100),
    score NUMERIC(5,1),
    dimension_scores JSONB DEFAULT '{}',
    issues_count INTEGER DEFAULT 0,
    rule_results JSONB DEFAULT '{}',
    run_by VARCHAR(100),
    created_at TIMESTAMP DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_qtrend_asset ON agent_quality_trends (asset_name);
CREATE INDEX IF NOT EXISTS idx_qtrend_time ON agent_quality_trends (created_at);
