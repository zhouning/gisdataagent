-- 249: Durable, pre-expiry ApprovalCase SLA escalation.
--
-- Escalation is an operational notification projection. It never changes the
-- ApprovalCase verdict, and every schedule is bound to the pending case's
-- immutable action and target fingerprint.

CREATE EXTENSION IF NOT EXISTS pgcrypto WITH SCHEMA public;

ALTER TABLE gda_control.approval_case_notification_outbox
    ADD COLUMN IF NOT EXISTS escalation_stage INTEGER,
    ADD COLUMN IF NOT EXISTS escalation_target_subject TEXT,
    ADD COLUMN IF NOT EXISTS escalation_on_call_ref TEXT,
    ADD COLUMN IF NOT EXISTS escalation_actor_subject TEXT,
    ADD COLUMN IF NOT EXISTS escalation_reason TEXT,
    ADD COLUMN IF NOT EXISTS idempotency_key CHAR(64);
ALTER TABLE gda_control.approval_case_notification_outbox
    ALTER COLUMN idempotency_key TYPE TEXT
    USING NULLIF(btrim(idempotency_key), '');

ALTER TABLE gda_control.approval_case_notification_outbox
    DROP CONSTRAINT IF EXISTS ck_gda_approval_notification_kind,
    DROP CONSTRAINT IF EXISTS ck_gda_approval_notification_event_binding,
    DROP CONSTRAINT IF EXISTS ck_gda_approval_notification_suppression;

ALTER TABLE gda_control.approval_case_notification_outbox
    ADD CONSTRAINT ck_gda_approval_notification_kind CHECK (
        notification_kind IN ('requested','escalated','expired','decided')
    ),
    ADD CONSTRAINT ck_gda_approval_notification_event_binding CHECK (
        (notification_kind = 'requested'
            AND approval_event_sequence_no = 0
            AND escalation_stage IS NULL
            AND escalation_target_subject IS NULL
            AND escalation_on_call_ref IS NULL
            AND escalation_actor_subject IS NULL
            AND escalation_reason IS NULL
            AND idempotency_key IS NULL)
        OR (notification_kind = 'escalated'
            AND approval_event_sequence_no IS NULL
            AND escalation_stage IN (1, 2)
            AND escalation_target_subject ~ '^team:[^[:space:]]+$'
            AND escalation_on_call_ref ~ '^oncall:[^[:space:]]+$'
            AND escalation_actor_subject ~ '^(human|workload|agent):[^[:space:]]+$'
            AND NULLIF(btrim(escalation_reason), '') IS NOT NULL
            AND idempotency_key ~ '^[0-9a-f]{64}$')
        OR (notification_kind = 'expired'
            AND approval_event_sequence_no IS NULL
            AND escalation_stage IS NULL
            AND escalation_target_subject IS NULL
            AND escalation_on_call_ref IS NULL
            AND escalation_actor_subject IS NULL
            AND escalation_reason IS NULL
            AND idempotency_key IS NULL)
        OR (notification_kind = 'decided'
            AND approval_event_sequence_no = 1
            AND escalation_stage IS NULL
            AND escalation_target_subject IS NULL
            AND escalation_on_call_ref IS NULL
            AND escalation_actor_subject IS NULL
            AND escalation_reason IS NULL
            AND idempotency_key IS NULL)
    ),
    ADD CONSTRAINT ck_gda_approval_notification_suppression CHECK (
        status <> 'suppressed'
        OR notification_kind IN ('expired', 'escalated')
    );

CREATE TABLE IF NOT EXISTS gda_control.approval_case_sla_escalation (
    tenant_id TEXT NOT NULL,
    escalation_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    approval_case_ref TEXT NOT NULL,
    expected_state_version INTEGER NOT NULL,
    action TEXT NOT NULL,
    target_fingerprint TEXT NOT NULL,
    escalation_stage INTEGER NOT NULL,
    due_at TIMESTAMPTZ NOT NULL,
    target_team_subject TEXT NOT NULL,
    on_call_ref TEXT NOT NULL,
    actor_subject TEXT NOT NULL,
    reason TEXT NOT NULL,
    idempotency_key TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'scheduled',
    created_at TIMESTAMPTZ NOT NULL,
    materialized_at TIMESTAMPTZ,
    suppressed_at TIMESTAMPTZ,
    CONSTRAINT uq_gda_approval_escalation_tenant_id
        UNIQUE (tenant_id, escalation_id),
    CONSTRAINT uq_gda_approval_escalation_stage
        UNIQUE (tenant_id, approval_case_ref, escalation_stage),
    CONSTRAINT uq_gda_approval_escalation_idempotency
        UNIQUE (tenant_id, idempotency_key),
    CONSTRAINT fk_gda_approval_escalation_case
        FOREIGN KEY (tenant_id, approval_case_ref)
        REFERENCES gda_control.approval_case(tenant_id, approval_case_ref),
    CONSTRAINT ck_gda_approval_escalation_stage
        CHECK (escalation_stage IN (1, 2)),
    CONSTRAINT ck_gda_approval_escalation_state_version
        CHECK (expected_state_version = 0),
    CONSTRAINT ck_gda_approval_escalation_action
        CHECK (action ~ '^[a-zA-Z0-9][a-zA-Z0-9._:-]{0,127}$'),
    CONSTRAINT ck_gda_approval_escalation_fingerprint
        CHECK (target_fingerprint ~ '^[0-9a-f]{64}$'),
    CONSTRAINT ck_gda_approval_escalation_target
        CHECK (target_team_subject ~ '^team:[^[:space:]]+$'),
    CONSTRAINT ck_gda_approval_escalation_on_call
        CHECK (on_call_ref ~ '^oncall:[^[:space:]]+$'),
    CONSTRAINT ck_gda_approval_escalation_actor
        CHECK (actor_subject ~ '^(human|workload|agent):[^[:space:]]+$'),
    CONSTRAINT ck_gda_approval_escalation_reason
        CHECK (NULLIF(btrim(reason), '') IS NOT NULL),
    CONSTRAINT ck_gda_approval_escalation_key
        CHECK (idempotency_key ~ '^[0-9a-f]{64}$'),
    CONSTRAINT ck_gda_approval_escalation_status
        CHECK (status IN ('scheduled','materialized','suppressed')),
    CONSTRAINT ck_gda_approval_escalation_terminal_times CHECK (
        (status = 'scheduled' AND materialized_at IS NULL AND suppressed_at IS NULL)
        OR (status = 'materialized' AND materialized_at IS NOT NULL AND suppressed_at IS NULL)
        OR (status = 'suppressed' AND materialized_at IS NULL AND suppressed_at IS NOT NULL)
    )
);

CREATE INDEX IF NOT EXISTS idx_gda_approval_escalation_due
    ON gda_control.approval_case_sla_escalation(tenant_id, due_at, escalation_id)
    WHERE status = 'scheduled';

ALTER TABLE gda_control.approval_case_sla_escalation
    ENABLE ROW LEVEL SECURITY;
ALTER TABLE gda_control.approval_case_sla_escalation
    FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation
    ON gda_control.approval_case_sla_escalation;
CREATE POLICY tenant_isolation
    ON gda_control.approval_case_sla_escalation
    USING (tenant_id = gda_control.current_tenant())
    WITH CHECK (tenant_id = gda_control.current_tenant());

CREATE OR REPLACE FUNCTION gda_control.schedule_approval_case_sla_escalation(
    p_tenant_id TEXT,
    p_approval_case_ref TEXT,
    p_expected_state_version INTEGER,
    p_escalation_stage INTEGER,
    p_due_at TIMESTAMPTZ,
    p_target_team_subject TEXT,
    p_on_call_ref TEXT,
    p_actor_subject TEXT,
    p_reason TEXT,
    p_idempotency_key TEXT
)
RETURNS SETOF gda_control.approval_case_sla_escalation
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public, gda_control
SET row_security = on
AS $$
DECLARE
    v_case gda_control.approval_case%ROWTYPE;
    v_existing gda_control.approval_case_sla_escalation%ROWTYPE;
    v_key TEXT;
BEGIN
    IF gda_control.current_tenant() IS DISTINCT FROM p_tenant_id THEN
        RAISE EXCEPTION 'ApprovalCase escalation tenant context is missing or mismatched'
            USING ERRCODE = '42501';
    END IF;
    IF p_escalation_stage NOT IN (1, 2)
       OR p_expected_state_version <> 0
       OR p_target_team_subject !~ '^team:[^[:space:]]+$'
       OR p_on_call_ref !~ '^oncall:[^[:space:]]+$'
       OR p_actor_subject !~ '^(human|workload|agent):[^[:space:]]+$'
       OR NULLIF(btrim(p_reason), '') IS NULL
       OR p_idempotency_key IS NULL
       OR p_idempotency_key !~ '^[0-9a-f]{64}$' THEN
        RAISE EXCEPTION 'ApprovalCase escalation identity or routing is invalid'
            USING ERRCODE = '22023';
    END IF;

    SELECT approval.* INTO v_case
    FROM gda_control.approval_case AS approval
    WHERE approval.tenant_id = p_tenant_id
      AND approval.approval_case_ref = p_approval_case_ref
    FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'ApprovalCase was not found' USING ERRCODE = 'P0002';
    END IF;
    IF v_case.state_version <> p_expected_state_version
       OR v_case.status <> 'pending' THEN
        RAISE EXCEPTION 'ApprovalCase escalation requires the live pending version'
            USING ERRCODE = '40001';
    END IF;
    IF p_due_at <= v_case.requested_at OR p_due_at >= v_case.expires_at THEN
        RAISE EXCEPTION 'ApprovalCase escalation must be due between request and expiry'
            USING ERRCODE = '22023';
    END IF;

    v_key := encode(public.digest(convert_to(
        p_tenant_id || chr(31) || p_approval_case_ref || chr(31) ||
        p_expected_state_version::TEXT || chr(31) || v_case.action || chr(31) ||
        v_case.target_fingerprint || chr(31) || p_escalation_stage::TEXT || chr(31) ||
        to_char(p_due_at AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"') || chr(31) ||
        p_target_team_subject || chr(31) || p_on_call_ref,
        'UTF8'), 'sha256'), 'hex');
    IF v_key IS DISTINCT FROM p_idempotency_key THEN
        RAISE EXCEPTION 'ApprovalCase escalation idempotency key does not match its scope'
            USING ERRCODE = '22023';
    END IF;

    INSERT INTO gda_control.approval_case_sla_escalation (
        tenant_id, approval_case_ref, expected_state_version, action,
        target_fingerprint, escalation_stage, due_at, target_team_subject,
        on_call_ref, actor_subject, reason, idempotency_key, created_at
    ) VALUES (
        p_tenant_id, p_approval_case_ref, p_expected_state_version, v_case.action,
        v_case.target_fingerprint, p_escalation_stage, p_due_at,
        p_target_team_subject, p_on_call_ref, p_actor_subject, btrim(p_reason),
        p_idempotency_key, clock_timestamp()
    ) ON CONFLICT (tenant_id, approval_case_ref, escalation_stage) DO NOTHING;

    SELECT escalation.* INTO v_existing
    FROM gda_control.approval_case_sla_escalation AS escalation
    WHERE escalation.tenant_id = p_tenant_id
      AND escalation.approval_case_ref = p_approval_case_ref
      AND escalation.escalation_stage = p_escalation_stage
    FOR UPDATE;
    IF v_existing.idempotency_key IS DISTINCT FROM p_idempotency_key
       OR v_existing.due_at IS DISTINCT FROM p_due_at
       OR v_existing.target_team_subject IS DISTINCT FROM p_target_team_subject
       OR v_existing.on_call_ref IS DISTINCT FROM p_on_call_ref
       OR v_existing.action IS DISTINCT FROM v_case.action
       OR v_existing.target_fingerprint IS DISTINCT FROM v_case.target_fingerprint THEN
        RAISE EXCEPTION 'ApprovalCase escalation identity already has different evidence'
            USING ERRCODE = '40001';
    END IF;
    RETURN NEXT v_existing;
END;
$$;

CREATE OR REPLACE FUNCTION gda_control.materialize_due_approval_case_sla_escalations(
    p_tenant_id TEXT,
    p_limit INTEGER DEFAULT 20
)
RETURNS SETOF gda_control.approval_case_notification_outbox
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, gda_control
SET row_security = on
AS $$
DECLARE
    v_due gda_control.approval_case_sla_escalation%ROWTYPE;
    v_notification gda_control.approval_case_notification_outbox%ROWTYPE;
BEGIN
    IF gda_control.current_tenant() IS DISTINCT FROM p_tenant_id THEN
        RAISE EXCEPTION 'ApprovalCase escalation tenant context is missing or mismatched'
            USING ERRCODE = '42501';
    END IF;
    IF p_limit IS NULL OR p_limit < 1 OR p_limit > 100 THEN
        RAISE EXCEPTION 'escalation materialization limit must be between 1 and 100'
            USING ERRCODE = '22023';
    END IF;

    FOR v_due IN
        SELECT escalation.*
        FROM gda_control.approval_case_sla_escalation AS escalation
        JOIN gda_control.approval_case AS approval
          ON approval.tenant_id = escalation.tenant_id
         AND approval.approval_case_ref = escalation.approval_case_ref
        WHERE escalation.tenant_id = p_tenant_id
          AND escalation.status = 'scheduled'
          AND escalation.due_at <= clock_timestamp()
          AND approval.status = 'pending'
          AND approval.expires_at > clock_timestamp()
        ORDER BY escalation.due_at, escalation.escalation_id
        LIMIT p_limit
        FOR UPDATE OF escalation SKIP LOCKED
    LOOP
        INSERT INTO gda_control.approval_case_notification_outbox (
            tenant_id, approval_case_ref, approval_event_sequence_no,
            notification_kind, channel, destination_ref, delivery_order,
            escalation_stage, escalation_target_subject, escalation_on_call_ref,
            escalation_actor_subject, escalation_reason, idempotency_key,
            available_at, created_at
        ) VALUES (
            v_due.tenant_id, v_due.approval_case_ref, NULL,
            'escalated', 'alertmanager', 'alertmanager:approval-default', 1,
            v_due.escalation_stage, v_due.target_team_subject, v_due.on_call_ref,
            v_due.actor_subject, v_due.reason, v_due.idempotency_key,
            v_due.due_at, v_due.created_at
        ) ON CONFLICT (tenant_id, approval_case_ref, notification_kind, channel, destination_ref)
        DO NOTHING;
        UPDATE gda_control.approval_case_sla_escalation
        SET status = 'materialized', materialized_at = clock_timestamp()
        WHERE tenant_id = v_due.tenant_id
          AND escalation_id = v_due.escalation_id
          AND status = 'scheduled';
        SELECT notification.* INTO v_notification
        FROM gda_control.approval_case_notification_outbox AS notification
        WHERE notification.tenant_id = v_due.tenant_id
          AND notification.approval_case_ref = v_due.approval_case_ref
          AND notification.notification_kind = 'escalated'
          AND notification.idempotency_key = v_due.idempotency_key;
        IF FOUND THEN
            RETURN NEXT v_notification;
        END IF;
    END LOOP;
END;
$$;

CREATE OR REPLACE FUNCTION gda_control.suppress_approval_case_sla_escalations()
RETURNS TRIGGER
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, gda_control
SET row_security = on
AS $$
BEGIN
    IF NEW.sequence_no = 1 THEN
        UPDATE gda_control.approval_case_sla_escalation
        SET status = 'suppressed', suppressed_at = NEW.occurred_at
        WHERE tenant_id = NEW.tenant_id
          AND approval_case_ref = NEW.approval_case_ref
          AND status = 'scheduled';
        UPDATE gda_control.approval_case_notification_outbox
        SET status = 'suppressed', completed_at = NEW.occurred_at
        WHERE tenant_id = NEW.tenant_id
          AND approval_case_ref = NEW.approval_case_ref
          AND notification_kind = 'escalated'
          AND status = 'pending';
    END IF;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_gda_approval_case_sla_escalation_suppression
    ON gda_control.approval_case_event;
CREATE TRIGGER trg_gda_approval_case_sla_escalation_suppression
AFTER INSERT ON gda_control.approval_case_event
FOR EACH ROW EXECUTE FUNCTION gda_control.suppress_approval_case_sla_escalations();

REVOKE ALL ON TABLE gda_control.approval_case_sla_escalation
    FROM PUBLIC, gda_control_gateway;
GRANT SELECT ON TABLE gda_control.approval_case_sla_escalation
    TO gda_control_gateway;
REVOKE ALL ON FUNCTION gda_control.schedule_approval_case_sla_escalation(
    TEXT, TEXT, INTEGER, INTEGER, TIMESTAMPTZ, TEXT, TEXT, TEXT, TEXT, TEXT
) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION gda_control.schedule_approval_case_sla_escalation(
    TEXT, TEXT, INTEGER, INTEGER, TIMESTAMPTZ, TEXT, TEXT, TEXT, TEXT, TEXT
) TO gda_control_gateway;
REVOKE ALL ON FUNCTION gda_control.materialize_due_approval_case_sla_escalations(
    TEXT, INTEGER
) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION gda_control.materialize_due_approval_case_sla_escalations(
    TEXT, INTEGER
) TO gda_control_gateway;
