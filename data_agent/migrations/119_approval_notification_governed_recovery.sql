-- 119: Governed manual recovery for ApprovalCase notification dead letters.
--
-- Recovery changes delivery state only. It never changes ApprovalCase status,
-- creates a verdict, or authorizes the governed target action.

ALTER TABLE gda_control.approval_case_notification_outbox
    ADD COLUMN IF NOT EXISTS recovery_count INTEGER NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS last_recovered_by TEXT,
    ADD COLUMN IF NOT EXISTS last_recovery_reason TEXT,
    ADD COLUMN IF NOT EXISTS last_recovered_at TIMESTAMPTZ;

ALTER TABLE gda_control.approval_case_notification_outbox
    ADD CONSTRAINT ck_gda_approval_notification_recovery_count
        CHECK (recovery_count BETWEEN 0 AND 10),
    ADD CONSTRAINT ck_gda_approval_notification_recovery_projection CHECK (
        (recovery_count = 0
            AND last_recovered_by IS NULL
            AND last_recovery_reason IS NULL
            AND last_recovered_at IS NULL)
        OR (recovery_count > 0
            AND last_recovered_by ~ '^human:[^[:space:]]+$'
            AND length(btrim(last_recovery_reason)) BETWEEN 1 AND 512
            AND last_recovered_at IS NOT NULL)
    );

CREATE TABLE gda_control.approval_case_notification_recovery_event (
    tenant_id TEXT NOT NULL,
    recovery_event_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    notification_id UUID NOT NULL,
    approval_case_ref TEXT NOT NULL,
    recovery_no INTEGER NOT NULL,
    actor_subject TEXT NOT NULL,
    reason TEXT NOT NULL,
    previous_attempt_count INTEGER NOT NULL,
    previous_last_error TEXT,
    occurred_at TIMESTAMPTZ NOT NULL,
    CONSTRAINT uq_gda_approval_notification_recovery_tenant_id
        UNIQUE (tenant_id, recovery_event_id),
    CONSTRAINT uq_gda_approval_notification_recovery_sequence
        UNIQUE (tenant_id, notification_id, recovery_no),
    CONSTRAINT fk_gda_approval_notification_recovery_notification
        FOREIGN KEY (tenant_id, notification_id)
        REFERENCES gda_control.approval_case_notification_outbox(
            tenant_id, notification_id
        ),
    CONSTRAINT fk_gda_approval_notification_recovery_case
        FOREIGN KEY (tenant_id, approval_case_ref)
        REFERENCES gda_control.approval_case(tenant_id, approval_case_ref),
    CONSTRAINT ck_gda_approval_notification_recovery_no
        CHECK (recovery_no BETWEEN 1 AND 10),
    CONSTRAINT ck_gda_approval_notification_recovery_actor
        CHECK (actor_subject ~ '^human:[^[:space:]]+$'),
    CONSTRAINT ck_gda_approval_notification_recovery_reason
        CHECK (length(btrim(reason)) BETWEEN 1 AND 512),
    CONSTRAINT ck_gda_approval_notification_recovery_attempts
        CHECK (previous_attempt_count >= 1)
);

CREATE INDEX idx_gda_approval_notification_recovery_case
    ON gda_control.approval_case_notification_recovery_event(
        tenant_id, approval_case_ref, occurred_at, recovery_event_id
    );

DROP TRIGGER IF EXISTS trg_gda_approval_notification_recovery_immutable
    ON gda_control.approval_case_notification_recovery_event;
CREATE TRIGGER trg_gda_approval_notification_recovery_immutable
BEFORE UPDATE OR DELETE
    ON gda_control.approval_case_notification_recovery_event
FOR EACH ROW EXECUTE FUNCTION gda_control.reject_immutable_mutation();

ALTER TABLE gda_control.approval_case_notification_recovery_event
    ENABLE ROW LEVEL SECURITY;
ALTER TABLE gda_control.approval_case_notification_recovery_event
    FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation
    ON gda_control.approval_case_notification_recovery_event;
CREATE POLICY tenant_isolation
    ON gda_control.approval_case_notification_recovery_event
    USING (tenant_id = gda_control.current_tenant())
    WITH CHECK (tenant_id = gda_control.current_tenant());

CREATE OR REPLACE FUNCTION gda_control.retry_approval_case_notification(
    p_tenant_id TEXT,
    p_approval_case_ref TEXT,
    p_notification_id UUID,
    p_expected_attempt_count INTEGER,
    p_actor_subject TEXT,
    p_reason TEXT
)
RETURNS SETOF gda_control.approval_case_notification_outbox
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public, gda_control
SET row_security = on
AS $$
DECLARE
    v_notification gda_control.approval_case_notification_outbox%ROWTYPE;
    v_case_status TEXT;
    v_occurred_at TIMESTAMPTZ;
    v_recovery_no INTEGER;
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

    SELECT notification.* INTO v_notification
    FROM gda_control.approval_case_notification_outbox AS notification
    WHERE notification.tenant_id = p_tenant_id
      AND notification.approval_case_ref = p_approval_case_ref
      AND notification.notification_id = p_notification_id
    FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'ApprovalCase notification was not found'
            USING ERRCODE = 'P0002';
    END IF;
    IF v_notification.status <> 'failed' THEN
        RAISE EXCEPTION 'only a failed notification may be recovered'
            USING ERRCODE = '40001';
    END IF;
    IF v_notification.attempt_count IS DISTINCT FROM p_expected_attempt_count THEN
        RAISE EXCEPTION 'notification attempt count changed'
            USING ERRCODE = '40001';
    END IF;
    IF v_notification.recovery_count >= 10 THEN
        RAISE EXCEPTION 'notification manual recovery limit reached'
            USING ERRCODE = '55000';
    END IF;

    SELECT approval.status INTO v_case_status
    FROM gda_control.approval_case AS approval
    WHERE approval.tenant_id = p_tenant_id
      AND approval.approval_case_ref = p_approval_case_ref;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'ApprovalCase was not found' USING ERRCODE = 'P0002';
    END IF;
    IF v_notification.notification_kind = 'expired'
       AND v_case_status <> 'pending' THEN
        RAISE EXCEPTION 'a terminal ApprovalCase expiry alert cannot be replayed'
            USING ERRCODE = '55000';
    END IF;

    v_recovery_no := v_notification.recovery_count + 1;
    v_occurred_at := clock_timestamp();

    INSERT INTO gda_control.approval_case_notification_recovery_event (
        tenant_id, notification_id, approval_case_ref, recovery_no,
        actor_subject, reason, previous_attempt_count,
        previous_last_error, occurred_at
    ) VALUES (
        p_tenant_id, p_notification_id, p_approval_case_ref, v_recovery_no,
        p_actor_subject, btrim(p_reason), v_notification.attempt_count,
        v_notification.last_error, v_occurred_at
    );

    UPDATE gda_control.approval_case_notification_outbox AS notification
    SET status = 'pending',
        attempt_count = 0,
        available_at = v_occurred_at,
        claimed_by = NULL,
        claimed_until = NULL,
        last_error = NULL,
        completed_at = NULL,
        recovery_count = v_recovery_no,
        last_recovered_by = p_actor_subject,
        last_recovery_reason = btrim(p_reason),
        last_recovered_at = v_occurred_at
    WHERE notification.tenant_id = p_tenant_id
      AND notification.notification_id = p_notification_id
    RETURNING notification.* INTO v_notification;

    RETURN NEXT v_notification;
END;
$$;

REVOKE ALL ON TABLE gda_control.approval_case_notification_recovery_event
    FROM PUBLIC, gda_control_gateway;
GRANT SELECT ON TABLE gda_control.approval_case_notification_recovery_event
    TO gda_control_gateway;

REVOKE ALL ON FUNCTION gda_control.retry_approval_case_notification(
    TEXT, TEXT, UUID, INTEGER, TEXT, TEXT
) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION gda_control.retry_approval_case_notification(
    TEXT, TEXT, UUID, INTEGER, TEXT, TEXT
) TO gda_control_gateway;
