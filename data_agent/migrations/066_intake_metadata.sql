-- Migration 066: NL2Semantic2SQL cold-start intake metadata tables
-- Supports the semi-automatic data onboarding pipeline:
--   discovered → drafted → reviewed → validated → active

CREATE TABLE IF NOT EXISTS agent_intake_jobs (
    id              SERIAL PRIMARY KEY,
    source_type     VARCHAR(32) NOT NULL DEFAULT 'postgis',
    source_ref      TEXT NOT NULL,
    status          VARCHAR(20) NOT NULL DEFAULT 'pending',
    tables_found    INTEGER DEFAULT 0,
    error           TEXT,
    started_at      TIMESTAMPTZ DEFAULT NOW(),
    finished_at     TIMESTAMPTZ,
    created_by      VARCHAR(128)
);

CREATE INDEX IF NOT EXISTS idx_intake_jobs_status ON agent_intake_jobs (status);

CREATE TABLE IF NOT EXISTS agent_dataset_profiles (
    id              SERIAL PRIMARY KEY,
    job_id          INTEGER REFERENCES agent_intake_jobs(id) ON DELETE CASCADE,
    table_name      VARCHAR(256) NOT NULL,
    schema_name     VARCHAR(128) NOT NULL DEFAULT 'public',
    row_count       BIGINT DEFAULT 0,
    geometry_type   VARCHAR(64),
    srid            INTEGER,
    columns_json    JSONB NOT NULL DEFAULT '[]',
    sample_values   JSONB DEFAULT '{}',
    indexes_json    JSONB DEFAULT '[]',
    risk_tags       JSONB DEFAULT '[]',
    primary_key_candidates JSONB DEFAULT '[]',
    table_comment   TEXT,
    status          VARCHAR(20) NOT NULL DEFAULT 'discovered',
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (job_id, table_name)
);

CREATE INDEX IF NOT EXISTS idx_dataset_profiles_status ON agent_dataset_profiles (status);
CREATE INDEX IF NOT EXISTS idx_dataset_profiles_table ON agent_dataset_profiles (table_name);

CREATE TABLE IF NOT EXISTS agent_semantic_drafts (
    id              SERIAL PRIMARY KEY,
    profile_id      INTEGER REFERENCES agent_dataset_profiles(id) ON DELETE CASCADE,
    table_name      VARCHAR(256) NOT NULL,
    version         INTEGER NOT NULL DEFAULT 1,
    display_name    TEXT,
    description     TEXT,
    aliases_json    JSONB DEFAULT '[]',
    columns_draft   JSONB DEFAULT '[]',
    join_candidates JSONB DEFAULT '[]',
    risk_flags      JSONB DEFAULT '[]',
    confidence      REAL DEFAULT 0.0,
    reviewed_by     VARCHAR(128),
    reviewed_at     TIMESTAMPTZ,
    review_notes    TEXT,
    status          VARCHAR(20) NOT NULL DEFAULT 'drafted',
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (profile_id, version)
);

CREATE INDEX IF NOT EXISTS idx_semantic_drafts_status ON agent_semantic_drafts (status);
CREATE INDEX IF NOT EXISTS idx_semantic_drafts_table ON agent_semantic_drafts (table_name);

CREATE TABLE IF NOT EXISTS agent_semantic_activations (
    id              SERIAL PRIMARY KEY,
    dataset_id      INTEGER REFERENCES agent_dataset_profiles(id) ON DELETE CASCADE,
    draft_id        INTEGER REFERENCES agent_semantic_drafts(id) ON DELETE SET NULL,
    draft_version   INTEGER NOT NULL,
    eval_score      REAL,
    eval_details    JSONB DEFAULT '{}',
    activated_by    VARCHAR(128),
    activated_at    TIMESTAMPTZ DEFAULT NOW(),
    rolled_back_at  TIMESTAMPTZ,
    is_current      BOOLEAN NOT NULL DEFAULT TRUE
);

CREATE INDEX IF NOT EXISTS idx_activations_dataset ON agent_semantic_activations (dataset_id);
CREATE INDEX IF NOT EXISTS idx_activations_current ON agent_semantic_activations (is_current) WHERE is_current = TRUE;
