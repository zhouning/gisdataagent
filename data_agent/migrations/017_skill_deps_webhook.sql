-- v14.3: Skill dependency graph and webhook triggers
ALTER TABLE agent_custom_skills ADD COLUMN IF NOT EXISTS depends_on INTEGER[] DEFAULT '{}'::integer[];
ALTER TABLE agent_custom_skills ADD COLUMN IF NOT EXISTS webhook_url VARCHAR(500) DEFAULT '';
ALTER TABLE agent_custom_skills ADD COLUMN IF NOT EXISTS webhook_events TEXT[] DEFAULT '{}'::text[];
