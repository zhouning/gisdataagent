-- 183: Reject lifecycle regression before accepting an idempotent historical replay.

CREATE OR REPLACE FUNCTION gda_control.record_customer_compensation_rule_contract(
    p_tenant_id TEXT,
    p_rule_id TEXT,
    p_semantic_version TEXT,
    p_rule_sha256 TEXT,
    p_contract_sha256 TEXT,
    p_status TEXT,
    p_contract_document JSONB
)
RETURNS TABLE(contract_document JSONB, created BOOLEAN)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, gda_control
SET row_security = on
AS $$
DECLARE
    v_existing gda_control.customer_compensation_rule_contract%ROWTYPE;
    v_current gda_control.customer_compensation_rule_contract%ROWTYPE;
    v_status_rank INTEGER;
    v_current_rank INTEGER;
BEGIN
    IF gda_control.current_tenant() IS NULL
       OR p_tenant_id IS DISTINCT FROM gda_control.current_tenant() THEN
        RAISE EXCEPTION 'customer compensation rule tenant is mismatched'
            USING ERRCODE = '42501';
    END IF;
    IF p_rule_id IS NULL
       OR p_rule_id !~ '^customer[.]compensation[.](corrective-forward|rollback|delete|restore|reconciliation)[.]v[1-9][0-9]*$'
       OR p_semantic_version IS NULL
       OR p_semantic_version !~ '^(0|[1-9][0-9]*)[.](0|[1-9][0-9]*)[.](0|[1-9][0-9]*)$'
       OR split_part(p_rule_id, '.v', 2)
            IS DISTINCT FROM split_part(p_semantic_version, '.', 1)
       OR p_rule_sha256 IS NULL
       OR p_rule_sha256 !~ '^[0-9a-f]{64}$'
       OR p_contract_sha256 IS NULL
       OR p_contract_sha256 !~ '^[0-9a-f]{64}$'
       OR p_status NOT IN ('draft_unreviewed', 'awaiting_customer_approval', 'customer_approved')
       OR p_contract_document IS NULL
       OR jsonb_typeof(p_contract_document) <> 'object'
       OR p_contract_document ->> 'tenant_id' IS DISTINCT FROM p_tenant_id
       OR p_contract_document ->> 'status' IS DISTINCT FROM p_status
       OR p_contract_document ->> 'contract_sha256' IS DISTINCT FROM p_contract_sha256
       OR p_contract_document ->> 'review_state'
            IS DISTINCT FROM 'technical_baseline_unreviewed'
       OR p_contract_document ->> 'intended_use'
            IS DISTINCT FROM 'assisted_precheck_not_for_production_decision'
       OR p_contract_document -> 'automatic_mutating_selection_allowed'
            IS DISTINCT FROM 'false'::JSONB
       OR p_contract_document -> 'execution_allowed'
            IS DISTINCT FROM 'false'::JSONB
       OR jsonb_typeof(p_contract_document -> 'rule') <> 'object'
       OR p_contract_document -> 'rule' ->> 'rule_id'
            IS DISTINCT FROM p_rule_id
       OR p_contract_document -> 'rule' ->> 'semantic_version'
            IS DISTINCT FROM p_semantic_version
       OR p_contract_document -> 'rule' ->> 'rule_sha256'
            IS DISTINCT FROM p_rule_sha256
       OR p_contract_document -> 'rule' ->> 'action' IS DISTINCT FROM (
            CASE p_rule_id
                WHEN 'customer.compensation.reconciliation.v1'
                    THEN 'reconcile_provider_outcome'
                WHEN 'customer.compensation.corrective-forward.v1'
                    THEN 'corrective_forward'
                WHEN 'customer.compensation.rollback.v1'
                    THEN 'rollback_committed_prefix'
                WHEN 'customer.compensation.delete.v1'
                    THEN 'delete_target'
                WHEN 'customer.compensation.restore.v1'
                    THEN 'restore_target'
            END
       )
       OR p_contract_document -> 'rule' -> 'mutates_provider'
            IS DISTINCT FROM (
                CASE WHEN p_rule_id = 'customer.compensation.reconciliation.v1'
                     THEN 'false'::JSONB ELSE 'true'::JSONB END
            )
       OR p_contract_document -> 'rule' ->> 'dataset_scope'
            IS DISTINCT FROM 'chongqing_customer_dataset'
       OR p_contract_document -> 'rule' -> 'automatic_mutating_selection_allowed'
            IS DISTINCT FROM 'false'::JSONB
       OR p_contract_document -> 'rule' -> 'execution_allowed'
            IS DISTINCT FROM 'false'::JSONB
       OR p_contract_document -> 'rule' -> 'approval_required'
            IS DISTINCT FROM 'true'::JSONB
       OR p_contract_document -> 'rule' -> 'ontology' ->> 'ontology_key'
            IS DISTINCT FROM 'natural-resource-one-map'
       OR p_contract_document -> 'rule' -> 'ontology' ->> 'semantic_version'
            IS DISTINCT FROM '2.3.0'
       OR p_contract_document -> 'rule' -> 'ontology' ->> 'package_id'
            IS DISTINCT FROM 'natural-resource-one-map:2.3.0:587915868b1221af'
       OR p_contract_document -> 'rule' -> 'ontology' ->> 'content_sha256'
            IS DISTINCT FROM '587915868b1221af2315508ede7bf7babced063cba8b261de2f10afa23841019'
       OR (
            p_status = 'customer_approved'
            AND (
                jsonb_typeof(p_contract_document -> 'approval_evidence') <> 'object'
                OR p_contract_document -> 'approval_evidence' ->> 'rule_id'
                    IS DISTINCT FROM p_rule_id
                OR p_contract_document -> 'approval_evidence' ->> 'rule_semantic_version'
                    IS DISTINCT FROM p_semantic_version
                OR p_contract_document -> 'approval_evidence' ->> 'rule_sha256'
                    IS DISTINCT FROM p_rule_sha256
                OR p_contract_document -> 'approval_evidence' ->> 'signature_verification_status'
                    IS DISTINCT FROM 'verified'
            )
       )
       OR (
            p_status <> 'customer_approved'
            AND jsonb_typeof(p_contract_document -> 'approval_evidence')
                IS DISTINCT FROM 'null'
       ) THEN
        RAISE EXCEPTION 'customer compensation rule contract is invalid'
            USING ERRCODE = '22023';
    END IF;

    PERFORM pg_advisory_xact_lock(
        hashtextextended(
            'customer-compensation-rule|' || p_tenant_id || '|' || p_rule_id,
            0
        )
    );

    SELECT current.* INTO v_current
    FROM gda_control.customer_compensation_rule_contract_current AS current
    WHERE current.tenant_id = p_tenant_id
      AND current.rule_id = p_rule_id;
    IF FOUND THEN
        v_current_rank := CASE v_current.status
            WHEN 'draft_unreviewed' THEN 1
            WHEN 'awaiting_customer_approval' THEN 2
            WHEN 'customer_approved' THEN 3
        END;
        v_status_rank := CASE p_status
            WHEN 'draft_unreviewed' THEN 1
            WHEN 'awaiting_customer_approval' THEN 2
            WHEN 'customer_approved' THEN 3
        END;
        IF v_status_rank < v_current_rank THEN
            RAISE EXCEPTION 'customer compensation rule lifecycle cannot regress'
                USING ERRCODE = '22023';
        END IF;
    END IF;

    SELECT stored.* INTO v_existing
    FROM gda_control.customer_compensation_rule_contract AS stored
    WHERE stored.tenant_id = p_tenant_id
      AND stored.rule_id = p_rule_id
      AND stored.contract_sha256 = p_contract_sha256;
    IF FOUND THEN
        IF v_existing.semantic_version IS DISTINCT FROM p_semantic_version
           OR v_existing.rule_sha256 IS DISTINCT FROM p_rule_sha256
           OR v_existing.status IS DISTINCT FROM p_status
           OR v_existing.contract_document IS DISTINCT FROM p_contract_document THEN
            RAISE EXCEPTION 'customer compensation rule contract idempotency differs'
                USING ERRCODE = '40001';
        END IF;
        RETURN QUERY SELECT v_existing.contract_document, FALSE;
        RETURN;
    END IF;

    PERFORM set_config(
        'gda.customer_compensation_rule_contract_write_allowed', '1', true
    );
    INSERT INTO gda_control.customer_compensation_rule_contract (
        tenant_id, rule_id, semantic_version, rule_sha256, contract_sha256,
        status, contract_document
    ) VALUES (
        p_tenant_id, p_rule_id, p_semantic_version, p_rule_sha256,
        p_contract_sha256, p_status, p_contract_document
    )
    RETURNING * INTO v_existing;
    PERFORM set_config(
        'gda.customer_compensation_rule_contract_write_allowed', '0', true
    );

    RETURN QUERY SELECT v_existing.contract_document, TRUE;
EXCEPTION WHEN OTHERS THEN
    PERFORM set_config(
        'gda.customer_compensation_rule_contract_write_allowed', '0', true
    );
    RAISE;
END;
$$;
