-- 111: Immutable provider completion receipts for security outcome reconciliation.

CREATE TABLE gda_control.security_operation_receipt (
    tenant_id TEXT NOT NULL,
    receipt_id UUID NOT NULL,
    attempt_id UUID NOT NULL,
    action TEXT NOT NULL,
    resource_ref TEXT NOT NULL,
    receipt_type TEXT NOT NULL,
    receipt_sha256 TEXT NOT NULL,
    evidence JSONB NOT NULL,
    recorded_by TEXT NOT NULL,
    recorded_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (tenant_id, receipt_id),
    CONSTRAINT uq_gda_security_operation_receipt_attempt
        UNIQUE (tenant_id, attempt_id),
    CONSTRAINT uq_gda_security_operation_receipt_sha256
        UNIQUE (tenant_id, receipt_sha256),
    CONSTRAINT ck_gda_security_operation_receipt_tenant
        CHECK (tenant_id ~ '^[a-z0-9][a-z0-9._-]{0,63}$'),
    CONSTRAINT ck_gda_security_operation_receipt_action
        CHECK (action ~ '^[a-z][a-z0-9_.:-]{1,127}$'),
    CONSTRAINT ck_gda_security_operation_receipt_resource
        CHECK (length(btrim(resource_ref)) BETWEEN 1 AND 512),
    CONSTRAINT ck_gda_security_operation_receipt_type
        CHECK (receipt_type ~ '^[a-z][a-z0-9_.:-]{1,127}$'),
    CONSTRAINT ck_gda_security_operation_receipt_sha256
        CHECK (receipt_sha256 ~ '^[0-9a-f]{64}$'),
    CONSTRAINT ck_gda_security_operation_receipt_evidence
        CHECK (jsonb_typeof(evidence) = 'object'),
    CONSTRAINT ck_gda_security_operation_receipt_actor
        CHECK (recorded_by ~ '^(human|workload|agent):[^[:space:]]+$')
);

CREATE INDEX idx_gda_security_operation_receipt_recorded_at
    ON gda_control.security_operation_receipt(tenant_id, recorded_at DESC);

CREATE OR REPLACE FUNCTION gda_control.security_operation_receipt_fingerprint(
    p_tenant_id TEXT,
    p_receipt_id UUID,
    p_attempt_id UUID,
    p_action TEXT,
    p_resource_ref TEXT,
    p_receipt_type TEXT,
    p_evidence JSONB,
    p_recorded_by TEXT,
    p_recorded_at TIMESTAMPTZ
)
RETURNS TEXT
LANGUAGE sql
IMMUTABLE
SET search_path = pg_catalog, public
AS $$
    SELECT encode(
        digest(
            convert_to(
                jsonb_build_object(
                    'tenant_id', p_tenant_id,
                    'receipt_id', p_receipt_id::text,
                    'attempt_id', p_attempt_id::text,
                    'action', p_action,
                    'resource_ref', p_resource_ref,
                    'receipt_type', p_receipt_type,
                    'evidence', p_evidence,
                    'recorded_by', p_recorded_by,
                    'recorded_at', to_char(
                        p_recorded_at AT TIME ZONE 'UTC',
                        'YYYY-MM-DD"T"HH24:MI:SS.US"Z"'
                    )
                )::text,
                'UTF8'
            ),
            'sha256'
        ),
        'hex'
    )
$$;

CREATE OR REPLACE FUNCTION gda_control.record_security_operation_receipt(
    p_tenant_id TEXT,
    p_attempt_id UUID,
    p_action TEXT,
    p_resource_ref TEXT,
    p_receipt_type TEXT,
    p_evidence JSONB,
    p_recorded_by TEXT
)
RETURNS TABLE (
    result_receipt_id UUID,
    result_receipt_sha256 TEXT,
    result_recorded_at TIMESTAMPTZ,
    result_inserted BOOLEAN
)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public, gda_control
SET row_security = on
SET TimeZone = 'UTC'
AS $$
DECLARE
    v_existing gda_control.security_operation_receipt%ROWTYPE;
    v_admission gda_control.security_event%ROWTYPE;
    v_receipt_id UUID;
    v_receipt_sha256 TEXT;
    v_recorded_at TIMESTAMPTZ;
    v_output_schema TEXT;
    v_output_table TEXT;
    v_spatial_index TEXT;
    v_expected_resource_ref TEXT;
    v_output_count BIGINT;
    v_index_valid BOOLEAN;
BEGIN
    IF gda_control.current_tenant() IS NULL
       OR p_tenant_id IS DISTINCT FROM gda_control.current_tenant() THEN
        RAISE EXCEPTION 'security receipt tenant context is missing or mismatched'
            USING ERRCODE = '42501';
    END IF;
    IF p_receipt_type <> 'gda.spatial_anonymization_receipt.v1'
       OR jsonb_typeof(p_evidence) IS DISTINCT FROM 'object'
       OR p_evidence->>'schema' IS DISTINCT FROM p_receipt_type
       OR p_evidence->>'tenant_id' IS DISTINCT FROM p_tenant_id
       OR p_evidence->>'attempt_id' IS DISTINCT FROM p_attempt_id::text
       OR p_evidence->>'action' IS DISTINCT FROM p_action
       OR p_evidence->>'status' IS DISTINCT FROM 'success' THEN
        RAISE EXCEPTION 'security receipt evidence binding is invalid'
            USING ERRCODE = '22023';
    END IF;

    v_output_schema := p_evidence->>'output_schema';
    v_output_table := p_evidence->>'output_table';
    v_spatial_index := p_evidence->>'spatial_index';
    IF v_output_schema !~ '^[^[:digit:][:space:]][^[:space:]]{0,62}$'
       OR v_output_table !~ '^[^[:digit:][:space:]][^[:space:]]{0,62}$'
       OR v_spatial_index !~ '^[^[:digit:][:space:]][^[:space:]]{0,62}$'
       OR NULLIF(p_evidence->>'output_row_count', '') IS NULL THEN
        RAISE EXCEPTION 'security receipt output evidence is invalid'
            USING ERRCODE = '22023';
    END IF;

    v_expected_resource_ref := format(
        'postgis://%s/%s->postgis://%s/%s',
        p_evidence->>'source_schema',
        p_evidence->>'source_table',
        v_output_schema,
        v_output_table
    );
    IF p_resource_ref IS DISTINCT FROM v_expected_resource_ref THEN
        RAISE EXCEPTION 'security receipt resource binding is invalid'
            USING ERRCODE = '22023';
    END IF;

    PERFORM pg_advisory_xact_lock(
        hashtextextended(
            'gda-security-receipt:' || p_tenant_id || ':' || p_attempt_id::text,
            0
        )
    );

    SELECT security_event.* INTO v_admission
    FROM gda_control.security_event AS security_event
    WHERE security_event.tenant_id = p_tenant_id
      AND security_event.attempt_id = p_attempt_id
      AND security_event.phase = 'admitted';
    IF NOT FOUND
       OR v_admission.action IS DISTINCT FROM p_action
       OR v_admission.resource_ref IS DISTINCT FROM p_resource_ref THEN
        RAISE EXCEPTION 'matching admitted security event was not found'
            USING ERRCODE = '22023';
    END IF;
    IF EXISTS (
        SELECT 1 FROM gda_control.security_event AS security_event
        WHERE security_event.tenant_id = p_tenant_id
          AND security_event.attempt_id = p_attempt_id
          AND security_event.phase = 'outcome'
    ) THEN
        RAISE EXCEPTION 'security outcome already exists'
            USING ERRCODE = '40001';
    END IF;

    IF to_regclass(format('%I.%I', v_output_schema, v_output_table)) IS NULL THEN
        RAISE EXCEPTION 'security receipt output table does not exist'
            USING ERRCODE = '22023';
    END IF;
    EXECUTE format(
        'SELECT count(*) FROM %I.%I',
        v_output_schema,
        v_output_table
    ) INTO v_output_count;
    IF v_output_count IS DISTINCT FROM (p_evidence->>'output_row_count')::BIGINT THEN
        RAISE EXCEPTION 'security receipt output row count does not match'
            USING ERRCODE = '22023';
    END IF;
    SELECT EXISTS (
        SELECT 1
        FROM pg_catalog.pg_class AS output_relation
        JOIN pg_catalog.pg_namespace AS output_namespace
          ON output_namespace.oid = output_relation.relnamespace
        JOIN pg_catalog.pg_index AS output_index
          ON output_index.indrelid = output_relation.oid
        JOIN pg_catalog.pg_class AS index_relation
          ON index_relation.oid = output_index.indexrelid
        JOIN pg_catalog.pg_am AS index_method
          ON index_method.oid = index_relation.relam
        WHERE output_namespace.nspname = v_output_schema
          AND output_relation.relname = v_output_table
          AND index_relation.relname = v_spatial_index
          AND index_method.amname = 'gist'
          AND output_index.indisvalid
          AND output_index.indisready
    ) INTO v_index_valid;
    IF NOT v_index_valid THEN
        RAISE EXCEPTION 'security receipt spatial index is missing or invalid'
            USING ERRCODE = '22023';
    END IF;

    SELECT security_operation_receipt.* INTO v_existing
    FROM gda_control.security_operation_receipt AS security_operation_receipt
    WHERE security_operation_receipt.tenant_id = p_tenant_id
      AND security_operation_receipt.attempt_id = p_attempt_id;
    IF FOUND THEN
        IF v_existing.action IS DISTINCT FROM p_action
           OR v_existing.resource_ref IS DISTINCT FROM p_resource_ref
           OR v_existing.receipt_type IS DISTINCT FROM p_receipt_type
           OR v_existing.evidence IS DISTINCT FROM p_evidence
           OR v_existing.recorded_by IS DISTINCT FROM p_recorded_by THEN
            RAISE EXCEPTION 'security receipt idempotency conflict'
                USING ERRCODE = '40001';
        END IF;
        RETURN QUERY SELECT
            v_existing.receipt_id,
            v_existing.receipt_sha256,
            v_existing.recorded_at,
            FALSE;
        RETURN;
    END IF;

    v_receipt_id := gen_random_uuid();
    v_recorded_at := clock_timestamp();
    v_receipt_sha256 := gda_control.security_operation_receipt_fingerprint(
        p_tenant_id,
        v_receipt_id,
        p_attempt_id,
        p_action,
        p_resource_ref,
        p_receipt_type,
        p_evidence,
        p_recorded_by,
        v_recorded_at
    );
    INSERT INTO gda_control.security_operation_receipt (
        tenant_id, receipt_id, attempt_id, action, resource_ref,
        receipt_type, receipt_sha256, evidence, recorded_by, recorded_at
    ) VALUES (
        p_tenant_id, v_receipt_id, p_attempt_id, p_action, p_resource_ref,
        p_receipt_type, v_receipt_sha256, p_evidence, p_recorded_by, v_recorded_at
    );
    RETURN QUERY SELECT
        v_receipt_id,
        v_receipt_sha256,
        v_recorded_at,
        TRUE;
END
$$;

CREATE OR REPLACE FUNCTION gda_control.verify_security_operation_receipts(
    p_tenant_id TEXT
)
RETURNS BOOLEAN
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public, gda_control
SET row_security = on
SET TimeZone = 'UTC'
AS $$
DECLARE
    v_valid BOOLEAN;
BEGIN
    IF gda_control.current_tenant() IS NULL
       OR p_tenant_id IS DISTINCT FROM gda_control.current_tenant() THEN
        RAISE EXCEPTION 'security receipt tenant context is missing or mismatched'
            USING ERRCODE = '42501';
    END IF;
    SELECT COALESCE(bool_and(
        receipt.receipt_sha256 = gda_control.security_operation_receipt_fingerprint(
            receipt.tenant_id,
            receipt.receipt_id,
            receipt.attempt_id,
            receipt.action,
            receipt.resource_ref,
            receipt.receipt_type,
            receipt.evidence,
            receipt.recorded_by,
            receipt.recorded_at
        )
    ), TRUE)
    INTO v_valid
    FROM gda_control.security_operation_receipt AS receipt
    WHERE receipt.tenant_id = p_tenant_id;
    RETURN v_valid;
END
$$;

DROP TRIGGER IF EXISTS trg_gda_security_operation_receipt_immutable
    ON gda_control.security_operation_receipt;
CREATE TRIGGER trg_gda_security_operation_receipt_immutable
BEFORE UPDATE OR DELETE ON gda_control.security_operation_receipt
FOR EACH ROW EXECUTE FUNCTION gda_control.reject_immutable_mutation();

ALTER TABLE gda_control.security_operation_receipt ENABLE ROW LEVEL SECURITY;
ALTER TABLE gda_control.security_operation_receipt FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation
    ON gda_control.security_operation_receipt;
CREATE POLICY tenant_isolation ON gda_control.security_operation_receipt
    USING (tenant_id = gda_control.current_tenant())
    WITH CHECK (tenant_id = gda_control.current_tenant());

REVOKE ALL ON gda_control.security_operation_receipt FROM PUBLIC;
REVOKE ALL ON gda_control.security_operation_receipt FROM gda_control_gateway;
REVOKE ALL ON FUNCTION gda_control.security_operation_receipt_fingerprint(
    text, uuid, uuid, text, text, text, jsonb, text, timestamptz
) FROM PUBLIC;
REVOKE ALL ON FUNCTION gda_control.record_security_operation_receipt(
    text, uuid, text, text, text, jsonb, text
) FROM PUBLIC;
REVOKE ALL ON FUNCTION gda_control.verify_security_operation_receipts(text)
    FROM PUBLIC;

GRANT SELECT ON gda_control.security_operation_receipt TO gda_control_gateway;
GRANT EXECUTE ON FUNCTION gda_control.record_security_operation_receipt(
    text, uuid, text, text, text, jsonb, text
) TO gda_control_gateway;
GRANT EXECUTE ON FUNCTION gda_control.verify_security_operation_receipts(text)
    TO gda_control_gateway;
