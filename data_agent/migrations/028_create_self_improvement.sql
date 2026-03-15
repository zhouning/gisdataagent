-- v11.0.5: Self-Improvement (Design Pattern Ch20)
-- Tracks prompt outcomes and tool preferences for continuous improvement.

CREATE TABLE IF NOT EXISTS agent_prompt_outcomes (
    id SERIAL PRIMARY KEY,
    pipeline_type VARCHAR(30) NOT NULL,
    prompt_hash VARCHAR(64) NOT NULL,
    success BOOLEAN DEFAULT TRUE,
    confidence REAL DEFAULT 0.5,
    duration REAL DEFAULT 0,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_apo_pipeline ON agent_prompt_outcomes(pipeline_type);
CREATE INDEX IF NOT EXISTS idx_apo_hash ON agent_prompt_outcomes(prompt_hash);

CREATE TABLE IF NOT EXISTS agent_tool_preferences (
    id SERIAL PRIMARY KEY,
    tool_name VARCHAR(100) NOT NULL,
    data_type VARCHAR(50) DEFAULT '',
    crs VARCHAR(50) DEFAULT '',
    success_rate REAL DEFAULT 0.5,
    avg_duration REAL DEFAULT 0,
    sample_count INTEGER DEFAULT 0,
    updated_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(tool_name, data_type, crs)
);

CREATE INDEX IF NOT EXISTS idx_atp_tool ON agent_tool_preferences(tool_name);
