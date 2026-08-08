-- 152: Durable provider delivery receipts for ConsumerBinding migrations.
--
-- The outbox stores only a logical Alertmanager route. Endpoint URLs and
-- credentials remain server-owned worker configuration. Terminal migration
-- state can reference only a database-verifiable outbox receipt.

CREATE EXTENSION IF NOT EXISTS pgcrypto WITH SCHEMA public;

ALTER TABLE gda_control.consumer_binding_migration_state
    DROP CONSTRAINT ck_gda_consumer_migration_state_notification;
ALTER TABLE gda_control.consumer_binding_migration_state
    ADD CONSTRAINT ck_gda_consumer_migration_state_notification CHECK (
        notification_status IN (
            'not_required', 'pending', 'delivered', 'failed'
        )
        AND jsonb_typeof(notification_evidence) = 'object'
        AND (
            (
                notification_status IN ('not_required', 'pending')
                AND notification_evidence = '{}'::jsonb
            )
            OR (
                notification_status IN ('delivered', 'failed')
                AND notification_evidence ? 'notification_id'
                AND notification_evidence ? 'receipt_sha256'
                AND notification_evidence - 'notification_id' - 'receipt_sha256'
                    = '{}'::jsonb
                AND notification_evidence->>'notification_id'
                    ~ '^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$'
                AND notification_evidence->>'receipt_sha256'
                    ~ '^[0-9a-f]{64}$'
            )
        )
    );

CREATE TABLE gda_control.consumer_binding_migration_notification_outbox (
    tenant_id TEXT NOT NULL,
    notification_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    migration_state_id UUID NOT NULL,
    binding_id UUID NOT NULL,
    product_urn TEXT NOT NULL,
    from_product_version_id UUID NOT NULL,
    to_product_version_id UUID NOT NULL,
    source_state_sha256 CHAR(64) NOT NULL,
    channel TEXT NOT NULL,
    destination_ref TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    attempt_count INTEGER NOT NULL DEFAULT 0,
    max_attempts INTEGER NOT NULL DEFAULT 10,
    available_at TIMESTAMPTZ NOT NULL,
    claimed_by TEXT,
    claimed_until TIMESTAMPTZ,
    last_error TEXT,
    provider_receipt JSONB NOT NULL DEFAULT '{}'::jsonb,
    receipt_sha256 CHAR(64),
    terminal_worker_id TEXT,
    created_at TIMESTAMPTZ NOT NULL,
    completed_at TIMESTAMPTZ,
    CONSTRAINT uq_gda_consumer_notification_tenant_id
        UNIQUE (tenant_id, notification_id),
    CONSTRAINT uq_gda_consumer_notification_source
        UNIQUE (
            tenant_id, migration_state_id, channel, destination_ref
        ),
    CONSTRAINT fk_gda_consumer_notification_state
        FOREIGN KEY (tenant_id, migration_state_id)
        REFERENCES gda_control.consumer_binding_migration_state(
            tenant_id, migration_state_id
        ),
    CONSTRAINT fk_gda_consumer_notification_binding
        FOREIGN KEY (tenant_id, binding_id)
        REFERENCES gda_control.consumer_binding(tenant_id, binding_id),
    CONSTRAINT fk_gda_consumer_notification_from_version
        FOREIGN KEY (tenant_id, product_urn, from_product_version_id)
        REFERENCES gda_control.data_product_version(
            tenant_id, product_urn, data_product_version_id
        ),
    CONSTRAINT fk_gda_consumer_notification_to_version
        FOREIGN KEY (tenant_id, product_urn, to_product_version_id)
        REFERENCES gda_control.data_product_version(
            tenant_id, product_urn, data_product_version_id
        ),
    CONSTRAINT ck_gda_consumer_notification_product_tenant CHECK (
        product_urn ~ '^gda://[a-z0-9][a-z0-9._-]{0,63}/data_product/[a-z0-9][a-z0-9._-]{0,127}$'
        AND split_part(product_urn, '/', 3) = tenant_id
    ),
    CONSTRAINT ck_gda_consumer_notification_transition CHECK (
        from_product_version_id <> to_product_version_id
        AND source_state_sha256 ~ '^[0-9a-f]{64}$'
    ),
    CONSTRAINT ck_gda_consumer_notification_channel CHECK (
        channel = 'alertmanager'
        AND destination_ref = 'alertmanager:consumer-binding-default'
    ),
    CONSTRAINT ck_gda_consumer_notification_status CHECK (
        status IN ('pending', 'in_flight', 'done', 'failed', 'superseded')
    ),
    CONSTRAINT ck_gda_consumer_notification_attempts CHECK (
        attempt_count >= 0 AND max_attempts BETWEEN 1 AND 100
    ),
    CONSTRAINT ck_gda_consumer_notification_claim_pair CHECK (
        (claimed_by IS NULL) = (claimed_until IS NULL)
    ),
    CONSTRAINT ck_gda_consumer_notification_provider_receipt CHECK (
        jsonb_typeof(provider_receipt) = 'object'
    ),
    CONSTRAINT ck_gda_consumer_notification_receipt_sha CHECK (
        receipt_sha256 IS NULL OR receipt_sha256 ~ '^[0-9a-f]{64}$'
    ),
    CONSTRAINT ck_gda_consumer_notification_delivery_state CHECK (
        (
            status = 'pending'
            AND claimed_by IS NULL
            AND completed_at IS NULL
            AND provider_receipt = '{}'::jsonb
            AND receipt_sha256 IS NULL
            AND terminal_worker_id IS NULL
        )
        OR (
            status = 'in_flight'
            AND claimed_by IS NOT NULL
            AND completed_at IS NULL
            AND provider_receipt = '{}'::jsonb
            AND receipt_sha256 IS NULL
            AND terminal_worker_id IS NULL
        )
        OR (
            status = 'done'
            AND claimed_by IS NULL
            AND completed_at IS NOT NULL
            AND provider_receipt <> '{}'::jsonb
            AND receipt_sha256 IS NOT NULL
            AND terminal_worker_id IS NOT NULL
            AND last_error IS NULL
        )
        OR (
            status = 'failed'
            AND claimed_by IS NULL
            AND completed_at IS NOT NULL
            AND provider_receipt = '{}'::jsonb
            AND receipt_sha256 IS NOT NULL
            AND terminal_worker_id IS NOT NULL
            AND last_error IS NOT NULL
        )
        OR (
            status = 'superseded'
            AND claimed_by IS NULL
            AND completed_at IS NOT NULL
            AND provider_receipt = '{}'::jsonb
            AND receipt_sha256 IS NULL
            AND terminal_worker_id IS NULL
            AND last_error IS NOT NULL
        )
    )
);

CREATE INDEX idx_gda_consumer_notification_due
    ON gda_control.consumer_binding_migration_notification_outbox(
        tenant_id, available_at, created_at, notification_id
    ) WHERE status IN ('pending', 'in_flight');
CREATE INDEX idx_gda_consumer_notification_transition
    ON gda_control.consumer_binding_migration_notification_outbox(
        tenant_id, product_urn, from_product_version_id,
        to_product_version_id, binding_id, created_at
    );

CREATE OR REPLACE FUNCTION gda_control.consumer_binding_notification_receipt_fingerprint(
    p_tenant_id TEXT,
    p_notification_id UUID,
    p_migration_state_id UUID,
    p_binding_id UUID,
    p_product_urn TEXT,
    p_from_product_version_id UUID,
    p_to_product_version_id UUID,
    p_source_state_sha256 TEXT,
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
                    'schema', 'gda.consumer_binding_notification_receipt.v1',
                    'tenant_id', p_tenant_id,
                    'notification_id', p_notification_id::text,
                    'migration_state_id', p_migration_state_id::text,
                    'binding_id', p_binding_id::text,
                    'product_urn', p_product_urn,
                    'from_product_version_id', p_from_product_version_id::text,
                    'to_product_version_id', p_to_product_version_id::text,
                    'source_state_sha256', p_source_state_sha256,
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

CREATE OR REPLACE FUNCTION gda_control.guard_consumer_binding_notification_outbox()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
DECLARE
    v_tenant_id TEXT;
BEGIN
    IF COALESCE(
        current_setting('gda.consumer_binding_notification_outbox_allowed', true), ''
    ) <> '1' THEN
        RAISE EXCEPTION 'use the ConsumerBinding notification outbox functions'
            USING ERRCODE = '55000';
    END IF;
    v_tenant_id := CASE WHEN TG_OP = 'DELETE' THEN OLD.tenant_id ELSE NEW.tenant_id END;
    IF gda_control.current_tenant() IS NULL
       OR v_tenant_id IS DISTINCT FROM gda_control.current_tenant() THEN
        RAISE EXCEPTION 'ConsumerBinding notification tenant is mismatched'
            USING ERRCODE = '42501';
    END IF;
    RETURN CASE WHEN TG_OP = 'DELETE' THEN OLD ELSE NEW END;
END;
$$;

CREATE TRIGGER trg_gda_consumer_binding_notification_guard
BEFORE INSERT OR UPDATE OR DELETE
ON gda_control.consumer_binding_migration_notification_outbox
FOR EACH ROW EXECUTE FUNCTION gda_control.guard_consumer_binding_notification_outbox();

CREATE OR REPLACE FUNCTION gda_control.enqueue_consumer_binding_migration_notification()
RETURNS TRIGGER
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, gda_control
SET row_security = on
AS $$
BEGIN
    IF gda_control.current_tenant() IS NULL
       OR NEW.tenant_id IS DISTINCT FROM gda_control.current_tenant() THEN
        RAISE EXCEPTION 'ConsumerBinding notification tenant context is missing or mismatched'
            USING ERRCODE = '42501';
    END IF;
    PERFORM set_config(
        'gda.consumer_binding_notification_outbox_allowed', '1', true
    );
    UPDATE gda_control.consumer_binding_migration_notification_outbox
       SET status = 'superseded',
           claimed_by = NULL,
           claimed_until = NULL,
           last_error = 'superseded by a newer migration state',
           completed_at = NEW.recorded_at
     WHERE tenant_id = NEW.tenant_id
       AND binding_id = NEW.binding_id
       AND from_product_version_id = NEW.from_product_version_id
       AND to_product_version_id = NEW.to_product_version_id
       AND source_state_sha256 <> NEW.state_sha256
       AND status = 'pending';
    IF NEW.notification_status = 'pending' THEN
        INSERT INTO gda_control.consumer_binding_migration_notification_outbox (
            tenant_id, migration_state_id, binding_id, product_urn,
            from_product_version_id, to_product_version_id,
            source_state_sha256, channel, destination_ref,
            available_at, created_at
        ) VALUES (
            NEW.tenant_id, NEW.migration_state_id, NEW.binding_id,
            NEW.product_urn, NEW.from_product_version_id,
            NEW.to_product_version_id, NEW.state_sha256,
            'alertmanager', 'alertmanager:consumer-binding-default',
            NEW.recorded_at, NEW.recorded_at
        ) ON CONFLICT (
            tenant_id, migration_state_id, channel, destination_ref
        ) DO NOTHING;
    END IF;
    PERFORM set_config(
        'gda.consumer_binding_notification_outbox_allowed', '0', true
    );
    RETURN NEW;
END;
$$;

CREATE TRIGGER trg_gda_consumer_binding_migration_notification
AFTER INSERT ON gda_control.consumer_binding_migration_state
FOR EACH ROW EXECUTE FUNCTION gda_control.enqueue_consumer_binding_migration_notification();

-- Backfill only the latest pending state for each exact consumer transition.
DO $$
DECLARE
    v_tenant RECORD;
BEGIN
    FOR v_tenant IN
        SELECT DISTINCT tenant_id
          FROM gda_control.consumer_binding_migration_state
    LOOP
        PERFORM set_config('app.current_tenant', v_tenant.tenant_id, true);
        PERFORM set_config(
            'gda.consumer_binding_notification_outbox_allowed', '1', true
        );
        INSERT INTO gda_control.consumer_binding_migration_notification_outbox (
            tenant_id, migration_state_id, binding_id, product_urn,
            from_product_version_id, to_product_version_id,
            source_state_sha256, channel, destination_ref,
            available_at, created_at
        )
        SELECT state.tenant_id, state.migration_state_id, state.binding_id,
               state.product_urn, state.from_product_version_id,
               state.to_product_version_id, state.state_sha256,
               'alertmanager', 'alertmanager:consumer-binding-default',
               state.recorded_at, state.recorded_at
          FROM gda_control.consumer_binding_migration_state AS state
         WHERE state.tenant_id = v_tenant.tenant_id
           AND state.notification_status = 'pending'
           AND NOT EXISTS (
               SELECT 1
                 FROM gda_control.consumer_binding_migration_state AS newer
                WHERE newer.tenant_id = state.tenant_id
                  AND newer.binding_id = state.binding_id
                  AND newer.from_product_version_id = state.from_product_version_id
                  AND newer.to_product_version_id = state.to_product_version_id
                  AND newer.state_version > state.state_version
           )
        ON CONFLICT (
            tenant_id, migration_state_id, channel, destination_ref
        ) DO NOTHING;
        PERFORM set_config(
            'gda.consumer_binding_notification_outbox_allowed', '0', true
        );
    END LOOP;
END;
$$;

CREATE OR REPLACE FUNCTION gda_control.claim_consumer_binding_migration_notifications(
    p_tenant_id TEXT,
    p_worker_id TEXT,
    p_limit INTEGER DEFAULT 10,
    p_lease_seconds INTEGER DEFAULT 60
)
RETURNS SETOF gda_control.consumer_binding_migration_notification_outbox
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
    IF p_lease_seconds IS NULL OR p_lease_seconds < 5 OR p_lease_seconds > 3600 THEN
        RAISE EXCEPTION 'lease must be between 5 and 3600 seconds'
            USING ERRCODE = '22023';
    END IF;

    PERFORM pg_advisory_xact_lock(
        hashtextextended(
            'data-product-promotion:' || p_tenant_id || ':' || due.product_urn,
            0
        )
    )
      FROM (
          SELECT DISTINCT notification.product_urn
            FROM gda_control.consumer_binding_migration_notification_outbox
                 AS notification
           WHERE notification.tenant_id = p_tenant_id
             AND notification.status IN ('pending', 'in_flight')
      ) AS due
     ORDER BY due.product_urn;

    PERFORM set_config(
        'gda.consumer_binding_notification_outbox_allowed', '1', true
    );
    UPDATE gda_control.consumer_binding_migration_notification_outbox AS notification
       SET status = 'superseded',
           claimed_by = NULL,
           claimed_until = NULL,
           last_error = 'superseded by a newer migration state',
           completed_at = clock_timestamp()
     WHERE notification.tenant_id = p_tenant_id
       AND notification.status = 'pending'
       AND EXISTS (
           SELECT 1
             FROM gda_control.consumer_binding_migration_state AS newer
            WHERE newer.tenant_id = notification.tenant_id
              AND newer.binding_id = notification.binding_id
              AND newer.from_product_version_id = notification.from_product_version_id
              AND newer.to_product_version_id = notification.to_product_version_id
              AND newer.state_version > (
                  SELECT source.state_version
                    FROM gda_control.consumer_binding_migration_state AS source
                   WHERE source.tenant_id = notification.tenant_id
                     AND source.migration_state_id = notification.migration_state_id
              )
       );

    WITH expired AS (
        SELECT notification.notification_id,
               notification.claimed_by AS terminal_worker_id,
               COALESCE(notification.last_error, 'worker lease expired') AS failure,
               clock_timestamp() AS completed_at
          FROM gda_control.consumer_binding_migration_notification_outbox AS notification
         WHERE notification.tenant_id = p_tenant_id
           AND notification.status = 'in_flight'
           AND notification.claimed_until <= clock_timestamp()
           AND notification.attempt_count >= notification.max_attempts
         FOR UPDATE
    )
    UPDATE gda_control.consumer_binding_migration_notification_outbox AS notification
       SET status = 'failed',
           claimed_by = NULL,
           claimed_until = NULL,
           last_error = expired.failure,
           provider_receipt = '{}'::jsonb,
           terminal_worker_id = expired.terminal_worker_id,
           completed_at = expired.completed_at,
           receipt_sha256 = gda_control.consumer_binding_notification_receipt_fingerprint(
               notification.tenant_id, notification.notification_id,
               notification.migration_state_id, notification.binding_id,
               notification.product_urn, notification.from_product_version_id,
               notification.to_product_version_id, notification.source_state_sha256,
               notification.channel, notification.destination_ref, 'failed',
               notification.attempt_count, notification.max_attempts, '{}'::jsonb,
               expired.failure, expired.terminal_worker_id, expired.completed_at
           )
      FROM expired
     WHERE notification.tenant_id = p_tenant_id
       AND notification.notification_id = expired.notification_id;

    RETURN QUERY
    WITH candidates AS (
        SELECT notification.notification_id
          FROM gda_control.consumer_binding_migration_notification_outbox AS notification
         WHERE notification.tenant_id = p_tenant_id
           AND notification.attempt_count < notification.max_attempts
           AND (
               (
                   notification.status = 'pending'
                   AND notification.available_at <= clock_timestamp()
               )
               OR (
                   notification.status = 'in_flight'
                   AND notification.claimed_until <= clock_timestamp()
               )
           )
         ORDER BY notification.available_at,
                  notification.created_at,
                  notification.notification_id
         LIMIT p_limit
         FOR UPDATE SKIP LOCKED
    )
    UPDATE gda_control.consumer_binding_migration_notification_outbox AS notification
       SET status = 'in_flight',
           attempt_count = notification.attempt_count + 1,
           claimed_by = p_worker_id,
           claimed_until = clock_timestamp()
               + make_interval(secs => p_lease_seconds),
           last_error = NULL,
           completed_at = NULL
      FROM candidates
     WHERE notification.tenant_id = p_tenant_id
       AND notification.notification_id = candidates.notification_id
    RETURNING notification.*;
END;
$$;

CREATE OR REPLACE FUNCTION gda_control.complete_consumer_binding_migration_notification(
    p_tenant_id TEXT,
    p_notification_id UUID,
    p_worker_id TEXT,
    p_provider_receipt JSONB
)
RETURNS SETOF gda_control.consumer_binding_migration_notification_outbox
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, gda_control
SET row_security = on
AS $$
DECLARE
    v_product_urn TEXT;
    v_destination_ref TEXT;
BEGIN
    IF gda_control.current_tenant() IS DISTINCT FROM p_tenant_id THEN
        RAISE EXCEPTION 'tenant context mismatch' USING ERRCODE = '42501';
    END IF;
    IF jsonb_typeof(p_provider_receipt) IS DISTINCT FROM 'object'
       OR p_provider_receipt->>'schema'
            IS DISTINCT FROM 'gda.alertmanager_provider_receipt.v1'
       OR p_provider_receipt->>'provider' IS DISTINCT FROM 'alertmanager'
       OR p_provider_receipt->>'accepted' IS DISTINCT FROM 'true'
       OR COALESCE(p_provider_receipt->>'http_status', '') !~ '^[0-9]{3}$'
       OR (p_provider_receipt->>'http_status')::INTEGER NOT BETWEEN 200 AND 299 THEN
        RAISE EXCEPTION 'provider receipt is invalid' USING ERRCODE = '22023';
    END IF;
    SELECT notification.product_urn, notification.destination_ref
      INTO v_product_urn, v_destination_ref
      FROM gda_control.consumer_binding_migration_notification_outbox AS notification
     WHERE notification.tenant_id = p_tenant_id
       AND notification.notification_id = p_notification_id;
    IF NOT FOUND
       OR p_provider_receipt->>'destination_ref'
            IS DISTINCT FROM v_destination_ref THEN
        RAISE EXCEPTION 'provider receipt destination is invalid'
            USING ERRCODE = '22023';
    END IF;
    PERFORM pg_advisory_xact_lock(
        hashtextextended(
            'data-product-promotion:' || p_tenant_id || ':' || v_product_urn,
            0
        )
    );
    PERFORM set_config(
        'gda.consumer_binding_notification_outbox_allowed', '1', true
    );
    RETURN QUERY
    WITH target AS (
        SELECT notification.*, clock_timestamp() AS terminal_at
          FROM gda_control.consumer_binding_migration_notification_outbox AS notification
         WHERE notification.tenant_id = p_tenant_id
           AND notification.notification_id = p_notification_id
           AND notification.status = 'in_flight'
           AND notification.claimed_by = p_worker_id
           AND notification.claimed_until > clock_timestamp()
         FOR UPDATE
    )
    UPDATE gda_control.consumer_binding_migration_notification_outbox AS notification
       SET status = 'done',
           claimed_by = NULL,
           claimed_until = NULL,
           last_error = NULL,
           provider_receipt = p_provider_receipt,
           terminal_worker_id = p_worker_id,
           completed_at = target.terminal_at,
           receipt_sha256 = gda_control.consumer_binding_notification_receipt_fingerprint(
               target.tenant_id, target.notification_id,
               target.migration_state_id, target.binding_id,
               target.product_urn, target.from_product_version_id,
               target.to_product_version_id, target.source_state_sha256,
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
END;
$$;

CREATE OR REPLACE FUNCTION gda_control.fail_consumer_binding_migration_notification(
    p_tenant_id TEXT,
    p_notification_id UUID,
    p_worker_id TEXT,
    p_error TEXT,
    p_retry_delay_seconds INTEGER DEFAULT 30
)
RETURNS SETOF gda_control.consumer_binding_migration_notification_outbox
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, gda_control
SET row_security = on
AS $$
DECLARE
    v_product_urn TEXT;
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
    SELECT notification.product_urn INTO v_product_urn
      FROM gda_control.consumer_binding_migration_notification_outbox AS notification
     WHERE notification.tenant_id = p_tenant_id
       AND notification.notification_id = p_notification_id;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'notification was not found' USING ERRCODE = 'P0002';
    END IF;
    PERFORM pg_advisory_xact_lock(
        hashtextextended(
            'data-product-promotion:' || p_tenant_id || ':' || v_product_urn,
            0
        )
    );
    PERFORM set_config(
        'gda.consumer_binding_notification_outbox_allowed', '1', true
    );
    RETURN QUERY
    WITH target AS (
        SELECT notification.*,
               left(p_error, 512) AS failure,
               clock_timestamp() AS terminal_at
          FROM gda_control.consumer_binding_migration_notification_outbox AS notification
         WHERE notification.tenant_id = p_tenant_id
           AND notification.notification_id = p_notification_id
           AND notification.status = 'in_flight'
           AND notification.claimed_by = p_worker_id
           AND notification.claimed_until > clock_timestamp()
         FOR UPDATE
    )
    UPDATE gda_control.consumer_binding_migration_notification_outbox AS notification
       SET status = CASE WHEN target.attempt_count >= target.max_attempts
                         THEN 'failed' ELSE 'pending' END,
           claimed_by = NULL,
           claimed_until = NULL,
           last_error = target.failure,
           available_at = CASE WHEN target.attempt_count >= target.max_attempts
                               THEN target.available_at
                               ELSE clock_timestamp()
                                    + make_interval(secs => p_retry_delay_seconds) END,
           provider_receipt = '{}'::jsonb,
           terminal_worker_id = CASE WHEN target.attempt_count >= target.max_attempts
                                     THEN p_worker_id ELSE NULL END,
           completed_at = CASE WHEN target.attempt_count >= target.max_attempts
                               THEN target.terminal_at ELSE NULL END,
           receipt_sha256 = CASE WHEN target.attempt_count >= target.max_attempts
               THEN gda_control.consumer_binding_notification_receipt_fingerprint(
                   target.tenant_id, target.notification_id,
                   target.migration_state_id, target.binding_id,
                   target.product_urn, target.from_product_version_id,
                   target.to_product_version_id, target.source_state_sha256,
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
END;
$$;

-- Replace migration 150's recorder so terminal evidence is always rechecked
-- against the immutable outbox receipt at write time.
CREATE OR REPLACE FUNCTION gda_control.record_consumer_binding_migration_state(
    p_tenant_id TEXT,
    p_migration_state_id UUID,
    p_binding_id UUID,
    p_product_urn TEXT,
    p_from_product_version_id UUID,
    p_to_product_version_id UUID,
    p_state_version INTEGER,
    p_compatibility_conclusion TEXT,
    p_compatibility_evidence JSONB,
    p_notification_status TEXT,
    p_notification_evidence JSONB,
    p_migration_deadline TIMESTAMPTZ,
    p_consumer_acknowledgement JSONB,
    p_previous_state_sha256 CHAR(64),
    p_recorded_by TEXT,
    p_recorded_at TIMESTAMPTZ,
    p_state_sha256 CHAR(64)
)
RETURNS TABLE(migration_state_id UUID, created BOOLEAN)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, gda_control
SET row_security = on
AS $$
DECLARE
    v_binding gda_control.consumer_binding%ROWTYPE;
    v_existing gda_control.consumer_binding_migration_state%ROWTYPE;
    v_latest gda_control.consumer_binding_migration_state%ROWTYPE;
    v_notification gda_control.consumer_binding_migration_notification_outbox%ROWTYPE;
    v_source_state_version INTEGER;
    v_inserted UUID;
BEGIN
    IF p_tenant_id IS DISTINCT FROM gda_control.current_tenant() THEN
        RAISE EXCEPTION 'consumer migration state tenant context is missing or mismatched'
            USING ERRCODE = '42501';
    END IF;
    PERFORM pg_advisory_xact_lock(
        hashtextextended(
            'data-product-promotion:' || p_tenant_id || ':' || p_product_urn, 0
        )
    );
    SELECT binding.* INTO v_binding
      FROM gda_control.consumer_binding AS binding
     WHERE binding.tenant_id = p_tenant_id
       AND binding.binding_id = p_binding_id;
    IF NOT FOUND OR v_binding.product_urn IS DISTINCT FROM p_product_urn THEN
        RAISE EXCEPTION 'ConsumerBinding was not found for migration state'
            USING ERRCODE = 'P0002';
    END IF;
    IF p_consumer_acknowledgement IS NOT NULL
       AND p_consumer_acknowledgement->>'consumer_ref'
            IS DISTINCT FROM v_binding.consumer_ref THEN
        RAISE EXCEPTION 'consumer acknowledgement actor does not match ConsumerBinding'
            USING ERRCODE = '42501';
    END IF;
    IF p_consumer_acknowledgement IS NOT NULL
       AND p_recorded_by IS DISTINCT FROM v_binding.consumer_ref THEN
        RAISE EXCEPTION 'consumer acknowledgement must be recorded by the bound consumer'
            USING ERRCODE = '42501';
    END IF;

    SELECT state.* INTO v_existing
      FROM gda_control.consumer_binding_migration_state AS state
     WHERE state.tenant_id = p_tenant_id
       AND state.migration_state_id = p_migration_state_id;
    IF FOUND THEN
        IF v_existing.binding_id IS DISTINCT FROM p_binding_id
           OR v_existing.product_urn IS DISTINCT FROM p_product_urn
           OR v_existing.from_product_version_id IS DISTINCT FROM p_from_product_version_id
           OR v_existing.to_product_version_id IS DISTINCT FROM p_to_product_version_id
           OR v_existing.state_version IS DISTINCT FROM p_state_version
           OR v_existing.compatibility_conclusion IS DISTINCT FROM p_compatibility_conclusion
           OR v_existing.compatibility_evidence IS DISTINCT FROM p_compatibility_evidence
           OR v_existing.notification_status IS DISTINCT FROM p_notification_status
           OR v_existing.notification_evidence IS DISTINCT FROM p_notification_evidence
           OR v_existing.migration_deadline IS DISTINCT FROM p_migration_deadline
           OR v_existing.consumer_acknowledgement IS DISTINCT FROM p_consumer_acknowledgement
           OR v_existing.previous_state_sha256 IS DISTINCT FROM p_previous_state_sha256
           OR v_existing.recorded_by IS DISTINCT FROM p_recorded_by
           OR v_existing.recorded_at IS DISTINCT FROM p_recorded_at
           OR v_existing.state_sha256 IS DISTINCT FROM p_state_sha256 THEN
            RAISE EXCEPTION 'consumer migration state identity already has a different payload'
                USING ERRCODE = '23505';
        END IF;
        RETURN QUERY SELECT v_existing.migration_state_id, FALSE;
        RETURN;
    END IF;
    IF EXISTS (
        SELECT 1 FROM gda_control.consumer_binding_migration_state AS state
         WHERE state.tenant_id = p_tenant_id
           AND state.state_sha256 = p_state_sha256
    ) THEN
        RAISE EXCEPTION 'consumer migration state fingerprint has a different identity'
            USING ERRCODE = '23505';
    END IF;

    SELECT state.* INTO v_latest
      FROM gda_control.consumer_binding_migration_state AS state
     WHERE state.tenant_id = p_tenant_id
       AND state.binding_id = p_binding_id
       AND state.from_product_version_id = p_from_product_version_id
       AND state.to_product_version_id = p_to_product_version_id
     ORDER BY state.state_version DESC
     LIMIT 1
     FOR UPDATE;
    IF FOUND THEN
        IF p_state_version <> v_latest.state_version + 1
           OR p_previous_state_sha256 IS DISTINCT FROM v_latest.state_sha256 THEN
            RAISE EXCEPTION 'consumer migration state compare-and-swap precondition failed'
                USING ERRCODE = '40001';
        END IF;
        IF EXISTS (
            SELECT 1
              FROM gda_control.consumer_binding_migration_notification_outbox AS notice
             WHERE notice.tenant_id = p_tenant_id
               AND notice.source_state_sha256 = v_latest.state_sha256
               AND notice.status = 'in_flight'
        ) THEN
            RAISE EXCEPTION 'consumer migration notification is currently in flight'
                USING ERRCODE = '40001';
        END IF;
    ELSIF p_state_version <> 1 OR p_previous_state_sha256 IS NOT NULL THEN
        RAISE EXCEPTION 'initial consumer migration state must start at version 1'
            USING ERRCODE = '40001';
    END IF;

    IF p_notification_status IN ('delivered', 'failed') THEN
        SELECT notice.* INTO v_notification
          FROM gda_control.consumer_binding_migration_notification_outbox AS notice
         WHERE notice.tenant_id = p_tenant_id
           AND notice.notification_id = (
               p_notification_evidence->>'notification_id'
           )::UUID;
        IF NOT FOUND
           OR v_notification.binding_id IS DISTINCT FROM p_binding_id
           OR v_notification.product_urn IS DISTINCT FROM p_product_urn
           OR v_notification.from_product_version_id
                IS DISTINCT FROM p_from_product_version_id
           OR v_notification.to_product_version_id
                IS DISTINCT FROM p_to_product_version_id
           OR v_notification.receipt_sha256
                IS DISTINCT FROM p_notification_evidence->>'receipt_sha256'
           OR (
               p_notification_status = 'delivered'
               AND v_notification.status <> 'done'
           )
           OR (
               p_notification_status = 'failed'
               AND v_notification.status <> 'failed'
           )
           OR v_notification.receipt_sha256 IS DISTINCT FROM
                gda_control.consumer_binding_notification_receipt_fingerprint(
                    v_notification.tenant_id, v_notification.notification_id,
                    v_notification.migration_state_id, v_notification.binding_id,
                    v_notification.product_urn,
                    v_notification.from_product_version_id,
                    v_notification.to_product_version_id,
                    v_notification.source_state_sha256,
                    v_notification.channel, v_notification.destination_ref,
                    v_notification.status, v_notification.attempt_count,
                    v_notification.max_attempts, v_notification.provider_receipt,
                    v_notification.last_error, v_notification.terminal_worker_id,
                    v_notification.completed_at
                ) THEN
            RAISE EXCEPTION 'terminal notification evidence is not backed by a valid outbox receipt'
                USING ERRCODE = '42501';
        END IF;
        SELECT source.state_version INTO v_source_state_version
          FROM gda_control.consumer_binding_migration_state AS source
         WHERE source.tenant_id = p_tenant_id
           AND source.migration_state_id = v_notification.migration_state_id
           AND source.state_sha256 = v_notification.source_state_sha256
           AND source.binding_id = p_binding_id
           AND source.from_product_version_id = p_from_product_version_id
           AND source.to_product_version_id = p_to_product_version_id;
        IF NOT FOUND OR v_source_state_version >= p_state_version THEN
            RAISE EXCEPTION 'terminal notification receipt does not precede this state'
                USING ERRCODE = '42501';
        END IF;
    END IF;

    PERFORM set_config('gda.consumer_migration_state_allowed', '1', true);
    INSERT INTO gda_control.consumer_binding_migration_state (
        tenant_id, migration_state_id, binding_id, product_urn,
        from_product_version_id, to_product_version_id, state_version,
        compatibility_conclusion, compatibility_evidence,
        notification_status, notification_evidence, migration_deadline,
        consumer_acknowledgement, previous_state_sha256,
        recorded_by, recorded_at, state_sha256
    ) VALUES (
        p_tenant_id, p_migration_state_id, p_binding_id, p_product_urn,
        p_from_product_version_id, p_to_product_version_id, p_state_version,
        p_compatibility_conclusion, p_compatibility_evidence,
        p_notification_status, p_notification_evidence, p_migration_deadline,
        p_consumer_acknowledgement, p_previous_state_sha256,
        p_recorded_by, p_recorded_at, p_state_sha256
    )
    RETURNING gda_control.consumer_binding_migration_state.migration_state_id
    INTO v_inserted;
    PERFORM set_config('gda.consumer_migration_state_allowed', '0', true);
    RETURN QUERY SELECT v_inserted, TRUE;
END;
$$;

ALTER TABLE gda_control.consumer_binding_migration_notification_outbox
    ENABLE ROW LEVEL SECURITY;
ALTER TABLE gda_control.consumer_binding_migration_notification_outbox
    FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation
    ON gda_control.consumer_binding_migration_notification_outbox
    USING (tenant_id = gda_control.current_tenant())
    WITH CHECK (tenant_id = gda_control.current_tenant());

REVOKE ALL ON TABLE gda_control.consumer_binding_migration_notification_outbox
    FROM PUBLIC, gda_control_gateway;
GRANT SELECT ON TABLE gda_control.consumer_binding_migration_notification_outbox
    TO gda_control_gateway;

REVOKE ALL ON FUNCTION gda_control.consumer_binding_notification_receipt_fingerprint(
    TEXT, UUID, UUID, UUID, TEXT, UUID, UUID, TEXT, TEXT, TEXT, TEXT,
    INTEGER, INTEGER, JSONB, TEXT, TEXT, TIMESTAMPTZ
) FROM PUBLIC;
REVOKE ALL ON FUNCTION gda_control.enqueue_consumer_binding_migration_notification()
    FROM PUBLIC;
REVOKE ALL ON FUNCTION gda_control.claim_consumer_binding_migration_notifications(
    TEXT, TEXT, INTEGER, INTEGER
) FROM PUBLIC;
REVOKE ALL ON FUNCTION gda_control.complete_consumer_binding_migration_notification(
    TEXT, UUID, TEXT, JSONB
) FROM PUBLIC;
REVOKE ALL ON FUNCTION gda_control.fail_consumer_binding_migration_notification(
    TEXT, UUID, TEXT, TEXT, INTEGER
) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION gda_control.claim_consumer_binding_migration_notifications(
    TEXT, TEXT, INTEGER, INTEGER
) TO gda_control_gateway;
GRANT EXECUTE ON FUNCTION gda_control.complete_consumer_binding_migration_notification(
    TEXT, UUID, TEXT, JSONB
) TO gda_control_gateway;
GRANT EXECUTE ON FUNCTION gda_control.fail_consumer_binding_migration_notification(
    TEXT, UUID, TEXT, TEXT, INTEGER
) TO gda_control_gateway;
