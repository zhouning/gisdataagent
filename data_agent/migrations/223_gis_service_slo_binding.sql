-- 223: Bind an actual GIS service to one exact activated SLO authority.
--
-- ServiceSLO is a projection over the generic SLO authority.  It does not
-- duplicate SLO definitions or activation state; this table records the
-- auditable GIS control-plane decision to consume one exact activation.

CREATE TABLE IF NOT EXISTS gda_control.gis_service_slo_binding (
    tenant_id TEXT NOT NULL,
    binding_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    service_urn TEXT NOT NULL,
    slo_definition_ref TEXT NOT NULL,
    active_version_ref TEXT NOT NULL,
    definition_fingerprint CHAR(64) NOT NULL,
    approval_case_ref TEXT NOT NULL,
    activation_version INTEGER NOT NULL,
    bound_by TEXT NOT NULL,
    binding_reason TEXT NOT NULL,
    bound_at TIMESTAMPTZ NOT NULL,
    CONSTRAINT uq_gda_gis_service_slo_binding_tenant_id
        UNIQUE (tenant_id, binding_id),
    CONSTRAINT uq_gda_gis_service_slo_binding_activation
        UNIQUE (
            tenant_id, service_urn, slo_definition_ref, activation_version
        ),
    CONSTRAINT fk_gda_gis_service_slo_binding_service
        FOREIGN KEY (tenant_id, service_urn)
        REFERENCES gda_control.gis_service(tenant_id, service_urn),
    CONSTRAINT fk_gda_gis_service_slo_binding_version
        FOREIGN KEY (tenant_id, active_version_ref, definition_fingerprint)
        REFERENCES gda_control.slo_definition_version(
            tenant_id, slo_version_ref, definition_fingerprint
        ),
    CONSTRAINT fk_gda_gis_service_slo_binding_approval
        FOREIGN KEY (tenant_id, approval_case_ref)
        REFERENCES gda_control.approval_case(tenant_id, approval_case_ref),
    CONSTRAINT ck_gda_gis_service_slo_binding_tenant
        CHECK (tenant_id ~ '^[a-z0-9][a-z0-9._-]{0,63}$'),
    CONSTRAINT ck_gda_gis_service_slo_binding_service
        CHECK (
            service_urn ~ '^gda://[a-z0-9][a-z0-9._-]{0,63}/gis_service/[a-z0-9][a-z0-9._-]{0,127}$'
            AND split_part(service_urn, '/', 3) = tenant_id
        ),
    CONSTRAINT ck_gda_gis_service_slo_binding_definition
        CHECK (
            slo_definition_ref ~ '^gda://[a-z0-9][a-z0-9._-]{0,63}/slo_definition/[a-z0-9][a-z0-9._-]{0,127}$'
            AND split_part(slo_definition_ref, '/', 3) = tenant_id
        ),
    CONSTRAINT ck_gda_gis_service_slo_binding_version
        CHECK (
            active_version_ref ~ '^gda://[a-z0-9][a-z0-9._-]{0,63}/slo_definition/[a-z0-9][a-z0-9._-]{0,127}\.v[1-9][0-9]*$'
            AND active_version_ref LIKE slo_definition_ref || '.v%'
        ),
    CONSTRAINT ck_gda_gis_service_slo_binding_fingerprint
        CHECK (definition_fingerprint ~ '^[0-9a-f]{64}$'),
    CONSTRAINT ck_gda_gis_service_slo_binding_approval
        CHECK (
            approval_case_ref ~ '^gda://[a-z0-9][a-z0-9._-]{0,63}/approval_case/[a-z0-9][a-z0-9._-]{0,127}$'
            AND split_part(approval_case_ref, '/', 3) = tenant_id
        ),
    CONSTRAINT ck_gda_gis_service_slo_binding_activation_version
        CHECK (activation_version >= 1),
    CONSTRAINT ck_gda_gis_service_slo_binding_actor
        CHECK (bound_by ~ '^(human|workload|agent):[^[:space:]]{1,128}$'),
    CONSTRAINT ck_gda_gis_service_slo_binding_reason
        CHECK (NULLIF(btrim(binding_reason), '') IS NOT NULL)
);

CREATE OR REPLACE FUNCTION gda_control.bind_gis_service_slo(
    p_tenant_id TEXT,
    p_binding_id UUID,
    p_service_urn TEXT,
    p_slo_definition_ref TEXT,
    p_active_version_ref TEXT,
    p_definition_fingerprint TEXT,
    p_approval_case_ref TEXT,
    p_activation_version INTEGER,
    p_bound_by TEXT,
    p_binding_reason TEXT,
    p_bound_at TIMESTAMPTZ
)
RETURNS UUID
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, gda_control, public
SET row_security = on
AS $$
DECLARE
    v_active gda_control.slo_definition_activation%ROWTYPE;
    v_definition gda_control.slo_definition_version%ROWTYPE;
    v_existing gda_control.gis_service_slo_binding%ROWTYPE;
    v_inserted UUID;
BEGIN
    IF gda_control.current_tenant() IS DISTINCT FROM p_tenant_id THEN
        RAISE EXCEPTION 'GIS ServiceSLO tenant context mismatch' USING ERRCODE = '42501';
    END IF;
    IF p_binding_id IS NULL OR p_service_urn IS NULL
       OR p_slo_definition_ref IS NULL OR p_active_version_ref IS NULL
       OR p_definition_fingerprint !~ '^[0-9a-f]{64}$'
       OR p_approval_case_ref IS NULL OR p_activation_version < 1
       OR p_bound_by !~ '^(human|workload|agent):[^[:space:]]{1,128}$'
       OR NULLIF(btrim(p_binding_reason), '') IS NULL OR p_bound_at IS NULL THEN
        RAISE EXCEPTION 'GIS ServiceSLO binding identity or provenance is invalid'
            USING ERRCODE = '22023';
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM gda_control.gis_service
        WHERE tenant_id = p_tenant_id AND service_urn = p_service_urn
    ) THEN
        RAISE EXCEPTION 'GIS service % was not found', p_service_urn
            USING ERRCODE = 'P0002';
    END IF;

    SELECT * INTO v_active
    FROM gda_control.slo_definition_activation
    WHERE tenant_id = p_tenant_id
      AND slo_definition_ref = p_slo_definition_ref;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'SLO definition % has no active authority', p_slo_definition_ref
            USING ERRCODE = 'P0002';
    END IF;
    IF v_active.active_version_ref IS DISTINCT FROM p_active_version_ref
       OR v_active.active_fingerprint IS DISTINCT FROM p_definition_fingerprint
       OR v_active.approval_case_ref IS DISTINCT FROM p_approval_case_ref
       OR v_active.activation_version IS DISTINCT FROM p_activation_version THEN
        RAISE EXCEPTION 'GIS ServiceSLO binding must name the exact active authority'
            USING ERRCODE = '23514';
    END IF;
    SELECT * INTO v_definition
    FROM gda_control.slo_definition_version
    WHERE tenant_id = p_tenant_id
      AND slo_version_ref = p_active_version_ref
      AND definition_fingerprint = p_definition_fingerprint;
    IF NOT FOUND OR v_definition.service_resource_urn IS DISTINCT FROM p_service_urn THEN
        RAISE EXCEPTION 'SLO service resource does not match GIS service'
            USING ERRCODE = '23514';
    END IF;

    INSERT INTO gda_control.gis_service_slo_binding (
        tenant_id, binding_id, service_urn, slo_definition_ref,
        active_version_ref, definition_fingerprint, approval_case_ref,
        activation_version, bound_by, binding_reason, bound_at
    ) VALUES (
        p_tenant_id, p_binding_id, p_service_urn, p_slo_definition_ref,
        p_active_version_ref, p_definition_fingerprint, p_approval_case_ref,
        p_activation_version, p_bound_by, p_binding_reason, p_bound_at
    )
    ON CONFLICT (
        tenant_id, service_urn, slo_definition_ref, activation_version
    ) DO NOTHING
    RETURNING binding_id INTO v_inserted;
    IF v_inserted IS NOT NULL THEN
        RETURN v_inserted;
    END IF;

    SELECT * INTO v_existing
    FROM gda_control.gis_service_slo_binding
    WHERE tenant_id = p_tenant_id
      AND service_urn = p_service_urn
      AND slo_definition_ref = p_slo_definition_ref
      AND activation_version = p_activation_version;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'GIS ServiceSLO binding was not visible' USING ERRCODE = 'P0002';
    END IF;
    IF v_existing.binding_id IS DISTINCT FROM p_binding_id
       OR v_existing.slo_definition_ref IS DISTINCT FROM p_slo_definition_ref
       OR v_existing.active_version_ref IS DISTINCT FROM p_active_version_ref
       OR v_existing.definition_fingerprint IS DISTINCT FROM p_definition_fingerprint
       OR v_existing.approval_case_ref IS DISTINCT FROM p_approval_case_ref
       OR v_existing.activation_version IS DISTINCT FROM p_activation_version
       OR v_existing.bound_by IS DISTINCT FROM p_bound_by
       OR v_existing.binding_reason IS DISTINCT FROM p_binding_reason THEN
        RAISE EXCEPTION 'GIS ServiceSLO activation already has different evidence'
            USING ERRCODE = '40001';
    END IF;
    RETURN v_existing.binding_id;
END;
$$;

DROP TRIGGER IF EXISTS trg_gda_gis_service_slo_binding_immutable
    ON gda_control.gis_service_slo_binding;
CREATE TRIGGER trg_gda_gis_service_slo_binding_immutable
BEFORE UPDATE OR DELETE ON gda_control.gis_service_slo_binding
FOR EACH ROW EXECUTE FUNCTION gda_control.reject_immutable_mutation();

ALTER TABLE gda_control.gis_service_slo_binding ENABLE ROW LEVEL SECURITY;
ALTER TABLE gda_control.gis_service_slo_binding FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON gda_control.gis_service_slo_binding;
CREATE POLICY tenant_isolation ON gda_control.gis_service_slo_binding
USING (tenant_id = gda_control.current_tenant())
WITH CHECK (tenant_id = gda_control.current_tenant());

REVOKE ALL ON TABLE gda_control.gis_service_slo_binding
    FROM PUBLIC, gda_control_gateway;
GRANT SELECT ON TABLE gda_control.gis_service_slo_binding TO gda_control_gateway;
REVOKE ALL ON FUNCTION gda_control.bind_gis_service_slo(
    TEXT, UUID, TEXT, TEXT, TEXT, TEXT, TEXT, INTEGER, TEXT, TEXT, TIMESTAMPTZ
) FROM PUBLIC, gda_control_gateway;
GRANT EXECUTE ON FUNCTION gda_control.bind_gis_service_slo(
    TEXT, UUID, TEXT, TEXT, TEXT, TEXT, TEXT, INTEGER, TEXT, TEXT, TIMESTAMPTZ
) TO gda_control_gateway;
