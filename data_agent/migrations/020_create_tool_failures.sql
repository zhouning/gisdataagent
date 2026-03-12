-- 020: Tool failure learning table
-- Records tool errors and hints for adaptive self-correction.

CREATE TABLE IF NOT EXISTS agent_tool_failures (
    id SERIAL PRIMARY KEY,
    username VARCHAR(100) NOT NULL,
    tool_name VARCHAR(200) NOT NULL,
    error_snippet VARCHAR(500),
    hint_applied TEXT,
    resolved BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_tf_tool ON agent_tool_failures(tool_name);
CREATE INDEX IF NOT EXISTS idx_tf_user ON agent_tool_failures(username);
CREATE INDEX IF NOT EXISTS idx_tf_created ON agent_tool_failures(created_at DESC);
