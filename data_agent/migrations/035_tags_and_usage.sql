-- Tags, categories, and usage stats for Skills and Tools (v15.0 cleanup)

-- Skills: add category, tags, use_count
ALTER TABLE agent_custom_skills ADD COLUMN IF NOT EXISTS category VARCHAR(50) DEFAULT '';
ALTER TABLE agent_custom_skills ADD COLUMN IF NOT EXISTS tags JSONB DEFAULT '[]';
ALTER TABLE agent_custom_skills ADD COLUMN IF NOT EXISTS use_count INTEGER DEFAULT 0;

-- User Tools: add category, tags, use_count
ALTER TABLE agent_user_tools ADD COLUMN IF NOT EXISTS category VARCHAR(50) DEFAULT '';
ALTER TABLE agent_user_tools ADD COLUMN IF NOT EXISTS tags JSONB DEFAULT '[]';
ALTER TABLE agent_user_tools ADD COLUMN IF NOT EXISTS use_count INTEGER DEFAULT 0;
