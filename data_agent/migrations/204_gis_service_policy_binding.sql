-- 204: Immutable Gateway policy binding for governed MVT releases.
--
-- This is the first executable ServicePolicyBinding profile.  It binds a
-- release to the roles and ConsumerBinding operation that the Gateway can
-- actually enforce.  It deliberately does not claim row, column, spatial,
-- temporal, purpose, or provider-side policy enforcement.

CREATE TABLE gda_control.service_policy_binding (
    tenant_id TEXT NOT NULL,
    service_policy_binding_id UUID PRIMARY KEY,
    service_definition_version_id UUID NOT NULL,
    service_release_binding_id UUID NOT NULL,
    policy_key TEXT NOT NULL,
    version_key TEXT NOT NULL,
    predecessor_version_id UUID,
    action TEXT NOT NULL,
    enforcement_point TEXT NOT NULL,
    allowed_roles TEXT[] NOT NULL,
    consumer_binding_required_roles TEXT[] NOT NULL,
    required_consumer_operation TEXT NOT NULL,
    policy_sha256 CHAR(64) NOT NULL,
    created_by TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    CONSTRAINT uq_gda_service_policy_tenant_id
        UNIQUE (tenant_id, service_policy_binding_id),
    CONSTRAINT uq_gda_service_policy_definition_id
        UNIQUE (
            tenant_id, service_definition_version_id,
            service_policy_binding_id
        ),
    CONSTRAINT uq_gda_service_policy_release
        UNIQUE (
            tenant_id, service_definition_version_id,
            service_release_binding_id
        ),
    CONSTRAINT uq_gda_service_policy_lineage_id
        UNIQUE (
            tenant_id, service_definition_version_id, policy_key,
            service_policy_binding_id
        ),
    CONSTRAINT uq_gda_service_policy_key
        UNIQUE (
            tenant_id, service_definition_version_id, policy_key, version_key
        ),
    CONSTRAINT fk_gda_service_policy_definition
        FOREIGN KEY (tenant_id, service_definition_version_id)
        REFERENCES gda_control.gis_service_definition_version(
            tenant_id, service_definition_version_id
        ),
    CONSTRAINT fk_gda_service_policy_release
        FOREIGN KEY (
            tenant_id, service_definition_version_id,
            service_release_binding_id
        ) REFERENCES gda_control.service_release_binding(
            tenant_id, service_definition_version_id,
            service_release_binding_id
        ),
    CONSTRAINT fk_gda_service_policy_predecessor
        FOREIGN KEY (
            tenant_id, service_definition_version_id, policy_key,
            predecessor_version_id
        ) REFERENCES gda_control.service_policy_binding(
            tenant_id, service_definition_version_id, policy_key,
            service_policy_binding_id
        ),
    CONSTRAINT ck_gda_service_policy_keys CHECK (
        policy_key ~ '^[a-z0-9][a-z0-9._-]{0,127}$'
        AND version_key ~ '^v[0-9]+\.[0-9]+\.[0-9]+$'
    ),
    CONSTRAINT ck_gda_service_policy_not_self CHECK (
        predecessor_version_id IS NULL
        OR predecessor_version_id <> service_policy_binding_id
    ),
    CONSTRAINT ck_gda_service_policy_profile CHECK (
        action = 'mvt.read'
        AND enforcement_point = 'gateway'
        AND required_consumer_operation = 'read'
    ),
    CONSTRAINT ck_gda_service_policy_allowed_roles CHECK (
        cardinality(allowed_roles) BETWEEN 1 AND 16
        AND array_position(allowed_roles, NULL) IS NULL
        AND array_to_string(allowed_roles, ',')
            ~ '^[a-z0-9][a-z0-9._-]{0,127}(,[a-z0-9][a-z0-9._-]{0,127})*$'
    ),
    CONSTRAINT ck_gda_service_policy_consumer_roles CHECK (
        cardinality(consumer_binding_required_roles) BETWEEN 0 AND 16
        AND array_position(consumer_binding_required_roles, NULL) IS NULL
        AND COALESCE(array_to_string(consumer_binding_required_roles, ','), '')
            ~ '^$|^[a-z0-9][a-z0-9._-]{0,127}(,[a-z0-9][a-z0-9._-]{0,127})*$'
    ),
    CONSTRAINT ck_gda_service_policy_sha256 CHECK (
        policy_sha256 ~ '^[0-9a-f]{64}$'
    ),
    CONSTRAINT ck_gda_service_policy_actor CHECK (
        length(btrim(created_by)) BETWEEN 1 AND 512
    )
);

CREATE TRIGGER trg_gda_service_policy_insert
BEFORE INSERT ON gda_control.service_policy_binding
FOR EACH ROW EXECUTE FUNCTION gda_control.guard_gis_service_record_insert();
CREATE TRIGGER trg_gda_service_policy_immutable
BEFORE UPDATE OR DELETE ON gda_control.service_policy_binding
FOR EACH ROW EXECUTE FUNCTION gda_control.reject_immutable_mutation();

CREATE FUNCTION gda_control.record_service_policy_binding(
    p_tenant_id TEXT,
    p_service_policy_binding_id UUID,
    p_service_definition_version_id UUID,
    p_service_release_binding_id UUID,
    p_policy_key TEXT,
    p_version_key TEXT,
    p_predecessor_version_id UUID,
    p_action TEXT,
    p_enforcement_point TEXT,
    p_allowed_roles TEXT[],
    p_consumer_binding_required_roles TEXT[],
    p_required_consumer_operation TEXT,
    p_policy_sha256 TEXT,
    p_created_by TEXT,
    p_created_at TIMESTAMPTZ
)
RETURNS UUID
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, gda_control
SET row_security = on
AS $$
DECLARE
    v_existing gda_control.service_policy_binding%ROWTYPE;
BEGIN
    IF gda_control.current_tenant() IS NULL
       OR p_tenant_id IS DISTINCT FROM gda_control.current_tenant() THEN
        RAISE EXCEPTION 'service policy tenant context is missing or mismatched'
            USING ERRCODE = '42501';
    END IF;
    SELECT * INTO v_existing
      FROM gda_control.service_policy_binding
     WHERE tenant_id = p_tenant_id
       AND service_policy_binding_id = p_service_policy_binding_id;
    IF FOUND THEN
        IF v_existing.service_definition_version_id =
                p_service_definition_version_id
           AND v_existing.service_release_binding_id =
                p_service_release_binding_id
           AND v_existing.policy_key = p_policy_key
           AND v_existing.version_key = p_version_key
           AND v_existing.predecessor_version_id IS NOT DISTINCT FROM
                p_predecessor_version_id
           AND v_existing.action = p_action
           AND v_existing.enforcement_point = p_enforcement_point
           AND v_existing.allowed_roles = p_allowed_roles
           AND v_existing.consumer_binding_required_roles =
                p_consumer_binding_required_roles
           AND v_existing.required_consumer_operation =
                p_required_consumer_operation
           AND v_existing.policy_sha256 = p_policy_sha256
           AND v_existing.created_by = p_created_by
           AND v_existing.created_at = p_created_at THEN
            RETURN p_service_policy_binding_id;
        END IF;
        RAISE EXCEPTION 'service policy identity has different immutable content'
            USING ERRCODE = '40001';
    END IF;
    PERFORM 1
      FROM gda_control.gis_service_definition_version AS definition
      JOIN gda_control.service_release_binding AS release
        ON release.tenant_id = definition.tenant_id
       AND release.service_definition_version_id =
            definition.service_definition_version_id
       AND release.service_release_binding_id = p_service_release_binding_id
     WHERE definition.tenant_id = p_tenant_id
       AND definition.service_definition_version_id =
            p_service_definition_version_id
       AND definition.service_type = 'vector_tile';
    IF NOT FOUND THEN
        RAISE EXCEPTION 'service policy must bind one vector-tile service release'
            USING ERRCODE = '23514';
    END IF;
    IF EXISTS (
        SELECT 1
          FROM unnest(p_consumer_binding_required_roles) AS role(role)
         WHERE NOT role = ANY (p_allowed_roles)
    ) THEN
        RAISE EXCEPTION 'consumer-binding roles must be admitted by the service policy'
            USING ERRCODE = '23514';
    END IF;
    IF (
        SELECT count(*) FROM unnest(p_allowed_roles) AS role(role)
    ) <> (
        SELECT count(DISTINCT role) FROM unnest(p_allowed_roles) AS role(role)
    ) OR (
        SELECT count(*) FROM unnest(p_consumer_binding_required_roles) AS role(role)
    ) <> (
        SELECT count(DISTINCT role)
           FROM unnest(p_consumer_binding_required_roles) AS role(role)
    ) THEN
        RAISE EXCEPTION 'service policy roles must not repeat'
            USING ERRCODE = '23514';
    END IF;
    PERFORM set_config('gda.gis_service_record_allowed', '1', true);
    INSERT INTO gda_control.service_policy_binding (
        tenant_id, service_policy_binding_id, service_definition_version_id,
        service_release_binding_id, policy_key, version_key,
        predecessor_version_id, action, enforcement_point, allowed_roles,
        consumer_binding_required_roles, required_consumer_operation,
        policy_sha256, created_by, created_at
    ) VALUES (
        p_tenant_id, p_service_policy_binding_id,
        p_service_definition_version_id, p_service_release_binding_id,
        p_policy_key, p_version_key, p_predecessor_version_id, p_action,
        p_enforcement_point, p_allowed_roles,
        p_consumer_binding_required_roles, p_required_consumer_operation,
        p_policy_sha256, p_created_by, p_created_at
    );
    RETURN p_service_policy_binding_id;
END;
$$;

CREATE OR REPLACE FUNCTION gda_control.enforce_endpoint_release_binding()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    PERFORM 1
      FROM gda_control.service_deployment_revision AS deployment
      JOIN gda_control.service_release_binding AS release
        ON release.tenant_id = deployment.tenant_id
       AND release.service_definition_version_id = deployment.service_definition_version_id
       AND release.service_release_binding_id = deployment.service_release_binding_id
      JOIN gda_control.gis_service_definition_version AS definition
        ON definition.tenant_id = deployment.tenant_id
       AND definition.service_definition_version_id = deployment.service_definition_version_id
     WHERE deployment.tenant_id = NEW.tenant_id
       AND deployment.deployment_revision_id = NEW.deployment_revision_id
       AND definition.service_urn = NEW.service_urn
       AND (
           definition.service_type <> 'vector_tile'
           OR (
               release.cache_policy_version_id IS NOT NULL
               AND EXISTS (
                   SELECT 1
                     FROM gda_control.service_policy_binding AS policy
                    WHERE policy.tenant_id = deployment.tenant_id
                      AND policy.service_definition_version_id =
                            deployment.service_definition_version_id
                      AND policy.service_release_binding_id =
                            deployment.service_release_binding_id
               )
           )
       );
    IF NOT FOUND THEN
        RAISE EXCEPTION 'endpoint requires a complete cache- and policy-governed service release'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION gda_control.enforce_active_endpoint_release_binding()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    PERFORM 1
      FROM gda_control.endpoint_revision AS endpoint
      JOIN gda_control.service_deployment_revision AS deployment
        ON deployment.tenant_id = endpoint.tenant_id
       AND deployment.deployment_revision_id = endpoint.deployment_revision_id
      JOIN gda_control.service_release_binding AS release
        ON release.tenant_id = deployment.tenant_id
       AND release.service_definition_version_id = deployment.service_definition_version_id
       AND release.service_release_binding_id = deployment.service_release_binding_id
      JOIN gda_control.gis_service_definition_version AS definition
        ON definition.tenant_id = deployment.tenant_id
       AND definition.service_definition_version_id = deployment.service_definition_version_id
     WHERE endpoint.tenant_id = NEW.tenant_id
       AND endpoint.service_urn = NEW.service_urn
       AND endpoint.endpoint_revision_id = NEW.active_endpoint_revision_id
       AND (
           definition.service_type <> 'vector_tile'
           OR (
               release.cache_policy_version_id IS NOT NULL
               AND EXISTS (
                   SELECT 1
                     FROM gda_control.service_policy_binding AS policy
                    WHERE policy.tenant_id = deployment.tenant_id
                      AND policy.service_definition_version_id =
                            deployment.service_definition_version_id
                      AND policy.service_release_binding_id =
                            deployment.service_release_binding_id
               )
           )
       );
    IF NOT FOUND THEN
        RAISE EXCEPTION 'active endpoint requires a complete cache- and policy-governed service release'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;

ALTER TABLE gda_control.service_policy_binding ENABLE ROW LEVEL SECURITY;
ALTER TABLE gda_control.service_policy_binding FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON gda_control.service_policy_binding
    USING (tenant_id = gda_control.current_tenant())
    WITH CHECK (tenant_id = gda_control.current_tenant());

REVOKE ALL ON TABLE gda_control.service_policy_binding
FROM PUBLIC, gda_control_gateway;
GRANT SELECT ON TABLE gda_control.service_policy_binding TO gda_control_gateway;

REVOKE ALL ON FUNCTION gda_control.record_service_policy_binding(
    TEXT, UUID, UUID, UUID, TEXT, TEXT, UUID, TEXT, TEXT, TEXT[], TEXT[],
    TEXT, TEXT, TEXT, TIMESTAMPTZ
) FROM PUBLIC;
REVOKE ALL ON FUNCTION gda_control.enforce_endpoint_release_binding() FROM PUBLIC;
REVOKE ALL ON FUNCTION gda_control.enforce_active_endpoint_release_binding() FROM PUBLIC;

GRANT EXECUTE ON FUNCTION gda_control.record_service_policy_binding(
    TEXT, UUID, UUID, UUID, TEXT, TEXT, UUID, TEXT, TEXT, TEXT[], TEXT[],
    TEXT, TEXT, TEXT, TIMESTAMPTZ
) TO gda_control_gateway;
