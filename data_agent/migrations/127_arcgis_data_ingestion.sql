-- Durable ArcGIS data-ingestion definitions, runs, and batch evidence.

-- Ingestion assets use immutable system identity rather than a display name.
-- This does not retroactively collapse legacy catalog rows that happen to share
-- a name but represent different storage backends.
CREATE UNIQUE INDEX IF NOT EXISTS uq_assets_external_identity_owner
    ON agent_data_assets(owner_username, external_system, external_id)
    WHERE external_system IS NOT NULL AND external_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS agent_ingestion_definitions (
    id BIGSERIAL PRIMARY KEY,
    source_id INTEGER NOT NULL REFERENCES agent_virtual_sources(id) ON DELETE CASCADE,
    owner_username VARCHAR(100) NOT NULL,
    tenant_id VARCHAR(64) NOT NULL DEFAULT 'local-dev',
    target_name VARCHAR(200) NOT NULL,
    target_mode VARCHAR(30) NOT NULL DEFAULT 'lakehouse_postgis',
    target_table VARCHAR(63),
    schedule_policy VARCHAR(30) NOT NULL DEFAULT 'on_demand',
    write_mode VARCHAR(30) NOT NULL DEFAULT 'full_snapshot',
    max_records INTEGER NOT NULL DEFAULT 1000000,
    page_size INTEGER NOT NULL DEFAULT 2000,
    config JSONB NOT NULL DEFAULT '{}'::jsonb,
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    next_run_at TIMESTAMPTZ,
    last_run_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_agent_ingestion_definition
        UNIQUE (source_id, target_name, owner_username),
    CONSTRAINT ck_agent_ingestion_target_mode
        CHECK (target_mode IN ('lakehouse', 'postgis', 'lakehouse_postgis')),
    CONSTRAINT ck_agent_ingestion_write_mode
        CHECK (write_mode = 'full_snapshot'),
    CONSTRAINT ck_agent_ingestion_schedule
        CHECK (schedule_policy IN (
            'on_demand', 'interval:5m', 'interval:30m', 'interval:1h'
        )),
    CONSTRAINT ck_agent_ingestion_max_records
        CHECK (max_records BETWEEN 1 AND 1000000),
    CONSTRAINT ck_agent_ingestion_page_size
        CHECK (page_size BETWEEN 1 AND 5000),
    CONSTRAINT ck_agent_ingestion_config
        CHECK (jsonb_typeof(config) = 'object'),
    CONSTRAINT ck_agent_ingestion_target_table CHECK (
        (target_mode = 'lakehouse' AND target_table IS NULL)
        OR
        (target_mode <> 'lakehouse' AND target_table ~ '^[a-z][a-z0-9_]{0,62}$')
    )
);

CREATE INDEX IF NOT EXISTS idx_agent_ingestion_definition_source
    ON agent_ingestion_definitions(source_id, owner_username);
CREATE INDEX IF NOT EXISTS idx_agent_ingestion_definition_due
    ON agent_ingestion_definitions(next_run_at)
    WHERE enabled = TRUE AND next_run_at IS NOT NULL;

CREATE TABLE IF NOT EXISTS agent_ingestion_runs (
    run_id UUID PRIMARY KEY,
    definition_id BIGINT NOT NULL
        REFERENCES agent_ingestion_definitions(id) ON DELETE CASCADE,
    source_id INTEGER NOT NULL REFERENCES agent_virtual_sources(id) ON DELETE RESTRICT,
    owner_username VARCHAR(100) NOT NULL,
    tenant_id VARCHAR(64) NOT NULL,
    idempotency_key VARCHAR(200) NOT NULL,
    trigger_type VARCHAR(20) NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'queued',
    worker_id VARCHAR(200),
    lease_expires_at TIMESTAMPTZ,
    cancellation_requested BOOLEAN NOT NULL DEFAULT FALSE,
    records_total BIGINT NOT NULL DEFAULT 0,
    records_read BIGINT NOT NULL DEFAULT 0,
    records_written BIGINT NOT NULL DEFAULT 0,
    batches_total INTEGER NOT NULL DEFAULT 0,
    batches_completed INTEGER NOT NULL DEFAULT 0,
    source_snapshot_sha256 CHAR(64),
    target_content_sha256 CHAR(64),
    target_uri TEXT,
    postgis_table VARCHAR(63),
    asset_id INTEGER REFERENCES agent_data_assets(id) ON DELETE SET NULL,
    quality_summary JSONB NOT NULL DEFAULT '{}'::jsonb,
    metadata_summary JSONB NOT NULL DEFAULT '{}'::jsonb,
    error_message TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    started_at TIMESTAMPTZ,
    heartbeat_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    CONSTRAINT uq_agent_ingestion_run_idempotency
        UNIQUE (definition_id, idempotency_key),
    CONSTRAINT ck_agent_ingestion_run_trigger
        CHECK (trigger_type IN ('manual', 'schedule', 'api', 'retry')),
    CONSTRAINT ck_agent_ingestion_run_status
        CHECK (status IN (
            'queued', 'running', 'committing', 'succeeded', 'failed',
            'cancelling', 'cancelled'
        )),
    CONSTRAINT ck_agent_ingestion_run_counts CHECK (
        records_total >= 0 AND records_read >= 0 AND records_written >= 0
        AND batches_total >= 0 AND batches_completed >= 0
    ),
    CONSTRAINT ck_agent_ingestion_run_quality
        CHECK (jsonb_typeof(quality_summary) = 'object'),
    CONSTRAINT ck_agent_ingestion_run_metadata
        CHECK (jsonb_typeof(metadata_summary) = 'object')
);

CREATE INDEX IF NOT EXISTS idx_agent_ingestion_run_definition
    ON agent_ingestion_runs(definition_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_agent_ingestion_run_owner
    ON agent_ingestion_runs(owner_username, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_agent_ingestion_run_claim
    ON agent_ingestion_runs(status, created_at)
    WHERE status IN ('queued', 'running', 'committing');

CREATE TABLE IF NOT EXISTS agent_ingestion_batches (
    run_id UUID NOT NULL REFERENCES agent_ingestion_runs(run_id) ON DELETE CASCADE,
    batch_index INTEGER NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'running',
    first_object_id TEXT,
    last_object_id TEXT,
    records_read INTEGER NOT NULL DEFAULT 0,
    records_written INTEGER NOT NULL DEFAULT 0,
    content_sha256 CHAR(64),
    lake_uri TEXT,
    error_message TEXT,
    started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at TIMESTAMPTZ,
    PRIMARY KEY (run_id, batch_index),
    CONSTRAINT ck_agent_ingestion_batch_status
        CHECK (status IN ('running', 'succeeded', 'failed')),
    CONSTRAINT ck_agent_ingestion_batch_counts
        CHECK (records_read >= 0 AND records_written >= 0)
);
