-- 220: Require fresh, Run-bound cache warmup evidence for migration activation.
--
-- A warmup receipt binds one successful PlatformRun and evidence Artifact to
-- an immutable endpoint, deployment, release and cache namespace.  The 218
-- cutover and 219 rollback markers activate a pointer trigger that requires a
-- still-live receipt for their destination endpoint.

CREATE TABLE gda_control.gis_service_endpoint_warmup (
    tenant_id TEXT NOT NULL,
    warmup_id UUID NOT NULL,
    service_urn TEXT NOT NULL,
    endpoint_revision_id UUID NOT NULL,
    deployment_revision_id UUID NOT NULL,
    service_definition_version_id UUID NOT NULL,
    service_release_binding_id UUID NOT NULL,
    cache_policy_version_id UUID NOT NULL,
    cache_namespace TEXT NOT NULL,
    run_id UUID NOT NULL,
    evidence_artifact_id UUID NOT NULL,
    requested_sample_count INTEGER NOT NULL,
    successful_sample_count INTEGER NOT NULL,
    sample_set_sha256 CHAR(64) NOT NULL,
    provider_receipt_sha256 CHAR(64) NOT NULL,
    started_at TIMESTAMPTZ NOT NULL,
    completed_at TIMESTAMPTZ NOT NULL,
    valid_until TIMESTAMPTZ NOT NULL,
    recorded_by TEXT NOT NULL,
    recorded_at TIMESTAMPTZ NOT NULL,
    warmup_sha256 CHAR(64) NOT NULL,
    CONSTRAINT pk_gda_gis_service_endpoint_warmup
        PRIMARY KEY (tenant_id, warmup_id),
    CONSTRAINT uq_gda_gis_service_endpoint_warmup_id UNIQUE (warmup_id),
    CONSTRAINT uq_gda_gis_service_endpoint_warmup_run
        UNIQUE (tenant_id, run_id),
    CONSTRAINT uq_gda_gis_service_endpoint_warmup_artifact
        UNIQUE (tenant_id, evidence_artifact_id),
    CONSTRAINT uq_gda_gis_service_endpoint_warmup_sha
        UNIQUE (tenant_id, warmup_sha256),
    CONSTRAINT fk_gda_gis_service_endpoint_warmup_service
        FOREIGN KEY (tenant_id, service_urn)
        REFERENCES gda_control.gis_service(tenant_id, service_urn),
    CONSTRAINT fk_gda_gis_service_endpoint_warmup_endpoint
        FOREIGN KEY (tenant_id, service_urn, endpoint_revision_id)
        REFERENCES gda_control.endpoint_revision(
            tenant_id, service_urn, endpoint_revision_id
        ),
    CONSTRAINT fk_gda_gis_service_endpoint_warmup_deployment
        FOREIGN KEY (
            tenant_id, service_definition_version_id,
            deployment_revision_id
        ) REFERENCES gda_control.service_deployment_revision(
            tenant_id, service_definition_version_id,
            deployment_revision_id
        ),
    CONSTRAINT fk_gda_gis_service_endpoint_warmup_release
        FOREIGN KEY (
            tenant_id, service_definition_version_id,
            service_release_binding_id
        ) REFERENCES gda_control.service_release_binding(
            tenant_id, service_definition_version_id,
            service_release_binding_id
        ),
    CONSTRAINT fk_gda_gis_service_endpoint_warmup_cache
        FOREIGN KEY (
            tenant_id, service_definition_version_id,
            cache_policy_version_id
        ) REFERENCES gda_control.cache_policy_version(
            tenant_id, service_definition_version_id,
            cache_policy_version_id
        ),
    CONSTRAINT fk_gda_gis_service_endpoint_warmup_run
        FOREIGN KEY (tenant_id, run_id)
        REFERENCES gda_control.platform_run(tenant_id, run_id),
    CONSTRAINT fk_gda_gis_service_endpoint_warmup_artifact
        FOREIGN KEY (tenant_id, evidence_artifact_id)
        REFERENCES gda_control.artifact(tenant_id, artifact_id),
    CONSTRAINT ck_gda_gis_service_endpoint_warmup_service CHECK (
        service_urn ~ '^gda://[a-z0-9][a-z0-9._-]{0,63}/gis_service/[a-z0-9][a-z0-9._-]{0,127}$'
        AND split_part(service_urn, '/', 3) = tenant_id
    ),
    CONSTRAINT ck_gda_gis_service_endpoint_warmup_cache_namespace CHECK (
        cache_namespace ~ '^[a-z0-9][a-z0-9._-]{0,127}$'
    ),
    CONSTRAINT ck_gda_gis_service_endpoint_warmup_samples CHECK (
        requested_sample_count > 0
        AND successful_sample_count = requested_sample_count
    ),
    CONSTRAINT ck_gda_gis_service_endpoint_warmup_window CHECK (
        started_at <= completed_at
        AND completed_at < valid_until
        AND completed_at <= recorded_at
        AND recorded_at < valid_until
    ),
    CONSTRAINT ck_gda_gis_service_endpoint_warmup_actor CHECK (
        recorded_by ~ '^workload:[^[:space:]]+$'
    ),
    CONSTRAINT ck_gda_gis_service_endpoint_warmup_hash CHECK (
        sample_set_sha256 ~ '^[0-9a-f]{64}$'
        AND provider_receipt_sha256 ~ '^[0-9a-f]{64}$'
        AND warmup_sha256 ~ '^[0-9a-f]{64}$'
    )
);

CREATE INDEX idx_gda_gis_service_endpoint_warmup_live
    ON gda_control.gis_service_endpoint_warmup(
        tenant_id, service_urn, endpoint_revision_id,
        valid_until DESC, completed_at DESC
    );

CREATE OR REPLACE FUNCTION gda_control.gis_service_endpoint_warmup_fingerprint(
    p_tenant_id TEXT,
    p_warmup_id UUID,
    p_service_urn TEXT,
    p_endpoint_revision_id UUID,
    p_deployment_revision_id UUID,
    p_service_definition_version_id UUID,
    p_service_release_binding_id UUID,
    p_cache_policy_version_id UUID,
    p_cache_namespace TEXT,
    p_run_id UUID,
    p_evidence_artifact_id UUID,
    p_requested_sample_count INTEGER,
    p_successful_sample_count INTEGER,
    p_sample_set_sha256 TEXT,
    p_provider_receipt_sha256 TEXT,
    p_started_at TIMESTAMPTZ,
    p_completed_at TIMESTAMPTZ,
    p_valid_until TIMESTAMPTZ,
    p_recorded_by TEXT,
    p_recorded_at TIMESTAMPTZ
)
RETURNS TEXT
LANGUAGE sql
IMMUTABLE
SET search_path = pg_catalog, public
AS $$
    WITH payload AS (
        SELECT jsonb_build_object(
            'cache_namespace', p_cache_namespace,
            'cache_policy_version_id', p_cache_policy_version_id::text,
            'completed_at', to_char(
                p_completed_at AT TIME ZONE 'UTC',
                'YYYY-MM-DD"T"HH24:MI:SS.US'
            ) || '+00:00',
            'deployment_revision_id', p_deployment_revision_id::text,
            'endpoint_revision_id', p_endpoint_revision_id::text,
            'evidence_artifact_id', p_evidence_artifact_id::text,
            'provider_receipt_sha256', p_provider_receipt_sha256,
            'recorded_at', to_char(
                p_recorded_at AT TIME ZONE 'UTC',
                'YYYY-MM-DD"T"HH24:MI:SS.US'
            ) || '+00:00',
            'recorded_by', p_recorded_by,
            'requested_sample_count', p_requested_sample_count,
            'run_id', p_run_id::text,
            'sample_set_sha256', p_sample_set_sha256,
            'schema', 'gda.gis_service_endpoint_warmup.v1',
            'service_definition_version_id',
                p_service_definition_version_id::text,
            'service_release_binding_id',
                p_service_release_binding_id::text,
            'service_urn', p_service_urn,
            'started_at', to_char(
                p_started_at AT TIME ZONE 'UTC',
                'YYYY-MM-DD"T"HH24:MI:SS.US'
            ) || '+00:00',
            'successful_sample_count', p_successful_sample_count,
            'tenant_id', p_tenant_id,
            'valid_until', to_char(
                p_valid_until AT TIME ZONE 'UTC',
                'YYYY-MM-DD"T"HH24:MI:SS.US'
            ) || '+00:00',
            'warmup_id', p_warmup_id::text
        ) AS object
    )
    SELECT encode(
        public.digest(
            convert_to(
                '{' || (
                    SELECT string_agg(
                        to_jsonb(key)::text || ':' || value::text,
                        ',' ORDER BY key
                    ) FROM jsonb_each(payload.object)
                ) || '}',
                'UTF8'
            ),
            'sha256'
        ),
        'hex'
    ) FROM payload
$$;

CREATE OR REPLACE FUNCTION gda_control.guard_gis_service_endpoint_warmup_insert()
RETURNS TRIGGER
LANGUAGE plpgsql
SET search_path = pg_catalog, gda_control
AS $$
BEGIN
    IF COALESCE(
        current_setting('gda.gis_service_endpoint_warmup_insert_allowed', true),
        ''
    ) <> NEW.warmup_id::text THEN
        RAISE EXCEPTION 'use gda_control.record_gis_service_endpoint_warmup()'
            USING ERRCODE = '55000';
    END IF;
    IF gda_control.current_tenant() IS NULL
       OR NEW.tenant_id IS DISTINCT FROM gda_control.current_tenant() THEN
        RAISE EXCEPTION 'GIS endpoint warmup tenant context is missing or mismatched'
            USING ERRCODE = '42501';
    END IF;
    IF NEW.warmup_sha256 IS DISTINCT FROM
       gda_control.gis_service_endpoint_warmup_fingerprint(
           NEW.tenant_id, NEW.warmup_id, NEW.service_urn,
           NEW.endpoint_revision_id, NEW.deployment_revision_id,
           NEW.service_definition_version_id,
           NEW.service_release_binding_id, NEW.cache_policy_version_id,
           NEW.cache_namespace, NEW.run_id, NEW.evidence_artifact_id,
           NEW.requested_sample_count, NEW.successful_sample_count,
           NEW.sample_set_sha256, NEW.provider_receipt_sha256,
           NEW.started_at, NEW.completed_at, NEW.valid_until,
           NEW.recorded_by, NEW.recorded_at
       ) THEN
        RAISE EXCEPTION 'GIS endpoint warmup fingerprint mismatch'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER trg_gda_gis_service_endpoint_warmup_insert
BEFORE INSERT ON gda_control.gis_service_endpoint_warmup
FOR EACH ROW EXECUTE FUNCTION
    gda_control.guard_gis_service_endpoint_warmup_insert();

CREATE TRIGGER trg_gda_gis_service_endpoint_warmup_immutable
BEFORE UPDATE OR DELETE ON gda_control.gis_service_endpoint_warmup
FOR EACH ROW EXECUTE FUNCTION gda_control.reject_immutable_mutation();

CREATE FUNCTION gda_control.record_gis_service_endpoint_warmup(
    p_tenant_id TEXT,
    p_warmup_id UUID,
    p_service_urn TEXT,
    p_endpoint_revision_id UUID,
    p_deployment_revision_id UUID,
    p_service_definition_version_id UUID,
    p_service_release_binding_id UUID,
    p_cache_policy_version_id UUID,
    p_cache_namespace TEXT,
    p_run_id UUID,
    p_evidence_artifact_id UUID,
    p_requested_sample_count INTEGER,
    p_successful_sample_count INTEGER,
    p_sample_set_sha256 TEXT,
    p_provider_receipt_sha256 TEXT,
    p_started_at TIMESTAMPTZ,
    p_completed_at TIMESTAMPTZ,
    p_valid_until TIMESTAMPTZ,
    p_recorded_by TEXT,
    p_recorded_at TIMESTAMPTZ,
    p_warmup_sha256 TEXT
)
RETURNS TABLE(warmup_id UUID, created BOOLEAN)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, gda_control
SET row_security = on
AS $$
DECLARE
    v_existing gda_control.gis_service_endpoint_warmup%ROWTYPE;
    v_endpoint gda_control.endpoint_revision%ROWTYPE;
    v_deployment gda_control.service_deployment_revision%ROWTYPE;
    v_release gda_control.service_release_binding%ROWTYPE;
    v_cache gda_control.cache_policy_version%ROWTYPE;
    v_run gda_control.platform_run%ROWTYPE;
    v_artifact gda_control.artifact%ROWTYPE;
    v_definition_capability TEXT;
    v_product_output_id UUID;
    v_success_details JSONB;
    v_now TIMESTAMPTZ;
    v_inserted UUID;
BEGIN
    IF p_tenant_id IS DISTINCT FROM gda_control.current_tenant() THEN
        RAISE EXCEPTION 'GIS endpoint warmup tenant context is missing or mismatched'
            USING ERRCODE = '42501';
    END IF;
    IF p_recorded_by !~ '^workload:[^[:space:]]+$'
       OR p_requested_sample_count <= 0
       OR p_successful_sample_count <> p_requested_sample_count
       OR p_started_at > p_completed_at
       OR p_completed_at >= p_valid_until
       OR p_completed_at > p_recorded_at
       OR p_recorded_at >= p_valid_until THEN
        RAISE EXCEPTION 'GIS endpoint warmup evidence is incomplete'
            USING ERRCODE = '22023';
    END IF;
    IF gda_control.gis_service_endpoint_warmup_fingerprint(
        p_tenant_id, p_warmup_id, p_service_urn,
        p_endpoint_revision_id, p_deployment_revision_id,
        p_service_definition_version_id, p_service_release_binding_id,
        p_cache_policy_version_id, p_cache_namespace, p_run_id,
        p_evidence_artifact_id, p_requested_sample_count,
        p_successful_sample_count, p_sample_set_sha256,
        p_provider_receipt_sha256, p_started_at, p_completed_at,
        p_valid_until, p_recorded_by, p_recorded_at
    ) IS DISTINCT FROM p_warmup_sha256 THEN
        RAISE EXCEPTION 'GIS endpoint warmup fingerprint does not match payload'
            USING ERRCODE = '23514';
    END IF;

    PERFORM pg_advisory_xact_lock(
        hashtextextended(
            'gis-service-migration:' || p_tenant_id || ':' || p_service_urn,
            0
        )
    );
    v_now := clock_timestamp();

    SELECT receipt.* INTO v_existing
      FROM gda_control.gis_service_endpoint_warmup AS receipt
     WHERE receipt.tenant_id = p_tenant_id
       AND (
           receipt.warmup_id = p_warmup_id
           OR receipt.run_id = p_run_id
           OR receipt.evidence_artifact_id = p_evidence_artifact_id
       )
     ORDER BY (receipt.warmup_id = p_warmup_id) DESC
     LIMIT 1;
    IF FOUND THEN
        IF v_existing.warmup_id IS DISTINCT FROM p_warmup_id
           OR v_existing.service_urn IS DISTINCT FROM p_service_urn
           OR v_existing.endpoint_revision_id IS DISTINCT FROM
               p_endpoint_revision_id
           OR v_existing.deployment_revision_id IS DISTINCT FROM
               p_deployment_revision_id
           OR v_existing.service_definition_version_id IS DISTINCT FROM
               p_service_definition_version_id
           OR v_existing.service_release_binding_id IS DISTINCT FROM
               p_service_release_binding_id
           OR v_existing.cache_policy_version_id IS DISTINCT FROM
               p_cache_policy_version_id
           OR v_existing.cache_namespace IS DISTINCT FROM p_cache_namespace
           OR v_existing.run_id IS DISTINCT FROM p_run_id
           OR v_existing.evidence_artifact_id IS DISTINCT FROM
               p_evidence_artifact_id
           OR v_existing.requested_sample_count IS DISTINCT FROM
               p_requested_sample_count
           OR v_existing.successful_sample_count IS DISTINCT FROM
               p_successful_sample_count
           OR v_existing.sample_set_sha256 IS DISTINCT FROM p_sample_set_sha256
           OR v_existing.provider_receipt_sha256 IS DISTINCT FROM
               p_provider_receipt_sha256
           OR v_existing.started_at IS DISTINCT FROM p_started_at
           OR v_existing.completed_at IS DISTINCT FROM p_completed_at
           OR v_existing.valid_until IS DISTINCT FROM p_valid_until
           OR v_existing.recorded_by IS DISTINCT FROM p_recorded_by
           OR v_existing.recorded_at IS DISTINCT FROM p_recorded_at
           OR v_existing.warmup_sha256 IS DISTINCT FROM p_warmup_sha256 THEN
            RAISE EXCEPTION 'GIS endpoint warmup identity has different content'
                USING ERRCODE = '23505';
        END IF;
        RETURN QUERY SELECT v_existing.warmup_id, FALSE;
        RETURN;
    END IF;

    SELECT endpoint.* INTO v_endpoint
      FROM gda_control.endpoint_revision AS endpoint
     WHERE endpoint.tenant_id = p_tenant_id
       AND endpoint.service_urn = p_service_urn
       AND endpoint.endpoint_revision_id = p_endpoint_revision_id
     FOR SHARE;
    IF NOT FOUND
       OR v_endpoint.deployment_revision_id IS DISTINCT FROM
           p_deployment_revision_id THEN
        RAISE EXCEPTION 'GIS endpoint warmup endpoint lineage mismatch'
            USING ERRCODE = '23514';
    END IF;

    SELECT deployment.* INTO v_deployment
      FROM gda_control.service_deployment_revision AS deployment
     WHERE deployment.tenant_id = p_tenant_id
       AND deployment.deployment_revision_id = p_deployment_revision_id
     FOR SHARE;
    IF NOT FOUND
       OR v_deployment.service_definition_version_id IS DISTINCT FROM
           p_service_definition_version_id
       OR v_deployment.service_release_binding_id IS DISTINCT FROM
           p_service_release_binding_id
       OR v_deployment.state <> 'ready'
       OR v_deployment.terminal_at > p_started_at THEN
        RAISE EXCEPTION 'GIS endpoint warmup requires its exact ready deployment'
            USING ERRCODE = '23514';
    END IF;

    SELECT release.* INTO v_release
      FROM gda_control.service_release_binding AS release
     WHERE release.tenant_id = p_tenant_id
       AND release.service_definition_version_id =
           p_service_definition_version_id
       AND release.service_release_binding_id = p_service_release_binding_id
     FOR SHARE;
    IF NOT FOUND
       OR v_release.cache_policy_version_id IS DISTINCT FROM
           p_cache_policy_version_id THEN
        RAISE EXCEPTION 'GIS endpoint warmup release/cache binding mismatch'
            USING ERRCODE = '23514';
    END IF;

    SELECT cache.* INTO v_cache
      FROM gda_control.cache_policy_version AS cache
     WHERE cache.tenant_id = p_tenant_id
       AND cache.service_definition_version_id =
           p_service_definition_version_id
       AND cache.cache_policy_version_id = p_cache_policy_version_id
     FOR SHARE;
    IF NOT FOUND
       OR v_cache.cache_namespace IS DISTINCT FROM p_cache_namespace
       OR p_valid_until > p_completed_at +
           make_interval(secs => v_cache.cache_max_age_seconds) THEN
        RAISE EXCEPTION 'GIS endpoint warmup exceeds its exact cache policy'
            USING ERRCODE = '23514';
    END IF;

    SELECT run.* INTO v_run
      FROM gda_control.platform_run AS run
     WHERE run.tenant_id = p_tenant_id AND run.run_id = p_run_id
     FOR SHARE;
    IF NOT FOUND OR v_run.status <> 'succeeded'
       OR v_run.subject_context->>'purpose' IS DISTINCT FROM
           'gis_service.endpoint_warmup'
       OR v_run.submitted_at > p_started_at
       OR v_run.terminal_at < p_completed_at
       OR v_run.terminal_at > p_recorded_at THEN
        RAISE EXCEPTION 'GIS endpoint warmup requires its successful PlatformRun'
            USING ERRCODE = '23514';
    END IF;
    SELECT definition.capability_id INTO v_definition_capability
      FROM gda_control.platform_definition_version AS definition
     WHERE definition.tenant_id = p_tenant_id
       AND definition.definition_version_id = v_run.definition_version_id;
    IF v_definition_capability IS DISTINCT FROM
       'gis-service-endpoint-warmup' THEN
        RAISE EXCEPTION 'PlatformRun is not a GIS endpoint warmup capability'
            USING ERRCODE = '23514';
    END IF;
    SELECT product.output_resource_version_id INTO v_product_output_id
      FROM gda_control.gis_service_definition_version AS definition
      JOIN gda_control.data_product_version AS product
        ON product.tenant_id = definition.tenant_id
       AND product.product_urn = definition.source_product_urn
       AND product.data_product_version_id =
           definition.source_data_product_version_id
     WHERE definition.tenant_id = p_tenant_id
       AND definition.service_definition_version_id =
           p_service_definition_version_id;
    PERFORM 1
      FROM gda_control.platform_run_input_binding AS input
     WHERE input.tenant_id = p_tenant_id
       AND input.run_id = p_run_id
       AND input.resource_version_id = v_product_output_id
       AND input.semantic_type = 'gda.gis_service.warmup_source';
    IF NOT FOUND THEN
        RAISE EXCEPTION 'warmup Run does not bind the product output version'
            USING ERRCODE = '23514';
    END IF;
    SELECT event.details INTO v_success_details
      FROM gda_control.platform_run_event AS event
     WHERE event.tenant_id = p_tenant_id
       AND event.run_id = p_run_id
       AND event.sequence_no = v_run.state_version
       AND event.to_status = 'succeeded';
    IF NOT FOUND OR v_success_details->>'schema' IS DISTINCT FROM
       'gda.run_success_evidence.v1' THEN
        RAISE EXCEPTION 'warmup Run lacks evidence-gated success'
            USING ERRCODE = '23514';
    END IF;

    SELECT artifact.* INTO v_artifact
      FROM gda_control.artifact AS artifact
     WHERE artifact.tenant_id = p_tenant_id
       AND artifact.artifact_id = p_evidence_artifact_id
     FOR SHARE;
    IF NOT FOUND
       OR v_artifact.run_id IS DISTINCT FROM p_run_id
       OR v_artifact.artifact_role <> 'evidence'
       OR v_artifact.content_sha256 IS DISTINCT FROM p_provider_receipt_sha256
       OR v_artifact.created_by IS DISTINCT FROM p_recorded_by
       OR v_artifact.created_at < p_completed_at
       OR v_artifact.created_at > v_run.terminal_at
       OR v_artifact.manifest->>'schema' IS DISTINCT FROM
           'gda.gis_service_endpoint_warmup_receipt.v1'
       OR v_artifact.manifest->>'warmup_id' IS DISTINCT FROM
           p_warmup_id::text
       OR v_artifact.manifest->>'service_urn' IS DISTINCT FROM p_service_urn
       OR v_artifact.manifest->>'endpoint_revision_id' IS DISTINCT FROM
           p_endpoint_revision_id::text
       OR v_artifact.manifest->>'deployment_revision_id' IS DISTINCT FROM
           p_deployment_revision_id::text
       OR v_artifact.manifest->>'service_definition_version_id' IS DISTINCT FROM
           p_service_definition_version_id::text
       OR v_artifact.manifest->>'service_release_binding_id' IS DISTINCT FROM
           p_service_release_binding_id::text
       OR v_artifact.manifest->>'cache_policy_version_id' IS DISTINCT FROM
           p_cache_policy_version_id::text
       OR v_artifact.manifest->>'cache_namespace' IS DISTINCT FROM
           p_cache_namespace
       OR v_artifact.manifest->>'requested_sample_count' IS DISTINCT FROM
           p_requested_sample_count::text
       OR v_artifact.manifest->>'successful_sample_count' IS DISTINCT FROM
           p_successful_sample_count::text
       OR v_artifact.manifest->>'sample_set_sha256' IS DISTINCT FROM
           p_sample_set_sha256
       OR v_artifact.manifest->>'provider_receipt_sha256' IS DISTINCT FROM
           p_provider_receipt_sha256
       OR v_artifact.manifest->>'started_at' IS DISTINCT FROM to_char(
           p_started_at AT TIME ZONE 'UTC',
           'YYYY-MM-DD"T"HH24:MI:SS.US'
       ) || '+00:00'
       OR v_artifact.manifest->>'completed_at' IS DISTINCT FROM to_char(
           p_completed_at AT TIME ZONE 'UTC',
           'YYYY-MM-DD"T"HH24:MI:SS.US'
       ) || '+00:00'
       OR v_artifact.manifest->>'valid_until' IS DISTINCT FROM to_char(
           p_valid_until AT TIME ZONE 'UTC',
           'YYYY-MM-DD"T"HH24:MI:SS.US'
       ) || '+00:00' THEN
        RAISE EXCEPTION 'warmup evidence Artifact does not bind this receipt'
            USING ERRCODE = '23514';
    END IF;
    IF p_recorded_at > v_now OR p_valid_until <= v_now THEN
        RAISE EXCEPTION 'GIS endpoint warmup receipt is not currently live'
            USING ERRCODE = '23514';
    END IF;

    PERFORM set_config(
        'gda.gis_service_endpoint_warmup_insert_allowed',
        p_warmup_id::text, true
    );
    INSERT INTO gda_control.gis_service_endpoint_warmup (
        tenant_id, warmup_id, service_urn, endpoint_revision_id,
        deployment_revision_id, service_definition_version_id,
        service_release_binding_id, cache_policy_version_id,
        cache_namespace, run_id, evidence_artifact_id,
        requested_sample_count, successful_sample_count,
        sample_set_sha256, provider_receipt_sha256, started_at,
        completed_at, valid_until, recorded_by, recorded_at, warmup_sha256
    ) VALUES (
        p_tenant_id, p_warmup_id, p_service_urn, p_endpoint_revision_id,
        p_deployment_revision_id, p_service_definition_version_id,
        p_service_release_binding_id, p_cache_policy_version_id,
        p_cache_namespace, p_run_id, p_evidence_artifact_id,
        p_requested_sample_count, p_successful_sample_count,
        p_sample_set_sha256, p_provider_receipt_sha256, p_started_at,
        p_completed_at, p_valid_until, p_recorded_by, p_recorded_at,
        p_warmup_sha256
    ) RETURNING gis_service_endpoint_warmup.warmup_id INTO v_inserted;
    PERFORM set_config(
        'gda.gis_service_endpoint_warmup_insert_allowed', '', true
    );
    RETURN QUERY SELECT v_inserted, TRUE;
END;
$$;

CREATE OR REPLACE FUNCTION
gda_control.guard_gis_service_migration_destination_warmup()
RETURNS TRIGGER
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, gda_control
SET row_security = on
AS $$
DECLARE
    v_now TIMESTAMPTZ;
BEGIN
    IF OLD.active_endpoint_revision_id IS NOT DISTINCT FROM
       NEW.active_endpoint_revision_id
       OR (
           COALESCE(current_setting(
               'gda.gis_service_migration_cutover_id', true
           ), '') = ''
           AND COALESCE(current_setting(
               'gda.gis_service_migration_rollback_id', true
           ), '') = ''
       ) THEN
        RETURN NEW;
    END IF;
    v_now := clock_timestamp();
    PERFORM 1
      FROM gda_control.gis_service_endpoint_warmup AS warmup
     WHERE warmup.tenant_id = NEW.tenant_id
       AND warmup.service_urn = NEW.service_urn
       AND warmup.endpoint_revision_id = NEW.active_endpoint_revision_id
       AND warmup.completed_at <= v_now
       AND warmup.valid_until > v_now
     ORDER BY warmup.completed_at DESC, warmup.warmup_id DESC
     LIMIT 1
     FOR SHARE;
    IF NOT FOUND THEN
        RAISE EXCEPTION
            'GIS service migration destination requires a live endpoint warmup receipt'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER trg_gda_01_gis_service_migration_destination_warmup
BEFORE UPDATE ON gda_control.gis_service
FOR EACH ROW EXECUTE FUNCTION
    gda_control.guard_gis_service_migration_destination_warmup();

ALTER TABLE gda_control.gis_service_endpoint_warmup
    ENABLE ROW LEVEL SECURITY;
ALTER TABLE gda_control.gis_service_endpoint_warmup
    FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation
ON gda_control.gis_service_endpoint_warmup
USING (tenant_id = gda_control.current_tenant())
WITH CHECK (tenant_id = gda_control.current_tenant());

REVOKE ALL ON TABLE gda_control.gis_service_endpoint_warmup
    FROM PUBLIC, gda_control_gateway;
GRANT SELECT ON TABLE gda_control.gis_service_endpoint_warmup
    TO gda_control_gateway;

REVOKE ALL ON FUNCTION gda_control.gis_service_endpoint_warmup_fingerprint(
    TEXT, UUID, TEXT, UUID, UUID, UUID, UUID, UUID, TEXT, UUID, UUID,
    INTEGER, INTEGER, TEXT, TEXT, TIMESTAMPTZ, TIMESTAMPTZ,
    TIMESTAMPTZ, TEXT, TIMESTAMPTZ
) FROM PUBLIC, gda_control_gateway;
GRANT EXECUTE ON FUNCTION gda_control.gis_service_endpoint_warmup_fingerprint(
    TEXT, UUID, TEXT, UUID, UUID, UUID, UUID, UUID, TEXT, UUID, UUID,
    INTEGER, INTEGER, TEXT, TEXT, TIMESTAMPTZ, TIMESTAMPTZ,
    TIMESTAMPTZ, TEXT, TIMESTAMPTZ
) TO gda_control_gateway;

REVOKE ALL ON FUNCTION gda_control.record_gis_service_endpoint_warmup(
    TEXT, UUID, TEXT, UUID, UUID, UUID, UUID, UUID, TEXT, UUID, UUID,
    INTEGER, INTEGER, TEXT, TEXT, TIMESTAMPTZ, TIMESTAMPTZ,
    TIMESTAMPTZ, TEXT, TIMESTAMPTZ, TEXT
) FROM PUBLIC, gda_control_gateway;
GRANT EXECUTE ON FUNCTION gda_control.record_gis_service_endpoint_warmup(
    TEXT, UUID, TEXT, UUID, UUID, UUID, UUID, UUID, TEXT, UUID, UUID,
    INTEGER, INTEGER, TEXT, TEXT, TIMESTAMPTZ, TIMESTAMPTZ,
    TIMESTAMPTZ, TEXT, TIMESTAMPTZ, TEXT
) TO gda_control_gateway;

REVOKE ALL ON FUNCTION
gda_control.guard_gis_service_endpoint_warmup_insert() FROM PUBLIC;
REVOKE ALL ON FUNCTION
gda_control.guard_gis_service_migration_destination_warmup() FROM PUBLIC;
