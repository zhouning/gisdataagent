-- v14.2: Skill publish approval workflow
ALTER TABLE agent_custom_skills ADD COLUMN IF NOT EXISTS publish_status VARCHAR(30) DEFAULT 'draft';
-- Values: draft | pending_approval | approved | rejected
ALTER TABLE agent_custom_skills ADD COLUMN IF NOT EXISTS review_note TEXT DEFAULT '';
ALTER TABLE agent_custom_skills ADD COLUMN IF NOT EXISTS reviewed_by VARCHAR(100) DEFAULT '';
