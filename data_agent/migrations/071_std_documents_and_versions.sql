-- =============================================================================
-- Migration 071: std_document + std_document_version
-- =============================================================================

CREATE TABLE IF NOT EXISTS std_document (
    id                  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    doc_code            TEXT NOT NULL,
    title               TEXT NOT NULL,
    source_type         TEXT NOT NULL
                            CHECK (source_type IN (
                                'national','industry','enterprise',
                                'international','draft')),
    source_url          TEXT,
    language            TEXT DEFAULT 'zh-CN',
    status              TEXT NOT NULL DEFAULT 'ingested'
                            CHECK (status IN (
                                'ingested','drafting','reviewing',
                                'published','superseded','archived')),
    current_version_id  UUID,
    owner_user_id       TEXT NOT NULL,
    tags                TEXT[] DEFAULT '{}',
    raw_file_path       TEXT,
    last_error_log      JSONB,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_by          TEXT,
    updated_by          TEXT,
    UNIQUE (doc_code, source_type)
);

CREATE INDEX IF NOT EXISTS idx_std_document_status ON std_document(status);
CREATE INDEX IF NOT EXISTS idx_std_document_owner ON std_document(owner_user_id);
CREATE INDEX IF NOT EXISTS idx_std_document_source_type ON std_document(source_type);

CREATE TABLE IF NOT EXISTS std_document_version (
    id                      UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    document_id             UUID NOT NULL REFERENCES std_document(id) ON DELETE CASCADE,
    version_label           TEXT NOT NULL,
    semver_major            INT NOT NULL,
    semver_minor            INT NOT NULL DEFAULT 0,
    semver_patch            INT NOT NULL DEFAULT 0,
    released_at             TIMESTAMPTZ,
    release_notes           TEXT,
    supersedes_version_id   UUID REFERENCES std_document_version(id),
    status                  TEXT NOT NULL DEFAULT 'draft'
                                CHECK (status IN ('draft','review','approved','released','retired')),
    snapshot_blob           JSONB,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_by              TEXT,
    updated_by              TEXT,
    UNIQUE (document_id, version_label)
);

CREATE INDEX IF NOT EXISTS idx_std_docver_doc ON std_document_version(document_id);
CREATE INDEX IF NOT EXISTS idx_std_docver_status ON std_document_version(status);

ALTER TABLE std_document
    ADD CONSTRAINT fk_std_document_current_version
    FOREIGN KEY (current_version_id) REFERENCES std_document_version(id)
    DEFERRABLE INITIALLY DEFERRED;
