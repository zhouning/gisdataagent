-- Token Usage Tracking table
-- Records per-pipeline LLM token consumption for cost management

CREATE TABLE IF NOT EXISTS agent_token_usage (
    id SERIAL PRIMARY KEY,
    username VARCHAR(100) NOT NULL,
    pipeline_type VARCHAR(30),
    model_name VARCHAR(50) DEFAULT 'gemini-2.5-flash',
    input_tokens INT DEFAULT 0,
    output_tokens INT DEFAULT 0,
    total_tokens INT DEFAULT 0,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_agent_token_usage_user ON agent_token_usage (username);
CREATE INDEX IF NOT EXISTS idx_agent_token_usage_date ON agent_token_usage (username, created_at);
