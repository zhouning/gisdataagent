-- 224: Reconcile GIS ServiceSLO bindings after generic SLO activation.
--
-- The generic SLO authority remains the lifecycle owner.  This outbox only
-- records a durable request to project an exact activation into GIS service
-- operations; the worker rechecks every identity before invoking migration
-- 223's binding authority.

CREATE TABLE IF NOT EXISTS gda_control.gis_service_slo_reconciliation_outbox (
    tenant_id TEXT NOT NULL,
    task_id UUID NOT NULL DEFAULT gen_random_uuid(),
    service_urn TEXT NOT NULL,
    slo_definition_ref TEXT NOT NULL,
    active_version_ref TEXT NOT NULL,
    definition_fingerprint CHAR(64) NOT NULL,
    approval_case_ref TEXT NOT NULL,
    activation_version INTEGER NOT NULL,
    status TEXT NOT NULL,
    attempt_count INTEGER NOT NULL DEFAULT 0,
    max_attempts INTEGER NOT NULL DEFAULT 5,
    available_at TIMESTAMPTZ NOT NULL,
    claimed_by TEXT,
    claimed_until TIMESTAMPTZ,
    binding_id UUID,
    last_error TEXT,
    created_at TIMESTAMPTZ NOT NULL,
    completed_at TIMESTAMPTZ,
    CONSTRAINT pk_gda_gis_service_slo_reconciliation
        PRIMARY KEY (tenant_id, task_id),
    CONSTRAINT uq_gda_gis_service_slo_reconciliation_task
        UNIQUE (task_id),
    CONSTRAINT uq_gda_gis_service_slo_reconciliation_activation
        UNIQUE (tenant_id, slo_definition_ref, activation_version),
    CONSTRAINT fk_gda_gis_service_slo_reconciliation_version
        FOREIGN KEY (tenant_id, active_version_ref, definition_fingerprint)
        REFERENCES gda_control.slo_definition_version(
            tenant_id, slo_version_ref, definition_fingerprint
        ),
    CONSTRAINT fk_gda_gis_service_slo_reconciliation_approval
        FOREIGN KEY (tenant_id, approval_case_ref)
        REFERENCES gda_control.approval_case(tenant_id, approval_case_ref),
    CONSTRAINT fk_gda_gis_service_slo_reconciliation_binding
        FOREIGN KEY (tenant_id, binding_id)
        REFERENCES gda_control.gis_service_slo_binding(tenant_id, binding_id),
    CONSTRAINT ck_gda_gis_service_slo_reconciliation_tenant
        CHECK (tenant_id ~ '^[a-z0-9][a-z0-9._-]{0,63}$'),
    CONSTRAINT ck_gda_gis_service_slo_reconciliation_service
        CHECK (
            service_urn ~ '^gda://[a-z0-9][a-z0-9._-]{0,63}/gis_service/[a-z0-9][a-z0-9._-]{0,127}$'
            AND split_part(service_urn, '/', 3) = tenant_id
        ),
    CONSTRAINT ck_gda_gis_service_slo_reconciliation_definition
        CHECK (
            slo_definition_ref ~ '^gda://[a-z0-9][a-z0-9._-]{0,63}/slo_definition/[a-z0-9][a-z0-9._-]{0,127}$'
            AND split_part(slo_definition_ref, '/', 3) = tenant_id
        ),
    CONSTRAINT ck_gda_gis_service_slo_reconciliation_version
        CHECK (
            active_version_ref ~ '^gda://[a-z0-9][a-z0-9._-]{0,63}/slo_definition/[a-z0-9][a-z0-9._-]{0,127}\.v[1-9][0-9]*$'
            AND active_version_ref LIKE slo_definition_ref || '.v%'
        ),
    CONSTRAINT ck_gda_gis_service_slo_reconciliation_fingerprint
        CHECK (definition_fingerprint ~ '^[0-9a-f]{64}$'),
    CONSTRAINT ck_gda_gis_service_slo_reconciliation_approval
        CHECK (
            approval_case_ref ~ '^gda://[a-z0-9][a-z0-9._-]{0,63}/approval_case/[a-z0-9][a-z0-9._-]{0,127}$'
            AND split_part(approval_case_ref, '/', 3) = tenant_id
        ),
    CONSTRAINT ck_gda_gis_service_slo_reconciliation_activation
        CHECK (activation_version >= 1),
    CONSTRAINT ck_gda_gis_service_slo_reconciliation_status
        CHECK (status IN ('pending', 'in_flight', 'done', 'failed', 'superseded')),
    CONSTRAINT ck_gda_gis_service_slo_reconciliation_attempts
        CHECK (attempt_count >= 0 AND max_attempts BETWEEN 1 AND 100),
    CONSTRAINT ck_gda_gis_service_slo_reconciliation_claim
        CHECK ((claimed_by IS NULL) = (claimed_until IS NULL)),
    CONSTRAINT ck_gda_gis_service_slo_reconciliation_delivery
        CHECK (
            (status = 'pending' AND claimed_by IS NULL AND completed_at IS NULL AND binding_id IS NULL)
            OR (status = 'in_flight' AND claimed_by IS NOT NULL AND completed_at IS NULL AND binding_id IS NULL)
            OR (status = 'done' AND claimed_by IS NULL AND completed_at IS NOT NULL AND binding_id IS NOT NULL)
            OR (
                status IN ('failed', 'superseded') AND claimed_by IS NULL
                AND completed_at IS NOT NULL AND binding_id IS NULL
                AND NULLIF(btrim(last_error), '') IS NOT NULL
            )
        )
);

CREATE INDEX IF NOT EXISTS idx_gda_gis_service_slo_reconciliation_due
    ON gda_control.gis_service_slo_reconciliation_outbox(
        tenant_id, available_at, created_at, task_id
    ) WHERE status = 'pending';
CREATE INDEX IF NOT EXISTS idx_gda_gis_service_slo_reconciliation_lease
    ON gda_control.gis_service_slo_reconciliation_outbox(tenant_id, claimed_until)
    WHERE status = 'in_flight';

CREATE OR REPLACE FUNCTION gda_control.enqueue_gis_service_slo_reconciliation(
    p_tenant_id TEXT,
    p_service_urn TEXT,
    p_slo_definition_ref TEXT,
    p_active_version_ref TEXT,
    p_definition_fingerprint TEXT,
    p_approval_case_ref TEXT,
    p_activation_version INTEGER,
    p_created_at TIMESTAMPTZ
)
RETURNS UUID
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, gda_control
SET row_security = on
AS $$
DECLARE
    v_existing gda_control.gis_service_slo_reconciliation_outbox%ROWTYPE;
    v_task_id UUID;
BEGIN
    IF gda_control.current_tenant() IS DISTINCT FROM p_tenant_id THEN
        RAISE EXCEPTION 'GIS ServiceSLO reconciliation tenant context mismatch'
            USING ERRCODE = '42501';
    END IF;
    IF p_service_urn !~ '^gda://[a-z0-9][a-z0-9._-]{0,63}/gis_service/[a-z0-9][a-z0-9._-]{0,127}$'
       OR split_part(p_service_urn, '/', 3) <> p_tenant_id
       OR p_activation_version < 1
       OR p_created_at IS NULL THEN
        RAISE EXCEPTION 'GIS ServiceSLO reconciliation identity is invalid'
            USING ERRCODE = '22023';
    END IF;

    SELECT * INTO v_existing
    FROM gda_control.gis_service_slo_reconciliation_outbox
    WHERE tenant_id = p_tenant_id
      AND slo_definition_ref = p_slo_definition_ref
      AND activation_version = p_activation_version;
    IF FOUND THEN
        IF v_existing.service_urn IS DISTINCT FROM p_service_urn
           OR v_existing.active_version_ref IS DISTINCT FROM p_active_version_ref
           OR v_existing.definition_fingerprint IS DISTINCT FROM p_definition_fingerprint
           OR v_existing.approval_case_ref IS DISTINCT FROM p_approval_case_ref THEN
            RAISE EXCEPTION 'GIS ServiceSLO reconciliation activation has different evidence'
                USING ERRCODE = '40001';
        END IF;
        RETURN v_existing.task_id;
    END IF;

    INSERT INTO gda_control.gis_service_slo_reconciliation_outbox (
        tenant_id, service_urn, slo_definition_ref, active_version_ref,
        definition_fingerprint, approval_case_ref, activation_version,
        status, available_at, created_at
    ) VALUES (
        p_tenant_id, p_service_urn, p_slo_definition_ref, p_active_version_ref,
        p_definition_fingerprint, p_approval_case_ref, p_activation_version,
        'pending', p_created_at, p_created_at
    )
    ON CONFLICT (tenant_id, slo_definition_ref, activation_version) DO NOTHING
    RETURNING task_id INTO v_task_id;
    IF v_task_id IS NOT NULL THEN
        RETURN v_task_id;
    END IF;

    SELECT task_id INTO v_task_id
    FROM gda_control.gis_service_slo_reconciliation_outbox
    WHERE tenant_id = p_tenant_id
      AND slo_definition_ref = p_slo_definition_ref
      AND activation_version = p_activation_version;
    RETURN v_task_id;
END;
$$;

CREATE OR REPLACE FUNCTION gda_control.enqueue_slo_activation_gis_service_reconciliation()
RETURNS TRIGGER
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, gda_control
SET row_security = on
AS $$
DECLARE
    v_service_urn TEXT;
BEGIN
    SELECT service_resource_urn INTO v_service_urn
    FROM gda_control.slo_definition_version
    WHERE tenant_id = NEW.tenant_id
      AND slo_version_ref = NEW.active_version_ref
      AND definition_fingerprint = NEW.active_fingerprint;
    IF FOUND
       AND v_service_urn ~ '^gda://[a-z0-9][a-z0-9._-]{0,63}/gis_service/'
       AND EXISTS (
            SELECT 1 FROM gda_control.gis_service
            WHERE tenant_id = NEW.tenant_id AND service_urn = v_service_urn
       ) THEN
        PERFORM gda_control.enqueue_gis_service_slo_reconciliation(
            NEW.tenant_id, v_service_urn, NEW.slo_definition_ref,
            NEW.active_version_ref, NEW.active_fingerprint,
            NEW.approval_case_ref, NEW.activation_version, NEW.activated_at
        );
    END IF;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_gda_slo_activation_gis_service_reconciliation
    ON gda_control.slo_definition_activation;
CREATE TRIGGER trg_gda_slo_activation_gis_service_reconciliation
AFTER INSERT OR UPDATE ON gda_control.slo_definition_activation
FOR EACH ROW EXECUTE FUNCTION
    gda_control.enqueue_slo_activation_gis_service_reconciliation();

CREATE OR REPLACE FUNCTION gda_control.claim_gis_service_slo_reconciliations(
    p_tenant_id TEXT,
    p_actor_subject TEXT,
    p_worker_id TEXT,
    p_limit INTEGER DEFAULT 10,
    p_lease_seconds INTEGER DEFAULT 60
)
RETURNS SETOF gda_control.gis_service_slo_reconciliation_outbox
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, gda_control
SET row_security = on
AS $$
BEGIN
    IF gda_control.current_tenant() IS DISTINCT FROM p_tenant_id
       OR p_actor_subject <> 'workload:gis-slo-binding-controller'
       OR NULLIF(btrim(p_worker_id), '') IS NULL THEN
        RAISE EXCEPTION 'GIS ServiceSLO reconciliation worker authority is invalid'
            USING ERRCODE = '42501';
    END IF;
    IF p_limit NOT BETWEEN 1 AND 100 OR p_lease_seconds NOT BETWEEN 5 AND 3600 THEN
        RAISE EXCEPTION 'GIS ServiceSLO reconciliation claim bounds are invalid'
            USING ERRCODE = '22023';
    END IF;

    -- Reconcile activations that predate migration 224 or a prior trigger repair.
    INSERT INTO gda_control.gis_service_slo_reconciliation_outbox (
        tenant_id, service_urn, slo_definition_ref, active_version_ref,
        definition_fingerprint, approval_case_ref, activation_version,
        status, available_at, created_at
    )
    SELECT activation.tenant_id, definition.service_resource_urn,
           activation.slo_definition_ref, activation.active_version_ref,
           activation.active_fingerprint, activation.approval_case_ref,
           activation.activation_version, 'pending', clock_timestamp(),
           activation.activated_at
    FROM gda_control.slo_definition_activation AS activation
    JOIN gda_control.slo_definition_version AS definition
      ON definition.tenant_id = activation.tenant_id
     AND definition.slo_version_ref = activation.active_version_ref
     AND definition.definition_fingerprint = activation.active_fingerprint
    JOIN gda_control.gis_service AS service
      ON service.tenant_id = definition.tenant_id
     AND service.service_urn = definition.service_resource_urn
    WHERE activation.tenant_id = p_tenant_id
    ON CONFLICT (tenant_id, slo_definition_ref, activation_version) DO NOTHING;

    UPDATE gda_control.gis_service_slo_reconciliation_outbox
       SET status = CASE WHEN attempt_count >= max_attempts THEN 'failed' ELSE 'pending' END,
           available_at = clock_timestamp(), claimed_by = NULL, claimed_until = NULL,
           last_error = COALESCE(last_error, 'worker lease expired'),
           completed_at = CASE WHEN attempt_count >= max_attempts THEN clock_timestamp() ELSE NULL END
     WHERE tenant_id = p_tenant_id AND status = 'in_flight'
       AND claimed_until <= clock_timestamp();

    RETURN QUERY
    WITH due AS (
        SELECT task_id
        FROM gda_control.gis_service_slo_reconciliation_outbox
        WHERE tenant_id = p_tenant_id AND status = 'pending'
          AND available_at <= clock_timestamp()
        ORDER BY available_at, created_at, task_id
        FOR UPDATE SKIP LOCKED LIMIT p_limit
    )
    UPDATE gda_control.gis_service_slo_reconciliation_outbox AS task
       SET status = 'in_flight', attempt_count = task.attempt_count + 1,
           claimed_by = p_worker_id,
           claimed_until = clock_timestamp() + make_interval(secs => p_lease_seconds),
           last_error = NULL
      FROM due
     WHERE task.tenant_id = p_tenant_id AND task.task_id = due.task_id
    RETURNING task.*;
END;
$$;

CREATE OR REPLACE FUNCTION gda_control.complete_gis_service_slo_reconciliation(
    p_tenant_id TEXT,
    p_task_id UUID,
    p_worker_id TEXT,
    p_bound_at TIMESTAMPTZ
)
RETURNS SETOF gda_control.gis_service_slo_reconciliation_outbox
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, gda_control, public
SET row_security = on
AS $$
DECLARE
    v_task gda_control.gis_service_slo_reconciliation_outbox%ROWTYPE;
    v_active gda_control.slo_definition_activation%ROWTYPE;
    v_binding_id UUID;
BEGIN
    IF gda_control.current_tenant() IS DISTINCT FROM p_tenant_id THEN
        RAISE EXCEPTION 'GIS ServiceSLO reconciliation tenant context mismatch'
            USING ERRCODE = '42501';
    END IF;
    SELECT * INTO v_task
    FROM gda_control.gis_service_slo_reconciliation_outbox
    WHERE tenant_id = p_tenant_id AND task_id = p_task_id
    FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'GIS ServiceSLO reconciliation task was not found'
            USING ERRCODE = 'P0002';
    END IF;
    IF v_task.status = 'done' THEN
        RETURN NEXT v_task;
        RETURN;
    END IF;
    IF v_task.status <> 'in_flight'
       OR v_task.claimed_by IS DISTINCT FROM p_worker_id
       OR v_task.claimed_until <= clock_timestamp() THEN
        RAISE EXCEPTION 'GIS ServiceSLO reconciliation task is not held by this worker'
            USING ERRCODE = '40001';
    END IF;

    SELECT * INTO v_active
    FROM gda_control.slo_definition_activation
    WHERE tenant_id = p_tenant_id
      AND slo_definition_ref = v_task.slo_definition_ref;
    IF NOT FOUND
       OR v_active.active_version_ref IS DISTINCT FROM v_task.active_version_ref
       OR v_active.active_fingerprint IS DISTINCT FROM v_task.definition_fingerprint
       OR v_active.approval_case_ref IS DISTINCT FROM v_task.approval_case_ref
       OR v_active.activation_version IS DISTINCT FROM v_task.activation_version THEN
        UPDATE gda_control.gis_service_slo_reconciliation_outbox
           SET status = 'superseded', claimed_by = NULL, claimed_until = NULL,
               last_error = 'activation superseded before reconciliation',
               completed_at = clock_timestamp()
         WHERE tenant_id = p_tenant_id AND task_id = p_task_id
         RETURNING * INTO v_task;
        RETURN NEXT v_task;
        RETURN;
    END IF;

    SELECT binding_id INTO v_binding_id
    FROM gda_control.gis_service_slo_binding
    WHERE tenant_id = p_tenant_id
      AND service_urn = v_task.service_urn
      AND slo_definition_ref = v_task.slo_definition_ref
      AND active_version_ref = v_task.active_version_ref
      AND definition_fingerprint = v_task.definition_fingerprint
      AND approval_case_ref = v_task.approval_case_ref
      AND activation_version = v_task.activation_version;
    IF NOT FOUND THEN
        SELECT gda_control.bind_gis_service_slo(
            p_tenant_id, gen_random_uuid(), v_task.service_urn,
            v_task.slo_definition_ref, v_task.active_version_ref,
            v_task.definition_fingerprint, v_task.approval_case_ref,
            v_task.activation_version, 'workload:gis-slo-binding-controller',
            'automatically reconcile the exact approved GIS ServiceSLO activation',
            COALESCE(p_bound_at, clock_timestamp())
        ) INTO v_binding_id;
    END IF;

    UPDATE gda_control.gis_service_slo_reconciliation_outbox
       SET status = 'done', claimed_by = NULL, claimed_until = NULL,
           binding_id = v_binding_id, completed_at = clock_timestamp()
     WHERE tenant_id = p_tenant_id AND task_id = p_task_id
     RETURNING * INTO v_task;
    RETURN NEXT v_task;
END;
$$;

CREATE OR REPLACE FUNCTION gda_control.fail_gis_service_slo_reconciliation(
    p_tenant_id TEXT,
    p_task_id UUID,
    p_worker_id TEXT,
    p_error TEXT,
    p_retry_delay_seconds INTEGER DEFAULT 30
)
RETURNS SETOF gda_control.gis_service_slo_reconciliation_outbox
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, gda_control
SET row_security = on
AS $$
DECLARE
    v_task gda_control.gis_service_slo_reconciliation_outbox%ROWTYPE;
BEGIN
    IF gda_control.current_tenant() IS DISTINCT FROM p_tenant_id THEN
        RAISE EXCEPTION 'GIS ServiceSLO reconciliation tenant context mismatch'
            USING ERRCODE = '42501';
    END IF;
    IF NULLIF(btrim(p_error), '') IS NULL
       OR length(p_error) > 2048
       OR p_retry_delay_seconds NOT BETWEEN 0 AND 86400 THEN
        RAISE EXCEPTION 'GIS ServiceSLO reconciliation failure details are invalid'
            USING ERRCODE = '22023';
    END IF;
    SELECT * INTO v_task
    FROM gda_control.gis_service_slo_reconciliation_outbox
    WHERE tenant_id = p_tenant_id AND task_id = p_task_id
    FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'GIS ServiceSLO reconciliation task was not found'
            USING ERRCODE = 'P0002';
    END IF;
    IF v_task.status <> 'in_flight'
       OR v_task.claimed_by IS DISTINCT FROM p_worker_id
       OR v_task.claimed_until <= clock_timestamp() THEN
        RAISE EXCEPTION 'GIS ServiceSLO reconciliation task is not held by this worker'
            USING ERRCODE = '40001';
    END IF;
    UPDATE gda_control.gis_service_slo_reconciliation_outbox
       SET status = CASE WHEN attempt_count >= max_attempts THEN 'failed' ELSE 'pending' END,
           available_at = clock_timestamp() + make_interval(secs => p_retry_delay_seconds),
           claimed_by = NULL, claimed_until = NULL, last_error = p_error,
           completed_at = CASE WHEN attempt_count >= max_attempts THEN clock_timestamp() ELSE NULL END
     WHERE tenant_id = p_tenant_id AND task_id = p_task_id
     RETURNING * INTO v_task;
    RETURN NEXT v_task;
END;
$$;

ALTER TABLE gda_control.gis_service_slo_reconciliation_outbox ENABLE ROW LEVEL SECURITY;
ALTER TABLE gda_control.gis_service_slo_reconciliation_outbox FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON gda_control.gis_service_slo_reconciliation_outbox;
CREATE POLICY tenant_isolation ON gda_control.gis_service_slo_reconciliation_outbox
USING (tenant_id = gda_control.current_tenant())
WITH CHECK (tenant_id = gda_control.current_tenant());

REVOKE ALL ON TABLE gda_control.gis_service_slo_reconciliation_outbox
    FROM PUBLIC, gda_control_gateway;
GRANT SELECT ON TABLE gda_control.gis_service_slo_reconciliation_outbox
    TO gda_control_gateway;
REVOKE ALL ON FUNCTION gda_control.enqueue_gis_service_slo_reconciliation(
    TEXT, TEXT, TEXT, TEXT, TEXT, TEXT, INTEGER, TIMESTAMPTZ
) FROM PUBLIC, gda_control_gateway;
REVOKE ALL ON FUNCTION
    gda_control.enqueue_slo_activation_gis_service_reconciliation()
    FROM PUBLIC, gda_control_gateway;
REVOKE ALL ON FUNCTION gda_control.claim_gis_service_slo_reconciliations(
    TEXT, TEXT, TEXT, INTEGER, INTEGER
) FROM PUBLIC, gda_control_gateway;
GRANT EXECUTE ON FUNCTION gda_control.claim_gis_service_slo_reconciliations(
    TEXT, TEXT, TEXT, INTEGER, INTEGER
) TO gda_control_gateway;
REVOKE ALL ON FUNCTION gda_control.complete_gis_service_slo_reconciliation(
    TEXT, UUID, TEXT, TIMESTAMPTZ
) FROM PUBLIC, gda_control_gateway;
GRANT EXECUTE ON FUNCTION gda_control.complete_gis_service_slo_reconciliation(
    TEXT, UUID, TEXT, TIMESTAMPTZ
) TO gda_control_gateway;
REVOKE ALL ON FUNCTION gda_control.fail_gis_service_slo_reconciliation(
    TEXT, UUID, TEXT, TEXT, INTEGER
) FROM PUBLIC, gda_control_gateway;
GRANT EXECUTE ON FUNCTION gda_control.fail_gis_service_slo_reconciliation(
    TEXT, UUID, TEXT, TEXT, INTEGER
) TO gda_control_gateway;
