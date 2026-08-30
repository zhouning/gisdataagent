-- 228: Governed, auditable recovery for DataIncident notification dead letters.
-- Recovery changes delivery state only; it never changes the DataIncident
-- lifecycle or reuses a provider receipt as an acceptance fact.

ALTER TABLE gda_control.data_incident_notification_outbox
    ADD COLUMN IF NOT EXISTS recovery_count INTEGER NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS last_recovered_by TEXT,
    ADD COLUMN IF NOT EXISTS last_recovery_reason TEXT,
    ADD COLUMN IF NOT EXISTS last_recovered_at TIMESTAMPTZ;

ALTER TABLE gda_control.data_incident_notification_outbox
    DROP CONSTRAINT IF EXISTS ck_gda_incident_notification_recovery_count,
    DROP CONSTRAINT IF EXISTS ck_gda_incident_notification_recovery_projection;

ALTER TABLE gda_control.data_incident_notification_outbox
    ADD CONSTRAINT ck_gda_incident_notification_recovery_count
        CHECK (recovery_count BETWEEN 0 AND 10),
    ADD CONSTRAINT ck_gda_incident_notification_recovery_projection CHECK (
        (recovery_count = 0
            AND last_recovered_by IS NULL
            AND last_recovery_reason IS NULL
            AND last_recovered_at IS NULL)
        OR (recovery_count > 0
            AND last_recovered_by ~ '^human:[^[:space:]]+$'
            AND length(btrim(last_recovery_reason)) BETWEEN 1 AND 512
            AND last_recovered_at IS NOT NULL)
    );

CREATE TABLE IF NOT EXISTS gda_control.data_incident_notification_recovery_event (
    tenant_id TEXT NOT NULL,
    recovery_event_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    notification_id UUID NOT NULL,
    incident_id UUID NOT NULL,
    incident_event_id UUID NOT NULL,
    recovery_no INTEGER NOT NULL,
    actor_subject TEXT NOT NULL,
    reason TEXT NOT NULL,
    previous_status TEXT NOT NULL,
    previous_attempt_count INTEGER NOT NULL,
    previous_max_attempts INTEGER NOT NULL,
    previous_last_error TEXT NOT NULL,
    previous_provider_receipt JSONB NOT NULL,
    previous_receipt_sha256 CHAR(64) NOT NULL,
    previous_terminal_worker_id TEXT NOT NULL,
    previous_completed_at TIMESTAMPTZ NOT NULL,
    occurred_at TIMESTAMPTZ NOT NULL,
    CONSTRAINT uq_gda_incident_notification_recovery_tenant_id
        UNIQUE (tenant_id, recovery_event_id),
    CONSTRAINT uq_gda_incident_notification_recovery_sequence
        UNIQUE (tenant_id, notification_id, recovery_no),
    CONSTRAINT fk_gda_incident_notification_recovery_notification
        FOREIGN KEY (tenant_id, notification_id)
        REFERENCES gda_control.data_incident_notification_outbox(
            tenant_id, notification_id
        ),
    CONSTRAINT fk_gda_incident_notification_recovery_incident
        FOREIGN KEY (tenant_id, incident_id)
        REFERENCES gda_control.data_incident(tenant_id, incident_id),
    CONSTRAINT fk_gda_incident_notification_recovery_event
        FOREIGN KEY (tenant_id, incident_id, incident_event_id)
        REFERENCES gda_control.data_incident_event(
            tenant_id, incident_id, event_id
        ),
    CONSTRAINT ck_gda_incident_notification_recovery_no
        CHECK (recovery_no BETWEEN 1 AND 10),
    CONSTRAINT ck_gda_incident_notification_recovery_actor
        CHECK (actor_subject ~ '^human:[^[:space:]]+$'),
    CONSTRAINT ck_gda_incident_notification_recovery_reason
        CHECK (length(btrim(reason)) BETWEEN 1 AND 512),
    CONSTRAINT ck_gda_incident_notification_recovery_status
        CHECK (previous_status = 'failed'),
    CONSTRAINT ck_gda_incident_notification_recovery_attempts
        CHECK (previous_attempt_count >= 1
            AND previous_max_attempts BETWEEN 1 AND 100
            AND previous_attempt_count >= previous_max_attempts),
    CONSTRAINT ck_gda_incident_notification_recovery_receipt
        CHECK (jsonb_typeof(previous_provider_receipt) = 'object'
            AND previous_provider_receipt = '{}'::jsonb),
    CONSTRAINT ck_gda_incident_notification_recovery_sha
        CHECK (previous_receipt_sha256 ~ '^[0-9a-f]{64}$'),
    CONSTRAINT ck_gda_incident_notification_recovery_terminal
        CHECK (length(btrim(previous_last_error)) BETWEEN 1 AND 512
            AND length(btrim(previous_terminal_worker_id)) >= 1),
    CONSTRAINT ck_gda_incident_notification_recovery_time
        CHECK (previous_completed_at IS NOT NULL AND occurred_at IS NOT NULL)
);

CREATE INDEX IF NOT EXISTS idx_gda_incident_notification_recovery_incident
    ON gda_control.data_incident_notification_recovery_event(
        tenant_id, incident_id, occurred_at, recovery_event_id
    );

CREATE OR REPLACE FUNCTION gda_control.guard_data_incident_notification_recovery_insert()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    IF COALESCE(
        current_setting('gda.data_incident_notification_recovery_allowed', true), ''
    ) <> '1' THEN
        RAISE EXCEPTION 'use gda_control.recover_data_incident_notification()'
            USING ERRCODE = '55000';
    END IF;
    IF gda_control.current_tenant() IS NULL
       OR NEW.tenant_id IS DISTINCT FROM gda_control.current_tenant() THEN
        RAISE EXCEPTION 'DataIncident notification recovery tenant is mismatched'
            USING ERRCODE = '42501';
    END IF;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_gda_incident_notification_recovery_guard
    ON gda_control.data_incident_notification_recovery_event;
CREATE TRIGGER trg_gda_incident_notification_recovery_guard
BEFORE INSERT
    ON gda_control.data_incident_notification_recovery_event
FOR EACH ROW EXECUTE FUNCTION gda_control.guard_data_incident_notification_recovery_insert();

DROP TRIGGER IF EXISTS trg_gda_incident_notification_recovery_immutable
    ON gda_control.data_incident_notification_recovery_event;
CREATE TRIGGER trg_gda_incident_notification_recovery_immutable
BEFORE UPDATE OR DELETE
    ON gda_control.data_incident_notification_recovery_event
FOR EACH ROW EXECUTE FUNCTION gda_control.reject_immutable_mutation();

ALTER TABLE gda_control.data_incident_notification_recovery_event
    ENABLE ROW LEVEL SECURITY;
ALTER TABLE gda_control.data_incident_notification_recovery_event
    FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation
    ON gda_control.data_incident_notification_recovery_event;
CREATE POLICY tenant_isolation
    ON gda_control.data_incident_notification_recovery_event
    USING (tenant_id = gda_control.current_tenant())
    WITH CHECK (tenant_id = gda_control.current_tenant());

CREATE OR REPLACE FUNCTION gda_control.recover_data_incident_notification(
    p_tenant_id TEXT,
    p_incident_id UUID,
    p_notification_id UUID,
    p_expected_attempt_count INTEGER,
    p_expected_receipt_sha256 TEXT,
    p_actor_subject TEXT,
    p_reason TEXT
)
RETURNS SETOF gda_control.data_incident_notification_outbox
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, gda_control
SET row_security = on
AS $$
DECLARE
    v_notification gda_control.data_incident_notification_outbox%ROWTYPE;
    v_recovery_no INTEGER;
    v_occurred_at TIMESTAMPTZ;
BEGIN
    IF gda_control.current_tenant() IS DISTINCT FROM p_tenant_id THEN
        RAISE EXCEPTION 'tenant context mismatch' USING ERRCODE = '42501';
    END IF;
    IF p_actor_subject !~ '^human:[^[:space:]]+$' THEN
        RAISE EXCEPTION 'notification recovery requires a human identity'
            USING ERRCODE = '42501';
    END IF;
    IF length(btrim(COALESCE(p_reason, ''))) NOT BETWEEN 1 AND 512 THEN
        RAISE EXCEPTION 'notification recovery reason is required'
            USING ERRCODE = '22023';
    END IF;
    IF p_expected_attempt_count IS NULL OR p_expected_attempt_count < 1 THEN
        RAISE EXCEPTION 'expected attempt count must be positive'
            USING ERRCODE = '22023';
    END IF;
    IF COALESCE(p_expected_receipt_sha256, '') !~ '^[0-9a-f]{64}$' THEN
        RAISE EXCEPTION 'expected failure receipt hash is required'
            USING ERRCODE = '22023';
    END IF;

    SELECT notification.* INTO v_notification
      FROM gda_control.data_incident_notification_outbox AS notification
     WHERE notification.tenant_id = p_tenant_id
       AND notification.incident_id = p_incident_id
       AND notification.notification_id = p_notification_id
     FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'DataIncident notification was not found'
            USING ERRCODE = 'P0002';
    END IF;
    IF v_notification.status <> 'failed' THEN
        RAISE EXCEPTION 'only a failed notification may be recovered'
            USING ERRCODE = '40001';
    END IF;
    IF v_notification.attempt_count IS DISTINCT FROM p_expected_attempt_count
       OR v_notification.receipt_sha256::TEXT IS DISTINCT FROM p_expected_receipt_sha256 THEN
        RAISE EXCEPTION 'notification failure evidence changed'
            USING ERRCODE = '40001';
    END IF;
    IF v_notification.recovery_count >= 10 THEN
        RAISE EXCEPTION 'notification manual recovery limit reached'
            USING ERRCODE = '55000';
    END IF;
    IF v_notification.completed_at IS NULL
       OR v_notification.last_error IS NULL
       OR v_notification.terminal_worker_id IS NULL
       OR v_notification.provider_receipt <> '{}'::jsonb THEN
        RAISE EXCEPTION 'failed notification has incomplete terminal evidence'
            USING ERRCODE = '55000';
    END IF;

    v_recovery_no := v_notification.recovery_count + 1;
    v_occurred_at := clock_timestamp();
    PERFORM set_config('gda.data_incident_notification_recovery_allowed', '1', true);
    INSERT INTO gda_control.data_incident_notification_recovery_event (
        tenant_id, notification_id, incident_id, incident_event_id,
        recovery_no, actor_subject, reason, previous_status,
        previous_attempt_count, previous_max_attempts, previous_last_error,
        previous_provider_receipt, previous_receipt_sha256,
        previous_terminal_worker_id, previous_completed_at, occurred_at
    ) VALUES (
        p_tenant_id, v_notification.notification_id, v_notification.incident_id,
        v_notification.incident_event_id, v_recovery_no, p_actor_subject,
        btrim(p_reason), v_notification.status, v_notification.attempt_count,
        v_notification.max_attempts, v_notification.last_error,
        v_notification.provider_receipt, v_notification.receipt_sha256,
        v_notification.terminal_worker_id, v_notification.completed_at,
        v_occurred_at
    );
    PERFORM set_config('gda.data_incident_notification_recovery_allowed', '0', true);

    PERFORM set_config('gda.data_incident_notification_outbox_allowed', '1', true);
    UPDATE gda_control.data_incident_notification_outbox AS notification
       SET status = 'pending',
           attempt_count = 0,
           available_at = v_occurred_at,
           claimed_by = NULL,
           claimed_until = NULL,
           last_error = NULL,
           provider_receipt = '{}'::jsonb,
           receipt_sha256 = NULL,
           terminal_worker_id = NULL,
           completed_at = NULL,
           recovery_count = v_recovery_no,
           last_recovered_by = p_actor_subject,
           last_recovery_reason = btrim(p_reason),
           last_recovered_at = v_occurred_at
     WHERE notification.tenant_id = p_tenant_id
       AND notification.notification_id = p_notification_id;
    PERFORM set_config('gda.data_incident_notification_outbox_allowed', '0', true);

    RETURN QUERY
    SELECT *
      FROM gda_control.data_incident_notification_outbox
     WHERE tenant_id = p_tenant_id
       AND notification_id = p_notification_id;
END;
$$;

REVOKE ALL ON TABLE gda_control.data_incident_notification_recovery_event
    FROM PUBLIC, gda_control_gateway;
GRANT SELECT ON TABLE gda_control.data_incident_notification_recovery_event
    TO gda_control_gateway;
REVOKE ALL ON FUNCTION gda_control.recover_data_incident_notification(
    TEXT, UUID, UUID, INTEGER, TEXT, TEXT, TEXT
) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION gda_control.recover_data_incident_notification(
    TEXT, UUID, UUID, INTEGER, TEXT, TEXT, TEXT
) TO gda_control_gateway;
