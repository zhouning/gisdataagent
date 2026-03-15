-- v11.0.3: Proactive Exploration
-- Background data monitoring and analysis suggestion generation.

CREATE TABLE IF NOT EXISTS agent_proactive_observations (
    id SERIAL PRIMARY KEY,
    observation_id VARCHAR(36) UNIQUE NOT NULL,
    user_id VARCHAR(100) NOT NULL,
    file_path TEXT NOT NULL,
    file_hash VARCHAR(64),
    data_profile JSONB DEFAULT '{}'::jsonb,
    suggestions JSONB DEFAULT '[]'::jsonb,
    dismissed BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_po_user ON agent_proactive_observations(user_id);
CREATE INDEX IF NOT EXISTS idx_po_dismissed ON agent_proactive_observations(dismissed) WHERE dismissed = FALSE;
