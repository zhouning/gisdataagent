-- 178: Immutable assisted-precheck proposals for blocked federated recovery.

CREATE TABLE IF NOT EXISTS gda_control.cross_store_projection_compensation_proposal (
    tenant_id TEXT NOT NULL,
    run_id TEXT NOT NULL,
    source_snapshot_sha256 CHAR(64) NOT NULL,
    blocked_plan_sha256 CHAR(64) NOT NULL,
    proposal_sha256 CHAR(64) NOT NULL,
    ontology_content_sha256 CHAR(64) NOT NULL,
    proposal_document JSONB NOT NULL,
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (tenant_id, proposal_sha256),
    CONSTRAINT uq_gda_projection_compensation_proposal_snapshot
        UNIQUE (tenant_id, run_id, source_snapshot_sha256),
    CONSTRAINT fk_gda_projection_compensation_proposal_snapshot
        FOREIGN KEY (tenant_id, source_snapshot_sha256)
        REFERENCES gda_control.cross_store_projection_federated_recovery_snapshot_history
            (tenant_id, snapshot_sha256),
    CONSTRAINT ck_gda_projection_compensation_proposal_tenant
        CHECK (tenant_id ~ '^[a-z0-9][a-z0-9._-]{0,63}$'),
    CONSTRAINT ck_gda_projection_compensation_proposal_run
        CHECK (NULLIF(btrim(run_id), '') IS NOT NULL AND octet_length(run_id) <= 512),
    CONSTRAINT ck_gda_projection_compensation_proposal_hashes
        CHECK (
            source_snapshot_sha256 ~ '^[0-9a-f]{64}$'
            AND blocked_plan_sha256 ~ '^[0-9a-f]{64}$'
            AND proposal_sha256 ~ '^[0-9a-f]{64}$'
            AND ontology_content_sha256 ~ '^[0-9a-f]{64}$'
        ),
    CONSTRAINT ck_gda_projection_compensation_proposal_document
        CHECK (
            jsonb_typeof(proposal_document) = 'object'
            AND proposal_document ->> 'tenant_id' = tenant_id
            AND proposal_document ->> 'run_id' = run_id
            AND proposal_document ->> 'source_snapshot_sha256' = source_snapshot_sha256
            AND proposal_document ->> 'blocked_plan_sha256' = blocked_plan_sha256
            AND proposal_document ->> 'proposal_sha256' = proposal_sha256
            AND proposal_document -> 'ontology' ->> 'content_sha256'
                = ontology_content_sha256
        )
);

CREATE INDEX IF NOT EXISTS idx_gda_projection_compensation_proposal_run
    ON gda_control.cross_store_projection_compensation_proposal
        (tenant_id, run_id, recorded_at DESC);

CREATE OR REPLACE VIEW gda_control.cross_store_projection_compensation_proposal_current
WITH (security_invoker = true)
AS
SELECT DISTINCT ON (tenant_id, run_id)
       tenant_id, run_id, source_snapshot_sha256, blocked_plan_sha256,
       proposal_sha256, ontology_content_sha256, proposal_document, recorded_at
FROM gda_control.cross_store_projection_compensation_proposal
ORDER BY tenant_id, run_id, recorded_at DESC, proposal_sha256 DESC;

CREATE OR REPLACE FUNCTION gda_control.guard_cross_store_projection_compensation_proposal_insert()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    IF COALESCE(
        current_setting(
            'gda.cross_store_projection_compensation_proposal_write_allowed', true
        ),
        ''
    ) <> '1' THEN
        RAISE EXCEPTION
            'use gda_control.record_cross_store_projection_compensation_proposal()'
            USING ERRCODE = '55000';
    END IF;
    IF gda_control.current_tenant() IS NULL
       OR NEW.tenant_id IS DISTINCT FROM gda_control.current_tenant() THEN
        RAISE EXCEPTION 'projection compensation proposal tenant is mismatched'
            USING ERRCODE = '42501';
    END IF;
    RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION gda_control.record_cross_store_projection_compensation_proposal(
    p_tenant_id TEXT,
    p_run_id TEXT,
    p_source_snapshot_sha256 TEXT,
    p_blocked_plan_sha256 TEXT,
    p_proposal_sha256 TEXT,
    p_ontology_content_sha256 TEXT,
    p_proposal_document JSONB
)
RETURNS TABLE(proposal_document JSONB, created BOOLEAN)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, gda_control
SET row_security = on
AS $$
DECLARE
    v_existing gda_control.cross_store_projection_compensation_proposal%ROWTYPE;
    v_source gda_control.cross_store_projection_federated_recovery_snapshot_history%ROWTYPE;
    v_candidate JSONB;
    v_candidate_count INTEGER;
    v_index INTEGER;
    v_plan_sha256s JSONB;
    v_recommended_count INTEGER;
    v_recommended_sha256 TEXT;
BEGIN
    IF gda_control.current_tenant() IS NULL
       OR p_tenant_id IS DISTINCT FROM gda_control.current_tenant() THEN
        RAISE EXCEPTION 'projection compensation proposal tenant is mismatched'
            USING ERRCODE = '42501';
    END IF;
    IF NULLIF(btrim(p_run_id), '') IS NULL
       OR octet_length(p_run_id) > 512
       OR p_source_snapshot_sha256 IS NULL
       OR p_source_snapshot_sha256 !~ '^[0-9a-f]{64}$'
       OR p_blocked_plan_sha256 IS NULL
       OR p_blocked_plan_sha256 !~ '^[0-9a-f]{64}$'
       OR p_proposal_sha256 IS NULL
       OR p_proposal_sha256 !~ '^[0-9a-f]{64}$'
       OR p_ontology_content_sha256 IS NULL
       OR p_ontology_content_sha256 !~ '^[0-9a-f]{64}$'
       OR p_proposal_document IS NULL
       OR jsonb_typeof(p_proposal_document) <> 'object'
       OR p_proposal_document ->> 'tenant_id' IS DISTINCT FROM p_tenant_id
       OR p_proposal_document ->> 'run_id' IS DISTINCT FROM p_run_id
       OR p_proposal_document ->> 'source_snapshot_sha256'
            IS DISTINCT FROM p_source_snapshot_sha256
       OR p_proposal_document ->> 'blocked_plan_sha256'
            IS DISTINCT FROM p_blocked_plan_sha256
       OR p_proposal_document ->> 'proposal_sha256'
            IS DISTINCT FROM p_proposal_sha256
       OR p_proposal_document ->> 'dataset_scope'
            IS DISTINCT FROM 'chongqing_customer_dataset'
       OR p_proposal_document ->> 'review_state'
            IS DISTINCT FROM 'technical_baseline_unreviewed'
       OR p_proposal_document ->> 'intended_use'
            IS DISTINCT FROM 'assisted_precheck_not_for_production_decision'
       OR p_proposal_document -> 'automatic_mutating_selection_allowed'
            IS DISTINCT FROM 'false'::JSONB
       OR p_proposal_document -> 'execution_allowed'
            IS DISTINCT FROM 'false'::JSONB
       OR p_proposal_document ->> 'recovery_state'
            NOT IN ('compensation_required', 'failed_closed')
       OR jsonb_typeof(p_proposal_document -> 'source_bindings') <> 'array'
       OR jsonb_array_length(p_proposal_document -> 'source_bindings')
            NOT BETWEEN 2 AND 32
       OR jsonb_typeof(p_proposal_document -> 'candidates') <> 'array'
       OR jsonb_array_length(p_proposal_document -> 'candidates')
            NOT BETWEEN 3 AND 6
       OR jsonb_typeof(p_proposal_document -> 'missing_customer_rule_ids')
            <> 'array'
       OR p_proposal_document -> 'ontology' ->> 'ontology_key'
            IS DISTINCT FROM 'natural-resource-one-map'
       OR p_proposal_document -> 'ontology' ->> 'semantic_version'
            IS DISTINCT FROM '2.3.0'
       OR p_proposal_document -> 'ontology' ->> 'package_id'
            IS DISTINCT FROM 'natural-resource-one-map:2.3.0:587915868b1221af'
       OR p_proposal_document -> 'ontology' ->> 'content_sha256'
            IS DISTINCT FROM p_ontology_content_sha256
       OR p_ontology_content_sha256 IS DISTINCT FROM
            '587915868b1221af2315508ede7bf7babced063cba8b261de2f10afa23841019'
       OR COALESCE((p_proposal_document ->> 'blocked_position')::INTEGER, -1) < 0
    THEN
        RAISE EXCEPTION 'projection compensation proposal evidence is invalid'
            USING ERRCODE = '22023';
    END IF;

    SELECT jsonb_agg(binding.value -> 'plan_sha256' ORDER BY binding.ordinality)
    INTO v_plan_sha256s
    FROM jsonb_array_elements(p_proposal_document -> 'source_bindings')
         WITH ORDINALITY AS binding(value, ordinality);
    IF EXISTS (
        SELECT 1
        FROM jsonb_array_elements(p_proposal_document -> 'source_bindings')
             WITH ORDINALITY AS binding(value, ordinality)
        WHERE binding.value ->> 'plan_sha256' !~ '^[0-9a-f]{64}$'
           OR (binding.value ->> 'position')::INTEGER <> binding.ordinality - 1
    ) OR (
        p_proposal_document -> 'source_bindings'
        -> (p_proposal_document ->> 'blocked_position')::INTEGER
        ->> 'plan_sha256'
    ) IS DISTINCT FROM p_blocked_plan_sha256 THEN
        RAISE EXCEPTION 'projection compensation proposal plan binding is invalid'
            USING ERRCODE = '22023';
    END IF;

    v_candidate_count := jsonb_array_length(p_proposal_document -> 'candidates');
    v_recommended_count := 0;
    FOR v_index IN 0..v_candidate_count - 1 LOOP
        v_candidate := p_proposal_document -> 'candidates' -> v_index;
        IF jsonb_typeof(v_candidate) <> 'object'
           OR (v_candidate ->> 'rank')::INTEGER <> v_index + 1
           OR v_candidate ->> 'candidate_sha256' !~ '^[0-9a-f]{64}$'
           OR v_candidate ->> 'action' NOT IN (
                'reconcile_provider_outcome', 'approved_reapply_sealed_plan',
                'corrective_forward', 'rollback_committed_prefix',
                'delete_target', 'restore_target'
           )
           OR jsonb_typeof(v_candidate -> 'plan_sha256s') <> 'array'
           OR jsonb_array_length(v_candidate -> 'plan_sha256s') < 1
           OR jsonb_typeof(v_candidate -> 'missing_customer_rule_ids') <> 'array'
        THEN
            RAISE EXCEPTION 'projection compensation candidate evidence is invalid'
                USING ERRCODE = '22023';
        END IF;
        IF v_candidate -> 'recommended' = 'true'::JSONB THEN
            v_recommended_count := v_recommended_count + 1;
            v_recommended_sha256 := v_candidate ->> 'candidate_sha256';
            IF v_candidate -> 'mutates_provider' IS DISTINCT FROM 'false'::JSONB
               OR v_candidate ->> 'action'
                    IS DISTINCT FROM 'reconcile_provider_outcome' THEN
                RAISE EXCEPTION 'mutating compensation cannot be recommended'
                    USING ERRCODE = '22023';
            END IF;
        END IF;
        IF v_candidate -> 'mutates_provider' = 'true'::JSONB
           AND v_candidate -> 'approval_required' IS DISTINCT FROM 'true'::JSONB THEN
            RAISE EXCEPTION 'mutating compensation lacks approval boundary'
                USING ERRCODE = '22023';
        END IF;
    END LOOP;
    IF v_recommended_count > 1 THEN
        RAISE EXCEPTION 'projection compensation proposal has multiple recommendations'
            USING ERRCODE = '22023';
    END IF;
    IF (
        p_proposal_document ->> 'recovery_state' = 'compensation_required'
        AND (
            v_recommended_count <> 1
            OR p_proposal_document ->> 'recommended_candidate_sha256'
                IS DISTINCT FROM v_recommended_sha256
        )
    ) OR (
        p_proposal_document ->> 'recovery_state' = 'failed_closed'
        AND (
            v_recommended_count <> 0
            OR p_proposal_document ->> 'recommended_candidate_sha256' IS NOT NULL
            OR EXISTS (
                SELECT 1
                FROM jsonb_array_elements(
                    p_proposal_document -> 'candidates'
                ) AS candidate(value)
                WHERE candidate.value ->> 'action' IN (
                    'reconcile_provider_outcome',
                    'approved_reapply_sealed_plan'
                )
            )
        )
    ) THEN
        RAISE EXCEPTION 'projection compensation recommendation state is invalid'
            USING ERRCODE = '22023';
    END IF;

    PERFORM pg_advisory_xact_lock(
        hashtextextended(
            'projection-compensation-proposal|' || p_tenant_id || '|'
            || p_run_id || '|' || p_source_snapshot_sha256,
            0
        )
    );

    SELECT source.* INTO v_source
    FROM gda_control.cross_store_projection_federated_recovery_snapshot_history AS source
    WHERE source.tenant_id = p_tenant_id
      AND source.snapshot_sha256 = p_source_snapshot_sha256;
    IF NOT FOUND
       OR v_source.run_id IS DISTINCT FROM p_run_id
       OR v_source.plan_sha256s IS DISTINCT FROM v_plan_sha256s
       OR v_source.snapshot_document ->> 'state'
            IS DISTINCT FROM p_proposal_document ->> 'recovery_state'
       OR (v_source.snapshot_document ->> 'current_position')::INTEGER
            IS DISTINCT FROM
            (p_proposal_document ->> 'blocked_position')::INTEGER THEN
        RAISE EXCEPTION 'federated recovery source snapshot is missing or drifted'
            USING ERRCODE = '22023';
    END IF;

    SELECT stored.* INTO v_existing
    FROM gda_control.cross_store_projection_compensation_proposal AS stored
    WHERE stored.tenant_id = p_tenant_id
      AND stored.run_id = p_run_id
      AND stored.source_snapshot_sha256 = p_source_snapshot_sha256;
    IF FOUND THEN
        IF v_existing.proposal_sha256 IS DISTINCT FROM p_proposal_sha256
           OR v_existing.proposal_document IS DISTINCT FROM p_proposal_document THEN
            RAISE EXCEPTION 'projection compensation proposal idempotency differs'
                USING ERRCODE = '40001';
        END IF;
        RETURN QUERY SELECT v_existing.proposal_document, FALSE;
        RETURN;
    END IF;

    PERFORM set_config(
        'gda.cross_store_projection_compensation_proposal_write_allowed',
        '1',
        true
    );
    INSERT INTO gda_control.cross_store_projection_compensation_proposal (
        tenant_id, run_id, source_snapshot_sha256, blocked_plan_sha256,
        proposal_sha256, ontology_content_sha256, proposal_document
    ) VALUES (
        p_tenant_id, p_run_id, p_source_snapshot_sha256, p_blocked_plan_sha256,
        p_proposal_sha256, p_ontology_content_sha256, p_proposal_document
    )
    RETURNING * INTO v_existing;
    PERFORM set_config(
        'gda.cross_store_projection_compensation_proposal_write_allowed',
        '0',
        true
    );

    RETURN QUERY SELECT v_existing.proposal_document, TRUE;
EXCEPTION WHEN OTHERS THEN
    PERFORM set_config(
        'gda.cross_store_projection_compensation_proposal_write_allowed',
        '0',
        true
    );
    RAISE;
END;
$$;

DROP TRIGGER IF EXISTS trg_gda_projection_compensation_proposal_insert_guard
    ON gda_control.cross_store_projection_compensation_proposal;
CREATE TRIGGER trg_gda_projection_compensation_proposal_insert_guard
BEFORE INSERT ON gda_control.cross_store_projection_compensation_proposal
FOR EACH ROW
EXECUTE FUNCTION gda_control.guard_cross_store_projection_compensation_proposal_insert();

DROP TRIGGER IF EXISTS trg_gda_projection_compensation_proposal_immutable
    ON gda_control.cross_store_projection_compensation_proposal;
CREATE TRIGGER trg_gda_projection_compensation_proposal_immutable
BEFORE UPDATE OR DELETE
ON gda_control.cross_store_projection_compensation_proposal
FOR EACH ROW EXECUTE FUNCTION gda_control.reject_immutable_mutation();

ALTER TABLE gda_control.cross_store_projection_compensation_proposal
    ENABLE ROW LEVEL SECURITY;
ALTER TABLE gda_control.cross_store_projection_compensation_proposal
    FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation
    ON gda_control.cross_store_projection_compensation_proposal;
CREATE POLICY tenant_isolation
    ON gda_control.cross_store_projection_compensation_proposal
    USING (tenant_id = gda_control.current_tenant())
    WITH CHECK (tenant_id = gda_control.current_tenant());

REVOKE ALL ON TABLE
    gda_control.cross_store_projection_compensation_proposal
    FROM PUBLIC, gda_control_gateway;
REVOKE ALL ON TABLE
    gda_control.cross_store_projection_compensation_proposal_current
    FROM PUBLIC, gda_control_gateway;
GRANT SELECT ON TABLE
    gda_control.cross_store_projection_compensation_proposal
    TO gda_control_gateway;
GRANT SELECT ON TABLE
    gda_control.cross_store_projection_compensation_proposal_current
    TO gda_control_gateway;

REVOKE ALL ON FUNCTION
    gda_control.guard_cross_store_projection_compensation_proposal_insert()
    FROM PUBLIC;
REVOKE ALL ON FUNCTION
    gda_control.record_cross_store_projection_compensation_proposal(
        TEXT, TEXT, TEXT, TEXT, TEXT, TEXT, JSONB
    ) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION
    gda_control.record_cross_store_projection_compensation_proposal(
        TEXT, TEXT, TEXT, TEXT, TEXT, TEXT, JSONB
    ) TO gda_control_gateway;
