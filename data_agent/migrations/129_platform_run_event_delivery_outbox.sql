-- 129: Durable CloudEvents delivery for immutable PlatformRun status facts.
--
-- This migration is prospective: only events inserted after the trigger is
-- installed are enqueued. Endpoint URLs and credentials remain server-owned
-- worker configuration and are never persisted in the control ledger.

CREATE UNIQUE INDEX IF NOT EXISTS uq_gda_run_event_delivery_binding
    ON gda_control.platform_run_event(tenant_id, run_id, event_id);

CREATE TABLE IF NOT EXISTS gda_control.platform_run_event_delivery_outbox (
    tenant_id TEXT NOT NULL,
    delivery_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id UUID NOT NULL,
    run_event_id UUID NOT NULL,
    run_sequence_no INTEGER NOT NULL,
    channel TEXT NOT NULL,
    destination_ref TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    attempt_count INTEGER NOT NULL DEFAULT 0,
    max_attempts INTEGER NOT NULL DEFAULT 10,
    available_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    claimed_by TEXT,
    claimed_until TIMESTAMPTZ,
    last_error TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_at TIMESTAMPTZ,
    CONSTRAINT uq_gda_run_event_delivery_tenant_id
        UNIQUE (tenant_id, delivery_id),
    CONSTRAINT uq_gda_run_event_delivery
        UNIQUE (tenant_id, run_event_id, channel, destination_ref),
    CONSTRAINT fk_gda_run_event_delivery_event
        FOREIGN KEY (tenant_id, run_id, run_event_id)
        REFERENCES gda_control.platform_run_event(tenant_id, run_id, event_id),
    CONSTRAINT ck_gda_run_event_delivery_sequence
        CHECK (run_sequence_no >= 0),
    CONSTRAINT ck_gda_run_event_delivery_channel
        CHECK (channel = 'gda.platform-runs.status'),
    CONSTRAINT ck_gda_run_event_delivery_destination
        CHECK (destination_ref = 'cloudevents:platform-run-default'),
    CONSTRAINT ck_gda_run_event_delivery_status
        CHECK (status IN ('pending', 'in_flight', 'done', 'failed')),
    CONSTRAINT ck_gda_run_event_delivery_attempt_count
        CHECK (attempt_count >= 0),
    CONSTRAINT ck_gda_run_event_delivery_max_attempts
        CHECK (max_attempts BETWEEN 1 AND 100),
    CONSTRAINT ck_gda_run_event_delivery_claim_pair CHECK (
        (claimed_by IS NULL) = (claimed_until IS NULL)
    ),
    CONSTRAINT ck_gda_run_event_delivery_state CHECK (
        (status = 'pending' AND claimed_by IS NULL AND completed_at IS NULL)
        OR
        (status = 'in_flight' AND claimed_by IS NOT NULL AND completed_at IS NULL)
        OR
        (status IN ('done', 'failed')
            AND claimed_by IS NULL AND completed_at IS NOT NULL)
    )
);

CREATE INDEX IF NOT EXISTS idx_gda_run_event_delivery_due
    ON gda_control.platform_run_event_delivery_outbox(
        tenant_id, available_at, created_at, delivery_id
    )
    WHERE status IN ('pending', 'in_flight');
CREATE INDEX IF NOT EXISTS idx_gda_run_event_delivery_run
    ON gda_control.platform_run_event_delivery_outbox(
        tenant_id, run_id, run_sequence_no
    );

CREATE OR REPLACE FUNCTION gda_control.enqueue_platform_run_event_delivery()
RETURNS TRIGGER
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, gda_control
SET row_security = on
AS $$
BEGIN
    IF gda_control.current_tenant() IS NULL
       OR NEW.tenant_id IS DISTINCT FROM gda_control.current_tenant() THEN
        RAISE EXCEPTION 'platform run event delivery tenant context is missing or mismatched'
            USING ERRCODE = '42501';
    END IF;
    INSERT INTO gda_control.platform_run_event_delivery_outbox (
        tenant_id, run_id, run_event_id, run_sequence_no,
        channel, destination_ref, available_at, created_at
    ) VALUES (
        NEW.tenant_id, NEW.run_id, NEW.event_id, NEW.sequence_no,
        'gda.platform-runs.status', 'cloudevents:platform-run-default',
        NEW.occurred_at, NEW.occurred_at
    )
    ON CONFLICT (tenant_id, run_event_id, channel, destination_ref)
    DO NOTHING;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_gda_platform_run_event_delivery
    ON gda_control.platform_run_event;
CREATE TRIGGER trg_gda_platform_run_event_delivery
AFTER INSERT ON gda_control.platform_run_event
FOR EACH ROW EXECUTE FUNCTION gda_control.enqueue_platform_run_event_delivery();

ALTER TABLE gda_control.platform_run_event_delivery_outbox
    ENABLE ROW LEVEL SECURITY;
ALTER TABLE gda_control.platform_run_event_delivery_outbox
    FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation
    ON gda_control.platform_run_event_delivery_outbox;
CREATE POLICY tenant_isolation
    ON gda_control.platform_run_event_delivery_outbox
    USING (tenant_id = gda_control.current_tenant())
    WITH CHECK (tenant_id = gda_control.current_tenant());

CREATE OR REPLACE FUNCTION gda_control.claim_platform_run_event_deliveries(
    p_tenant_id TEXT,
    p_worker_id TEXT,
    p_limit INTEGER DEFAULT 10,
    p_lease_seconds INTEGER DEFAULT 60
)
RETURNS SETOF gda_control.platform_run_event_delivery_outbox
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, gda_control
SET row_security = on
AS $$
BEGIN
    IF gda_control.current_tenant() IS DISTINCT FROM p_tenant_id THEN
        RAISE EXCEPTION 'tenant context mismatch' USING ERRCODE = '42501';
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

    UPDATE gda_control.platform_run_event_delivery_outbox
       SET status = 'failed',
           claimed_by = NULL,
           claimed_until = NULL,
           last_error = COALESCE(last_error, 'worker lease expired'),
           completed_at = clock_timestamp()
     WHERE tenant_id = p_tenant_id
       AND status = 'in_flight'
       AND claimed_until <= clock_timestamp()
       AND attempt_count >= max_attempts;

    RETURN QUERY
    WITH candidates AS (
        SELECT delivery.delivery_id
        FROM gda_control.platform_run_event_delivery_outbox AS delivery
        WHERE delivery.tenant_id = p_tenant_id
          AND delivery.attempt_count < delivery.max_attempts
          AND (
              (delivery.status = 'pending'
                  AND delivery.available_at <= clock_timestamp())
              OR
              (delivery.status = 'in_flight'
                  AND delivery.claimed_until <= clock_timestamp())
          )
          AND NOT EXISTS (
              SELECT 1
              FROM gda_control.platform_run_event_delivery_outbox AS prior
              WHERE prior.tenant_id = delivery.tenant_id
                AND prior.run_id = delivery.run_id
                AND prior.channel = delivery.channel
                AND prior.destination_ref = delivery.destination_ref
                AND prior.run_sequence_no < delivery.run_sequence_no
                AND prior.status <> 'done'
          )
        ORDER BY delivery.available_at, delivery.created_at, delivery.delivery_id
        LIMIT p_limit
        FOR UPDATE SKIP LOCKED
    )
    UPDATE gda_control.platform_run_event_delivery_outbox AS delivery
       SET status = 'in_flight',
           attempt_count = delivery.attempt_count + 1,
           claimed_by = p_worker_id,
           claimed_until = clock_timestamp()
               + make_interval(secs => p_lease_seconds),
           completed_at = NULL
      FROM candidates
     WHERE delivery.tenant_id = p_tenant_id
       AND delivery.delivery_id = candidates.delivery_id
    RETURNING delivery.*;
END;
$$;

CREATE OR REPLACE FUNCTION gda_control.complete_platform_run_event_delivery(
    p_tenant_id TEXT,
    p_delivery_id UUID,
    p_worker_id TEXT
)
RETURNS SETOF gda_control.platform_run_event_delivery_outbox
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, gda_control
SET row_security = on
AS $$
BEGIN
    IF gda_control.current_tenant() IS DISTINCT FROM p_tenant_id THEN
        RAISE EXCEPTION 'tenant context mismatch' USING ERRCODE = '42501';
    END IF;
    RETURN QUERY
    UPDATE gda_control.platform_run_event_delivery_outbox AS delivery
       SET status = 'done',
           claimed_by = NULL,
           claimed_until = NULL,
           last_error = NULL,
           completed_at = clock_timestamp()
     WHERE delivery.tenant_id = p_tenant_id
       AND delivery.delivery_id = p_delivery_id
       AND delivery.status = 'in_flight'
       AND delivery.claimed_by = p_worker_id
       AND delivery.claimed_until > clock_timestamp()
    RETURNING delivery.*;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'delivery claim is missing, expired, or owned by another worker'
            USING ERRCODE = '40001';
    END IF;
END;
$$;

CREATE OR REPLACE FUNCTION gda_control.fail_platform_run_event_delivery(
    p_tenant_id TEXT,
    p_delivery_id UUID,
    p_worker_id TEXT,
    p_error TEXT,
    p_retry_delay_seconds INTEGER DEFAULT 30
)
RETURNS SETOF gda_control.platform_run_event_delivery_outbox
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, gda_control
SET row_security = on
AS $$
BEGIN
    IF gda_control.current_tenant() IS DISTINCT FROM p_tenant_id THEN
        RAISE EXCEPTION 'tenant context mismatch' USING ERRCODE = '42501';
    END IF;
    IF COALESCE(btrim(p_error), '') = '' THEN
        RAISE EXCEPTION 'failure reason is required' USING ERRCODE = '22023';
    END IF;
    IF p_retry_delay_seconds IS NULL
       OR p_retry_delay_seconds < 0 OR p_retry_delay_seconds > 86400 THEN
        RAISE EXCEPTION 'retry delay must be between 0 and 86400 seconds'
            USING ERRCODE = '22023';
    END IF;
    RETURN QUERY
    UPDATE gda_control.platform_run_event_delivery_outbox AS delivery
       SET status = CASE
               WHEN delivery.attempt_count >= delivery.max_attempts
               THEN 'failed' ELSE 'pending' END,
           claimed_by = NULL,
           claimed_until = NULL,
           last_error = left(p_error, 512),
           available_at = CASE
               WHEN delivery.attempt_count >= delivery.max_attempts
               THEN delivery.available_at
               ELSE clock_timestamp()
                   + make_interval(secs => p_retry_delay_seconds)
               END,
           completed_at = CASE
               WHEN delivery.attempt_count >= delivery.max_attempts
               THEN clock_timestamp() ELSE NULL END
     WHERE delivery.tenant_id = p_tenant_id
       AND delivery.delivery_id = p_delivery_id
       AND delivery.status = 'in_flight'
       AND delivery.claimed_by = p_worker_id
       AND delivery.claimed_until > clock_timestamp()
    RETURNING delivery.*;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'delivery claim is missing, expired, or owned by another worker'
            USING ERRCODE = '40001';
    END IF;
END;
$$;

REVOKE ALL ON TABLE gda_control.platform_run_event_delivery_outbox
    FROM PUBLIC, gda_control_gateway;
GRANT SELECT ON TABLE gda_control.platform_run_event_delivery_outbox
    TO gda_control_gateway;

REVOKE ALL ON FUNCTION gda_control.enqueue_platform_run_event_delivery()
    FROM PUBLIC;
REVOKE ALL ON FUNCTION gda_control.claim_platform_run_event_deliveries(
    TEXT, TEXT, INTEGER, INTEGER
) FROM PUBLIC;
REVOKE ALL ON FUNCTION gda_control.complete_platform_run_event_delivery(
    TEXT, UUID, TEXT
) FROM PUBLIC;
REVOKE ALL ON FUNCTION gda_control.fail_platform_run_event_delivery(
    TEXT, UUID, TEXT, TEXT, INTEGER
) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION gda_control.claim_platform_run_event_deliveries(
    TEXT, TEXT, INTEGER, INTEGER
) TO gda_control_gateway;
GRANT EXECUTE ON FUNCTION gda_control.complete_platform_run_event_delivery(
    TEXT, UUID, TEXT
) TO gda_control_gateway;
GRANT EXECUTE ON FUNCTION gda_control.fail_platform_run_event_delivery(
    TEXT, UUID, TEXT, TEXT, INTEGER
) TO gda_control_gateway;
