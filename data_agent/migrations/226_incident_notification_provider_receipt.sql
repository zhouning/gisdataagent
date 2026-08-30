-- 226: Bind DataIncident notification terminal state to a provider receipt.
--
-- The original 099 outbox proved that a worker claimed/completed a delivery,
-- but did not retain what the external provider accepted.  This migration
-- keeps the same outbox and adds an immutable, database-verifiable receipt.

CREATE EXTENSION IF NOT EXISTS pgcrypto WITH SCHEMA public;

ALTER TABLE gda_control.data_incident_notification_outbox
    ADD COLUMN IF NOT EXISTS provider_receipt JSONB NOT NULL DEFAULT '{}'::jsonb,
    ADD COLUMN IF NOT EXISTS receipt_sha256 CHAR(64),
    ADD COLUMN IF NOT EXISTS terminal_worker_id TEXT;

ALTER TABLE gda_control.data_incident_notification_outbox
    DROP CONSTRAINT IF EXISTS ck_gda_incident_notification_delivery_state;
ALTER TABLE gda_control.data_incident_notification_outbox
    DROP CONSTRAINT IF EXISTS ck_gda_incident_notification_provider_receipt;
ALTER TABLE gda_control.data_incident_notification_outbox
    DROP CONSTRAINT IF EXISTS ck_gda_incident_notification_receipt_sha;

CREATE OR REPLACE FUNCTION gda_control.data_incident_notification_receipt_fingerprint(
    p_tenant_id TEXT,
    p_notification_id UUID,
    p_incident_id UUID,
    p_incident_event_id UUID,
    p_incident_sequence_no INTEGER,
    p_channel TEXT,
    p_destination_ref TEXT,
    p_status TEXT,
    p_attempt_count INTEGER,
    p_max_attempts INTEGER,
    p_provider_receipt JSONB,
    p_last_error TEXT,
    p_terminal_worker_id TEXT,
    p_completed_at TIMESTAMPTZ
)
RETURNS TEXT
LANGUAGE sql
IMMUTABLE
SET search_path = pg_catalog, public
SET TimeZone = 'UTC'
AS $$
    SELECT encode(
        public.digest(
            convert_to(
                jsonb_build_object(
                    'schema', 'gda.data_incident_notification_receipt.v1',
                    'tenant_id', p_tenant_id,
                    'notification_id', p_notification_id::text,
                    'incident_id', p_incident_id::text,
                    'incident_event_id', p_incident_event_id::text,
                    'incident_sequence_no', p_incident_sequence_no,
                    'channel', p_channel,
                    'destination_ref', p_destination_ref,
                    'status', p_status,
                    'attempt_count', p_attempt_count,
                    'max_attempts', p_max_attempts,
                    'provider_receipt', p_provider_receipt,
                    'last_error', p_last_error,
                    'terminal_worker_id', p_terminal_worker_id,
                    'completed_at', to_char(
                        p_completed_at AT TIME ZONE 'UTC',
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

-- Existing terminal rows predate provider receipts. Preserve them as explicit
-- unknown evidence; never claim that an external provider accepted them.
UPDATE gda_control.data_incident_notification_outbox AS notification
   SET provider_receipt = jsonb_build_object(
           'schema', 'gda.data_incident_notification_legacy_receipt.v1',
           'provider', 'unknown',
           'accepted', false,
           'reason', 'completed before provider receipt authority'
       ),
       terminal_worker_id = COALESCE(terminal_worker_id, 'migration:226'),
       receipt_sha256 = gda_control.data_incident_notification_receipt_fingerprint(
           notification.tenant_id, notification.notification_id,
           notification.incident_id, notification.incident_event_id,
           notification.incident_sequence_no, notification.channel,
           notification.destination_ref, notification.status,
           notification.attempt_count, notification.max_attempts,
           jsonb_build_object(
               'schema', 'gda.data_incident_notification_legacy_receipt.v1',
               'provider', 'unknown',
               'accepted', false,
               'reason', 'completed before provider receipt authority'
           ),
           notification.last_error, COALESCE(notification.terminal_worker_id, 'migration:226'),
           notification.completed_at
       )
 WHERE notification.status = 'done'
   AND notification.completed_at IS NOT NULL;

UPDATE gda_control.data_incident_notification_outbox AS notification
   SET terminal_worker_id = COALESCE(terminal_worker_id, 'migration:226'),
       receipt_sha256 = gda_control.data_incident_notification_receipt_fingerprint(
           notification.tenant_id, notification.notification_id,
           notification.incident_id, notification.incident_event_id,
           notification.incident_sequence_no, notification.channel,
           notification.destination_ref, notification.status,
           notification.attempt_count, notification.max_attempts,
           '{}'::jsonb, notification.last_error,
           COALESCE(notification.terminal_worker_id, 'migration:226'),
           notification.completed_at
       )
 WHERE notification.status = 'failed'
   AND notification.completed_at IS NOT NULL;

ALTER TABLE gda_control.data_incident_notification_outbox
    ADD CONSTRAINT ck_gda_incident_notification_provider_receipt CHECK (
        jsonb_typeof(provider_receipt) = 'object'
    ),
    ADD CONSTRAINT ck_gda_incident_notification_receipt_sha CHECK (
        receipt_sha256 IS NULL OR receipt_sha256 ~ '^[0-9a-f]{64}$'
    ),
    ADD CONSTRAINT ck_gda_incident_notification_delivery_state CHECK (
        (
            status = 'pending'
            AND claimed_by IS NULL AND completed_at IS NULL
            AND provider_receipt = '{}'::jsonb
            AND receipt_sha256 IS NULL AND terminal_worker_id IS NULL
        )
        OR (
            status = 'in_flight'
            AND claimed_by IS NOT NULL AND completed_at IS NULL
            AND provider_receipt = '{}'::jsonb
            AND receipt_sha256 IS NULL AND terminal_worker_id IS NULL
        )
        OR (
            status = 'done'
            AND claimed_by IS NULL AND completed_at IS NOT NULL
            AND provider_receipt <> '{}'::jsonb
            AND receipt_sha256 IS NOT NULL AND terminal_worker_id IS NOT NULL
            AND last_error IS NULL
        )
        OR (
            status = 'failed'
            AND claimed_by IS NULL AND completed_at IS NOT NULL
            AND provider_receipt = '{}'::jsonb
            AND receipt_sha256 IS NOT NULL AND terminal_worker_id IS NOT NULL
            AND last_error IS NOT NULL
        )
    );

CREATE OR REPLACE FUNCTION gda_control.guard_data_incident_notification_outbox()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    IF COALESCE(
        current_setting('gda.data_incident_notification_outbox_allowed', true), ''
    ) <> '1' THEN
        RAISE EXCEPTION 'use the DataIncident notification outbox functions'
            USING ERRCODE = '55000';
    END IF;
    IF gda_control.current_tenant() IS NULL
       OR (CASE WHEN TG_OP = 'DELETE' THEN OLD.tenant_id ELSE NEW.tenant_id END)
          IS DISTINCT FROM gda_control.current_tenant() THEN
        RAISE EXCEPTION 'DataIncident notification tenant is mismatched'
            USING ERRCODE = '42501';
    END IF;
    RETURN CASE WHEN TG_OP = 'DELETE' THEN OLD ELSE NEW END;
END;
$$;

DROP TRIGGER IF EXISTS trg_gda_data_incident_notification_guard
    ON gda_control.data_incident_notification_outbox;
CREATE TRIGGER trg_gda_data_incident_notification_guard
BEFORE INSERT OR UPDATE OR DELETE
ON gda_control.data_incident_notification_outbox
FOR EACH ROW EXECUTE FUNCTION gda_control.guard_data_incident_notification_outbox();

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
    PERFORM set_config('gda.data_incident_notification_outbox_allowed', '1', true);
    INSERT INTO gda_control.data_incident_notification_outbox (
        tenant_id, incident_id, incident_event_id, incident_sequence_no,
        channel, destination_ref, available_at, created_at
    ) VALUES (
        NEW.tenant_id, NEW.incident_id, NEW.event_id, NEW.sequence_no,
        'alertmanager', 'alertmanager:default', NEW.occurred_at, NEW.occurred_at
    )
    ON CONFLICT (tenant_id, incident_event_id, channel, destination_ref)
    DO NOTHING;
    PERFORM set_config('gda.data_incident_notification_outbox_allowed', '0', true);
    RETURN NEW;
END;
$$;

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
        RAISE EXCEPTION 'claim limit must be between 1 and 100' USING ERRCODE = '22023';
    END IF;
    IF p_lease_seconds IS NULL OR p_lease_seconds < 5 OR p_lease_seconds > 3600 THEN
        RAISE EXCEPTION 'lease must be between 5 and 3600 seconds' USING ERRCODE = '22023';
    END IF;
    PERFORM set_config('gda.data_incident_notification_outbox_allowed', '1', true);

    WITH expired AS (
        SELECT notification.*, clock_timestamp() AS terminal_at,
               COALESCE(notification.last_error, 'worker lease expired') AS failure
          FROM gda_control.data_incident_notification_outbox AS notification
         WHERE notification.tenant_id = p_tenant_id
           AND notification.status = 'in_flight'
           AND notification.claimed_until <= clock_timestamp()
           AND notification.attempt_count >= notification.max_attempts
         FOR UPDATE
    )
    UPDATE gda_control.data_incident_notification_outbox AS notification
       SET status = 'failed', claimed_by = NULL, claimed_until = NULL,
           last_error = expired.failure, provider_receipt = '{}'::jsonb,
           terminal_worker_id = expired.claimed_by,
           completed_at = expired.terminal_at,
           receipt_sha256 = gda_control.data_incident_notification_receipt_fingerprint(
               expired.tenant_id, expired.notification_id, expired.incident_id,
               expired.incident_event_id, expired.incident_sequence_no,
               expired.channel, expired.destination_ref, 'failed',
               expired.attempt_count, expired.max_attempts, '{}'::jsonb,
               expired.failure, expired.claimed_by, expired.terminal_at
           )
      FROM expired
     WHERE notification.tenant_id = expired.tenant_id
       AND notification.notification_id = expired.notification_id;

    RETURN QUERY
    WITH candidates AS (
        SELECT notification.notification_id
          FROM gda_control.data_incident_notification_outbox AS notification
         WHERE notification.tenant_id = p_tenant_id
           AND notification.attempt_count < notification.max_attempts
           AND (
               (notification.status = 'pending' AND notification.available_at <= clock_timestamp())
               OR (notification.status = 'in_flight' AND notification.claimed_until <= clock_timestamp())
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
         ORDER BY notification.available_at, notification.created_at,
                  notification.notification_id
         LIMIT p_limit
         FOR UPDATE SKIP LOCKED
    )
    UPDATE gda_control.data_incident_notification_outbox AS notification
       SET status = 'in_flight',
           attempt_count = notification.attempt_count + 1,
           claimed_by = p_worker_id,
           claimed_until = clock_timestamp() + make_interval(secs => p_lease_seconds),
           completed_at = NULL
      FROM candidates
     WHERE notification.tenant_id = p_tenant_id
       AND notification.notification_id = candidates.notification_id
    RETURNING notification.*;
    PERFORM set_config('gda.data_incident_notification_outbox_allowed', '0', true);
END;
$$;

REVOKE ALL ON FUNCTION gda_control.complete_data_incident_notification(
    TEXT, UUID, TEXT
) FROM PUBLIC, gda_control_gateway;
DROP FUNCTION gda_control.complete_data_incident_notification(TEXT, UUID, TEXT);

CREATE OR REPLACE FUNCTION gda_control.complete_data_incident_notification(
    p_tenant_id TEXT,
    p_notification_id UUID,
    p_worker_id TEXT,
    p_provider_receipt JSONB
)
RETURNS SETOF gda_control.data_incident_notification_outbox
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, gda_control
SET row_security = on
AS $$
DECLARE
    v_destination_ref TEXT;
BEGIN
    IF gda_control.current_tenant() IS DISTINCT FROM p_tenant_id THEN
        RAISE EXCEPTION 'tenant context mismatch' USING ERRCODE = '42501';
    END IF;
    IF jsonb_typeof(p_provider_receipt) IS DISTINCT FROM 'object'
       OR p_provider_receipt->>'schema' NOT IN (
           'gda.alertmanager_provider_receipt.v1',
           'gda.data_incident_notification_legacy_receipt.v1'
       )
       OR (
           p_provider_receipt->>'schema' = 'gda.alertmanager_provider_receipt.v1'
           AND (
               p_provider_receipt->>'provider' IS DISTINCT FROM 'alertmanager'
               OR p_provider_receipt->>'accepted' IS DISTINCT FROM 'true'
               OR COALESCE(p_provider_receipt->>'http_status', '') !~ '^[0-9]{3}$'
               OR (p_provider_receipt->>'http_status')::INTEGER NOT BETWEEN 200 AND 299
               OR COALESCE(p_provider_receipt->>'accepted_at', '') = ''
               OR COALESCE(p_provider_receipt->>'destination_ref', '') = ''
           )
       )
       OR (
           p_provider_receipt->>'schema' = 'gda.data_incident_notification_legacy_receipt.v1'
           AND p_provider_receipt->>'accepted' IS DISTINCT FROM 'false'
       ) THEN
        RAISE EXCEPTION 'provider receipt is invalid' USING ERRCODE = '22023';
    END IF;
    SELECT destination_ref INTO v_destination_ref
      FROM gda_control.data_incident_notification_outbox
     WHERE tenant_id = p_tenant_id AND notification_id = p_notification_id;
    IF NOT FOUND OR p_provider_receipt->>'destination_ref' IS DISTINCT FROM v_destination_ref THEN
        RAISE EXCEPTION 'provider receipt destination is invalid' USING ERRCODE = '22023';
    END IF;
    PERFORM set_config('gda.data_incident_notification_outbox_allowed', '1', true);
    RETURN QUERY
    WITH target AS (
        SELECT notification.*, clock_timestamp() AS terminal_at
          FROM gda_control.data_incident_notification_outbox AS notification
         WHERE notification.tenant_id = p_tenant_id
           AND notification.notification_id = p_notification_id
           AND notification.status = 'in_flight'
           AND notification.claimed_by = p_worker_id
           AND notification.claimed_until > clock_timestamp()
         FOR UPDATE
    )
    UPDATE gda_control.data_incident_notification_outbox AS notification
       SET status = 'done', claimed_by = NULL, claimed_until = NULL,
           last_error = NULL, provider_receipt = p_provider_receipt,
           terminal_worker_id = p_worker_id, completed_at = target.terminal_at,
           receipt_sha256 = gda_control.data_incident_notification_receipt_fingerprint(
               target.tenant_id, target.notification_id, target.incident_id,
               target.incident_event_id, target.incident_sequence_no,
               target.channel, target.destination_ref, 'done',
               target.attempt_count, target.max_attempts, p_provider_receipt,
               NULL, p_worker_id, target.terminal_at
           )
      FROM target
     WHERE notification.tenant_id = target.tenant_id
       AND notification.notification_id = target.notification_id
    RETURNING notification.*;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'notification claim is missing, expired, or owned by another worker'
            USING ERRCODE = '40001';
    END IF;
    PERFORM set_config('gda.data_incident_notification_outbox_allowed', '0', true);
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
    IF p_retry_delay_seconds IS NULL OR p_retry_delay_seconds < 0 OR p_retry_delay_seconds > 86400 THEN
        RAISE EXCEPTION 'retry delay must be between 0 and 86400 seconds' USING ERRCODE = '22023';
    END IF;
    PERFORM set_config('gda.data_incident_notification_outbox_allowed', '1', true);
    RETURN QUERY
    WITH target AS (
        SELECT notification.*, left(p_error, 512) AS failure,
               clock_timestamp() AS terminal_at
          FROM gda_control.data_incident_notification_outbox AS notification
         WHERE notification.tenant_id = p_tenant_id
           AND notification.notification_id = p_notification_id
           AND notification.status = 'in_flight'
           AND notification.claimed_by = p_worker_id
           AND notification.claimed_until > clock_timestamp()
         FOR UPDATE
    )
    UPDATE gda_control.data_incident_notification_outbox AS notification
       SET status = CASE WHEN target.attempt_count >= target.max_attempts THEN 'failed' ELSE 'pending' END,
           claimed_by = NULL, claimed_until = NULL, last_error = target.failure,
           available_at = CASE WHEN target.attempt_count >= target.max_attempts THEN target.available_at
                               ELSE clock_timestamp() + make_interval(secs => p_retry_delay_seconds) END,
           provider_receipt = '{}'::jsonb,
           terminal_worker_id = CASE WHEN target.attempt_count >= target.max_attempts THEN p_worker_id ELSE NULL END,
           completed_at = CASE WHEN target.attempt_count >= target.max_attempts THEN target.terminal_at ELSE NULL END,
           receipt_sha256 = CASE WHEN target.attempt_count >= target.max_attempts
               THEN gda_control.data_incident_notification_receipt_fingerprint(
                   target.tenant_id, target.notification_id, target.incident_id,
                   target.incident_event_id, target.incident_sequence_no,
                   target.channel, target.destination_ref, 'failed',
                   target.attempt_count, target.max_attempts, '{}'::jsonb,
                   target.failure, p_worker_id, target.terminal_at
               ) ELSE NULL END
      FROM target
     WHERE notification.tenant_id = target.tenant_id
       AND notification.notification_id = target.notification_id
    RETURNING notification.*;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'notification claim is missing, expired, or owned by another worker'
            USING ERRCODE = '40001';
    END IF;
    PERFORM set_config('gda.data_incident_notification_outbox_allowed', '0', true);
END;
$$;

REVOKE ALL ON FUNCTION gda_control.data_incident_notification_receipt_fingerprint(
    TEXT, UUID, UUID, UUID, INTEGER, TEXT, TEXT, TEXT, INTEGER, INTEGER,
    JSONB, TEXT, TEXT, TIMESTAMPTZ
) FROM PUBLIC;
REVOKE ALL ON FUNCTION gda_control.complete_data_incident_notification(
    TEXT, UUID, TEXT, JSONB
) FROM PUBLIC;
REVOKE ALL ON FUNCTION gda_control.fail_data_incident_notification(
    TEXT, UUID, TEXT, TEXT, INTEGER
) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION gda_control.complete_data_incident_notification(
    TEXT, UUID, TEXT, JSONB
) TO gda_control_gateway;
GRANT EXECUTE ON FUNCTION gda_control.fail_data_incident_notification(
    TEXT, UUID, TEXT, TEXT, INTEGER
) TO gda_control_gateway;
