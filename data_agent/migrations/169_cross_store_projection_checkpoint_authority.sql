-- 169: Append-only cross-store projection checkpoint authority.

CREATE TABLE IF NOT EXISTS gda_control.cross_store_projection_checkpoint_history (
    tenant_id TEXT NOT NULL,
    projection_id TEXT NOT NULL,
    target_engine TEXT NOT NULL,
    target_ref TEXT NOT NULL,
    checkpoint_version INTEGER NOT NULL,
    source_resource_version_ref TEXT NOT NULL,
    source_content_sha256 CHAR(64) NOT NULL,
    target_exists BOOLEAN NOT NULL,
    target_content_sha256 CHAR(64),
    target_row_count BIGINT NOT NULL,
    target_commit_ref JSONB NOT NULL,
    repair_plan_sha256 CHAR(64) NOT NULL,
    plan_idempotency_key CHAR(64) NOT NULL,
    previous_checkpoint_sha256 CHAR(64),
    updated_by TEXT NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    checkpoint_sha256 CHAR(64) NOT NULL,
    PRIMARY KEY (
        tenant_id, projection_id, target_engine, target_ref, checkpoint_version
    ),
    CONSTRAINT uq_gda_cross_store_projection_checkpoint_sha
        UNIQUE (tenant_id, checkpoint_sha256),
    CONSTRAINT uq_gda_cross_store_projection_checkpoint_plan
        UNIQUE (tenant_id, plan_idempotency_key),
    CONSTRAINT ck_gda_cross_store_projection_checkpoint_tenant
        CHECK (tenant_id ~ '^[a-z0-9][a-z0-9._-]{0,63}$'),
    CONSTRAINT ck_gda_cross_store_projection_checkpoint_projection CHECK (
        projection_id ~ '^[A-Za-z0-9][A-Za-z0-9._:-]{2,127}$'
    ),
    CONSTRAINT ck_gda_cross_store_projection_checkpoint_engine CHECK (
        target_engine IN ('postgis', 'rdf', 'vector', 'object_store', 'lakehouse')
    ),
    CONSTRAINT ck_gda_cross_store_projection_checkpoint_refs CHECK (
        NULLIF(btrim(target_ref), '') IS NOT NULL
        AND octet_length(target_ref) <= 512
        AND NULLIF(btrim(source_resource_version_ref), '') IS NOT NULL
        AND octet_length(source_resource_version_ref) <= 512
    ),
    CONSTRAINT ck_gda_cross_store_projection_checkpoint_version
        CHECK (checkpoint_version >= 1),
    CONSTRAINT ck_gda_cross_store_projection_checkpoint_source_sha
        CHECK (source_content_sha256 ~ '^[0-9a-f]{64}$'),
    CONSTRAINT ck_gda_cross_store_projection_checkpoint_target_state CHECK (
        target_row_count >= 0
        AND (
            target_exists
            AND target_content_sha256 IS NOT NULL
            AND target_content_sha256 ~ '^[0-9a-f]{64}$'
            OR NOT target_exists
            AND target_content_sha256 IS NULL
            AND target_row_count = 0
        )
    ),
    CONSTRAINT ck_gda_cross_store_projection_checkpoint_commit CHECK (
        jsonb_typeof(target_commit_ref) = 'object'
        AND target_commit_ref <> '{}'::jsonb
        AND target_commit_ref ? 'plan_sha256'
        AND target_commit_ref ? 'idempotency_key'
        AND target_commit_ref ->> 'plan_sha256' = repair_plan_sha256
        AND target_commit_ref ->> 'idempotency_key' = plan_idempotency_key
    ),
    CONSTRAINT ck_gda_cross_store_projection_checkpoint_repair_sha CHECK (
        repair_plan_sha256 ~ '^[0-9a-f]{64}$'
        AND plan_idempotency_key ~ '^[0-9a-f]{64}$'
    ),
    CONSTRAINT ck_gda_cross_store_projection_checkpoint_predecessor CHECK (
        (
            checkpoint_version = 1
            AND previous_checkpoint_sha256 IS NULL
        ) OR (
            checkpoint_version > 1
            AND previous_checkpoint_sha256 IS NOT NULL
            AND previous_checkpoint_sha256 ~ '^[0-9a-f]{64}$'
            AND previous_checkpoint_sha256 <> checkpoint_sha256
        )
    ),
    CONSTRAINT ck_gda_cross_store_projection_checkpoint_actor CHECK (
        updated_by ~ '^(human|workload|agent):[^[:space:]]{1,128}$'
    ),
    CONSTRAINT ck_gda_cross_store_projection_checkpoint_sha CHECK (
        checkpoint_sha256 ~ '^[0-9a-f]{64}$'
    )
);

CREATE INDEX IF NOT EXISTS idx_gda_cross_store_projection_checkpoint_current
    ON gda_control.cross_store_projection_checkpoint_history (
        tenant_id, projection_id, target_engine, target_ref,
        checkpoint_version DESC
    );

CREATE OR REPLACE VIEW gda_control.cross_store_projection_checkpoint_current
WITH (security_invoker = true)
AS
SELECT DISTINCT ON (tenant_id, projection_id, target_engine, target_ref)
       tenant_id, projection_id, target_engine, target_ref,
       checkpoint_version, source_resource_version_ref,
       source_content_sha256, target_exists, target_content_sha256,
       target_row_count, target_commit_ref, repair_plan_sha256,
       plan_idempotency_key, previous_checkpoint_sha256,
       updated_by, updated_at, checkpoint_sha256
FROM gda_control.cross_store_projection_checkpoint_history
ORDER BY tenant_id, projection_id, target_engine, target_ref,
         checkpoint_version DESC;

CREATE OR REPLACE FUNCTION gda_control.guard_cross_store_projection_checkpoint_insert()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    IF COALESCE(
        current_setting('gda.cross_store_projection_checkpoint_write_allowed', true),
        ''
    ) <> '1' THEN
        RAISE EXCEPTION 'use gda_control.record_cross_store_projection_checkpoint()'
            USING ERRCODE = '55000';
    END IF;
    IF gda_control.current_tenant() IS NULL
       OR NEW.tenant_id IS DISTINCT FROM gda_control.current_tenant() THEN
        RAISE EXCEPTION 'projection checkpoint tenant context is missing or mismatched'
            USING ERRCODE = '42501';
    END IF;
    RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION gda_control.record_cross_store_projection_checkpoint(
    p_tenant_id TEXT,
    p_projection_id TEXT,
    p_target_engine TEXT,
    p_target_ref TEXT,
    p_checkpoint_version INTEGER,
    p_source_resource_version_ref TEXT,
    p_source_content_sha256 TEXT,
    p_target_exists BOOLEAN,
    p_target_content_sha256 TEXT,
    p_target_row_count BIGINT,
    p_target_commit_ref JSONB,
    p_repair_plan_sha256 TEXT,
    p_plan_idempotency_key TEXT,
    p_previous_checkpoint_sha256 TEXT,
    p_updated_by TEXT,
    p_updated_at TIMESTAMPTZ,
    p_checkpoint_sha256 TEXT
)
RETURNS TABLE(checkpoint_document JSONB, created BOOLEAN)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, gda_control
SET row_security = on
AS $$
DECLARE
    v_current gda_control.cross_store_projection_checkpoint_history%ROWTYPE;
    v_existing gda_control.cross_store_projection_checkpoint_history%ROWTYPE;
BEGIN
    IF gda_control.current_tenant() IS NULL
       OR p_tenant_id IS DISTINCT FROM gda_control.current_tenant() THEN
        RAISE EXCEPTION 'projection checkpoint tenant context is missing or mismatched'
            USING ERRCODE = '42501';
    END IF;
    IF p_projection_id !~ '^[A-Za-z0-9][A-Za-z0-9._:-]{2,127}$'
       OR p_target_engine NOT IN (
            'postgis', 'rdf', 'vector', 'object_store', 'lakehouse'
       )
       OR NULLIF(btrim(p_target_ref), '') IS NULL
       OR octet_length(p_target_ref) > 512
       OR p_checkpoint_version IS NULL
       OR p_checkpoint_version < 1
       OR NULLIF(btrim(p_source_resource_version_ref), '') IS NULL
       OR octet_length(p_source_resource_version_ref) > 512
       OR p_source_content_sha256 IS NULL
       OR p_source_content_sha256 !~ '^[0-9a-f]{64}$'
       OR p_target_exists IS NULL
       OR p_target_row_count IS NULL
       OR p_target_row_count < 0
       OR (
            p_target_exists
            AND (
                p_target_content_sha256 IS NULL
                OR p_target_content_sha256 !~ '^[0-9a-f]{64}$'
            )
       )
       OR (
            NOT p_target_exists
            AND (
                p_target_content_sha256 IS NOT NULL
                OR p_target_row_count <> 0
            )
       )
       OR p_target_commit_ref IS NULL
       OR jsonb_typeof(p_target_commit_ref) <> 'object'
       OR p_target_commit_ref = '{}'::jsonb
       OR p_repair_plan_sha256 IS NULL
       OR p_repair_plan_sha256 !~ '^[0-9a-f]{64}$'
       OR p_plan_idempotency_key IS NULL
       OR p_plan_idempotency_key !~ '^[0-9a-f]{64}$'
       OR p_target_commit_ref ->> 'plan_sha256'
            IS DISTINCT FROM p_repair_plan_sha256
       OR p_target_commit_ref ->> 'idempotency_key'
            IS DISTINCT FROM p_plan_idempotency_key
       OR p_updated_by IS NULL
       OR p_updated_by !~ '^(human|workload|agent):[^[:space:]]{1,128}$'
       OR p_updated_at IS NULL
       OR p_checkpoint_sha256 IS NULL
       OR p_checkpoint_sha256 !~ '^[0-9a-f]{64}$'
       OR (
            p_checkpoint_version = 1
            AND p_previous_checkpoint_sha256 IS NOT NULL
       )
       OR (
            p_checkpoint_version > 1
            AND (
                p_previous_checkpoint_sha256 IS NULL
                OR p_previous_checkpoint_sha256 !~ '^[0-9a-f]{64}$'
            )
       ) THEN
        RAISE EXCEPTION 'projection checkpoint identity or evidence is invalid'
            USING ERRCODE = '22023';
    END IF;

    -- One lock order for every caller prevents both target and plan races.
    PERFORM pg_advisory_xact_lock(
        hashtextextended(
            'projection-checkpoint-target|' || p_tenant_id || '|' ||
            p_projection_id || '|' || p_target_engine || '|' || p_target_ref,
            0
        )
    );
    PERFORM pg_advisory_xact_lock(
        hashtextextended(
            'projection-checkpoint-plan|' || p_tenant_id || '|' ||
            p_plan_idempotency_key,
            0
        )
    );

    SELECT history.* INTO v_existing
    FROM gda_control.cross_store_projection_checkpoint_history AS history
    WHERE history.tenant_id = p_tenant_id
      AND (
          history.checkpoint_sha256 = p_checkpoint_sha256
          OR history.plan_idempotency_key = p_plan_idempotency_key
      )
    ORDER BY (
        history.checkpoint_sha256 = p_checkpoint_sha256
        AND history.plan_idempotency_key = p_plan_idempotency_key
    ) DESC
    LIMIT 1;
    IF FOUND THEN
        IF v_existing.projection_id IS DISTINCT FROM p_projection_id
           OR v_existing.target_engine IS DISTINCT FROM p_target_engine
           OR v_existing.target_ref IS DISTINCT FROM p_target_ref
           OR v_existing.checkpoint_version IS DISTINCT FROM p_checkpoint_version
           OR v_existing.source_resource_version_ref
                IS DISTINCT FROM p_source_resource_version_ref
           OR v_existing.source_content_sha256
                IS DISTINCT FROM p_source_content_sha256
           OR v_existing.target_exists IS DISTINCT FROM p_target_exists
           OR v_existing.target_content_sha256
                IS DISTINCT FROM p_target_content_sha256
           OR v_existing.target_row_count IS DISTINCT FROM p_target_row_count
           OR v_existing.target_commit_ref IS DISTINCT FROM p_target_commit_ref
           OR v_existing.repair_plan_sha256
                IS DISTINCT FROM p_repair_plan_sha256
           OR v_existing.plan_idempotency_key
                IS DISTINCT FROM p_plan_idempotency_key
           OR v_existing.previous_checkpoint_sha256
                IS DISTINCT FROM p_previous_checkpoint_sha256
           OR v_existing.updated_by IS DISTINCT FROM p_updated_by
           OR v_existing.updated_at IS DISTINCT FROM p_updated_at
           OR v_existing.checkpoint_sha256
                IS DISTINCT FROM p_checkpoint_sha256 THEN
            RAISE EXCEPTION 'projection checkpoint idempotency evidence differs'
                USING ERRCODE = '40001';
        END IF;
        RETURN QUERY SELECT to_jsonb(v_existing), FALSE;
        RETURN;
    END IF;

    SELECT history.* INTO v_current
    FROM gda_control.cross_store_projection_checkpoint_history AS history
    WHERE history.tenant_id = p_tenant_id
      AND history.projection_id = p_projection_id
      AND history.target_engine = p_target_engine
      AND history.target_ref = p_target_ref
    ORDER BY history.checkpoint_version DESC
    LIMIT 1
    FOR UPDATE;

    IF NOT FOUND THEN
        IF p_checkpoint_version <> 1
           OR p_previous_checkpoint_sha256 IS NOT NULL THEN
            RAISE EXCEPTION 'initial projection checkpoint must start at version 1'
                USING ERRCODE = '40001';
        END IF;
    ELSIF p_previous_checkpoint_sha256
            IS DISTINCT FROM v_current.checkpoint_sha256
       OR p_checkpoint_version <> v_current.checkpoint_version + 1
       OR p_updated_at < v_current.updated_at THEN
        RAISE EXCEPTION 'projection checkpoint predecessor or version conflict'
            USING ERRCODE = '40001';
    END IF;

    PERFORM set_config(
        'gda.cross_store_projection_checkpoint_write_allowed', '1', true
    );
    INSERT INTO gda_control.cross_store_projection_checkpoint_history (
        tenant_id, projection_id, target_engine, target_ref,
        checkpoint_version, source_resource_version_ref,
        source_content_sha256, target_exists, target_content_sha256,
        target_row_count, target_commit_ref, repair_plan_sha256,
        plan_idempotency_key, previous_checkpoint_sha256,
        updated_by, updated_at, checkpoint_sha256
    ) VALUES (
        p_tenant_id, p_projection_id, p_target_engine, p_target_ref,
        p_checkpoint_version, p_source_resource_version_ref,
        p_source_content_sha256, p_target_exists, p_target_content_sha256,
        p_target_row_count, p_target_commit_ref, p_repair_plan_sha256,
        p_plan_idempotency_key, p_previous_checkpoint_sha256,
        p_updated_by, p_updated_at, p_checkpoint_sha256
    )
    RETURNING * INTO v_existing;
    PERFORM set_config(
        'gda.cross_store_projection_checkpoint_write_allowed', '0', true
    );

    RETURN QUERY SELECT to_jsonb(v_existing), TRUE;
EXCEPTION WHEN OTHERS THEN
    PERFORM set_config(
        'gda.cross_store_projection_checkpoint_write_allowed', '0', true
    );
    RAISE;
END;
$$;

DROP TRIGGER IF EXISTS trg_gda_cross_store_projection_checkpoint_insert_guard
    ON gda_control.cross_store_projection_checkpoint_history;
CREATE TRIGGER trg_gda_cross_store_projection_checkpoint_insert_guard
BEFORE INSERT ON gda_control.cross_store_projection_checkpoint_history
FOR EACH ROW
EXECUTE FUNCTION gda_control.guard_cross_store_projection_checkpoint_insert();

DROP TRIGGER IF EXISTS trg_gda_cross_store_projection_checkpoint_immutable
    ON gda_control.cross_store_projection_checkpoint_history;
CREATE TRIGGER trg_gda_cross_store_projection_checkpoint_immutable
BEFORE UPDATE OR DELETE ON gda_control.cross_store_projection_checkpoint_history
FOR EACH ROW EXECUTE FUNCTION gda_control.reject_immutable_mutation();

ALTER TABLE gda_control.cross_store_projection_checkpoint_history
    ENABLE ROW LEVEL SECURITY;
ALTER TABLE gda_control.cross_store_projection_checkpoint_history
    FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation
    ON gda_control.cross_store_projection_checkpoint_history;
CREATE POLICY tenant_isolation
    ON gda_control.cross_store_projection_checkpoint_history
    USING (tenant_id = gda_control.current_tenant())
    WITH CHECK (tenant_id = gda_control.current_tenant());

REVOKE ALL ON TABLE gda_control.cross_store_projection_checkpoint_history
    FROM PUBLIC, gda_control_gateway;
REVOKE ALL ON TABLE gda_control.cross_store_projection_checkpoint_current
    FROM PUBLIC, gda_control_gateway;
GRANT SELECT ON TABLE gda_control.cross_store_projection_checkpoint_history
    TO gda_control_gateway;
GRANT SELECT ON TABLE gda_control.cross_store_projection_checkpoint_current
    TO gda_control_gateway;

REVOKE ALL ON FUNCTION gda_control.guard_cross_store_projection_checkpoint_insert()
    FROM PUBLIC;
REVOKE ALL ON FUNCTION gda_control.record_cross_store_projection_checkpoint(
    TEXT, TEXT, TEXT, TEXT, INTEGER, TEXT, TEXT, BOOLEAN, TEXT, BIGINT,
    JSONB, TEXT, TEXT, TEXT, TEXT, TIMESTAMPTZ, TEXT
) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION gda_control.record_cross_store_projection_checkpoint(
    TEXT, TEXT, TEXT, TEXT, INTEGER, TEXT, TEXT, BOOLEAN, TEXT, BIGINT,
    JSONB, TEXT, TEXT, TEXT, TEXT, TIMESTAMPTZ, TEXT
) TO gda_control_gateway;
