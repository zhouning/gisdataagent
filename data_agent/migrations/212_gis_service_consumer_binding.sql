-- 212: Exact-release consumer authorization for governed GIS MVT delivery.
--
-- DataProduct ConsumerBinding controls product promotion and offline/product
-- consumption. A protocol endpoint needs a second, typed fact: the consumer
-- is admitted to this exact GIS ServiceDefinitionVersion and release. This
-- first profile intentionally covers only mvt.read; quota accounting and
-- generic ABAC are not implied by this authority.

CREATE TABLE gda_control.service_consumer_binding (
    tenant_id TEXT NOT NULL,
    service_consumer_binding_id UUID PRIMARY KEY,
    service_urn TEXT NOT NULL,
    service_definition_version_id UUID NOT NULL,
    service_release_binding_id UUID NOT NULL,
    consumer_ref TEXT NOT NULL,
    action TEXT NOT NULL,
    purpose TEXT NOT NULL,
    scope JSONB NOT NULL,
    credential_ref TEXT NOT NULL,
    expires_at TIMESTAMPTZ NOT NULL,
    compatibility_fingerprint CHAR(64) NOT NULL,
    compatibility_evidence JSONB NOT NULL,
    binding_sha256 CHAR(64) NOT NULL,
    created_by TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    CONSTRAINT uq_gda_service_consumer_binding_tenant_id
        UNIQUE (tenant_id, service_consumer_binding_id),
    CONSTRAINT uq_gda_service_consumer_binding_sha256
        UNIQUE (tenant_id, binding_sha256),
    CONSTRAINT fk_gda_service_consumer_binding_service
        FOREIGN KEY (tenant_id, service_urn)
        REFERENCES gda_control.gis_service(tenant_id, service_urn),
    CONSTRAINT fk_gda_service_consumer_binding_release
        FOREIGN KEY (
            tenant_id, service_definition_version_id,
            service_release_binding_id
        ) REFERENCES gda_control.service_release_binding(
            tenant_id, service_definition_version_id,
            service_release_binding_id
        ),
    CONSTRAINT ck_gda_service_consumer_binding_service_tenant CHECK (
        service_urn ~ '^gda://[a-z0-9][a-z0-9._-]{0,63}/gis_service/[a-z0-9][a-z0-9._-]{0,127}$'
        AND split_part(service_urn, '/', 3) = tenant_id
    ),
    CONSTRAINT ck_gda_service_consumer_binding_consumer CHECK (
        consumer_ref ~ '^(human|workload|agent|service):[^[:space:]]+$'
        AND length(consumer_ref) BETWEEN 7 AND 512
    ),
    CONSTRAINT ck_gda_service_consumer_binding_profile CHECK (
        action = 'mvt.read'
        AND purpose = 'gis_mvt_read'
        AND scope = '{"operations":["read"]}'::jsonb
    ),
    CONSTRAINT ck_gda_service_consumer_binding_text CHECK (
        NULLIF(btrim(credential_ref), '') IS NOT NULL
        AND NULLIF(btrim(created_by), '') IS NOT NULL
    ),
    CONSTRAINT ck_gda_service_consumer_binding_expiry CHECK (
        expires_at > created_at
    ),
    CONSTRAINT ck_gda_service_consumer_binding_compatibility CHECK (
        compatibility_fingerprint ~ '^[0-9a-f]{64}$'
        AND jsonb_typeof(compatibility_evidence) = 'object'
        AND compatibility_evidence <> '{}'::jsonb
    ),
    CONSTRAINT ck_gda_service_consumer_binding_sha256 CHECK (
        binding_sha256 ~ '^[0-9a-f]{64}$'
    )
);

CREATE INDEX idx_gda_service_consumer_binding_active
    ON gda_control.service_consumer_binding(
        tenant_id, service_urn, service_definition_version_id,
        service_release_binding_id, consumer_ref, expires_at,
        service_consumer_binding_id
    );

CREATE OR REPLACE FUNCTION gda_control.guard_service_consumer_binding_insert()
RETURNS TRIGGER
LANGUAGE plpgsql
SET search_path = pg_catalog, gda_control
AS $$
BEGIN
    IF COALESCE(
        current_setting('gda.service_consumer_binding_allowed', true), ''
    ) <> '1' THEN
        RAISE EXCEPTION 'use gda_control.record_service_consumer_binding()'
            USING ERRCODE = '55000';
    END IF;
    IF gda_control.current_tenant() IS NULL
       OR NEW.tenant_id IS DISTINCT FROM gda_control.current_tenant() THEN
        RAISE EXCEPTION 'service consumer binding tenant context is missing or mismatched'
            USING ERRCODE = '42501';
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER trg_gda_service_consumer_binding_insert
BEFORE INSERT ON gda_control.service_consumer_binding
FOR EACH ROW EXECUTE FUNCTION gda_control.guard_service_consumer_binding_insert();

CREATE TRIGGER trg_gda_service_consumer_binding_immutable
BEFORE UPDATE OR DELETE ON gda_control.service_consumer_binding
FOR EACH ROW EXECUTE FUNCTION gda_control.reject_immutable_mutation();

CREATE OR REPLACE FUNCTION gda_control.record_service_consumer_binding(
    p_tenant_id TEXT,
    p_service_consumer_binding_id UUID,
    p_service_urn TEXT,
    p_service_definition_version_id UUID,
    p_service_release_binding_id UUID,
    p_consumer_ref TEXT,
    p_action TEXT,
    p_purpose TEXT,
    p_scope JSONB,
    p_credential_ref TEXT,
    p_expires_at TIMESTAMPTZ,
    p_compatibility_fingerprint CHAR(64),
    p_compatibility_evidence JSONB,
    p_binding_sha256 CHAR(64),
    p_created_by TEXT,
    p_created_at TIMESTAMPTZ
)
RETURNS TABLE(service_consumer_binding_id UUID, created BOOLEAN)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, gda_control
SET row_security = on
AS $$
DECLARE
    v_existing gda_control.service_consumer_binding%ROWTYPE;
    v_inserted UUID;
BEGIN
    IF p_tenant_id IS DISTINCT FROM gda_control.current_tenant() THEN
        RAISE EXCEPTION 'service consumer binding tenant context is missing or mismatched'
            USING ERRCODE = '42501';
    END IF;

    PERFORM 1
      FROM gda_control.gis_service_definition_version AS definition
      JOIN gda_control.service_release_binding AS release
        ON release.tenant_id = definition.tenant_id
       AND release.service_definition_version_id = definition.service_definition_version_id
       AND release.service_release_binding_id = p_service_release_binding_id
     WHERE definition.tenant_id = p_tenant_id
       AND definition.service_definition_version_id = p_service_definition_version_id
       AND definition.service_urn = p_service_urn
       AND definition.service_type = 'vector_tile';
    IF NOT FOUND THEN
        RAISE EXCEPTION 'service consumer binding must target one vector-tile service release'
            USING ERRCODE = '23514';
    END IF;

    PERFORM set_config('gda.service_consumer_binding_allowed', '1', true);
    INSERT INTO gda_control.service_consumer_binding (
        tenant_id, service_consumer_binding_id, service_urn,
        service_definition_version_id, service_release_binding_id,
        consumer_ref, action, purpose, scope, credential_ref, expires_at,
        compatibility_fingerprint, compatibility_evidence, binding_sha256,
        created_by, created_at
    ) VALUES (
        p_tenant_id, p_service_consumer_binding_id, p_service_urn,
        p_service_definition_version_id, p_service_release_binding_id,
        p_consumer_ref, p_action, p_purpose, p_scope, p_credential_ref,
        p_expires_at, p_compatibility_fingerprint, p_compatibility_evidence,
        p_binding_sha256, p_created_by, p_created_at
    ) ON CONFLICT DO NOTHING
    RETURNING gda_control.service_consumer_binding.service_consumer_binding_id
        INTO v_inserted;

    SELECT binding.* INTO v_existing
      FROM gda_control.service_consumer_binding AS binding
     WHERE binding.tenant_id = p_tenant_id
       AND (
           binding.service_consumer_binding_id = p_service_consumer_binding_id
           OR binding.binding_sha256 = p_binding_sha256
       )
     ORDER BY (
         binding.service_consumer_binding_id = p_service_consumer_binding_id
     ) DESC
     LIMIT 1;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'service consumer binding write was not visible'
            USING ERRCODE = '40001';
    END IF;
    IF v_existing.service_consumer_binding_id IS DISTINCT FROM p_service_consumer_binding_id
       OR v_existing.service_urn IS DISTINCT FROM p_service_urn
       OR v_existing.service_definition_version_id IS DISTINCT FROM p_service_definition_version_id
       OR v_existing.service_release_binding_id IS DISTINCT FROM p_service_release_binding_id
       OR v_existing.consumer_ref IS DISTINCT FROM p_consumer_ref
       OR v_existing.action IS DISTINCT FROM p_action
       OR v_existing.purpose IS DISTINCT FROM p_purpose
       OR v_existing.scope IS DISTINCT FROM p_scope
       OR v_existing.credential_ref IS DISTINCT FROM p_credential_ref
       OR v_existing.expires_at IS DISTINCT FROM p_expires_at
       OR v_existing.compatibility_fingerprint IS DISTINCT FROM p_compatibility_fingerprint
       OR v_existing.compatibility_evidence IS DISTINCT FROM p_compatibility_evidence
       OR v_existing.binding_sha256 IS DISTINCT FROM p_binding_sha256
       OR v_existing.created_by IS DISTINCT FROM p_created_by
       OR v_existing.created_at IS DISTINCT FROM p_created_at THEN
        RAISE EXCEPTION 'ServiceConsumerBinding identity already has a different payload'
            USING ERRCODE = '23505';
    END IF;
    RETURN QUERY SELECT v_existing.service_consumer_binding_id, (v_inserted IS NOT NULL);
END;
$$;

ALTER TABLE gda_control.service_consumer_binding ENABLE ROW LEVEL SECURITY;
ALTER TABLE gda_control.service_consumer_binding FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON gda_control.service_consumer_binding
    USING (tenant_id = gda_control.current_tenant())
    WITH CHECK (tenant_id = gda_control.current_tenant());

REVOKE ALL ON TABLE gda_control.service_consumer_binding
    FROM PUBLIC, gda_control_gateway;
GRANT SELECT ON TABLE gda_control.service_consumer_binding TO gda_control_gateway;

REVOKE ALL ON FUNCTION gda_control.record_service_consumer_binding(
    TEXT, UUID, TEXT, UUID, UUID, TEXT, TEXT, TEXT, JSONB, TEXT,
    TIMESTAMPTZ, CHAR(64), JSONB, CHAR(64), TEXT, TIMESTAMPTZ
) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION gda_control.record_service_consumer_binding(
    TEXT, UUID, TEXT, UUID, UUID, TEXT, TEXT, TEXT, JSONB, TEXT,
    TIMESTAMPTZ, CHAR(64), JSONB, CHAR(64), TEXT, TIMESTAMPTZ
) TO gda_control_gateway;
