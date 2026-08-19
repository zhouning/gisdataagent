-- 166: Durable idempotency ledger for sealed Chongqing package reconciliation.

CREATE TABLE IF NOT EXISTS gda_control.chongqing_data_package_reconciliation (
    tenant_id TEXT NOT NULL,
    idempotency_key TEXT NOT NULL,
    request_sha256 CHAR(64) NOT NULL,
    recorded_by TEXT NOT NULL,
    plan_sha256 CHAR(64) NOT NULL,
    plan_document JSONB NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    receipt_sha256 CHAR(64),
    receipt_document JSONB,
    response_document JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    completed_at TIMESTAMPTZ,
    PRIMARY KEY (tenant_id, idempotency_key),
    CONSTRAINT ck_gda_cq_package_reconciliation_tenant CHECK (
        tenant_id ~ '^[a-z0-9][a-z0-9._-]{0,63}$'
    ),
    CONSTRAINT ck_gda_cq_package_reconciliation_idempotency CHECK (
        idempotency_key ~ '^[A-Za-z0-9][A-Za-z0-9._:-]{2,127}$'
    ),
    CONSTRAINT ck_gda_cq_package_reconciliation_actor CHECK (
        recorded_by ~ '^(human|workload|agent):[^[:space:]]{1,128}$'
    ),
    CONSTRAINT ck_gda_cq_package_reconciliation_hashes CHECK (
        request_sha256 ~ '^[0-9a-f]{64}$'
        AND plan_sha256 ~ '^[0-9a-f]{64}$'
        AND (receipt_sha256 IS NULL OR receipt_sha256 ~ '^[0-9a-f]{64}$')
    ),
    CONSTRAINT ck_gda_cq_package_reconciliation_documents CHECK (
        jsonb_typeof(plan_document) = 'object'
        AND (receipt_document IS NULL OR jsonb_typeof(receipt_document) = 'object')
        AND (response_document IS NULL OR jsonb_typeof(response_document) = 'object')
    ),
    CONSTRAINT ck_gda_cq_package_reconciliation_status CHECK (
        (status = 'pending'
            AND receipt_sha256 IS NULL
            AND receipt_document IS NULL
            AND response_document IS NULL
            AND completed_at IS NULL)
        OR
        (status = 'completed'
            AND receipt_sha256 IS NOT NULL
            AND receipt_document IS NOT NULL
            AND response_document IS NOT NULL
            AND completed_at IS NOT NULL)
    )
);

ALTER TABLE gda_control.chongqing_data_package_reconciliation
    ENABLE ROW LEVEL SECURITY;
ALTER TABLE gda_control.chongqing_data_package_reconciliation
    FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation
    ON gda_control.chongqing_data_package_reconciliation;
CREATE POLICY tenant_isolation
    ON gda_control.chongqing_data_package_reconciliation
    USING (tenant_id = gda_control.current_tenant())
    WITH CHECK (tenant_id = gda_control.current_tenant());

CREATE OR REPLACE FUNCTION gda_control.reserve_chongqing_data_package_reconciliation(
    p_tenant_id TEXT,
    p_idempotency_key TEXT,
    p_request_sha256 TEXT,
    p_recorded_by TEXT,
    p_plan_document JSONB
)
RETURNS JSONB
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, gda_control
AS $$
DECLARE
    v_existing gda_control.chongqing_data_package_reconciliation%ROWTYPE;
    v_plan_sha256 TEXT := p_plan_document ->> 'plan_sha256';
BEGIN
    IF gda_control.current_tenant() IS NULL
       OR p_tenant_id IS DISTINCT FROM gda_control.current_tenant() THEN
        RAISE EXCEPTION 'package reconciliation tenant context is missing or mismatched'
            USING ERRCODE = '42501';
    END IF;
    IF p_idempotency_key !~ '^[A-Za-z0-9][A-Za-z0-9._:-]{2,127}$'
       OR p_request_sha256 !~ '^[0-9a-f]{64}$'
       OR p_recorded_by !~ '^(human|workload|agent):[^[:space:]]{1,128}$'
       OR jsonb_typeof(p_plan_document) <> 'object'
       OR v_plan_sha256 !~ '^[0-9a-f]{64}$'
       OR p_plan_document ->> 'tenant_id' IS DISTINCT FROM p_tenant_id THEN
        RAISE EXCEPTION 'package reconciliation reservation is invalid'
            USING ERRCODE = '22023';
    END IF;

    PERFORM pg_advisory_xact_lock(
        hashtextextended(
            'cq-package-reconciliation|' || p_tenant_id || '|' || p_idempotency_key,
            0
        )
    );
    SELECT * INTO v_existing
    FROM gda_control.chongqing_data_package_reconciliation
    WHERE tenant_id = p_tenant_id AND idempotency_key = p_idempotency_key;

    IF FOUND THEN
        IF v_existing.request_sha256 <> p_request_sha256 THEN
            RAISE EXCEPTION 'package reconciliation idempotency key has different evidence'
                USING ERRCODE = '23505';
        END IF;
        RETURN jsonb_build_object(
            'status', v_existing.status,
            'request_sha256', v_existing.request_sha256,
            'plan_document', v_existing.plan_document,
            'response_document', v_existing.response_document
        );
    END IF;

    INSERT INTO gda_control.chongqing_data_package_reconciliation (
        tenant_id,
        idempotency_key,
        request_sha256,
        recorded_by,
        plan_sha256,
        plan_document
    ) VALUES (
        p_tenant_id,
        p_idempotency_key,
        p_request_sha256,
        p_recorded_by,
        v_plan_sha256,
        p_plan_document
    )
    RETURNING * INTO v_existing;

    RETURN jsonb_build_object(
        'status', v_existing.status,
        'request_sha256', v_existing.request_sha256,
        'plan_document', v_existing.plan_document,
        'response_document', v_existing.response_document
    );
END;
$$;

CREATE OR REPLACE FUNCTION gda_control.complete_chongqing_data_package_reconciliation(
    p_tenant_id TEXT,
    p_idempotency_key TEXT,
    p_request_sha256 TEXT,
    p_receipt_document JSONB,
    p_response_document JSONB
)
RETURNS JSONB
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, gda_control
AS $$
DECLARE
    v_existing gda_control.chongqing_data_package_reconciliation%ROWTYPE;
    v_receipt_sha256 TEXT := p_receipt_document ->> 'receipt_sha256';
BEGIN
    IF gda_control.current_tenant() IS NULL
       OR p_tenant_id IS DISTINCT FROM gda_control.current_tenant() THEN
        RAISE EXCEPTION 'package reconciliation tenant context is missing or mismatched'
            USING ERRCODE = '42501';
    END IF;
    IF p_request_sha256 !~ '^[0-9a-f]{64}$'
       OR jsonb_typeof(p_receipt_document) <> 'object'
       OR jsonb_typeof(p_response_document) <> 'object'
       OR v_receipt_sha256 !~ '^[0-9a-f]{64}$'
       OR p_receipt_document ->> 'tenant_id' IS DISTINCT FROM p_tenant_id
       OR p_response_document ->> 'tenant_id' IS DISTINCT FROM p_tenant_id
       OR p_response_document ->> 'request_sha256' IS DISTINCT FROM p_request_sha256
       OR p_response_document ->> 'receipt_sha256' IS DISTINCT FROM v_receipt_sha256 THEN
        RAISE EXCEPTION 'package reconciliation completion is invalid'
            USING ERRCODE = '22023';
    END IF;

    PERFORM pg_advisory_xact_lock(
        hashtextextended(
            'cq-package-reconciliation|' || p_tenant_id || '|' || p_idempotency_key,
            0
        )
    );
    SELECT * INTO v_existing
    FROM gda_control.chongqing_data_package_reconciliation
    WHERE tenant_id = p_tenant_id AND idempotency_key = p_idempotency_key
    FOR UPDATE;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'package reconciliation reservation was not found'
            USING ERRCODE = 'P0002';
    END IF;
    IF v_existing.request_sha256 <> p_request_sha256 THEN
        RAISE EXCEPTION 'package reconciliation idempotency key has different evidence'
            USING ERRCODE = '23505';
    END IF;
    IF v_existing.status = 'completed' THEN
        IF v_existing.receipt_document <> p_receipt_document
           OR v_existing.response_document <> p_response_document THEN
            RAISE EXCEPTION 'package reconciliation completion has different evidence'
                USING ERRCODE = '23505';
        END IF;
        RETURN v_existing.response_document;
    END IF;

    UPDATE gda_control.chongqing_data_package_reconciliation
    SET status = 'completed',
        receipt_sha256 = v_receipt_sha256,
        receipt_document = p_receipt_document,
        response_document = p_response_document,
        completed_at = clock_timestamp()
    WHERE tenant_id = p_tenant_id AND idempotency_key = p_idempotency_key
    RETURNING * INTO v_existing;

    RETURN v_existing.response_document;
END;
$$;

REVOKE ALL ON TABLE gda_control.chongqing_data_package_reconciliation
    FROM PUBLIC, gda_control_gateway;
REVOKE ALL ON FUNCTION gda_control.reserve_chongqing_data_package_reconciliation(
    TEXT, TEXT, TEXT, TEXT, JSONB
) FROM PUBLIC;
REVOKE ALL ON FUNCTION gda_control.complete_chongqing_data_package_reconciliation(
    TEXT, TEXT, TEXT, JSONB, JSONB
) FROM PUBLIC;

GRANT SELECT ON TABLE gda_control.chongqing_data_package_reconciliation
    TO gda_control_gateway;
GRANT EXECUTE ON FUNCTION gda_control.reserve_chongqing_data_package_reconciliation(
    TEXT, TEXT, TEXT, TEXT, JSONB
) TO gda_control_gateway;
GRANT EXECUTE ON FUNCTION gda_control.complete_chongqing_data_package_reconciliation(
    TEXT, TEXT, TEXT, JSONB, JSONB
) TO gda_control_gateway;
