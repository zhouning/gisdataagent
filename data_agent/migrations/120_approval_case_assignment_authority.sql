-- 120: Tenant-scoped ApprovalCase assignment and delegation authority.
--
-- Assignment is operational routing, not approval. It can restrict who may
-- decide a case, but it never creates a verdict or authorizes the target action.

CREATE TABLE gda_control.approval_case_assignment (
    tenant_id TEXT NOT NULL,
    approval_case_ref TEXT PRIMARY KEY,
    assignment_version INTEGER NOT NULL,
    status TEXT NOT NULL,
    assignee_subject TEXT,
    last_actor_subject TEXT NOT NULL,
    last_reason TEXT NOT NULL,
    delegation_depth INTEGER NOT NULL DEFAULT 0,
    assigned_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    closed_at TIMESTAMPTZ,
    CONSTRAINT uq_gda_approval_assignment_tenant_ref
        UNIQUE (tenant_id, approval_case_ref),
    CONSTRAINT fk_gda_approval_assignment_case
        FOREIGN KEY (tenant_id, approval_case_ref)
        REFERENCES gda_control.approval_case(tenant_id, approval_case_ref),
    CONSTRAINT ck_gda_approval_assignment_version
        CHECK (assignment_version >= 1),
    CONSTRAINT ck_gda_approval_assignment_status
        CHECK (status IN ('assigned','released','closed')),
    CONSTRAINT ck_gda_approval_assignment_actor
        CHECK (last_actor_subject ~ '^(human|workload|agent):[^[:space:]]+$'),
    CONSTRAINT ck_gda_approval_assignment_reason
        CHECK (length(btrim(last_reason)) BETWEEN 1 AND 512),
    CONSTRAINT ck_gda_approval_assignment_depth
        CHECK (delegation_depth BETWEEN 0 AND 5),
    CONSTRAINT ck_gda_approval_assignment_state CHECK (
        (status = 'assigned'
            AND assignee_subject ~ '^human:[^[:space:]]+$'
            AND closed_at IS NULL)
        OR (status = 'released'
            AND assignee_subject IS NULL
            AND closed_at IS NULL)
        OR (status = 'closed' AND closed_at IS NOT NULL)
    ),
    CONSTRAINT ck_gda_approval_assignment_time CHECK (
        updated_at >= assigned_at
        AND (closed_at IS NULL OR closed_at = updated_at)
    )
);

CREATE INDEX idx_gda_approval_assignment_inbox
    ON gda_control.approval_case_assignment(
        tenant_id, status, assignee_subject, updated_at DESC
    );

CREATE TABLE gda_control.approval_case_assignment_event (
    tenant_id TEXT NOT NULL,
    assignment_event_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    approval_case_ref TEXT NOT NULL,
    assignment_version INTEGER NOT NULL,
    action TEXT NOT NULL,
    from_assignee_subject TEXT,
    to_assignee_subject TEXT,
    actor_subject TEXT NOT NULL,
    reason TEXT NOT NULL,
    delegation_depth INTEGER NOT NULL,
    occurred_at TIMESTAMPTZ NOT NULL,
    CONSTRAINT uq_gda_approval_assignment_event_tenant_id
        UNIQUE (tenant_id, assignment_event_id),
    CONSTRAINT uq_gda_approval_assignment_event_version
        UNIQUE (tenant_id, approval_case_ref, assignment_version),
    CONSTRAINT fk_gda_approval_assignment_event_case
        FOREIGN KEY (tenant_id, approval_case_ref)
        REFERENCES gda_control.approval_case(tenant_id, approval_case_ref),
    CONSTRAINT ck_gda_approval_assignment_event_version
        CHECK (assignment_version >= 1),
    CONSTRAINT ck_gda_approval_assignment_event_action
        CHECK (action IN ('assigned','reassigned','delegated','released','closed')),
    CONSTRAINT ck_gda_approval_assignment_event_actor CHECK (
        (action = 'closed'
            AND actor_subject ~ '^(human|workload|agent):[^[:space:]]+$')
        OR (action <> 'closed'
            AND actor_subject ~ '^human:[^[:space:]]+$')
    ),
    CONSTRAINT ck_gda_approval_assignment_event_assignees CHECK (
        (from_assignee_subject IS NULL
            OR from_assignee_subject ~ '^human:[^[:space:]]+$')
        AND (to_assignee_subject IS NULL
            OR to_assignee_subject ~ '^human:[^[:space:]]+$')
    ),
    CONSTRAINT ck_gda_approval_assignment_event_reason
        CHECK (length(btrim(reason)) BETWEEN 1 AND 512),
    CONSTRAINT ck_gda_approval_assignment_event_depth
        CHECK (delegation_depth BETWEEN 0 AND 5),
    CONSTRAINT ck_gda_approval_assignment_event_transition CHECK (
        (action = 'assigned'
            AND from_assignee_subject IS NULL
            AND to_assignee_subject IS NOT NULL
            AND delegation_depth = 0)
        OR (action IN ('reassigned','delegated')
            AND from_assignee_subject IS NOT NULL
            AND to_assignee_subject IS NOT NULL
            AND from_assignee_subject <> to_assignee_subject
            AND (action = 'delegated' OR delegation_depth = 0))
        OR (action = 'released'
            AND from_assignee_subject IS NOT NULL
            AND to_assignee_subject IS NULL
            AND delegation_depth = 0)
        OR (action = 'closed'
            AND from_assignee_subject IS NOT DISTINCT FROM to_assignee_subject)
    )
);

CREATE INDEX idx_gda_approval_assignment_event_case
    ON gda_control.approval_case_assignment_event(
        tenant_id, approval_case_ref, assignment_version
    );

DROP TRIGGER IF EXISTS trg_gda_approval_assignment_event_immutable
    ON gda_control.approval_case_assignment_event;
CREATE TRIGGER trg_gda_approval_assignment_event_immutable
BEFORE UPDATE OR DELETE ON gda_control.approval_case_assignment_event
FOR EACH ROW EXECUTE FUNCTION gda_control.reject_immutable_mutation();

ALTER TABLE gda_control.approval_case_assignment ENABLE ROW LEVEL SECURITY;
ALTER TABLE gda_control.approval_case_assignment FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation
    ON gda_control.approval_case_assignment;
CREATE POLICY tenant_isolation
    ON gda_control.approval_case_assignment
    USING (tenant_id = gda_control.current_tenant())
    WITH CHECK (tenant_id = gda_control.current_tenant());

ALTER TABLE gda_control.approval_case_assignment_event ENABLE ROW LEVEL SECURITY;
ALTER TABLE gda_control.approval_case_assignment_event FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation
    ON gda_control.approval_case_assignment_event;
CREATE POLICY tenant_isolation
    ON gda_control.approval_case_assignment_event
    USING (tenant_id = gda_control.current_tenant())
    WITH CHECK (tenant_id = gda_control.current_tenant());

CREATE OR REPLACE FUNCTION gda_control.transition_approval_case_assignment(
    p_tenant_id TEXT,
    p_approval_case_ref TEXT,
    p_expected_assignment_version INTEGER,
    p_operation TEXT,
    p_actor_subject TEXT,
    p_assignee_subject TEXT,
    p_reason TEXT
)
RETURNS SETOF gda_control.approval_case_assignment
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, gda_control
SET row_security = on
AS $$
DECLARE
    v_case gda_control.approval_case%ROWTYPE;
    v_assignment gda_control.approval_case_assignment%ROWTYPE;
    v_action TEXT;
    v_from_assignee TEXT;
    v_to_assignee TEXT;
    v_next_version INTEGER;
    v_next_depth INTEGER;
    v_occurred_at TIMESTAMPTZ;
BEGIN
    IF gda_control.current_tenant() IS DISTINCT FROM p_tenant_id THEN
        RAISE EXCEPTION 'tenant context mismatch' USING ERRCODE = '42501';
    END IF;
    IF p_operation NOT IN ('assign','reassign','delegate','release')
       OR p_actor_subject !~ '^human:[^[:space:]]+$'
       OR length(btrim(COALESCE(p_reason, ''))) NOT BETWEEN 1 AND 512
       OR p_expected_assignment_version IS NULL
       OR p_expected_assignment_version < 0 THEN
        RAISE EXCEPTION 'approval assignment operation is invalid'
            USING ERRCODE = '22023';
    END IF;
    IF p_operation = 'release' AND p_assignee_subject IS NOT NULL THEN
        RAISE EXCEPTION 'release must not specify an assignee'
            USING ERRCODE = '22023';
    END IF;
    IF p_operation <> 'release'
       AND (p_assignee_subject IS NULL
            OR p_assignee_subject !~ '^human:[^[:space:]]+$') THEN
        RAISE EXCEPTION 'assignment requires a human assignee'
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
    v_occurred_at := clock_timestamp();
    IF v_case.status <> 'pending' OR v_occurred_at >= v_case.expires_at THEN
        RAISE EXCEPTION 'only a live pending ApprovalCase may be routed'
            USING ERRCODE = '55000';
    END IF;
    IF p_assignee_subject IS NOT NULL
       AND p_assignee_subject = v_case.requester_subject THEN
        RAISE EXCEPTION 'ApprovalCase requester cannot be assigned as approver'
            USING ERRCODE = '55000';
    END IF;

    SELECT assignment.* INTO v_assignment
    FROM gda_control.approval_case_assignment AS assignment
    WHERE assignment.tenant_id = p_tenant_id
      AND assignment.approval_case_ref = p_approval_case_ref
    FOR UPDATE;

    IF NOT FOUND THEN
        IF p_expected_assignment_version <> 0 OR p_operation <> 'assign' THEN
            RAISE EXCEPTION 'initial assignment requires version zero and assign operation'
                USING ERRCODE = '40001';
        END IF;
        INSERT INTO gda_control.approval_case_assignment (
            tenant_id, approval_case_ref, assignment_version, status,
            assignee_subject, last_actor_subject, last_reason,
            delegation_depth, assigned_at, updated_at
        ) VALUES (
            p_tenant_id, p_approval_case_ref, 1, 'assigned',
            p_assignee_subject, p_actor_subject, btrim(p_reason),
            0, v_occurred_at, v_occurred_at
        ) RETURNING * INTO v_assignment;
        INSERT INTO gda_control.approval_case_assignment_event (
            tenant_id, approval_case_ref, assignment_version, action,
            from_assignee_subject, to_assignee_subject, actor_subject,
            reason, delegation_depth, occurred_at
        ) VALUES (
            p_tenant_id, p_approval_case_ref, 1, 'assigned',
            NULL, p_assignee_subject, p_actor_subject,
            btrim(p_reason), 0, v_occurred_at
        );
        RETURN NEXT v_assignment;
        RETURN;
    END IF;

    IF v_assignment.assignment_version <> p_expected_assignment_version THEN
        RAISE EXCEPTION 'ApprovalCase assignment version conflict'
            USING ERRCODE = '40001';
    END IF;
    IF v_assignment.status = 'closed' THEN
        RAISE EXCEPTION 'ApprovalCase assignment is closed'
            USING ERRCODE = '40001';
    END IF;

    v_from_assignee := v_assignment.assignee_subject;
    v_to_assignee := p_assignee_subject;
    v_next_version := v_assignment.assignment_version + 1;
    v_next_depth := 0;

    IF p_operation = 'assign' THEN
        IF v_assignment.status <> 'released' THEN
            RAISE EXCEPTION 'assign requires a released routing state'
                USING ERRCODE = '40001';
        END IF;
        v_action := 'assigned';
    ELSIF p_operation = 'reassign' THEN
        IF v_assignment.status <> 'assigned'
           OR p_assignee_subject = v_assignment.assignee_subject THEN
            RAISE EXCEPTION 'reassign requires a different active assignee'
                USING ERRCODE = '40001';
        END IF;
        v_action := 'reassigned';
    ELSIF p_operation = 'delegate' THEN
        IF v_assignment.status <> 'assigned'
           OR p_actor_subject <> v_assignment.assignee_subject THEN
            RAISE EXCEPTION 'only the current assignee may delegate'
                USING ERRCODE = '42501';
        END IF;
        IF p_assignee_subject = v_assignment.assignee_subject THEN
            RAISE EXCEPTION 'delegation requires a different assignee'
                USING ERRCODE = '40001';
        END IF;
        IF v_assignment.delegation_depth >= 5 THEN
            RAISE EXCEPTION 'ApprovalCase delegation depth limit reached'
                USING ERRCODE = '55000';
        END IF;
        v_action := 'delegated';
        v_next_depth := v_assignment.delegation_depth + 1;
    ELSE
        IF v_assignment.status <> 'assigned' THEN
            RAISE EXCEPTION 'release requires an active assignee'
                USING ERRCODE = '40001';
        END IF;
        v_action := 'released';
        v_to_assignee := NULL;
    END IF;

    UPDATE gda_control.approval_case_assignment AS assignment
    SET assignment_version = v_next_version,
        status = CASE WHEN p_operation = 'release' THEN 'released' ELSE 'assigned' END,
        assignee_subject = v_to_assignee,
        last_actor_subject = p_actor_subject,
        last_reason = btrim(p_reason),
        delegation_depth = v_next_depth,
        updated_at = v_occurred_at,
        closed_at = NULL
    WHERE assignment.tenant_id = p_tenant_id
      AND assignment.approval_case_ref = p_approval_case_ref
    RETURNING assignment.* INTO v_assignment;

    INSERT INTO gda_control.approval_case_assignment_event (
        tenant_id, approval_case_ref, assignment_version, action,
        from_assignee_subject, to_assignee_subject, actor_subject,
        reason, delegation_depth, occurred_at
    ) VALUES (
        p_tenant_id, p_approval_case_ref, v_next_version, v_action,
        v_from_assignee, v_to_assignee, p_actor_subject,
        btrim(p_reason), v_next_depth, v_occurred_at
    );
    RETURN NEXT v_assignment;
END;
$$;

CREATE OR REPLACE FUNCTION gda_control.close_approval_case_assignment()
RETURNS TRIGGER
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, gda_control
SET row_security = on
AS $$
DECLARE
    v_assignment gda_control.approval_case_assignment%ROWTYPE;
    v_reason TEXT;
    v_next_version INTEGER;
BEGIN
    IF NEW.sequence_no <> 1 THEN
        RETURN NEW;
    END IF;
    SELECT assignment.* INTO v_assignment
    FROM gda_control.approval_case_assignment AS assignment
    WHERE assignment.tenant_id = NEW.tenant_id
      AND assignment.approval_case_ref = NEW.approval_case_ref
    FOR UPDATE;
    IF NOT FOUND OR v_assignment.status = 'closed' THEN
        RETURN NEW;
    END IF;
    v_next_version := v_assignment.assignment_version + 1;
    v_reason := 'ApprovalCase reached terminal state: ' || NEW.to_status;
    INSERT INTO gda_control.approval_case_assignment_event (
        tenant_id, approval_case_ref, assignment_version, action,
        from_assignee_subject, to_assignee_subject, actor_subject,
        reason, delegation_depth, occurred_at
    ) VALUES (
        NEW.tenant_id, NEW.approval_case_ref, v_next_version, 'closed',
        v_assignment.assignee_subject, v_assignment.assignee_subject,
        NEW.actor_subject, v_reason, v_assignment.delegation_depth,
        NEW.occurred_at
    );
    UPDATE gda_control.approval_case_assignment AS assignment
    SET assignment_version = v_next_version,
        status = 'closed',
        last_actor_subject = NEW.actor_subject,
        last_reason = v_reason,
        updated_at = NEW.occurred_at,
        closed_at = NEW.occurred_at
    WHERE assignment.tenant_id = NEW.tenant_id
      AND assignment.approval_case_ref = NEW.approval_case_ref;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_gda_approval_assignment_close
    ON gda_control.approval_case_event;
CREATE TRIGGER trg_gda_approval_assignment_close
AFTER INSERT ON gda_control.approval_case_event
FOR EACH ROW EXECUTE FUNCTION gda_control.close_approval_case_assignment();

-- Preserve the existing ApprovalCase transition contract while adding one
-- routing check. Both assignment and decision paths lock the case row first.
CREATE OR REPLACE FUNCTION gda_control.transition_approval_case(
    p_tenant_id TEXT,
    p_approval_case_ref TEXT,
    p_expected_state_version INTEGER,
    p_to_status TEXT,
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
    v_assignment gda_control.approval_case_assignment%ROWTYPE;
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
       OR p_to_status NOT IN ('approved','rejected','cancelled')
       OR p_actor_subject !~ '^(human|workload|agent):[^[:space:]]+$'
       OR NULLIF(btrim(p_reason), '') IS NULL THEN
        RAISE EXCEPTION 'ApprovalCase decision identity, verdict, actor and reason are invalid'
            USING ERRCODE = '22023';
    END IF;
    IF jsonb_typeof(p_details) <> 'object' THEN
        RAISE EXCEPTION 'ApprovalCase decision details must be a JSON object'
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
    IF v_case.state_version <> p_expected_state_version THEN
        RAISE EXCEPTION 'ApprovalCase state version conflict: expected %, actual %',
            p_expected_state_version, v_case.state_version
            USING ERRCODE = '40001';
    END IF;
    IF v_case.status <> 'pending' THEN
        RAISE EXCEPTION 'ApprovalCase is already terminal'
            USING ERRCODE = '23514';
    END IF;

    SELECT assignment.* INTO v_assignment
    FROM gda_control.approval_case_assignment AS assignment
    WHERE assignment.tenant_id = p_tenant_id
      AND assignment.approval_case_ref = p_approval_case_ref
    FOR SHARE;
    IF FOUND AND v_assignment.status = 'assigned'
       AND v_assignment.assignee_subject <> p_actor_subject THEN
        RAISE EXCEPTION 'ApprovalCase decision is reserved for the current assignee'
            USING ERRCODE = '42501';
    END IF;
    IF FOUND AND v_assignment.status = 'closed' THEN
        RAISE EXCEPTION 'ApprovalCase assignment is already closed'
            USING ERRCODE = '40001';
    END IF;

    v_occurred_at := clock_timestamp();
    IF v_occurred_at >= v_case.expires_at THEN
        RAISE EXCEPTION 'ApprovalCase is expired'
            USING ERRCODE = '23514';
    END IF;
    IF p_to_status IN ('approved','rejected')
       AND (
            p_actor_subject !~ '^human:[^[:space:]]+$'
            OR p_actor_subject = v_case.requester_subject
       ) THEN
        RAISE EXCEPTION 'ApprovalCase verdict requires an independent human approver'
            USING ERRCODE = '23514';
    END IF;

    PERFORM set_config('gda.approval_case_transition_allowed', '1', true);
    UPDATE gda_control.approval_case
    SET status = p_to_status,
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
        v_case.tenant_id, v_case.approval_case_ref, 1, 'pending', p_to_status,
        p_actor_subject, p_reason, p_details, v_occurred_at
    );
    RETURN 1;
EXCEPTION WHEN OTHERS THEN
    PERFORM set_config('gda.approval_case_transition_allowed', '0', true);
    RAISE;
END;
$$;

REVOKE ALL ON TABLE gda_control.approval_case_assignment
    FROM PUBLIC, gda_control_gateway;
REVOKE ALL ON TABLE gda_control.approval_case_assignment_event
    FROM PUBLIC, gda_control_gateway;
GRANT SELECT ON TABLE gda_control.approval_case_assignment
    TO gda_control_gateway;
GRANT SELECT ON TABLE gda_control.approval_case_assignment_event
    TO gda_control_gateway;

REVOKE ALL ON FUNCTION gda_control.transition_approval_case_assignment(
    TEXT, TEXT, INTEGER, TEXT, TEXT, TEXT, TEXT
) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION gda_control.transition_approval_case_assignment(
    TEXT, TEXT, INTEGER, TEXT, TEXT, TEXT, TEXT
) TO gda_control_gateway;
REVOKE ALL ON FUNCTION gda_control.close_approval_case_assignment()
    FROM PUBLIC;
