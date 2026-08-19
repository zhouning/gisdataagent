-- 188: Durable CAS budget for one Chongqing five-Provider unknown resume.
--
-- A safe observation does not itself authorize repeated Provider callbacks.
-- This append-only ledger atomically consumes expected attempt count zero
-- before the sole permitted resume invocation. The gateway cannot write the
-- table directly and an already-consumed position is never replayed.

CREATE TABLE IF NOT EXISTS
    gda_control.chongqing_five_provider_unknown_resume_attempt_ledger (
    tenant_id TEXT NOT NULL,
    run_id TEXT NOT NULL,
    request_bundle_sha256 CHAR(64) NOT NULL,
    position INTEGER NOT NULL,
    attempt_number INTEGER NOT NULL,
    attempt_id UUID NOT NULL,
    prior_execution_result_sha256 CHAR(64) NOT NULL,
    reconciliation_case_sha256 CHAR(64) NOT NULL,
    action_map_sha256 CHAR(64) NOT NULL,
    action_execution_binding_sha256 CHAR(64) NOT NULL,
    target_engine TEXT NOT NULL,
    request_sha256 CHAR(64) NOT NULL,
    unknown_outcome_sha256 CHAR(64) NOT NULL,
    observation_sha256 CHAR(64) NOT NULL,
    expected_consumed_attempts INTEGER NOT NULL,
    attempt_limit INTEGER NOT NULL,
    consumed_by TEXT NOT NULL,
    requested_at TIMESTAMPTZ NOT NULL,
    request_fingerprint_sha256 CHAR(64) NOT NULL,
    receipt_sha256 CHAR(64) NOT NULL,
    request_document JSONB NOT NULL,
    receipt_document JSONB NOT NULL,
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (
        tenant_id, run_id, request_bundle_sha256, position, attempt_number
    ),
    CONSTRAINT uq_gda_chongqing_unknown_resume_attempt_id
        UNIQUE (tenant_id, attempt_id),
    CONSTRAINT uq_gda_chongqing_unknown_resume_receipt_sha
        UNIQUE (tenant_id, receipt_sha256),
    CONSTRAINT ck_gda_chongqing_unknown_resume_tenant
        CHECK (tenant_id ~ '^[a-z0-9][a-z0-9._-]{0,63}$'),
    CONSTRAINT ck_gda_chongqing_unknown_resume_run
        CHECK (octet_length(btrim(run_id)) BETWEEN 1 AND 512),
    CONSTRAINT ck_gda_chongqing_unknown_resume_position
        CHECK (position BETWEEN 0 AND 31),
    CONSTRAINT ck_gda_chongqing_unknown_resume_attempt
        CHECK (
            attempt_number = 1
            AND expected_consumed_attempts = 0
            AND attempt_limit = 1
        ),
    CONSTRAINT ck_gda_chongqing_unknown_resume_engine
        CHECK (
            target_engine IN (
                'postgis', 'vector', 'rdf', 'object_store', 'lakehouse'
            )
        ),
    CONSTRAINT ck_gda_chongqing_unknown_resume_hashes
        CHECK (
            request_bundle_sha256 ~ '^[0-9a-f]{64}$'
            AND prior_execution_result_sha256 ~ '^[0-9a-f]{64}$'
            AND reconciliation_case_sha256 ~ '^[0-9a-f]{64}$'
            AND action_map_sha256 ~ '^[0-9a-f]{64}$'
            AND action_execution_binding_sha256 ~ '^[0-9a-f]{64}$'
            AND request_sha256 ~ '^[0-9a-f]{64}$'
            AND unknown_outcome_sha256 ~ '^[0-9a-f]{64}$'
            AND observation_sha256 ~ '^[0-9a-f]{64}$'
            AND request_fingerprint_sha256 ~ '^[0-9a-f]{64}$'
            AND receipt_sha256 ~ '^[0-9a-f]{64}$'
        ),
    CONSTRAINT ck_gda_chongqing_unknown_resume_actor
        CHECK (octet_length(btrim(consumed_by)) BETWEEN 1 AND 256),
    CONSTRAINT ck_gda_chongqing_unknown_resume_request_document
        CHECK (
            jsonb_typeof(request_document) = 'object'
            AND request_document ->> 'tenant_id' = tenant_id
            AND request_document ->> 'run_id' = run_id
            AND request_document ->> 'request_bundle_sha256'
                = request_bundle_sha256
            AND (request_document ->> 'position')::INTEGER = position
            AND request_document ->> 'attempt_id' = attempt_id::TEXT
            AND request_document ->> 'prior_execution_result_sha256'
                = prior_execution_result_sha256
            AND request_document ->> 'reconciliation_case_sha256'
                = reconciliation_case_sha256
            AND request_document ->> 'action_map_sha256' = action_map_sha256
            AND request_document ->> 'action_execution_binding_sha256'
                = action_execution_binding_sha256
            AND request_document ->> 'target_engine' = target_engine
            AND request_document ->> 'request_sha256' = request_sha256
            AND request_document ->> 'unknown_outcome_sha256'
                = unknown_outcome_sha256
            AND request_document ->> 'observation_sha256' = observation_sha256
            AND (request_document ->> 'expected_consumed_attempts')::INTEGER
                = expected_consumed_attempts
            AND (request_document ->> 'attempt_limit')::INTEGER = attempt_limit
            AND request_document ->> 'consumed_by' = consumed_by
            AND (request_document ->> 'requested_at')::TIMESTAMPTZ
                = requested_at
            AND request_document ->> 'request_fingerprint_sha256'
                = request_fingerprint_sha256
            AND request_document -> 'committed_prefix_replay_allowed'
                = 'false'::JSONB
            AND request_document -> 'provider_invocation_performed'
                = 'false'::JSONB
            AND request_document -> 'production_execution_authorized'
                = 'false'::JSONB
            AND request_document ->> 'review_state'
                = 'technical_baseline_unreviewed'
            AND request_document ->> 'intended_use'
                = 'assisted_precheck_not_for_production_decision'
        ),
    CONSTRAINT ck_gda_chongqing_unknown_resume_receipt_document
        CHECK (
            jsonb_typeof(receipt_document) = 'object'
            AND receipt_document -> 'request' = request_document
            AND (receipt_document ->> 'attempt_number')::INTEGER
                = attempt_number
            AND (receipt_document ->> 'consumed_at')::TIMESTAMPTZ
                = requested_at
            AND receipt_document ->> 'receipt_sha256' = receipt_sha256
            AND receipt_document -> 'authority_write_performed' = 'true'::JSONB
            AND receipt_document -> 'provider_invocation_performed'
                = 'false'::JSONB
            AND receipt_document -> 'cross_store_transaction_performed'
                = 'false'::JSONB
            AND receipt_document -> 'production_execution_authorized'
                = 'false'::JSONB
            AND receipt_document ->> 'review_state'
                = 'technical_baseline_unreviewed'
            AND receipt_document ->> 'intended_use'
                = 'assisted_precheck_not_for_production_decision'
        )
);

CREATE INDEX IF NOT EXISTS idx_gda_chongqing_unknown_resume_attempt_current
    ON gda_control.chongqing_five_provider_unknown_resume_attempt_ledger (
        tenant_id, run_id, request_bundle_sha256, position, attempt_number DESC
    );

CREATE OR REPLACE VIEW
    gda_control.chongqing_five_provider_unknown_resume_attempt_current
WITH (security_invoker = true)
AS
SELECT DISTINCT ON (tenant_id, run_id, request_bundle_sha256, position)
       tenant_id, run_id, request_bundle_sha256, position, attempt_number,
       attempt_id, receipt_sha256, receipt_document, recorded_at
FROM gda_control.chongqing_five_provider_unknown_resume_attempt_ledger
ORDER BY tenant_id, run_id, request_bundle_sha256, position, attempt_number DESC;

CREATE OR REPLACE FUNCTION
    gda_control.guard_chongqing_five_provider_unknown_resume_attempt_insert()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    IF COALESCE(
        current_setting('gda.chongqing_unknown_resume_write_allowed', true),
        ''
    ) <> '1' THEN
        RAISE EXCEPTION
            'use consume_chongqing_five_provider_unknown_resume_attempt()'
            USING ERRCODE = '55000';
    END IF;
    IF gda_control.current_tenant() IS NULL
       OR NEW.tenant_id IS DISTINCT FROM gda_control.current_tenant() THEN
        RAISE EXCEPTION 'unknown-resume attempt tenant is mismatched'
            USING ERRCODE = '42501';
    END IF;
    RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION
    gda_control.consume_chongqing_five_provider_unknown_resume_attempt(
        p_tenant_id TEXT,
        p_run_id TEXT,
        p_request_bundle_sha256 TEXT,
        p_position INTEGER,
        p_attempt_id UUID,
        p_prior_execution_result_sha256 TEXT,
        p_reconciliation_case_sha256 TEXT,
        p_action_map_sha256 TEXT,
        p_action_execution_binding_sha256 TEXT,
        p_target_engine TEXT,
        p_request_sha256 TEXT,
        p_unknown_outcome_sha256 TEXT,
        p_observation_sha256 TEXT,
        p_expected_consumed_attempts INTEGER,
        p_attempt_limit INTEGER,
        p_consumed_by TEXT,
        p_requested_at TIMESTAMPTZ,
        p_request_fingerprint_sha256 TEXT,
        p_receipt_sha256 TEXT,
        p_request_document JSONB,
        p_receipt_document JSONB
    )
RETURNS TABLE(receipt_document JSONB)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, gda_control
SET row_security = on
AS $$
DECLARE
    v_consumed_attempts INTEGER;
    v_record
        gda_control.chongqing_five_provider_unknown_resume_attempt_ledger%ROWTYPE;
BEGIN
    IF gda_control.current_tenant() IS NULL
       OR p_tenant_id IS DISTINCT FROM gda_control.current_tenant() THEN
        RAISE EXCEPTION 'unknown-resume attempt tenant is mismatched'
            USING ERRCODE = '42501';
    END IF;
    IF p_run_id IS NULL
       OR octet_length(btrim(p_run_id)) NOT BETWEEN 1 AND 512
       OR p_request_bundle_sha256 !~ '^[0-9a-f]{64}$'
       OR p_position NOT BETWEEN 0 AND 31
       OR p_attempt_id IS NULL
       OR p_prior_execution_result_sha256 !~ '^[0-9a-f]{64}$'
       OR p_reconciliation_case_sha256 !~ '^[0-9a-f]{64}$'
       OR p_action_map_sha256 !~ '^[0-9a-f]{64}$'
       OR p_action_execution_binding_sha256 !~ '^[0-9a-f]{64}$'
       OR p_target_engine NOT IN (
            'postgis', 'vector', 'rdf', 'object_store', 'lakehouse'
       )
       OR p_request_sha256 !~ '^[0-9a-f]{64}$'
       OR p_unknown_outcome_sha256 !~ '^[0-9a-f]{64}$'
       OR p_observation_sha256 !~ '^[0-9a-f]{64}$'
       OR p_expected_consumed_attempts IS DISTINCT FROM 0
       OR p_attempt_limit IS DISTINCT FROM 1
       OR p_consumed_by IS NULL
       OR octet_length(btrim(p_consumed_by)) NOT BETWEEN 1 AND 256
       OR p_requested_at IS NULL
       OR p_request_fingerprint_sha256 !~ '^[0-9a-f]{64}$'
       OR p_receipt_sha256 !~ '^[0-9a-f]{64}$'
       OR p_request_document IS NULL
       OR jsonb_typeof(p_request_document) <> 'object'
       OR p_receipt_document IS NULL
       OR jsonb_typeof(p_receipt_document) <> 'object'
       OR p_request_document ->> 'tenant_id' IS DISTINCT FROM p_tenant_id
       OR p_request_document ->> 'run_id' IS DISTINCT FROM btrim(p_run_id)
       OR p_request_document ->> 'request_bundle_sha256'
            IS DISTINCT FROM p_request_bundle_sha256
       OR (p_request_document ->> 'position')::INTEGER
            IS DISTINCT FROM p_position
       OR p_request_document ->> 'attempt_id'
            IS DISTINCT FROM p_attempt_id::TEXT
       OR p_request_document ->> 'prior_execution_result_sha256'
            IS DISTINCT FROM p_prior_execution_result_sha256
       OR p_request_document ->> 'reconciliation_case_sha256'
            IS DISTINCT FROM p_reconciliation_case_sha256
       OR p_request_document ->> 'action_map_sha256'
            IS DISTINCT FROM p_action_map_sha256
       OR p_request_document ->> 'action_execution_binding_sha256'
            IS DISTINCT FROM p_action_execution_binding_sha256
       OR p_request_document ->> 'target_engine'
            IS DISTINCT FROM p_target_engine
       OR p_request_document ->> 'request_sha256'
            IS DISTINCT FROM p_request_sha256
       OR p_request_document ->> 'unknown_outcome_sha256'
            IS DISTINCT FROM p_unknown_outcome_sha256
       OR p_request_document ->> 'observation_sha256'
            IS DISTINCT FROM p_observation_sha256
       OR (p_request_document ->> 'expected_consumed_attempts')::INTEGER
            IS DISTINCT FROM p_expected_consumed_attempts
       OR (p_request_document ->> 'attempt_limit')::INTEGER
            IS DISTINCT FROM p_attempt_limit
       OR p_request_document ->> 'consumed_by'
            IS DISTINCT FROM btrim(p_consumed_by)
       OR (p_request_document ->> 'requested_at')::TIMESTAMPTZ
            IS DISTINCT FROM p_requested_at
       OR p_request_document ->> 'request_fingerprint_sha256'
            IS DISTINCT FROM p_request_fingerprint_sha256
       OR p_request_document -> 'committed_prefix_replay_allowed'
            IS DISTINCT FROM 'false'::JSONB
       OR p_request_document -> 'provider_invocation_performed'
            IS DISTINCT FROM 'false'::JSONB
       OR p_request_document -> 'production_execution_authorized'
            IS DISTINCT FROM 'false'::JSONB
       OR p_receipt_document -> 'request' IS DISTINCT FROM p_request_document
       OR (p_receipt_document ->> 'attempt_number')::INTEGER
            IS DISTINCT FROM 1
       OR (p_receipt_document ->> 'consumed_at')::TIMESTAMPTZ
            IS DISTINCT FROM p_requested_at
       OR p_receipt_document ->> 'receipt_sha256'
            IS DISTINCT FROM p_receipt_sha256
       OR p_receipt_document -> 'authority_write_performed'
            IS DISTINCT FROM 'true'::JSONB
       OR p_receipt_document -> 'provider_invocation_performed'
            IS DISTINCT FROM 'false'::JSONB
       OR p_receipt_document -> 'cross_store_transaction_performed'
            IS DISTINCT FROM 'false'::JSONB
       OR p_receipt_document -> 'production_execution_authorized'
            IS DISTINCT FROM 'false'::JSONB THEN
        RAISE EXCEPTION 'unknown-resume attempt evidence is invalid'
            USING ERRCODE = '22023';
    END IF;

    PERFORM pg_advisory_xact_lock(
        hashtextextended(
            'chongqing-unknown-resume|' || p_tenant_id || '|' ||
            btrim(p_run_id) || '|' || p_request_bundle_sha256 || '|' ||
            p_position::TEXT,
            0
        )
    );

    SELECT count(*)::INTEGER INTO v_consumed_attempts
    FROM gda_control.chongqing_five_provider_unknown_resume_attempt_ledger
    WHERE tenant_id = p_tenant_id
      AND run_id = btrim(p_run_id)
      AND request_bundle_sha256 = p_request_bundle_sha256
      AND position = p_position;
    IF v_consumed_attempts IS DISTINCT FROM p_expected_consumed_attempts
       OR v_consumed_attempts >= p_attempt_limit THEN
        RAISE EXCEPTION
            'unknown-resume attempt budget predecessor is stale or exhausted'
            USING ERRCODE = '40001';
    END IF;

    PERFORM set_config(
        'gda.chongqing_unknown_resume_write_allowed', '1', true
    );
    INSERT INTO
        gda_control.chongqing_five_provider_unknown_resume_attempt_ledger (
        tenant_id, run_id, request_bundle_sha256, position, attempt_number,
        attempt_id, prior_execution_result_sha256,
        reconciliation_case_sha256, action_map_sha256,
        action_execution_binding_sha256, target_engine, request_sha256,
        unknown_outcome_sha256, observation_sha256,
        expected_consumed_attempts, attempt_limit, consumed_by, requested_at,
        request_fingerprint_sha256, receipt_sha256, request_document,
        receipt_document
    ) VALUES (
        p_tenant_id, btrim(p_run_id), p_request_bundle_sha256, p_position, 1,
        p_attempt_id, p_prior_execution_result_sha256,
        p_reconciliation_case_sha256, p_action_map_sha256,
        p_action_execution_binding_sha256, p_target_engine, p_request_sha256,
        p_unknown_outcome_sha256, p_observation_sha256,
        p_expected_consumed_attempts, p_attempt_limit, btrim(p_consumed_by),
        p_requested_at, p_request_fingerprint_sha256, p_receipt_sha256,
        p_request_document, p_receipt_document
    )
    RETURNING * INTO v_record;
    PERFORM set_config(
        'gda.chongqing_unknown_resume_write_allowed', '0', true
    );

    RETURN QUERY SELECT v_record.receipt_document;
EXCEPTION WHEN OTHERS THEN
    PERFORM set_config(
        'gda.chongqing_unknown_resume_write_allowed', '0', true
    );
    RAISE;
END;
$$;

DROP TRIGGER IF EXISTS trg_gda_chongqing_unknown_resume_attempt_insert_guard
    ON gda_control.chongqing_five_provider_unknown_resume_attempt_ledger;
CREATE TRIGGER trg_gda_chongqing_unknown_resume_attempt_insert_guard
BEFORE INSERT
ON gda_control.chongqing_five_provider_unknown_resume_attempt_ledger
FOR EACH ROW
EXECUTE FUNCTION
    gda_control.guard_chongqing_five_provider_unknown_resume_attempt_insert();

DROP TRIGGER IF EXISTS trg_gda_chongqing_unknown_resume_attempt_immutable
    ON gda_control.chongqing_five_provider_unknown_resume_attempt_ledger;
CREATE TRIGGER trg_gda_chongqing_unknown_resume_attempt_immutable
BEFORE UPDATE OR DELETE
ON gda_control.chongqing_five_provider_unknown_resume_attempt_ledger
FOR EACH ROW EXECUTE FUNCTION gda_control.reject_immutable_mutation();

ALTER TABLE gda_control.chongqing_five_provider_unknown_resume_attempt_ledger
    ENABLE ROW LEVEL SECURITY;
ALTER TABLE gda_control.chongqing_five_provider_unknown_resume_attempt_ledger
    FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation
    ON gda_control.chongqing_five_provider_unknown_resume_attempt_ledger;
CREATE POLICY tenant_isolation
    ON gda_control.chongqing_five_provider_unknown_resume_attempt_ledger
    USING (tenant_id = gda_control.current_tenant())
    WITH CHECK (tenant_id = gda_control.current_tenant());

REVOKE ALL ON TABLE
    gda_control.chongqing_five_provider_unknown_resume_attempt_ledger
    FROM PUBLIC, gda_control_gateway;
REVOKE ALL ON TABLE
    gda_control.chongqing_five_provider_unknown_resume_attempt_current
    FROM PUBLIC, gda_control_gateway;
GRANT SELECT ON TABLE
    gda_control.chongqing_five_provider_unknown_resume_attempt_ledger
    TO gda_control_gateway;
GRANT SELECT ON TABLE
    gda_control.chongqing_five_provider_unknown_resume_attempt_current
    TO gda_control_gateway;

REVOKE ALL ON FUNCTION
    gda_control.consume_chongqing_five_provider_unknown_resume_attempt(
        TEXT, TEXT, TEXT, INTEGER, UUID, TEXT, TEXT, TEXT, TEXT, TEXT,
        TEXT, TEXT, TEXT, INTEGER, INTEGER, TEXT, TIMESTAMPTZ, TEXT,
        TEXT, JSONB, JSONB
    ) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION
    gda_control.consume_chongqing_five_provider_unknown_resume_attempt(
        TEXT, TEXT, TEXT, INTEGER, UUID, TEXT, TEXT, TEXT, TEXT, TEXT,
        TEXT, TEXT, TEXT, INTEGER, INTEGER, TEXT, TIMESTAMPTZ, TEXT,
        TEXT, JSONB, JSONB
    ) TO gda_control_gateway;
