-- 110: Tenant-scoped, append-only security event hash chain.
--
-- Operational agent_audit_log remains useful for dashboards and retention, but
-- sensitive platform actions need durable admission evidence before execution.
-- Only the least-privilege gateway function may append events. Direct writes,
-- updates and deletes are denied.

CREATE EXTENSION IF NOT EXISTS pgcrypto WITH SCHEMA public;

CREATE TABLE gda_control.security_event (
    tenant_id TEXT NOT NULL,
    event_id UUID NOT NULL,
    sequence_no BIGINT NOT NULL,
    attempt_id UUID NOT NULL,
    phase TEXT NOT NULL,
    action TEXT NOT NULL,
    outcome TEXT NOT NULL,
    actor_subject TEXT NOT NULL,
    resource_ref TEXT NOT NULL,
    reason TEXT NOT NULL,
    details JSONB NOT NULL DEFAULT '{}'::jsonb,
    previous_event_sha256 TEXT,
    event_sha256 TEXT NOT NULL,
    occurred_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (tenant_id, event_id),
    CONSTRAINT uq_gda_security_event_sequence
        UNIQUE (tenant_id, sequence_no),
    CONSTRAINT uq_gda_security_event_attempt_phase
        UNIQUE (tenant_id, attempt_id, phase),
    CONSTRAINT uq_gda_security_event_sha256
        UNIQUE (tenant_id, event_sha256),
    CONSTRAINT ck_gda_security_event_tenant
        CHECK (tenant_id ~ '^[a-z0-9][a-z0-9._-]{0,63}$'),
    CONSTRAINT ck_gda_security_event_sequence
        CHECK (sequence_no >= 0),
    CONSTRAINT ck_gda_security_event_phase
        CHECK (phase IN ('admitted', 'outcome', 'denied')),
    CONSTRAINT ck_gda_security_event_action
        CHECK (action ~ '^[a-z][a-z0-9_.:-]{1,127}$'),
    CONSTRAINT ck_gda_security_event_outcome
        CHECK (
            (phase = 'admitted' AND outcome = 'admitted')
            OR (phase = 'outcome' AND outcome IN ('success', 'failure'))
            OR (phase = 'denied' AND outcome = 'denied')
        ),
    CONSTRAINT ck_gda_security_event_actor
        CHECK (actor_subject ~ '^(human|workload|agent):[^[:space:]]+$'),
    CONSTRAINT ck_gda_security_event_resource
        CHECK (length(btrim(resource_ref)) BETWEEN 1 AND 512),
    CONSTRAINT ck_gda_security_event_reason
        CHECK (length(btrim(reason)) BETWEEN 1 AND 512),
    CONSTRAINT ck_gda_security_event_details
        CHECK (jsonb_typeof(details) = 'object'),
    CONSTRAINT ck_gda_security_event_previous_sha256
        CHECK (
            previous_event_sha256 IS NULL
            OR previous_event_sha256 ~ '^[0-9a-f]{64}$'
        ),
    CONSTRAINT ck_gda_security_event_sha256
        CHECK (event_sha256 ~ '^[0-9a-f]{64}$')
);

CREATE INDEX idx_gda_security_event_attempt
    ON gda_control.security_event(tenant_id, attempt_id, sequence_no);
CREATE INDEX idx_gda_security_event_action_time
    ON gda_control.security_event(tenant_id, action, occurred_at DESC);

CREATE OR REPLACE FUNCTION gda_control.security_event_fingerprint(
    p_tenant_id TEXT,
    p_event_id UUID,
    p_sequence_no BIGINT,
    p_attempt_id UUID,
    p_phase TEXT,
    p_action TEXT,
    p_outcome TEXT,
    p_actor_subject TEXT,
    p_resource_ref TEXT,
    p_reason TEXT,
    p_details JSONB,
    p_previous_event_sha256 TEXT,
    p_occurred_at TIMESTAMPTZ
)
RETURNS TEXT
LANGUAGE sql
IMMUTABLE
SET search_path = pg_catalog, public
AS $$
    SELECT encode(
        digest(
            convert_to(
                jsonb_build_object(
                    'tenant_id', p_tenant_id,
                    'event_id', p_event_id::text,
                    'sequence_no', p_sequence_no,
                    'attempt_id', p_attempt_id::text,
                    'phase', p_phase,
                    'action', p_action,
                    'outcome', p_outcome,
                    'actor_subject', p_actor_subject,
                    'resource_ref', p_resource_ref,
                    'reason', p_reason,
                    'details', p_details,
                    'previous_event_sha256', p_previous_event_sha256,
                    'occurred_at', to_char(
                        p_occurred_at AT TIME ZONE 'UTC',
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

CREATE OR REPLACE FUNCTION gda_control.append_security_event(
    p_tenant_id TEXT,
    p_attempt_id UUID,
    p_phase TEXT,
    p_action TEXT,
    p_outcome TEXT,
    p_actor_subject TEXT,
    p_resource_ref TEXT,
    p_reason TEXT,
    p_details JSONB DEFAULT '{}'::jsonb
)
RETURNS TABLE (
    result_event_id UUID,
    result_sequence_no BIGINT,
    result_previous_event_sha256 TEXT,
    result_event_sha256 TEXT,
    result_occurred_at TIMESTAMPTZ,
    result_inserted BOOLEAN
)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public, gda_control
SET row_security = on
SET TimeZone = 'UTC'
AS $$
DECLARE
    v_existing gda_control.security_event%ROWTYPE;
    v_event_id UUID;
    v_sequence_no BIGINT;
    v_previous_event_sha256 TEXT;
    v_event_sha256 TEXT;
    v_occurred_at TIMESTAMPTZ;
BEGIN
    IF gda_control.current_tenant() IS NULL
       OR p_tenant_id IS DISTINCT FROM gda_control.current_tenant() THEN
        RAISE EXCEPTION 'security event tenant context is missing or mismatched'
            USING ERRCODE = '42501';
    END IF;
    IF p_attempt_id IS NULL
       OR NULLIF(btrim(p_action), '') IS NULL
       OR NULLIF(btrim(p_actor_subject), '') IS NULL
       OR NULLIF(btrim(p_resource_ref), '') IS NULL
       OR NULLIF(btrim(p_reason), '') IS NULL
       OR jsonb_typeof(p_details) IS DISTINCT FROM 'object' THEN
        RAISE EXCEPTION 'security event fields are incomplete'
            USING ERRCODE = '22023';
    END IF;
    IF NOT (
        (p_phase = 'admitted' AND p_outcome = 'admitted')
        OR (p_phase = 'outcome' AND p_outcome IN ('success', 'failure'))
        OR (p_phase = 'denied' AND p_outcome = 'denied')
    ) THEN
        RAISE EXCEPTION 'security event phase/outcome is invalid'
            USING ERRCODE = '22023';
    END IF;

    PERFORM pg_advisory_xact_lock(
        hashtextextended('gda-security-event:' || p_tenant_id, 0)
    );

    SELECT security_event.* INTO v_existing
    FROM gda_control.security_event AS security_event
    WHERE security_event.tenant_id = p_tenant_id
      AND security_event.attempt_id = p_attempt_id
      AND security_event.phase = p_phase;

    IF FOUND THEN
        IF v_existing.action IS DISTINCT FROM p_action
           OR v_existing.outcome IS DISTINCT FROM p_outcome
           OR v_existing.actor_subject IS DISTINCT FROM p_actor_subject
           OR v_existing.resource_ref IS DISTINCT FROM p_resource_ref
           OR v_existing.reason IS DISTINCT FROM p_reason
           OR v_existing.details IS DISTINCT FROM p_details THEN
            RAISE EXCEPTION 'security event idempotency conflict'
                USING ERRCODE = '40001';
        END IF;
        RETURN QUERY SELECT
            v_existing.event_id,
            v_existing.sequence_no,
            v_existing.previous_event_sha256,
            v_existing.event_sha256,
            v_existing.occurred_at,
            FALSE;
        RETURN;
    END IF;

    SELECT
        security_event.sequence_no + 1,
        security_event.event_sha256
    INTO v_sequence_no, v_previous_event_sha256
    FROM gda_control.security_event AS security_event
    WHERE security_event.tenant_id = p_tenant_id
    ORDER BY security_event.sequence_no DESC
    LIMIT 1;

    IF NOT FOUND THEN
        v_sequence_no := 0;
        v_previous_event_sha256 := NULL;
    END IF;

    v_event_id := gen_random_uuid();
    v_occurred_at := clock_timestamp();
    v_event_sha256 := gda_control.security_event_fingerprint(
        p_tenant_id,
        v_event_id,
        v_sequence_no,
        p_attempt_id,
        p_phase,
        p_action,
        p_outcome,
        p_actor_subject,
        p_resource_ref,
        p_reason,
        p_details,
        v_previous_event_sha256,
        v_occurred_at
    );

    INSERT INTO gda_control.security_event (
        tenant_id,
        event_id,
        sequence_no,
        attempt_id,
        phase,
        action,
        outcome,
        actor_subject,
        resource_ref,
        reason,
        details,
        previous_event_sha256,
        event_sha256,
        occurred_at
    ) VALUES (
        p_tenant_id,
        v_event_id,
        v_sequence_no,
        p_attempt_id,
        p_phase,
        p_action,
        p_outcome,
        p_actor_subject,
        p_resource_ref,
        p_reason,
        p_details,
        v_previous_event_sha256,
        v_event_sha256,
        v_occurred_at
    );

    RETURN QUERY SELECT
        v_event_id,
        v_sequence_no,
        v_previous_event_sha256,
        v_event_sha256,
        v_occurred_at,
        TRUE;
END
$$;

CREATE OR REPLACE FUNCTION gda_control.verify_security_event_chain(
    p_tenant_id TEXT
)
RETURNS BOOLEAN
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public, gda_control
SET row_security = on
SET TimeZone = 'UTC'
AS $$
DECLARE
    v_valid BOOLEAN;
BEGIN
    IF gda_control.current_tenant() IS NULL
       OR p_tenant_id IS DISTINCT FROM gda_control.current_tenant() THEN
        RAISE EXCEPTION 'security event tenant context is missing or mismatched'
            USING ERRCODE = '42501';
    END IF;

    SELECT COALESCE(bool_and(
        ordered.sequence_no = ordered.expected_sequence_no
        AND ordered.previous_event_sha256
            IS NOT DISTINCT FROM ordered.expected_previous_sha256
        AND ordered.event_sha256 = gda_control.security_event_fingerprint(
            ordered.tenant_id,
            ordered.event_id,
            ordered.sequence_no,
            ordered.attempt_id,
            ordered.phase,
            ordered.action,
            ordered.outcome,
            ordered.actor_subject,
            ordered.resource_ref,
            ordered.reason,
            ordered.details,
            ordered.previous_event_sha256,
            ordered.occurred_at
        )
    ), TRUE)
    INTO v_valid
    FROM (
        SELECT
            security_event.*,
            row_number() OVER (ORDER BY sequence_no) - 1
                AS expected_sequence_no,
            lag(event_sha256) OVER (ORDER BY sequence_no)
                AS expected_previous_sha256
        FROM gda_control.security_event AS security_event
        WHERE tenant_id = p_tenant_id
    ) AS ordered;
    RETURN v_valid;
END
$$;

DROP TRIGGER IF EXISTS trg_gda_security_event_immutable
    ON gda_control.security_event;
CREATE TRIGGER trg_gda_security_event_immutable
BEFORE UPDATE OR DELETE ON gda_control.security_event
FOR EACH ROW EXECUTE FUNCTION gda_control.reject_immutable_mutation();

ALTER TABLE gda_control.security_event ENABLE ROW LEVEL SECURITY;
ALTER TABLE gda_control.security_event FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON gda_control.security_event;
CREATE POLICY tenant_isolation ON gda_control.security_event
    USING (tenant_id = gda_control.current_tenant())
    WITH CHECK (tenant_id = gda_control.current_tenant());

REVOKE ALL ON gda_control.security_event FROM PUBLIC;
REVOKE ALL ON gda_control.security_event FROM gda_control_gateway;
REVOKE ALL ON FUNCTION gda_control.security_event_fingerprint(
    text, uuid, bigint, uuid, text, text, text, text, text, text,
    jsonb, text, timestamptz
) FROM PUBLIC;
REVOKE ALL ON FUNCTION gda_control.append_security_event(
    text, uuid, text, text, text, text, text, text, jsonb
) FROM PUBLIC;
REVOKE ALL ON FUNCTION gda_control.verify_security_event_chain(text)
    FROM PUBLIC;

GRANT SELECT ON gda_control.security_event TO gda_control_gateway;
GRANT EXECUTE ON FUNCTION gda_control.append_security_event(
    text, uuid, text, text, text, text, text, text, jsonb
) TO gda_control_gateway;
GRANT EXECUTE ON FUNCTION gda_control.verify_security_event_chain(text)
    TO gda_control_gateway;
