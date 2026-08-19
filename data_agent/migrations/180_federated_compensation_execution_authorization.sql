-- 180: Consume a separate federated compensation execution authorization once.
--
-- Review approval is evidence only. A second independently approved execution
-- case is required, and consumption still performs no Provider mutation.

CREATE TABLE IF NOT EXISTS
gda_control.federated_compensation_execution_authorization_consumption (
    tenant_id TEXT NOT NULL,
    execution_approval_case_ref TEXT NOT NULL,
    review_approval_case_ref TEXT NOT NULL,
    proposal_sha256 CHAR(64) NOT NULL,
    candidate_sha256 CHAR(64) NOT NULL,
    execution_authorization_sha256 CHAR(64) NOT NULL,
    review_binding_sha256 CHAR(64) NOT NULL,
    execution_decided_by TEXT NOT NULL,
    review_decided_by TEXT NOT NULL,
    consumed_by TEXT NOT NULL,
    consume_reason TEXT NOT NULL,
    consumed_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (tenant_id, execution_approval_case_ref),
    CONSTRAINT uq_gda_federated_compensation_execution_review_consumption
        UNIQUE (tenant_id, review_approval_case_ref),
    CONSTRAINT fk_gda_federated_compensation_execution_case
        FOREIGN KEY (tenant_id, execution_approval_case_ref)
        REFERENCES gda_control.approval_case(tenant_id, approval_case_ref),
    CONSTRAINT fk_gda_federated_compensation_review_case
        FOREIGN KEY (tenant_id, review_approval_case_ref)
        REFERENCES gda_control.approval_case(tenant_id, approval_case_ref),
    CONSTRAINT ck_gda_federated_compensation_consumption_tenant
        CHECK (tenant_id ~ '^[a-z0-9][a-z0-9._-]{0,63}$'),
    CONSTRAINT ck_gda_federated_compensation_execution_case_ref CHECK (
        execution_approval_case_ref ~ (
            '^gda://[a-z0-9][a-z0-9._-]{0,63}/approval_case/'
            || '[a-z0-9][a-z0-9._-]{0,127}$'
        )
        AND split_part(execution_approval_case_ref, '/', 3) = tenant_id
    ),
    CONSTRAINT ck_gda_federated_compensation_review_case_ref CHECK (
        review_approval_case_ref ~ (
            '^gda://[a-z0-9][a-z0-9._-]{0,63}/approval_case/'
            || '[a-z0-9][a-z0-9._-]{0,127}$'
        )
        AND split_part(review_approval_case_ref, '/', 3) = tenant_id
        AND review_approval_case_ref <> execution_approval_case_ref
    ),
    CONSTRAINT ck_gda_federated_compensation_consumption_hashes CHECK (
        proposal_sha256 ~ '^[0-9a-f]{64}$'
        AND candidate_sha256 ~ '^[0-9a-f]{64}$'
        AND execution_authorization_sha256 ~ '^[0-9a-f]{64}$'
        AND review_binding_sha256 ~ '^[0-9a-f]{64}$'
    ),
    CONSTRAINT ck_gda_federated_compensation_consumption_approvers CHECK (
        execution_decided_by ~ '^human:[^[:space:]]{1,128}$'
        AND review_decided_by ~ '^human:[^[:space:]]{1,128}$'
        AND execution_decided_by <> review_decided_by
    ),
    CONSTRAINT ck_gda_federated_compensation_consumption_actor CHECK (
        consumed_by ~ '^(human|agent|workload):[^[:space:]]{1,128}$'
    ),
    CONSTRAINT ck_gda_federated_compensation_consumption_reason CHECK (
        NULLIF(btrim(consume_reason), '') IS NOT NULL
        AND octet_length(consume_reason) <= 1024
    )
);

CREATE TRIGGER trg_gda_federated_compensation_execution_consumption_immutable
BEFORE UPDATE OR DELETE ON
gda_control.federated_compensation_execution_authorization_consumption
FOR EACH ROW EXECUTE FUNCTION gda_control.reject_immutable_mutation();

ALTER TABLE
gda_control.federated_compensation_execution_authorization_consumption
    ENABLE ROW LEVEL SECURITY;
ALTER TABLE
gda_control.federated_compensation_execution_authorization_consumption
    FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON
gda_control.federated_compensation_execution_authorization_consumption
    USING (tenant_id = gda_control.current_tenant())
    WITH CHECK (tenant_id = gda_control.current_tenant());

REVOKE ALL ON TABLE
gda_control.federated_compensation_execution_authorization_consumption
    FROM PUBLIC, gda_control_gateway;
GRANT SELECT ON TABLE
gda_control.federated_compensation_execution_authorization_consumption
    TO gda_control_gateway;

CREATE FUNCTION
gda_control.consume_federated_compensation_execution_authorization(
    p_tenant_id TEXT,
    p_execution_approval_case_ref TEXT,
    p_review_approval_case_ref TEXT,
    p_proposal_sha256 TEXT,
    p_candidate_sha256 TEXT,
    p_execution_authorization_sha256 TEXT,
    p_review_binding_sha256 TEXT,
    p_consumed_by TEXT,
    p_consume_reason TEXT
)
RETURNS SETOF
gda_control.federated_compensation_execution_authorization_consumption
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, gda_control
SET row_security = on
AS $$
DECLARE
    v_execution gda_control.approval_case%ROWTYPE;
    v_review gda_control.approval_case%ROWTYPE;
    v_existing
        gda_control.federated_compensation_execution_authorization_consumption%ROWTYPE;
    v_inserted
        gda_control.federated_compensation_execution_authorization_consumption%ROWTYPE;
    v_expected_execution_target TEXT;
    v_expected_review_target TEXT;
    v_proposal_document JSONB;
    v_candidate JSONB;
BEGIN
    IF gda_control.current_tenant() IS NULL
       OR p_tenant_id IS DISTINCT FROM gda_control.current_tenant() THEN
        RAISE EXCEPTION 'federated compensation tenant context is missing or mismatched'
            USING ERRCODE = '42501';
    END IF;
    IF p_execution_approval_case_ref IS NULL
       OR p_review_approval_case_ref IS NULL
       OR p_execution_approval_case_ref = p_review_approval_case_ref
       OR p_proposal_sha256 !~ '^[0-9a-f]{64}$'
       OR p_candidate_sha256 !~ '^[0-9a-f]{64}$'
       OR p_execution_authorization_sha256 !~ '^[0-9a-f]{64}$'
       OR p_review_binding_sha256 !~ '^[0-9a-f]{64}$'
       OR p_consumed_by !~ '^(human|agent|workload):[^[:space:]]{1,128}$'
       OR NULLIF(btrim(p_consume_reason), '') IS NULL
       OR octet_length(btrim(p_consume_reason)) > 1024 THEN
        RAISE EXCEPTION 'federated compensation consumption identity is invalid'
            USING ERRCODE = '22023';
    END IF;

    PERFORM pg_advisory_xact_lock(
        hashtextextended(
            'federated-compensation-execution|'
            || p_tenant_id || '|' || p_execution_approval_case_ref,
            0
        )
    );
    SELECT consumption.* INTO v_existing
    FROM gda_control.
         federated_compensation_execution_authorization_consumption AS consumption
    WHERE consumption.tenant_id = p_tenant_id
      AND consumption.execution_approval_case_ref
            = p_execution_approval_case_ref;
    IF FOUND THEN
        IF v_existing.review_approval_case_ref
                IS DISTINCT FROM p_review_approval_case_ref
           OR v_existing.proposal_sha256::TEXT
                IS DISTINCT FROM p_proposal_sha256
           OR v_existing.candidate_sha256::TEXT
                IS DISTINCT FROM p_candidate_sha256
           OR v_existing.execution_authorization_sha256::TEXT
                IS DISTINCT FROM p_execution_authorization_sha256
           OR v_existing.review_binding_sha256::TEXT
                IS DISTINCT FROM p_review_binding_sha256
           OR v_existing.consumed_by IS DISTINCT FROM p_consumed_by
           OR v_existing.consume_reason IS DISTINCT FROM btrim(p_consume_reason) THEN
            RAISE EXCEPTION 'execution authorization consumption evidence differs'
                USING ERRCODE = '40001';
        END IF;
        RETURN NEXT v_existing;
        RETURN;
    END IF;
    IF EXISTS (
        SELECT 1
        FROM gda_control.
             federated_compensation_execution_authorization_consumption AS consumption
        WHERE consumption.tenant_id = p_tenant_id
          AND consumption.review_approval_case_ref = p_review_approval_case_ref
    ) THEN
        RAISE EXCEPTION 'review ApprovalCase was already consumed for execution'
            USING ERRCODE = '40001';
    END IF;

    SELECT approval.* INTO v_execution
    FROM gda_control.approval_case AS approval
    WHERE approval.tenant_id = p_tenant_id
      AND approval.approval_case_ref = p_execution_approval_case_ref
    FOR UPDATE;
    SELECT approval.* INTO v_review
    FROM gda_control.approval_case AS approval
    WHERE approval.tenant_id = p_tenant_id
      AND approval.approval_case_ref = p_review_approval_case_ref
    FOR UPDATE;

    v_expected_execution_target := format(
        'gda://%s/compensation_candidate/%s',
        p_tenant_id,
        p_candidate_sha256
    );
    v_expected_review_target := format(
        'gda://%s/compensation_proposal/%s',
        p_tenant_id,
        p_proposal_sha256
    );
    IF v_execution.approval_case_ref IS NULL
       OR v_execution.status IS DISTINCT FROM 'approved'
       OR v_execution.state_version IS DISTINCT FROM 1
       OR clock_timestamp() >= v_execution.expires_at
       OR v_execution.target_resource_urn
            IS DISTINCT FROM v_expected_execution_target
       OR v_execution.target_fingerprint
            IS DISTINCT FROM p_execution_authorization_sha256
       OR v_execution.action
            IS DISTINCT FROM 'projection.federated.compensation.execute'
       OR v_execution.request_context ->> 'schema'
            IS DISTINCT FROM
            'gda.federated-projection-compensation-execution-binding.v1'
       OR v_execution.request_context ->> 'execution_authorization_sha256'
            IS DISTINCT FROM p_execution_authorization_sha256
       OR v_execution.request_context ->> 'proposal_sha256'
            IS DISTINCT FROM p_proposal_sha256
       OR v_execution.request_context ->> 'candidate_sha256'
            IS DISTINCT FROM p_candidate_sha256
       OR v_execution.request_context ->> 'review_approval_case_ref'
            IS DISTINCT FROM p_review_approval_case_ref
       OR v_execution.request_context ->> 'review_binding_sha256'
            IS DISTINCT FROM p_review_binding_sha256
       OR v_execution.request_context -> 'review_approval_is_execution_authority'
            IS DISTINCT FROM 'false'::JSONB
       OR v_execution.request_context -> 'execution_case_is_provider_execution'
            IS DISTINCT FROM 'false'::JSONB
       OR v_execution.request_context -> 'automatic_execution_allowed'
            IS DISTINCT FROM 'false'::JSONB
       OR v_execution.request_context -> 'provider_execution_performed'
            IS DISTINCT FROM 'false'::JSONB
       OR jsonb_typeof(v_execution.request_context -> 'approved_rules')
            IS DISTINCT FROM 'array'
       OR jsonb_array_length(v_execution.request_context -> 'approved_rules') < 1 THEN
        RAISE EXCEPTION 'execution ApprovalCase does not authorize this candidate'
            USING ERRCODE = '23514';
    END IF;
    IF v_review.approval_case_ref IS NULL
       OR v_review.status IS DISTINCT FROM 'approved'
       OR v_review.state_version IS DISTINCT FROM 1
       OR clock_timestamp() >= v_review.expires_at
       OR v_review.target_resource_urn IS DISTINCT FROM v_expected_review_target
       OR v_review.target_fingerprint IS DISTINCT FROM p_review_binding_sha256
       OR v_review.action
            IS DISTINCT FROM 'projection.federated.compensation.review'
       OR v_review.request_context ->> 'schema'
            IS DISTINCT FROM
            'gda.federated-projection-compensation-approval-binding.v1'
       OR v_review.request_context ->> 'binding_sha256'
            IS DISTINCT FROM p_review_binding_sha256
       OR v_review.request_context ->> 'proposal_sha256'
            IS DISTINCT FROM p_proposal_sha256
       OR v_review.request_context ->> 'candidate_sha256'
            IS DISTINCT FROM p_candidate_sha256
       OR v_review.request_context -> 'approval_case_is_execution_authority'
            IS DISTINCT FROM 'false'::JSONB
       OR v_review.request_context -> 'execution_allowed'
            IS DISTINCT FROM 'false'::JSONB THEN
        RAISE EXCEPTION 'review ApprovalCase evidence is invalid or expired'
            USING ERRCODE = '23514';
    END IF;
    IF v_execution.requested_at < v_review.decided_at
       OR v_execution.expires_at > v_review.expires_at
       OR v_execution.decided_by = v_review.decided_by THEN
        RAISE EXCEPTION 'execution verdict is not independent from review verdict'
            USING ERRCODE = '23514';
    END IF;
    SELECT proposal.proposal_document
    INTO v_proposal_document
    FROM gda_control.cross_store_projection_compensation_proposal_current
         AS proposal
    WHERE proposal.tenant_id = p_tenant_id
      AND proposal.run_id = v_execution.request_context ->> 'run_id'
      AND proposal.proposal_sha256 = p_proposal_sha256;
    IF v_proposal_document IS NULL THEN
        RAISE EXCEPTION 'compensation proposal current drifted before consumption'
            USING ERRCODE = '23514';
    END IF;
    SELECT candidate.value
    INTO v_candidate
    FROM jsonb_array_elements(v_proposal_document -> 'candidates')
         AS candidate(value)
    WHERE candidate.value ->> 'candidate_sha256' = p_candidate_sha256;
    IF v_candidate IS NULL
       OR v_candidate ->> 'action'
            IS DISTINCT FROM v_execution.request_context ->> 'candidate_action'
       OR v_candidate -> 'mutates_provider' IS DISTINCT FROM 'true'::JSONB
       OR v_candidate -> 'approval_required' IS DISTINCT FROM 'true'::JSONB
       OR v_candidate -> 'recommended' IS DISTINCT FROM 'false'::JSONB
       OR v_candidate ->> 'implementation'
            IS DISTINCT FROM 'requires_customer_rule'
       OR v_candidate -> 'missing_customer_rule_ids' IS DISTINCT FROM (
            SELECT COALESCE(
                jsonb_agg(
                    to_jsonb(approved_rule.value ->> 'rule_id')
                    ORDER BY approved_rule.value ->> 'rule_id'
                ),
                '[]'::JSONB
            )
            FROM jsonb_array_elements(
                v_execution.request_context -> 'approved_rules'
            ) AS approved_rule(value)
       )
       OR v_review.request_context -> 'approved_rule_contract_sha256s'
            IS DISTINCT FROM (
                SELECT COALESCE(
                    jsonb_agg(
                        to_jsonb(approved_rule.value ->> 'contract_sha256')
                        ORDER BY approved_rule.value ->> 'rule_id'
                    ),
                    '[]'::JSONB
                )
                FROM jsonb_array_elements(
                    v_execution.request_context -> 'approved_rules'
                ) AS approved_rule(value)
            ) THEN
        RAISE EXCEPTION 'compensation candidate current drifted before consumption'
            USING ERRCODE = '23514';
    END IF;
    IF EXISTS (
        SELECT 1
        FROM jsonb_array_elements(
            v_execution.request_context -> 'approved_rules'
        ) AS approved_rule(value)
        LEFT JOIN gda_control.customer_compensation_rule_contract_current AS rule
          ON rule.tenant_id = p_tenant_id
         AND rule.rule_id = approved_rule.value ->> 'rule_id'
        WHERE rule.rule_id IS NULL
           OR rule.status <> 'customer_approved'
           OR rule.semantic_version
                IS DISTINCT FROM approved_rule.value ->> 'semantic_version'
           OR rule.rule_sha256
                IS DISTINCT FROM approved_rule.value ->> 'rule_sha256'
           OR rule.contract_sha256
                IS DISTINCT FROM approved_rule.value ->> 'contract_sha256'
           OR rule.contract_document -> 'approval_evidence'
                ->> 'approval_artifact_sha256'
                IS DISTINCT FROM
                approved_rule.value ->> 'approval_artifact_sha256'
    ) THEN
        RAISE EXCEPTION 'customer compensation rule current drifted before consumption'
            USING ERRCODE = '23514';
    END IF;

    INSERT INTO gda_control.
        federated_compensation_execution_authorization_consumption (
            tenant_id, execution_approval_case_ref, review_approval_case_ref,
            proposal_sha256, candidate_sha256,
            execution_authorization_sha256, review_binding_sha256,
            execution_decided_by, review_decided_by,
            consumed_by, consume_reason
        )
    VALUES (
        p_tenant_id, p_execution_approval_case_ref, p_review_approval_case_ref,
        p_proposal_sha256, p_candidate_sha256,
        p_execution_authorization_sha256, p_review_binding_sha256,
        v_execution.decided_by, v_review.decided_by,
        p_consumed_by, btrim(p_consume_reason)
    )
    RETURNING * INTO v_inserted;
    RETURN NEXT v_inserted;
END;
$$;

REVOKE ALL ON FUNCTION
gda_control.consume_federated_compensation_execution_authorization(
    TEXT, TEXT, TEXT, TEXT, TEXT, TEXT, TEXT, TEXT, TEXT
) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION
gda_control.consume_federated_compensation_execution_authorization(
    TEXT, TEXT, TEXT, TEXT, TEXT, TEXT, TEXT, TEXT, TEXT
) TO gda_control_gateway;
