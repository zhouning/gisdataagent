-- 098: Tenant-scoped OpenLineage HTTP delivery outbox.
--
-- This table owns at-least-once delivery state only. The immutable binding,
-- PlatformRun and receiver remain the authorities for their own domains.

CREATE TABLE IF NOT EXISTS gda_control.metadata_fabric_lineage_outbox (
    tenant_id TEXT NOT NULL,
    delivery_id UUID PRIMARY KEY,
    binding_id UUID NOT NULL,
    resource_version_id UUID NOT NULL,
    run_id UUID NOT NULL,
    source_plan_sha256 CHAR(64) NOT NULL,
    target_name TEXT NOT NULL,
    event JSONB NOT NULL,
    event_sha256 CHAR(64) NOT NULL,
    idempotency_key CHAR(64) NOT NULL,
    actor_subject TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    attempt_count INTEGER NOT NULL DEFAULT 0,
    max_attempts INTEGER NOT NULL DEFAULT 3,
    available_at TIMESTAMPTZ NOT NULL,
    claimed_by TEXT,
    claimed_until TIMESTAMPTZ,
    last_error_code TEXT,
    response_status INTEGER,
    response_body_sha256 CHAR(64),
    receipt_sha256 CHAR(64),
    created_at TIMESTAMPTZ NOT NULL,
    completed_at TIMESTAMPTZ,
    CONSTRAINT uq_gda_lineage_delivery_tenant_id
        UNIQUE (tenant_id, delivery_id),
    CONSTRAINT uq_gda_lineage_delivery_event
        UNIQUE (tenant_id, binding_id, target_name, event_sha256),
    CONSTRAINT uq_gda_lineage_delivery_idempotency
        UNIQUE (tenant_id, idempotency_key),
    CONSTRAINT fk_gda_lineage_delivery_binding
        FOREIGN KEY (tenant_id, binding_id)
        REFERENCES gda_control.metadata_fabric_binding(tenant_id, binding_id),
    CONSTRAINT ck_gda_lineage_delivery_document CHECK (
        jsonb_typeof(event) = 'object'
        AND event->>'schemaURL'
            = 'https://openlineage.io/spec/2-0-2/OpenLineage.json#/definitions/RunEvent'
        AND event->>'eventType' = 'COMPLETE'
        AND event->'run'->>'runId' = run_id::text
    ),
    CONSTRAINT ck_gda_lineage_delivery_sha256 CHECK (
        source_plan_sha256 ~ '^[0-9a-f]{64}$'
        AND event_sha256 ~ '^[0-9a-f]{64}$'
        AND idempotency_key ~ '^[0-9a-f]{64}$'
        AND (
            response_body_sha256 IS NULL
            OR response_body_sha256 ~ '^[0-9a-f]{64}$'
        )
        AND (
            receipt_sha256 IS NULL
            OR receipt_sha256 ~ '^[0-9a-f]{64}$'
        )
    ),
    CONSTRAINT ck_gda_lineage_delivery_actor CHECK (
        actor_subject ~ '^workload:.+'
    ),
    CONSTRAINT ck_gda_lineage_delivery_status CHECK (
        status IN ('pending', 'in_flight', 'delivered', 'failed')
    ),
    CONSTRAINT ck_gda_lineage_delivery_attempts CHECK (
        attempt_count >= 0 AND max_attempts BETWEEN 1 AND 20
    ),
    CONSTRAINT ck_gda_lineage_delivery_claim CHECK (
        (claimed_by IS NULL) = (claimed_until IS NULL)
    ),
    CONSTRAINT ck_gda_lineage_delivery_error CHECK (
        last_error_code IS NULL
        OR last_error_code ~ '^[a-z0-9_]{1,64}$'
    ),
    CONSTRAINT ck_gda_lineage_delivery_response CHECK (
        (response_status IS NULL OR response_status BETWEEN 100 AND 599)
        AND (response_body_sha256 IS NULL OR response_status IS NOT NULL)
    ),
    CONSTRAINT ck_gda_lineage_delivery_state CHECK (
        (
            status = 'pending'
            AND claimed_by IS NULL
            AND completed_at IS NULL
            AND receipt_sha256 IS NULL
        )
        OR (
            status = 'in_flight'
            AND claimed_by IS NOT NULL
            AND completed_at IS NULL
            AND receipt_sha256 IS NULL
        )
        OR (
            status = 'delivered'
            AND claimed_by IS NULL
            AND completed_at IS NOT NULL
            AND last_error_code IS NULL
            AND response_status BETWEEN 200 AND 299
            AND response_body_sha256 IS NOT NULL
            AND receipt_sha256 IS NOT NULL
        )
        OR (
            status = 'failed'
            AND claimed_by IS NULL
            AND completed_at IS NOT NULL
            AND last_error_code IS NOT NULL
            AND receipt_sha256 IS NULL
        )
    )
);

CREATE INDEX IF NOT EXISTS idx_gda_lineage_delivery_due
    ON gda_control.metadata_fabric_lineage_outbox(
        tenant_id, actor_subject, available_at, created_at
    ) WHERE status = 'pending';
CREATE INDEX IF NOT EXISTS idx_gda_lineage_delivery_expired_claim
    ON gda_control.metadata_fabric_lineage_outbox(tenant_id, claimed_until)
    WHERE status = 'in_flight';
CREATE INDEX IF NOT EXISTS idx_gda_lineage_delivery_binding
    ON gda_control.metadata_fabric_lineage_outbox(
        tenant_id, binding_id, created_at
    );

ALTER TABLE gda_control.metadata_fabric_lineage_outbox
    ENABLE ROW LEVEL SECURITY;
ALTER TABLE gda_control.metadata_fabric_lineage_outbox
    FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS gda_lineage_delivery_tenant_isolation
    ON gda_control.metadata_fabric_lineage_outbox;
CREATE POLICY gda_lineage_delivery_tenant_isolation
    ON gda_control.metadata_fabric_lineage_outbox
    USING (tenant_id = gda_control.current_tenant())
    WITH CHECK (tenant_id = gda_control.current_tenant());

CREATE OR REPLACE FUNCTION gda_control.claim_metadata_fabric_lineage(
    p_tenant_id TEXT,
    p_actor_subject TEXT,
    p_worker_id TEXT,
    p_limit INTEGER DEFAULT 10,
    p_lease_seconds INTEGER DEFAULT 60
)
RETURNS SETOF gda_control.metadata_fabric_lineage_outbox
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, gda_control
SET row_security = on
AS $$
BEGIN
    IF gda_control.current_tenant() IS DISTINCT FROM p_tenant_id THEN
        RAISE EXCEPTION 'tenant context mismatch' USING ERRCODE = '42501';
    END IF;
    IF COALESCE(btrim(p_actor_subject), '') = ''
       OR p_actor_subject !~ '^workload:.+' THEN
        RAISE EXCEPTION 'lineage actor is invalid' USING ERRCODE = '22023';
    END IF;
    IF COALESCE(btrim(p_worker_id), '') = '' THEN
        RAISE EXCEPTION 'worker identity is required' USING ERRCODE = '22023';
    END IF;
    IF p_limit IS NULL OR p_limit < 1 OR p_limit > 100 THEN
        RAISE EXCEPTION 'claim limit must be between 1 and 100'
            USING ERRCODE = '22023';
    END IF;
    IF p_lease_seconds IS NULL
       OR p_lease_seconds < 5 OR p_lease_seconds > 3600 THEN
        RAISE EXCEPTION 'lease must be between 5 and 3600 seconds'
            USING ERRCODE = '22023';
    END IF;

    UPDATE gda_control.metadata_fabric_lineage_outbox
       SET status = 'failed',
           claimed_by = NULL,
           claimed_until = NULL,
           last_error_code = COALESCE(last_error_code, 'lease_expired'),
           response_status = NULL,
           response_body_sha256 = NULL,
           completed_at = clock_timestamp()
     WHERE tenant_id = p_tenant_id
       AND status = 'in_flight'
       AND claimed_until <= clock_timestamp()
       AND attempt_count >= max_attempts;

    RETURN QUERY
    WITH candidates AS (
        SELECT delivery_id
          FROM gda_control.metadata_fabric_lineage_outbox
         WHERE tenant_id = p_tenant_id
           AND actor_subject = p_actor_subject
           AND attempt_count < max_attempts
           AND (
               (status = 'pending' AND available_at <= clock_timestamp())
               OR
               (status = 'in_flight' AND claimed_until <= clock_timestamp())
           )
         ORDER BY available_at, created_at, delivery_id
         LIMIT p_limit
         FOR UPDATE SKIP LOCKED
    )
    UPDATE gda_control.metadata_fabric_lineage_outbox AS delivery
       SET status = 'in_flight',
           attempt_count = delivery.attempt_count + 1,
           claimed_by = p_worker_id,
           claimed_until = clock_timestamp()
               + make_interval(secs => p_lease_seconds),
           last_error_code = NULL,
           response_status = NULL,
           response_body_sha256 = NULL,
           completed_at = NULL
      FROM candidates
     WHERE delivery.tenant_id = p_tenant_id
       AND delivery.delivery_id = candidates.delivery_id
    RETURNING delivery.*;
END;
$$;

CREATE OR REPLACE FUNCTION gda_control.complete_metadata_fabric_lineage(
    p_tenant_id TEXT,
    p_delivery_id UUID,
    p_worker_id TEXT,
    p_response_status INTEGER,
    p_response_body_sha256 TEXT,
    p_receipt_sha256 TEXT
)
RETURNS SETOF gda_control.metadata_fabric_lineage_outbox
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, gda_control
SET row_security = on
AS $$
BEGIN
    IF gda_control.current_tenant() IS DISTINCT FROM p_tenant_id THEN
        RAISE EXCEPTION 'tenant context mismatch' USING ERRCODE = '42501';
    END IF;
    IF p_response_status < 200 OR p_response_status > 299 THEN
        RAISE EXCEPTION 'successful response must be 2xx'
            USING ERRCODE = '22023';
    END IF;
    IF p_response_body_sha256 !~ '^[0-9a-f]{64}$'
       OR p_receipt_sha256 !~ '^[0-9a-f]{64}$' THEN
        RAISE EXCEPTION 'delivery receipt fingerprint is invalid'
            USING ERRCODE = '22023';
    END IF;
    RETURN QUERY
    UPDATE gda_control.metadata_fabric_lineage_outbox AS delivery
       SET status = 'delivered',
           claimed_by = NULL,
           claimed_until = NULL,
           last_error_code = NULL,
           response_status = p_response_status,
           response_body_sha256 = p_response_body_sha256,
           receipt_sha256 = p_receipt_sha256,
           completed_at = clock_timestamp()
     WHERE delivery.tenant_id = p_tenant_id
       AND delivery.delivery_id = p_delivery_id
       AND delivery.status = 'in_flight'
       AND delivery.claimed_by = p_worker_id
       AND delivery.claimed_until > clock_timestamp()
    RETURNING delivery.*;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'lineage claim is missing, expired, or owned by another worker'
            USING ERRCODE = '40001';
    END IF;
END;
$$;

CREATE OR REPLACE FUNCTION gda_control.fail_metadata_fabric_lineage(
    p_tenant_id TEXT,
    p_delivery_id UUID,
    p_worker_id TEXT,
    p_error_code TEXT,
    p_response_status INTEGER DEFAULT NULL,
    p_retryable BOOLEAN DEFAULT true,
    p_retry_delay_seconds INTEGER DEFAULT 30
)
RETURNS SETOF gda_control.metadata_fabric_lineage_outbox
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, gda_control
SET row_security = on
AS $$
BEGIN
    IF gda_control.current_tenant() IS DISTINCT FROM p_tenant_id THEN
        RAISE EXCEPTION 'tenant context mismatch' USING ERRCODE = '42501';
    END IF;
    IF COALESCE(p_error_code, '') !~ '^[a-z0-9_]{1,64}$' THEN
        RAISE EXCEPTION 'failure code is invalid' USING ERRCODE = '22023';
    END IF;
    IF p_response_status IS NOT NULL
       AND (p_response_status < 100 OR p_response_status > 599) THEN
        RAISE EXCEPTION 'failure response status is invalid'
            USING ERRCODE = '22023';
    END IF;
    IF p_retry_delay_seconds IS NULL
       OR p_retry_delay_seconds < 0 OR p_retry_delay_seconds > 86400 THEN
        RAISE EXCEPTION 'retry delay must be between 0 and 86400 seconds'
            USING ERRCODE = '22023';
    END IF;
    RETURN QUERY
    UPDATE gda_control.metadata_fabric_lineage_outbox AS delivery
       SET status = CASE
               WHEN NOT p_retryable
                    OR delivery.attempt_count >= delivery.max_attempts
               THEN 'failed' ELSE 'pending' END,
           claimed_by = NULL,
           claimed_until = NULL,
           last_error_code = p_error_code,
           response_status = p_response_status,
           response_body_sha256 = NULL,
           available_at = CASE
               WHEN NOT p_retryable
                    OR delivery.attempt_count >= delivery.max_attempts
               THEN delivery.available_at
               ELSE clock_timestamp()
                   + make_interval(secs => p_retry_delay_seconds)
               END,
           completed_at = CASE
               WHEN NOT p_retryable
                    OR delivery.attempt_count >= delivery.max_attempts
               THEN clock_timestamp() ELSE NULL END
     WHERE delivery.tenant_id = p_tenant_id
       AND delivery.delivery_id = p_delivery_id
       AND delivery.status = 'in_flight'
       AND delivery.claimed_by = p_worker_id
       AND delivery.claimed_until > clock_timestamp()
    RETURNING delivery.*;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'lineage claim is missing, expired, or owned by another worker'
            USING ERRCODE = '40001';
    END IF;
END;
$$;

REVOKE ALL ON TABLE gda_control.metadata_fabric_lineage_outbox FROM PUBLIC;
REVOKE ALL ON TABLE gda_control.metadata_fabric_lineage_outbox
    FROM gda_control_gateway;
GRANT SELECT, INSERT ON gda_control.metadata_fabric_lineage_outbox
    TO gda_control_gateway;

REVOKE ALL ON FUNCTION gda_control.claim_metadata_fabric_lineage(
    text, text, text, integer, integer
) FROM PUBLIC;
REVOKE ALL ON FUNCTION gda_control.complete_metadata_fabric_lineage(
    text, uuid, text, integer, text, text
) FROM PUBLIC;
REVOKE ALL ON FUNCTION gda_control.fail_metadata_fabric_lineage(
    text, uuid, text, text, integer, boolean, integer
) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION gda_control.claim_metadata_fabric_lineage(
    text, text, text, integer, integer
) TO gda_control_gateway;
GRANT EXECUTE ON FUNCTION gda_control.complete_metadata_fabric_lineage(
    text, uuid, text, integer, text, text
) TO gda_control_gateway;
GRANT EXECUTE ON FUNCTION gda_control.fail_metadata_fabric_lineage(
    text, uuid, text, text, integer, boolean, integer
) TO gda_control_gateway;
