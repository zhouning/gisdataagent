-- 153: Minimal GIS Service Control Plane authority.
--
-- Service definitions extend the existing Resource/PlatformDefinition ledger,
-- deployments bind PlatformRun/provider observations, and one CAS pointer owns
-- the active endpoint. This is not a provider catalog or execution runtime.

CREATE TABLE gda_control.gis_service (
    tenant_id TEXT NOT NULL,
    service_urn TEXT NOT NULL,
    active_endpoint_revision_id UUID,
    endpoint_state_version INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (tenant_id, service_urn),
    CONSTRAINT fk_gda_gis_service_resource
        FOREIGN KEY (tenant_id, service_urn)
        REFERENCES gda_control.resource(tenant_id, resource_urn),
    CONSTRAINT ck_gda_gis_service_kind CHECK (
        split_part(service_urn, '/', 4) = 'gis_service'
    ),
    CONSTRAINT ck_gda_gis_service_state_version CHECK (
        endpoint_state_version >= 0
    ),
    CONSTRAINT ck_gda_gis_service_timestamps CHECK (updated_at >= created_at)
);

CREATE TABLE gda_control.gis_service_definition_version (
    tenant_id TEXT NOT NULL,
    service_definition_version_id UUID PRIMARY KEY,
    service_urn TEXT NOT NULL,
    version_key TEXT NOT NULL,
    predecessor_version_id UUID,
    platform_definition_version_id UUID NOT NULL,
    source_product_urn TEXT NOT NULL,
    source_data_product_version_id UUID NOT NULL,
    source_manifest_sha256 CHAR(64) NOT NULL,
    service_type TEXT NOT NULL,
    service_contract JSONB NOT NULL,
    definition_sha256 CHAR(64) NOT NULL,
    created_by TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    CONSTRAINT uq_gda_gis_service_definition_tenant_id
        UNIQUE (tenant_id, service_definition_version_id),
    CONSTRAINT uq_gda_gis_service_definition_identity
        UNIQUE (tenant_id, service_urn, service_definition_version_id),
    CONSTRAINT uq_gda_gis_service_definition_key
        UNIQUE (tenant_id, service_urn, version_key),
    CONSTRAINT fk_gda_gis_service_definition_service
        FOREIGN KEY (tenant_id, service_urn)
        REFERENCES gda_control.gis_service(tenant_id, service_urn),
    CONSTRAINT fk_gda_gis_service_definition_predecessor
        FOREIGN KEY (tenant_id, service_urn, predecessor_version_id)
        REFERENCES gda_control.gis_service_definition_version(
            tenant_id, service_urn, service_definition_version_id
        ),
    CONSTRAINT fk_gda_gis_service_definition_platform
        FOREIGN KEY (tenant_id, platform_definition_version_id)
        REFERENCES gda_control.platform_definition_version(
            tenant_id, definition_version_id
        ),
    CONSTRAINT fk_gda_gis_service_definition_product
        FOREIGN KEY (
            tenant_id, source_product_urn, source_data_product_version_id
        ) REFERENCES gda_control.data_product_version(
            tenant_id, product_urn, data_product_version_id
        ),
    CONSTRAINT ck_gda_gis_service_definition_version_key CHECK (
        version_key ~ '^v[0-9]+\.[0-9]+\.[0-9]+$'
    ),
    CONSTRAINT ck_gda_gis_service_definition_not_self CHECK (
        predecessor_version_id IS NULL
        OR predecessor_version_id <> service_definition_version_id
    ),
    CONSTRAINT ck_gda_gis_service_definition_manifest CHECK (
        source_manifest_sha256 ~ '^[0-9a-f]{64}$'
    ),
    CONSTRAINT ck_gda_gis_service_definition_type CHECK (
        service_type IN ('feature', 'map', 'vector_tile', 'coverage')
    ),
    CONSTRAINT ck_gda_gis_service_definition_contract CHECK (
        jsonb_typeof(service_contract) = 'object'
        AND service_contract <> '{}'::jsonb
    ),
    CONSTRAINT ck_gda_gis_service_definition_sha256 CHECK (
        definition_sha256 ~ '^[0-9a-f]{64}$'
    ),
    CONSTRAINT ck_gda_gis_service_definition_actor CHECK (
        length(btrim(created_by)) BETWEEN 1 AND 512
    )
);

CREATE UNIQUE INDEX uq_gda_gis_service_definition_root
    ON gda_control.gis_service_definition_version(tenant_id, service_urn)
    WHERE predecessor_version_id IS NULL;
CREATE UNIQUE INDEX uq_gda_gis_service_definition_successor
    ON gda_control.gis_service_definition_version(
        tenant_id, service_urn, predecessor_version_id
    ) WHERE predecessor_version_id IS NOT NULL;

CREATE TABLE gda_control.service_deployment_revision (
    tenant_id TEXT NOT NULL,
    deployment_revision_id UUID PRIMARY KEY,
    service_definition_version_id UUID NOT NULL,
    run_id UUID NOT NULL,
    revision_key TEXT NOT NULL,
    provider_system TEXT NOT NULL,
    provider_namespace TEXT NOT NULL,
    provider_deployment_id TEXT NOT NULL,
    provider_revision_ref TEXT NOT NULL,
    config_sha256 CHAR(64) NOT NULL,
    deployment_sha256 CHAR(64) NOT NULL,
    state TEXT NOT NULL DEFAULT 'planned',
    state_version INTEGER NOT NULL DEFAULT 0,
    terminal_observation_id UUID,
    created_by TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    terminal_at TIMESTAMPTZ,
    CONSTRAINT uq_gda_service_deployment_tenant_id
        UNIQUE (tenant_id, deployment_revision_id),
    CONSTRAINT uq_gda_service_deployment_definition_id
        UNIQUE (
            tenant_id, service_definition_version_id, deployment_revision_id
        ),
    CONSTRAINT uq_gda_service_deployment_key
        UNIQUE (tenant_id, service_definition_version_id, revision_key),
    CONSTRAINT uq_gda_service_deployment_provider_revision
        UNIQUE (
            tenant_id, provider_system, provider_namespace,
            provider_deployment_id, provider_revision_ref
        ),
    CONSTRAINT fk_gda_service_deployment_definition
        FOREIGN KEY (tenant_id, service_definition_version_id)
        REFERENCES gda_control.gis_service_definition_version(
            tenant_id, service_definition_version_id
        ),
    CONSTRAINT fk_gda_service_deployment_run
        FOREIGN KEY (tenant_id, run_id)
        REFERENCES gda_control.platform_run(tenant_id, run_id),
    CONSTRAINT fk_gda_service_deployment_observation
        FOREIGN KEY (tenant_id, terminal_observation_id)
        REFERENCES gda_control.framework_attempt_observation(
            tenant_id, observation_id
        ),
    CONSTRAINT ck_gda_service_deployment_revision_key CHECK (
        revision_key ~ '^r[0-9]+$'
    ),
    CONSTRAINT ck_gda_service_deployment_provider CHECK (
        provider_system ~ '^[a-zA-Z0-9][a-zA-Z0-9._:-]{0,127}$'
        AND length(btrim(provider_namespace)) BETWEEN 1 AND 512
        AND length(btrim(provider_deployment_id)) BETWEEN 1 AND 512
        AND length(btrim(provider_revision_ref)) BETWEEN 1 AND 512
    ),
    CONSTRAINT ck_gda_service_deployment_hashes CHECK (
        config_sha256 ~ '^[0-9a-f]{64}$'
        AND deployment_sha256 ~ '^[0-9a-f]{64}$'
    ),
    CONSTRAINT ck_gda_service_deployment_state CHECK (
        state IN ('planned', 'deploying', 'ready', 'failed')
        AND state_version >= 0
    ),
    CONSTRAINT ck_gda_service_deployment_terminal CHECK (
        (
            state IN ('ready', 'failed')
            AND terminal_observation_id IS NOT NULL
            AND terminal_at IS NOT NULL
        ) OR (
            state IN ('planned', 'deploying')
            AND terminal_observation_id IS NULL
            AND terminal_at IS NULL
        )
    ),
    CONSTRAINT ck_gda_service_deployment_actor CHECK (
        length(btrim(created_by)) BETWEEN 1 AND 512
    ),
    CONSTRAINT ck_gda_service_deployment_timestamps CHECK (
        updated_at >= created_at
        AND (terminal_at IS NULL OR terminal_at >= created_at)
    )
);

CREATE TABLE gda_control.service_deployment_event (
    tenant_id TEXT NOT NULL,
    event_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    deployment_revision_id UUID NOT NULL,
    sequence_no INTEGER NOT NULL,
    from_state TEXT,
    to_state TEXT NOT NULL,
    provider_observation_id UUID,
    actor_subject TEXT NOT NULL,
    reason TEXT NOT NULL,
    idempotency_key TEXT NOT NULL,
    event_sha256 CHAR(64) NOT NULL,
    occurred_at TIMESTAMPTZ NOT NULL,
    CONSTRAINT uq_gda_service_deployment_event_tenant_id
        UNIQUE (tenant_id, event_id),
    CONSTRAINT uq_gda_service_deployment_event_sequence
        UNIQUE (tenant_id, deployment_revision_id, sequence_no),
    CONSTRAINT uq_gda_service_deployment_event_idempotency
        UNIQUE (tenant_id, deployment_revision_id, idempotency_key),
    CONSTRAINT fk_gda_service_deployment_event_deployment
        FOREIGN KEY (tenant_id, deployment_revision_id)
        REFERENCES gda_control.service_deployment_revision(
            tenant_id, deployment_revision_id
        ),
    CONSTRAINT fk_gda_service_deployment_event_observation
        FOREIGN KEY (tenant_id, provider_observation_id)
        REFERENCES gda_control.framework_attempt_observation(
            tenant_id, observation_id
        ),
    CONSTRAINT ck_gda_service_deployment_event_state CHECK (
        (sequence_no = 0 AND from_state IS NULL AND to_state = 'planned')
        OR (
            sequence_no > 0
            AND from_state IN ('planned', 'deploying')
            AND to_state IN ('deploying', 'ready', 'failed')
        )
    ),
    CONSTRAINT ck_gda_service_deployment_event_payload CHECK (
        (to_state IN ('ready', 'failed')) =
            (provider_observation_id IS NOT NULL)
    ),
    CONSTRAINT ck_gda_service_deployment_event_text CHECK (
        NULLIF(btrim(actor_subject), '') IS NOT NULL
        AND NULLIF(btrim(reason), '') IS NOT NULL
        AND NULLIF(btrim(idempotency_key), '') IS NOT NULL
    ),
    CONSTRAINT ck_gda_service_deployment_event_sha256 CHECK (
        event_sha256 ~ '^[0-9a-f]{64}$'
    )
);

CREATE TABLE gda_control.endpoint_revision (
    tenant_id TEXT NOT NULL,
    endpoint_revision_id UUID PRIMARY KEY,
    service_urn TEXT NOT NULL,
    deployment_revision_id UUID NOT NULL,
    endpoint_protocol TEXT NOT NULL,
    endpoint_uri TEXT NOT NULL,
    endpoint_contract JSONB NOT NULL,
    endpoint_sha256 CHAR(64) NOT NULL,
    created_by TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    CONSTRAINT uq_gda_endpoint_revision_tenant_id
        UNIQUE (tenant_id, endpoint_revision_id),
    CONSTRAINT uq_gda_endpoint_revision_service_id
        UNIQUE (tenant_id, service_urn, endpoint_revision_id),
    CONSTRAINT uq_gda_endpoint_revision_uri
        UNIQUE (tenant_id, endpoint_uri),
    CONSTRAINT fk_gda_endpoint_revision_service
        FOREIGN KEY (tenant_id, service_urn)
        REFERENCES gda_control.gis_service(tenant_id, service_urn),
    CONSTRAINT fk_gda_endpoint_revision_deployment
        FOREIGN KEY (tenant_id, deployment_revision_id)
        REFERENCES gda_control.service_deployment_revision(
            tenant_id, deployment_revision_id
        ),
    CONSTRAINT ck_gda_endpoint_revision_protocol CHECK (
        endpoint_protocol IN (
            'arcgis_rest', 'ogc_api_features', 'wms', 'wmts', 'mvt'
        )
    ),
    CONSTRAINT ck_gda_endpoint_revision_uri CHECK (
        endpoint_uri ~ '^https://[^/?#@]+(/[^?#]*)?$'
        AND length(endpoint_uri) <= 2048
    ),
    CONSTRAINT ck_gda_endpoint_revision_contract CHECK (
        jsonb_typeof(endpoint_contract) = 'object'
        AND endpoint_contract <> '{}'::jsonb
    ),
    CONSTRAINT ck_gda_endpoint_revision_sha256 CHECK (
        endpoint_sha256 ~ '^[0-9a-f]{64}$'
    ),
    CONSTRAINT ck_gda_endpoint_revision_actor CHECK (
        length(btrim(created_by)) BETWEEN 1 AND 512
    )
);

ALTER TABLE gda_control.gis_service
    ADD CONSTRAINT fk_gda_gis_service_active_endpoint
    FOREIGN KEY (tenant_id, service_urn, active_endpoint_revision_id)
    REFERENCES gda_control.endpoint_revision(
        tenant_id, service_urn, endpoint_revision_id
    );

CREATE TABLE gda_control.gis_service_endpoint_activation_event (
    tenant_id TEXT NOT NULL,
    event_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    service_urn TEXT NOT NULL,
    from_endpoint_revision_id UUID,
    to_endpoint_revision_id UUID NOT NULL,
    from_state_version INTEGER NOT NULL,
    to_state_version INTEGER NOT NULL,
    actor_subject TEXT NOT NULL,
    reason TEXT NOT NULL,
    idempotency_key TEXT NOT NULL,
    event_sha256 CHAR(64) NOT NULL,
    occurred_at TIMESTAMPTZ NOT NULL,
    CONSTRAINT uq_gda_gis_service_activation_tenant_id
        UNIQUE (tenant_id, event_id),
    CONSTRAINT uq_gda_gis_service_activation_version
        UNIQUE (tenant_id, service_urn, to_state_version),
    CONSTRAINT uq_gda_gis_service_activation_idempotency
        UNIQUE (tenant_id, service_urn, idempotency_key),
    CONSTRAINT fk_gda_gis_service_activation_service
        FOREIGN KEY (tenant_id, service_urn)
        REFERENCES gda_control.gis_service(tenant_id, service_urn),
    CONSTRAINT fk_gda_gis_service_activation_from_endpoint
        FOREIGN KEY (tenant_id, service_urn, from_endpoint_revision_id)
        REFERENCES gda_control.endpoint_revision(
            tenant_id, service_urn, endpoint_revision_id
        ),
    CONSTRAINT fk_gda_gis_service_activation_to_endpoint
        FOREIGN KEY (tenant_id, service_urn, to_endpoint_revision_id)
        REFERENCES gda_control.endpoint_revision(
            tenant_id, service_urn, endpoint_revision_id
        ),
    CONSTRAINT ck_gda_gis_service_activation_state CHECK (
        from_state_version >= 0
        AND to_state_version = from_state_version + 1
    ),
    CONSTRAINT ck_gda_gis_service_activation_distinct CHECK (
        from_endpoint_revision_id IS NULL
        OR from_endpoint_revision_id <> to_endpoint_revision_id
    ),
    CONSTRAINT ck_gda_gis_service_activation_text CHECK (
        NULLIF(btrim(actor_subject), '') IS NOT NULL
        AND NULLIF(btrim(reason), '') IS NOT NULL
        AND NULLIF(btrim(idempotency_key), '') IS NOT NULL
    ),
    CONSTRAINT ck_gda_gis_service_activation_sha256 CHECK (
        event_sha256 ~ '^[0-9a-f]{64}$'
    )
);

CREATE INDEX idx_gda_service_deployment_definition
    ON gda_control.service_deployment_revision(
        tenant_id, service_definition_version_id, created_at DESC
    );
CREATE INDEX idx_gda_service_deployment_run
    ON gda_control.service_deployment_revision(tenant_id, run_id);
CREATE INDEX idx_gda_endpoint_revision_service
    ON gda_control.endpoint_revision(tenant_id, service_urn, created_at DESC);

CREATE OR REPLACE FUNCTION gda_control.guard_gis_service_record_insert()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    IF gda_control.current_tenant() IS NULL
       OR NEW.tenant_id IS DISTINCT FROM gda_control.current_tenant() THEN
        RAISE EXCEPTION 'GIS service tenant context is missing or mismatched'
            USING ERRCODE = '42501';
    END IF;
    IF COALESCE(current_setting('gda.gis_service_record_allowed', true), '') <> '1' THEN
        RAISE EXCEPTION 'use the governed GIS service recorder'
            USING ERRCODE = '42501';
    END IF;
    RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION gda_control.guard_gis_service_pointer_update()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    IF COALESCE(current_setting('gda.gis_service_pointer_update_allowed', true), '') <> '1' THEN
        RAISE EXCEPTION 'use the governed GIS endpoint activation recorder'
            USING ERRCODE = '55000';
    END IF;
    IF NEW.tenant_id IS DISTINCT FROM OLD.tenant_id
       OR NEW.service_urn IS DISTINCT FROM OLD.service_urn
       OR NEW.created_at IS DISTINCT FROM OLD.created_at
       OR NEW.endpoint_state_version <> OLD.endpoint_state_version + 1
       OR NEW.active_endpoint_revision_id IS NOT DISTINCT FROM OLD.active_endpoint_revision_id
       OR NEW.updated_at < OLD.updated_at THEN
        RAISE EXCEPTION 'invalid GIS service active endpoint CAS update'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION gda_control.guard_service_deployment_mutation()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    IF TG_OP = 'INSERT' THEN
        IF COALESCE(current_setting('gda.gis_service_record_allowed', true), '') <> '1' THEN
            RAISE EXCEPTION 'use the governed service deployment recorder'
                USING ERRCODE = '42501';
        END IF;
        IF NEW.state <> 'planned' OR NEW.state_version <> 0
           OR NEW.terminal_observation_id IS NOT NULL
           OR NEW.terminal_at IS NOT NULL THEN
            RAISE EXCEPTION 'service deployment must start planned at state version zero'
                USING ERRCODE = '23514';
        END IF;
        RETURN NEW;
    END IF;
    IF COALESCE(current_setting('gda.service_deployment_transition_allowed', true), '') <> '1' THEN
        RAISE EXCEPTION 'use the governed service deployment transition recorder'
            USING ERRCODE = '55000';
    END IF;
    IF NEW.tenant_id IS DISTINCT FROM OLD.tenant_id
       OR NEW.deployment_revision_id IS DISTINCT FROM OLD.deployment_revision_id
       OR NEW.service_definition_version_id IS DISTINCT FROM OLD.service_definition_version_id
       OR NEW.run_id IS DISTINCT FROM OLD.run_id
       OR NEW.revision_key IS DISTINCT FROM OLD.revision_key
       OR NEW.provider_system IS DISTINCT FROM OLD.provider_system
       OR NEW.provider_namespace IS DISTINCT FROM OLD.provider_namespace
       OR NEW.provider_deployment_id IS DISTINCT FROM OLD.provider_deployment_id
       OR NEW.provider_revision_ref IS DISTINCT FROM OLD.provider_revision_ref
       OR NEW.config_sha256 IS DISTINCT FROM OLD.config_sha256
       OR NEW.deployment_sha256 IS DISTINCT FROM OLD.deployment_sha256
       OR NEW.created_by IS DISTINCT FROM OLD.created_by
       OR NEW.created_at IS DISTINCT FROM OLD.created_at
       OR NEW.state_version <> OLD.state_version + 1
       OR NEW.updated_at < OLD.updated_at THEN
        RAISE EXCEPTION 'service deployment immutable binding changed'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER trg_gda_gis_service_insert
BEFORE INSERT ON gda_control.gis_service
FOR EACH ROW EXECUTE FUNCTION gda_control.guard_gis_service_record_insert();
CREATE TRIGGER trg_gda_gis_service_update
BEFORE UPDATE ON gda_control.gis_service
FOR EACH ROW EXECUTE FUNCTION gda_control.guard_gis_service_pointer_update();
CREATE TRIGGER trg_gda_gis_service_definition_insert
BEFORE INSERT ON gda_control.gis_service_definition_version
FOR EACH ROW EXECUTE FUNCTION gda_control.guard_gis_service_record_insert();
CREATE TRIGGER trg_gda_service_deployment_mutation
BEFORE INSERT OR UPDATE ON gda_control.service_deployment_revision
FOR EACH ROW EXECUTE FUNCTION gda_control.guard_service_deployment_mutation();
CREATE TRIGGER trg_gda_service_deployment_event_insert
BEFORE INSERT ON gda_control.service_deployment_event
FOR EACH ROW EXECUTE FUNCTION gda_control.guard_gis_service_record_insert();
CREATE TRIGGER trg_gda_endpoint_revision_insert
BEFORE INSERT ON gda_control.endpoint_revision
FOR EACH ROW EXECUTE FUNCTION gda_control.guard_gis_service_record_insert();
CREATE TRIGGER trg_gda_gis_service_activation_event_insert
BEFORE INSERT ON gda_control.gis_service_endpoint_activation_event
FOR EACH ROW EXECUTE FUNCTION gda_control.guard_gis_service_record_insert();

CREATE TRIGGER trg_gda_gis_service_definition_immutable
BEFORE UPDATE OR DELETE ON gda_control.gis_service_definition_version
FOR EACH ROW EXECUTE FUNCTION gda_control.reject_immutable_mutation();
CREATE TRIGGER trg_gda_service_deployment_delete_immutable
BEFORE DELETE ON gda_control.service_deployment_revision
FOR EACH ROW EXECUTE FUNCTION gda_control.reject_immutable_mutation();
CREATE TRIGGER trg_gda_service_deployment_event_immutable
BEFORE UPDATE OR DELETE ON gda_control.service_deployment_event
FOR EACH ROW EXECUTE FUNCTION gda_control.reject_immutable_mutation();
CREATE TRIGGER trg_gda_endpoint_revision_immutable
BEFORE UPDATE OR DELETE ON gda_control.endpoint_revision
FOR EACH ROW EXECUTE FUNCTION gda_control.reject_immutable_mutation();
CREATE TRIGGER trg_gda_gis_service_activation_event_immutable
BEFORE UPDATE OR DELETE ON gda_control.gis_service_endpoint_activation_event
FOR EACH ROW EXECUTE FUNCTION gda_control.reject_immutable_mutation();

CREATE OR REPLACE FUNCTION gda_control.initialize_service_deployment_event()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    INSERT INTO gda_control.service_deployment_event (
        tenant_id, deployment_revision_id, sequence_no, from_state, to_state,
        provider_observation_id, actor_subject, reason, idempotency_key,
        event_sha256, occurred_at
    ) VALUES (
        NEW.tenant_id, NEW.deployment_revision_id, 0, NULL, 'planned', NULL,
        NEW.created_by, 'deployment revision recorded',
        'planned:' || NEW.deployment_revision_id::text,
        encode(sha256(convert_to(jsonb_build_object(
            'tenant_id', NEW.tenant_id,
            'deployment_revision_id', NEW.deployment_revision_id::text,
            'sequence_no', 0,
            'from_state', NULL,
            'to_state', 'planned',
            'provider_observation_id', NULL,
            'actor_subject', NEW.created_by,
            'reason', 'deployment revision recorded',
            'occurred_at', NEW.created_at
        )::text, 'UTF8')), 'hex'),
        NEW.created_at
    );
    RETURN NEW;
END;
$$;

CREATE TRIGGER trg_gda_service_deployment_initialize_event
AFTER INSERT ON gda_control.service_deployment_revision
FOR EACH ROW EXECUTE FUNCTION gda_control.initialize_service_deployment_event();

CREATE OR REPLACE FUNCTION gda_control.record_gis_service_definition_version(
    p_tenant_id TEXT,
    p_service_definition_version_id UUID,
    p_service_urn TEXT,
    p_version_key TEXT,
    p_predecessor_version_id UUID,
    p_platform_definition_version_id UUID,
    p_source_product_urn TEXT,
    p_source_data_product_version_id UUID,
    p_source_manifest_sha256 TEXT,
    p_service_type TEXT,
    p_service_contract JSONB,
    p_definition_sha256 TEXT,
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
    v_existing gda_control.gis_service_definition_version%ROWTYPE;
    v_current_product_version_id UUID;
    v_current_manifest_sha256 TEXT;
    v_latest_definition_id UUID;
BEGIN
    IF gda_control.current_tenant() IS NULL
       OR p_tenant_id IS DISTINCT FROM gda_control.current_tenant() THEN
        RAISE EXCEPTION 'GIS service tenant context is missing or mismatched'
            USING ERRCODE = '42501';
    END IF;
    PERFORM pg_advisory_xact_lock(hashtextextended(
        p_tenant_id || ':' || 'gis-service:' || p_service_urn, 0
    ));

    SELECT * INTO v_existing
      FROM gda_control.gis_service_definition_version
     WHERE tenant_id = p_tenant_id
       AND service_definition_version_id = p_service_definition_version_id;
    IF FOUND THEN
        IF v_existing.service_urn = p_service_urn
           AND v_existing.version_key = p_version_key
           AND v_existing.predecessor_version_id IS NOT DISTINCT FROM p_predecessor_version_id
           AND v_existing.platform_definition_version_id = p_platform_definition_version_id
           AND v_existing.source_product_urn = p_source_product_urn
           AND v_existing.source_data_product_version_id = p_source_data_product_version_id
           AND v_existing.source_manifest_sha256 = p_source_manifest_sha256
           AND v_existing.service_type = p_service_type
           AND v_existing.service_contract = p_service_contract
           AND v_existing.definition_sha256 = p_definition_sha256
           AND v_existing.created_by = p_created_by
           AND v_existing.created_at = p_created_at THEN
            RETURN p_service_definition_version_id;
        END IF;
        RAISE EXCEPTION 'GIS service definition identity has different immutable content'
            USING ERRCODE = '40001';
    END IF;

    PERFORM 1 FROM gda_control.resource
     WHERE tenant_id = p_tenant_id
       AND resource_urn = p_service_urn
       AND resource_kind = 'gis_service';
    IF NOT FOUND THEN
        RAISE EXCEPTION 'GIS service Resource was not found'
            USING ERRCODE = 'P0002';
    END IF;
    PERFORM 1 FROM gda_control.platform_definition_version
     WHERE tenant_id = p_tenant_id
       AND definition_version_id = p_platform_definition_version_id;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'PlatformDefinitionVersion was not found'
            USING ERRCODE = 'P0002';
    END IF;

    SELECT product.current_version_id, version.manifest_sha256
      INTO v_current_product_version_id, v_current_manifest_sha256
      FROM gda_control.data_product AS product
      JOIN gda_control.data_product_version AS version
        ON version.tenant_id = product.tenant_id
       AND version.product_urn = product.product_urn
       AND version.data_product_version_id = product.current_version_id
     WHERE product.tenant_id = p_tenant_id
       AND product.product_urn = p_source_product_urn
       AND version.quality_verdict = 'passed';
    IF NOT FOUND
       OR v_current_product_version_id IS DISTINCT FROM p_source_data_product_version_id
       OR v_current_manifest_sha256 IS DISTINCT FROM p_source_manifest_sha256 THEN
        RAISE EXCEPTION 'GIS service source must bind the active approved DataProductVersion'
            USING ERRCODE = '23514';
    END IF;
    PERFORM 1 FROM gda_control.data_product_event
     WHERE tenant_id = p_tenant_id
       AND product_urn = p_source_product_urn
       AND to_version_id = p_source_data_product_version_id
       AND event_type IN ('published', 'advanced', 'promoted', 'rolled_back')
       AND occurred_at <= p_created_at;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'active DataProductVersion lacks governed publication evidence'
            USING ERRCODE = '23514';
    END IF;

    PERFORM set_config('gda.gis_service_record_allowed', '1', true);
    INSERT INTO gda_control.gis_service (
        tenant_id, service_urn, created_at, updated_at
    ) VALUES (
        p_tenant_id, p_service_urn, p_created_at, p_created_at
    ) ON CONFLICT DO NOTHING;

    SELECT service_definition_version_id INTO v_latest_definition_id
      FROM gda_control.gis_service_definition_version
     WHERE tenant_id = p_tenant_id AND service_urn = p_service_urn
     ORDER BY created_at DESC, service_definition_version_id DESC
     LIMIT 1;
    IF v_latest_definition_id IS NULL AND p_predecessor_version_id IS NOT NULL THEN
        RAISE EXCEPTION 'first GIS service definition cannot name a predecessor'
            USING ERRCODE = '23514';
    ELSIF v_latest_definition_id IS NOT NULL
          AND p_predecessor_version_id IS DISTINCT FROM v_latest_definition_id THEN
        RAISE EXCEPTION 'GIS service definition must extend the latest version'
            USING ERRCODE = '40001';
    END IF;

    INSERT INTO gda_control.gis_service_definition_version (
        tenant_id, service_definition_version_id, service_urn, version_key,
        predecessor_version_id, platform_definition_version_id,
        source_product_urn, source_data_product_version_id,
        source_manifest_sha256, service_type, service_contract,
        definition_sha256, created_by, created_at
    ) VALUES (
        p_tenant_id, p_service_definition_version_id, p_service_urn,
        p_version_key, p_predecessor_version_id,
        p_platform_definition_version_id, p_source_product_urn,
        p_source_data_product_version_id, p_source_manifest_sha256,
        p_service_type, p_service_contract, p_definition_sha256,
        p_created_by, p_created_at
    );
    RETURN p_service_definition_version_id;
END;
$$;

CREATE OR REPLACE FUNCTION gda_control.record_service_deployment_revision(
    p_tenant_id TEXT,
    p_deployment_revision_id UUID,
    p_service_definition_version_id UUID,
    p_run_id UUID,
    p_revision_key TEXT,
    p_provider_system TEXT,
    p_provider_namespace TEXT,
    p_provider_deployment_id TEXT,
    p_provider_revision_ref TEXT,
    p_config_sha256 TEXT,
    p_deployment_sha256 TEXT,
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
    v_existing gda_control.service_deployment_revision%ROWTYPE;
    v_platform_definition_version_id UUID;
    v_output_resource_version_id UUID;
    v_run_definition_version_id UUID;
    v_run_status TEXT;
BEGIN
    IF gda_control.current_tenant() IS NULL
       OR p_tenant_id IS DISTINCT FROM gda_control.current_tenant() THEN
        RAISE EXCEPTION 'service deployment tenant context is missing or mismatched'
            USING ERRCODE = '42501';
    END IF;
    SELECT * INTO v_existing
      FROM gda_control.service_deployment_revision
     WHERE tenant_id = p_tenant_id
       AND deployment_revision_id = p_deployment_revision_id;
    IF FOUND THEN
        IF v_existing.service_definition_version_id = p_service_definition_version_id
           AND v_existing.run_id = p_run_id
           AND v_existing.revision_key = p_revision_key
           AND v_existing.provider_system = p_provider_system
           AND v_existing.provider_namespace = p_provider_namespace
           AND v_existing.provider_deployment_id = p_provider_deployment_id
           AND v_existing.provider_revision_ref = p_provider_revision_ref
           AND v_existing.config_sha256 = p_config_sha256
           AND v_existing.deployment_sha256 = p_deployment_sha256
           AND v_existing.created_by = p_created_by
           AND v_existing.created_at = p_created_at THEN
            RETURN p_deployment_revision_id;
        END IF;
        RAISE EXCEPTION 'service deployment identity has different immutable content'
            USING ERRCODE = '40001';
    END IF;

    SELECT definition.platform_definition_version_id,
           product_version.output_resource_version_id
      INTO v_platform_definition_version_id, v_output_resource_version_id
      FROM gda_control.gis_service_definition_version AS definition
      JOIN gda_control.data_product_version AS product_version
        ON product_version.tenant_id = definition.tenant_id
       AND product_version.product_urn = definition.source_product_urn
       AND product_version.data_product_version_id =
            definition.source_data_product_version_id
     WHERE definition.tenant_id = p_tenant_id
       AND definition.service_definition_version_id =
            p_service_definition_version_id;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'GISServiceDefinitionVersion was not found'
            USING ERRCODE = 'P0002';
    END IF;
    SELECT definition_version_id, status
      INTO v_run_definition_version_id, v_run_status
      FROM gda_control.platform_run
     WHERE tenant_id = p_tenant_id AND run_id = p_run_id;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'PlatformRun was not found'
            USING ERRCODE = 'P0002';
    END IF;
    IF v_run_definition_version_id <> v_platform_definition_version_id
       OR v_run_status NOT IN ('accepted', 'dispatching', 'running', 'reconciling') THEN
        RAISE EXCEPTION 'service deployment Run does not bind the service definition'
            USING ERRCODE = '23514';
    END IF;
    PERFORM 1 FROM gda_control.platform_run_input_binding
     WHERE tenant_id = p_tenant_id
       AND run_id = p_run_id
       AND resource_version_id = v_output_resource_version_id;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'service deployment Run does not bind the product output version'
            USING ERRCODE = '23514';
    END IF;

    PERFORM set_config('gda.gis_service_record_allowed', '1', true);
    INSERT INTO gda_control.service_deployment_revision (
        tenant_id, deployment_revision_id, service_definition_version_id,
        run_id, revision_key, provider_system, provider_namespace,
        provider_deployment_id, provider_revision_ref, config_sha256,
        deployment_sha256, created_by, created_at, updated_at
    ) VALUES (
        p_tenant_id, p_deployment_revision_id,
        p_service_definition_version_id, p_run_id, p_revision_key,
        p_provider_system, p_provider_namespace, p_provider_deployment_id,
        p_provider_revision_ref, p_config_sha256, p_deployment_sha256,
        p_created_by, p_created_at, p_created_at
    );
    RETURN p_deployment_revision_id;
END;
$$;

CREATE OR REPLACE FUNCTION gda_control.transition_service_deployment_revision(
    p_tenant_id TEXT,
    p_deployment_revision_id UUID,
    p_expected_state_version INTEGER,
    p_to_state TEXT,
    p_provider_observation_id UUID,
    p_actor_subject TEXT,
    p_reason TEXT,
    p_idempotency_key TEXT,
    p_occurred_at TIMESTAMPTZ
)
RETURNS INTEGER
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, gda_control
SET row_security = on
AS $$
DECLARE
    v_deployment gda_control.service_deployment_revision%ROWTYPE;
    v_event gda_control.service_deployment_event%ROWTYPE;
    v_run_status TEXT;
    v_observed_state TEXT;
    v_observation_evidence JSONB;
    v_new_state_version INTEGER;
BEGIN
    IF gda_control.current_tenant() IS NULL
       OR p_tenant_id IS DISTINCT FROM gda_control.current_tenant() THEN
        RAISE EXCEPTION 'service deployment tenant context is missing or mismatched'
            USING ERRCODE = '42501';
    END IF;
    IF NULLIF(btrim(p_actor_subject), '') IS NULL
       OR NULLIF(btrim(p_reason), '') IS NULL
       OR NULLIF(btrim(p_idempotency_key), '') IS NULL THEN
        RAISE EXCEPTION 'deployment transition actor, reason and idempotency are required'
            USING ERRCODE = '22023';
    END IF;

    SELECT * INTO v_deployment
      FROM gda_control.service_deployment_revision
     WHERE tenant_id = p_tenant_id
       AND deployment_revision_id = p_deployment_revision_id
     FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'ServiceDeploymentRevision was not found'
            USING ERRCODE = 'P0002';
    END IF;
    SELECT * INTO v_event
      FROM gda_control.service_deployment_event
     WHERE tenant_id = p_tenant_id
       AND deployment_revision_id = p_deployment_revision_id
       AND idempotency_key = p_idempotency_key;
    IF FOUND THEN
        IF v_event.to_state = p_to_state
           AND v_event.provider_observation_id IS NOT DISTINCT FROM p_provider_observation_id
           AND v_event.actor_subject = p_actor_subject
           AND v_event.reason = p_reason
           AND v_event.occurred_at = p_occurred_at THEN
            RETURN v_event.sequence_no;
        END IF;
        RAISE EXCEPTION 'deployment transition idempotency has different content'
            USING ERRCODE = '40001';
    END IF;
    IF v_deployment.state_version <> p_expected_state_version THEN
        RAISE EXCEPTION 'deployment state version conflict'
            USING ERRCODE = '40001';
    END IF;
    IF NOT (
        (v_deployment.state = 'planned' AND p_to_state = 'deploying')
        OR (v_deployment.state = 'deploying' AND p_to_state IN ('ready', 'failed'))
    ) THEN
        RAISE EXCEPTION 'invalid service deployment state transition'
            USING ERRCODE = '23514';
    END IF;
    SELECT status INTO v_run_status
      FROM gda_control.platform_run
     WHERE tenant_id = p_tenant_id AND run_id = v_deployment.run_id;

    IF p_to_state = 'deploying' THEN
        IF p_provider_observation_id IS NOT NULL
           OR v_run_status NOT IN ('dispatching', 'running', 'reconciling', 'succeeded') THEN
            RAISE EXCEPTION 'deploying requires an active deployment PlatformRun'
                USING ERRCODE = '23514';
        END IF;
    ELSE
        SELECT observed_state, evidence
          INTO v_observed_state, v_observation_evidence
          FROM gda_control.framework_attempt_observation
         WHERE tenant_id = p_tenant_id
           AND observation_id = p_provider_observation_id
           AND run_id = v_deployment.run_id;
        IF NOT FOUND
           OR v_observation_evidence->>'deployment_revision_id' IS DISTINCT FROM
                p_deployment_revision_id::text
           OR v_observation_evidence->>'provider_deployment_id' IS DISTINCT FROM
                v_deployment.provider_deployment_id
           OR v_observation_evidence->>'provider_revision_ref' IS DISTINCT FROM
                v_deployment.provider_revision_ref THEN
            RAISE EXCEPTION 'terminal provider observation does not bind this deployment'
                USING ERRCODE = '23514';
        END IF;
        IF p_to_state = 'ready'
           AND (
               v_run_status <> 'succeeded'
               OR lower(v_observed_state) NOT IN ('success', 'succeeded', 'ready', 'completed')
           ) THEN
            RAISE EXCEPTION 'ready requires succeeded Run and success observation'
                USING ERRCODE = '23514';
        ELSIF p_to_state = 'failed'
              AND (
                  v_run_status NOT IN ('failed', 'cancelled', 'timed_out')
                  OR lower(v_observed_state) NOT IN ('failed', 'error', 'cancelled', 'timed_out')
              ) THEN
            RAISE EXCEPTION 'failed requires terminal failed Run and observation'
                USING ERRCODE = '23514';
        END IF;
    END IF;

    v_new_state_version := v_deployment.state_version + 1;
    PERFORM set_config('gda.service_deployment_transition_allowed', '1', true);
    UPDATE gda_control.service_deployment_revision
       SET state = p_to_state,
           state_version = v_new_state_version,
           terminal_observation_id = CASE
               WHEN p_to_state IN ('ready', 'failed') THEN p_provider_observation_id
               ELSE NULL
           END,
           updated_at = p_occurred_at,
           terminal_at = CASE
               WHEN p_to_state IN ('ready', 'failed') THEN p_occurred_at
               ELSE NULL
           END
     WHERE tenant_id = p_tenant_id
       AND deployment_revision_id = p_deployment_revision_id;

    PERFORM set_config('gda.gis_service_record_allowed', '1', true);
    INSERT INTO gda_control.service_deployment_event (
        tenant_id, deployment_revision_id, sequence_no, from_state, to_state,
        provider_observation_id, actor_subject, reason, idempotency_key,
        event_sha256, occurred_at
    ) VALUES (
        p_tenant_id, p_deployment_revision_id, v_new_state_version,
        v_deployment.state, p_to_state, p_provider_observation_id,
        p_actor_subject, p_reason, p_idempotency_key,
        encode(sha256(convert_to(jsonb_build_object(
            'tenant_id', p_tenant_id,
            'deployment_revision_id', p_deployment_revision_id::text,
            'sequence_no', v_new_state_version,
            'from_state', v_deployment.state,
            'to_state', p_to_state,
            'provider_observation_id', p_provider_observation_id::text,
            'actor_subject', p_actor_subject,
            'reason', p_reason,
            'occurred_at', p_occurred_at
        )::text, 'UTF8')), 'hex'),
        p_occurred_at
    );
    RETURN v_new_state_version;
END;
$$;

CREATE OR REPLACE FUNCTION gda_control.record_endpoint_revision(
    p_tenant_id TEXT,
    p_endpoint_revision_id UUID,
    p_service_urn TEXT,
    p_deployment_revision_id UUID,
    p_endpoint_protocol TEXT,
    p_endpoint_uri TEXT,
    p_endpoint_contract JSONB,
    p_endpoint_sha256 TEXT,
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
    v_existing gda_control.endpoint_revision%ROWTYPE;
    v_deployment_state TEXT;
    v_deployment_terminal_at TIMESTAMPTZ;
    v_service_urn TEXT;
    v_service_type TEXT;
BEGIN
    IF gda_control.current_tenant() IS NULL
       OR p_tenant_id IS DISTINCT FROM gda_control.current_tenant() THEN
        RAISE EXCEPTION 'endpoint tenant context is missing or mismatched'
            USING ERRCODE = '42501';
    END IF;
    SELECT * INTO v_existing FROM gda_control.endpoint_revision
     WHERE tenant_id = p_tenant_id
       AND endpoint_revision_id = p_endpoint_revision_id;
    IF FOUND THEN
        IF v_existing.service_urn = p_service_urn
           AND v_existing.deployment_revision_id = p_deployment_revision_id
           AND v_existing.endpoint_protocol = p_endpoint_protocol
           AND v_existing.endpoint_uri = p_endpoint_uri
           AND v_existing.endpoint_contract = p_endpoint_contract
           AND v_existing.endpoint_sha256 = p_endpoint_sha256
           AND v_existing.created_by = p_created_by
           AND v_existing.created_at = p_created_at THEN
            RETURN p_endpoint_revision_id;
        END IF;
        RAISE EXCEPTION 'endpoint revision identity has different immutable content'
            USING ERRCODE = '40001';
    END IF;

    SELECT deployment.state, deployment.terminal_at,
           definition.service_urn, definition.service_type
      INTO v_deployment_state, v_deployment_terminal_at,
           v_service_urn, v_service_type
      FROM gda_control.service_deployment_revision AS deployment
      JOIN gda_control.gis_service_definition_version AS definition
        ON definition.tenant_id = deployment.tenant_id
       AND definition.service_definition_version_id =
            deployment.service_definition_version_id
     WHERE deployment.tenant_id = p_tenant_id
       AND deployment.deployment_revision_id = p_deployment_revision_id;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'ServiceDeploymentRevision was not found'
            USING ERRCODE = 'P0002';
    END IF;
    IF v_deployment_state <> 'ready'
       OR v_service_urn <> p_service_urn
       OR p_created_at < v_deployment_terminal_at THEN
        RAISE EXCEPTION 'endpoint revision requires a ready deployment for this service'
            USING ERRCODE = '23514';
    END IF;
    IF NOT (
        (v_service_type = 'feature' AND p_endpoint_protocol IN ('arcgis_rest', 'ogc_api_features'))
        OR (v_service_type = 'map' AND p_endpoint_protocol IN ('arcgis_rest', 'wms', 'wmts'))
        OR (v_service_type = 'vector_tile' AND p_endpoint_protocol IN ('arcgis_rest', 'mvt', 'wmts'))
        OR (v_service_type = 'coverage' AND p_endpoint_protocol IN ('arcgis_rest', 'wms'))
    ) THEN
        RAISE EXCEPTION 'endpoint protocol is incompatible with the service type'
            USING ERRCODE = '23514';
    END IF;

    PERFORM set_config('gda.gis_service_record_allowed', '1', true);
    INSERT INTO gda_control.endpoint_revision (
        tenant_id, endpoint_revision_id, service_urn,
        deployment_revision_id, endpoint_protocol, endpoint_uri,
        endpoint_contract, endpoint_sha256, created_by, created_at
    ) VALUES (
        p_tenant_id, p_endpoint_revision_id, p_service_urn,
        p_deployment_revision_id, p_endpoint_protocol, p_endpoint_uri,
        p_endpoint_contract, p_endpoint_sha256, p_created_by, p_created_at
    );
    RETURN p_endpoint_revision_id;
END;
$$;

CREATE OR REPLACE FUNCTION gda_control.activate_gis_service_endpoint(
    p_tenant_id TEXT,
    p_service_urn TEXT,
    p_endpoint_revision_id UUID,
    p_expected_state_version INTEGER,
    p_actor_subject TEXT,
    p_reason TEXT,
    p_idempotency_key TEXT,
    p_occurred_at TIMESTAMPTZ
)
RETURNS INTEGER
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, gda_control
SET row_security = on
AS $$
DECLARE
    v_service gda_control.gis_service%ROWTYPE;
    v_event gda_control.gis_service_endpoint_activation_event%ROWTYPE;
    v_endpoint_service_urn TEXT;
    v_deployment_state TEXT;
    v_new_state_version INTEGER;
BEGIN
    IF gda_control.current_tenant() IS NULL
       OR p_tenant_id IS DISTINCT FROM gda_control.current_tenant() THEN
        RAISE EXCEPTION 'endpoint activation tenant context is missing or mismatched'
            USING ERRCODE = '42501';
    END IF;
    IF NULLIF(btrim(p_actor_subject), '') IS NULL
       OR NULLIF(btrim(p_reason), '') IS NULL
       OR NULLIF(btrim(p_idempotency_key), '') IS NULL THEN
        RAISE EXCEPTION 'activation actor, reason and idempotency are required'
            USING ERRCODE = '22023';
    END IF;
    SELECT * INTO v_service FROM gda_control.gis_service
     WHERE tenant_id = p_tenant_id AND service_urn = p_service_urn
     FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'GIS service was not found'
            USING ERRCODE = 'P0002';
    END IF;
    SELECT * INTO v_event
      FROM gda_control.gis_service_endpoint_activation_event
     WHERE tenant_id = p_tenant_id
       AND service_urn = p_service_urn
       AND idempotency_key = p_idempotency_key;
    IF FOUND THEN
        IF v_event.to_endpoint_revision_id = p_endpoint_revision_id
           AND v_event.actor_subject = p_actor_subject
           AND v_event.reason = p_reason
           AND v_event.occurred_at = p_occurred_at THEN
            RETURN v_event.to_state_version;
        END IF;
        RAISE EXCEPTION 'endpoint activation idempotency has different content'
            USING ERRCODE = '40001';
    END IF;
    IF v_service.endpoint_state_version <> p_expected_state_version THEN
        RAISE EXCEPTION 'endpoint active pointer state version conflict'
            USING ERRCODE = '40001';
    END IF;
    IF v_service.active_endpoint_revision_id IS NOT DISTINCT FROM p_endpoint_revision_id THEN
        RAISE EXCEPTION 'endpoint revision is already active'
            USING ERRCODE = '23514';
    END IF;
    SELECT endpoint.service_urn, deployment.state
      INTO v_endpoint_service_urn, v_deployment_state
      FROM gda_control.endpoint_revision AS endpoint
      JOIN gda_control.service_deployment_revision AS deployment
        ON deployment.tenant_id = endpoint.tenant_id
       AND deployment.deployment_revision_id = endpoint.deployment_revision_id
     WHERE endpoint.tenant_id = p_tenant_id
       AND endpoint.endpoint_revision_id = p_endpoint_revision_id;
    IF NOT FOUND
       OR v_endpoint_service_urn <> p_service_urn
       OR v_deployment_state <> 'ready' THEN
        RAISE EXCEPTION 'active endpoint must belong to a ready service deployment'
            USING ERRCODE = '23514';
    END IF;
    IF p_occurred_at < v_service.updated_at THEN
        RAISE EXCEPTION 'endpoint activation time cannot move backwards'
            USING ERRCODE = '23514';
    END IF;

    v_new_state_version := v_service.endpoint_state_version + 1;
    PERFORM set_config('gda.gis_service_pointer_update_allowed', '1', true);
    UPDATE gda_control.gis_service
       SET active_endpoint_revision_id = p_endpoint_revision_id,
           endpoint_state_version = v_new_state_version,
           updated_at = p_occurred_at
     WHERE tenant_id = p_tenant_id AND service_urn = p_service_urn;

    PERFORM set_config('gda.gis_service_record_allowed', '1', true);
    INSERT INTO gda_control.gis_service_endpoint_activation_event (
        tenant_id, service_urn, from_endpoint_revision_id,
        to_endpoint_revision_id, from_state_version, to_state_version,
        actor_subject, reason, idempotency_key, event_sha256, occurred_at
    ) VALUES (
        p_tenant_id, p_service_urn, v_service.active_endpoint_revision_id,
        p_endpoint_revision_id, v_service.endpoint_state_version,
        v_new_state_version, p_actor_subject, p_reason, p_idempotency_key,
        encode(sha256(convert_to(jsonb_build_object(
            'tenant_id', p_tenant_id,
            'service_urn', p_service_urn,
            'from_endpoint_revision_id', v_service.active_endpoint_revision_id::text,
            'to_endpoint_revision_id', p_endpoint_revision_id::text,
            'from_state_version', v_service.endpoint_state_version,
            'to_state_version', v_new_state_version,
            'actor_subject', p_actor_subject,
            'reason', p_reason,
            'occurred_at', p_occurred_at
        )::text, 'UTF8')), 'hex'),
        p_occurred_at
    );
    RETURN v_new_state_version;
END;
$$;

DO $$
DECLARE
    relation_name TEXT;
BEGIN
    FOREACH relation_name IN ARRAY ARRAY[
        'gis_service',
        'gis_service_definition_version',
        'service_deployment_revision',
        'service_deployment_event',
        'endpoint_revision',
        'gis_service_endpoint_activation_event'
    ]
    LOOP
        EXECUTE format(
            'ALTER TABLE gda_control.%I ENABLE ROW LEVEL SECURITY',
            relation_name
        );
        EXECUTE format(
            'ALTER TABLE gda_control.%I FORCE ROW LEVEL SECURITY',
            relation_name
        );
        EXECUTE format(
            'CREATE POLICY tenant_isolation ON gda_control.%I '
            'USING (tenant_id = gda_control.current_tenant()) '
            'WITH CHECK (tenant_id = gda_control.current_tenant())',
            relation_name
        );
    END LOOP;
END;
$$;

REVOKE ALL ON TABLE
    gda_control.gis_service,
    gda_control.gis_service_definition_version,
    gda_control.service_deployment_revision,
    gda_control.service_deployment_event,
    gda_control.endpoint_revision,
    gda_control.gis_service_endpoint_activation_event
FROM PUBLIC, gda_control_gateway;

GRANT SELECT ON TABLE
    gda_control.gis_service,
    gda_control.gis_service_definition_version,
    gda_control.service_deployment_revision,
    gda_control.service_deployment_event,
    gda_control.endpoint_revision,
    gda_control.gis_service_endpoint_activation_event
TO gda_control_gateway;

REVOKE ALL ON FUNCTION gda_control.guard_gis_service_record_insert() FROM PUBLIC;
REVOKE ALL ON FUNCTION gda_control.guard_gis_service_pointer_update() FROM PUBLIC;
REVOKE ALL ON FUNCTION gda_control.guard_service_deployment_mutation() FROM PUBLIC;
REVOKE ALL ON FUNCTION gda_control.initialize_service_deployment_event() FROM PUBLIC;
REVOKE ALL ON FUNCTION gda_control.record_gis_service_definition_version(
    TEXT, UUID, TEXT, TEXT, UUID, UUID, TEXT, UUID, TEXT, TEXT, JSONB,
    TEXT, TEXT, TIMESTAMPTZ
) FROM PUBLIC;
REVOKE ALL ON FUNCTION gda_control.record_service_deployment_revision(
    TEXT, UUID, UUID, UUID, TEXT, TEXT, TEXT, TEXT, TEXT, TEXT, TEXT,
    TEXT, TIMESTAMPTZ
) FROM PUBLIC;
REVOKE ALL ON FUNCTION gda_control.transition_service_deployment_revision(
    TEXT, UUID, INTEGER, TEXT, UUID, TEXT, TEXT, TEXT, TIMESTAMPTZ
) FROM PUBLIC;
REVOKE ALL ON FUNCTION gda_control.record_endpoint_revision(
    TEXT, UUID, TEXT, UUID, TEXT, TEXT, JSONB, TEXT, TEXT, TIMESTAMPTZ
) FROM PUBLIC;
REVOKE ALL ON FUNCTION gda_control.activate_gis_service_endpoint(
    TEXT, TEXT, UUID, INTEGER, TEXT, TEXT, TEXT, TIMESTAMPTZ
) FROM PUBLIC;

GRANT EXECUTE ON FUNCTION gda_control.record_gis_service_definition_version(
    TEXT, UUID, TEXT, TEXT, UUID, UUID, TEXT, UUID, TEXT, TEXT, JSONB,
    TEXT, TEXT, TIMESTAMPTZ
) TO gda_control_gateway;
GRANT EXECUTE ON FUNCTION gda_control.record_service_deployment_revision(
    TEXT, UUID, UUID, UUID, TEXT, TEXT, TEXT, TEXT, TEXT, TEXT, TEXT,
    TEXT, TIMESTAMPTZ
) TO gda_control_gateway;
GRANT EXECUTE ON FUNCTION gda_control.transition_service_deployment_revision(
    TEXT, UUID, INTEGER, TEXT, UUID, TEXT, TEXT, TEXT, TIMESTAMPTZ
) TO gda_control_gateway;
GRANT EXECUTE ON FUNCTION gda_control.record_endpoint_revision(
    TEXT, UUID, TEXT, UUID, TEXT, TEXT, JSONB, TEXT, TEXT, TIMESTAMPTZ
) TO gda_control_gateway;
GRANT EXECUTE ON FUNCTION gda_control.activate_gis_service_endpoint(
    TEXT, TEXT, UUID, INTEGER, TEXT, TEXT, TEXT, TIMESTAMPTZ
) TO gda_control_gateway;
