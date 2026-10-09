-- Versioned custom agents, immutable release snapshots, and deployment history.
CREATE TABLE IF NOT EXISTS agent_definitions (
    id BIGSERIAL PRIMARY KEY,
    tenant_id VARCHAR(100) NOT NULL,
    owner_username VARCHAR(100) NOT NULL,
    name VARCHAR(120) NOT NULL,
    slug VARCHAR(140) NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    status VARCHAR(30) NOT NULL DEFAULT 'draft'
        CHECK (status IN ('draft', 'testing', 'pending_approval', 'approved', 'published', 'disabled', 'archived')),
    current_version INTEGER NOT NULL DEFAULT 1,
    active_version INTEGER,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    archived_at TIMESTAMPTZ,
    UNIQUE (tenant_id, owner_username, slug)
);

CREATE INDEX IF NOT EXISTS idx_agent_definitions_scope
    ON agent_definitions (tenant_id, owner_username, status);

CREATE TABLE IF NOT EXISTS agent_versions (
    id BIGSERIAL PRIMARY KEY,
    agent_id BIGINT NOT NULL REFERENCES agent_definitions(id) ON DELETE CASCADE,
    version INTEGER NOT NULL,
    status VARCHAR(30) NOT NULL DEFAULT 'draft'
        CHECK (status IN ('draft', 'testing', 'pending_approval', 'approved', 'published', 'rejected')),
    spec_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    test_passed_at TIMESTAMPTZ,
    test_report JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_by VARCHAR(100) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (agent_id, version)
);

CREATE TABLE IF NOT EXISTS agent_version_skills (
    version_id BIGINT NOT NULL REFERENCES agent_versions(id) ON DELETE CASCADE,
    skill_id INTEGER NOT NULL,
    skill_version INTEGER NOT NULL,
    snapshot_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    PRIMARY KEY (version_id, skill_id)
);

-- Existing skills start at their current version. Materialize that version so
-- agents can pin a concrete skill snapshot instead of following mutable data.
INSERT INTO agent_skill_versions (skill_id, version, instruction, description, toolset_names)
SELECT id, COALESCE(version, 1), instruction, COALESCE(description, ''),
       COALESCE(toolset_names, '{}'::text[])
FROM agent_custom_skills
ON CONFLICT (skill_id, version) DO NOTHING;

CREATE TABLE IF NOT EXISTS agent_version_tools (
    version_id BIGINT NOT NULL REFERENCES agent_versions(id) ON DELETE CASCADE,
    toolset_name VARCHAR(100) NOT NULL,
    PRIMARY KEY (version_id, toolset_name)
);

CREATE TABLE IF NOT EXISTS agent_deployments (
    id BIGSERIAL PRIMARY KEY,
    agent_id BIGINT NOT NULL REFERENCES agent_definitions(id) ON DELETE CASCADE,
    version_id BIGINT NOT NULL REFERENCES agent_versions(id),
    revision INTEGER NOT NULL,
    environment VARCHAR(40) NOT NULL DEFAULT 'production',
    state VARCHAR(20) NOT NULL DEFAULT 'active'
        CHECK (state IN ('active', 'disabled', 'superseded')),
    traffic_percent SMALLINT NOT NULL DEFAULT 100
        CHECK (traffic_percent BETWEEN 0 AND 100),
    deployed_by VARCHAR(100) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (agent_id, revision)
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_agent_deployments_active
    ON agent_deployments (agent_id, environment) WHERE state = 'active';

CREATE TABLE IF NOT EXISTS agent_lifecycle_events (
    id BIGSERIAL PRIMARY KEY,
    agent_id BIGINT NOT NULL REFERENCES agent_definitions(id) ON DELETE CASCADE,
    version INTEGER,
    event_type VARCHAR(40) NOT NULL,
    actor_username VARCHAR(100) NOT NULL,
    details JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_agent_lifecycle_events_agent
    ON agent_lifecycle_events (agent_id, created_at DESC);
