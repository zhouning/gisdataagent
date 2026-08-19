-- 179: Append-only customer compensation rule authority.
--
-- This table records technical-baseline customer rule evidence.  It is not a
-- customer approval system and it never enables mutation execution.

CREATE TABLE IF NOT EXISTS gda_control.customer_compensation_rule_contract (
    tenant_id TEXT NOT NULL,
    rule_id TEXT NOT NULL,
    semantic_version TEXT NOT NULL,
    rule_sha256 CHAR(64) NOT NULL,
    contract_sha256 CHAR(64) NOT NULL,
    status TEXT NOT NULL,
    contract_document JSONB NOT NULL,
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (tenant_id, contract_sha256),
    CONSTRAINT uq_gda_customer_compensation_rule_contract_identity
        UNIQUE (tenant_id, rule_id, contract_sha256),
    CONSTRAINT ck_gda_customer_compensation_rule_contract_tenant
        CHECK (tenant_id ~ '^[a-z0-9][a-z0-9._-]{0,63}$'),
    CONSTRAINT ck_gda_customer_compensation_rule_contract_rule_id
        CHECK (
            rule_id ~ '^customer[.]compensation[.](corrective-forward|rollback|delete|restore|reconciliation)[.]v[1-9][0-9]*$'
        ),
    CONSTRAINT ck_gda_customer_compensation_rule_contract_semver
    CHECK (semantic_version ~ '^(0|[1-9][0-9]*)[.](0|[1-9][0-9]*)[.](0|[1-9][0-9]*)$'),
    CONSTRAINT ck_gda_customer_compensation_rule_contract_major
        CHECK (split_part(rule_id, '.v', 2) = split_part(semantic_version, '.', 1)),
    CONSTRAINT ck_gda_customer_compensation_rule_contract_status
        CHECK (status IN ('draft_unreviewed', 'awaiting_customer_approval', 'customer_approved')),
    CONSTRAINT ck_gda_customer_compensation_rule_contract_hashes
        CHECK (
            rule_sha256 ~ '^[0-9a-f]{64}$'
            AND contract_sha256 ~ '^[0-9a-f]{64}$'
        ),
    CONSTRAINT ck_gda_customer_compensation_rule_contract_document
        CHECK (
            jsonb_typeof(contract_document) = 'object'
            AND contract_document ->> 'tenant_id' = tenant_id
            AND contract_document ->> 'status' = status
            AND contract_document ->> 'contract_sha256' = contract_sha256
            AND contract_document ->> 'review_state'
                = 'technical_baseline_unreviewed'
            AND contract_document ->> 'intended_use'
                = 'assisted_precheck_not_for_production_decision'
            AND contract_document -> 'automatic_mutating_selection_allowed'
                IS DISTINCT FROM 'true'::JSONB
            AND contract_document -> 'execution_allowed'
                IS DISTINCT FROM 'true'::JSONB
            AND jsonb_typeof(contract_document -> 'rule') = 'object'
            AND contract_document -> 'rule' ->> 'rule_id' = rule_id
            AND contract_document -> 'rule' ->> 'semantic_version'
                = semantic_version
            AND contract_document -> 'rule' ->> 'rule_sha256' = rule_sha256
            AND contract_document -> 'rule' ->> 'action' = CASE rule_id
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
            AND contract_document -> 'rule' -> 'mutates_provider'
                IS NOT DISTINCT FROM (
                    CASE WHEN rule_id = 'customer.compensation.reconciliation.v1'
                         THEN 'false'::JSONB ELSE 'true'::JSONB END
                )
            AND contract_document -> 'rule' ->> 'dataset_scope'
                = 'chongqing_customer_dataset'
            AND contract_document -> 'rule' -> 'automatic_mutating_selection_allowed'
                IS DISTINCT FROM 'true'::JSONB
            AND contract_document -> 'rule' -> 'execution_allowed'
                IS DISTINCT FROM 'true'::JSONB
            AND contract_document -> 'rule' -> 'approval_required'
                = 'true'::JSONB
            AND contract_document -> 'rule' -> 'ontology' ->> 'ontology_key'
                = 'natural-resource-one-map'
            AND contract_document -> 'rule' -> 'ontology' ->> 'semantic_version'
                = '2.3.0'
            AND contract_document -> 'rule' -> 'ontology' ->> 'package_id'
                = 'natural-resource-one-map:2.3.0:587915868b1221af'
            AND contract_document -> 'rule' -> 'ontology' ->> 'content_sha256'
                = '587915868b1221af2315508ede7bf7babced063cba8b261de2f10afa23841019'
            AND (
                status <> 'customer_approved'
                OR (
                    jsonb_typeof(contract_document -> 'approval_evidence') = 'object'
                    AND contract_document -> 'approval_evidence' ->> 'rule_id' = rule_id
                    AND contract_document -> 'approval_evidence' ->> 'rule_semantic_version'
                        = semantic_version
                    AND contract_document -> 'approval_evidence' ->> 'rule_sha256'
                        = rule_sha256
                    AND contract_document -> 'approval_evidence' ->> 'signature_verification_status'
                        = 'verified'
                )
            )
            AND (
                status = 'customer_approved'
                OR jsonb_typeof(contract_document -> 'approval_evidence')
                    IS NOT DISTINCT FROM 'null'
            )
        )
);

CREATE INDEX IF NOT EXISTS idx_gda_customer_compensation_rule_contract_current
    ON gda_control.customer_compensation_rule_contract
        (tenant_id, rule_id, recorded_at DESC, contract_sha256 DESC);

CREATE OR REPLACE VIEW gda_control.customer_compensation_rule_contract_current
WITH (security_invoker = true)
AS
SELECT DISTINCT ON (tenant_id, rule_id)
       tenant_id, rule_id, semantic_version, rule_sha256, contract_sha256,
       status, contract_document, recorded_at
FROM gda_control.customer_compensation_rule_contract
ORDER BY tenant_id, rule_id, recorded_at DESC, contract_sha256 DESC;

CREATE OR REPLACE FUNCTION gda_control.guard_customer_compensation_rule_contract_insert()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    IF COALESCE(
        current_setting('gda.customer_compensation_rule_contract_write_allowed', true),
        ''
    ) <> '1' THEN
        RAISE EXCEPTION
            'use gda_control.record_customer_compensation_rule_contract()'
            USING ERRCODE = '55000';
    END IF;
    IF gda_control.current_tenant() IS NULL
       OR NEW.tenant_id IS DISTINCT FROM gda_control.current_tenant() THEN
        RAISE EXCEPTION 'customer compensation rule tenant is mismatched'
            USING ERRCODE = '42501';
    END IF;
    RETURN NEW;
END;
$$;

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

DROP TRIGGER IF EXISTS trg_gda_customer_compensation_rule_contract_insert_guard
    ON gda_control.customer_compensation_rule_contract;
CREATE TRIGGER trg_gda_customer_compensation_rule_contract_insert_guard
BEFORE INSERT ON gda_control.customer_compensation_rule_contract
FOR EACH ROW
EXECUTE FUNCTION gda_control.guard_customer_compensation_rule_contract_insert();

DROP TRIGGER IF EXISTS trg_gda_customer_compensation_rule_contract_immutable
    ON gda_control.customer_compensation_rule_contract;
CREATE TRIGGER trg_gda_customer_compensation_rule_contract_immutable
BEFORE UPDATE OR DELETE
ON gda_control.customer_compensation_rule_contract
FOR EACH ROW EXECUTE FUNCTION gda_control.reject_immutable_mutation();

ALTER TABLE gda_control.customer_compensation_rule_contract
    ENABLE ROW LEVEL SECURITY;
ALTER TABLE gda_control.customer_compensation_rule_contract
    FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation
    ON gda_control.customer_compensation_rule_contract;
CREATE POLICY tenant_isolation
    ON gda_control.customer_compensation_rule_contract
    USING (tenant_id = gda_control.current_tenant())
    WITH CHECK (tenant_id = gda_control.current_tenant());

REVOKE ALL ON TABLE
    gda_control.customer_compensation_rule_contract
    FROM PUBLIC, gda_control_gateway;
REVOKE ALL ON TABLE
    gda_control.customer_compensation_rule_contract_current
    FROM PUBLIC, gda_control_gateway;
GRANT SELECT ON TABLE
    gda_control.customer_compensation_rule_contract
    TO gda_control_gateway;
GRANT SELECT ON TABLE
    gda_control.customer_compensation_rule_contract_current
    TO gda_control_gateway;

REVOKE ALL ON FUNCTION
    gda_control.guard_customer_compensation_rule_contract_insert()
    FROM PUBLIC;
REVOKE ALL ON FUNCTION
    gda_control.record_customer_compensation_rule_contract(
        TEXT, TEXT, TEXT, TEXT, TEXT, TEXT, JSONB
    ) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION
    gda_control.record_customer_compensation_rule_contract(
        TEXT, TEXT, TEXT, TEXT, TEXT, TEXT, JSONB
    ) TO gda_control_gateway;
