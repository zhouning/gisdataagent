-- 096: Immutable quality evidence and evidence-gated PlatformRun success.
--
-- Provider success is only an observation. A PlatformRun may become succeeded
-- only after the database verifies its output, quality, and lineage bindings.

CREATE TABLE IF NOT EXISTS gda_control.quality_result (
    tenant_id TEXT NOT NULL,
    quality_result_id UUID PRIMARY KEY,
    run_id UUID NOT NULL,
    resource_version_id UUID NOT NULL,
    rule_version_ref TEXT NOT NULL,
    verdict TEXT NOT NULL,
    metrics JSONB NOT NULL,
    evidence_artifact_id UUID NOT NULL,
    result_sha256 CHAR(64) NOT NULL,
    evaluated_by TEXT NOT NULL,
    evaluated_at TIMESTAMPTZ NOT NULL,
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_gda_quality_result_tenant_id
        UNIQUE (tenant_id, quality_result_id),
    CONSTRAINT uq_gda_quality_result_fingerprint
        UNIQUE (tenant_id, run_id, result_sha256),
    CONSTRAINT fk_gda_quality_result_run
        FOREIGN KEY (tenant_id, run_id)
        REFERENCES gda_control.platform_run(tenant_id, run_id),
    CONSTRAINT fk_gda_quality_result_resource_version
        FOREIGN KEY (tenant_id, resource_version_id)
        REFERENCES gda_control.resource_version(tenant_id, resource_version_id),
    CONSTRAINT fk_gda_quality_result_evidence_artifact
        FOREIGN KEY (tenant_id, evidence_artifact_id)
        REFERENCES gda_control.artifact(tenant_id, artifact_id),
    CONSTRAINT ck_gda_quality_result_rule
        CHECK (NULLIF(btrim(rule_version_ref), '') IS NOT NULL),
    CONSTRAINT ck_gda_quality_result_verdict
        CHECK (verdict IN ('passed', 'failed')),
    CONSTRAINT ck_gda_quality_result_metrics
        CHECK (jsonb_typeof(metrics) = 'object' AND metrics <> '{}'::jsonb),
    CONSTRAINT ck_gda_quality_result_sha256
        CHECK (result_sha256 ~ '^[0-9a-f]{64}$'),
    CONSTRAINT ck_gda_quality_result_evaluator
        CHECK (evaluated_by ~ '^workload:.+')
);

CREATE INDEX IF NOT EXISTS idx_gda_quality_result_run
    ON gda_control.quality_result(tenant_id, run_id, evaluated_at DESC);
CREATE INDEX IF NOT EXISTS idx_gda_quality_result_resource
    ON gda_control.quality_result(
        tenant_id, resource_version_id, evaluated_at DESC
    );

DROP TRIGGER IF EXISTS trg_gda_immutable
    ON gda_control.quality_result;
CREATE TRIGGER trg_gda_immutable
BEFORE UPDATE OR DELETE ON gda_control.quality_result
FOR EACH ROW EXECUTE FUNCTION gda_control.reject_immutable_mutation();

ALTER TABLE gda_control.quality_result ENABLE ROW LEVEL SECURITY;
ALTER TABLE gda_control.quality_result FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON gda_control.quality_result;
CREATE POLICY tenant_isolation ON gda_control.quality_result
    USING (tenant_id = gda_control.current_tenant())
    WITH CHECK (tenant_id = gda_control.current_tenant());

-- Preserve the original transition implementation as a private primitive.
-- The public gateway wrapper below removes direct access to succeeded.
DO $migration$
BEGIN
    IF to_regprocedure(
        'gda_control.apply_platform_run_transition(text,uuid,integer,text,text,text,jsonb)'
    ) IS NULL THEN
        ALTER FUNCTION gda_control.transition_platform_run(
            text, uuid, integer, text, text, text, jsonb
        ) RENAME TO apply_platform_run_transition;
    END IF;
END
$migration$;

REVOKE ALL ON FUNCTION gda_control.apply_platform_run_transition(
    text, uuid, integer, text, text, text, jsonb
) FROM PUBLIC;
REVOKE ALL ON FUNCTION gda_control.apply_platform_run_transition(
    text, uuid, integer, text, text, text, jsonb
) FROM gda_control_gateway;

CREATE OR REPLACE FUNCTION gda_control.transition_platform_run(
    p_tenant_id TEXT,
    p_run_id UUID,
    p_expected_state_version INTEGER,
    p_to_status TEXT,
    p_actor_subject TEXT,
    p_reason TEXT,
    p_details JSONB DEFAULT '{}'::jsonb
)
RETURNS INTEGER
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, gda_control
SET row_security = on
AS $$
BEGIN
    IF p_to_status = 'succeeded' THEN
        RAISE EXCEPTION
            'succeeded requires gda_control.finalize_platform_run_success()'
            USING ERRCODE = '23514';
    END IF;
    RETURN gda_control.apply_platform_run_transition(
        p_tenant_id,
        p_run_id,
        p_expected_state_version,
        p_to_status,
        p_actor_subject,
        p_reason,
        p_details
    );
END;
$$;

CREATE OR REPLACE FUNCTION gda_control.finalize_platform_run_success(
    p_tenant_id TEXT,
    p_run_id UUID,
    p_expected_state_version INTEGER,
    p_actor_subject TEXT,
    p_reason TEXT,
    p_details JSONB
)
RETURNS INTEGER
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, gda_control
SET row_security = on
AS $$
DECLARE
    v_run gda_control.platform_run%ROWTYPE;
    v_event gda_control.platform_run_event%ROWTYPE;
    v_observation_id UUID;
    v_output_artifact_id UUID;
    v_quality_result_id UUID;
    v_lineage_event_id UUID;
    v_expected_evidence_sha256 TEXT;
    v_output gda_control.artifact%ROWTYPE;
    v_quality gda_control.quality_result%ROWTYPE;
BEGIN
    IF gda_control.current_tenant() IS NULL
       OR p_tenant_id IS DISTINCT FROM gda_control.current_tenant() THEN
        RAISE EXCEPTION 'platform run tenant context is missing or mismatched'
            USING ERRCODE = '42501';
    END IF;
    IF NULLIF(btrim(p_actor_subject), '') IS NULL
       OR NULLIF(btrim(p_reason), '') IS NULL THEN
        RAISE EXCEPTION 'finalization actor and reason are required'
            USING ERRCODE = '22023';
    END IF;
    IF jsonb_typeof(p_details) <> 'object'
       OR p_details->>'schema' <> 'gda.run_success_evidence.v1'
       OR p_details->>'tenant_id' IS DISTINCT FROM p_tenant_id
       OR p_details->>'run_id' IS DISTINCT FROM p_run_id::text
       OR COALESCE(p_details->>'evidence_sha256', '')
            !~ '^[0-9a-f]{64}$' THEN
        RAISE EXCEPTION 'success evidence envelope is invalid'
            USING ERRCODE = '22023';
    END IF;

    SELECT * INTO v_run
    FROM gda_control.platform_run
    WHERE tenant_id = p_tenant_id AND run_id = p_run_id
    FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'platform run % not found', p_run_id
            USING ERRCODE = 'P0002';
    END IF;

    IF v_run.status = 'succeeded' THEN
        SELECT * INTO v_event
        FROM gda_control.platform_run_event
        WHERE tenant_id = p_tenant_id
          AND run_id = p_run_id
          AND sequence_no = v_run.state_version;
        IF FOUND
           AND v_event.to_status = 'succeeded'
           AND v_event.actor_subject = p_actor_subject
           AND v_event.reason = p_reason
           AND v_event.details = p_details THEN
            RETURN v_run.state_version;
        END IF;
        RAISE EXCEPTION 'successful Run has a different terminal verdict'
            USING ERRCODE = '40001';
    END IF;

    IF v_run.state_version <> p_expected_state_version THEN
        RAISE EXCEPTION 'platform run state version conflict: expected %, actual %',
            p_expected_state_version, v_run.state_version
            USING ERRCODE = '40001';
    END IF;
    IF v_run.status NOT IN ('running', 'reconciling') THEN
        RAISE EXCEPTION 'success finalization requires running or reconciling Run'
            USING ERRCODE = '23514';
    END IF;
    IF p_actor_subject IS DISTINCT FROM concat(
        v_run.subject_context->>'subject_type',
        ':',
        v_run.subject_context->>'subject_id'
    ) THEN
        RAISE EXCEPTION 'finalization actor does not match Run workload'
            USING ERRCODE = '42501';
    END IF;

    BEGIN
        v_observation_id := (p_details->>'attempt_observation_id')::uuid;
        v_output_artifact_id := (p_details->>'output_artifact_id')::uuid;
        v_quality_result_id := (p_details->>'quality_result_id')::uuid;
        v_lineage_event_id := (p_details->>'lineage_event_id')::uuid;
    EXCEPTION WHEN invalid_text_representation OR null_value_not_allowed THEN
        RAISE EXCEPTION 'success evidence identifiers must be UUIDs'
            USING ERRCODE = '22023';
    END;

    v_expected_evidence_sha256 := encode(
        sha256(
            convert_to(
                '{"attempt_observation_id":'
                || to_json(v_observation_id::text)::text
                || ',"lineage_event_id":'
                || to_json(v_lineage_event_id::text)::text
                || ',"output_artifact_id":'
                || to_json(v_output_artifact_id::text)::text
                || ',"quality_result_id":'
                || to_json(v_quality_result_id::text)::text
                || ',"run_id":'
                || to_json(p_run_id::text)::text
                || ',"tenant_id":'
                || to_json(p_tenant_id)::text
                || '}',
                'UTF8'
            )
        ),
        'hex'
    );
    IF p_details->>'evidence_sha256'
       IS DISTINCT FROM v_expected_evidence_sha256 THEN
        RAISE EXCEPTION 'success evidence fingerprint does not match its bindings'
            USING ERRCODE = '22023';
    END IF;

    PERFORM 1
    FROM gda_control.framework_attempt_observation
    WHERE tenant_id = p_tenant_id
      AND observation_id = v_observation_id
      AND run_id = p_run_id
      AND framework_kind = 'dolphinscheduler'
      AND lower(observed_state) = 'success';
    IF NOT FOUND THEN
        RAISE EXCEPTION 'DolphinScheduler success observation was not found'
            USING ERRCODE = '23514';
    END IF;

    SELECT artifact.* INTO v_output
    FROM gda_control.artifact AS artifact
    JOIN gda_control.resource_version AS version
      ON version.tenant_id = artifact.tenant_id
     AND version.resource_version_id = artifact.resource_version_id
     AND version.content_sha256 = artifact.content_sha256
    WHERE artifact.tenant_id = p_tenant_id
      AND artifact.artifact_id = v_output_artifact_id
      AND artifact.run_id = p_run_id
      AND artifact.artifact_role = 'output';
    IF NOT FOUND THEN
        RAISE EXCEPTION 'content-bound output Artifact was not found'
            USING ERRCODE = '23514';
    END IF;

    SELECT quality.* INTO v_quality
    FROM gda_control.quality_result AS quality
    JOIN gda_control.artifact AS evidence
      ON evidence.tenant_id = quality.tenant_id
     AND evidence.artifact_id = quality.evidence_artifact_id
    WHERE quality.tenant_id = p_tenant_id
      AND quality.quality_result_id = v_quality_result_id
      AND quality.run_id = p_run_id
      AND quality.resource_version_id = v_output.resource_version_id
      AND quality.verdict = 'passed'
      AND quality.evaluated_by <> p_actor_subject
      AND quality.evaluated_at >= v_output.created_at
      AND evidence.artifact_role = 'evidence'
      AND evidence.run_id = p_run_id
      AND evidence.resource_version_id = v_output.resource_version_id
      AND evidence.created_by = quality.evaluated_by;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'independent passed QualityResult was not found'
            USING ERRCODE = '23514';
    END IF;

    PERFORM 1
    FROM gda_control.lineage_event AS lineage
    WHERE lineage.tenant_id = p_tenant_id
      AND lineage.lineage_event_id = v_lineage_event_id
      AND lineage.run_id = p_run_id
      AND lineage.definition_version_id = v_run.definition_version_id
      AND lineage.artifact_id = v_output_artifact_id
      AND lineage.target_resource_version_id = v_output.resource_version_id
      AND EXISTS (
          SELECT 1
          FROM gda_control.platform_run_input_binding AS input
          WHERE input.tenant_id = p_tenant_id
            AND input.run_id = p_run_id
            AND input.resource_version_id = lineage.source_resource_version_id
      );
    IF NOT FOUND THEN
        RAISE EXCEPTION 'input-to-output LineageEvent was not found'
            USING ERRCODE = '23514';
    END IF;

    RETURN gda_control.apply_platform_run_transition(
        p_tenant_id,
        p_run_id,
        p_expected_state_version,
        'succeeded',
        p_actor_subject,
        p_reason,
        p_details
    );
END;
$$;

REVOKE ALL ON TABLE gda_control.quality_result FROM PUBLIC;
REVOKE ALL ON TABLE gda_control.quality_result FROM gda_control_gateway;
GRANT SELECT, INSERT ON gda_control.quality_result TO gda_control_gateway;

REVOKE ALL ON FUNCTION gda_control.transition_platform_run(
    text, uuid, integer, text, text, text, jsonb
) FROM PUBLIC;
REVOKE ALL ON FUNCTION gda_control.finalize_platform_run_success(
    text, uuid, integer, text, text, jsonb
) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION gda_control.transition_platform_run(
    text, uuid, integer, text, text, text, jsonb
) TO gda_control_gateway;
GRANT EXECUTE ON FUNCTION gda_control.finalize_platform_run_success(
    text, uuid, integer, text, text, jsonb
) TO gda_control_gateway;
