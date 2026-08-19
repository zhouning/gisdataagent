-- 177: Durable append-only aggregate ledger for ordered multi-provider recovery.

-- Recovery events are plan-local. Migration 170 used tenant-wide event hash
-- uniqueness even though the event fingerprint does not contain plan identity.
ALTER TABLE gda_control.cross_store_projection_recovery_event_history
    DROP CONSTRAINT IF EXISTS uq_gda_projection_recovery_event_sha;
ALTER TABLE gda_control.cross_store_projection_recovery_event_history
    ADD CONSTRAINT uq_gda_projection_recovery_event_sha
        UNIQUE (tenant_id, plan_sha256, event_sha256);

CREATE OR REPLACE FUNCTION gda_control.record_cross_store_projection_recovery_snapshot(
    p_tenant_id TEXT,
    p_plan_sha256 TEXT,
    p_plan_idempotency_key TEXT,
    p_projection_id TEXT,
    p_target_engine TEXT,
    p_target_ref TEXT,
    p_snapshot_document JSONB,
    p_snapshot_sha256 TEXT,
    p_event_document JSONB,
    p_event_sha256 TEXT
)
RETURNS TABLE(snapshot_document JSONB, created BOOLEAN)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, gda_control
SET row_security = on
AS $$
DECLARE
    v_current gda_control.cross_store_projection_recovery_snapshot_history%ROWTYPE;
    v_existing gda_control.cross_store_projection_recovery_snapshot_history%ROWTYPE;
    v_event gda_control.cross_store_projection_recovery_event_history%ROWTYPE;
    v_new_event_count INTEGER;
    v_old_event_count INTEGER;
    v_snapshot_version INTEGER;
    v_index INTEGER;
BEGIN
    IF gda_control.current_tenant() IS NULL
       OR p_tenant_id IS DISTINCT FROM gda_control.current_tenant() THEN
        RAISE EXCEPTION 'projection recovery tenant context is missing or mismatched'
            USING ERRCODE = '42501';
    END IF;
    IF p_plan_sha256 IS NULL OR p_plan_sha256 !~ '^[0-9a-f]{64}$'
       OR p_plan_idempotency_key IS NULL
       OR p_plan_idempotency_key !~ '^[0-9a-f]{64}$'
       OR p_projection_id IS NULL
       OR p_projection_id !~ '^[A-Za-z0-9][A-Za-z0-9._:-]{2,127}$'
       OR p_target_engine NOT IN ('postgis', 'rdf', 'vector', 'object_store', 'lakehouse')
       OR NULLIF(btrim(p_target_ref), '') IS NULL
       OR octet_length(p_target_ref) > 512
       OR p_snapshot_sha256 IS NULL OR p_snapshot_sha256 !~ '^[0-9a-f]{64}$'
       OR p_event_sha256 IS NULL OR p_event_sha256 !~ '^[0-9a-f]{64}$'
       OR p_snapshot_document IS NULL
       OR jsonb_typeof(p_snapshot_document) <> 'object'
       OR p_event_document IS NULL
       OR jsonb_typeof(p_event_document) <> 'object'
       OR p_snapshot_document ->> 'tenant_id' IS DISTINCT FROM p_tenant_id
       OR p_snapshot_document ->> 'projection_id' IS DISTINCT FROM p_projection_id
       OR p_snapshot_document ->> 'target_engine' IS DISTINCT FROM p_target_engine
       OR p_snapshot_document ->> 'target_ref' IS DISTINCT FROM p_target_ref
       OR p_snapshot_document ->> 'plan_sha256' IS DISTINCT FROM p_plan_sha256
       OR p_snapshot_document ->> 'plan_idempotency_key'
            IS DISTINCT FROM p_plan_idempotency_key
       OR p_snapshot_document ->> 'snapshot_sha256' IS DISTINCT FROM p_snapshot_sha256
       OR p_event_document ->> 'event_sha256' IS DISTINCT FROM p_event_sha256
       OR jsonb_typeof(p_snapshot_document -> 'events') <> 'array'
       OR jsonb_array_length(p_snapshot_document -> 'events') < 1 THEN
        RAISE EXCEPTION 'projection recovery identity or evidence is invalid'
            USING ERRCODE = '22023';
    END IF;

    PERFORM pg_advisory_xact_lock(
        hashtextextended(
            'projection-recovery-plan|' || p_tenant_id || '|' || p_plan_sha256,
            0
        )
    );

    SELECT history.* INTO v_existing
    FROM gda_control.cross_store_projection_recovery_snapshot_history AS history
    WHERE history.tenant_id = p_tenant_id
      AND history.snapshot_sha256 = p_snapshot_sha256;
    IF FOUND THEN
        IF v_existing.snapshot_document IS DISTINCT FROM p_snapshot_document THEN
            RAISE EXCEPTION 'projection recovery snapshot idempotency evidence differs'
                USING ERRCODE = '40001';
        END IF;
        RETURN QUERY SELECT v_existing.snapshot_document, FALSE;
        RETURN;
    END IF;

    SELECT events.* INTO v_event
    FROM gda_control.cross_store_projection_recovery_event_history AS events
    WHERE events.tenant_id = p_tenant_id
      AND events.plan_sha256 = p_plan_sha256
      AND events.event_sha256 = p_event_sha256;
    IF FOUND THEN
        IF v_event.event_document IS DISTINCT FROM p_event_document THEN
            RAISE EXCEPTION 'projection recovery event idempotency evidence differs'
                USING ERRCODE = '40001';
        END IF;
        RAISE EXCEPTION 'projection recovery event already belongs to another snapshot'
            USING ERRCODE = '40001';
    END IF;

    SELECT history.* INTO v_current
    FROM gda_control.cross_store_projection_recovery_snapshot_history AS history
    WHERE history.tenant_id = p_tenant_id
      AND history.plan_sha256 = p_plan_sha256
    ORDER BY history.snapshot_version DESC
    LIMIT 1
    FOR UPDATE;

    v_new_event_count := jsonb_array_length(p_snapshot_document -> 'events');
    IF NOT FOUND THEN
        IF v_new_event_count <> 1 THEN
            RAISE EXCEPTION 'initial projection recovery snapshot must contain one event'
                USING ERRCODE = '40001';
        END IF;
        v_old_event_count := 0;
        v_snapshot_version := 1;
    ELSE
        v_old_event_count := jsonb_array_length(v_current.snapshot_document -> 'events');
        IF v_new_event_count <> v_old_event_count + 1 THEN
            RAISE EXCEPTION 'projection recovery event chain skipped a predecessor'
                USING ERRCODE = '40001';
        END IF;
        FOR v_index IN 0..v_old_event_count - 1 LOOP
            IF (p_snapshot_document -> 'events' -> v_index)
                IS DISTINCT FROM (v_current.snapshot_document -> 'events' -> v_index) THEN
                RAISE EXCEPTION 'projection recovery event chain is not append-only'
                    USING ERRCODE = '40001';
            END IF;
        END LOOP;
        v_snapshot_version := v_current.snapshot_version + 1;
    END IF;

    IF (p_snapshot_document -> 'events' -> (v_new_event_count - 1))
        IS DISTINCT FROM p_event_document THEN
        RAISE EXCEPTION 'latest recovery event does not match snapshot event chain'
            USING ERRCODE = '22023';
    END IF;

    PERFORM set_config(
        'gda.cross_store_projection_recovery_write_allowed', '1', true
    );
    INSERT INTO gda_control.cross_store_projection_recovery_event_history (
        tenant_id, plan_sha256, event_index, event_sha256, event_document
    ) VALUES (
        p_tenant_id, p_plan_sha256, v_new_event_count,
        p_event_sha256, p_event_document
    );
    INSERT INTO gda_control.cross_store_projection_recovery_snapshot_history (
        tenant_id, plan_sha256, snapshot_version, plan_idempotency_key,
        projection_id, target_engine, target_ref, snapshot_sha256,
        snapshot_document
    ) VALUES (
        p_tenant_id, p_plan_sha256, v_snapshot_version, p_plan_idempotency_key,
        p_projection_id, p_target_engine, p_target_ref, p_snapshot_sha256,
        p_snapshot_document
    )
    RETURNING * INTO v_existing;
    PERFORM set_config(
        'gda.cross_store_projection_recovery_write_allowed', '0', true
    );

    RETURN QUERY SELECT v_existing.snapshot_document, TRUE;
EXCEPTION WHEN OTHERS THEN
    PERFORM set_config(
        'gda.cross_store_projection_recovery_write_allowed', '0', true
    );
    RAISE;
END;
$$;

CREATE TABLE IF NOT EXISTS gda_control.cross_store_projection_federated_recovery_event_history (
    tenant_id TEXT NOT NULL,
    run_id TEXT NOT NULL,
    event_sequence INTEGER NOT NULL,
    event_sha256 CHAR(64) NOT NULL,
    event_document JSONB NOT NULL,
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (tenant_id, run_id, event_sequence),
    CONSTRAINT uq_gda_federated_projection_recovery_event_sha
        UNIQUE (tenant_id, event_sha256),
    CONSTRAINT ck_gda_federated_projection_recovery_event_tenant
        CHECK (tenant_id ~ '^[a-z0-9][a-z0-9._-]{0,63}$'),
    CONSTRAINT ck_gda_federated_projection_recovery_event_run
        CHECK (NULLIF(btrim(run_id), '') IS NOT NULL AND octet_length(run_id) <= 256),
    CONSTRAINT ck_gda_federated_projection_recovery_event_sequence
        CHECK (event_sequence >= 1),
    CONSTRAINT ck_gda_federated_projection_recovery_event_sha
        CHECK (event_sha256 ~ '^[0-9a-f]{64}$'),
    CONSTRAINT ck_gda_federated_projection_recovery_event_document
        CHECK (
            jsonb_typeof(event_document) = 'object'
            AND (event_document ->> 'sequence')::INTEGER = event_sequence
            AND event_document ->> 'event_sha256' = event_sha256
        )
);

CREATE TABLE IF NOT EXISTS gda_control.cross_store_projection_federated_recovery_snapshot_history (
    tenant_id TEXT NOT NULL,
    run_id TEXT NOT NULL,
    snapshot_version INTEGER NOT NULL,
    plan_sha256s JSONB NOT NULL,
    snapshot_sha256 CHAR(64) NOT NULL,
    snapshot_document JSONB NOT NULL,
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (tenant_id, run_id, snapshot_version),
    CONSTRAINT uq_gda_federated_projection_recovery_snapshot_sha
        UNIQUE (tenant_id, snapshot_sha256),
    CONSTRAINT ck_gda_federated_projection_recovery_snapshot_tenant
        CHECK (tenant_id ~ '^[a-z0-9][a-z0-9._-]{0,63}$'),
    CONSTRAINT ck_gda_federated_projection_recovery_snapshot_run
        CHECK (NULLIF(btrim(run_id), '') IS NOT NULL AND octet_length(run_id) <= 256),
    CONSTRAINT ck_gda_federated_projection_recovery_snapshot_version
        CHECK (snapshot_version >= 1),
    CONSTRAINT ck_gda_federated_projection_recovery_snapshot_plans
        CHECK (
            jsonb_typeof(plan_sha256s) = 'array'
            AND jsonb_array_length(plan_sha256s) BETWEEN 2 AND 32
        ),
    CONSTRAINT ck_gda_federated_projection_recovery_snapshot_sha
        CHECK (snapshot_sha256 ~ '^[0-9a-f]{64}$'),
    CONSTRAINT ck_gda_federated_projection_recovery_snapshot_document
        CHECK (
            jsonb_typeof(snapshot_document) = 'object'
            AND snapshot_document ->> 'tenant_id' = tenant_id
            AND snapshot_document ->> 'run_id' = run_id
            AND snapshot_document -> 'plan_sha256s' = plan_sha256s
            AND snapshot_document ->> 'snapshot_sha256' = snapshot_sha256
        )
);

CREATE INDEX IF NOT EXISTS idx_gda_federated_projection_recovery_event_run
    ON gda_control.cross_store_projection_federated_recovery_event_history
        (tenant_id, run_id, event_sequence);
CREATE INDEX IF NOT EXISTS idx_gda_federated_projection_recovery_snapshot_current
    ON gda_control.cross_store_projection_federated_recovery_snapshot_history
        (tenant_id, run_id, snapshot_version DESC);

CREATE OR REPLACE VIEW gda_control.cross_store_projection_federated_recovery_snapshot_current
WITH (security_invoker = true)
AS
SELECT DISTINCT ON (tenant_id, run_id)
       tenant_id, run_id, snapshot_version, plan_sha256s, snapshot_sha256,
       snapshot_document, recorded_at
FROM gda_control.cross_store_projection_federated_recovery_snapshot_history
ORDER BY tenant_id, run_id, snapshot_version DESC;

CREATE OR REPLACE FUNCTION gda_control.guard_cross_store_projection_federated_recovery_insert()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    IF COALESCE(
        current_setting(
            'gda.cross_store_projection_federated_recovery_write_allowed', true
        ),
        ''
    ) <> '1' THEN
        RAISE EXCEPTION
            'use gda_control.record_cross_store_projection_federated_recovery_snapshot()'
            USING ERRCODE = '55000';
    END IF;
    IF gda_control.current_tenant() IS NULL
       OR NEW.tenant_id IS DISTINCT FROM gda_control.current_tenant() THEN
        RAISE EXCEPTION 'federated projection recovery tenant context is missing or mismatched'
            USING ERRCODE = '42501';
    END IF;
    RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION gda_control.record_cross_store_projection_federated_recovery_snapshot(
    p_tenant_id TEXT,
    p_run_id TEXT,
    p_plan_sha256s JSONB,
    p_snapshot_document JSONB,
    p_snapshot_sha256 TEXT,
    p_event_document JSONB,
    p_event_sha256 TEXT
)
RETURNS TABLE(snapshot_document JSONB, created BOOLEAN)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, gda_control
SET row_security = on
AS $$
DECLARE
    v_current gda_control.cross_store_projection_federated_recovery_snapshot_history%ROWTYPE;
    v_existing gda_control.cross_store_projection_federated_recovery_snapshot_history%ROWTYPE;
    v_event gda_control.cross_store_projection_federated_recovery_event_history%ROWTYPE;
    v_event_count INTEGER;
    v_old_event_count INTEGER;
    v_snapshot_version INTEGER;
    v_index INTEGER;
    v_plan_count INTEGER;
    v_unique_plan_count INTEGER;
BEGIN
    IF gda_control.current_tenant() IS NULL
       OR p_tenant_id IS DISTINCT FROM gda_control.current_tenant() THEN
        RAISE EXCEPTION 'federated projection recovery tenant context is missing or mismatched'
            USING ERRCODE = '42501';
    END IF;
    IF p_run_id IS NULL
       OR NULLIF(btrim(p_run_id), '') IS NULL
       OR octet_length(p_run_id) > 256
       OR p_plan_sha256s IS NULL
       OR jsonb_typeof(p_plan_sha256s) <> 'array'
       OR jsonb_array_length(p_plan_sha256s) NOT BETWEEN 2 AND 32
       OR p_snapshot_sha256 IS NULL
       OR p_snapshot_sha256 !~ '^[0-9a-f]{64}$'
       OR p_event_sha256 IS NULL
       OR p_event_sha256 !~ '^[0-9a-f]{64}$'
       OR p_snapshot_document IS NULL
       OR jsonb_typeof(p_snapshot_document) <> 'object'
       OR p_event_document IS NULL
       OR jsonb_typeof(p_event_document) <> 'object'
       OR p_snapshot_document ->> 'tenant_id' IS DISTINCT FROM p_tenant_id
       OR p_snapshot_document ->> 'run_id' IS DISTINCT FROM p_run_id
       OR p_snapshot_document -> 'plan_sha256s' IS DISTINCT FROM p_plan_sha256s
       OR p_snapshot_document ->> 'snapshot_sha256' IS DISTINCT FROM p_snapshot_sha256
       OR p_event_document ->> 'event_sha256' IS DISTINCT FROM p_event_sha256
       OR jsonb_typeof(p_snapshot_document -> 'events') <> 'array'
       OR jsonb_array_length(p_snapshot_document -> 'events') < 1 THEN
        RAISE EXCEPTION 'federated projection recovery identity or evidence is invalid'
            USING ERRCODE = '22023';
    END IF;

    SELECT count(*), count(DISTINCT value)
    INTO v_plan_count, v_unique_plan_count
    FROM jsonb_array_elements_text(p_plan_sha256s);
    IF v_plan_count IS DISTINCT FROM v_unique_plan_count
       OR EXISTS (
            SELECT 1
            FROM jsonb_array_elements_text(p_plan_sha256s) AS plan(value)
            WHERE plan.value !~ '^[0-9a-f]{64}$'
       ) THEN
        RAISE EXCEPTION 'federated projection recovery plan identities are invalid'
            USING ERRCODE = '22023';
    END IF;

    PERFORM pg_advisory_xact_lock(
        hashtextextended(
            'federated-projection-recovery-run|' || p_tenant_id || '|' || p_run_id,
            0
        )
    );

    SELECT history.* INTO v_existing
    FROM gda_control.cross_store_projection_federated_recovery_snapshot_history AS history
    WHERE history.tenant_id = p_tenant_id
      AND history.snapshot_sha256 = p_snapshot_sha256;
    IF FOUND THEN
        IF v_existing.snapshot_document IS DISTINCT FROM p_snapshot_document THEN
            RAISE EXCEPTION 'federated recovery snapshot idempotency evidence differs'
                USING ERRCODE = '40001';
        END IF;
        RETURN QUERY SELECT v_existing.snapshot_document, FALSE;
        RETURN;
    END IF;

    SELECT events.* INTO v_event
    FROM gda_control.cross_store_projection_federated_recovery_event_history AS events
    WHERE events.tenant_id = p_tenant_id
      AND events.event_sha256 = p_event_sha256;
    IF FOUND THEN
        IF v_event.event_document IS DISTINCT FROM p_event_document THEN
            RAISE EXCEPTION 'federated recovery event idempotency evidence differs'
                USING ERRCODE = '40001';
        END IF;
        RAISE EXCEPTION 'federated recovery event already belongs to another snapshot'
            USING ERRCODE = '40001';
    END IF;

    SELECT history.* INTO v_current
    FROM gda_control.cross_store_projection_federated_recovery_snapshot_history AS history
    WHERE history.tenant_id = p_tenant_id
      AND history.run_id = p_run_id
    ORDER BY history.snapshot_version DESC
    LIMIT 1
    FOR UPDATE;

    v_event_count := jsonb_array_length(p_snapshot_document -> 'events');
    IF NOT FOUND THEN
        IF v_event_count <> 1
           OR (p_event_document ->> 'sequence')::INTEGER <> 1 THEN
            RAISE EXCEPTION 'initial federated recovery snapshot must contain event one'
                USING ERRCODE = '40001';
        END IF;
        v_old_event_count := 0;
        v_snapshot_version := 1;
    ELSE
        IF v_current.plan_sha256s IS DISTINCT FROM p_plan_sha256s THEN
            RAISE EXCEPTION 'federated recovery run plan identity changed'
                USING ERRCODE = '40001';
        END IF;
        v_old_event_count := jsonb_array_length(v_current.snapshot_document -> 'events');
        IF v_event_count <> v_old_event_count + 1
           OR (p_event_document ->> 'sequence')::INTEGER <> v_event_count THEN
            RAISE EXCEPTION 'federated recovery event chain skipped a predecessor'
                USING ERRCODE = '40001';
        END IF;
        FOR v_index IN 0..v_old_event_count - 1 LOOP
            IF (p_snapshot_document -> 'events' -> v_index)
                IS DISTINCT FROM (v_current.snapshot_document -> 'events' -> v_index) THEN
                RAISE EXCEPTION 'federated recovery event chain is not append-only'
                    USING ERRCODE = '40001';
            END IF;
        END LOOP;
        v_snapshot_version := v_current.snapshot_version + 1;
    END IF;

    IF (p_snapshot_document -> 'events' -> (v_event_count - 1))
        IS DISTINCT FROM p_event_document THEN
        RAISE EXCEPTION 'latest federated recovery event differs from its snapshot'
            USING ERRCODE = '22023';
    END IF;

    PERFORM set_config(
        'gda.cross_store_projection_federated_recovery_write_allowed', '1', true
    );
    INSERT INTO gda_control.cross_store_projection_federated_recovery_event_history (
        tenant_id, run_id, event_sequence, event_sha256, event_document
    ) VALUES (
        p_tenant_id, p_run_id, v_event_count, p_event_sha256, p_event_document
    );
    INSERT INTO gda_control.cross_store_projection_federated_recovery_snapshot_history (
        tenant_id, run_id, snapshot_version, plan_sha256s, snapshot_sha256,
        snapshot_document
    ) VALUES (
        p_tenant_id, p_run_id, v_snapshot_version, p_plan_sha256s,
        p_snapshot_sha256, p_snapshot_document
    )
    RETURNING * INTO v_existing;
    PERFORM set_config(
        'gda.cross_store_projection_federated_recovery_write_allowed', '0', true
    );

    RETURN QUERY SELECT v_existing.snapshot_document, TRUE;
EXCEPTION WHEN OTHERS THEN
    PERFORM set_config(
        'gda.cross_store_projection_federated_recovery_write_allowed', '0', true
    );
    RAISE;
END;
$$;

DROP TRIGGER IF EXISTS trg_gda_federated_projection_recovery_event_insert_guard
    ON gda_control.cross_store_projection_federated_recovery_event_history;
CREATE TRIGGER trg_gda_federated_projection_recovery_event_insert_guard
BEFORE INSERT ON gda_control.cross_store_projection_federated_recovery_event_history
FOR EACH ROW EXECUTE FUNCTION gda_control.guard_cross_store_projection_federated_recovery_insert();

DROP TRIGGER IF EXISTS trg_gda_federated_projection_recovery_snapshot_insert_guard
    ON gda_control.cross_store_projection_federated_recovery_snapshot_history;
CREATE TRIGGER trg_gda_federated_projection_recovery_snapshot_insert_guard
BEFORE INSERT ON gda_control.cross_store_projection_federated_recovery_snapshot_history
FOR EACH ROW EXECUTE FUNCTION gda_control.guard_cross_store_projection_federated_recovery_insert();

DROP TRIGGER IF EXISTS trg_gda_federated_projection_recovery_event_immutable
    ON gda_control.cross_store_projection_federated_recovery_event_history;
CREATE TRIGGER trg_gda_federated_projection_recovery_event_immutable
BEFORE UPDATE OR DELETE
ON gda_control.cross_store_projection_federated_recovery_event_history
FOR EACH ROW EXECUTE FUNCTION gda_control.reject_immutable_mutation();

DROP TRIGGER IF EXISTS trg_gda_federated_projection_recovery_snapshot_immutable
    ON gda_control.cross_store_projection_federated_recovery_snapshot_history;
CREATE TRIGGER trg_gda_federated_projection_recovery_snapshot_immutable
BEFORE UPDATE OR DELETE
ON gda_control.cross_store_projection_federated_recovery_snapshot_history
FOR EACH ROW EXECUTE FUNCTION gda_control.reject_immutable_mutation();

ALTER TABLE gda_control.cross_store_projection_federated_recovery_event_history
    ENABLE ROW LEVEL SECURITY;
ALTER TABLE gda_control.cross_store_projection_federated_recovery_event_history
    FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation
    ON gda_control.cross_store_projection_federated_recovery_event_history;
CREATE POLICY tenant_isolation
    ON gda_control.cross_store_projection_federated_recovery_event_history
    USING (tenant_id = gda_control.current_tenant())
    WITH CHECK (tenant_id = gda_control.current_tenant());

ALTER TABLE gda_control.cross_store_projection_federated_recovery_snapshot_history
    ENABLE ROW LEVEL SECURITY;
ALTER TABLE gda_control.cross_store_projection_federated_recovery_snapshot_history
    FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation
    ON gda_control.cross_store_projection_federated_recovery_snapshot_history;
CREATE POLICY tenant_isolation
    ON gda_control.cross_store_projection_federated_recovery_snapshot_history
    USING (tenant_id = gda_control.current_tenant())
    WITH CHECK (tenant_id = gda_control.current_tenant());

REVOKE ALL ON TABLE
    gda_control.cross_store_projection_federated_recovery_event_history
    FROM PUBLIC, gda_control_gateway;
REVOKE ALL ON TABLE
    gda_control.cross_store_projection_federated_recovery_snapshot_history
    FROM PUBLIC, gda_control_gateway;
REVOKE ALL ON TABLE
    gda_control.cross_store_projection_federated_recovery_snapshot_current
    FROM PUBLIC, gda_control_gateway;
GRANT SELECT ON TABLE
    gda_control.cross_store_projection_federated_recovery_event_history
    TO gda_control_gateway;
GRANT SELECT ON TABLE
    gda_control.cross_store_projection_federated_recovery_snapshot_history
    TO gda_control_gateway;
GRANT SELECT ON TABLE
    gda_control.cross_store_projection_federated_recovery_snapshot_current
    TO gda_control_gateway;

REVOKE ALL ON FUNCTION
    gda_control.guard_cross_store_projection_federated_recovery_insert()
    FROM PUBLIC;
REVOKE ALL ON FUNCTION
    gda_control.record_cross_store_projection_federated_recovery_snapshot(
        TEXT, TEXT, JSONB, JSONB, TEXT, JSONB, TEXT
    ) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION
    gda_control.record_cross_store_projection_federated_recovery_snapshot(
        TEXT, TEXT, JSONB, JSONB, TEXT, JSONB, TEXT
    ) TO gda_control_gateway;
