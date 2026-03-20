-- v12.2: Semantic metrics — business metric definitions for natural language → SQL mapping
CREATE TABLE IF NOT EXISTS agent_semantic_metrics (
    id SERIAL PRIMARY KEY,
    metric_name VARCHAR(200) NOT NULL,
    definition TEXT NOT NULL,
    domain VARCHAR(100) DEFAULT '',
    description TEXT DEFAULT '',
    unit VARCHAR(50) DEFAULT '',
    aliases TEXT DEFAULT '',
    owner_username VARCHAR(100) NOT NULL DEFAULT 'system',
    created_at TIMESTAMP DEFAULT NOW(),
    CONSTRAINT uq_metric_name_owner UNIQUE (metric_name, owner_username)
);

CREATE INDEX IF NOT EXISTS idx_semantic_metrics_domain ON agent_semantic_metrics (domain);
