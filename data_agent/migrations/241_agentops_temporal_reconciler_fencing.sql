-- 241: Lease and fencing authority for concurrent AgentOps reconcilers.

CREATE TABLE IF NOT EXISTS gda_control.agentops_temporal_reconciler_lease (
    tenant_id TEXT NOT NULL,
    workflow_id TEXT NOT NULL,
    lease_owner TEXT NOT NULL,
    lease_epoch BIGINT NOT NULL,
    lease_acquired_at TIMESTAMPTZ NOT NULL,
    lease_expires_at TIMESTAMPTZ NOT NULL,
    lease_updated_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (tenant_id, workflow_id),
    CONSTRAINT ck_gda_agentops_temporal_reconciler_lease_tenant
        CHECK (tenant_id ~ '^[a-z0-9][a-z0-9._-]{0,63}$'),
    CONSTRAINT ck_gda_agentops_temporal_reconciler_lease_workflow
        CHECK (workflow_id ~ '^[a-z][a-z0-9._:-]{1,254}$'),
    CONSTRAINT ck_gda_agentops_temporal_reconciler_lease_owner
        CHECK (lease_owner ~ '^(workload|agent):[^[:space:]]{1,128}$'),
    CONSTRAINT ck_gda_agentops_temporal_reconciler_lease_epoch
        CHECK (lease_epoch >= 1),
    CONSTRAINT ck_gda_agentops_temporal_reconciler_lease_time CHECK (
        lease_expires_at >= lease_acquired_at
        AND lease_updated_at >= lease_acquired_at
    )
);

CREATE INDEX IF NOT EXISTS idx_gda_agentops_temporal_reconciler_lease_expiry
    ON gda_control.agentops_temporal_reconciler_lease (
        tenant_id, lease_expires_at, workflow_id
    );

CREATE TABLE IF NOT EXISTS gda_control.agentops_temporal_checkpoint_lease_binding (
    tenant_id TEXT NOT NULL,
    workflow_id TEXT NOT NULL,
    checkpoint_sha256 CHAR(64) NOT NULL,
    lease_owner TEXT NOT NULL,
    lease_epoch BIGINT NOT NULL,
    bound_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (tenant_id, workflow_id, checkpoint_sha256),
    CONSTRAINT fk_gda_agentops_temporal_checkpoint_lease_binding
        FOREIGN KEY (tenant_id, workflow_id, checkpoint_sha256)
        REFERENCES gda_control.agentops_temporal_checkpoint_history (
            tenant_id, workflow_id, checkpoint_sha256
        ),
    CONSTRAINT ck_gda_agentops_temporal_checkpoint_lease_owner
        CHECK (lease_owner ~ '^(workload|agent):[^[:space:]]{1,128}$'),
    CONSTRAINT ck_gda_agentops_temporal_checkpoint_lease_epoch
        CHECK (lease_epoch >= 1)
);

CREATE TABLE IF NOT EXISTS gda_control.agentops_temporal_reconciliation_lease_binding (
    tenant_id TEXT NOT NULL,
    workflow_id TEXT NOT NULL,
    reconciliation_sha256 CHAR(64) NOT NULL,
    lease_owner TEXT NOT NULL,
    lease_epoch BIGINT NOT NULL,
    bound_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (tenant_id, workflow_id, reconciliation_sha256),
    CONSTRAINT fk_gda_agentops_temporal_reconciliation_lease_binding
        FOREIGN KEY (tenant_id, reconciliation_sha256)
        REFERENCES gda_control.agentops_temporal_reconciliation_evidence (
            tenant_id, reconciliation_sha256
        ),
    CONSTRAINT ck_gda_agentops_temporal_reconciliation_lease_owner
        CHECK (lease_owner ~ '^(workload|agent):[^[:space:]]{1,128}$'),
    CONSTRAINT ck_gda_agentops_temporal_reconciliation_lease_epoch
        CHECK (lease_epoch >= 1)
);

CREATE OR REPLACE FUNCTION gda_control.guard_agentops_temporal_reconciler_state()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
DECLARE
    v_tenant_id TEXT;
BEGIN
    IF COALESCE(
        current_setting('gda.agentops_temporal_reconciler_write_allowed', true),
        ''
    ) <> '1' THEN
        RAISE EXCEPTION 'use the AgentOps Temporal reconciler functions'
            USING ERRCODE = '55000';
    END IF;
    v_tenant_id := CASE WHEN TG_OP = 'DELETE' THEN OLD.tenant_id ELSE NEW.tenant_id END;
    IF gda_control.current_tenant() IS NULL
       OR v_tenant_id IS DISTINCT FROM gda_control.current_tenant() THEN
        RAISE EXCEPTION 'AgentOps reconciler tenant context is missing or mismatched'
            USING ERRCODE = '42501';
    END IF;
    RETURN CASE WHEN TG_OP = 'DELETE' THEN OLD ELSE NEW END;
END;
$$;

CREATE OR REPLACE FUNCTION gda_control.acquire_agentops_temporal_reconciler_lease(
    p_tenant_id TEXT,
    p_workflow_id TEXT,
    p_lease_owner TEXT,
    p_lease_seconds INTEGER DEFAULT 60
)
RETURNS SETOF gda_control.agentops_temporal_reconciler_lease
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, gda_control
SET row_security = on
AS $$
DECLARE
    v_existing gda_control.agentops_temporal_reconciler_lease%ROWTYPE;
    v_now TIMESTAMPTZ := clock_timestamp();
    v_lease_exists BOOLEAN;
BEGIN
    IF gda_control.current_tenant() IS NULL
       OR p_tenant_id IS DISTINCT FROM gda_control.current_tenant() THEN
        RAISE EXCEPTION 'AgentOps reconciler tenant context is missing or mismatched'
            USING ERRCODE = '42501';
    END IF;
    IF p_workflow_id !~ '^[a-z][a-z0-9._:-]{1,254}$'
       OR p_lease_owner !~ '^(workload|agent):[^[:space:]]{1,128}$'
       OR p_lease_seconds IS NULL
       OR p_lease_seconds < 1
       OR p_lease_seconds > 3600 THEN
        RAISE EXCEPTION 'AgentOps reconciler lease request is invalid'
            USING ERRCODE = '22023';
    END IF;

    PERFORM pg_advisory_xact_lock(hashtextextended(
        'agentops-temporal-reconciler-lease|' || p_tenant_id || '|' ||
        p_workflow_id,
        0
    ));
    SELECT lease.* INTO v_existing
    FROM gda_control.agentops_temporal_reconciler_lease AS lease
    WHERE lease.tenant_id = p_tenant_id
      AND lease.workflow_id = p_workflow_id
    FOR UPDATE;
    v_lease_exists := FOUND;

    IF v_lease_exists
       AND v_existing.lease_expires_at > v_now
       AND v_existing.lease_owner IS DISTINCT FROM p_lease_owner THEN
        RAISE EXCEPTION 'AgentOps reconciler lease is owned by another worker'
            USING ERRCODE = '40001';
    END IF;

    PERFORM set_config(
        'gda.agentops_temporal_reconciler_write_allowed', '1', true
    );
    IF NOT v_lease_exists THEN
        RETURN QUERY
        INSERT INTO gda_control.agentops_temporal_reconciler_lease (
            tenant_id, workflow_id, lease_owner, lease_epoch,
            lease_acquired_at, lease_expires_at, lease_updated_at
        ) VALUES (
            p_tenant_id, p_workflow_id, p_lease_owner, 1,
            v_now, v_now + make_interval(secs => p_lease_seconds), v_now
        )
        RETURNING *;
    ELSIF v_existing.lease_expires_at > v_now THEN
        RETURN QUERY
        UPDATE gda_control.agentops_temporal_reconciler_lease AS lease
        SET lease_expires_at = GREATEST(
                lease.lease_expires_at,
                v_now + make_interval(secs => p_lease_seconds)
            ),
            lease_updated_at = v_now
        WHERE lease.tenant_id = p_tenant_id
          AND lease.workflow_id = p_workflow_id
        RETURNING lease.*;
    ELSE
        RETURN QUERY
        UPDATE gda_control.agentops_temporal_reconciler_lease AS lease
        SET lease_owner = p_lease_owner,
            lease_epoch = lease.lease_epoch + 1,
            lease_acquired_at = v_now,
            lease_expires_at = v_now + make_interval(secs => p_lease_seconds),
            lease_updated_at = v_now
        WHERE lease.tenant_id = p_tenant_id
          AND lease.workflow_id = p_workflow_id
        RETURNING lease.*;
    END IF;
    PERFORM set_config(
        'gda.agentops_temporal_reconciler_write_allowed', '0', true
    );
EXCEPTION WHEN OTHERS THEN
    PERFORM set_config(
        'gda.agentops_temporal_reconciler_write_allowed', '0', true
    );
    RAISE;
END;
$$;

CREATE OR REPLACE FUNCTION gda_control.renew_agentops_temporal_reconciler_lease(
    p_tenant_id TEXT,
    p_workflow_id TEXT,
    p_lease_owner TEXT,
    p_lease_epoch BIGINT,
    p_lease_seconds INTEGER DEFAULT 60
)
RETURNS SETOF gda_control.agentops_temporal_reconciler_lease
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, gda_control
SET row_security = on
AS $$
DECLARE
    v_now TIMESTAMPTZ := clock_timestamp();
BEGIN
    IF gda_control.current_tenant() IS NULL
       OR p_tenant_id IS DISTINCT FROM gda_control.current_tenant() THEN
        RAISE EXCEPTION 'AgentOps reconciler tenant context is missing or mismatched'
            USING ERRCODE = '42501';
    END IF;
    IF p_lease_seconds IS NULL
       OR p_lease_seconds < 1
       OR p_lease_seconds > 3600 THEN
        RAISE EXCEPTION 'AgentOps reconciler lease duration is invalid'
            USING ERRCODE = '22023';
    END IF;
    PERFORM set_config(
        'gda.agentops_temporal_reconciler_write_allowed', '1', true
    );
    RETURN QUERY
    UPDATE gda_control.agentops_temporal_reconciler_lease AS lease
    SET lease_expires_at = v_now + make_interval(secs => p_lease_seconds),
        lease_updated_at = v_now
    WHERE lease.tenant_id = p_tenant_id
      AND lease.workflow_id = p_workflow_id
      AND lease.lease_owner = p_lease_owner
      AND lease.lease_epoch = p_lease_epoch
      AND lease.lease_expires_at > v_now
    RETURNING lease.*;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'AgentOps reconciler lease is stale, expired, or not owned'
            USING ERRCODE = '40001';
    END IF;
    PERFORM set_config(
        'gda.agentops_temporal_reconciler_write_allowed', '0', true
    );
EXCEPTION WHEN OTHERS THEN
    PERFORM set_config(
        'gda.agentops_temporal_reconciler_write_allowed', '0', true
    );
    RAISE;
END;
$$;

CREATE OR REPLACE FUNCTION gda_control.release_agentops_temporal_reconciler_lease(
    p_tenant_id TEXT,
    p_workflow_id TEXT,
    p_lease_owner TEXT,
    p_lease_epoch BIGINT
)
RETURNS SETOF gda_control.agentops_temporal_reconciler_lease
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, gda_control
SET row_security = on
AS $$
DECLARE
    v_now TIMESTAMPTZ := clock_timestamp();
BEGIN
    IF gda_control.current_tenant() IS NULL
       OR p_tenant_id IS DISTINCT FROM gda_control.current_tenant() THEN
        RAISE EXCEPTION 'AgentOps reconciler tenant context is missing or mismatched'
            USING ERRCODE = '42501';
    END IF;
    PERFORM set_config(
        'gda.agentops_temporal_reconciler_write_allowed', '1', true
    );
    RETURN QUERY
    UPDATE gda_control.agentops_temporal_reconciler_lease AS lease
    SET lease_expires_at = v_now,
        lease_updated_at = v_now
    WHERE lease.tenant_id = p_tenant_id
      AND lease.workflow_id = p_workflow_id
      AND lease.lease_owner = p_lease_owner
      AND lease.lease_epoch = p_lease_epoch
      AND lease.lease_expires_at > v_now
    RETURNING lease.*;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'AgentOps reconciler lease is stale, expired, or not owned'
            USING ERRCODE = '40001';
    END IF;
    PERFORM set_config(
        'gda.agentops_temporal_reconciler_write_allowed', '0', true
    );
EXCEPTION WHEN OTHERS THEN
    PERFORM set_config(
        'gda.agentops_temporal_reconciler_write_allowed', '0', true
    );
    RAISE;
END;
$$;

CREATE OR REPLACE FUNCTION gda_control.assert_agentops_temporal_reconciler_lease(
    p_tenant_id TEXT,
    p_workflow_id TEXT,
    p_lease_owner TEXT,
    p_lease_epoch BIGINT
)
RETURNS VOID
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, gda_control
SET row_security = on
AS $$
BEGIN
    IF gda_control.current_tenant() IS NULL
       OR p_tenant_id IS DISTINCT FROM gda_control.current_tenant() THEN
        RAISE EXCEPTION 'AgentOps reconciler tenant context is missing or mismatched'
            USING ERRCODE = '42501';
    END IF;
    PERFORM 1
    FROM gda_control.agentops_temporal_reconciler_lease AS lease
    WHERE lease.tenant_id = p_tenant_id
      AND lease.workflow_id = p_workflow_id
      AND lease.lease_owner = p_lease_owner
      AND lease.lease_epoch = p_lease_epoch
      AND lease.lease_expires_at > clock_timestamp()
    FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'AgentOps reconciler lease is stale, expired, or not owned'
            USING ERRCODE = '40001';
    END IF;
END;
$$;

CREATE OR REPLACE FUNCTION gda_control.record_agentops_temporal_checkpoint_fenced(
    p_tenant_id TEXT,
    p_workflow_id TEXT,
    p_previous_checkpoint_sha256 TEXT,
    p_checkpoint_document JSONB,
    p_fingerprint_payload TEXT,
    p_recorded_by TEXT,
    p_lease_owner TEXT,
    p_lease_epoch BIGINT
)
RETURNS TABLE(
    checkpoint_document JSONB,
    checkpoint_sequence BIGINT,
    created BOOLEAN
)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, gda_control
SET row_security = on
AS $$
DECLARE
    v_result RECORD;
    v_existing gda_control.agentops_temporal_checkpoint_lease_binding%ROWTYPE;
    v_checkpoint_sha256 TEXT;
BEGIN
    IF p_recorded_by IS DISTINCT FROM p_lease_owner THEN
        RAISE EXCEPTION 'checkpoint recorder must own the reconciler lease'
            USING ERRCODE = '42501';
    END IF;
    PERFORM gda_control.assert_agentops_temporal_reconciler_lease(
        p_tenant_id, p_workflow_id, p_lease_owner, p_lease_epoch
    );
    SELECT * INTO v_result
    FROM gda_control.record_agentops_temporal_checkpoint(
        p_tenant_id, p_workflow_id, p_previous_checkpoint_sha256,
        p_checkpoint_document, p_fingerprint_payload, p_recorded_by
    );
    v_checkpoint_sha256 := p_checkpoint_document ->> 'checkpoint_sha256';

    SELECT binding.* INTO v_existing
    FROM gda_control.agentops_temporal_checkpoint_lease_binding AS binding
    WHERE binding.tenant_id = p_tenant_id
      AND binding.workflow_id = p_workflow_id
      AND binding.checkpoint_sha256 = v_checkpoint_sha256;
    IF FOUND THEN
        IF v_existing.lease_owner IS DISTINCT FROM p_lease_owner
           OR v_existing.lease_epoch IS DISTINCT FROM p_lease_epoch THEN
            RAISE EXCEPTION 'checkpoint is bound to a different fencing epoch'
                USING ERRCODE = '40001';
        END IF;
    ELSE
        PERFORM set_config(
            'gda.agentops_temporal_reconciler_write_allowed', '1', true
        );
        INSERT INTO gda_control.agentops_temporal_checkpoint_lease_binding (
            tenant_id, workflow_id, checkpoint_sha256,
            lease_owner, lease_epoch
        ) VALUES (
            p_tenant_id, p_workflow_id, v_checkpoint_sha256,
            p_lease_owner, p_lease_epoch
        );
        PERFORM set_config(
            'gda.agentops_temporal_reconciler_write_allowed', '0', true
        );
    END IF;
    RETURN QUERY SELECT
        v_result.checkpoint_document,
        v_result.checkpoint_sequence,
        v_result.created;
EXCEPTION WHEN OTHERS THEN
    PERFORM set_config(
        'gda.agentops_temporal_reconciler_write_allowed', '0', true
    );
    RAISE;
END;
$$;

CREATE OR REPLACE FUNCTION gda_control.record_agentops_temporal_reconciliation_fenced(
    p_tenant_id TEXT,
    p_workflow_id TEXT,
    p_provider_run_id TEXT,
    p_checkpoint_sha256 TEXT,
    p_observation_document JSONB,
    p_observation_fingerprint_payload TEXT,
    p_reconciliation_document JSONB,
    p_reconciliation_fingerprint_payload TEXT,
    p_recorded_by TEXT,
    p_lease_owner TEXT,
    p_lease_epoch BIGINT
)
RETURNS TABLE(
    observation_document JSONB,
    reconciliation_document JSONB,
    created BOOLEAN
)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, gda_control
SET row_security = on
AS $$
DECLARE
    v_result RECORD;
    v_existing gda_control.agentops_temporal_reconciliation_lease_binding%ROWTYPE;
    v_reconciliation_sha256 TEXT;
BEGIN
    IF p_recorded_by IS DISTINCT FROM p_lease_owner THEN
        RAISE EXCEPTION 'reconciliation recorder must own the reconciler lease'
            USING ERRCODE = '42501';
    END IF;
    PERFORM gda_control.assert_agentops_temporal_reconciler_lease(
        p_tenant_id, p_workflow_id, p_lease_owner, p_lease_epoch
    );
    SELECT * INTO v_result
    FROM gda_control.record_agentops_temporal_reconciliation(
        p_tenant_id, p_workflow_id, p_provider_run_id,
        p_checkpoint_sha256, p_observation_document,
        p_observation_fingerprint_payload, p_reconciliation_document,
        p_reconciliation_fingerprint_payload, p_recorded_by
    );
    v_reconciliation_sha256 :=
        p_reconciliation_document ->> 'reconciliation_sha256';

    SELECT binding.* INTO v_existing
    FROM gda_control.agentops_temporal_reconciliation_lease_binding AS binding
    WHERE binding.tenant_id = p_tenant_id
      AND binding.workflow_id = p_workflow_id
      AND binding.reconciliation_sha256 = v_reconciliation_sha256;
    IF FOUND THEN
        IF v_existing.lease_owner IS DISTINCT FROM p_lease_owner
           OR v_existing.lease_epoch IS DISTINCT FROM p_lease_epoch THEN
            RAISE EXCEPTION 'reconciliation is bound to a different fencing epoch'
                USING ERRCODE = '40001';
        END IF;
    ELSE
        PERFORM set_config(
            'gda.agentops_temporal_reconciler_write_allowed', '1', true
        );
        INSERT INTO gda_control.agentops_temporal_reconciliation_lease_binding (
            tenant_id, workflow_id, reconciliation_sha256,
            lease_owner, lease_epoch
        ) VALUES (
            p_tenant_id, p_workflow_id, v_reconciliation_sha256,
            p_lease_owner, p_lease_epoch
        );
        PERFORM set_config(
            'gda.agentops_temporal_reconciler_write_allowed', '0', true
        );
    END IF;
    RETURN QUERY SELECT
        v_result.observation_document,
        v_result.reconciliation_document,
        v_result.created;
EXCEPTION WHEN OTHERS THEN
    PERFORM set_config(
        'gda.agentops_temporal_reconciler_write_allowed', '0', true
    );
    RAISE;
END;
$$;

DROP TRIGGER IF EXISTS trg_gda_agentops_temporal_reconciler_lease_guard
    ON gda_control.agentops_temporal_reconciler_lease;
CREATE TRIGGER trg_gda_agentops_temporal_reconciler_lease_guard
BEFORE INSERT OR UPDATE OR DELETE
ON gda_control.agentops_temporal_reconciler_lease
FOR EACH ROW EXECUTE FUNCTION gda_control.guard_agentops_temporal_reconciler_state();

DROP TRIGGER IF EXISTS trg_gda_agentops_temporal_checkpoint_lease_binding_guard
    ON gda_control.agentops_temporal_checkpoint_lease_binding;
CREATE TRIGGER trg_gda_agentops_temporal_checkpoint_lease_binding_guard
BEFORE INSERT ON gda_control.agentops_temporal_checkpoint_lease_binding
FOR EACH ROW EXECUTE FUNCTION gda_control.guard_agentops_temporal_reconciler_state();
DROP TRIGGER IF EXISTS trg_gda_agentops_temporal_checkpoint_lease_binding_immutable
    ON gda_control.agentops_temporal_checkpoint_lease_binding;
CREATE TRIGGER trg_gda_agentops_temporal_checkpoint_lease_binding_immutable
BEFORE UPDATE OR DELETE ON gda_control.agentops_temporal_checkpoint_lease_binding
FOR EACH ROW EXECUTE FUNCTION gda_control.reject_immutable_mutation();

DROP TRIGGER IF EXISTS trg_gda_agentops_temporal_reconciliation_lease_binding_guard
    ON gda_control.agentops_temporal_reconciliation_lease_binding;
CREATE TRIGGER trg_gda_agentops_temporal_reconciliation_lease_binding_guard
BEFORE INSERT ON gda_control.agentops_temporal_reconciliation_lease_binding
FOR EACH ROW EXECUTE FUNCTION gda_control.guard_agentops_temporal_reconciler_state();
DROP TRIGGER IF EXISTS trg_gda_agentops_temporal_reconciliation_lease_binding_immutable
    ON gda_control.agentops_temporal_reconciliation_lease_binding;
CREATE TRIGGER trg_gda_agentops_temporal_reconciliation_lease_binding_immutable
BEFORE UPDATE OR DELETE ON gda_control.agentops_temporal_reconciliation_lease_binding
FOR EACH ROW EXECUTE FUNCTION gda_control.reject_immutable_mutation();

ALTER TABLE gda_control.agentops_temporal_reconciler_lease
    ENABLE ROW LEVEL SECURITY;
ALTER TABLE gda_control.agentops_temporal_reconciler_lease
    FORCE ROW LEVEL SECURITY;
ALTER TABLE gda_control.agentops_temporal_checkpoint_lease_binding
    ENABLE ROW LEVEL SECURITY;
ALTER TABLE gda_control.agentops_temporal_checkpoint_lease_binding
    FORCE ROW LEVEL SECURITY;
ALTER TABLE gda_control.agentops_temporal_reconciliation_lease_binding
    ENABLE ROW LEVEL SECURITY;
ALTER TABLE gda_control.agentops_temporal_reconciliation_lease_binding
    FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS tenant_isolation
    ON gda_control.agentops_temporal_reconciler_lease;
CREATE POLICY tenant_isolation
    ON gda_control.agentops_temporal_reconciler_lease
    USING (tenant_id = gda_control.current_tenant())
    WITH CHECK (tenant_id = gda_control.current_tenant());
DROP POLICY IF EXISTS tenant_isolation
    ON gda_control.agentops_temporal_checkpoint_lease_binding;
CREATE POLICY tenant_isolation
    ON gda_control.agentops_temporal_checkpoint_lease_binding
    USING (tenant_id = gda_control.current_tenant())
    WITH CHECK (tenant_id = gda_control.current_tenant());
DROP POLICY IF EXISTS tenant_isolation
    ON gda_control.agentops_temporal_reconciliation_lease_binding;
CREATE POLICY tenant_isolation
    ON gda_control.agentops_temporal_reconciliation_lease_binding
    USING (tenant_id = gda_control.current_tenant())
    WITH CHECK (tenant_id = gda_control.current_tenant());

REVOKE ALL ON TABLE gda_control.agentops_temporal_reconciler_lease
    FROM PUBLIC, gda_control_gateway;
REVOKE ALL ON TABLE gda_control.agentops_temporal_checkpoint_lease_binding
    FROM PUBLIC, gda_control_gateway;
REVOKE ALL ON TABLE gda_control.agentops_temporal_reconciliation_lease_binding
    FROM PUBLIC, gda_control_gateway;
GRANT SELECT ON TABLE gda_control.agentops_temporal_reconciler_lease
    TO gda_control_gateway;
GRANT SELECT ON TABLE gda_control.agentops_temporal_checkpoint_lease_binding
    TO gda_control_gateway;
GRANT SELECT ON TABLE gda_control.agentops_temporal_reconciliation_lease_binding
    TO gda_control_gateway;

-- Once migration 241 is installed, gateway callers must use fenced writes.
REVOKE ALL ON FUNCTION gda_control.record_agentops_temporal_checkpoint(
    TEXT, TEXT, TEXT, JSONB, TEXT, TEXT
) FROM gda_control_gateway;
REVOKE ALL ON FUNCTION gda_control.record_agentops_temporal_reconciliation(
    TEXT, TEXT, TEXT, TEXT, JSONB, TEXT, JSONB, TEXT, TEXT
) FROM gda_control_gateway;

REVOKE ALL ON FUNCTION gda_control.guard_agentops_temporal_reconciler_state()
    FROM PUBLIC;
REVOKE ALL ON FUNCTION gda_control.assert_agentops_temporal_reconciler_lease(
    TEXT, TEXT, TEXT, BIGINT
) FROM PUBLIC;
REVOKE ALL ON FUNCTION gda_control.acquire_agentops_temporal_reconciler_lease(
    TEXT, TEXT, TEXT, INTEGER
) FROM PUBLIC;
REVOKE ALL ON FUNCTION gda_control.renew_agentops_temporal_reconciler_lease(
    TEXT, TEXT, TEXT, BIGINT, INTEGER
) FROM PUBLIC;
REVOKE ALL ON FUNCTION gda_control.release_agentops_temporal_reconciler_lease(
    TEXT, TEXT, TEXT, BIGINT
) FROM PUBLIC;
REVOKE ALL ON FUNCTION gda_control.record_agentops_temporal_checkpoint_fenced(
    TEXT, TEXT, TEXT, JSONB, TEXT, TEXT, TEXT, BIGINT
) FROM PUBLIC;
REVOKE ALL ON FUNCTION gda_control.record_agentops_temporal_reconciliation_fenced(
    TEXT, TEXT, TEXT, TEXT, JSONB, TEXT, JSONB, TEXT, TEXT, TEXT, BIGINT
) FROM PUBLIC;

GRANT EXECUTE ON FUNCTION gda_control.acquire_agentops_temporal_reconciler_lease(
    TEXT, TEXT, TEXT, INTEGER
) TO gda_control_gateway;
GRANT EXECUTE ON FUNCTION gda_control.renew_agentops_temporal_reconciler_lease(
    TEXT, TEXT, TEXT, BIGINT, INTEGER
) TO gda_control_gateway;
GRANT EXECUTE ON FUNCTION gda_control.release_agentops_temporal_reconciler_lease(
    TEXT, TEXT, TEXT, BIGINT
) TO gda_control_gateway;
GRANT EXECUTE ON FUNCTION gda_control.record_agentops_temporal_checkpoint_fenced(
    TEXT, TEXT, TEXT, JSONB, TEXT, TEXT, TEXT, BIGINT
) TO gda_control_gateway;
GRANT EXECUTE ON FUNCTION gda_control.record_agentops_temporal_reconciliation_fenced(
    TEXT, TEXT, TEXT, TEXT, JSONB, TEXT, JSONB, TEXT, TEXT, TEXT, BIGINT
) TO gda_control_gateway;
