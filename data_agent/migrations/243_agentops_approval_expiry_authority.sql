-- 243: Atomic ApprovalCase expiry authority for Temporal HITL convergence.
--
-- PostgreSQL, not a workflow timer or client clock, decides the race between a
-- human verdict and expiry. The existing ApprovalCase row/event authority and
-- assignment-close trigger remain the only terminal state machine.

ALTER TABLE gda_control.approval_case
    DROP CONSTRAINT IF EXISTS ck_gda_approval_case_time;
ALTER TABLE gda_control.approval_case
    ADD CONSTRAINT ck_gda_approval_case_time CHECK (
        expires_at > requested_at
        AND updated_at >= requested_at
        AND (
            decided_at IS NULL
            OR (
                decided_at >= requested_at
                AND (status = 'cancelled' OR decided_at < expires_at)
            )
        )
    );

CREATE OR REPLACE FUNCTION gda_control.expire_approval_case(
    p_tenant_id TEXT,
    p_approval_case_ref TEXT,
    p_expected_state_version INTEGER,
    p_actor_subject TEXT,
    p_reason TEXT,
    p_details JSONB DEFAULT '{}'::jsonb
)
RETURNS INTEGER
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, gda_control
SET row_security = on
AS $$
DECLARE
    v_case gda_control.approval_case%ROWTYPE;
    v_event gda_control.approval_case_event%ROWTYPE;
    v_occurred_at TIMESTAMPTZ;
BEGIN
    IF gda_control.current_tenant() IS NULL
       OR p_tenant_id IS DISTINCT FROM gda_control.current_tenant() THEN
        RAISE EXCEPTION 'ApprovalCase tenant context is missing or mismatched'
            USING ERRCODE = '42501';
    END IF;
    IF p_approval_case_ref IS NULL
       OR p_approval_case_ref !~ '^gda://[a-z0-9][a-z0-9._-]{0,63}/approval_case/[a-z0-9][a-z0-9._-]{0,127}$'
       OR split_part(p_approval_case_ref, '/', 3) <> p_tenant_id
       OR p_expected_state_version < 0
       OR p_actor_subject !~ '^(workload|agent):[^[:space:]]+$'
       OR NULLIF(btrim(p_reason), '') IS NULL
       OR jsonb_typeof(p_details) <> 'object' THEN
        RAISE EXCEPTION 'ApprovalCase expiry identity, version, actor, reason or details are invalid'
            USING ERRCODE = '22023';
    END IF;

    SELECT approval.* INTO v_case
    FROM gda_control.approval_case AS approval
    WHERE approval.tenant_id = p_tenant_id
      AND approval.approval_case_ref = p_approval_case_ref
    FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'ApprovalCase % not found', p_approval_case_ref
            USING ERRCODE = 'P0002';
    END IF;

    -- An activity retry after a committed response loss is an exact replay only
    -- when the immutable terminal event carries the same expiry evidence.
    IF v_case.status = 'cancelled' AND v_case.state_version = 1 THEN
        SELECT event.* INTO v_event
        FROM gda_control.approval_case_event AS event
        WHERE event.tenant_id = p_tenant_id
          AND event.approval_case_ref = p_approval_case_ref
          AND event.sequence_no = 1;
        IF FOUND
           AND v_case.decided_at >= v_case.expires_at
           AND v_event.to_status = 'cancelled'
           AND v_event.actor_subject = p_actor_subject
           AND v_event.reason = p_reason
           AND v_event.details = p_details
           AND v_event.occurred_at = v_case.decided_at THEN
            RETURN 1;
        END IF;
        RAISE EXCEPTION 'ApprovalCase terminal state conflicts with expiry evidence'
            USING ERRCODE = '40001';
    END IF;
    IF v_case.state_version <> p_expected_state_version THEN
        RAISE EXCEPTION 'ApprovalCase state version conflict: expected %, actual %',
            p_expected_state_version, v_case.state_version
            USING ERRCODE = '40001';
    END IF;
    IF v_case.status <> 'pending' THEN
        RAISE EXCEPTION 'ApprovalCase terminal state won the expiry race'
            USING ERRCODE = '40001';
    END IF;

    v_occurred_at := clock_timestamp();
    IF v_occurred_at < v_case.expires_at THEN
        RAISE EXCEPTION 'ApprovalCase has not expired'
            USING ERRCODE = '23514';
    END IF;

    PERFORM set_config('gda.approval_case_transition_allowed', '1', true);
    UPDATE gda_control.approval_case
    SET status = 'cancelled',
        state_version = 1,
        decided_by = p_actor_subject,
        decision_reason = p_reason,
        decided_at = v_occurred_at,
        updated_at = v_occurred_at
    WHERE tenant_id = p_tenant_id
      AND approval_case_ref = p_approval_case_ref;
    PERFORM set_config('gda.approval_case_transition_allowed', '0', true);

    INSERT INTO gda_control.approval_case_event (
        tenant_id, approval_case_ref, sequence_no, from_status, to_status,
        actor_subject, reason, details, occurred_at
    ) VALUES (
        v_case.tenant_id, v_case.approval_case_ref, 1, 'pending', 'cancelled',
        p_actor_subject, p_reason, p_details, v_occurred_at
    );
    RETURN 1;
EXCEPTION WHEN OTHERS THEN
    PERFORM set_config('gda.approval_case_transition_allowed', '0', true);
    RAISE;
END;
$$;

REVOKE ALL ON FUNCTION gda_control.expire_approval_case(
    TEXT, TEXT, INTEGER, TEXT, TEXT, JSONB
) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION gda_control.expire_approval_case(
    TEXT, TEXT, INTEGER, TEXT, TEXT, JSONB
) TO gda_control_gateway;
