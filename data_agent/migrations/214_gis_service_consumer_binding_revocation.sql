-- 214: Approval-bound, append-only revocation for GIS service consumer bindings.
--
-- A binding remains immutable.  Revocation is a separate fact so the original
-- grant, its approval and its checksum remain available for audit and replay.

CREATE TABLE gda_control.service_consumer_binding_revocation (
    tenant_id TEXT NOT NULL,
    service_consumer_binding_revocation_id UUID NOT NULL,
    service_consumer_binding_id UUID NOT NULL,
    binding_sha256 CHAR(64) NOT NULL,
    approval_case_ref TEXT NOT NULL,
    revoke_plan_sha256 CHAR(64) NOT NULL,
    reason TEXT NOT NULL,
    context JSONB NOT NULL DEFAULT '{}'::jsonb,
    revoked_by TEXT NOT NULL,
    revoked_at TIMESTAMPTZ NOT NULL,
    CONSTRAINT pk_gda_service_consumer_binding_revocation
        PRIMARY KEY (tenant_id, service_consumer_binding_revocation_id),
    CONSTRAINT uq_gda_service_consumer_binding_revocation_binding
        UNIQUE (tenant_id, service_consumer_binding_id),
    CONSTRAINT fk_gda_service_consumer_binding_revocation_binding
        FOREIGN KEY (tenant_id, service_consumer_binding_id)
        REFERENCES gda_control.service_consumer_binding(
            tenant_id, service_consumer_binding_id
        ),
    CONSTRAINT fk_gda_service_consumer_binding_revocation_case
        FOREIGN KEY (tenant_id, approval_case_ref)
        REFERENCES gda_control.approval_case(tenant_id, approval_case_ref),
    CONSTRAINT ck_gda_service_consumer_binding_revocation_case_ref CHECK (
        approval_case_ref ~ '^gda://[a-z0-9][a-z0-9._-]{0,63}/approval_case/[a-z0-9][a-z0-9._-]{0,127}$'
        AND split_part(approval_case_ref, '/', 3) = tenant_id
    ),
    CONSTRAINT ck_gda_service_consumer_binding_revocation_sha256 CHECK (
        binding_sha256 ~ '^[0-9a-f]{64}$'
        AND revoke_plan_sha256 ~ '^[0-9a-f]{64}$'
    ),
    CONSTRAINT ck_gda_service_consumer_binding_revocation_reason CHECK (
        NULLIF(btrim(reason), '') IS NOT NULL AND length(reason) <= 2048
    ),
    CONSTRAINT ck_gda_service_consumer_binding_revocation_context CHECK (
        jsonb_typeof(context) = 'object'
    ),
    CONSTRAINT ck_gda_service_consumer_binding_revocation_actor CHECK (
        revoked_by ~ '^human:[^[:space:]]+$' AND length(revoked_by) <= 512
    )
);

CREATE INDEX idx_gda_service_consumer_binding_revocation_lookup
    ON gda_control.service_consumer_binding_revocation(
        tenant_id, service_consumer_binding_id, revoked_at DESC
    );

CREATE OR REPLACE FUNCTION gda_control.guard_service_consumer_binding_revocation_insert()
RETURNS TRIGGER
LANGUAGE plpgsql
SET search_path = pg_catalog, gda_control
AS $$
BEGIN
    IF COALESCE(
        current_setting('gda.service_consumer_binding_revocation_allowed', true), ''
    ) <> '1' THEN
        RAISE EXCEPTION
            'use gda_control.record_service_consumer_binding_revocation()'
            USING ERRCODE = '55000';
    END IF;
    IF gda_control.current_tenant() IS NULL
       OR NEW.tenant_id IS DISTINCT FROM gda_control.current_tenant() THEN
        RAISE EXCEPTION
            'service consumer binding revocation tenant context is missing or mismatched'
            USING ERRCODE = '42501';
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER trg_gda_service_consumer_binding_revocation_insert
BEFORE INSERT ON gda_control.service_consumer_binding_revocation
FOR EACH ROW EXECUTE FUNCTION
    gda_control.guard_service_consumer_binding_revocation_insert();

CREATE TRIGGER trg_gda_service_consumer_binding_revocation_immutable
BEFORE UPDATE OR DELETE ON gda_control.service_consumer_binding_revocation
FOR EACH ROW EXECUTE FUNCTION gda_control.reject_immutable_mutation();

CREATE FUNCTION gda_control.record_service_consumer_binding_revocation(
    p_tenant_id TEXT,
    p_service_consumer_binding_revocation_id UUID,
    p_service_consumer_binding_id UUID,
    p_binding_sha256 CHAR(64),
    p_approval_case_ref TEXT,
    p_revoke_plan_sha256 CHAR(64),
    p_reason TEXT,
    p_revoked_by TEXT,
    p_revoked_at TIMESTAMPTZ
)
RETURNS TABLE(service_consumer_binding_revocation_id UUID, created BOOLEAN)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, gda_control
SET row_security = on
AS $$
DECLARE
    v_case gda_control.approval_case%ROWTYPE;
    v_binding gda_control.service_consumer_binding%ROWTYPE;
    v_existing gda_control.service_consumer_binding_revocation%ROWTYPE;
    v_context JSONB;
    v_inserted UUID;
    v_expected_case_ref TEXT;
    v_expected_target TEXT;
BEGIN
    IF p_tenant_id IS DISTINCT FROM gda_control.current_tenant() THEN
        RAISE EXCEPTION
            'service consumer binding revocation tenant context is missing or mismatched'
            USING ERRCODE = '42501';
    END IF;

    v_expected_case_ref := format(
        'gda://%s/approval_case/gis-service-consumer-binding-revoke-%s',
        p_tenant_id, replace(p_service_consumer_binding_id::TEXT, '-', '')
    );
    v_expected_target := format(
        'gda://%s/service_consumer_binding/%s',
        p_tenant_id, replace(p_service_consumer_binding_id::TEXT, '-', '')
    );
    IF p_approval_case_ref IS NULL
       OR p_approval_case_ref <> v_expected_case_ref
       OR p_revoke_plan_sha256 IS NULL
       OR p_revoke_plan_sha256 !~ '^[0-9a-f]{64}$' THEN
        RAISE EXCEPTION
            'service consumer binding revoke requires its deterministic ApprovalCase and plan fingerprint'
            USING ERRCODE = '22023';
    END IF;

    SELECT approval.* INTO v_case
      FROM gda_control.approval_case AS approval
     WHERE approval.tenant_id = p_tenant_id
       AND approval.approval_case_ref = p_approval_case_ref
     FOR SHARE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'service consumer binding revoke ApprovalCase was not found'
            USING ERRCODE = 'P0002';
    END IF;
    IF v_case.status <> 'approved'
       OR clock_timestamp() >= v_case.expires_at
       OR v_case.action <> 'gis_service_consumer_binding.revoke'
       OR v_case.target_resource_urn <> v_expected_target
       OR v_case.target_fingerprint <> p_revoke_plan_sha256 THEN
        RAISE EXCEPTION
            'service consumer binding requires a live approved matching revoke ApprovalCase'
            USING ERRCODE = '23514';
    END IF;

    v_context := v_case.request_context;
    IF v_context ->> 'schema'
           <> 'gda.gis_service_consumer_binding_revocation.v1'
       OR v_context ->> 'revoke_plan_sha256' <> p_revoke_plan_sha256
       OR v_context ->> 'service_consumer_binding_id'
           <> p_service_consumer_binding_id::TEXT
       OR v_context ->> 'binding_sha256' <> p_binding_sha256::TEXT
       OR v_context ->> 'service_consumer_binding_revocation_id'
           <> p_service_consumer_binding_revocation_id::TEXT
       OR v_context ->> 'reason' <> p_reason
       OR v_context ->> 'service_urn' IS NULL
       OR v_context ->> 'service_release_binding_id' IS NULL
       OR v_context ->> 'consumer_ref' IS NULL
       OR v_context -> 'context' IS NULL THEN
        RAISE EXCEPTION
            'revoke ApprovalCase does not authorize this revocation payload'
            USING ERRCODE = '23514';
    END IF;

    SELECT binding.* INTO v_binding
      FROM gda_control.service_consumer_binding AS binding
     WHERE binding.tenant_id = p_tenant_id
       AND binding.service_consumer_binding_id = p_service_consumer_binding_id
     FOR SHARE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'service consumer binding to revoke was not found'
            USING ERRCODE = 'P0002';
    END IF;
    IF v_binding.binding_sha256 IS DISTINCT FROM p_binding_sha256
       OR v_binding.service_urn IS DISTINCT FROM (v_context ->> 'service_urn')
       OR v_binding.service_release_binding_id::TEXT IS DISTINCT FROM
           (v_context ->> 'service_release_binding_id')
       OR v_binding.consumer_ref IS DISTINCT FROM (v_context ->> 'consumer_ref') THEN
        RAISE EXCEPTION
            'revoke ApprovalCase does not match the current immutable binding'
            USING ERRCODE = '23514';
    END IF;
    IF v_case.decided_by IS DISTINCT FROM p_revoked_by
       OR p_revoked_by !~ '^human:[^[:space:]]+$'
       OR p_revoked_at IS NULL
       OR p_revoked_at > clock_timestamp() THEN
        RAISE EXCEPTION
            'revocation actor and timestamp must match the approved human decision'
            USING ERRCODE = '23514';
    END IF;

    PERFORM set_config('gda.service_consumer_binding_revocation_allowed', '1', true);
    INSERT INTO gda_control.service_consumer_binding_revocation (
        tenant_id, service_consumer_binding_revocation_id,
        service_consumer_binding_id, binding_sha256, approval_case_ref,
        revoke_plan_sha256, reason, context, revoked_by, revoked_at
    ) VALUES (
        p_tenant_id, p_service_consumer_binding_revocation_id,
        p_service_consumer_binding_id, p_binding_sha256, p_approval_case_ref,
        p_revoke_plan_sha256, p_reason, v_context -> 'context', p_revoked_by,
        p_revoked_at
    ) ON CONFLICT DO NOTHING
    RETURNING gda_control.service_consumer_binding_revocation
        .service_consumer_binding_revocation_id INTO v_inserted;

    SELECT revocation.* INTO v_existing
      FROM gda_control.service_consumer_binding_revocation AS revocation
     WHERE revocation.tenant_id = p_tenant_id
       AND (
           revocation.service_consumer_binding_revocation_id =
               p_service_consumer_binding_revocation_id
           OR revocation.service_consumer_binding_id = p_service_consumer_binding_id
           OR revocation.approval_case_ref = p_approval_case_ref
       )
     ORDER BY (
         revocation.service_consumer_binding_revocation_id =
             p_service_consumer_binding_revocation_id
     ) DESC
     LIMIT 1;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'service consumer binding revocation write was not visible'
            USING ERRCODE = '40001';
    END IF;
    IF v_existing.service_consumer_binding_revocation_id IS DISTINCT FROM
           p_service_consumer_binding_revocation_id
       OR v_existing.service_consumer_binding_id IS DISTINCT FROM
           p_service_consumer_binding_id
       OR v_existing.binding_sha256 IS DISTINCT FROM p_binding_sha256
       OR v_existing.approval_case_ref IS DISTINCT FROM p_approval_case_ref
       OR v_existing.revoke_plan_sha256 IS DISTINCT FROM p_revoke_plan_sha256
       OR v_existing.reason IS DISTINCT FROM p_reason
       OR v_existing.context IS DISTINCT FROM (v_context -> 'context')
       OR v_existing.revoked_by IS DISTINCT FROM p_revoked_by
       OR v_existing.revoked_at IS DISTINCT FROM p_revoked_at THEN
        RAISE EXCEPTION
            'ServiceConsumerBinding revocation identity already has different content'
            USING ERRCODE = '23505';
    END IF;
    RETURN QUERY SELECT v_existing.service_consumer_binding_revocation_id,
        (v_inserted IS NOT NULL);
END;
$$;

ALTER TABLE gda_control.service_consumer_binding_revocation ENABLE ROW LEVEL SECURITY;
ALTER TABLE gda_control.service_consumer_binding_revocation FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation
    ON gda_control.service_consumer_binding_revocation
    USING (tenant_id = gda_control.current_tenant())
    WITH CHECK (tenant_id = gda_control.current_tenant());

REVOKE ALL ON TABLE gda_control.service_consumer_binding_revocation
    FROM PUBLIC, gda_control_gateway;
GRANT SELECT ON TABLE gda_control.service_consumer_binding_revocation
    TO gda_control_gateway;
REVOKE ALL ON FUNCTION gda_control.record_service_consumer_binding_revocation(
    TEXT, UUID, UUID, CHAR(64), TEXT, CHAR(64), TEXT, TEXT, TIMESTAMPTZ
) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION gda_control.record_service_consumer_binding_revocation(
    TEXT, UUID, UUID, CHAR(64), TEXT, CHAR(64), TEXT, TEXT, TIMESTAMPTZ
) TO gda_control_gateway;
