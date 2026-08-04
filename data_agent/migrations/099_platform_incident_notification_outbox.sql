-- 099: Durable external delivery for governed DataIncident lifecycle events.
--
-- The outbox stores only a logical destination reference. Endpoint URLs and
-- credentials remain server-side worker configuration. Delivery is at least
-- once; stable Alertmanager labels make replay idempotent at the receiver.

CREATE UNIQUE INDEX IF NOT EXISTS uq_gda_data_incident_event_binding
    ON gda_control.data_incident_event(tenant_id, incident_id, event_id);

CREATE TABLE IF NOT EXISTS gda_control.data_incident_notification_outbox (
    tenant_id TEXT NOT NULL,
    notification_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    incident_id UUID NOT NULL,
    incident_event_id UUID NOT NULL,
    incident_sequence_no INTEGER NOT NULL,
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
    CONSTRAINT uq_gda_incident_notification_tenant_id
        UNIQUE (tenant_id, notification_id),
    CONSTRAINT uq_gda_incident_notification_delivery
        UNIQUE (tenant_id, incident_event_id, channel, destination_ref),
    CONSTRAINT fk_gda_incident_notification_incident
        FOREIGN KEY (tenant_id, incident_id)
        REFERENCES gda_control.data_incident(tenant_id, incident_id),
    CONSTRAINT fk_gda_incident_notification_event
        FOREIGN KEY (tenant_id, incident_id, incident_event_id)
        REFERENCES gda_control.data_incident_event(tenant_id, incident_id, event_id),
    CONSTRAINT ck_gda_incident_notification_sequence
        CHECK (incident_sequence_no >= 0),
    CONSTRAINT ck_gda_incident_notification_channel
        CHECK (channel = 'alertmanager'),
    CONSTRAINT ck_gda_incident_notification_destination
        CHECK (destination_ref ~ '^alertmanager:[a-zA-Z0-9._-]{1,96}$'),
    CONSTRAINT ck_gda_incident_notification_status
        CHECK (status IN ('pending', 'in_flight', 'done', 'failed')),
    CONSTRAINT ck_gda_incident_notification_attempt_count
        CHECK (attempt_count >= 0),
    CONSTRAINT ck_gda_incident_notification_max_attempts
        CHECK (max_attempts BETWEEN 1 AND 100),
    CONSTRAINT ck_gda_incident_notification_claim_pair CHECK (
        (claimed_by IS NULL) = (claimed_until IS NULL)
    ),
    CONSTRAINT ck_gda_incident_notification_delivery_state CHECK (
        (status = 'pending' AND claimed_by IS NULL AND completed_at IS NULL)
        OR
        (status = 'in_flight' AND claimed_by IS NOT NULL AND completed_at IS NULL)
        OR
        (status IN ('done', 'failed')
            AND claimed_by IS NULL AND completed_at IS NOT NULL)
    )
);

CREATE INDEX IF NOT EXISTS idx_gda_incident_notification_due
    ON gda_control.data_incident_notification_outbox(
        tenant_id, available_at, created_at, notification_id
    )
    WHERE status IN ('pending', 'in_flight');
CREATE INDEX IF NOT EXISTS idx_gda_incident_notification_incident
    ON gda_control.data_incident_notification_outbox(
        tenant_id, incident_id, incident_sequence_no
    );

CREATE OR REPLACE FUNCTION gda_control.enqueue_data_incident_notification()
RETURNS TRIGGER
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, gda_control
SET row_security = on
AS $$
BEGIN
    IF gda_control.current_tenant() IS NULL
       OR NEW.tenant_id IS DISTINCT FROM gda_control.current_tenant() THEN
        RAISE EXCEPTION 'data incident notification tenant context is missing or mismatched'
            USING ERRCODE = '42501';
    END IF;
    INSERT INTO gda_control.data_incident_notification_outbox (
        tenant_id, incident_id, incident_event_id, incident_sequence_no,
        channel, destination_ref, available_at, created_at
    ) VALUES (
        NEW.tenant_id, NEW.incident_id, NEW.event_id, NEW.sequence_no,
        'alertmanager', 'alertmanager:default', NEW.occurred_at, NEW.occurred_at
    )
    ON CONFLICT (tenant_id, incident_event_id, channel, destination_ref)
    DO NOTHING;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_gda_data_incident_notification
    ON gda_control.data_incident_event;
CREATE TRIGGER trg_gda_data_incident_notification
AFTER INSERT ON gda_control.data_incident_event
FOR EACH ROW EXECUTE FUNCTION gda_control.enqueue_data_incident_notification();

-- Existing incidents did not have a notification trigger. Backfill only the
-- latest lifecycle event so deployment does not replay obsolete open states.
INSERT INTO gda_control.data_incident_notification_outbox (
    tenant_id, incident_id, incident_event_id, incident_sequence_no,
    channel, destination_ref, available_at, created_at
)
SELECT event.tenant_id, event.incident_id, event.event_id, event.sequence_no,
       'alertmanager', 'alertmanager:default', event.occurred_at, event.occurred_at
FROM gda_control.data_incident_event AS event
JOIN (
    SELECT tenant_id, incident_id, max(sequence_no) AS sequence_no
    FROM gda_control.data_incident_event
    GROUP BY tenant_id, incident_id
) AS latest
  ON latest.tenant_id = event.tenant_id
 AND latest.incident_id = event.incident_id
 AND latest.sequence_no = event.sequence_no
ON CONFLICT (tenant_id, incident_event_id, channel, destination_ref)
DO NOTHING;

ALTER TABLE gda_control.data_incident_notification_outbox
    ENABLE ROW LEVEL SECURITY;
ALTER TABLE gda_control.data_incident_notification_outbox
    FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation
    ON gda_control.data_incident_notification_outbox;
CREATE POLICY tenant_isolation
    ON gda_control.data_incident_notification_outbox
    USING (tenant_id = gda_control.current_tenant())
    WITH CHECK (tenant_id = gda_control.current_tenant());

CREATE OR REPLACE FUNCTION gda_control.claim_data_incident_notifications(
    p_tenant_id TEXT,
    p_worker_id TEXT,
    p_limit INTEGER DEFAULT 10,
    p_lease_seconds INTEGER DEFAULT 60
)
RETURNS SETOF gda_control.data_incident_notification_outbox
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

    UPDATE gda_control.data_incident_notification_outbox
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
        SELECT notification.notification_id
        FROM gda_control.data_incident_notification_outbox AS notification
        WHERE notification.tenant_id = p_tenant_id
          AND notification.attempt_count < notification.max_attempts
          AND (
              (notification.status = 'pending'
                  AND notification.available_at <= clock_timestamp())
              OR
              (notification.status = 'in_flight'
                  AND notification.claimed_until <= clock_timestamp())
          )
          AND NOT EXISTS (
              SELECT 1
              FROM gda_control.data_incident_notification_outbox AS prior
              WHERE prior.tenant_id = notification.tenant_id
                AND prior.incident_id = notification.incident_id
                AND prior.channel = notification.channel
                AND prior.destination_ref = notification.destination_ref
                AND prior.incident_sequence_no < notification.incident_sequence_no
                AND prior.status <> 'done'
          )
        ORDER BY notification.available_at,
                 notification.created_at,
                 notification.notification_id
        LIMIT p_limit
        FOR UPDATE SKIP LOCKED
    )
    UPDATE gda_control.data_incident_notification_outbox AS notification
       SET status = 'in_flight',
           attempt_count = notification.attempt_count + 1,
           claimed_by = p_worker_id,
           claimed_until = clock_timestamp()
               + make_interval(secs => p_lease_seconds),
           completed_at = NULL
      FROM candidates
     WHERE notification.tenant_id = p_tenant_id
       AND notification.notification_id = candidates.notification_id
    RETURNING notification.*;
END;
$$;

CREATE OR REPLACE FUNCTION gda_control.complete_data_incident_notification(
    p_tenant_id TEXT,
    p_notification_id UUID,
    p_worker_id TEXT
)
RETURNS SETOF gda_control.data_incident_notification_outbox
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
    UPDATE gda_control.data_incident_notification_outbox AS notification
       SET status = 'done',
           claimed_by = NULL,
           claimed_until = NULL,
           last_error = NULL,
           completed_at = clock_timestamp()
     WHERE notification.tenant_id = p_tenant_id
       AND notification.notification_id = p_notification_id
       AND notification.status = 'in_flight'
       AND notification.claimed_by = p_worker_id
       AND notification.claimed_until > clock_timestamp()
    RETURNING notification.*;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'notification claim is missing, expired, or owned by another worker'
            USING ERRCODE = '40001';
    END IF;
END;
$$;

CREATE OR REPLACE FUNCTION gda_control.fail_data_incident_notification(
    p_tenant_id TEXT,
    p_notification_id UUID,
    p_worker_id TEXT,
    p_error TEXT,
    p_retry_delay_seconds INTEGER DEFAULT 30
)
RETURNS SETOF gda_control.data_incident_notification_outbox
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
    UPDATE gda_control.data_incident_notification_outbox AS notification
       SET status = CASE
               WHEN notification.attempt_count >= notification.max_attempts
               THEN 'failed' ELSE 'pending' END,
           claimed_by = NULL,
           claimed_until = NULL,
           last_error = left(p_error, 512),
           available_at = CASE
               WHEN notification.attempt_count >= notification.max_attempts
               THEN notification.available_at
               ELSE clock_timestamp()
                   + make_interval(secs => p_retry_delay_seconds)
               END,
           completed_at = CASE
               WHEN notification.attempt_count >= notification.max_attempts
               THEN clock_timestamp() ELSE NULL END
     WHERE notification.tenant_id = p_tenant_id
       AND notification.notification_id = p_notification_id
       AND notification.status = 'in_flight'
       AND notification.claimed_by = p_worker_id
       AND notification.claimed_until > clock_timestamp()
    RETURNING notification.*;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'notification claim is missing, expired, or owned by another worker'
            USING ERRCODE = '40001';
    END IF;
END;
$$;

REVOKE ALL ON TABLE gda_control.data_incident_notification_outbox
    FROM PUBLIC, gda_control_gateway;
GRANT SELECT ON TABLE gda_control.data_incident_notification_outbox
    TO gda_control_gateway;

REVOKE ALL ON FUNCTION gda_control.enqueue_data_incident_notification()
    FROM PUBLIC;
REVOKE ALL ON FUNCTION gda_control.claim_data_incident_notifications(
    TEXT, TEXT, INTEGER, INTEGER
) FROM PUBLIC;
REVOKE ALL ON FUNCTION gda_control.complete_data_incident_notification(
    TEXT, UUID, TEXT
) FROM PUBLIC;
REVOKE ALL ON FUNCTION gda_control.fail_data_incident_notification(
    TEXT, UUID, TEXT, TEXT, INTEGER
) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION gda_control.claim_data_incident_notifications(
    TEXT, TEXT, INTEGER, INTEGER
) TO gda_control_gateway;
GRANT EXECUTE ON FUNCTION gda_control.complete_data_incident_notification(
    TEXT, UUID, TEXT
) TO gda_control_gateway;
GRANT EXECUTE ON FUNCTION gda_control.fail_data_incident_notification(
    TEXT, UUID, TEXT, TEXT, INTEGER
) TO gda_control_gateway;
