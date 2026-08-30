-- 250: Allow one ApprovalCase notification per SLA escalation stage.
--
-- Migration 249 added escalation_stage to the outbox payload but the legacy
-- delivery key did not include it. Stage 1 and stage 2 therefore collided
-- when both were due for the same case. This forward migration preserves
-- applied migration 249 and makes the delivery identity stage-aware.

ALTER TABLE gda_control.approval_case_notification_outbox
    DROP CONSTRAINT IF EXISTS uq_gda_approval_notification_delivery;

ALTER TABLE gda_control.approval_case_notification_outbox
    ADD CONSTRAINT uq_gda_approval_notification_delivery
        UNIQUE NULLS NOT DISTINCT (
            tenant_id,
            approval_case_ref,
            notification_kind,
            channel,
            destination_ref,
            escalation_stage
        );

ALTER TABLE gda_control.approval_case_sla_escalation
    DROP CONSTRAINT IF EXISTS ck_gda_approval_escalation_terminal_times;

ALTER TABLE gda_control.approval_case_sla_escalation
    ADD CONSTRAINT ck_gda_approval_escalation_terminal_times CHECK (
        (status = 'scheduled' AND materialized_at IS NULL AND suppressed_at IS NULL)
        OR (status = 'materialized' AND materialized_at IS NOT NULL AND suppressed_at IS NULL)
        OR (status = 'suppressed' AND suppressed_at IS NOT NULL)
    );

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
        ) ON CONFLICT (
            tenant_id, approval_case_ref, notification_kind, channel,
            destination_ref, escalation_stage
        ) DO NOTHING;

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
          AND notification.escalation_stage = v_due.escalation_stage
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
          AND status IN ('scheduled', 'materialized');

        -- A materialized escalation can still be pending in the notification
        -- outbox. Suppress it atomically with the scheduled projection so a
        -- later worker claim cannot send a stale escalation.
        UPDATE gda_control.approval_case_notification_outbox
        SET status = 'suppressed',
            claimed_by = NULL,
            claimed_until = NULL,
            completed_at = NEW.occurred_at
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
