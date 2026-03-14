-- v10.0.2: User Custom Skill Bundles
-- DB-driven user-defined toolset+skill compositions.

CREATE TABLE IF NOT EXISTS agent_skill_bundles (
    id SERIAL PRIMARY KEY,
    owner_username VARCHAR(100) NOT NULL,
    bundle_name VARCHAR(100) NOT NULL,
    description TEXT DEFAULT '',
    toolset_names TEXT[] DEFAULT '{}'::text[],
    skill_names TEXT[] DEFAULT '{}'::text[],
    intent_triggers TEXT[] DEFAULT '{}'::text[],
    is_shared BOOLEAN DEFAULT FALSE,
    enabled BOOLEAN DEFAULT TRUE,
    use_count INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(owner_username, bundle_name)
);

CREATE INDEX IF NOT EXISTS idx_sb_owner ON agent_skill_bundles(owner_username);
CREATE INDEX IF NOT EXISTS idx_sb_shared ON agent_skill_bundles(is_shared) WHERE is_shared = TRUE;
