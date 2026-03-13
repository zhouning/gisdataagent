-- v8.0.1: DB-driven Custom Skills
-- Users can create custom expert agents with tailored instructions and tools.

CREATE TABLE IF NOT EXISTS agent_custom_skills (
    id SERIAL PRIMARY KEY,
    owner_username VARCHAR(100) NOT NULL,
    skill_name VARCHAR(100) NOT NULL,
    description TEXT DEFAULT '',
    instruction TEXT NOT NULL,
    toolset_names TEXT[] DEFAULT '{}',
    trigger_keywords TEXT[] DEFAULT '{}',
    model_tier VARCHAR(20) DEFAULT 'standard',
    is_shared BOOLEAN DEFAULT FALSE,
    enabled BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(owner_username, skill_name)
);

CREATE INDEX IF NOT EXISTS idx_cs_owner ON agent_custom_skills(owner_username);
CREATE INDEX IF NOT EXISTS idx_cs_shared ON agent_custom_skills(is_shared) WHERE is_shared = TRUE;
CREATE INDEX IF NOT EXISTS idx_cs_enabled ON agent_custom_skills(enabled) WHERE enabled = TRUE;
