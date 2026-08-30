-- 232: Durable identity authority for a control-ledger/object-store recovery pair.
--
-- A binding can cover several tenants.  The authority stores one identical row
-- per covered tenant so normal tenant RLS remains enforceable.  The rows are
-- evidence copies, not an attempt to make PostgreSQL and an object provider a
-- distributed transaction.

CREATE TABLE IF NOT EXISTS gda_control.cross_store_recovery_binding_history (
    tenant_id TEXT NOT NULL,
    binding_sha256 CHAR(64) NOT NULL,
    source_resource_version_ref TEXT NOT NULL,
    binding_document JSONB NOT NULL,
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (tenant_id, binding_sha256),
    CONSTRAINT uq_gda_cross_store_binding_source
        UNIQUE (tenant_id, source_resource_version_ref),
    CONSTRAINT ck_gda_cross_store_binding_tenant
        CHECK (tenant_id ~ '^[a-z0-9][a-z0-9._-]{0,63}$'),
    CONSTRAINT ck_gda_cross_store_binding_sha
        CHECK (binding_sha256 ~ '^[0-9a-f]{64}$'),
    CONSTRAINT ck_gda_cross_store_binding_source
        CHECK (
            NULLIF(btrim(source_resource_version_ref), '') IS NOT NULL
            AND octet_length(source_resource_version_ref) <= 512
        ),
    CONSTRAINT ck_gda_cross_store_binding_document
        CHECK (
            jsonb_typeof(binding_document) = 'object'
            AND binding_document ->> 'schema' = 'gda.cross_store_recovery_binding.v1'
            AND binding_document ->> 'binding_sha256' = binding_sha256
            AND binding_document ->> 'source_resource_version_ref'
                = source_resource_version_ref
            AND jsonb_typeof(binding_document -> 'tenant_ids') = 'array'
            AND jsonb_array_length(binding_document -> 'tenant_ids') > 0
            AND binding_document ->> 'source_content_sha256' ~ '^[0-9a-f]{64}$'
            AND binding_document ->> 'control_manifest_sha256' ~ '^[0-9a-f]{64}$'
            AND binding_document ->> 'object_manifest_sha256' ~ '^[0-9a-f]{64}$'
        )
);

CREATE INDEX IF NOT EXISTS idx_gda_cross_store_binding_source
    ON gda_control.cross_store_recovery_binding_history
        (tenant_id, source_resource_version_ref, recorded_at DESC);

CREATE OR REPLACE VIEW gda_control.cross_store_recovery_binding_current
WITH (security_invoker = true)
AS
SELECT tenant_id, binding_sha256, source_resource_version_ref,
       binding_document, recorded_at
FROM gda_control.cross_store_recovery_binding_history;

CREATE OR REPLACE FUNCTION gda_control.guard_cross_store_recovery_binding_insert()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    IF COALESCE(
        current_setting('gda.cross_store_recovery_binding_write_allowed', true),
        ''
    ) <> '1' THEN
        RAISE EXCEPTION 'use gda_control.record_cross_store_recovery_binding()'
            USING ERRCODE = '55000';
    END IF;
    IF gda_control.current_tenant() IS NULL
       OR NEW.tenant_id IS DISTINCT FROM gda_control.current_tenant() THEN
        RAISE EXCEPTION 'cross-store recovery binding tenant context is missing or mismatched'
            USING ERRCODE = '42501';
    END IF;
    IF NOT EXISTS (
        SELECT 1
        FROM jsonb_array_elements_text(NEW.binding_document -> 'tenant_ids') AS ids(value)
        WHERE ids.value = NEW.tenant_id
    ) THEN
        RAISE EXCEPTION 'cross-store recovery binding does not cover authority tenant'
            USING ERRCODE = '42501';
    END IF;
    RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION gda_control.record_cross_store_recovery_binding(
    p_tenant_id TEXT,
    p_binding_sha256 TEXT,
    p_binding_document JSONB
)
RETURNS TABLE(binding_document JSONB, created BOOLEAN)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, gda_control
SET row_security = on
AS $$
DECLARE
    v_existing gda_control.cross_store_recovery_binding_history%ROWTYPE;
    v_source_ref TEXT;
    v_tenant_count INTEGER;
    v_distinct_tenant_count INTEGER;
BEGIN
    IF gda_control.current_tenant() IS NULL
       OR p_tenant_id IS DISTINCT FROM gda_control.current_tenant() THEN
        RAISE EXCEPTION 'cross-store recovery binding tenant context is missing or mismatched'
            USING ERRCODE = '42501';
    END IF;
    IF p_tenant_id IS NULL OR p_tenant_id !~ '^[a-z0-9][a-z0-9._-]{0,63}$'
       OR p_binding_sha256 IS NULL OR p_binding_sha256 !~ '^[0-9a-f]{64}$'
       OR p_binding_document IS NULL
       OR jsonb_typeof(p_binding_document) <> 'object'
       OR p_binding_document ->> 'schema'
            IS DISTINCT FROM 'gda.cross_store_recovery_binding.v1'
       OR p_binding_document ->> 'binding_sha256'
            IS DISTINCT FROM p_binding_sha256
       OR NULLIF(btrim(p_binding_document ->> 'source_resource_version_ref'), '') IS NULL
       OR octet_length(p_binding_document ->> 'source_resource_version_ref') > 512
       OR jsonb_typeof(p_binding_document -> 'tenant_ids') <> 'array'
       OR jsonb_array_length(p_binding_document -> 'tenant_ids') < 1
       OR p_binding_document ->> 'source_content_sha256' !~ '^[0-9a-f]{64}$'
       OR p_binding_document ->> 'control_manifest_sha256' !~ '^[0-9a-f]{64}$'
       OR p_binding_document ->> 'object_manifest_sha256' !~ '^[0-9a-f]{64}$'
       OR EXISTS (
           SELECT 1
           FROM jsonb_array_elements_text(p_binding_document -> 'tenant_ids') AS ids(value)
           WHERE ids.value !~ '^[a-z0-9][a-z0-9._-]{0,63}$'
       ) THEN
        RAISE EXCEPTION 'cross-store recovery binding identity or evidence is invalid'
            USING ERRCODE = '22023';
    END IF;

    SELECT count(*), count(DISTINCT value)
    INTO v_tenant_count, v_distinct_tenant_count
    FROM jsonb_array_elements_text(p_binding_document -> 'tenant_ids') AS ids(value);
    IF v_tenant_count <> v_distinct_tenant_count
       OR NOT EXISTS (
           SELECT 1
           FROM jsonb_array_elements_text(p_binding_document -> 'tenant_ids') AS ids(value)
           WHERE ids.value = p_tenant_id
       ) THEN
        RAISE EXCEPTION 'cross-store recovery binding tenant set is invalid'
            USING ERRCODE = '22023';
    END IF;
    IF (p_binding_document -> 'tenant_ids') IS DISTINCT FROM (
        SELECT jsonb_agg(ids.value ORDER BY ids.value)
        FROM jsonb_array_elements_text(p_binding_document -> 'tenant_ids') AS ids(value)
    ) THEN
        RAISE EXCEPTION 'cross-store recovery binding tenant set must be sorted'
            USING ERRCODE = '22023';
    END IF;

    v_source_ref := p_binding_document ->> 'source_resource_version_ref';
    PERFORM pg_advisory_xact_lock(
        hashtextextended(
            'cross-store-recovery-binding|' || p_tenant_id || '|' || v_source_ref,
            0
        )
    );

    SELECT history.* INTO v_existing
    FROM gda_control.cross_store_recovery_binding_history AS history
    WHERE history.tenant_id = p_tenant_id
      AND history.binding_sha256 = p_binding_sha256;
    IF FOUND THEN
        IF v_existing.binding_document IS DISTINCT FROM p_binding_document THEN
            RAISE EXCEPTION 'cross-store recovery binding idempotency evidence differs'
                USING ERRCODE = '40001';
        END IF;
        RETURN QUERY SELECT v_existing.binding_document, FALSE;
        RETURN;
    END IF;

    SELECT history.* INTO v_existing
    FROM gda_control.cross_store_recovery_binding_history AS history
    WHERE history.tenant_id = p_tenant_id
      AND history.source_resource_version_ref = v_source_ref;
    IF FOUND THEN
        RAISE EXCEPTION 'cross-store recovery source already has a different binding'
            USING ERRCODE = '40001';
    END IF;

    PERFORM set_config(
        'gda.cross_store_recovery_binding_write_allowed', '1', true
    );
    INSERT INTO gda_control.cross_store_recovery_binding_history (
        tenant_id, binding_sha256, source_resource_version_ref, binding_document
    ) VALUES (
        p_tenant_id, p_binding_sha256, v_source_ref, p_binding_document
    )
    RETURNING * INTO v_existing;
    PERFORM set_config(
        'gda.cross_store_recovery_binding_write_allowed', '0', true
    );

    RETURN QUERY SELECT v_existing.binding_document, TRUE;
EXCEPTION WHEN OTHERS THEN
    PERFORM set_config(
        'gda.cross_store_recovery_binding_write_allowed', '0', true
    );
    RAISE;
END;
$$;

DROP TRIGGER IF EXISTS trg_gda_cross_store_recovery_binding_insert_guard
    ON gda_control.cross_store_recovery_binding_history;
CREATE TRIGGER trg_gda_cross_store_recovery_binding_insert_guard
BEFORE INSERT ON gda_control.cross_store_recovery_binding_history
FOR EACH ROW EXECUTE FUNCTION gda_control.guard_cross_store_recovery_binding_insert();

DROP TRIGGER IF EXISTS trg_gda_cross_store_recovery_binding_immutable
    ON gda_control.cross_store_recovery_binding_history;
CREATE TRIGGER trg_gda_cross_store_recovery_binding_immutable
BEFORE UPDATE OR DELETE ON gda_control.cross_store_recovery_binding_history
FOR EACH ROW EXECUTE FUNCTION gda_control.reject_immutable_mutation();

ALTER TABLE gda_control.cross_store_recovery_binding_history
    ENABLE ROW LEVEL SECURITY;
ALTER TABLE gda_control.cross_store_recovery_binding_history
    FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation
    ON gda_control.cross_store_recovery_binding_history;
CREATE POLICY tenant_isolation
    ON gda_control.cross_store_recovery_binding_history
    USING (tenant_id = gda_control.current_tenant())
    WITH CHECK (tenant_id = gda_control.current_tenant());

REVOKE ALL ON TABLE gda_control.cross_store_recovery_binding_history
    FROM PUBLIC, gda_control_gateway;
REVOKE ALL ON TABLE gda_control.cross_store_recovery_binding_current
    FROM PUBLIC, gda_control_gateway;
GRANT SELECT ON TABLE gda_control.cross_store_recovery_binding_history
    TO gda_control_gateway;
GRANT SELECT ON TABLE gda_control.cross_store_recovery_binding_current
    TO gda_control_gateway;

REVOKE ALL ON FUNCTION gda_control.guard_cross_store_recovery_binding_insert()
    FROM PUBLIC;
REVOKE ALL ON FUNCTION gda_control.record_cross_store_recovery_binding(TEXT, TEXT, JSONB)
    FROM PUBLIC;
GRANT EXECUTE ON FUNCTION gda_control.record_cross_store_recovery_binding(TEXT, TEXT, JSONB)
    TO gda_control_gateway;
