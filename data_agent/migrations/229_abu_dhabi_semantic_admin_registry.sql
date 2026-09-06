-- 229: Product semantic administration registry.
--
-- The customer console must not edit generated evidence JSON in place.  This
-- registry stores human changes as versioned, auditable drafts and lets the
-- runtime consume only an explicitly published version in a later promotion
-- step.  Payloads are intentionally JSONB because the two source catalogs
-- have different field and contract shapes.

CREATE TABLE IF NOT EXISTS agent_semantic_admin_versions (
    id BIGSERIAL PRIMARY KEY,
    scope VARCHAR(32) NOT NULL CHECK (scope ~ '^[A-Za-z0-9][A-Za-z0-9_.:-]{0,31}$'),
    version_label VARCHAR(120) NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'draft'
        CHECK (status IN ('draft', 'reviewed', 'published', 'rolled_back')),
    created_by VARCHAR(255) NOT NULL,
    reviewed_by VARCHAR(255),
    published_by VARCHAR(255),
    review_notes TEXT NOT NULL DEFAULT '',
    validation_report JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    reviewed_at TIMESTAMPTZ,
    published_at TIMESTAMPTZ,
    UNIQUE (scope, version_label)
);

CREATE INDEX IF NOT EXISTS idx_semantic_admin_versions_scope_status
    ON agent_semantic_admin_versions (scope, status, updated_at DESC);

CREATE TABLE IF NOT EXISTS agent_semantic_admin_entries (
    id BIGSERIAL PRIMARY KEY,
    version_id BIGINT NOT NULL REFERENCES agent_semantic_admin_versions(id)
        ON DELETE CASCADE,
    scope VARCHAR(32) NOT NULL CHECK (scope ~ '^[A-Za-z0-9][A-Za-z0-9_.:-]{0,31}$'),
    entry_type VARCHAR(32) NOT NULL CHECK (entry_type IN
        ('assets', 'fields', 'relationships', 'metric_contracts')),
    natural_key VARCHAR(512) NOT NULL,
    payload JSONB NOT NULL,
    state VARCHAR(20) NOT NULL DEFAULT 'draft'
        CHECK (state IN ('draft', 'published', 'deleted')),
    created_by VARCHAR(255) NOT NULL,
    updated_by VARCHAR(255) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (version_id, entry_type, natural_key)
);

CREATE INDEX IF NOT EXISTS idx_semantic_admin_entries_lookup
    ON agent_semantic_admin_entries (scope, entry_type, state, updated_at DESC);

CREATE INDEX IF NOT EXISTS idx_semantic_admin_entries_version
    ON agent_semantic_admin_entries (version_id, entry_type);
