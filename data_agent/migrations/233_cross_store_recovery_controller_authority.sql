-- 233: Durable append-only state for the cross-store recovery controller.
--
-- A controller snapshot covers one or more tenants.  PostgreSQL stores the
-- identical snapshot once per covered tenant so normal tenant RLS remains the
-- read boundary.  The repository writes all copies in one local transaction;
-- this is durable controller state, not a distributed provider transaction.

CREATE TABLE IF NOT EXISTS gda_control.cross_store_recovery_controller_history (
    tenant_id TEXT NOT NULL,
    run_id TEXT NOT NULL,
    snapshot_version INTEGER NOT NULL,
    snapshot_sha256 CHAR(64) NOT NULL,
    snapshot_document JSONB NOT NULL,
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (tenant_id, run_id, snapshot_version),
    CONSTRAINT uq_gda_cross_store_controller_snapshot
        UNIQUE (tenant_id, run_id, snapshot_sha256),
    CONSTRAINT ck_gda_cross_store_controller_tenant
        CHECK (tenant_id ~ '^[a-z0-9][a-z0-9._-]{0,63}$'),
    CONSTRAINT ck_gda_cross_store_controller_run
        CHECK (run_id ~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$'),
    CONSTRAINT ck_gda_cross_store_controller_version
        CHECK (snapshot_version >= 1),
    CONSTRAINT ck_gda_cross_store_controller_sha
        CHECK (snapshot_sha256 ~ '^[0-9a-f]{64}$'),
    CONSTRAINT ck_gda_cross_store_controller_document
        CHECK (
            jsonb_typeof(snapshot_document) = 'object'
            AND snapshot_document ->> 'run_id' = run_id
            AND snapshot_document ->> 'snapshot_sha256' = snapshot_sha256
            AND jsonb_typeof(snapshot_document -> 'tenant_ids') = 'array'
            AND (
                jsonb_array_length(snapshot_document -> 'tenant_ids') > 0
                OR (
                    jsonb_array_length(snapshot_document -> 'tenant_ids') = 0
                    AND snapshot_document ->> 'state' = 'planned'
                    AND snapshot_document ->> 'next_action' = 'await_admission'
                    AND snapshot_document ->> 'binding_sha256' IS NULL
                )
                OR (
                    jsonb_array_length(snapshot_document -> 'tenant_ids') = 0
                    AND snapshot_document ->> 'state' = 'failed_closed'
                    AND snapshot_document ->> 'next_action' = 'await_operator'
                    AND snapshot_document ->> 'binding_sha256' IS NULL
                )
            )
            AND jsonb_typeof(snapshot_document -> 'events') = 'array'
            AND jsonb_array_length(snapshot_document -> 'events') = snapshot_version
            AND (
                snapshot_document ->> 'binding_sha256' IS NULL
                OR snapshot_document ->> 'binding_sha256' ~ '^[0-9a-f]{64}$'
            )
        )
);

CREATE INDEX IF NOT EXISTS idx_gda_cross_store_controller_current
    ON gda_control.cross_store_recovery_controller_history
        (tenant_id, run_id, snapshot_version DESC);

CREATE OR REPLACE VIEW gda_control.cross_store_recovery_controller_current
WITH (security_invoker = true)
AS
SELECT DISTINCT ON (tenant_id, run_id)
       tenant_id, run_id, snapshot_version, snapshot_sha256,
       snapshot_document, recorded_at
FROM gda_control.cross_store_recovery_controller_history
ORDER BY tenant_id, run_id, snapshot_version DESC;

CREATE OR REPLACE FUNCTION gda_control.guard_cross_store_recovery_controller_insert()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    IF COALESCE(
        current_setting('gda.cross_store_recovery_controller_write_allowed', true),
        ''
    ) <> '1' THEN
        RAISE EXCEPTION 'use gda_control.record_cross_store_recovery_controller_snapshot()'
            USING ERRCODE = '55000';
    END IF;
    IF gda_control.current_tenant() IS NULL
       OR NEW.tenant_id IS DISTINCT FROM gda_control.current_tenant() THEN
        RAISE EXCEPTION 'cross-store recovery controller tenant context is missing or mismatched'
            USING ERRCODE = '42501';
    END IF;
    IF jsonb_array_length(NEW.snapshot_document -> 'tenant_ids') > 0
       AND NOT EXISTS (
        SELECT 1
        FROM jsonb_array_elements_text(NEW.snapshot_document -> 'tenant_ids') AS ids(value)
        WHERE ids.value = NEW.tenant_id
    ) THEN
        RAISE EXCEPTION 'cross-store recovery controller snapshot does not cover authority tenant'
            USING ERRCODE = '42501';
    END IF;
    RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION gda_control.record_cross_store_recovery_controller_snapshot(
    p_tenant_id TEXT,
    p_run_id TEXT,
    p_snapshot_document JSONB,
    p_snapshot_sha256 TEXT
)
RETURNS TABLE(snapshot_document JSONB, created BOOLEAN)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, gda_control
SET row_security = on
AS $$
DECLARE
    v_existing gda_control.cross_store_recovery_controller_history%ROWTYPE;
    v_current gda_control.cross_store_recovery_controller_history%ROWTYPE;
    v_new_event_count INTEGER;
    v_old_event_count INTEGER;
    v_index INTEGER;
    v_tenant_count INTEGER;
    v_distinct_tenant_count INTEGER;
BEGIN
    IF gda_control.current_tenant() IS NULL
       OR p_tenant_id IS DISTINCT FROM gda_control.current_tenant() THEN
        RAISE EXCEPTION 'cross-store recovery controller tenant context is missing or mismatched'
            USING ERRCODE = '42501';
    END IF;
    IF p_tenant_id IS NULL OR p_tenant_id !~ '^[a-z0-9][a-z0-9._-]{0,63}$'
       OR p_run_id IS NULL OR p_run_id !~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$'
       OR p_snapshot_sha256 IS NULL OR p_snapshot_sha256 !~ '^[0-9a-f]{64}$'
       OR p_snapshot_document IS NULL
       OR jsonb_typeof(p_snapshot_document) <> 'object'
       OR p_snapshot_document ->> 'run_id' IS DISTINCT FROM p_run_id
       OR p_snapshot_document ->> 'snapshot_sha256' IS DISTINCT FROM p_snapshot_sha256
       OR jsonb_typeof(p_snapshot_document -> 'tenant_ids') <> 'array'
       OR (
           jsonb_array_length(p_snapshot_document -> 'tenant_ids') < 1
           AND NOT (
               (
                   jsonb_array_length(p_snapshot_document -> 'tenant_ids') = 0
                   AND p_snapshot_document ->> 'state' = 'planned'
                   AND p_snapshot_document ->> 'next_action' = 'await_admission'
                   AND p_snapshot_document ->> 'binding_sha256' IS NULL
               )
               OR (
                   jsonb_array_length(p_snapshot_document -> 'tenant_ids') = 0
                   AND p_snapshot_document ->> 'state' = 'failed_closed'
                   AND p_snapshot_document ->> 'next_action' = 'await_operator'
                   AND p_snapshot_document ->> 'binding_sha256' IS NULL
               )
           )
       )
       OR jsonb_typeof(p_snapshot_document -> 'events') <> 'array'
       OR jsonb_array_length(p_snapshot_document -> 'events') < 1
       OR EXISTS (
           SELECT 1
           FROM jsonb_array_elements_text(p_snapshot_document -> 'tenant_ids') AS ids(value)
           WHERE ids.value !~ '^[a-z0-9][a-z0-9._-]{0,63}$'
       ) THEN
        RAISE EXCEPTION 'cross-store recovery controller identity or evidence is invalid'
            USING ERRCODE = '22023';
    END IF;

    SELECT count(*), count(DISTINCT value)
    INTO v_tenant_count, v_distinct_tenant_count
    FROM jsonb_array_elements_text(p_snapshot_document -> 'tenant_ids') AS ids(value);
    IF v_tenant_count <> v_distinct_tenant_count
       OR (
           jsonb_array_length(p_snapshot_document -> 'tenant_ids') > 0
           AND NOT EXISTS (
           SELECT 1
           FROM jsonb_array_elements_text(p_snapshot_document -> 'tenant_ids') AS ids(value)
           WHERE ids.value = p_tenant_id
           )
       )
       OR (p_snapshot_document -> 'tenant_ids') IS DISTINCT FROM COALESCE(
           (
               SELECT jsonb_agg(ids.value ORDER BY ids.value)
               FROM jsonb_array_elements_text(p_snapshot_document -> 'tenant_ids') AS ids(value)
           ),
           '[]'::jsonb
       ) THEN
        RAISE EXCEPTION 'cross-store recovery controller tenant set is invalid'
            USING ERRCODE = '22023';
    END IF;

    PERFORM pg_advisory_xact_lock(
        hashtextextended('cross-store-recovery-controller|' || p_tenant_id || '|' || p_run_id, 0)
    );

    SELECT history.* INTO v_existing
    FROM gda_control.cross_store_recovery_controller_history AS history
    WHERE history.tenant_id = p_tenant_id
      AND history.run_id = p_run_id
      AND history.snapshot_sha256 = p_snapshot_sha256;
    IF FOUND THEN
        IF v_existing.snapshot_document IS DISTINCT FROM p_snapshot_document THEN
            RAISE EXCEPTION 'cross-store recovery controller idempotency evidence differs'
                USING ERRCODE = '40001';
        END IF;
        RETURN QUERY SELECT v_existing.snapshot_document, FALSE;
        RETURN;
    END IF;

    SELECT history.* INTO v_current
    FROM gda_control.cross_store_recovery_controller_history AS history
    WHERE history.tenant_id = p_tenant_id
      AND history.run_id = p_run_id
    ORDER BY history.snapshot_version DESC
    LIMIT 1
    FOR UPDATE;

    v_new_event_count := jsonb_array_length(p_snapshot_document -> 'events');
    IF NOT FOUND THEN
        IF v_new_event_count <> 1 THEN
            RAISE EXCEPTION 'initial controller snapshot must contain one event'
                USING ERRCODE = '40001';
        END IF;
    ELSE
        v_old_event_count := jsonb_array_length(v_current.snapshot_document -> 'events');
        IF v_new_event_count <> v_old_event_count + 1 THEN
            RAISE EXCEPTION 'controller event chain skipped a predecessor'
                USING ERRCODE = '40001';
        END IF;
        FOR v_index IN 0..v_old_event_count - 1 LOOP
            IF (p_snapshot_document -> 'events' -> v_index)
                IS DISTINCT FROM (v_current.snapshot_document -> 'events' -> v_index) THEN
                RAISE EXCEPTION 'controller event chain is not append-only'
                    USING ERRCODE = '40001';
            END IF;
        END LOOP;
    END IF;

    PERFORM set_config(
        'gda.cross_store_recovery_controller_write_allowed', '1', true
    );
    INSERT INTO gda_control.cross_store_recovery_controller_history (
        tenant_id, run_id, snapshot_version, snapshot_sha256, snapshot_document
    ) VALUES (
        p_tenant_id, p_run_id, v_new_event_count,
        p_snapshot_sha256, p_snapshot_document
    )
    RETURNING * INTO v_existing;
    PERFORM set_config(
        'gda.cross_store_recovery_controller_write_allowed', '0', true
    );
    RETURN QUERY SELECT v_existing.snapshot_document, TRUE;
EXCEPTION WHEN OTHERS THEN
    PERFORM set_config(
        'gda.cross_store_recovery_controller_write_allowed', '0', true
    );
    RAISE;
END;
$$;

DROP TRIGGER IF EXISTS trg_gda_cross_store_recovery_controller_insert_guard
    ON gda_control.cross_store_recovery_controller_history;
CREATE TRIGGER trg_gda_cross_store_recovery_controller_insert_guard
BEFORE INSERT ON gda_control.cross_store_recovery_controller_history
FOR EACH ROW EXECUTE FUNCTION gda_control.guard_cross_store_recovery_controller_insert();

DROP TRIGGER IF EXISTS trg_gda_cross_store_recovery_controller_immutable
    ON gda_control.cross_store_recovery_controller_history;
CREATE TRIGGER trg_gda_cross_store_recovery_controller_immutable
BEFORE UPDATE OR DELETE ON gda_control.cross_store_recovery_controller_history
FOR EACH ROW EXECUTE FUNCTION gda_control.reject_immutable_mutation();

ALTER TABLE gda_control.cross_store_recovery_controller_history
    ENABLE ROW LEVEL SECURITY;
ALTER TABLE gda_control.cross_store_recovery_controller_history
    FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation
    ON gda_control.cross_store_recovery_controller_history;
CREATE POLICY tenant_isolation
    ON gda_control.cross_store_recovery_controller_history
    USING (tenant_id = gda_control.current_tenant())
    WITH CHECK (tenant_id = gda_control.current_tenant());

REVOKE ALL ON TABLE gda_control.cross_store_recovery_controller_history
    FROM PUBLIC, gda_control_gateway;
REVOKE ALL ON TABLE gda_control.cross_store_recovery_controller_current
    FROM PUBLIC, gda_control_gateway;
GRANT SELECT ON TABLE gda_control.cross_store_recovery_controller_history
    TO gda_control_gateway;
GRANT SELECT ON TABLE gda_control.cross_store_recovery_controller_current
    TO gda_control_gateway;

REVOKE ALL ON FUNCTION gda_control.guard_cross_store_recovery_controller_insert()
    FROM PUBLIC;
REVOKE ALL ON FUNCTION gda_control.record_cross_store_recovery_controller_snapshot(TEXT, TEXT, JSONB, TEXT)
    FROM PUBLIC;
GRANT EXECUTE ON FUNCTION gda_control.record_cross_store_recovery_controller_snapshot(TEXT, TEXT, JSONB, TEXT)
    TO gda_control_gateway;
