-- 142: Atomically bind governed Silver/Gold source-sync commits to quality,
-- approval, lineage, and metadata projection evidence.

CREATE EXTENSION IF NOT EXISTS pgcrypto WITH SCHEMA public;

CREATE OR REPLACE FUNCTION gda_control.source_sync_uuid_array_is_canonical(
    p_values UUID[]
)
RETURNS BOOLEAN
LANGUAGE sql
IMMUTABLE
PARALLEL SAFE
AS $$
    SELECT p_values IS NOT NULL
       AND cardinality(p_values) > 0
       AND cardinality(p_values) = (
           SELECT count(DISTINCT value) FROM unnest(p_values) AS value
       )
       AND p_values = ARRAY(
           SELECT value FROM unnest(p_values) AS value ORDER BY value::TEXT
       );
$$;

CREATE OR REPLACE FUNCTION
gda_control.source_sync_commit_governance_evidence_sha256(
    p_tenant_id TEXT,
    p_sync_commit_id UUID,
    p_target_resource_version_id UUID,
    p_output_artifact_id UUID,
    p_quality_result_ids UUID[],
    p_lineage_event_id UUID,
    p_metadata_change_id UUID,
    p_approval_case_ref TEXT
)
RETURNS TEXT
LANGUAGE sql
IMMUTABLE
PARALLEL SAFE
AS $$
    SELECT encode(
        public.digest(
            convert_to(
                '{"approval_case_ref":'
                || COALESCE(to_json(p_approval_case_ref)::TEXT, 'null')
                || ',"lineage_event_id":'
                || to_json(p_lineage_event_id::TEXT)::TEXT
                || ',"metadata_change_id":'
                || to_json(p_metadata_change_id::TEXT)::TEXT
                || ',"output_artifact_id":'
                || to_json(p_output_artifact_id::TEXT)::TEXT
                || ',"quality_result_ids":'
                || to_json(p_quality_result_ids)::TEXT
                || ',"sync_commit_id":'
                || to_json(p_sync_commit_id::TEXT)::TEXT
                || ',"target_resource_version_id":'
                || to_json(p_target_resource_version_id::TEXT)::TEXT
                || ',"tenant_id":'
                || to_json(p_tenant_id)::TEXT
                || '}',
                'UTF8'
            ),
            'sha256'
        ),
        'hex'
    );
$$;

CREATE TABLE IF NOT EXISTS gda_control.source_sync_commit_governance_evidence (
    tenant_id TEXT NOT NULL,
    sync_commit_id UUID PRIMARY KEY,
    target_resource_version_id UUID NOT NULL,
    output_artifact_id UUID NOT NULL,
    quality_result_ids UUID[] NOT NULL,
    lineage_event_id UUID NOT NULL,
    metadata_change_id UUID NOT NULL,
    approval_case_ref TEXT,
    evidence_sha256 CHAR(64) NOT NULL,
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_gda_source_sync_commit_governance_tenant_id
        UNIQUE (tenant_id, sync_commit_id),
    CONSTRAINT fk_gda_source_sync_commit_governance_commit
        FOREIGN KEY (tenant_id, sync_commit_id)
        REFERENCES gda_control.source_sync_commit(tenant_id, sync_commit_id),
    CONSTRAINT fk_gda_source_sync_commit_governance_target_version
        FOREIGN KEY (tenant_id, target_resource_version_id)
        REFERENCES gda_control.resource_version(tenant_id, resource_version_id),
    CONSTRAINT fk_gda_source_sync_commit_governance_output
        FOREIGN KEY (tenant_id, output_artifact_id)
        REFERENCES gda_control.artifact(tenant_id, artifact_id),
    CONSTRAINT fk_gda_source_sync_commit_governance_lineage
        FOREIGN KEY (tenant_id, lineage_event_id)
        REFERENCES gda_control.lineage_event(tenant_id, lineage_event_id),
    CONSTRAINT fk_gda_source_sync_commit_governance_metadata
        FOREIGN KEY (tenant_id, metadata_change_id)
        REFERENCES gda_control.metadata_change_outbox(tenant_id, change_id),
    CONSTRAINT fk_gda_source_sync_commit_governance_approval
        FOREIGN KEY (tenant_id, approval_case_ref)
        REFERENCES gda_control.approval_case(tenant_id, approval_case_ref),
    CONSTRAINT ck_gda_source_sync_commit_governance_quality_ids
        CHECK (gda_control.source_sync_uuid_array_is_canonical(quality_result_ids)),
    CONSTRAINT ck_gda_source_sync_commit_governance_approval_tenant CHECK (
        approval_case_ref IS NULL OR (
            approval_case_ref ~ '^gda://[a-z0-9][a-z0-9._-]{0,63}/approval_case/[a-z0-9][a-z0-9._-]{0,127}$'
            AND split_part(approval_case_ref, '/', 3) = tenant_id
        )
    ),
    CONSTRAINT ck_gda_source_sync_commit_governance_sha CHECK (
        evidence_sha256 =
            gda_control.source_sync_commit_governance_evidence_sha256(
                tenant_id, sync_commit_id, target_resource_version_id,
                output_artifact_id, quality_result_ids, lineage_event_id,
                metadata_change_id, approval_case_ref
            )
    )
);

CREATE INDEX IF NOT EXISTS idx_gda_source_sync_commit_governance_target
    ON gda_control.source_sync_commit_governance_evidence(
        tenant_id, target_resource_version_id
    );
CREATE INDEX IF NOT EXISTS idx_gda_source_sync_commit_governance_lineage
    ON gda_control.source_sync_commit_governance_evidence(
        tenant_id, lineage_event_id
    );

CREATE OR REPLACE FUNCTION gda_control.guard_source_sync_governance_evidence_insert()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    IF COALESCE(
        current_setting('gda.source_sync_governance_evidence_allowed', true),
        ''
    ) <> '1' THEN
        RAISE EXCEPTION 'use gda_control.commit_source_sync()'
            USING ERRCODE = '55000';
    END IF;
    IF gda_control.current_tenant() IS NULL
       OR NEW.tenant_id IS DISTINCT FROM gda_control.current_tenant() THEN
        RAISE EXCEPTION 'source sync governance evidence tenant is mismatched'
            USING ERRCODE = '42501';
    END IF;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_gda_source_sync_governance_evidence_insert_guard
    ON gda_control.source_sync_commit_governance_evidence;
CREATE TRIGGER trg_gda_source_sync_governance_evidence_insert_guard
BEFORE INSERT ON gda_control.source_sync_commit_governance_evidence
FOR EACH ROW
EXECUTE FUNCTION gda_control.guard_source_sync_governance_evidence_insert();

DROP TRIGGER IF EXISTS trg_gda_source_sync_governance_evidence_immutable
    ON gda_control.source_sync_commit_governance_evidence;
CREATE TRIGGER trg_gda_source_sync_governance_evidence_immutable
BEFORE UPDATE OR DELETE
ON gda_control.source_sync_commit_governance_evidence
FOR EACH ROW EXECUTE FUNCTION gda_control.reject_immutable_mutation();

ALTER TABLE gda_control.source_sync_commit_governance_evidence
    ENABLE ROW LEVEL SECURITY;
ALTER TABLE gda_control.source_sync_commit_governance_evidence
    FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation
    ON gda_control.source_sync_commit_governance_evidence;
CREATE POLICY tenant_isolation
    ON gda_control.source_sync_commit_governance_evidence
    USING (tenant_id = gda_control.current_tenant())
    WITH CHECK (tenant_id = gda_control.current_tenant());

REVOKE ALL ON TABLE gda_control.source_sync_commit_governance_evidence
    FROM PUBLIC, gda_control_gateway;
GRANT SELECT ON TABLE gda_control.source_sync_commit_governance_evidence
    TO gda_control_gateway;
REVOKE ALL ON FUNCTION
    gda_control.guard_source_sync_governance_evidence_insert()
    FROM PUBLIC, gda_control_gateway;
REVOKE ALL ON FUNCTION
    gda_control.source_sync_commit_governance_evidence_sha256(
        TEXT, UUID, UUID, UUID, UUID[], UUID, UUID, TEXT
    ) FROM PUBLIC, gda_control_gateway;

-- Preserve migration 104 as a private CAS primitive. Only the governed wrapper
-- below remains executable by the gateway.
DO $migration$
BEGIN
    IF to_regprocedure(
        'gda_control.commit_source_sync_v104(text,uuid,uuid,uuid,integer,integer,jsonb,text,jsonb,text,text,jsonb,text,bigint,bigint,bigint,bigint,bigint,text,timestamptz,text)'
    ) IS NULL THEN
        IF to_regprocedure(
            'gda_control.commit_source_sync(text,uuid,uuid,uuid,integer,integer,jsonb,text,jsonb,text,text,jsonb,text,bigint,bigint,bigint,bigint,bigint,text,timestamptz,text)'
        ) IS NULL THEN
            RAISE EXCEPTION 'migration 104 commit_source_sync() is required';
        END IF;
        ALTER FUNCTION gda_control.commit_source_sync(
            TEXT, UUID, UUID, UUID, INTEGER, INTEGER, JSONB, TEXT, JSONB, TEXT,
            TEXT, JSONB, TEXT, BIGINT, BIGINT, BIGINT, BIGINT, BIGINT, TEXT,
            TIMESTAMPTZ, TEXT
        ) RENAME TO commit_source_sync_v104;
    END IF;
END
$migration$;

REVOKE ALL ON FUNCTION gda_control.commit_source_sync_v104(
    TEXT, UUID, UUID, UUID, INTEGER, INTEGER, JSONB, TEXT, JSONB, TEXT,
    TEXT, JSONB, TEXT, BIGINT, BIGINT, BIGINT, BIGINT, BIGINT, TEXT,
    TIMESTAMPTZ, TEXT
) FROM PUBLIC, gda_control_gateway;

CREATE OR REPLACE FUNCTION gda_control.commit_source_sync(
    p_tenant_id TEXT,
    p_sync_commit_id UUID,
    p_sync_definition_version_id UUID,
    p_run_id UUID,
    p_from_state_version INTEGER,
    p_to_state_version INTEGER,
    p_previous_cursor JSONB,
    p_previous_cursor_sha256 TEXT,
    p_next_cursor JSONB,
    p_next_cursor_sha256 TEXT,
    p_source_slice_sha256 TEXT,
    p_target_commit_ref JSONB,
    p_target_content_sha256 TEXT,
    p_records_read BIGINT,
    p_records_inserted BIGINT,
    p_records_updated BIGINT,
    p_records_deleted BIGINT,
    p_records_output BIGINT,
    p_committed_by TEXT,
    p_committed_at TIMESTAMPTZ,
    p_commit_sha256 TEXT,
    p_governance_evidence JSONB DEFAULT NULL
)
RETURNS TABLE(result_sync_commit_id UUID, result_created BOOLEAN)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, gda_control
SET row_security = on
AS $$
DECLARE
    v_definition gda_control.source_sync_definition%ROWTYPE;
    v_existing gda_control.source_sync_commit%ROWTYPE;
    v_stored_evidence
        gda_control.source_sync_commit_governance_evidence%ROWTYPE;
    v_target_version gda_control.resource_version%ROWTYPE;
    v_output gda_control.artifact%ROWTYPE;
    v_lineage gda_control.lineage_event%ROWTYPE;
    v_metadata gda_control.metadata_change_outbox%ROWTYPE;
    v_approval gda_control.approval_case%ROWTYPE;
    v_target_layer TEXT;
    v_promotion_mode TEXT;
    v_evidence_tenant TEXT;
    v_evidence_commit_id UUID;
    v_target_resource_version_id UUID;
    v_output_artifact_id UUID;
    v_quality_result_ids UUID[];
    v_lineage_event_id UUID;
    v_metadata_change_id UUID;
    v_approval_case_ref TEXT;
    v_evidence_sha256 TEXT;
    v_expected_quality_refs TEXT[];
    v_actual_quality_refs TEXT[];
    v_quality_count INTEGER;
    v_result_sync_commit_id UUID;
    v_result_created BOOLEAN;
BEGIN
    IF gda_control.current_tenant() IS NULL
       OR p_tenant_id IS DISTINCT FROM gda_control.current_tenant() THEN
        RAISE EXCEPTION 'source sync tenant context is missing or mismatched'
            USING ERRCODE = '42501';
    END IF;

    SELECT * INTO v_definition
    FROM gda_control.source_sync_definition AS definition
    WHERE definition.tenant_id = p_tenant_id
      AND definition.sync_definition_version_id = p_sync_definition_version_id;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'source sync definition not found'
            USING ERRCODE = 'P0002';
    END IF;

    v_target_layer := v_definition.governance_contract->>'target_layer';
    v_promotion_mode := v_definition.governance_contract->>'promotion_mode';

    IF v_definition.governance_contract IS NULL
       OR v_target_layer IN ('landing', 'ods') THEN
        IF p_governance_evidence IS NOT NULL THEN
            RAISE EXCEPTION 'Landing and ODS commits must not bind promotion evidence'
                USING ERRCODE = '22023';
        END IF;
        RETURN QUERY
        SELECT * FROM gda_control.commit_source_sync_v104(
            p_tenant_id, p_sync_commit_id, p_sync_definition_version_id,
            p_run_id, p_from_state_version, p_to_state_version,
            p_previous_cursor, p_previous_cursor_sha256,
            p_next_cursor, p_next_cursor_sha256, p_source_slice_sha256,
            p_target_commit_ref, p_target_content_sha256, p_records_read,
            p_records_inserted, p_records_updated, p_records_deleted,
            p_records_output, p_committed_by, p_committed_at, p_commit_sha256
        );
        RETURN;
    END IF;

    IF v_target_layer NOT IN ('silver', 'gold') THEN
        RAISE EXCEPTION 'source sync target layer is unsupported'
            USING ERRCODE = '22023';
    END IF;

    SELECT * INTO v_existing
    FROM gda_control.source_sync_commit AS commit
    WHERE commit.tenant_id = p_tenant_id
      AND commit.sync_commit_id = p_sync_commit_id;
    IF FOUND THEN
        IF p_governance_evidence IS NULL THEN
            RAISE EXCEPTION 'governed commit replay requires its original evidence'
                USING ERRCODE = '23514';
        END IF;
    ELSE
        SELECT * INTO v_existing
        FROM gda_control.source_sync_commit AS commit
        WHERE commit.tenant_id = p_tenant_id
          AND commit.sync_definition_version_id = p_sync_definition_version_id
          AND commit.previous_cursor_sha256 = p_previous_cursor_sha256
          AND commit.next_cursor_sha256 = p_next_cursor_sha256
          AND commit.source_slice_sha256 = p_source_slice_sha256;
        IF FOUND THEN
            SELECT * INTO v_stored_evidence
            FROM gda_control.source_sync_commit_governance_evidence AS evidence
            WHERE evidence.tenant_id = p_tenant_id
              AND evidence.sync_commit_id = v_existing.sync_commit_id;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'replayed source slice lacks governance evidence'
                    USING ERRCODE = '23514';
            END IF;
            IF p_governance_evidence IS NOT NULL THEN
                RAISE EXCEPTION 'cross-run replay must reuse original governance evidence'
                    USING ERRCODE = '23514';
            END IF;
            RETURN QUERY
            SELECT * FROM gda_control.commit_source_sync_v104(
                p_tenant_id, p_sync_commit_id, p_sync_definition_version_id,
                p_run_id, p_from_state_version, p_to_state_version,
                p_previous_cursor, p_previous_cursor_sha256,
                p_next_cursor, p_next_cursor_sha256, p_source_slice_sha256,
                p_target_commit_ref, p_target_content_sha256, p_records_read,
                p_records_inserted, p_records_updated, p_records_deleted,
                p_records_output, p_committed_by, p_committed_at, p_commit_sha256
            );
            RETURN;
        END IF;
    END IF;

    IF p_governance_evidence IS NULL
       OR jsonb_typeof(p_governance_evidence) <> 'object'
       OR NOT p_governance_evidence ?& ARRAY[
           'tenant_id', 'sync_commit_id', 'target_resource_version_id',
           'output_artifact_id', 'quality_result_ids', 'lineage_event_id',
           'metadata_change_id', 'approval_case_ref', 'evidence_sha256'
       ]
       OR (SELECT count(*) FROM jsonb_object_keys(p_governance_evidence)) <> 9
       OR jsonb_typeof(p_governance_evidence->'quality_result_ids') <> 'array' THEN
        RAISE EXCEPTION 'governed Silver and Gold commits require complete evidence'
            USING ERRCODE = '22023';
    END IF;

    BEGIN
        v_evidence_tenant := p_governance_evidence->>'tenant_id';
        v_evidence_commit_id := (p_governance_evidence->>'sync_commit_id')::UUID;
        v_target_resource_version_id :=
            (p_governance_evidence->>'target_resource_version_id')::UUID;
        v_output_artifact_id :=
            (p_governance_evidence->>'output_artifact_id')::UUID;
        SELECT COALESCE(array_agg(value::UUID ORDER BY value), ARRAY[]::UUID[])
        INTO v_quality_result_ids
        FROM jsonb_array_elements_text(
            p_governance_evidence->'quality_result_ids'
        ) AS value;
        v_lineage_event_id :=
            (p_governance_evidence->>'lineage_event_id')::UUID;
        v_metadata_change_id :=
            (p_governance_evidence->>'metadata_change_id')::UUID;
        v_approval_case_ref := NULLIF(
            p_governance_evidence->>'approval_case_ref', ''
        );
        v_evidence_sha256 := p_governance_evidence->>'evidence_sha256';
    EXCEPTION WHEN invalid_text_representation THEN
        RAISE EXCEPTION 'source sync governance evidence identifiers are invalid'
            USING ERRCODE = '22023';
    END;

    IF v_evidence_tenant IS DISTINCT FROM p_tenant_id
       OR v_evidence_commit_id IS DISTINCT FROM p_sync_commit_id
       OR NOT gda_control.source_sync_uuid_array_is_canonical(
           v_quality_result_ids
       )
       OR p_governance_evidence->'quality_result_ids'
            IS DISTINCT FROM to_jsonb(v_quality_result_ids)
       OR v_evidence_sha256 !~ '^[0-9a-f]{64}$' THEN
        RAISE EXCEPTION 'source sync governance evidence identity is invalid'
            USING ERRCODE = '22023';
    END IF;

    IF v_existing.sync_commit_id IS NOT NULL THEN
        SELECT * INTO v_stored_evidence
        FROM gda_control.source_sync_commit_governance_evidence AS evidence
        WHERE evidence.tenant_id = p_tenant_id
          AND evidence.sync_commit_id = p_sync_commit_id;
        IF NOT FOUND
           OR v_stored_evidence.target_resource_version_id
                IS DISTINCT FROM v_target_resource_version_id
           OR v_stored_evidence.output_artifact_id
                IS DISTINCT FROM v_output_artifact_id
           OR v_stored_evidence.quality_result_ids
                IS DISTINCT FROM v_quality_result_ids
           OR v_stored_evidence.lineage_event_id
                IS DISTINCT FROM v_lineage_event_id
           OR v_stored_evidence.metadata_change_id
                IS DISTINCT FROM v_metadata_change_id
           OR v_stored_evidence.approval_case_ref
                IS DISTINCT FROM v_approval_case_ref
           OR v_stored_evidence.evidence_sha256
                IS DISTINCT FROM v_evidence_sha256 THEN
            RAISE EXCEPTION 'source sync commit identity has different governance evidence'
                USING ERRCODE = '40001';
        END IF;
        RETURN QUERY
        SELECT * FROM gda_control.commit_source_sync_v104(
            p_tenant_id, p_sync_commit_id, p_sync_definition_version_id,
            p_run_id, p_from_state_version, p_to_state_version,
            p_previous_cursor, p_previous_cursor_sha256,
            p_next_cursor, p_next_cursor_sha256, p_source_slice_sha256,
            p_target_commit_ref, p_target_content_sha256, p_records_read,
            p_records_inserted, p_records_updated, p_records_deleted,
            p_records_output, p_committed_by, p_committed_at, p_commit_sha256
        );
        RETURN;
    END IF;

    PERFORM 1
    FROM gda_control.resource AS quarantine
    WHERE quarantine.tenant_id = p_tenant_id
      AND quarantine.resource_urn =
          v_definition.governance_contract->>'quarantine_resource_urn';
    IF NOT FOUND THEN
        RAISE EXCEPTION 'governed source sync requires its quarantine Resource'
            USING ERRCODE = '23514';
    END IF;

    SELECT * INTO v_target_version
    FROM gda_control.resource_version AS version
    WHERE version.tenant_id = p_tenant_id
      AND version.resource_version_id = v_target_resource_version_id;
    IF NOT FOUND
       OR v_target_version.resource_urn IS DISTINCT FROM
            v_definition.target_resource_urn
       OR v_target_version.content_sha256 IS DISTINCT FROM
            p_target_content_sha256 THEN
        RAISE EXCEPTION 'target ResourceVersion does not match source sync output'
            USING ERRCODE = '23514';
    END IF;

    SELECT * INTO v_output
    FROM gda_control.artifact AS artifact
    WHERE artifact.tenant_id = p_tenant_id
      AND artifact.artifact_id = v_output_artifact_id;
    IF NOT FOUND
       OR v_output.artifact_role <> 'output'
       OR v_output.run_id IS DISTINCT FROM p_run_id
       OR v_output.resource_version_id IS DISTINCT FROM
            v_target_resource_version_id
       OR v_output.content_sha256 IS DISTINCT FROM p_target_content_sha256 THEN
        RAISE EXCEPTION 'output Artifact does not match source sync target'
            USING ERRCODE = '23514';
    END IF;

    SELECT COALESCE(array_agg(value ORDER BY value), ARRAY[]::TEXT[])
    INTO v_expected_quality_refs
    FROM jsonb_array_elements_text(
        v_definition.governance_contract->'quality_rule_version_refs'
    ) AS value;
    SELECT count(*),
           COALESCE(array_agg(result.rule_version_ref ORDER BY result.rule_version_ref),
                    ARRAY[]::TEXT[])
    INTO v_quality_count, v_actual_quality_refs
    FROM gda_control.quality_result AS result
    JOIN gda_control.artifact AS evidence_artifact
      ON evidence_artifact.tenant_id = result.tenant_id
     AND evidence_artifact.artifact_id = result.evidence_artifact_id
    WHERE result.tenant_id = p_tenant_id
      AND result.quality_result_id = ANY(v_quality_result_ids)
      AND result.run_id = p_run_id
      AND result.resource_version_id = v_target_resource_version_id
      AND result.verdict = 'passed'
      AND result.evaluated_by <> p_committed_by
      AND result.evaluated_at <= p_committed_at
      AND evidence_artifact.artifact_role = 'evidence'
      AND evidence_artifact.run_id = p_run_id
      AND evidence_artifact.resource_version_id = v_target_resource_version_id;
    IF v_quality_count <> cardinality(v_quality_result_ids)
       OR v_actual_quality_refs IS DISTINCT FROM v_expected_quality_refs THEN
        RAISE EXCEPTION 'quality evidence does not exactly satisfy sync contract'
            USING ERRCODE = '23514';
    END IF;

    SELECT lineage.* INTO v_lineage
    FROM gda_control.lineage_event AS lineage
    JOIN gda_control.resource_version AS source_version
      ON source_version.tenant_id = lineage.tenant_id
     AND source_version.resource_version_id =
         lineage.source_resource_version_id
    WHERE lineage.tenant_id = p_tenant_id
      AND lineage.lineage_event_id = v_lineage_event_id
      AND lineage.run_id = p_run_id
      AND lineage.definition_version_id =
          v_definition.platform_definition_version_id
      AND lineage.target_resource_version_id = v_target_resource_version_id
      AND lineage.artifact_id = v_output_artifact_id
      AND lineage.producer = p_committed_by
      AND lineage.occurred_at <= p_committed_at
      AND source_version.resource_urn = v_definition.source_resource_urn;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'LineageEvent does not match source sync execution'
            USING ERRCODE = '23514';
    END IF;

    SELECT * INTO v_metadata
    FROM gda_control.metadata_change_outbox AS change
    WHERE change.tenant_id = p_tenant_id
      AND change.change_id = v_metadata_change_id;
    IF NOT FOUND
       OR v_metadata.aggregate_id IS DISTINCT FROM v_lineage_event_id
       OR v_metadata.payload_sha256 IS DISTINCT FROM v_lineage.event_sha256
       OR v_metadata.change_type <> 'lineage_upsert'
       OR v_metadata.destination_ref <> 'openmetadata:default' THEN
        RAISE EXCEPTION 'metadata outbox change does not match LineageEvent'
            USING ERRCODE = '23514';
    END IF;

    IF v_promotion_mode = 'approval_gated' OR v_target_layer = 'gold' THEN
        IF v_approval_case_ref IS NULL THEN
            RAISE EXCEPTION 'approval-gated source sync requires ApprovalCase'
                USING ERRCODE = '23514';
        END IF;
    END IF;
    IF v_approval_case_ref IS NOT NULL THEN
        SELECT * INTO v_approval
        FROM gda_control.approval_case AS approval
        WHERE approval.tenant_id = p_tenant_id
          AND approval.approval_case_ref = v_approval_case_ref;
        IF NOT FOUND
           OR v_approval.target_resource_urn IS DISTINCT FROM
                v_definition.target_resource_urn
           OR v_approval.target_fingerprint IS DISTINCT FROM
                p_target_content_sha256
           OR v_approval.action <> 'source_sync.promote'
           OR v_approval.status <> 'approved'
           OR v_approval.decided_at IS NULL
           OR v_approval.decided_at > p_committed_at THEN
            RAISE EXCEPTION 'ApprovalCase does not authorize source sync promotion'
                USING ERRCODE = '23514';
        END IF;
    END IF;

    SELECT result.result_sync_commit_id, result.result_created
    INTO v_result_sync_commit_id, v_result_created
    FROM gda_control.commit_source_sync_v104(
        p_tenant_id, p_sync_commit_id, p_sync_definition_version_id,
        p_run_id, p_from_state_version, p_to_state_version,
        p_previous_cursor, p_previous_cursor_sha256,
        p_next_cursor, p_next_cursor_sha256, p_source_slice_sha256,
        p_target_commit_ref, p_target_content_sha256, p_records_read,
        p_records_inserted, p_records_updated, p_records_deleted,
        p_records_output, p_committed_by, p_committed_at, p_commit_sha256
    ) AS result;

    IF v_result_sync_commit_id <> p_sync_commit_id THEN
        PERFORM 1
        FROM gda_control.source_sync_commit_governance_evidence AS evidence
        WHERE evidence.tenant_id = p_tenant_id
          AND evidence.sync_commit_id = v_result_sync_commit_id;
        IF NOT FOUND THEN
            RAISE EXCEPTION 'replayed source slice lacks governance evidence'
                USING ERRCODE = '23514';
        END IF;
        RETURN QUERY SELECT v_result_sync_commit_id, FALSE;
        RETURN;
    END IF;

    PERFORM set_config(
        'gda.source_sync_governance_evidence_allowed', '1', true
    );
    INSERT INTO gda_control.source_sync_commit_governance_evidence (
        tenant_id, sync_commit_id, target_resource_version_id,
        output_artifact_id, quality_result_ids, lineage_event_id,
        metadata_change_id, approval_case_ref, evidence_sha256,
        recorded_at
    ) VALUES (
        p_tenant_id, p_sync_commit_id, v_target_resource_version_id,
        v_output_artifact_id, v_quality_result_ids, v_lineage_event_id,
        v_metadata_change_id, v_approval_case_ref, v_evidence_sha256,
        p_committed_at
    );
    PERFORM set_config(
        'gda.source_sync_governance_evidence_allowed', '0', true
    );

    RETURN QUERY SELECT v_result_sync_commit_id, v_result_created;
EXCEPTION WHEN OTHERS THEN
    PERFORM set_config(
        'gda.source_sync_governance_evidence_allowed', '0', true
    );
    RAISE;
END;
$$;

REVOKE ALL ON FUNCTION gda_control.commit_source_sync(
    TEXT, UUID, UUID, UUID, INTEGER, INTEGER, JSONB, TEXT, JSONB, TEXT,
    TEXT, JSONB, TEXT, BIGINT, BIGINT, BIGINT, BIGINT, BIGINT, TEXT,
    TIMESTAMPTZ, TEXT, JSONB
) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION gda_control.commit_source_sync(
    TEXT, UUID, UUID, UUID, INTEGER, INTEGER, JSONB, TEXT, JSONB, TEXT,
    TEXT, JSONB, TEXT, BIGINT, BIGINT, BIGINT, BIGINT, BIGINT, TEXT,
    TIMESTAMPTZ, TEXT, JSONB
) TO gda_control_gateway;
