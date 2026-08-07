-- 125: Atomically project active master versions into generic platform resources.
--
-- The master-data ledger remains authoritative. This bridge gives every
-- activation a stable ResourceVersion identity that Metadata Fabric and other
-- platform consumers can resolve without deriving identity from display data.

CREATE OR REPLACE FUNCTION gda_control.master_resource_version_id(
    p_tenant_id TEXT,
    p_entity_version_ref TEXT,
    p_entity_fingerprint TEXT
)
RETURNS UUID
LANGUAGE sql
IMMUTABLE
STRICT
SET search_path = pg_catalog, public
AS $$
    SELECT (
        substr(value, 1, 8) || '-' ||
        substr(value, 9, 4) || '-' ||
        '5' || substr(value, 14, 3) || '-' ||
        '8' || substr(value, 18, 3) || '-' ||
        substr(value, 21, 12)
    )::uuid
    FROM (
        SELECT encode(
            public.digest(
                convert_to(
                    'gda.master_resource_version.v1|' || p_tenant_id || '|' ||
                    p_entity_version_ref || '|' || p_entity_fingerprint,
                    'UTF8'
                ),
                'sha256'
            ),
            'hex'
        ) AS value
    ) AS fingerprint
$$;

CREATE TABLE IF NOT EXISTS gda_control.master_resource_projection (
    tenant_id TEXT NOT NULL,
    entity_ref TEXT NOT NULL,
    entity_version_ref TEXT NOT NULL,
    entity_fingerprint CHAR(64) NOT NULL,
    activation_version INTEGER NOT NULL,
    resource_version_id UUID NOT NULL,
    previous_resource_version_id UUID,
    approval_case_ref TEXT NOT NULL,
    projected_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (tenant_id, entity_ref, activation_version),
    CONSTRAINT uq_gda_master_resource_projection_version UNIQUE (
        tenant_id, entity_ref, activation_version,
        resource_version_id, entity_fingerprint
    ),
    CONSTRAINT fk_gda_master_resource_projection_master_version
        FOREIGN KEY (tenant_id, entity_version_ref, entity_fingerprint)
        REFERENCES gda_control.master_entity_version(
            tenant_id, entity_version_ref, entity_fingerprint
        ),
    CONSTRAINT fk_gda_master_resource_projection_resource_version
        FOREIGN KEY (
            tenant_id, entity_ref, resource_version_id, entity_fingerprint
        )
        REFERENCES gda_control.resource_version(
            tenant_id, resource_urn, resource_version_id, content_sha256
        ),
    CONSTRAINT fk_gda_master_resource_projection_previous_version
        FOREIGN KEY (tenant_id, entity_ref, previous_resource_version_id)
        REFERENCES gda_control.resource_version(
            tenant_id, resource_urn, resource_version_id
        ),
    CONSTRAINT fk_gda_master_resource_projection_approval
        FOREIGN KEY (tenant_id, approval_case_ref)
        REFERENCES gda_control.approval_case(tenant_id, approval_case_ref),
    CONSTRAINT ck_gda_master_resource_projection_entity CHECK (
        entity_ref ~ '^gda://[a-z0-9][a-z0-9._-]{0,63}/master_entity/[a-z0-9][a-z0-9._-]{0,127}$'
        AND split_part(entity_ref, '/', 3) = tenant_id
        AND entity_version_ref LIKE entity_ref || '.v%'
        AND substring(entity_version_ref FROM length(entity_ref) + 3)
            ~ '^[1-9][0-9]*$'
    ),
    CONSTRAINT ck_gda_master_resource_projection_fingerprint
        CHECK (entity_fingerprint ~ '^[0-9a-f]{64}$'),
    CONSTRAINT ck_gda_master_resource_projection_activation
        CHECK (activation_version >= 1)
);

CREATE INDEX IF NOT EXISTS idx_gda_master_resource_projection_version
    ON gda_control.master_resource_projection(
        tenant_id, resource_version_id, activation_version DESC
    );

CREATE OR REPLACE FUNCTION gda_control.project_master_activation_to_resource(
    p_tenant_id TEXT,
    p_entity_ref TEXT,
    p_activation_version INTEGER
)
RETURNS UUID
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, gda_control, public
SET row_security = on
AS $$
DECLARE
    v_activation gda_control.master_entity_activation%ROWTYPE;
    v_version gda_control.master_entity_version%ROWTYPE;
    v_resource gda_control.resource%ROWTYPE;
    v_resource_version gda_control.resource_version%ROWTYPE;
    v_projection gda_control.master_resource_projection%ROWTYPE;
    v_resource_version_id UUID;
    v_previous_resource_version_id UUID;
    v_governance_ref JSONB;
    v_authority_version_ref JSONB;
    v_resource_version_preexisting BOOLEAN;
BEGIN
    IF gda_control.current_tenant() IS NULL
       OR p_tenant_id IS DISTINCT FROM gda_control.current_tenant() THEN
        RAISE EXCEPTION 'master resource projection tenant context is missing or mismatched'
            USING ERRCODE = '42501';
    END IF;

    SELECT * INTO v_activation
    FROM gda_control.master_entity_activation
    WHERE tenant_id = p_tenant_id
      AND entity_ref = p_entity_ref
      AND activation_version = p_activation_version;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'exact master activation was not found'
            USING ERRCODE = 'P0002';
    END IF;

    SELECT * INTO v_version
    FROM gda_control.master_entity_version
    WHERE tenant_id = p_tenant_id
      AND entity_version_ref = v_activation.active_version_ref
      AND entity_fingerprint = v_activation.active_fingerprint;
    IF NOT FOUND
       OR v_version.entity_ref <> p_entity_ref
       OR v_version.domain <> v_activation.domain
       OR v_version.business_key <> v_activation.business_key THEN
        RAISE EXCEPTION 'master activation does not bind an exact entity version'
            USING ERRCODE = '23514';
    END IF;

    v_resource_version_id := gda_control.master_resource_version_id(
        p_tenant_id,
        v_version.entity_version_ref,
        v_version.entity_fingerprint
    );
    SELECT resource_version_id INTO v_previous_resource_version_id
    FROM gda_control.master_resource_projection
    WHERE tenant_id = p_tenant_id
      AND entity_ref = p_entity_ref
      AND activation_version < p_activation_version
    ORDER BY activation_version DESC
    LIMIT 1;

    v_governance_ref := jsonb_build_object(
        'schema', 'gda.master_resource.v1',
        'master_data_domain', v_version.domain
    );
    INSERT INTO gda_control.resource (
        tenant_id, resource_urn, resource_kind, authority_system,
        authority_locator, owner_ref, governance_ref, technical_refs
    ) VALUES (
        p_tenant_id, p_entity_ref, 'master_entity', 'gda_control.master_data',
        p_entity_ref, v_version.owner_subject, v_governance_ref, '[]'::jsonb
    )
    ON CONFLICT DO NOTHING;

    SELECT * INTO v_resource
    FROM gda_control.resource
    WHERE tenant_id = p_tenant_id AND resource_urn = p_entity_ref;
    IF NOT FOUND
       OR v_resource.resource_kind <> 'master_entity'
       OR v_resource.authority_system <> 'gda_control.master_data'
       OR v_resource.authority_locator <> p_entity_ref
       OR v_resource.owner_ref <> v_version.owner_subject
       OR v_resource.governance_ref IS DISTINCT FROM v_governance_ref
       OR v_resource.technical_refs IS DISTINCT FROM '[]'::jsonb THEN
        RAISE EXCEPTION 'master Resource identity already has different evidence'
            USING ERRCODE = '40001';
    END IF;

    SELECT EXISTS (
        SELECT 1 FROM gda_control.master_resource_projection
        WHERE tenant_id = p_tenant_id
          AND resource_version_id = v_resource_version_id
    ) INTO v_resource_version_preexisting;
    v_authority_version_ref := jsonb_build_object(
        'authority_system', 'gda_control.master_data',
        'entity_version_ref', v_version.entity_version_ref,
        'entity_fingerprint', v_version.entity_fingerprint
    );
    INSERT INTO gda_control.resource_version (
        tenant_id, resource_version_id, resource_urn, version_key,
        predecessor_version_id, content_sha256, authority_version_ref,
        created_by, created_at
    ) VALUES (
        p_tenant_id, v_resource_version_id, p_entity_ref,
        'v' || v_version.entity_version::text,
        v_previous_resource_version_id, v_version.entity_fingerprint,
        v_authority_version_ref, v_version.created_by, v_version.created_at
    )
    ON CONFLICT DO NOTHING;

    SELECT * INTO v_resource_version
    FROM gda_control.resource_version
    WHERE tenant_id = p_tenant_id
      AND resource_version_id = v_resource_version_id;
    IF NOT FOUND
       OR v_resource_version.resource_urn <> p_entity_ref
       OR v_resource_version.version_key <> 'v' || v_version.entity_version::text
       OR v_resource_version.content_sha256 <> v_version.entity_fingerprint
       OR v_resource_version.authority_version_ref IS DISTINCT FROM v_authority_version_ref
       OR v_resource_version.created_by <> v_version.created_by
       OR v_resource_version.created_at <> v_version.created_at
       OR (
            NOT v_resource_version_preexisting
            AND v_resource_version.predecessor_version_id
                IS DISTINCT FROM v_previous_resource_version_id
       ) THEN
        RAISE EXCEPTION 'master ResourceVersion identity already has different evidence'
            USING ERRCODE = '40001';
    END IF;

    INSERT INTO gda_control.master_resource_projection (
        tenant_id, entity_ref, entity_version_ref, entity_fingerprint,
        activation_version, resource_version_id,
        previous_resource_version_id, approval_case_ref, projected_at
    ) VALUES (
        p_tenant_id, p_entity_ref, v_version.entity_version_ref,
        v_version.entity_fingerprint, p_activation_version,
        v_resource_version_id, v_previous_resource_version_id,
        v_activation.approval_case_ref, v_activation.activated_at
    )
    ON CONFLICT DO NOTHING;

    SELECT * INTO v_projection
    FROM gda_control.master_resource_projection
    WHERE tenant_id = p_tenant_id
      AND entity_ref = p_entity_ref
      AND activation_version = p_activation_version;
    IF NOT FOUND
       OR v_projection.entity_version_ref <> v_version.entity_version_ref
       OR v_projection.entity_fingerprint <> v_version.entity_fingerprint
       OR v_projection.resource_version_id <> v_resource_version_id
       OR v_projection.previous_resource_version_id
            IS DISTINCT FROM v_previous_resource_version_id
       OR v_projection.approval_case_ref <> v_activation.approval_case_ref
       OR v_projection.projected_at <> v_activation.activated_at THEN
        RAISE EXCEPTION 'master resource projection already has different evidence'
            USING ERRCODE = '40001';
    END IF;

    RETURN v_resource_version_id;
END;
$$;

CREATE OR REPLACE FUNCTION gda_control.project_master_activation_trigger()
RETURNS TRIGGER
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, gda_control
SET row_security = on
AS $$
BEGIN
    PERFORM gda_control.project_master_activation_to_resource(
        NEW.tenant_id,
        NEW.entity_ref,
        NEW.activation_version
    );
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_gda_master_activation_resource_projection
    ON gda_control.master_entity_activation;
CREATE TRIGGER trg_gda_master_activation_resource_projection
AFTER INSERT OR UPDATE ON gda_control.master_entity_activation
FOR EACH ROW EXECUTE FUNCTION gda_control.project_master_activation_trigger();

ALTER TABLE gda_control.master_resource_projection ENABLE ROW LEVEL SECURITY;
ALTER TABLE gda_control.master_resource_projection FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation
    ON gda_control.master_resource_projection;
CREATE POLICY tenant_isolation
    ON gda_control.master_resource_projection
    USING (tenant_id = gda_control.current_tenant())
    WITH CHECK (tenant_id = gda_control.current_tenant());

DROP TRIGGER IF EXISTS trg_gda_master_resource_projection_immutable
    ON gda_control.master_resource_projection;
CREATE TRIGGER trg_gda_master_resource_projection_immutable
BEFORE UPDATE OR DELETE ON gda_control.master_resource_projection
FOR EACH ROW EXECUTE FUNCTION gda_control.reject_immutable_mutation();

REVOKE ALL ON TABLE gda_control.master_resource_projection
    FROM PUBLIC, gda_control_gateway;
GRANT SELECT ON TABLE gda_control.master_resource_projection
    TO gda_control_gateway;
REVOKE ALL ON FUNCTION gda_control.master_resource_version_id(TEXT, TEXT, TEXT)
    FROM PUBLIC;
REVOKE ALL ON FUNCTION gda_control.project_master_activation_to_resource(
    TEXT, TEXT, INTEGER
) FROM PUBLIC;
REVOKE ALL ON FUNCTION gda_control.project_master_activation_trigger()
    FROM PUBLIC;

-- Upgrade existing repositories by projecting only their current active
-- pointer. Historical activations remain in master_data_event and are not
-- reconstructed as if they had been projected at their original time.
DO $$
DECLARE
    v_activation RECORD;
BEGIN
    FOR v_activation IN
        SELECT tenant_id, entity_ref, activation_version
        FROM gda_control.master_entity_activation
        ORDER BY tenant_id, entity_ref
    LOOP
        PERFORM set_config(
            'app.current_tenant', v_activation.tenant_id, true
        );
        PERFORM gda_control.project_master_activation_to_resource(
            v_activation.tenant_id,
            v_activation.entity_ref,
            v_activation.activation_version
        );
    END LOOP;
END
$$;
