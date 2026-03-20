-- v14.1: Version management, tags, and usage tracking for skills and tools
ALTER TABLE agent_custom_skills ADD COLUMN IF NOT EXISTS version INTEGER DEFAULT 1;
ALTER TABLE agent_custom_skills ADD COLUMN IF NOT EXISTS category VARCHAR(50) DEFAULT '';
ALTER TABLE agent_custom_skills ADD COLUMN IF NOT EXISTS tags TEXT[] DEFAULT '{}'::text[];
ALTER TABLE agent_custom_skills ADD COLUMN IF NOT EXISTS use_count INTEGER DEFAULT 0;

ALTER TABLE agent_user_tools ADD COLUMN IF NOT EXISTS version INTEGER DEFAULT 1;
ALTER TABLE agent_user_tools ADD COLUMN IF NOT EXISTS category VARCHAR(50) DEFAULT '';
ALTER TABLE agent_user_tools ADD COLUMN IF NOT EXISTS tags TEXT[] DEFAULT '{}'::text[];
ALTER TABLE agent_user_tools ADD COLUMN IF NOT EXISTS use_count INTEGER DEFAULT 0;

-- Version history tables
CREATE TABLE IF NOT EXISTS agent_skill_versions (
    id SERIAL PRIMARY KEY,
    skill_id INTEGER NOT NULL,
    version INTEGER NOT NULL,
    instruction TEXT NOT NULL,
    description TEXT DEFAULT '',
    toolset_names TEXT[] DEFAULT '{}'::text[],
    created_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(skill_id, version)
);

CREATE TABLE IF NOT EXISTS agent_tool_versions (
    id SERIAL PRIMARY KEY,
    tool_id INTEGER NOT NULL,
    version INTEGER NOT NULL,
    description TEXT DEFAULT '',
    parameters JSONB DEFAULT '[]',
    template_config JSONB DEFAULT '{}',
    created_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(tool_id, version)
);
