-- 143: Require physical rejected-record quarantine evidence before a new
-- governed Silver/Gold SourceSync transaction may commit.

ALTER TABLE gda_control.artifact
    DROP CONSTRAINT IF EXISTS ck_gda_artifact_role;
ALTER TABLE gda_control.artifact
    ADD CONSTRAINT ck_gda_artifact_role CHECK (artifact_role IN (
        'input','output','checkpoint','log','evidence','quarantine',
        'execution_plan'
    ));

CREATE OR REPLACE FUNCTION gda_control.source_sync_quarantine_reason_counts_valid(
    p_reason_counts JSONB,
    p_records_rejected BIGINT
)
RETURNS BOOLEAN
LANGUAGE sql
IMMUTABLE
PARALLEL SAFE
AS $$
    SELECT p_records_rejected >= 0
       AND jsonb_typeof(p_reason_counts) = 'object'
       AND ((p_records_rejected = 0) = (p_reason_counts = '{}'::JSONB))
       AND NOT EXISTS (
           SELECT 1
           FROM jsonb_each(p_reason_counts) AS reason(key, value)
           WHERE key !~ '^[a-zA-Z0-9][a-zA-Z0-9._:-]{0,127}$'
              OR jsonb_typeof(value) <> 'number'
              OR value::TEXT !~ '^[1-9][0-9]*$'
       )
       AND p_records_rejected = COALESCE((
           SELECT sum((value::TEXT)::BIGINT)
           FROM jsonb_each(p_reason_counts)
       ), 0);
$$;

CREATE OR REPLACE FUNCTION
gda_control.source_sync_quarantine_evidence_sha256(
    p_tenant_id TEXT,
    p_sync_commit_id UUID,
    p_source_slice_sha256 TEXT,
    p_quarantine_resource_version_id UUID,
    p_quarantine_artifact_id UUID,
    p_records_rejected BIGINT,
    p_reason_counts JSONB
)
RETURNS TEXT
LANGUAGE sql
IMMUTABLE
PARALLEL SAFE
AS $$
    WITH canonical_reason_counts AS (
        SELECT CASE
            WHEN count(*) = 0 THEN '{}'
            ELSE '{' || string_agg(
                to_json(key)::TEXT || ':' || value::TEXT,
                ',' ORDER BY key
            ) || '}'
        END AS document
        FROM jsonb_each(p_reason_counts)
    )
    SELECT encode(
        public.digest(
            convert_to(
                '{"quarantine_artifact_id":'
                || to_json(p_quarantine_artifact_id::TEXT)::TEXT
                || ',"quarantine_resource_version_id":'
                || to_json(p_quarantine_resource_version_id::TEXT)::TEXT
                || ',"reason_counts":' || reason.document
                || ',"records_rejected":' || p_records_rejected::TEXT
                || ',"source_slice_sha256":'
                || to_json(p_source_slice_sha256)::TEXT
                || ',"sync_commit_id":'
                || to_json(p_sync_commit_id::TEXT)::TEXT
                || ',"tenant_id":' || to_json(p_tenant_id)::TEXT
                || '}',
                'UTF8'
            ),
            'sha256'
        ),
        'hex'
    )
    FROM canonical_reason_counts AS reason;
$$;

CREATE TABLE IF NOT EXISTS gda_control.source_sync_quarantine_evidence (
    tenant_id TEXT NOT NULL,
    sync_commit_id UUID PRIMARY KEY,
    source_slice_sha256 CHAR(64) NOT NULL,
    quarantine_resource_version_id UUID NOT NULL,
    quarantine_artifact_id UUID NOT NULL,
    records_rejected BIGINT NOT NULL,
    reason_counts JSONB NOT NULL,
    evidence_sha256 CHAR(64) NOT NULL,
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_gda_source_sync_quarantine_tenant_id
        UNIQUE (tenant_id, sync_commit_id),
    CONSTRAINT fk_gda_source_sync_quarantine_commit
        FOREIGN KEY (tenant_id, sync_commit_id)
        REFERENCES gda_control.source_sync_commit(tenant_id, sync_commit_id),
    CONSTRAINT fk_gda_source_sync_quarantine_resource_version
        FOREIGN KEY (tenant_id, quarantine_resource_version_id)
        REFERENCES gda_control.resource_version(tenant_id, resource_version_id),
    CONSTRAINT fk_gda_source_sync_quarantine_artifact
        FOREIGN KEY (tenant_id, quarantine_artifact_id)
        REFERENCES gda_control.artifact(tenant_id, artifact_id),
    CONSTRAINT ck_gda_source_sync_quarantine_source_sha
        CHECK (source_slice_sha256 ~ '^[0-9a-f]{64}$'),
    CONSTRAINT ck_gda_source_sync_quarantine_reasons CHECK (
        gda_control.source_sync_quarantine_reason_counts_valid(
            reason_counts, records_rejected
        )
    ),
    CONSTRAINT ck_gda_source_sync_quarantine_evidence_sha CHECK (
        evidence_sha256 = gda_control.source_sync_quarantine_evidence_sha256(
            tenant_id, sync_commit_id, source_slice_sha256,
            quarantine_resource_version_id, quarantine_artifact_id,
            records_rejected, reason_counts
        )
    )
);

CREATE INDEX IF NOT EXISTS idx_gda_source_sync_quarantine_artifact
    ON gda_control.source_sync_quarantine_evidence(
        tenant_id, quarantine_artifact_id
    );

CREATE OR REPLACE FUNCTION gda_control.guard_source_sync_quarantine_insert()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    IF COALESCE(
        current_setting('gda.source_sync_quarantine_evidence_allowed', true),
        ''
    ) <> '1' THEN
        RAISE EXCEPTION 'use gda_control.bind_source_sync_quarantine_evidence()'
            USING ERRCODE = '55000';
    END IF;
    IF gda_control.current_tenant() IS NULL
       OR NEW.tenant_id IS DISTINCT FROM gda_control.current_tenant() THEN
        RAISE EXCEPTION 'source sync quarantine evidence tenant is mismatched'
            USING ERRCODE = '42501';
    END IF;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_gda_source_sync_quarantine_insert_guard
    ON gda_control.source_sync_quarantine_evidence;
CREATE TRIGGER trg_gda_source_sync_quarantine_insert_guard
BEFORE INSERT ON gda_control.source_sync_quarantine_evidence
FOR EACH ROW EXECUTE FUNCTION gda_control.guard_source_sync_quarantine_insert();

DROP TRIGGER IF EXISTS trg_gda_source_sync_quarantine_immutable
    ON gda_control.source_sync_quarantine_evidence;
CREATE TRIGGER trg_gda_source_sync_quarantine_immutable
BEFORE UPDATE OR DELETE ON gda_control.source_sync_quarantine_evidence
FOR EACH ROW EXECUTE FUNCTION gda_control.reject_immutable_mutation();

ALTER TABLE gda_control.source_sync_quarantine_evidence
    ENABLE ROW LEVEL SECURITY;
ALTER TABLE gda_control.source_sync_quarantine_evidence
    FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation
    ON gda_control.source_sync_quarantine_evidence;
CREATE POLICY tenant_isolation
    ON gda_control.source_sync_quarantine_evidence
    USING (tenant_id = gda_control.current_tenant())
    WITH CHECK (tenant_id = gda_control.current_tenant());

CREATE OR REPLACE FUNCTION gda_control.bind_source_sync_quarantine_evidence(
    p_tenant_id TEXT,
    p_sync_commit_id UUID,
    p_quarantine_evidence JSONB
)
RETURNS VOID
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, gda_control
SET row_security = on
AS $$
DECLARE
    v_commit gda_control.source_sync_commit%ROWTYPE;
    v_definition gda_control.source_sync_definition%ROWTYPE;
    v_existing gda_control.source_sync_quarantine_evidence%ROWTYPE;
    v_quarantine_version gda_control.resource_version%ROWTYPE;
    v_artifact gda_control.artifact%ROWTYPE;
    v_evidence_tenant TEXT;
    v_evidence_commit_id UUID;
    v_source_slice_sha256 TEXT;
    v_quarantine_resource_version_id UUID;
    v_quarantine_artifact_id UUID;
    v_records_rejected BIGINT;
    v_reason_counts JSONB;
    v_evidence_sha256 TEXT;
BEGIN
    IF gda_control.current_tenant() IS NULL
       OR p_tenant_id IS DISTINCT FROM gda_control.current_tenant() THEN
        RAISE EXCEPTION 'source sync tenant context is missing or mismatched'
            USING ERRCODE = '42501';
    END IF;
    IF p_quarantine_evidence IS NULL
       OR jsonb_typeof(p_quarantine_evidence) <> 'object'
       OR NOT p_quarantine_evidence ?& ARRAY[
           'tenant_id', 'sync_commit_id', 'source_slice_sha256',
           'quarantine_resource_version_id', 'quarantine_artifact_id',
           'records_rejected', 'reason_counts', 'evidence_sha256'
       ]
       OR (SELECT count(*) FROM jsonb_object_keys(p_quarantine_evidence)) <> 8
       OR jsonb_typeof(p_quarantine_evidence->'reason_counts') <> 'object'
       OR jsonb_typeof(p_quarantine_evidence->'records_rejected') <> 'number' THEN
        RAISE EXCEPTION 'source sync quarantine evidence is incomplete'
            USING ERRCODE = '22023';
    END IF;

    BEGIN
        v_evidence_tenant := p_quarantine_evidence->>'tenant_id';
        v_evidence_commit_id :=
            (p_quarantine_evidence->>'sync_commit_id')::UUID;
        v_source_slice_sha256 :=
            p_quarantine_evidence->>'source_slice_sha256';
        v_quarantine_resource_version_id :=
            (p_quarantine_evidence->>'quarantine_resource_version_id')::UUID;
        v_quarantine_artifact_id :=
            (p_quarantine_evidence->>'quarantine_artifact_id')::UUID;
        v_records_rejected :=
            (p_quarantine_evidence->>'records_rejected')::BIGINT;
        v_reason_counts := p_quarantine_evidence->'reason_counts';
        v_evidence_sha256 := p_quarantine_evidence->>'evidence_sha256';
    EXCEPTION WHEN invalid_text_representation OR numeric_value_out_of_range THEN
        RAISE EXCEPTION 'source sync quarantine evidence values are invalid'
            USING ERRCODE = '22023';
    END;

    IF v_evidence_tenant IS DISTINCT FROM p_tenant_id
       OR v_evidence_commit_id IS DISTINCT FROM p_sync_commit_id
       OR v_source_slice_sha256 !~ '^[0-9a-f]{64}$'
       OR v_evidence_sha256 !~ '^[0-9a-f]{64}$'
       OR NOT gda_control.source_sync_quarantine_reason_counts_valid(
           v_reason_counts, v_records_rejected
       ) THEN
        RAISE EXCEPTION 'source sync quarantine evidence identity is invalid'
            USING ERRCODE = '22023';
    END IF;

    SELECT * INTO v_commit
    FROM gda_control.source_sync_commit AS commit
    WHERE commit.tenant_id = p_tenant_id
      AND commit.sync_commit_id = p_sync_commit_id;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'source sync commit not found'
            USING ERRCODE = 'P0002';
    END IF;
    SELECT * INTO v_definition
    FROM gda_control.source_sync_definition AS definition
    WHERE definition.tenant_id = p_tenant_id
      AND definition.sync_definition_version_id =
          v_commit.sync_definition_version_id;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'source sync definition not found'
            USING ERRCODE = 'P0002';
    END IF;
    IF v_definition.governance_contract->>'target_layer'
       NOT IN ('silver', 'gold') THEN
        RAISE EXCEPTION 'only Silver and Gold commits bind quarantine evidence'
            USING ERRCODE = '23514';
    END IF;
    IF v_commit.source_slice_sha256 IS DISTINCT FROM v_source_slice_sha256 THEN
        RAISE EXCEPTION 'quarantine evidence source slice does not match commit'
            USING ERRCODE = '23514';
    END IF;

    SELECT * INTO v_existing
    FROM gda_control.source_sync_quarantine_evidence AS evidence
    WHERE evidence.tenant_id = p_tenant_id
      AND evidence.sync_commit_id = p_sync_commit_id;
    IF FOUND THEN
        IF v_existing.source_slice_sha256 IS DISTINCT FROM v_source_slice_sha256
           OR v_existing.quarantine_resource_version_id
                IS DISTINCT FROM v_quarantine_resource_version_id
           OR v_existing.quarantine_artifact_id
                IS DISTINCT FROM v_quarantine_artifact_id
           OR v_existing.records_rejected IS DISTINCT FROM v_records_rejected
           OR v_existing.reason_counts IS DISTINCT FROM v_reason_counts
           OR v_existing.evidence_sha256 IS DISTINCT FROM v_evidence_sha256 THEN
            RAISE EXCEPTION 'source sync commit has different quarantine evidence'
                USING ERRCODE = '40001';
        END IF;
        RETURN;
    END IF;

    SELECT * INTO v_quarantine_version
    FROM gda_control.resource_version AS version
    WHERE version.tenant_id = p_tenant_id
      AND version.resource_version_id = v_quarantine_resource_version_id;
    IF NOT FOUND
       OR v_quarantine_version.resource_urn IS DISTINCT FROM
          v_definition.governance_contract->>'quarantine_resource_urn' THEN
        RAISE EXCEPTION 'quarantine ResourceVersion does not match sync contract'
            USING ERRCODE = '23514';
    END IF;

    SELECT * INTO v_artifact
    FROM gda_control.artifact AS artifact
    WHERE artifact.tenant_id = p_tenant_id
      AND artifact.artifact_id = v_quarantine_artifact_id;
    IF NOT FOUND
       OR v_artifact.artifact_role <> 'quarantine'
       OR v_artifact.run_id IS DISTINCT FROM v_commit.run_id
       OR v_artifact.resource_version_id IS DISTINCT FROM
          v_quarantine_resource_version_id
       OR v_quarantine_version.content_sha256 IS DISTINCT FROM
          v_artifact.content_sha256
       OR v_artifact.created_by IS DISTINCT FROM v_commit.committed_by
       OR v_artifact.created_at > v_commit.committed_at
       OR (v_records_rejected > 0 AND v_artifact.size_bytes = 0)
       OR v_artifact.manifest->>'schema' IS DISTINCT FROM
          'gda.source_sync_quarantine.v1'
       OR v_artifact.manifest->>'source_slice_sha256' IS DISTINCT FROM
          v_source_slice_sha256
       OR v_artifact.manifest->>'sync_definition_version_id' IS DISTINCT FROM
          v_commit.sync_definition_version_id::TEXT
       OR v_artifact.manifest->'records_rejected'
          IS DISTINCT FROM to_jsonb(v_records_rejected)
       OR v_artifact.manifest->'reason_counts'
          IS DISTINCT FROM v_reason_counts
       OR v_artifact.manifest->>'target_content_sha256' IS DISTINCT FROM
          v_commit.target_content_sha256
       OR v_artifact.manifest->>'rejected_content_sha256' IS DISTINCT FROM
          v_artifact.content_sha256 THEN
        RAISE EXCEPTION 'quarantine Artifact does not match provider rejection receipt'
            USING ERRCODE = '23514';
    END IF;

    PERFORM set_config(
        'gda.source_sync_quarantine_evidence_allowed', '1', true
    );
    INSERT INTO gda_control.source_sync_quarantine_evidence (
        tenant_id, sync_commit_id, source_slice_sha256,
        quarantine_resource_version_id, quarantine_artifact_id,
        records_rejected, reason_counts, evidence_sha256, recorded_at
    ) VALUES (
        p_tenant_id, p_sync_commit_id, v_source_slice_sha256,
        v_quarantine_resource_version_id, v_quarantine_artifact_id,
        v_records_rejected, v_reason_counts, v_evidence_sha256,
        v_commit.committed_at
    );
    PERFORM set_config(
        'gda.source_sync_quarantine_evidence_allowed', '0', true
    );
EXCEPTION WHEN OTHERS THEN
    PERFORM set_config(
        'gda.source_sync_quarantine_evidence_allowed', '0', true
    );
    RAISE;
END;
$$;

CREATE OR REPLACE FUNCTION
gda_control.require_source_sync_quarantine_evidence()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
DECLARE
    v_target_layer TEXT;
BEGIN
    SELECT definition.governance_contract->>'target_layer'
    INTO v_target_layer
    FROM gda_control.source_sync_definition AS definition
    WHERE definition.tenant_id = NEW.tenant_id
      AND definition.sync_definition_version_id =
          NEW.sync_definition_version_id;
    IF v_target_layer IN ('silver', 'gold')
       AND NOT EXISTS (
           SELECT 1
           FROM gda_control.source_sync_quarantine_evidence AS evidence
           WHERE evidence.tenant_id = NEW.tenant_id
             AND evidence.sync_commit_id = NEW.sync_commit_id
       ) THEN
        RAISE EXCEPTION
            'Silver and Gold source sync commits require quarantine evidence'
            USING ERRCODE = '23514';
    END IF;
    RETURN NULL;
END;
$$;

DROP TRIGGER IF EXISTS trg_gda_source_sync_commit_requires_quarantine
    ON gda_control.source_sync_commit;
CREATE CONSTRAINT TRIGGER trg_gda_source_sync_commit_requires_quarantine
AFTER INSERT ON gda_control.source_sync_commit
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW
EXECUTE FUNCTION gda_control.require_source_sync_quarantine_evidence();

REVOKE ALL ON TABLE gda_control.source_sync_quarantine_evidence
    FROM PUBLIC, gda_control_gateway;
GRANT SELECT ON TABLE gda_control.source_sync_quarantine_evidence
    TO gda_control_gateway;

REVOKE ALL ON FUNCTION
    gda_control.source_sync_quarantine_reason_counts_valid(JSONB, BIGINT)
    FROM PUBLIC, gda_control_gateway;
REVOKE ALL ON FUNCTION
    gda_control.source_sync_quarantine_evidence_sha256(
        TEXT, UUID, TEXT, UUID, UUID, BIGINT, JSONB
    ) FROM PUBLIC, gda_control_gateway;
REVOKE ALL ON FUNCTION gda_control.guard_source_sync_quarantine_insert()
    FROM PUBLIC, gda_control_gateway;
REVOKE ALL ON FUNCTION gda_control.require_source_sync_quarantine_evidence()
    FROM PUBLIC, gda_control_gateway;
REVOKE ALL ON FUNCTION gda_control.bind_source_sync_quarantine_evidence(
    TEXT, UUID, JSONB
) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION gda_control.bind_source_sync_quarantine_evidence(
    TEXT, UUID, JSONB
) TO gda_control_gateway;
