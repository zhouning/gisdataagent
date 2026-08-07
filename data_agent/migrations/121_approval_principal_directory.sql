-- 121: Tenant-scoped approval principal directory and team authority.
--
-- The collaboration tables in the public schema are not an approval
-- authority: they are not tenant scoped and do not model eligibility,
-- availability or effective time. This migration creates an independent,
-- fail-closed directory for ApprovalCase routing and decisions.

CREATE TABLE gda_control.approval_principal (
    tenant_id TEXT NOT NULL,
    principal_subject TEXT NOT NULL,
    principal_type TEXT NOT NULL,
    display_name TEXT NOT NULL,
    directory_version INTEGER NOT NULL,
    status TEXT NOT NULL,
    approval_eligible BOOLEAN NOT NULL,
    availability_status TEXT NOT NULL,
    valid_from TIMESTAMPTZ NOT NULL,
    valid_until TIMESTAMPTZ,
    last_actor_subject TEXT NOT NULL,
    last_reason TEXT NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (tenant_id, principal_subject),
    CONSTRAINT ck_gda_approval_principal_subject CHECK (
        principal_subject ~ '^(human|team):[a-z0-9][a-z0-9._-]{0,127}$'
        AND split_part(principal_subject, ':', 1) = principal_type
    ),
    CONSTRAINT ck_gda_approval_principal_type
        CHECK (principal_type IN ('human','team')),
    CONSTRAINT ck_gda_approval_principal_name
        CHECK (length(btrim(display_name)) BETWEEN 1 AND 200),
    CONSTRAINT ck_gda_approval_principal_version
        CHECK (directory_version >= 1),
    CONSTRAINT ck_gda_approval_principal_status
        CHECK (status IN ('active','inactive')),
    CONSTRAINT ck_gda_approval_principal_availability
        CHECK (availability_status IN ('available','unavailable')),
    CONSTRAINT ck_gda_approval_principal_window
        CHECK (valid_until IS NULL OR valid_until > valid_from),
    CONSTRAINT ck_gda_approval_principal_actor
        CHECK (last_actor_subject ~ '^human:[^[:space:]]+$'),
    CONSTRAINT ck_gda_approval_principal_reason
        CHECK (length(btrim(last_reason)) BETWEEN 1 AND 512)
);

CREATE INDEX idx_gda_approval_principal_candidate
    ON gda_control.approval_principal (
        tenant_id, status, approval_eligible, availability_status,
        principal_type, display_name
    );

CREATE TABLE gda_control.approval_principal_event (
    tenant_id TEXT NOT NULL,
    principal_event_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    principal_subject TEXT NOT NULL,
    directory_version INTEGER NOT NULL,
    action TEXT NOT NULL,
    actor_subject TEXT NOT NULL,
    reason TEXT NOT NULL,
    principal_snapshot JSONB NOT NULL,
    occurred_at TIMESTAMPTZ NOT NULL,
    CONSTRAINT uq_gda_approval_principal_event_tenant_id
        UNIQUE (tenant_id, principal_event_id),
    CONSTRAINT uq_gda_approval_principal_event_version
        UNIQUE (tenant_id, principal_subject, directory_version),
    CONSTRAINT fk_gda_approval_principal_event_principal
        FOREIGN KEY (tenant_id, principal_subject)
        REFERENCES gda_control.approval_principal(tenant_id, principal_subject),
    CONSTRAINT ck_gda_approval_principal_event_version
        CHECK (directory_version >= 1),
    CONSTRAINT ck_gda_approval_principal_event_action
        CHECK (action IN ('registered','updated')),
    CONSTRAINT ck_gda_approval_principal_event_actor
        CHECK (actor_subject ~ '^human:[^[:space:]]+$'),
    CONSTRAINT ck_gda_approval_principal_event_reason
        CHECK (length(btrim(reason)) BETWEEN 1 AND 512),
    CONSTRAINT ck_gda_approval_principal_event_snapshot
        CHECK (jsonb_typeof(principal_snapshot) = 'object')
);

CREATE TABLE gda_control.approval_team_member (
    tenant_id TEXT NOT NULL,
    team_subject TEXT NOT NULL,
    member_subject TEXT NOT NULL,
    membership_version INTEGER NOT NULL,
    status TEXT NOT NULL,
    can_delegate BOOLEAN NOT NULL,
    valid_from TIMESTAMPTZ NOT NULL,
    valid_until TIMESTAMPTZ,
    last_actor_subject TEXT NOT NULL,
    last_reason TEXT NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (tenant_id, team_subject, member_subject),
    CONSTRAINT fk_gda_approval_team_member_team
        FOREIGN KEY (tenant_id, team_subject)
        REFERENCES gda_control.approval_principal(tenant_id, principal_subject),
    CONSTRAINT fk_gda_approval_team_member_human
        FOREIGN KEY (tenant_id, member_subject)
        REFERENCES gda_control.approval_principal(tenant_id, principal_subject),
    CONSTRAINT ck_gda_approval_team_member_subjects CHECK (
        team_subject ~ '^team:[a-z0-9][a-z0-9._-]{0,127}$'
        AND member_subject ~ '^human:[a-z0-9][a-z0-9._-]{0,127}$'
    ),
    CONSTRAINT ck_gda_approval_team_member_version
        CHECK (membership_version >= 1),
    CONSTRAINT ck_gda_approval_team_member_status
        CHECK (status IN ('active','inactive')),
    CONSTRAINT ck_gda_approval_team_member_window
        CHECK (valid_until IS NULL OR valid_until > valid_from),
    CONSTRAINT ck_gda_approval_team_member_actor
        CHECK (last_actor_subject ~ '^human:[^[:space:]]+$'),
    CONSTRAINT ck_gda_approval_team_member_reason
        CHECK (length(btrim(last_reason)) BETWEEN 1 AND 512)
);

CREATE INDEX idx_gda_approval_team_member_active
    ON gda_control.approval_team_member (
        tenant_id, team_subject, status, member_subject
    );

CREATE TABLE gda_control.approval_team_member_event (
    tenant_id TEXT NOT NULL,
    membership_event_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    team_subject TEXT NOT NULL,
    member_subject TEXT NOT NULL,
    membership_version INTEGER NOT NULL,
    action TEXT NOT NULL,
    actor_subject TEXT NOT NULL,
    reason TEXT NOT NULL,
    membership_snapshot JSONB NOT NULL,
    occurred_at TIMESTAMPTZ NOT NULL,
    CONSTRAINT uq_gda_approval_team_member_event_tenant_id
        UNIQUE (tenant_id, membership_event_id),
    CONSTRAINT uq_gda_approval_team_member_event_version
        UNIQUE (tenant_id, team_subject, member_subject, membership_version),
    CONSTRAINT fk_gda_approval_team_member_event_member
        FOREIGN KEY (tenant_id, team_subject, member_subject)
        REFERENCES gda_control.approval_team_member(
            tenant_id, team_subject, member_subject
        ),
    CONSTRAINT ck_gda_approval_team_member_event_version
        CHECK (membership_version >= 1),
    CONSTRAINT ck_gda_approval_team_member_event_action
        CHECK (action IN ('registered','updated')),
    CONSTRAINT ck_gda_approval_team_member_event_actor
        CHECK (actor_subject ~ '^human:[^[:space:]]+$'),
    CONSTRAINT ck_gda_approval_team_member_event_reason
        CHECK (length(btrim(reason)) BETWEEN 1 AND 512),
    CONSTRAINT ck_gda_approval_team_member_event_snapshot
        CHECK (jsonb_typeof(membership_snapshot) = 'object')
);

ALTER TABLE gda_control.approval_principal ENABLE ROW LEVEL SECURITY;
ALTER TABLE gda_control.approval_principal FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON gda_control.approval_principal
    USING (tenant_id = gda_control.current_tenant())
    WITH CHECK (tenant_id = gda_control.current_tenant());

ALTER TABLE gda_control.approval_principal_event ENABLE ROW LEVEL SECURITY;
ALTER TABLE gda_control.approval_principal_event FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON gda_control.approval_principal_event
    USING (tenant_id = gda_control.current_tenant())
    WITH CHECK (tenant_id = gda_control.current_tenant());

ALTER TABLE gda_control.approval_team_member ENABLE ROW LEVEL SECURITY;
ALTER TABLE gda_control.approval_team_member FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON gda_control.approval_team_member
    USING (tenant_id = gda_control.current_tenant())
    WITH CHECK (tenant_id = gda_control.current_tenant());

ALTER TABLE gda_control.approval_team_member_event ENABLE ROW LEVEL SECURITY;
ALTER TABLE gda_control.approval_team_member_event FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON gda_control.approval_team_member_event
    USING (tenant_id = gda_control.current_tenant())
    WITH CHECK (tenant_id = gda_control.current_tenant());

CREATE TRIGGER trg_gda_approval_principal_event_immutable
BEFORE UPDATE OR DELETE ON gda_control.approval_principal_event
FOR EACH ROW EXECUTE FUNCTION gda_control.reject_immutable_mutation();

CREATE TRIGGER trg_gda_approval_team_member_event_immutable
BEFORE UPDATE OR DELETE ON gda_control.approval_team_member_event
FOR EACH ROW EXECUTE FUNCTION gda_control.reject_immutable_mutation();

CREATE OR REPLACE FUNCTION gda_control.approval_principal_eligibility_reason(
    p_tenant_id TEXT,
    p_principal_subject TEXT,
    p_at TIMESTAMPTZ DEFAULT clock_timestamp()
)
RETURNS TEXT
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog, gda_control
SET row_security = on
AS $$
DECLARE
    v_principal gda_control.approval_principal%ROWTYPE;
BEGIN
    IF gda_control.current_tenant() IS DISTINCT FROM p_tenant_id THEN
        RETURN 'tenant_mismatch';
    END IF;
    SELECT principal.* INTO v_principal
    FROM gda_control.approval_principal AS principal
    WHERE principal.tenant_id = p_tenant_id
      AND principal.principal_subject = p_principal_subject;
    IF NOT FOUND THEN
        RETURN 'not_registered';
    ELSIF v_principal.status <> 'active' THEN
        RETURN 'inactive';
    ELSIF NOT v_principal.approval_eligible THEN
        RETURN 'not_approval_eligible';
    ELSIF v_principal.availability_status <> 'available' THEN
        RETURN 'unavailable';
    ELSIF p_at < v_principal.valid_from THEN
        RETURN 'not_yet_valid';
    ELSIF v_principal.valid_until IS NOT NULL AND p_at >= v_principal.valid_until THEN
        RETURN 'expired';
    ELSIF v_principal.principal_type = 'team' AND NOT EXISTS (
        SELECT 1
        FROM gda_control.approval_team_member AS membership
        JOIN gda_control.approval_principal AS member
          ON member.tenant_id = membership.tenant_id
         AND member.principal_subject = membership.member_subject
        WHERE membership.tenant_id = p_tenant_id
          AND membership.team_subject = p_principal_subject
          AND membership.status = 'active'
          AND p_at >= membership.valid_from
          AND (membership.valid_until IS NULL OR p_at < membership.valid_until)
          AND member.principal_type = 'human'
          AND member.status = 'active'
          AND member.approval_eligible
          AND member.availability_status = 'available'
          AND p_at >= member.valid_from
          AND (member.valid_until IS NULL OR p_at < member.valid_until)
    ) THEN
        RETURN 'team_without_eligible_member';
    END IF;
    RETURN 'eligible';
END;
$$;

CREATE OR REPLACE FUNCTION gda_control.approval_principal_is_eligible(
    p_tenant_id TEXT,
    p_principal_subject TEXT,
    p_at TIMESTAMPTZ DEFAULT clock_timestamp()
)
RETURNS BOOLEAN
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog, gda_control
SET row_security = on
AS $$
    SELECT gda_control.approval_principal_eligibility_reason(
        p_tenant_id, p_principal_subject, p_at
    ) = 'eligible'
$$;

CREATE OR REPLACE FUNCTION gda_control.approval_team_authorizes_actor(
    p_tenant_id TEXT,
    p_team_subject TEXT,
    p_actor_subject TEXT,
    p_require_delegate BOOLEAN DEFAULT false,
    p_at TIMESTAMPTZ DEFAULT clock_timestamp()
)
RETURNS BOOLEAN
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog, gda_control
SET row_security = on
AS $$
    SELECT
        gda_control.current_tenant() = p_tenant_id
        AND gda_control.approval_principal_is_eligible(
            p_tenant_id, p_team_subject, p_at
        )
        AND gda_control.approval_principal_is_eligible(
            p_tenant_id, p_actor_subject, p_at
        )
        AND EXISTS (
            SELECT 1
            FROM gda_control.approval_team_member AS membership
            WHERE membership.tenant_id = p_tenant_id
              AND membership.team_subject = p_team_subject
              AND membership.member_subject = p_actor_subject
              AND membership.status = 'active'
              AND (NOT p_require_delegate OR membership.can_delegate)
              AND p_at >= membership.valid_from
              AND (membership.valid_until IS NULL OR p_at < membership.valid_until)
        )
$$;

CREATE OR REPLACE FUNCTION gda_control.upsert_approval_principal(
    p_tenant_id TEXT,
    p_principal_subject TEXT,
    p_expected_directory_version INTEGER,
    p_display_name TEXT,
    p_status TEXT,
    p_approval_eligible BOOLEAN,
    p_availability_status TEXT,
    p_valid_from TIMESTAMPTZ,
    p_valid_until TIMESTAMPTZ,
    p_actor_subject TEXT,
    p_reason TEXT
)
RETURNS SETOF gda_control.approval_principal
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, gda_control
SET row_security = on
AS $$
DECLARE
    v_principal gda_control.approval_principal%ROWTYPE;
    v_next_version INTEGER;
    v_action TEXT;
    v_occurred_at TIMESTAMPTZ := clock_timestamp();
BEGIN
    IF gda_control.current_tenant() IS DISTINCT FROM p_tenant_id
       OR p_actor_subject !~ '^human:[^[:space:]]+$' THEN
        RAISE EXCEPTION 'approval directory tenant or actor is invalid'
            USING ERRCODE = '42501';
    END IF;
    IF p_principal_subject !~ '^(human|team):[a-z0-9][a-z0-9._-]{0,127}$'
       OR length(btrim(COALESCE(p_display_name, ''))) NOT BETWEEN 1 AND 200
       OR p_status NOT IN ('active','inactive')
       OR p_availability_status NOT IN ('available','unavailable')
       OR p_expected_directory_version IS NULL
       OR p_expected_directory_version < 0
       OR p_approval_eligible IS NULL
       OR p_valid_from IS NULL
       OR (p_valid_until IS NOT NULL AND p_valid_until <= p_valid_from)
       OR length(btrim(COALESCE(p_reason, ''))) NOT BETWEEN 1 AND 512 THEN
        RAISE EXCEPTION 'approval principal contract is invalid'
            USING ERRCODE = '22023';
    END IF;

    SELECT principal.* INTO v_principal
    FROM gda_control.approval_principal AS principal
    WHERE principal.tenant_id = p_tenant_id
      AND principal.principal_subject = p_principal_subject
    FOR UPDATE;

    IF NOT FOUND THEN
        IF p_expected_directory_version <> 0 THEN
            RAISE EXCEPTION 'initial principal registration requires version zero'
                USING ERRCODE = '40001';
        END IF;
        v_next_version := 1;
        v_action := 'registered';
        INSERT INTO gda_control.approval_principal (
            tenant_id, principal_subject, principal_type, display_name,
            directory_version, status, approval_eligible, availability_status,
            valid_from, valid_until, last_actor_subject, last_reason, updated_at
        ) VALUES (
            p_tenant_id, p_principal_subject,
            split_part(p_principal_subject, ':', 1), btrim(p_display_name),
            v_next_version, p_status, p_approval_eligible,
            p_availability_status, p_valid_from, p_valid_until,
            p_actor_subject, btrim(p_reason), v_occurred_at
        ) RETURNING * INTO v_principal;
    ELSE
        IF v_principal.directory_version <> p_expected_directory_version THEN
            RAISE EXCEPTION 'approval principal directory version conflict'
                USING ERRCODE = '40001';
        END IF;
        v_next_version := v_principal.directory_version + 1;
        v_action := 'updated';
        UPDATE gda_control.approval_principal AS principal
        SET display_name = btrim(p_display_name),
            directory_version = v_next_version,
            status = p_status,
            approval_eligible = p_approval_eligible,
            availability_status = p_availability_status,
            valid_from = p_valid_from,
            valid_until = p_valid_until,
            last_actor_subject = p_actor_subject,
            last_reason = btrim(p_reason),
            updated_at = v_occurred_at
        WHERE principal.tenant_id = p_tenant_id
          AND principal.principal_subject = p_principal_subject
        RETURNING * INTO v_principal;
    END IF;

    INSERT INTO gda_control.approval_principal_event (
        tenant_id, principal_subject, directory_version, action,
        actor_subject, reason, principal_snapshot, occurred_at
    ) VALUES (
        p_tenant_id, p_principal_subject, v_next_version, v_action,
        p_actor_subject, btrim(p_reason), to_jsonb(v_principal), v_occurred_at
    );
    RETURN NEXT v_principal;
END;
$$;

CREATE OR REPLACE FUNCTION gda_control.upsert_approval_team_member(
    p_tenant_id TEXT,
    p_team_subject TEXT,
    p_member_subject TEXT,
    p_expected_membership_version INTEGER,
    p_status TEXT,
    p_can_delegate BOOLEAN,
    p_valid_from TIMESTAMPTZ,
    p_valid_until TIMESTAMPTZ,
    p_actor_subject TEXT,
    p_reason TEXT
)
RETURNS SETOF gda_control.approval_team_member
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, gda_control
SET row_security = on
AS $$
DECLARE
    v_membership gda_control.approval_team_member%ROWTYPE;
    v_next_version INTEGER;
    v_action TEXT;
    v_occurred_at TIMESTAMPTZ := clock_timestamp();
BEGIN
    IF gda_control.current_tenant() IS DISTINCT FROM p_tenant_id
       OR p_actor_subject !~ '^human:[^[:space:]]+$' THEN
        RAISE EXCEPTION 'approval team tenant or actor is invalid'
            USING ERRCODE = '42501';
    END IF;
    IF p_team_subject !~ '^team:[a-z0-9][a-z0-9._-]{0,127}$'
       OR p_member_subject !~ '^human:[a-z0-9][a-z0-9._-]{0,127}$'
       OR p_expected_membership_version IS NULL
       OR p_expected_membership_version < 0
       OR p_status NOT IN ('active','inactive')
       OR p_can_delegate IS NULL
       OR p_valid_from IS NULL
       OR (p_valid_until IS NOT NULL AND p_valid_until <= p_valid_from)
       OR length(btrim(COALESCE(p_reason, ''))) NOT BETWEEN 1 AND 512 THEN
        RAISE EXCEPTION 'approval team membership contract is invalid'
            USING ERRCODE = '22023';
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM gda_control.approval_principal
        WHERE tenant_id = p_tenant_id
          AND principal_subject = p_team_subject
          AND principal_type = 'team'
    ) OR NOT EXISTS (
        SELECT 1 FROM gda_control.approval_principal
        WHERE tenant_id = p_tenant_id
          AND principal_subject = p_member_subject
          AND principal_type = 'human'
    ) THEN
        RAISE EXCEPTION 'approval team and human principal must be registered first'
            USING ERRCODE = '23503';
    END IF;

    SELECT membership.* INTO v_membership
    FROM gda_control.approval_team_member AS membership
    WHERE membership.tenant_id = p_tenant_id
      AND membership.team_subject = p_team_subject
      AND membership.member_subject = p_member_subject
    FOR UPDATE;

    IF NOT FOUND THEN
        IF p_expected_membership_version <> 0 THEN
            RAISE EXCEPTION 'initial team membership requires version zero'
                USING ERRCODE = '40001';
        END IF;
        v_next_version := 1;
        v_action := 'registered';
        INSERT INTO gda_control.approval_team_member (
            tenant_id, team_subject, member_subject, membership_version,
            status, can_delegate, valid_from, valid_until,
            last_actor_subject, last_reason, updated_at
        ) VALUES (
            p_tenant_id, p_team_subject, p_member_subject, v_next_version,
            p_status, p_can_delegate, p_valid_from, p_valid_until,
            p_actor_subject, btrim(p_reason), v_occurred_at
        ) RETURNING * INTO v_membership;
    ELSE
        IF v_membership.membership_version <> p_expected_membership_version THEN
            RAISE EXCEPTION 'approval team membership version conflict'
                USING ERRCODE = '40001';
        END IF;
        v_next_version := v_membership.membership_version + 1;
        v_action := 'updated';
        UPDATE gda_control.approval_team_member AS membership
        SET membership_version = v_next_version,
            status = p_status,
            can_delegate = p_can_delegate,
            valid_from = p_valid_from,
            valid_until = p_valid_until,
            last_actor_subject = p_actor_subject,
            last_reason = btrim(p_reason),
            updated_at = v_occurred_at
        WHERE membership.tenant_id = p_tenant_id
          AND membership.team_subject = p_team_subject
          AND membership.member_subject = p_member_subject
        RETURNING * INTO v_membership;
    END IF;

    INSERT INTO gda_control.approval_team_member_event (
        tenant_id, team_subject, member_subject, membership_version, action,
        actor_subject, reason, membership_snapshot, occurred_at
    ) VALUES (
        p_tenant_id, p_team_subject, p_member_subject, v_next_version, v_action,
        p_actor_subject, btrim(p_reason), to_jsonb(v_membership), v_occurred_at
    );
    RETURN NEXT v_membership;
END;
$$;

-- Assignment targets are now either a registered human or a registered team.
ALTER TABLE gda_control.approval_case_assignment
    DROP CONSTRAINT ck_gda_approval_assignment_state;
ALTER TABLE gda_control.approval_case_assignment
    ADD CONSTRAINT ck_gda_approval_assignment_state CHECK (
        (status = 'assigned'
            AND assignee_subject ~ '^(human|team):[^[:space:]]+$'
            AND closed_at IS NULL)
        OR (status = 'released'
            AND assignee_subject IS NULL
            AND closed_at IS NULL)
        OR (status = 'closed' AND closed_at IS NOT NULL)
    );

ALTER TABLE gda_control.approval_case_assignment_event
    DROP CONSTRAINT ck_gda_approval_assignment_event_assignees;
ALTER TABLE gda_control.approval_case_assignment_event
    ADD CONSTRAINT ck_gda_approval_assignment_event_assignees CHECK (
        (from_assignee_subject IS NULL
            OR from_assignee_subject ~ '^(human|team):[^[:space:]]+$')
        AND (to_assignee_subject IS NULL
            OR to_assignee_subject ~ '^(human|team):[^[:space:]]+$')
    );

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
            OR p_assignee_subject !~ '^(human|team):[a-z0-9][a-z0-9._-]{0,127}$') THEN
        RAISE EXCEPTION 'assignment requires a typed human or team assignee'
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
    IF p_assignee_subject IS NOT NULL
       AND NOT gda_control.approval_principal_is_eligible(
            p_tenant_id, p_assignee_subject, v_occurred_at
       ) THEN
        RAISE EXCEPTION 'ApprovalCase assignee is not currently eligible: %',
            gda_control.approval_principal_eligibility_reason(
                p_tenant_id, p_assignee_subject, v_occurred_at
            ) USING ERRCODE = '55000';
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
        IF v_assignment.status <> 'assigned' THEN
            RAISE EXCEPTION 'delegation requires an active assignment'
                USING ERRCODE = '40001';
        END IF;
        IF (
            v_assignment.assignee_subject LIKE 'human:%'
            AND p_actor_subject <> v_assignment.assignee_subject
        ) OR (
            v_assignment.assignee_subject LIKE 'team:%'
            AND NOT gda_control.approval_team_authorizes_actor(
                p_tenant_id, v_assignment.assignee_subject,
                p_actor_subject, true, v_occurred_at
            )
        ) THEN
            RAISE EXCEPTION 'only the current assignee or team delegate may delegate'
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

CREATE OR REPLACE FUNCTION gda_control.approval_assignment_actor_access(
    p_tenant_id TEXT,
    p_approval_case_ref TEXT,
    p_actor_subject TEXT,
    p_at TIMESTAMPTZ DEFAULT clock_timestamp()
)
RETURNS TABLE (can_decide BOOLEAN, can_delegate BOOLEAN, access_reason TEXT)
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog, gda_control
SET row_security = on
AS $$
DECLARE
    v_case gda_control.approval_case%ROWTYPE;
    v_assignment gda_control.approval_case_assignment%ROWTYPE;
BEGIN
    can_decide := false;
    can_delegate := false;
    IF gda_control.current_tenant() IS DISTINCT FROM p_tenant_id THEN
        access_reason := 'tenant_mismatch';
        RETURN NEXT;
        RETURN;
    END IF;
    SELECT approval.* INTO v_case
    FROM gda_control.approval_case AS approval
    WHERE approval.tenant_id = p_tenant_id
      AND approval.approval_case_ref = p_approval_case_ref;
    IF NOT FOUND THEN
        access_reason := 'case_not_found';
        RETURN NEXT;
        RETURN;
    ELSIF v_case.status <> 'pending' OR p_at >= v_case.expires_at THEN
        access_reason := 'case_not_live';
        RETURN NEXT;
        RETURN;
    ELSIF p_actor_subject = v_case.requester_subject THEN
        access_reason := 'requester_is_not_independent';
        RETURN NEXT;
        RETURN;
    ELSIF NOT gda_control.approval_principal_is_eligible(
        p_tenant_id, p_actor_subject, p_at
    ) THEN
        access_reason := gda_control.approval_principal_eligibility_reason(
            p_tenant_id, p_actor_subject, p_at
        );
        RETURN NEXT;
        RETURN;
    END IF;

    SELECT assignment.* INTO v_assignment
    FROM gda_control.approval_case_assignment AS assignment
    WHERE assignment.tenant_id = p_tenant_id
      AND assignment.approval_case_ref = p_approval_case_ref;
    IF NOT FOUND OR v_assignment.status = 'released' THEN
        can_decide := true;
        access_reason := 'open_pool_eligible';
    ELSIF v_assignment.status = 'closed' THEN
        access_reason := 'assignment_closed';
    ELSIF v_assignment.assignee_subject LIKE 'human:%' THEN
        can_decide := v_assignment.assignee_subject = p_actor_subject;
        can_delegate := can_decide AND v_assignment.delegation_depth < 5;
        access_reason := CASE WHEN can_decide THEN 'direct_assignee' ELSE 'reserved' END;
    ELSE
        can_decide := gda_control.approval_team_authorizes_actor(
            p_tenant_id, v_assignment.assignee_subject,
            p_actor_subject, false, p_at
        );
        can_delegate := v_assignment.delegation_depth < 5
            AND gda_control.approval_team_authorizes_actor(
                p_tenant_id, v_assignment.assignee_subject,
                p_actor_subject, true, p_at
            );
        access_reason := CASE
            WHEN can_delegate THEN 'team_delegate'
            WHEN can_decide THEN 'team_member'
            ELSE 'reserved'
        END;
    END IF;
    RETURN NEXT;
END;
$$;

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

    v_occurred_at := clock_timestamp();
    SELECT assignment.* INTO v_assignment
    FROM gda_control.approval_case_assignment AS assignment
    WHERE assignment.tenant_id = p_tenant_id
      AND assignment.approval_case_ref = p_approval_case_ref
    FOR SHARE;
    IF FOUND AND v_assignment.status = 'assigned' AND (
        (v_assignment.assignee_subject LIKE 'human:%'
            AND v_assignment.assignee_subject <> p_actor_subject)
        OR (v_assignment.assignee_subject LIKE 'team:%'
            AND NOT gda_control.approval_team_authorizes_actor(
                p_tenant_id, v_assignment.assignee_subject,
                p_actor_subject, false, v_occurred_at
            ))
    ) THEN
        RAISE EXCEPTION 'ApprovalCase decision is reserved for the current assignee'
            USING ERRCODE = '42501';
    END IF;
    IF FOUND AND v_assignment.status = 'closed' THEN
        RAISE EXCEPTION 'ApprovalCase assignment is already closed'
            USING ERRCODE = '40001';
    END IF;

    IF v_occurred_at >= v_case.expires_at THEN
        RAISE EXCEPTION 'ApprovalCase is expired'
            USING ERRCODE = '23514';
    END IF;
    IF p_actor_subject LIKE 'human:%'
       AND NOT gda_control.approval_principal_is_eligible(
            p_tenant_id, p_actor_subject, v_occurred_at
       ) THEN
        RAISE EXCEPTION 'ApprovalCase human decision requires a currently eligible principal'
            USING ERRCODE = '23514';
    END IF;
    IF p_to_status IN ('approved','rejected') AND (
        p_actor_subject !~ '^human:[^[:space:]]+$'
        OR p_actor_subject = v_case.requester_subject
    ) THEN
        RAISE EXCEPTION 'ApprovalCase verdict requires an eligible independent human approver'
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

REVOKE ALL ON TABLE gda_control.approval_principal
    FROM PUBLIC, gda_control_gateway;
REVOKE ALL ON TABLE gda_control.approval_principal_event
    FROM PUBLIC, gda_control_gateway;
REVOKE ALL ON TABLE gda_control.approval_team_member
    FROM PUBLIC, gda_control_gateway;
REVOKE ALL ON TABLE gda_control.approval_team_member_event
    FROM PUBLIC, gda_control_gateway;
GRANT SELECT ON TABLE gda_control.approval_principal
    TO gda_control_gateway;
GRANT SELECT ON TABLE gda_control.approval_principal_event
    TO gda_control_gateway;
GRANT SELECT ON TABLE gda_control.approval_team_member
    TO gda_control_gateway;
GRANT SELECT ON TABLE gda_control.approval_team_member_event
    TO gda_control_gateway;

REVOKE ALL ON FUNCTION gda_control.approval_principal_eligibility_reason(
    TEXT, TEXT, TIMESTAMPTZ
) FROM PUBLIC;
REVOKE ALL ON FUNCTION gda_control.approval_principal_is_eligible(
    TEXT, TEXT, TIMESTAMPTZ
) FROM PUBLIC;
REVOKE ALL ON FUNCTION gda_control.approval_team_authorizes_actor(
    TEXT, TEXT, TEXT, BOOLEAN, TIMESTAMPTZ
) FROM PUBLIC;
REVOKE ALL ON FUNCTION gda_control.upsert_approval_principal(
    TEXT, TEXT, INTEGER, TEXT, TEXT, BOOLEAN, TEXT,
    TIMESTAMPTZ, TIMESTAMPTZ, TEXT, TEXT
) FROM PUBLIC;
REVOKE ALL ON FUNCTION gda_control.upsert_approval_team_member(
    TEXT, TEXT, TEXT, INTEGER, TEXT, BOOLEAN,
    TIMESTAMPTZ, TIMESTAMPTZ, TEXT, TEXT
) FROM PUBLIC;
REVOKE ALL ON FUNCTION gda_control.approval_assignment_actor_access(
    TEXT, TEXT, TEXT, TIMESTAMPTZ
) FROM PUBLIC;

GRANT EXECUTE ON FUNCTION gda_control.approval_principal_eligibility_reason(
    TEXT, TEXT, TIMESTAMPTZ
) TO gda_control_gateway;
GRANT EXECUTE ON FUNCTION gda_control.approval_principal_is_eligible(
    TEXT, TEXT, TIMESTAMPTZ
) TO gda_control_gateway;
GRANT EXECUTE ON FUNCTION gda_control.approval_team_authorizes_actor(
    TEXT, TEXT, TEXT, BOOLEAN, TIMESTAMPTZ
) TO gda_control_gateway;
GRANT EXECUTE ON FUNCTION gda_control.upsert_approval_principal(
    TEXT, TEXT, INTEGER, TEXT, TEXT, BOOLEAN, TEXT,
    TIMESTAMPTZ, TIMESTAMPTZ, TEXT, TEXT
) TO gda_control_gateway;
GRANT EXECUTE ON FUNCTION gda_control.upsert_approval_team_member(
    TEXT, TEXT, TEXT, INTEGER, TEXT, BOOLEAN,
    TIMESTAMPTZ, TIMESTAMPTZ, TEXT, TEXT
) TO gda_control_gateway;
GRANT EXECUTE ON FUNCTION gda_control.approval_assignment_actor_access(
    TEXT, TEXT, TEXT, TIMESTAMPTZ
) TO gda_control_gateway;

COMMENT ON TABLE gda_control.approval_principal IS
    'Tenant-scoped authority for human and team ApprovalCase eligibility.';
COMMENT ON TABLE gda_control.approval_team_member IS
    'Effective-time team membership used for ApprovalCase decision and delegation.';
COMMENT ON FUNCTION gda_control.approval_assignment_actor_access(
    TEXT, TEXT, TEXT, TIMESTAMPTZ
) IS 'Resolves current human access without creating an approval verdict.';
