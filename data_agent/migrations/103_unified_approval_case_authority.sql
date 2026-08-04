-- 103: Unified, tenant-scoped ApprovalCase authority.
--
-- ApprovalCase owns one immutable target/action binding and one terminal human
-- verdict. Domain projections may consume that verdict, but may not manufacture
-- approval state from an unverified ResourceURN string.

CREATE TABLE IF NOT EXISTS gda_control.approval_case (
    tenant_id TEXT NOT NULL,
    approval_case_ref TEXT PRIMARY KEY,
    target_resource_urn TEXT NOT NULL,
    target_fingerprint CHAR(64) NOT NULL,
    action TEXT NOT NULL,
    requester_subject TEXT NOT NULL,
    request_reason TEXT NOT NULL,
    request_context JSONB NOT NULL DEFAULT '{}'::jsonb,
    status TEXT NOT NULL DEFAULT 'pending',
    state_version INTEGER NOT NULL DEFAULT 0,
    requested_at TIMESTAMPTZ NOT NULL,
    expires_at TIMESTAMPTZ NOT NULL,
    decided_by TEXT,
    decision_reason TEXT,
    decided_at TIMESTAMPTZ,
    updated_at TIMESTAMPTZ NOT NULL,
    CONSTRAINT uq_gda_approval_case_tenant_ref
        UNIQUE (tenant_id, approval_case_ref),
    CONSTRAINT fk_gda_approval_case_resource
        FOREIGN KEY (tenant_id, approval_case_ref)
        REFERENCES gda_control.resource(tenant_id, resource_urn),
    CONSTRAINT ck_gda_approval_case_tenant
        CHECK (tenant_id ~ '^[a-z0-9][a-z0-9._-]{0,63}$'),
    CONSTRAINT ck_gda_approval_case_ref CHECK (
        approval_case_ref ~ '^gda://[a-z0-9][a-z0-9._-]{0,63}/approval_case/[a-z0-9][a-z0-9._-]{0,127}$'
        AND split_part(approval_case_ref, '/', 3) = tenant_id
    ),
    CONSTRAINT ck_gda_approval_case_target CHECK (
        target_resource_urn ~ '^gda://[a-z0-9][a-z0-9._-]{0,63}/[a-z][a-z0-9_-]{1,31}/[a-z0-9][a-z0-9._-]{0,127}$'
        AND split_part(target_resource_urn, '/', 3) = tenant_id
    ),
    CONSTRAINT ck_gda_approval_case_target_sha
        CHECK (target_fingerprint ~ '^[0-9a-f]{64}$'),
    CONSTRAINT ck_gda_approval_case_action
        CHECK (action ~ '^[a-zA-Z0-9][a-zA-Z0-9._:-]{0,127}$'),
    CONSTRAINT ck_gda_approval_case_requester
        CHECK (requester_subject ~ '^(human|workload|agent):[^[:space:]]+$'),
    CONSTRAINT ck_gda_approval_case_request_reason
        CHECK (NULLIF(btrim(request_reason), '') IS NOT NULL),
    CONSTRAINT ck_gda_approval_case_context
        CHECK (jsonb_typeof(request_context) = 'object'),
    CONSTRAINT ck_gda_approval_case_status
        CHECK (status IN ('pending','approved','rejected','cancelled')),
    CONSTRAINT ck_gda_approval_case_state_version
        CHECK (state_version IN (0, 1)),
    CONSTRAINT ck_gda_approval_case_state CHECK (
        (
            state_version = 0
            AND status = 'pending'
            AND decided_by IS NULL
            AND decision_reason IS NULL
            AND decided_at IS NULL
        ) OR (
            state_version = 1
            AND status IN ('approved','rejected','cancelled')
            AND decided_by IS NOT NULL
            AND decision_reason IS NOT NULL
            AND decided_at IS NOT NULL
        )
    ),
    CONSTRAINT ck_gda_approval_case_decider CHECK (
        status NOT IN ('approved','rejected')
        OR (
            decided_by ~ '^human:[^[:space:]]+$'
            AND decided_by <> requester_subject
        )
    ),
    CONSTRAINT ck_gda_approval_case_time CHECK (
        expires_at > requested_at
        AND updated_at >= requested_at
        AND (
            decided_at IS NULL
            OR (decided_at >= requested_at AND decided_at < expires_at)
        )
    )
);

CREATE INDEX IF NOT EXISTS idx_gda_approval_case_inbox
    ON gda_control.approval_case(tenant_id, status, expires_at, requested_at);
CREATE INDEX IF NOT EXISTS idx_gda_approval_case_target
    ON gda_control.approval_case(
        tenant_id, target_resource_urn, target_fingerprint, action
    );

CREATE TABLE IF NOT EXISTS gda_control.approval_case_event (
    tenant_id TEXT NOT NULL,
    approval_event_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    approval_case_ref TEXT NOT NULL,
    sequence_no INTEGER NOT NULL,
    from_status TEXT,
    to_status TEXT NOT NULL,
    actor_subject TEXT NOT NULL,
    reason TEXT NOT NULL,
    details JSONB NOT NULL DEFAULT '{}'::jsonb,
    occurred_at TIMESTAMPTZ NOT NULL,
    CONSTRAINT uq_gda_approval_case_event_tenant_id
        UNIQUE (tenant_id, approval_event_id),
    CONSTRAINT uq_gda_approval_case_event_sequence
        UNIQUE (tenant_id, approval_case_ref, sequence_no),
    CONSTRAINT fk_gda_approval_case_event_case
        FOREIGN KEY (tenant_id, approval_case_ref)
        REFERENCES gda_control.approval_case(tenant_id, approval_case_ref),
    CONSTRAINT ck_gda_approval_case_event_sequence
        CHECK (sequence_no IN (0, 1)),
    CONSTRAINT ck_gda_approval_case_event_from_status CHECK (
        from_status IS NULL OR from_status = 'pending'
    ),
    CONSTRAINT ck_gda_approval_case_event_to_status CHECK (
        to_status IN ('pending','approved','rejected','cancelled')
    ),
    CONSTRAINT ck_gda_approval_case_event_transition CHECK (
        (
            sequence_no = 0
            AND from_status IS NULL
            AND to_status = 'pending'
        ) OR (
            sequence_no = 1
            AND from_status = 'pending'
            AND to_status IN ('approved','rejected','cancelled')
        )
    ),
    CONSTRAINT ck_gda_approval_case_event_actor
        CHECK (actor_subject ~ '^(human|workload|agent):[^[:space:]]+$'),
    CONSTRAINT ck_gda_approval_case_event_human_verdict CHECK (
        to_status NOT IN ('approved','rejected')
        OR actor_subject ~ '^human:[^[:space:]]+$'
    ),
    CONSTRAINT ck_gda_approval_case_event_reason
        CHECK (NULLIF(btrim(reason), '') IS NOT NULL),
    CONSTRAINT ck_gda_approval_case_event_details
        CHECK (jsonb_typeof(details) = 'object')
);

CREATE INDEX IF NOT EXISTS idx_gda_approval_case_event_case
    ON gda_control.approval_case_event(
        tenant_id, approval_case_ref, sequence_no
    );

CREATE OR REPLACE FUNCTION gda_control.guard_approval_case_insert()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
DECLARE
    v_resource gda_control.resource%ROWTYPE;
BEGIN
    IF gda_control.current_tenant() IS NULL
       OR NEW.tenant_id IS DISTINCT FROM gda_control.current_tenant() THEN
        RAISE EXCEPTION 'ApprovalCase tenant context is missing or mismatched'
            USING ERRCODE = '42501';
    END IF;
    IF NEW.state_version <> 0
       OR NEW.status <> 'pending'
       OR NEW.decided_by IS NOT NULL
       OR NEW.decision_reason IS NOT NULL
       OR NEW.decided_at IS NOT NULL
       OR NEW.updated_at IS DISTINCT FROM NEW.requested_at THEN
        RAISE EXCEPTION 'ApprovalCase has an invalid initial state'
            USING ERRCODE = '23514';
    END IF;
    SELECT * INTO v_resource
    FROM gda_control.resource
    WHERE tenant_id = NEW.tenant_id
      AND resource_urn = NEW.approval_case_ref;
    IF NOT FOUND
       OR v_resource.resource_kind <> 'approval_case'
       OR v_resource.authority_system <> 'gda_control'
       OR v_resource.authority_locator <> NEW.approval_case_ref THEN
        RAISE EXCEPTION 'ApprovalCase requires its canonical authority Resource'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION gda_control.initialize_approval_case_event()
RETURNS TRIGGER
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, gda_control
SET row_security = on
AS $$
BEGIN
    IF gda_control.current_tenant() IS NULL
       OR NEW.tenant_id IS DISTINCT FROM gda_control.current_tenant() THEN
        RAISE EXCEPTION 'ApprovalCase tenant context is missing or mismatched'
            USING ERRCODE = '42501';
    END IF;
    INSERT INTO gda_control.approval_case_event (
        tenant_id, approval_case_ref, sequence_no, from_status, to_status,
        actor_subject, reason, details, occurred_at
    ) VALUES (
        NEW.tenant_id, NEW.approval_case_ref, 0, NULL, 'pending',
        NEW.requester_subject, NEW.request_reason,
        jsonb_build_object(
            'target_resource_urn', NEW.target_resource_urn,
            'target_fingerprint', NEW.target_fingerprint,
            'action', NEW.action,
            'request_context', NEW.request_context
        ),
        NEW.requested_at
    );
    RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION gda_control.guard_approval_case_update()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    IF COALESCE(current_setting('gda.approval_case_transition_allowed', true), '') <> '1' THEN
        RAISE EXCEPTION 'use gda_control.transition_approval_case()'
            USING ERRCODE = '55000';
    END IF;
    IF NEW.tenant_id IS DISTINCT FROM OLD.tenant_id
       OR NEW.approval_case_ref IS DISTINCT FROM OLD.approval_case_ref
       OR NEW.target_resource_urn IS DISTINCT FROM OLD.target_resource_urn
       OR NEW.target_fingerprint IS DISTINCT FROM OLD.target_fingerprint
       OR NEW.action IS DISTINCT FROM OLD.action
       OR NEW.requester_subject IS DISTINCT FROM OLD.requester_subject
       OR NEW.request_reason IS DISTINCT FROM OLD.request_reason
       OR NEW.request_context IS DISTINCT FROM OLD.request_context
       OR NEW.requested_at IS DISTINCT FROM OLD.requested_at
       OR NEW.expires_at IS DISTINCT FROM OLD.expires_at THEN
        RAISE EXCEPTION 'immutable ApprovalCase scope cannot be changed'
            USING ERRCODE = '55000';
    END IF;
    IF NEW.state_version <> OLD.state_version + 1
       OR OLD.status <> 'pending'
       OR NEW.status NOT IN ('approved','rejected','cancelled') THEN
        RAISE EXCEPTION 'ApprovalCase transition must record one terminal decision'
            USING ERRCODE = '40001';
    END IF;
    RETURN NEW;
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

    SELECT * INTO v_case
    FROM gda_control.approval_case
    WHERE tenant_id = p_tenant_id
      AND approval_case_ref = p_approval_case_ref
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

DROP TRIGGER IF EXISTS trg_gda_approval_case_insert_guard
    ON gda_control.approval_case;
CREATE TRIGGER trg_gda_approval_case_insert_guard
BEFORE INSERT ON gda_control.approval_case
FOR EACH ROW EXECUTE FUNCTION gda_control.guard_approval_case_insert();

DROP TRIGGER IF EXISTS trg_gda_approval_case_initialize
    ON gda_control.approval_case;
CREATE TRIGGER trg_gda_approval_case_initialize
AFTER INSERT ON gda_control.approval_case
FOR EACH ROW EXECUTE FUNCTION gda_control.initialize_approval_case_event();

DROP TRIGGER IF EXISTS trg_gda_approval_case_update_guard
    ON gda_control.approval_case;
CREATE TRIGGER trg_gda_approval_case_update_guard
BEFORE UPDATE ON gda_control.approval_case
FOR EACH ROW EXECUTE FUNCTION gda_control.guard_approval_case_update();

DROP TRIGGER IF EXISTS trg_gda_approval_case_delete_guard
    ON gda_control.approval_case;
CREATE TRIGGER trg_gda_approval_case_delete_guard
BEFORE DELETE ON gda_control.approval_case
FOR EACH ROW EXECUTE FUNCTION gda_control.reject_immutable_mutation();

DROP TRIGGER IF EXISTS trg_gda_approval_case_event_immutable
    ON gda_control.approval_case_event;
CREATE TRIGGER trg_gda_approval_case_event_immutable
BEFORE UPDATE OR DELETE ON gda_control.approval_case_event
FOR EACH ROW EXECUTE FUNCTION gda_control.reject_immutable_mutation();

ALTER TABLE gda_control.approval_case ENABLE ROW LEVEL SECURITY;
ALTER TABLE gda_control.approval_case FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON gda_control.approval_case;
CREATE POLICY tenant_isolation ON gda_control.approval_case
USING (tenant_id = gda_control.current_tenant())
WITH CHECK (tenant_id = gda_control.current_tenant());

ALTER TABLE gda_control.approval_case_event ENABLE ROW LEVEL SECURITY;
ALTER TABLE gda_control.approval_case_event FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON gda_control.approval_case_event;
CREATE POLICY tenant_isolation ON gda_control.approval_case_event
USING (tenant_id = gda_control.current_tenant())
WITH CHECK (tenant_id = gda_control.current_tenant());

REVOKE ALL ON TABLE gda_control.approval_case
    FROM PUBLIC, gda_control_gateway;
REVOKE ALL ON TABLE gda_control.approval_case_event
    FROM PUBLIC, gda_control_gateway;
GRANT SELECT, INSERT ON gda_control.approval_case
    TO gda_control_gateway;
GRANT SELECT ON gda_control.approval_case_event
    TO gda_control_gateway;

REVOKE ALL ON FUNCTION gda_control.guard_approval_case_insert()
    FROM PUBLIC;
REVOKE ALL ON FUNCTION gda_control.initialize_approval_case_event()
    FROM PUBLIC;
REVOKE ALL ON FUNCTION gda_control.guard_approval_case_update()
    FROM PUBLIC;
REVOKE ALL ON FUNCTION gda_control.transition_approval_case(
    TEXT, TEXT, INTEGER, TEXT, TEXT, TEXT, JSONB
) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION gda_control.transition_approval_case(
    TEXT, TEXT, INTEGER, TEXT, TEXT, TEXT, JSONB
) TO gda_control_gateway;

-- Historical migration-102 rows are not rewritten. NOT VALID enforces this FK
-- for all new lifecycle events without inventing ApprovalCase truth for old refs.
ALTER TABLE gda_control.source_schema_drift_lifecycle_event
    DROP CONSTRAINT IF EXISTS fk_gda_source_drift_lifecycle_approval_case;
ALTER TABLE gda_control.source_schema_drift_lifecycle_event
    ADD CONSTRAINT fk_gda_source_drift_lifecycle_approval_case
    FOREIGN KEY (tenant_id, approval_case_ref)
    REFERENCES gda_control.approval_case(tenant_id, approval_case_ref)
    NOT VALID;

CREATE OR REPLACE FUNCTION gda_control.transition_source_schema_drift(
    p_tenant_id TEXT,
    p_drift_event_id TEXT,
    p_expected_state_version INTEGER,
    p_to_status TEXT,
    p_actor_subject TEXT,
    p_reason TEXT,
    p_approval_case_ref TEXT DEFAULT NULL,
    p_details JSONB DEFAULT '{}'::jsonb
)
RETURNS INTEGER
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, gda_control
SET row_security = on
AS $$
DECLARE
    v_drift gda_control.source_schema_drift%ROWTYPE;
    v_approval gda_control.approval_case%ROWTYPE;
    v_allowed BOOLEAN := FALSE;
    v_new_version INTEGER;
    v_occurred_at TIMESTAMPTZ;
    v_expected_target TEXT;
BEGIN
    IF gda_control.current_tenant() IS NULL
       OR p_tenant_id IS DISTINCT FROM gda_control.current_tenant() THEN
        RAISE EXCEPTION 'source schema drift tenant context is missing or mismatched'
            USING ERRCODE = '42501';
    END IF;
    IF p_drift_event_id IS NULL
       OR p_drift_event_id !~ '^[0-9a-f]{64}$'
       OR NULLIF(btrim(p_actor_subject), '') IS NULL
       OR NULLIF(btrim(p_reason), '') IS NULL THEN
        RAISE EXCEPTION 'drift identity, transition actor and reason are required'
            USING ERRCODE = '22023';
    END IF;
    IF jsonb_typeof(p_details) <> 'object' THEN
        RAISE EXCEPTION 'schema drift transition details must be a JSON object'
            USING ERRCODE = '22023';
    END IF;
    IF p_to_status IN ('approved','rejected') THEN
        IF p_approval_case_ref IS NULL
           OR p_approval_case_ref !~ '^gda://[a-z0-9][a-z0-9._-]{0,63}/approval_case/[a-z0-9][a-z0-9._-]{0,127}$'
           OR split_part(p_approval_case_ref, '/', 3) <> p_tenant_id THEN
            RAISE EXCEPTION 'drift verdict requires a tenant ApprovalCase reference'
                USING ERRCODE = '23514';
        END IF;
    ELSIF p_approval_case_ref IS NOT NULL THEN
        RAISE EXCEPTION 'ApprovalCase reference is only valid for a drift verdict'
            USING ERRCODE = '23514';
    END IF;

    SELECT * INTO v_drift
    FROM gda_control.source_schema_drift
    WHERE tenant_id = p_tenant_id AND drift_event_id = p_drift_event_id
    FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'source schema drift % not found', p_drift_event_id
            USING ERRCODE = 'P0002';
    END IF;
    IF v_drift.state_version <> p_expected_state_version THEN
        RAISE EXCEPTION 'schema drift state version conflict: expected %, actual %',
            p_expected_state_version, v_drift.state_version
            USING ERRCODE = '40001';
    END IF;

    v_allowed := CASE v_drift.status
        WHEN 'observed' THEN p_to_status = 'reconciled'
        WHEN 'approval_required' THEN p_to_status IN ('approved','rejected')
        WHEN 'approved' THEN p_to_status = 'reconciled'
        ELSE FALSE
    END;
    IF NOT v_allowed THEN
        RAISE EXCEPTION 'invalid schema drift transition % -> %',
            v_drift.status, p_to_status
            USING ERRCODE = '23514';
    END IF;

    v_occurred_at := clock_timestamp();
    IF p_to_status IN ('approved','rejected') THEN
        SELECT * INTO v_approval
        FROM gda_control.approval_case
        WHERE tenant_id = p_tenant_id
          AND approval_case_ref = p_approval_case_ref;
        IF NOT FOUND THEN
            RAISE EXCEPTION 'ApprovalCase % not found', p_approval_case_ref
                USING ERRCODE = '23514';
        END IF;
        v_expected_target := 'gda://' || p_tenant_id
            || '/schema_drift/' || p_drift_event_id;
        IF v_approval.target_resource_urn <> v_expected_target
           OR v_approval.target_fingerprint <> p_drift_event_id
           OR v_approval.action <> 'source_schema_drift.reconcile'
           OR v_approval.status <> p_to_status
           OR v_approval.decided_by <> p_actor_subject
           OR v_approval.decision_reason <> p_reason
           OR v_approval.decided_at IS NULL
           OR v_occurred_at >= v_approval.expires_at THEN
            RAISE EXCEPTION 'ApprovalCase does not authorize this drift verdict'
                USING ERRCODE = '23514';
        END IF;
    END IF;

    v_new_version := v_drift.state_version + 1;
    PERFORM set_config('gda.schema_drift_transition_allowed', '1', true);
    UPDATE gda_control.source_schema_drift
    SET status = p_to_status,
        state_version = v_new_version,
        updated_at = v_occurred_at
    WHERE tenant_id = p_tenant_id AND drift_event_id = p_drift_event_id;
    PERFORM set_config('gda.schema_drift_transition_allowed', '0', true);

    INSERT INTO gda_control.source_schema_drift_lifecycle_event (
        tenant_id, drift_event_id, sequence_no, from_status, to_status,
        actor_subject, reason, approval_case_ref, details, occurred_at
    ) VALUES (
        v_drift.tenant_id, v_drift.drift_event_id, v_new_version,
        v_drift.status, p_to_status, p_actor_subject, p_reason,
        p_approval_case_ref, p_details, v_occurred_at
    );
    RETURN v_new_version;
EXCEPTION WHEN OTHERS THEN
    PERFORM set_config('gda.schema_drift_transition_allowed', '0', true);
    RAISE;
END;
$$;

REVOKE ALL ON FUNCTION gda_control.transition_source_schema_drift(
    TEXT, TEXT, INTEGER, TEXT, TEXT, TEXT, TEXT, JSONB
) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION gda_control.transition_source_schema_drift(
    TEXT, TEXT, INTEGER, TEXT, TEXT, TEXT, TEXT, JSONB
) TO gda_control_gateway;
