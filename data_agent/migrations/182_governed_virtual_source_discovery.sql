-- 182: Product-governed virtual source definitions and metadata-only discovery evidence.
-- Source credentials remain in the existing encrypted auth_config column. The new
-- documents are deliberately secret-free and may be exposed to authorized operators.

ALTER TABLE agent_virtual_sources
    ADD COLUMN IF NOT EXISTS credential_reference JSONB NOT NULL DEFAULT '{}'::jsonb,
    ADD COLUMN IF NOT EXISTS source_definition JSONB NOT NULL DEFAULT '{}'::jsonb,
    ADD COLUMN IF NOT EXISTS discovery_snapshot JSONB,
    ADD COLUMN IF NOT EXISTS discovery_fingerprint VARCHAR(64),
    ADD COLUMN IF NOT EXISTS profile_snapshot JSONB,
    ADD COLUMN IF NOT EXISTS profile_fingerprint VARCHAR(64),
    ADD COLUMN IF NOT EXISTS last_discovery_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS discovery_status VARCHAR(20) NOT NULL DEFAULT 'not_run',
    ADD COLUMN IF NOT EXISTS discovery_error TEXT;

ALTER TABLE agent_virtual_sources
    DROP CONSTRAINT IF EXISTS ck_vsource_discovery_status;

ALTER TABLE agent_virtual_sources
    ADD CONSTRAINT ck_vsource_discovery_status
    CHECK (discovery_status IN ('not_run', 'running', 'succeeded', 'failed'));

CREATE INDEX IF NOT EXISTS idx_vsource_discovery_status
    ON agent_virtual_sources (owner_username, discovery_status);

CREATE INDEX IF NOT EXISTS idx_vsource_discovery_fingerprint
    ON agent_virtual_sources (discovery_fingerprint)
    WHERE discovery_fingerprint IS NOT NULL;
