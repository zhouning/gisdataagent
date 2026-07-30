-- 099: Transactional outbox for authoritative ResourceVersion changes.
--
-- The ResourceVersion remains authoritative. This table owns only delivery of
-- its content-bound MetadataChangeEvent to the Active Metadata router.

CREATE TABLE IF NOT EXISTS gda_control.metadata_change_outbox (
    tenant_id TEXT NOT NULL,
    event_id UUID PRIMARY KEY,
    event_type TEXT NOT NULL,
    resource_urn TEXT NOT NULL,
    resource_version_id UUID NOT NULL,
    version_key TEXT NOT NULL,
    predecessor_version_id UUID,
    content_sha256 CHAR(64) NOT NULL,
    producer_subject TEXT NOT NULL,
    consumer_subject TEXT NOT NULL,
    occurred_at TIMESTAMPTZ NOT NULL,
    event JSONB NOT NULL,
    event_sha256 CHAR(64) NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    attempt_count INTEGER NOT NULL DEFAULT 0,
    max_attempts INTEGER NOT NULL DEFAULT 5,
    available_at TIMESTAMPTZ NOT NULL,
    claimed_by TEXT,
    claimed_until TIMESTAMPTZ,
    last_error_code TEXT,
    activation_intent_sha256 CHAR(64),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_at TIMESTAMPTZ,
    CONSTRAINT uq_gda_metadata_change_tenant_event
        UNIQUE (tenant_id, event_id),
    CONSTRAINT uq_gda_metadata_change_version_type
        UNIQUE (tenant_id, resource_version_id, event_type),
    CONSTRAINT uq_gda_metadata_change_sha
        UNIQUE (tenant_id, event_sha256),
    CONSTRAINT fk_gda_metadata_change_version
        FOREIGN KEY (
            tenant_id, resource_urn, resource_version_id, content_sha256
        ) REFERENCES gda_control.resource_version(
            tenant_id, resource_urn, resource_version_id, content_sha256
        ),
    CONSTRAINT ck_gda_metadata_change_type CHECK (
        event_type = 'resource_version.registered'
    ),
    CONSTRAINT ck_gda_metadata_change_subjects CHECK (
        producer_subject ~ '^(human|workload|agent):.+'
        AND consumer_subject ~ '^workload:.+'
    ),
    CONSTRAINT ck_gda_metadata_change_event_document CHECK (
        jsonb_typeof(event) = 'object'
        AND event ?& ARRAY[
            'schema', 'event_id', 'event_type', 'tenant_id',
            'resource_urn', 'resource_version_id', 'version_key',
            'predecessor_version_id', 'content_sha256',
            'producer_subject', 'consumer_subject', 'occurred_at',
            'event_sha256'
        ]
        AND event - ARRAY[
            'schema', 'event_id', 'event_type', 'tenant_id',
            'resource_urn', 'resource_version_id', 'version_key',
            'predecessor_version_id', 'content_sha256',
            'producer_subject', 'consumer_subject', 'occurred_at',
            'event_sha256'
        ] = '{}'::jsonb
        AND event->>'schema' = 'gda.metadata_change_event.v1'
        AND event->>'event_id' = event_id::text
        AND event->>'event_type' = event_type
        AND event->>'tenant_id' = tenant_id
        AND event->>'resource_urn' = resource_urn
        AND event->>'resource_version_id' = resource_version_id::text
        AND event->>'version_key' = version_key
        AND event->>'predecessor_version_id'
            IS NOT DISTINCT FROM predecessor_version_id::text
        AND event->>'content_sha256' = content_sha256
        AND event->>'producer_subject' = producer_subject
        AND event->>'consumer_subject' = consumer_subject
        AND (event->>'occurred_at')::timestamptz = occurred_at
        AND event->>'event_sha256' = event_sha256
    ),
    CONSTRAINT ck_gda_metadata_change_sha256 CHECK (
        content_sha256 ~ '^[0-9a-f]{64}$'
        AND event_sha256 ~ '^[0-9a-f]{64}$'
        AND (
            activation_intent_sha256 IS NULL
            OR activation_intent_sha256 ~ '^[0-9a-f]{64}$'
        )
    ),
    CONSTRAINT ck_gda_metadata_change_status CHECK (
        status IN ('pending', 'in_flight', 'processed', 'failed')
    ),
    CONSTRAINT ck_gda_metadata_change_attempts CHECK (
        attempt_count >= 0 AND max_attempts BETWEEN 1 AND 20
    ),
    CONSTRAINT ck_gda_metadata_change_claim CHECK (
        (claimed_by IS NULL) = (claimed_until IS NULL)
    ),
    CONSTRAINT ck_gda_metadata_change_error CHECK (
        last_error_code IS NULL
        OR last_error_code ~ '^[a-z0-9_]{1,64}$'
    ),
    CONSTRAINT ck_gda_metadata_change_state CHECK (
        (
            status = 'pending'
            AND claimed_by IS NULL
            AND completed_at IS NULL
            AND activation_intent_sha256 IS NULL
        )
        OR (
            status = 'in_flight'
            AND claimed_by IS NOT NULL
            AND completed_at IS NULL
            AND activation_intent_sha256 IS NULL
        )
        OR (
            status = 'processed'
            AND claimed_by IS NULL
            AND completed_at IS NOT NULL
            AND last_error_code IS NULL
            AND activation_intent_sha256 IS NOT NULL
        )
        OR (
            status = 'failed'
            AND claimed_by IS NULL
            AND completed_at IS NOT NULL
            AND last_error_code IS NOT NULL
            AND activation_intent_sha256 IS NULL
        )
    )
);

CREATE INDEX IF NOT EXISTS idx_gda_metadata_change_due
    ON gda_control.metadata_change_outbox(
        tenant_id, consumer_subject, available_at, occurred_at
    ) WHERE status = 'pending';
CREATE INDEX IF NOT EXISTS idx_gda_metadata_change_expired_claim
    ON gda_control.metadata_change_outbox(tenant_id, claimed_until)
    WHERE status = 'in_flight';
CREATE INDEX IF NOT EXISTS idx_gda_metadata_change_resource
    ON gda_control.metadata_change_outbox(
        tenant_id, resource_urn, occurred_at DESC
    );

ALTER TABLE gda_control.metadata_change_outbox ENABLE ROW LEVEL SECURITY;
ALTER TABLE gda_control.metadata_change_outbox FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS gda_metadata_change_tenant_isolation
    ON gda_control.metadata_change_outbox;
CREATE POLICY gda_metadata_change_tenant_isolation
    ON gda_control.metadata_change_outbox
    USING (tenant_id = gda_control.current_tenant())
    WITH CHECK (tenant_id = gda_control.current_tenant());

CREATE OR REPLACE FUNCTION gda_control.claim_metadata_changes(
    p_tenant_id TEXT,
    p_consumer_subject TEXT,
    p_worker_id TEXT,
    p_limit INTEGER DEFAULT 10,
    p_lease_seconds INTEGER DEFAULT 60
)
RETURNS SETOF gda_control.metadata_change_outbox
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, gda_control
SET row_security = on
AS $$
BEGIN
    IF gda_control.current_tenant() IS DISTINCT FROM p_tenant_id THEN
        RAISE EXCEPTION 'tenant context mismatch' USING ERRCODE = '42501';
    END IF;
    IF COALESCE(btrim(p_consumer_subject), '') = ''
       OR p_consumer_subject !~ '^workload:.+' THEN
        RAISE EXCEPTION 'metadata change consumer is invalid'
            USING ERRCODE = '22023';
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

    UPDATE gda_control.metadata_change_outbox
       SET status = 'failed',
           claimed_by = NULL,
           claimed_until = NULL,
           last_error_code = COALESCE(last_error_code, 'lease_expired'),
           completed_at = clock_timestamp()
     WHERE tenant_id = p_tenant_id
       AND status = 'in_flight'
       AND claimed_until <= clock_timestamp()
       AND attempt_count >= max_attempts;

    RETURN QUERY
    WITH candidates AS (
        SELECT event_id
          FROM gda_control.metadata_change_outbox
         WHERE tenant_id = p_tenant_id
           AND consumer_subject = p_consumer_subject
           AND attempt_count < max_attempts
           AND (
               (status = 'pending' AND available_at <= clock_timestamp())
               OR
               (status = 'in_flight' AND claimed_until <= clock_timestamp())
           )
         ORDER BY available_at, occurred_at, event_id
         LIMIT p_limit
         FOR UPDATE SKIP LOCKED
    )
    UPDATE gda_control.metadata_change_outbox AS delivery
       SET status = 'in_flight',
           attempt_count = delivery.attempt_count + 1,
           claimed_by = p_worker_id,
           claimed_until = clock_timestamp()
               + make_interval(secs => p_lease_seconds),
           last_error_code = NULL,
           completed_at = NULL
      FROM candidates
     WHERE delivery.tenant_id = p_tenant_id
       AND delivery.event_id = candidates.event_id
    RETURNING delivery.*;
END;
$$;

CREATE OR REPLACE FUNCTION gda_control.complete_metadata_change(
    p_tenant_id TEXT,
    p_event_id UUID,
    p_worker_id TEXT,
    p_activation_intent_sha256 TEXT
)
RETURNS SETOF gda_control.metadata_change_outbox
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, gda_control
SET row_security = on
AS $$
BEGIN
    IF gda_control.current_tenant() IS DISTINCT FROM p_tenant_id THEN
        RAISE EXCEPTION 'tenant context mismatch' USING ERRCODE = '42501';
    END IF;
    IF p_activation_intent_sha256 !~ '^[0-9a-f]{64}$' THEN
        RAISE EXCEPTION 'activation intent fingerprint is invalid'
            USING ERRCODE = '22023';
    END IF;
    RETURN QUERY
    UPDATE gda_control.metadata_change_outbox AS delivery
       SET status = 'processed',
           claimed_by = NULL,
           claimed_until = NULL,
           last_error_code = NULL,
           activation_intent_sha256 = p_activation_intent_sha256,
           completed_at = clock_timestamp()
     WHERE delivery.tenant_id = p_tenant_id
       AND delivery.event_id = p_event_id
       AND delivery.status = 'in_flight'
       AND delivery.claimed_by = p_worker_id
       AND delivery.claimed_until > clock_timestamp()
    RETURNING delivery.*;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'metadata change claim is missing, expired, or owned by another worker'
            USING ERRCODE = '40001';
    END IF;
END;
$$;

CREATE OR REPLACE FUNCTION gda_control.fail_metadata_change(
    p_tenant_id TEXT,
    p_event_id UUID,
    p_worker_id TEXT,
    p_error_code TEXT,
    p_retryable BOOLEAN DEFAULT true,
    p_retry_delay_seconds INTEGER DEFAULT 30
)
RETURNS SETOF gda_control.metadata_change_outbox
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
    IF p_retry_delay_seconds IS NULL
       OR p_retry_delay_seconds < 0 OR p_retry_delay_seconds > 86400 THEN
        RAISE EXCEPTION 'retry delay must be between 0 and 86400 seconds'
            USING ERRCODE = '22023';
    END IF;
    RETURN QUERY
    UPDATE gda_control.metadata_change_outbox AS delivery
       SET status = CASE
               WHEN NOT p_retryable
                    OR delivery.attempt_count >= delivery.max_attempts
               THEN 'failed' ELSE 'pending' END,
           claimed_by = NULL,
           claimed_until = NULL,
           last_error_code = p_error_code,
           activation_intent_sha256 = NULL,
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
       AND delivery.event_id = p_event_id
       AND delivery.status = 'in_flight'
       AND delivery.claimed_by = p_worker_id
       AND delivery.claimed_until > clock_timestamp()
    RETURNING delivery.*;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'metadata change claim is missing, expired, or owned by another worker'
            USING ERRCODE = '40001';
    END IF;
END;
$$;

REVOKE ALL ON TABLE gda_control.metadata_change_outbox FROM PUBLIC;
REVOKE ALL ON TABLE gda_control.metadata_change_outbox
    FROM gda_control_gateway;
GRANT SELECT, INSERT ON gda_control.metadata_change_outbox
    TO gda_control_gateway;

REVOKE ALL ON FUNCTION gda_control.claim_metadata_changes(
    text, text, text, integer, integer
) FROM PUBLIC;
REVOKE ALL ON FUNCTION gda_control.complete_metadata_change(
    text, uuid, text, text
) FROM PUBLIC;
REVOKE ALL ON FUNCTION gda_control.fail_metadata_change(
    text, uuid, text, text, boolean, integer
) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION gda_control.claim_metadata_changes(
    text, text, text, integer, integer
) TO gda_control_gateway;
GRANT EXECUTE ON FUNCTION gda_control.complete_metadata_change(
    text, uuid, text, text
) TO gda_control_gateway;
GRANT EXECUTE ON FUNCTION gda_control.fail_metadata_change(
    text, uuid, text, text, boolean, integer
) TO gda_control_gateway;
