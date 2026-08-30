-- 215: Approval-bound, append-only renewal for GIS service consumer bindings.
--
-- A renewal is a new immutable binding.  The previous binding remains
-- readable evidence, while Gateway active lookup excludes it through the
-- source-to-target renewal fact.

ALTER TABLE gda_control.service_consumer_binding
    ADD COLUMN renewal_of_binding_id UUID,
    ADD COLUMN renewal_approval_case_ref TEXT,
    ADD COLUMN renewal_plan_sha256 CHAR(64);

ALTER TABLE gda_control.service_consumer_binding
    DROP CONSTRAINT ck_gda_service_consumer_binding_approval_binding,
    ADD CONSTRAINT fk_gda_service_consumer_binding_renewal_source
        FOREIGN KEY (tenant_id, renewal_of_binding_id)
        REFERENCES gda_control.service_consumer_binding(
            tenant_id, service_consumer_binding_id
        ),
    ADD CONSTRAINT fk_gda_service_consumer_binding_renewal_case
        FOREIGN KEY (tenant_id, renewal_approval_case_ref)
        REFERENCES gda_control.approval_case(tenant_id, approval_case_ref),
    ADD CONSTRAINT ck_gda_service_consumer_binding_lifecycle CHECK (
        (
            approval_case_ref IS NULL
            AND grant_plan_sha256 IS NULL
            AND renewal_of_binding_id IS NULL
            AND renewal_approval_case_ref IS NULL
            AND renewal_plan_sha256 IS NULL
        ) OR (
            approval_case_ref IS NOT NULL
            AND grant_plan_sha256 ~ '^[0-9a-f]{64}$'
            AND renewal_of_binding_id IS NULL
            AND renewal_approval_case_ref IS NULL
            AND renewal_plan_sha256 IS NULL
        ) OR (
            approval_case_ref IS NULL
            AND grant_plan_sha256 IS NULL
            AND renewal_of_binding_id IS NOT NULL
            AND renewal_approval_case_ref ~ '^gda://[a-z0-9][a-z0-9._-]{0,63}/approval_case/[a-z0-9][a-z0-9._-]{0,127}$'
            AND split_part(renewal_approval_case_ref, '/', 3) = tenant_id
            AND renewal_plan_sha256 ~ '^[0-9a-f]{64}$'
        )
    );

CREATE UNIQUE INDEX uq_gda_service_consumer_binding_renewal_case
    ON gda_control.service_consumer_binding(tenant_id, renewal_approval_case_ref)
    WHERE renewal_approval_case_ref IS NOT NULL;

CREATE TABLE gda_control.service_consumer_binding_renewal (
    tenant_id TEXT NOT NULL,
    service_consumer_binding_renewal_id UUID NOT NULL,
    source_binding_id UUID NOT NULL,
    source_binding_sha256 CHAR(64) NOT NULL,
    target_binding_id UUID NOT NULL,
    target_binding_sha256 CHAR(64) NOT NULL,
    approval_case_ref TEXT NOT NULL,
    renewal_plan_sha256 CHAR(64) NOT NULL,
    renewed_by TEXT NOT NULL,
    renewed_at TIMESTAMPTZ NOT NULL,
    CONSTRAINT pk_gda_service_consumer_binding_renewal
        PRIMARY KEY (tenant_id, service_consumer_binding_renewal_id),
    CONSTRAINT uq_gda_service_consumer_binding_renewal_source
        UNIQUE (tenant_id, source_binding_id),
    CONSTRAINT uq_gda_service_consumer_binding_renewal_target
        UNIQUE (tenant_id, target_binding_id),
    CONSTRAINT fk_gda_service_consumer_binding_renewal_source
        FOREIGN KEY (tenant_id, source_binding_id)
        REFERENCES gda_control.service_consumer_binding(
            tenant_id, service_consumer_binding_id
        ),
    CONSTRAINT fk_gda_service_consumer_binding_renewal_target
        FOREIGN KEY (tenant_id, target_binding_id)
        REFERENCES gda_control.service_consumer_binding(
            tenant_id, service_consumer_binding_id
        ),
    CONSTRAINT fk_gda_service_consumer_binding_renewal_approval_case
        FOREIGN KEY (tenant_id, approval_case_ref)
        REFERENCES gda_control.approval_case(tenant_id, approval_case_ref),
    CONSTRAINT ck_gda_service_consumer_binding_renewal_hash CHECK (
        source_binding_sha256 ~ '^[0-9a-f]{64}$'
        AND target_binding_sha256 ~ '^[0-9a-f]{64}$'
        AND renewal_plan_sha256 ~ '^[0-9a-f]{64}$'
    ),
    CONSTRAINT ck_gda_service_consumer_binding_renewal_distinct CHECK (
        source_binding_id <> target_binding_id
    ),
    CONSTRAINT ck_gda_service_consumer_binding_renewal_case_ref CHECK (
        approval_case_ref ~ '^gda://[a-z0-9][a-z0-9._-]{0,63}/approval_case/[a-z0-9][a-z0-9._-]{0,127}$'
        AND split_part(approval_case_ref, '/', 3) = tenant_id
    ),
    CONSTRAINT ck_gda_service_consumer_binding_renewal_actor CHECK (
        renewed_by ~ '^human:[^[:space:]]+$' AND length(renewed_by) <= 512
    )
);

CREATE INDEX idx_gda_service_consumer_binding_renewal_target_lookup
    ON gda_control.service_consumer_binding_renewal(
        tenant_id, target_binding_id, renewed_at DESC
    );

CREATE OR REPLACE FUNCTION gda_control.guard_service_consumer_binding_renewal_insert()
RETURNS TRIGGER
LANGUAGE plpgsql
SET search_path = pg_catalog, gda_control
AS $$
BEGIN
    IF COALESCE(
        current_setting('gda.service_consumer_binding_renewal_allowed', true), ''
    ) <> '1' THEN
        RAISE EXCEPTION
            'use gda_control.record_service_consumer_binding_renewal()'
            USING ERRCODE = '55000';
    END IF;
    IF gda_control.current_tenant() IS NULL
       OR NEW.tenant_id IS DISTINCT FROM gda_control.current_tenant() THEN
        RAISE EXCEPTION
            'service consumer binding renewal tenant context is missing or mismatched'
            USING ERRCODE = '42501';
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER trg_gda_service_consumer_binding_renewal_insert
BEFORE INSERT ON gda_control.service_consumer_binding_renewal
FOR EACH ROW EXECUTE FUNCTION
    gda_control.guard_service_consumer_binding_renewal_insert();

CREATE TRIGGER trg_gda_service_consumer_binding_renewal_immutable
BEFORE UPDATE OR DELETE ON gda_control.service_consumer_binding_renewal
FOR EACH ROW EXECUTE FUNCTION gda_control.reject_immutable_mutation();

CREATE FUNCTION gda_control.record_service_consumer_binding_renewal(
    p_tenant_id TEXT,
    p_service_consumer_binding_renewal_id UUID,
    p_source_binding_id UUID,
    p_source_binding_sha256 CHAR(64),
    p_target_binding_id UUID,
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
    p_target_binding_sha256 CHAR(64),
    p_created_by TEXT,
    p_created_at TIMESTAMPTZ,
    p_approval_case_ref TEXT,
    p_renewal_plan_sha256 CHAR(64),
    p_renewed_by TEXT,
    p_renewed_at TIMESTAMPTZ
)
RETURNS TABLE(service_consumer_binding_renewal_id UUID, created BOOLEAN)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, gda_control
SET row_security = on
AS $$
DECLARE
    v_case gda_control.approval_case%ROWTYPE;
    v_source gda_control.service_consumer_binding%ROWTYPE;
    v_target gda_control.service_consumer_binding%ROWTYPE;
    v_existing gda_control.service_consumer_binding_renewal%ROWTYPE;
    v_existing_target gda_control.service_consumer_binding%ROWTYPE;
    v_plan JSONB;
    v_inserted UUID;
    v_expected_case_ref TEXT;
    v_expected_target TEXT;
BEGIN
    IF p_tenant_id IS DISTINCT FROM gda_control.current_tenant() THEN
        RAISE EXCEPTION
            'service consumer binding renewal tenant context is missing or mismatched'
            USING ERRCODE = '42501';
    END IF;
    IF p_source_binding_id = p_target_binding_id THEN
        RAISE EXCEPTION 'service consumer binding renewal source and target must differ'
            USING ERRCODE = '22023';
    END IF;

    v_expected_case_ref := format(
        'gda://%s/approval_case/gis-service-consumer-binding-renew-%s',
        p_tenant_id, replace(p_target_binding_id::TEXT, '-', '')
    );
    v_expected_target := format(
        'gda://%s/service_consumer_binding/%s',
        p_tenant_id, replace(p_target_binding_id::TEXT, '-', '')
    );
    IF p_approval_case_ref IS NULL
       OR p_approval_case_ref <> v_expected_case_ref
       OR p_renewal_plan_sha256 IS NULL
       OR p_renewal_plan_sha256 !~ '^[0-9a-f]{64}$' THEN
        RAISE EXCEPTION
            'service consumer binding renewal requires its deterministic ApprovalCase and plan fingerprint'
            USING ERRCODE = '22023';
    END IF;

    SELECT approval.* INTO v_case
      FROM gda_control.approval_case AS approval
     WHERE approval.tenant_id = p_tenant_id
       AND approval.approval_case_ref = p_approval_case_ref
     FOR SHARE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'service consumer binding renewal ApprovalCase was not found'
            USING ERRCODE = 'P0002';
    END IF;
    IF v_case.status <> 'approved'
       OR clock_timestamp() >= v_case.expires_at
       OR v_case.action <> 'gis_service_consumer_binding.renew'
       OR v_case.target_resource_urn <> v_expected_target
       OR v_case.target_fingerprint <> p_renewal_plan_sha256 THEN
        RAISE EXCEPTION
            'service consumer binding requires a live approved matching renewal ApprovalCase'
            USING ERRCODE = '23514';
    END IF;

    v_plan := v_case.request_context -> 'service_consumer_binding';
    IF v_case.request_context ->> 'schema'
           <> 'gda.gis_service_consumer_binding_renewal.v1'
       OR v_case.request_context ->> 'renewal_plan_sha256'
           <> p_renewal_plan_sha256
       OR v_case.request_context ->> 'source_binding_id'
           <> p_source_binding_id::TEXT
       OR v_case.request_context ->> 'source_binding_sha256'
           <> p_source_binding_sha256::TEXT
       OR v_case.request_context ->> 'service_consumer_binding_renewal_id'
           <> p_service_consumer_binding_renewal_id::TEXT
       OR jsonb_typeof(v_plan) <> 'object'
       OR v_plan ->> 'tenant_id' <> p_tenant_id
       OR v_plan ->> 'service_consumer_binding_id'
           <> p_target_binding_id::TEXT
       OR v_plan ->> 'service_urn' <> p_service_urn
       OR v_plan ->> 'service_definition_version_id'
           <> p_service_definition_version_id::TEXT
       OR v_plan ->> 'service_release_binding_id'
           <> p_service_release_binding_id::TEXT
       OR v_plan ->> 'consumer_ref' <> p_consumer_ref
       OR v_plan ->> 'action' <> p_action
       OR v_plan ->> 'purpose' <> p_purpose
       OR v_plan -> 'scope' IS DISTINCT FROM p_scope
       OR v_plan ->> 'credential_ref' <> p_credential_ref
       OR (v_plan ->> 'expires_at')::TIMESTAMPTZ IS DISTINCT FROM p_expires_at
       OR v_plan ->> 'compatibility_fingerprint'
           <> p_compatibility_fingerprint::TEXT
       OR v_plan -> 'compatibility_evidence'
           IS DISTINCT FROM p_compatibility_evidence
       OR v_plan ->> 'binding_sha256' <> p_target_binding_sha256::TEXT
       OR v_plan ->> 'created_by' <> p_created_by
       OR (v_plan ->> 'created_at')::TIMESTAMPTZ IS DISTINCT FROM p_created_at THEN
        RAISE EXCEPTION
            'renewal ApprovalCase does not authorize this target binding payload'
            USING ERRCODE = '23514';
    END IF;

    SELECT source.* INTO v_source
      FROM gda_control.service_consumer_binding AS source
     WHERE source.tenant_id = p_tenant_id
       AND source.service_consumer_binding_id = p_source_binding_id
     FOR SHARE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'service consumer binding renewal source was not found'
            USING ERRCODE = 'P0002';
    END IF;
    IF v_source.binding_sha256 IS DISTINCT FROM p_source_binding_sha256
       OR v_source.service_urn IS DISTINCT FROM p_service_urn
       OR v_source.service_definition_version_id IS DISTINCT FROM
           p_service_definition_version_id
       OR v_source.service_release_binding_id IS DISTINCT FROM
           p_service_release_binding_id
       OR v_source.consumer_ref IS DISTINCT FROM p_consumer_ref
       OR p_expires_at <= v_source.expires_at
       OR p_created_at <= v_source.created_at THEN
        RAISE EXCEPTION
            'renewal target must extend the same live service release binding'
            USING ERRCODE = '23514';
    END IF;
    IF EXISTS (
        SELECT 1 FROM gda_control.service_consumer_binding_revocation AS revoke
         WHERE revoke.tenant_id = p_tenant_id
           AND revoke.service_consumer_binding_id = p_source_binding_id
    ) THEN
        RAISE EXCEPTION 'a revoked service consumer binding cannot be renewed'
            USING ERRCODE = '23514';
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
        RAISE EXCEPTION 'service consumer binding renewal must target one vector-tile release'
            USING ERRCODE = '23514';
    END IF;

    PERFORM set_config('gda.service_consumer_binding_allowed', '1', true);
    INSERT INTO gda_control.service_consumer_binding (
        tenant_id, service_consumer_binding_id, service_urn,
        service_definition_version_id, service_release_binding_id,
        consumer_ref, action, purpose, scope, credential_ref, expires_at,
        compatibility_fingerprint, compatibility_evidence, binding_sha256,
        created_by, created_at, renewal_of_binding_id,
        renewal_approval_case_ref, renewal_plan_sha256
    ) VALUES (
        p_tenant_id, p_target_binding_id, p_service_urn,
        p_service_definition_version_id, p_service_release_binding_id,
        p_consumer_ref, p_action, p_purpose, p_scope, p_credential_ref,
        p_expires_at, p_compatibility_fingerprint, p_compatibility_evidence,
        p_target_binding_sha256, p_created_by, p_created_at,
        p_source_binding_id, p_approval_case_ref, p_renewal_plan_sha256
    ) ON CONFLICT DO NOTHING
    RETURNING service_consumer_binding_id INTO v_inserted;

    PERFORM set_config('gda.service_consumer_binding_renewal_allowed', '1', true);
    INSERT INTO gda_control.service_consumer_binding_renewal (
        tenant_id, service_consumer_binding_renewal_id, source_binding_id,
        source_binding_sha256, target_binding_id, target_binding_sha256,
        approval_case_ref, renewal_plan_sha256, renewed_by, renewed_at
    ) VALUES (
        p_tenant_id, p_service_consumer_binding_renewal_id, p_source_binding_id,
        p_source_binding_sha256, p_target_binding_id, p_target_binding_sha256,
        p_approval_case_ref, p_renewal_plan_sha256, p_renewed_by, p_renewed_at
    ) ON CONFLICT DO NOTHING;

    SELECT target.* INTO v_target
      FROM gda_control.service_consumer_binding AS target
     WHERE target.tenant_id = p_tenant_id
       AND target.service_consumer_binding_id = p_target_binding_id;
    SELECT renewal.* INTO v_existing
      FROM gda_control.service_consumer_binding_renewal AS renewal
     WHERE renewal.tenant_id = p_tenant_id
       AND (
           renewal.service_consumer_binding_renewal_id =
               p_service_consumer_binding_renewal_id
           OR renewal.source_binding_id = p_source_binding_id
           OR renewal.target_binding_id = p_target_binding_id
           OR renewal.approval_case_ref = p_approval_case_ref
       )
     ORDER BY (
         renewal.service_consumer_binding_renewal_id =
             p_service_consumer_binding_renewal_id
     ) DESC
     LIMIT 1;
    IF NOT FOUND OR v_target.service_consumer_binding_id IS NULL THEN
        RAISE EXCEPTION 'service consumer binding renewal write was not visible'
            USING ERRCODE = '40001';
    END IF;
    IF v_existing.service_consumer_binding_renewal_id IS DISTINCT FROM
           p_service_consumer_binding_renewal_id
       OR v_existing.source_binding_id IS DISTINCT FROM p_source_binding_id
       OR v_existing.source_binding_sha256 IS DISTINCT FROM p_source_binding_sha256
       OR v_existing.target_binding_id IS DISTINCT FROM p_target_binding_id
       OR v_existing.target_binding_sha256 IS DISTINCT FROM p_target_binding_sha256
       OR v_existing.approval_case_ref IS DISTINCT FROM p_approval_case_ref
       OR v_existing.renewal_plan_sha256 IS DISTINCT FROM p_renewal_plan_sha256
       OR v_existing.renewed_by IS DISTINCT FROM p_renewed_by
       OR v_existing.renewed_at IS DISTINCT FROM p_renewed_at THEN
        RAISE EXCEPTION 'ServiceConsumerBinding renewal identity has different content'
            USING ERRCODE = '23505';
    END IF;
    IF v_target.service_consumer_binding_id IS DISTINCT FROM p_target_binding_id
       OR v_target.renewal_of_binding_id IS DISTINCT FROM p_source_binding_id
       OR v_target.renewal_approval_case_ref IS DISTINCT FROM p_approval_case_ref
       OR v_target.renewal_plan_sha256 IS DISTINCT FROM p_renewal_plan_sha256
       OR v_target.binding_sha256 IS DISTINCT FROM p_target_binding_sha256
       OR v_target.expires_at IS DISTINCT FROM p_expires_at
       OR v_target.created_at IS DISTINCT FROM p_created_at THEN
        RAISE EXCEPTION 'ServiceConsumerBinding renewal target has different content'
            USING ERRCODE = '23505';
    END IF;
    RETURN QUERY SELECT p_service_consumer_binding_renewal_id, (v_inserted IS NOT NULL);
END;
$$;

ALTER TABLE gda_control.service_consumer_binding_renewal ENABLE ROW LEVEL SECURITY;
ALTER TABLE gda_control.service_consumer_binding_renewal FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON gda_control.service_consumer_binding_renewal
    USING (tenant_id = gda_control.current_tenant())
    WITH CHECK (tenant_id = gda_control.current_tenant());

REVOKE ALL ON TABLE gda_control.service_consumer_binding_renewal
    FROM PUBLIC, gda_control_gateway;
GRANT SELECT ON TABLE gda_control.service_consumer_binding_renewal
    TO gda_control_gateway;
REVOKE ALL ON FUNCTION gda_control.record_service_consumer_binding_renewal(
    TEXT, UUID, UUID, CHAR(64), UUID, TEXT, UUID, UUID, TEXT, TEXT, TEXT,
    JSONB, TEXT, TIMESTAMPTZ, CHAR(64), JSONB, CHAR(64), TEXT, TIMESTAMPTZ,
    TEXT, CHAR(64), TEXT, TIMESTAMPTZ
) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION gda_control.record_service_consumer_binding_renewal(
    TEXT, UUID, UUID, CHAR(64), UUID, TEXT, UUID, UUID, TEXT, TEXT, TEXT,
    JSONB, TEXT, TIMESTAMPTZ, CHAR(64), JSONB, CHAR(64), TEXT, TIMESTAMPTZ,
    TEXT, CHAR(64), TEXT, TIMESTAMPTZ
) TO gda_control_gateway;
