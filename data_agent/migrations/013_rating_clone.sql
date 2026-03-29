-- v14.0: Add rating and clone fields to custom_skills and user_tools
ALTER TABLE agent_custom_skills ADD COLUMN IF NOT EXISTS rating_sum INTEGER DEFAULT 0;
ALTER TABLE agent_custom_skills ADD COLUMN IF NOT EXISTS rating_count INTEGER DEFAULT 0;
ALTER TABLE agent_custom_skills ADD COLUMN IF NOT EXISTS clone_count INTEGER DEFAULT 0;

ALTER TABLE agent_user_tools ADD COLUMN IF NOT EXISTS rating_sum INTEGER DEFAULT 0;
ALTER TABLE agent_user_tools ADD COLUMN IF NOT EXISTS rating_count INTEGER DEFAULT 0;
ALTER TABLE agent_user_tools ADD COLUMN IF NOT EXISTS clone_count INTEGER DEFAULT 0;
