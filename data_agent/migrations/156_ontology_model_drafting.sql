-- 156: Governed ontology model drafts and append-only change history.
-- Drafts are never part of the active immutable package. They point at an
-- exact published baseline and are materialized only when a reviewer accepts
-- the changes through the existing ontology publisher workflow.

CREATE TABLE IF NOT EXISTS gda_ontology.ontology_draft (
    draft_id UUID PRIMARY KEY,
    ontology_key TEXT NOT NULL,
    base_version_id UUID NOT NULL
        REFERENCES gda_ontology.ontology_version(ontology_version_id),
    base_content_sha256 CHAR(64) NOT NULL,
    title TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'draft',
    revision INTEGER NOT NULL DEFAULT 0,
    created_by TEXT NOT NULL,
    updated_by TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    submitted_at TIMESTAMPTZ,
    submitted_by TEXT,
    CONSTRAINT ck_gda_ontology_draft_status CHECK (
        status IN ('draft', 'in_review', 'rejected', 'abandoned')
    ),
    CONSTRAINT ck_gda_ontology_draft_revision CHECK (revision >= 0),
    CONSTRAINT ck_gda_ontology_draft_hash CHECK (
        base_content_sha256 ~ '^[0-9a-f]{64}$'
    ),
    CONSTRAINT ck_gda_ontology_draft_submission CHECK (
        (status IN ('in_review', 'rejected') AND submitted_at IS NOT NULL AND submitted_by IS NOT NULL)
        OR status IN ('draft', 'abandoned')
    )
);

CREATE INDEX IF NOT EXISTS idx_gda_ontology_draft_owner
    ON gda_ontology.ontology_draft (ontology_key, created_by, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_gda_ontology_draft_status
    ON gda_ontology.ontology_draft (ontology_key, status, updated_at DESC);

CREATE TABLE IF NOT EXISTS gda_ontology.ontology_draft_change (
    change_id UUID PRIMARY KEY,
    draft_id UUID NOT NULL
        REFERENCES gda_ontology.ontology_draft(draft_id) ON DELETE RESTRICT,
    sequence_no INTEGER NOT NULL,
    idempotency_key TEXT NOT NULL,
    operation TEXT NOT NULL,
    entity_type TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    actor TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_gda_ontology_draft_change_sequence UNIQUE (draft_id, sequence_no),
    CONSTRAINT uq_gda_ontology_draft_change_idempotency UNIQUE (draft_id, idempotency_key),
    CONSTRAINT ck_gda_ontology_draft_change_operation CHECK (
        operation IN ('upsert_concept', 'upsert_property', 'upsert_relation', 'deprecate_entity')
    ),
    CONSTRAINT ck_gda_ontology_draft_change_entity_type CHECK (
        entity_type IN ('concept', 'property', 'relation')
    ),
    CONSTRAINT ck_gda_ontology_draft_change_idempotency CHECK (
        octet_length(idempotency_key) BETWEEN 8 AND 128
    )
);

CREATE INDEX IF NOT EXISTS idx_gda_ontology_draft_change_draft
    ON gda_ontology.ontology_draft_change (draft_id, sequence_no);
CREATE INDEX IF NOT EXISTS idx_gda_ontology_draft_change_entity
    ON gda_ontology.ontology_draft_change (draft_id, entity_type, entity_id);

CREATE OR REPLACE FUNCTION gda_ontology.validate_ontology_draft_baseline()
RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
    base_key TEXT;
    base_status TEXT;
    base_hash CHAR(64);
BEGIN
    SELECT ontology_key, status, content_sha256
      INTO base_key, base_status, base_hash
      FROM gda_ontology.ontology_version
     WHERE ontology_version_id = NEW.base_version_id;
    IF base_key IS NULL OR base_status <> 'published' THEN
        RAISE EXCEPTION 'ontology draft baseline must be a published version'
            USING ERRCODE = '23514';
    END IF;
    IF base_key <> NEW.ontology_key OR base_hash <> NEW.base_content_sha256 THEN
        RAISE EXCEPTION 'ontology draft baseline key/hash mismatch'
            USING ERRCODE = '23514';
    END IF;
    IF TG_OP = 'UPDATE' AND (
        NEW.ontology_key <> OLD.ontology_key
        OR NEW.base_version_id <> OLD.base_version_id
        OR NEW.base_content_sha256 <> OLD.base_content_sha256
        OR NEW.created_by <> OLD.created_by
        OR NEW.created_at <> OLD.created_at
    ) THEN
        RAISE EXCEPTION 'ontology draft baseline identity is immutable'
            USING ERRCODE = '55000';
    END IF;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS validate_ontology_draft_baseline
    ON gda_ontology.ontology_draft;
CREATE TRIGGER validate_ontology_draft_baseline
BEFORE INSERT OR UPDATE ON gda_ontology.ontology_draft
FOR EACH ROW EXECUTE FUNCTION gda_ontology.validate_ontology_draft_baseline();

CREATE OR REPLACE FUNCTION gda_ontology.reject_ontology_draft_change_mutation()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'ontology draft change history is append-only'
        USING ERRCODE = '55000';
END;
$$;

DROP TRIGGER IF EXISTS reject_ontology_draft_change_mutation
    ON gda_ontology.ontology_draft_change;
CREATE TRIGGER reject_ontology_draft_change_mutation
BEFORE UPDATE OR DELETE ON gda_ontology.ontology_draft_change
FOR EACH ROW EXECUTE FUNCTION gda_ontology.reject_ontology_draft_change_mutation();

CREATE OR REPLACE FUNCTION gda_ontology.touch_ontology_draft()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS touch_ontology_draft ON gda_ontology.ontology_draft;
CREATE TRIGGER touch_ontology_draft
BEFORE UPDATE ON gda_ontology.ontology_draft
FOR EACH ROW EXECUTE FUNCTION gda_ontology.touch_ontology_draft();

DO $$
DECLARE
    runtime_role TEXT := current_setting('gda.runtime_role', true);
    publisher_role TEXT := current_setting('gda.ontology_publisher_role', true);
BEGIN
    IF runtime_role IS NULL OR runtime_role = '' THEN
        runtime_role := 'agent_user';
    END IF;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = runtime_role) THEN
        EXECUTE format('GRANT USAGE ON SCHEMA gda_ontology TO %I', runtime_role);
        EXECUTE format(
            'GRANT SELECT, INSERT, UPDATE ON gda_ontology.ontology_draft TO %I',
            runtime_role
        );
        EXECUTE format(
            'GRANT SELECT, INSERT ON gda_ontology.ontology_draft_change TO %I',
            runtime_role
        );
    END IF;
    IF publisher_role IS NULL OR publisher_role = '' THEN
        publisher_role := 'gda_ontology_publisher';
    END IF;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = publisher_role) THEN
        EXECUTE format(
            'GRANT SELECT, INSERT, UPDATE ON gda_ontology.ontology_draft TO %I',
            publisher_role
        );
        EXECUTE format(
            'GRANT SELECT, INSERT ON gda_ontology.ontology_draft_change TO %I',
            publisher_role
        );
    END IF;
END;
$$;
