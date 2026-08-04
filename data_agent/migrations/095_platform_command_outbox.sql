-- 095: Tenant-scoped delivery outbox for PlatformRun provider commands.
--
-- This table is delivery state, not a scheduler, provider state store, or
-- PlatformRun authority. Long-running work remains in DolphinScheduler.

CREATE TABLE IF NOT EXISTS gda_control.platform_command_outbox (
    tenant_id TEXT NOT NULL,
    command_id UUID PRIMARY KEY,
    run_id UUID NOT NULL,
    command_type TEXT NOT NULL,
    execution_plan_artifact_id UUID NOT NULL,
    trigger_observation_id UUID,
    dedupe_key TEXT NOT NULL,
    actor_subject TEXT NOT NULL,
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    status TEXT NOT NULL DEFAULT 'pending',
    attempt_count INTEGER NOT NULL DEFAULT 0,
    max_attempts INTEGER NOT NULL DEFAULT 5,
    available_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    claimed_by TEXT,
    claimed_until TIMESTAMPTZ,
    last_error TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_at TIMESTAMPTZ,
    CONSTRAINT uq_gda_command_tenant_id UNIQUE (tenant_id, command_id),
    CONSTRAINT uq_gda_command_dedupe UNIQUE (tenant_id, dedupe_key),
    CONSTRAINT fk_gda_command_run
        FOREIGN KEY (tenant_id, run_id)
        REFERENCES gda_control.platform_run(tenant_id, run_id),
    CONSTRAINT fk_gda_command_execution_plan
        FOREIGN KEY (tenant_id, execution_plan_artifact_id)
        REFERENCES gda_control.artifact(tenant_id, artifact_id),
    CONSTRAINT fk_gda_command_trigger_observation
        FOREIGN KEY (tenant_id, trigger_observation_id)
        REFERENCES gda_control.framework_attempt_observation(
            tenant_id, observation_id
        ),
    CONSTRAINT ck_gda_command_type CHECK (
        command_type IN (
            'dolphinscheduler.dispatch', 'dolphinscheduler.reconcile'
        )
    ),
    CONSTRAINT ck_gda_command_payload CHECK (jsonb_typeof(payload) = 'object'),
    CONSTRAINT ck_gda_command_status CHECK (
        status IN ('pending', 'in_flight', 'done', 'failed')
    ),
    CONSTRAINT ck_gda_command_attempt_count CHECK (attempt_count >= 0),
    CONSTRAINT ck_gda_command_max_attempts CHECK (
        max_attempts BETWEEN 1 AND 100
    ),
    CONSTRAINT ck_gda_command_claim_pair CHECK (
        (claimed_by IS NULL) = (claimed_until IS NULL)
    ),
    CONSTRAINT ck_gda_command_delivery_state CHECK (
        (status = 'pending' AND claimed_by IS NULL AND completed_at IS NULL)
        OR
        (status = 'in_flight' AND claimed_by IS NOT NULL AND completed_at IS NULL)
        OR
        (status IN ('done', 'failed') AND claimed_by IS NULL AND completed_at IS NOT NULL)
    ),
    CONSTRAINT ck_gda_dispatch_has_no_callback CHECK (
        command_type <> 'dolphinscheduler.dispatch'
        OR trigger_observation_id IS NULL
    )
);

CREATE INDEX IF NOT EXISTS idx_gda_command_due
    ON gda_control.platform_command_outbox(
        tenant_id, actor_subject, available_at, created_at
    )
    WHERE status = 'pending';
CREATE INDEX IF NOT EXISTS idx_gda_command_expired_claim
    ON gda_control.platform_command_outbox(tenant_id, claimed_until)
    WHERE status = 'in_flight';
CREATE INDEX IF NOT EXISTS idx_gda_command_run
    ON gda_control.platform_command_outbox(tenant_id, run_id, created_at);

ALTER TABLE gda_control.platform_command_outbox ENABLE ROW LEVEL SECURITY;
ALTER TABLE gda_control.platform_command_outbox FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS gda_command_tenant_isolation
    ON gda_control.platform_command_outbox;
CREATE POLICY gda_command_tenant_isolation
    ON gda_control.platform_command_outbox
    USING (tenant_id = gda_control.current_tenant())
    WITH CHECK (tenant_id = gda_control.current_tenant());

CREATE OR REPLACE FUNCTION gda_control.claim_platform_commands(
    p_tenant_id TEXT,
    p_actor_subject TEXT,
    p_worker_id TEXT,
    p_limit INTEGER DEFAULT 10,
    p_lease_seconds INTEGER DEFAULT 60
)
RETURNS SETOF gda_control.platform_command_outbox
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, gda_control
SET row_security = on
AS $$
BEGIN
    IF gda_control.current_tenant() IS DISTINCT FROM p_tenant_id THEN
        RAISE EXCEPTION 'tenant context mismatch' USING ERRCODE = '42501';
    END IF;
    IF COALESCE(btrim(p_actor_subject), '') = '' THEN
        RAISE EXCEPTION 'command actor is required' USING ERRCODE = '22023';
    END IF;
    IF COALESCE(btrim(p_worker_id), '') = '' THEN
        RAISE EXCEPTION 'worker identity is required' USING ERRCODE = '22023';
    END IF;
    IF p_limit IS NULL OR p_limit < 1 OR p_limit > 100 THEN
        RAISE EXCEPTION 'claim limit must be between 1 and 100'
            USING ERRCODE = '22023';
    END IF;
    IF p_lease_seconds IS NULL
       OR p_lease_seconds < 5 OR p_lease_seconds > 3600 THEN
        RAISE EXCEPTION 'lease must be between 5 and 3600 seconds'
            USING ERRCODE = '22023';
    END IF;

    UPDATE gda_control.platform_command_outbox
       SET status = 'failed',
           claimed_by = NULL,
           claimed_until = NULL,
           last_error = COALESCE(last_error, 'worker lease expired'),
           completed_at = clock_timestamp()
     WHERE tenant_id = p_tenant_id
       AND status = 'in_flight'
       AND claimed_until <= clock_timestamp()
       AND attempt_count >= max_attempts;

    RETURN QUERY
    WITH candidates AS (
        SELECT command_id
          FROM gda_control.platform_command_outbox
         WHERE tenant_id = p_tenant_id
           AND actor_subject = p_actor_subject
           AND attempt_count < max_attempts
           AND (
               (status = 'pending' AND available_at <= clock_timestamp())
               OR
               (status = 'in_flight' AND claimed_until <= clock_timestamp())
           )
         ORDER BY available_at, created_at, command_id
         LIMIT p_limit
         FOR UPDATE SKIP LOCKED
    )
    UPDATE gda_control.platform_command_outbox AS command
       SET status = 'in_flight',
           attempt_count = command.attempt_count + 1,
           claimed_by = p_worker_id,
           claimed_until = clock_timestamp()
               + make_interval(secs => p_lease_seconds),
           completed_at = NULL
      FROM candidates
     WHERE command.tenant_id = p_tenant_id
       AND command.command_id = candidates.command_id
    RETURNING command.*;
END;
$$;

CREATE OR REPLACE FUNCTION gda_control.complete_platform_command(
    p_tenant_id TEXT,
    p_command_id UUID,
    p_worker_id TEXT
)
RETURNS SETOF gda_control.platform_command_outbox
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, gda_control
SET row_security = on
AS $$
BEGIN
    IF gda_control.current_tenant() IS DISTINCT FROM p_tenant_id THEN
        RAISE EXCEPTION 'tenant context mismatch' USING ERRCODE = '42501';
    END IF;
    RETURN QUERY
    UPDATE gda_control.platform_command_outbox AS command
       SET status = 'done',
           claimed_by = NULL,
           claimed_until = NULL,
           last_error = NULL,
           completed_at = clock_timestamp()
     WHERE command.tenant_id = p_tenant_id
       AND command.command_id = p_command_id
       AND command.status = 'in_flight'
       AND command.claimed_by = p_worker_id
       AND command.claimed_until > clock_timestamp()
    RETURNING command.*;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'command claim is missing, expired, or owned by another worker'
            USING ERRCODE = '40001';
    END IF;
END;
$$;

CREATE OR REPLACE FUNCTION gda_control.fail_platform_command(
    p_tenant_id TEXT,
    p_command_id UUID,
    p_worker_id TEXT,
    p_error TEXT,
    p_retry_delay_seconds INTEGER DEFAULT 30
)
RETURNS SETOF gda_control.platform_command_outbox
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, gda_control
SET row_security = on
AS $$
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
    RETURN QUERY
    UPDATE gda_control.platform_command_outbox AS command
       SET status = CASE
               WHEN command.attempt_count >= command.max_attempts
               THEN 'failed' ELSE 'pending' END,
           claimed_by = NULL,
           claimed_until = NULL,
           last_error = left(p_error, 2000),
           available_at = CASE
               WHEN command.attempt_count >= command.max_attempts
               THEN command.available_at
               ELSE clock_timestamp()
                   + make_interval(secs => p_retry_delay_seconds)
               END,
           completed_at = CASE
               WHEN command.attempt_count >= command.max_attempts
               THEN clock_timestamp() ELSE NULL END
     WHERE command.tenant_id = p_tenant_id
       AND command.command_id = p_command_id
       AND command.status = 'in_flight'
       AND command.claimed_by = p_worker_id
       AND command.claimed_until > clock_timestamp()
    RETURNING command.*;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'command claim is missing, expired, or owned by another worker'
            USING ERRCODE = '40001';
    END IF;
END;
$$;

REVOKE ALL ON TABLE gda_control.platform_command_outbox FROM PUBLIC;
REVOKE ALL ON TABLE gda_control.platform_command_outbox
    FROM gda_control_gateway;
GRANT SELECT, INSERT ON gda_control.platform_command_outbox
    TO gda_control_gateway;

REVOKE ALL ON FUNCTION gda_control.claim_platform_commands(
    text, text, text, integer, integer
) FROM PUBLIC;
REVOKE ALL ON FUNCTION gda_control.complete_platform_command(
    text, uuid, text
) FROM PUBLIC;
REVOKE ALL ON FUNCTION gda_control.fail_platform_command(
    text, uuid, text, text, integer
) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION gda_control.claim_platform_commands(
    text, text, text, integer, integer
) TO gda_control_gateway;
GRANT EXECUTE ON FUNCTION gda_control.complete_platform_command(
    text, uuid, text
) TO gda_control_gateway;
GRANT EXECUTE ON FUNCTION gda_control.fail_platform_command(
    text, uuid, text, text, integer
) TO gda_control_gateway;
