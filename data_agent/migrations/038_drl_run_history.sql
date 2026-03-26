-- DRL optimization run history for A/B comparison (v15.4)
CREATE TABLE IF NOT EXISTS drl_run_history (
    id SERIAL PRIMARY KEY,
    username VARCHAR(100) NOT NULL,
    scenario_id VARCHAR(50) NOT NULL DEFAULT 'farmland_optimization',
    weights JSONB NOT NULL DEFAULT '{}',
    output_path VARCHAR(500) DEFAULT '',
    summary TEXT DEFAULT '',
    metrics JSONB NOT NULL DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_drl_history_user ON drl_run_history (username, created_at DESC);
