-- 219: Roll back an atomic GIS service migration under Incident or approval authority.
--
-- The rollback reuses the only active endpoint pointer and the immutable 218
-- cutover receipt.  It validates the complete current consumer set against
-- the original source release, changes the pointer with CAS and appends one
-- authority-bound receipt in the same transaction.

CREATE TABLE gda_control.gis_service_migration_rollback (
    tenant_id TEXT NOT NULL,
    rollback_id UUID NOT NULL,
    cutover_id UUID NOT NULL,
    cutover_sha256 CHAR(64) NOT NULL,
    service_urn TEXT NOT NULL,
    from_endpoint_revision_id UUID NOT NULL,
    to_endpoint_revision_id UUID NOT NULL,
    from_service_definition_version_id UUID NOT NULL,
    from_service_release_binding_id UUID NOT NULL,
    to_service_definition_version_id UUID NOT NULL,
    to_service_release_binding_id UUID NOT NULL,
    source_product_urn TEXT NOT NULL,
    from_product_version_id UUID NOT NULL,
    to_product_version_id UUID NOT NULL,
    current_binding_count INTEGER NOT NULL,
    current_consumer_count INTEGER NOT NULL,
    rollback_binding_count INTEGER NOT NULL,
    rollback_consumer_count INTEGER NOT NULL,
    rollback_binding_set_sha256 CHAR(64) NOT NULL,
    from_state_version INTEGER NOT NULL,
    to_state_version INTEGER NOT NULL,
    activation_event_id UUID NOT NULL,
    cache_transition_mode TEXT NOT NULL,
    authorization_kind TEXT NOT NULL,
    authorization_ref TEXT NOT NULL,
    authorization_sha256 CHAR(64) NOT NULL,
    authorization_status TEXT NOT NULL,
    authorization_state_version INTEGER NOT NULL,
    actor_subject TEXT NOT NULL,
    reason TEXT NOT NULL,
    idempotency_key TEXT NOT NULL,
    occurred_at TIMESTAMPTZ NOT NULL,
    rollback_sha256 CHAR(64) NOT NULL,
    CONSTRAINT pk_gda_gis_service_migration_rollback
        PRIMARY KEY (tenant_id, rollback_id),
    CONSTRAINT uq_gda_gis_service_migration_rollback_id UNIQUE (rollback_id),
    CONSTRAINT uq_gda_gis_service_migration_rollback_cutover
        UNIQUE (tenant_id, cutover_id),
    CONSTRAINT uq_gda_gis_service_migration_rollback_idempotency
        UNIQUE (tenant_id, service_urn, idempotency_key),
    CONSTRAINT uq_gda_gis_service_migration_rollback_activation
        UNIQUE (tenant_id, activation_event_id),
    CONSTRAINT uq_gda_gis_service_migration_rollback_sha
        UNIQUE (tenant_id, rollback_sha256),
    CONSTRAINT fk_gda_gis_service_migration_rollback_cutover
        FOREIGN KEY (tenant_id, cutover_id)
        REFERENCES gda_control.gis_service_migration_cutover(
            tenant_id, cutover_id
        ),
    CONSTRAINT fk_gda_gis_service_migration_rollback_service
        FOREIGN KEY (tenant_id, service_urn)
        REFERENCES gda_control.gis_service(tenant_id, service_urn),
    CONSTRAINT fk_gda_gis_service_migration_rollback_from_endpoint
        FOREIGN KEY (tenant_id, service_urn, from_endpoint_revision_id)
        REFERENCES gda_control.endpoint_revision(
            tenant_id, service_urn, endpoint_revision_id
        ),
    CONSTRAINT fk_gda_gis_service_migration_rollback_to_endpoint
        FOREIGN KEY (tenant_id, service_urn, to_endpoint_revision_id)
        REFERENCES gda_control.endpoint_revision(
            tenant_id, service_urn, endpoint_revision_id
        ),
    CONSTRAINT fk_gda_gis_service_migration_rollback_from_release
        FOREIGN KEY (
            tenant_id, from_service_definition_version_id,
            from_service_release_binding_id
        ) REFERENCES gda_control.service_release_binding(
            tenant_id, service_definition_version_id,
            service_release_binding_id
        ),
    CONSTRAINT fk_gda_gis_service_migration_rollback_to_release
        FOREIGN KEY (
            tenant_id, to_service_definition_version_id,
            to_service_release_binding_id
        ) REFERENCES gda_control.service_release_binding(
            tenant_id, service_definition_version_id,
            service_release_binding_id
        ),
    CONSTRAINT fk_gda_gis_service_migration_rollback_from_product
        FOREIGN KEY (tenant_id, source_product_urn, from_product_version_id)
        REFERENCES gda_control.data_product_version(
            tenant_id, product_urn, data_product_version_id
        ),
    CONSTRAINT fk_gda_gis_service_migration_rollback_to_product
        FOREIGN KEY (tenant_id, source_product_urn, to_product_version_id)
        REFERENCES gda_control.data_product_version(
            tenant_id, product_urn, data_product_version_id
        ),
    CONSTRAINT fk_gda_gis_service_migration_rollback_activation
        FOREIGN KEY (tenant_id, activation_event_id)
        REFERENCES gda_control.gis_service_endpoint_activation_event(
            tenant_id, event_id
        ),
    CONSTRAINT ck_gda_gis_service_migration_rollback_service CHECK (
        service_urn ~ '^gda://[a-z0-9][a-z0-9._-]{0,63}/gis_service/[a-z0-9][a-z0-9._-]{0,127}$'
        AND split_part(service_urn, '/', 3) = tenant_id
    ),
    CONSTRAINT ck_gda_gis_service_migration_rollback_product CHECK (
        source_product_urn ~ '^gda://[a-z0-9][a-z0-9._-]{0,63}/data_product/[a-z0-9][a-z0-9._-]{0,127}$'
        AND split_part(source_product_urn, '/', 3) = tenant_id
        AND from_product_version_id <> to_product_version_id
    ),
    CONSTRAINT ck_gda_gis_service_migration_rollback_direction CHECK (
        from_endpoint_revision_id <> to_endpoint_revision_id
        AND from_service_definition_version_id <>
            to_service_definition_version_id
        AND from_service_release_binding_id <>
            to_service_release_binding_id
    ),
    CONSTRAINT ck_gda_gis_service_migration_rollback_counts CHECK (
        current_binding_count >= 0
        AND current_binding_count = current_consumer_count
        AND rollback_binding_count = rollback_consumer_count
        AND current_consumer_count = rollback_consumer_count
    ),
    CONSTRAINT ck_gda_gis_service_migration_rollback_state CHECK (
        from_state_version >= 0
        AND to_state_version = from_state_version + 1
    ),
    CONSTRAINT ck_gda_gis_service_migration_rollback_cache CHECK (
        cache_transition_mode = 'release_namespace_rollover'
    ),
    CONSTRAINT ck_gda_gis_service_migration_rollback_authority CHECK (
        (
            authorization_kind = 'incident'
            AND authorization_status IN ('open', 'acknowledged')
            AND authorization_ref ~ '^[0-9a-fA-F-]{36}$'
        ) OR (
            authorization_kind = 'approval_case'
            AND authorization_status = 'approved'
            AND authorization_ref ~ '^gda://[a-z0-9][a-z0-9._-]{0,63}/approval_case/[a-z0-9][a-z0-9._-]{0,127}$'
            AND split_part(authorization_ref, '/', 3) = tenant_id
        )
    ),
    CONSTRAINT ck_gda_gis_service_migration_rollback_actor CHECK (
        actor_subject ~ '^(human|workload|agent|service):[^[:space:]]+$'
        AND NULLIF(btrim(reason), '') IS NOT NULL
        AND NULLIF(btrim(idempotency_key), '') IS NOT NULL
    ),
    CONSTRAINT ck_gda_gis_service_migration_rollback_hash CHECK (
        cutover_sha256 ~ '^[0-9a-f]{64}$'
        AND rollback_binding_set_sha256 ~ '^[0-9a-f]{64}$'
        AND authorization_sha256 ~ '^[0-9a-f]{64}$'
        AND rollback_sha256 ~ '^[0-9a-f]{64}$'
        AND authorization_state_version >= 0
    )
);

CREATE INDEX idx_gda_gis_service_migration_rollback_service
    ON gda_control.gis_service_migration_rollback(
        tenant_id, service_urn, occurred_at DESC, rollback_id
    );

CREATE OR REPLACE FUNCTION
gda_control.gis_service_migration_rollback_operation_fingerprint(
    p_tenant_id TEXT,
    p_service_urn TEXT,
    p_cutover_id UUID,
    p_cutover_sha256 TEXT,
    p_from_endpoint_revision_id UUID,
    p_to_endpoint_revision_id UUID,
    p_from_state_version INTEGER
)
RETURNS TEXT
LANGUAGE sql
IMMUTABLE
SET search_path = pg_catalog, public
AS $$
    WITH payload AS (
        SELECT jsonb_build_object(
            'cutover_id', p_cutover_id::text,
            'cutover_sha256', p_cutover_sha256,
            'from_endpoint_revision_id', p_from_endpoint_revision_id::text,
            'from_state_version', p_from_state_version,
            'schema', 'gda.gis_service_migration.rollback.v1',
            'service_urn', p_service_urn,
            'tenant_id', p_tenant_id,
            'to_endpoint_revision_id', p_to_endpoint_revision_id::text
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

CREATE OR REPLACE FUNCTION gda_control.gis_service_migration_rollback_fingerprint(
    p_tenant_id TEXT,
    p_rollback_id UUID,
    p_cutover_id UUID,
    p_cutover_sha256 TEXT,
    p_service_urn TEXT,
    p_from_endpoint_revision_id UUID,
    p_to_endpoint_revision_id UUID,
    p_from_service_definition_version_id UUID,
    p_from_service_release_binding_id UUID,
    p_to_service_definition_version_id UUID,
    p_to_service_release_binding_id UUID,
    p_source_product_urn TEXT,
    p_from_product_version_id UUID,
    p_to_product_version_id UUID,
    p_current_binding_count INTEGER,
    p_current_consumer_count INTEGER,
    p_rollback_binding_count INTEGER,
    p_rollback_consumer_count INTEGER,
    p_rollback_binding_set_sha256 TEXT,
    p_from_state_version INTEGER,
    p_to_state_version INTEGER,
    p_activation_event_id UUID,
    p_cache_transition_mode TEXT,
    p_authorization_kind TEXT,
    p_authorization_ref TEXT,
    p_authorization_sha256 TEXT,
    p_authorization_status TEXT,
    p_authorization_state_version INTEGER,
    p_actor_subject TEXT,
    p_reason TEXT,
    p_idempotency_key TEXT,
    p_occurred_at TIMESTAMPTZ
)
RETURNS TEXT
LANGUAGE sql
IMMUTABLE
SET search_path = pg_catalog, public
AS $$
    WITH payload AS (
        SELECT jsonb_build_object(
            'activation_event_id', p_activation_event_id::text,
            'actor_subject', p_actor_subject,
            'authorization_kind', p_authorization_kind,
            'authorization_ref', p_authorization_ref,
            'authorization_sha256', p_authorization_sha256,
            'authorization_state_version', p_authorization_state_version,
            'authorization_status', p_authorization_status,
            'cache_transition_mode', p_cache_transition_mode,
            'current_binding_count', p_current_binding_count,
            'current_consumer_count', p_current_consumer_count,
            'cutover_id', p_cutover_id::text,
            'cutover_sha256', p_cutover_sha256,
            'from_endpoint_revision_id', p_from_endpoint_revision_id::text,
            'from_product_version_id', p_from_product_version_id::text,
            'from_service_definition_version_id',
                p_from_service_definition_version_id::text,
            'from_service_release_binding_id',
                p_from_service_release_binding_id::text,
            'from_state_version', p_from_state_version,
            'idempotency_key', p_idempotency_key,
            'occurred_at', to_char(
                p_occurred_at AT TIME ZONE 'UTC',
                'YYYY-MM-DD"T"HH24:MI:SS.US'
            ) || '+00:00',
            'reason', p_reason,
            'rollback_binding_count', p_rollback_binding_count,
            'rollback_binding_set_sha256', p_rollback_binding_set_sha256,
            'rollback_consumer_count', p_rollback_consumer_count,
            'rollback_id', p_rollback_id::text,
            'schema', 'gda.gis_service_migration_rollback.v1',
            'service_urn', p_service_urn,
            'source_product_urn', p_source_product_urn,
            'tenant_id', p_tenant_id,
            'to_endpoint_revision_id', p_to_endpoint_revision_id::text,
            'to_product_version_id', p_to_product_version_id::text,
            'to_service_definition_version_id',
                p_to_service_definition_version_id::text,
            'to_service_release_binding_id',
                p_to_service_release_binding_id::text,
            'to_state_version', p_to_state_version
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

CREATE OR REPLACE FUNCTION
gda_control.guard_gis_service_migration_rollback_insert()
RETURNS TRIGGER
LANGUAGE plpgsql
SET search_path = pg_catalog, gda_control
AS $$
BEGIN
    IF COALESCE(
        current_setting(
            'gda.gis_service_migration_rollback_insert_allowed', true
        ), ''
    ) <> NEW.rollback_id::text THEN
        RAISE EXCEPTION 'use gda_control.rollback_gis_service_migration()'
            USING ERRCODE = '55000';
    END IF;
    IF gda_control.current_tenant() IS NULL
       OR NEW.tenant_id IS DISTINCT FROM gda_control.current_tenant() THEN
        RAISE EXCEPTION 'GIS service rollback tenant context is missing or mismatched'
            USING ERRCODE = '42501';
    END IF;
    IF NEW.rollback_sha256 IS DISTINCT FROM
       gda_control.gis_service_migration_rollback_fingerprint(
           NEW.tenant_id, NEW.rollback_id, NEW.cutover_id,
           NEW.cutover_sha256, NEW.service_urn,
           NEW.from_endpoint_revision_id, NEW.to_endpoint_revision_id,
           NEW.from_service_definition_version_id,
           NEW.from_service_release_binding_id,
           NEW.to_service_definition_version_id,
           NEW.to_service_release_binding_id, NEW.source_product_urn,
           NEW.from_product_version_id, NEW.to_product_version_id,
           NEW.current_binding_count, NEW.current_consumer_count,
           NEW.rollback_binding_count, NEW.rollback_consumer_count,
           NEW.rollback_binding_set_sha256, NEW.from_state_version,
           NEW.to_state_version, NEW.activation_event_id,
           NEW.cache_transition_mode, NEW.authorization_kind,
           NEW.authorization_ref, NEW.authorization_sha256,
           NEW.authorization_status, NEW.authorization_state_version,
           NEW.actor_subject, NEW.reason, NEW.idempotency_key,
           NEW.occurred_at
       ) THEN
        RAISE EXCEPTION 'GIS service rollback fingerprint mismatch'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER trg_gda_gis_service_migration_rollback_insert
BEFORE INSERT ON gda_control.gis_service_migration_rollback
FOR EACH ROW EXECUTE FUNCTION
    gda_control.guard_gis_service_migration_rollback_insert();

CREATE TRIGGER trg_gda_gis_service_migration_rollback_immutable
BEFORE UPDATE OR DELETE ON gda_control.gis_service_migration_rollback
FOR EACH ROW EXECUTE FUNCTION gda_control.reject_immutable_mutation();

-- Extend the 218 table guard with the one rollback marker.  Generic endpoint
-- activation remains unable to set either transaction-local authority marker.
CREATE OR REPLACE FUNCTION gda_control.guard_gis_service_migration_pointer_update()
RETURNS TRIGGER
LANGUAGE plpgsql
SET search_path = pg_catalog, gda_control
AS $$
DECLARE
    v_source_definition_id UUID;
    v_source_release_id UUID;
    v_source_product_version_id UUID;
    v_target_product_version_id UUID;
BEGIN
    IF OLD.active_endpoint_revision_id IS NULL
       OR OLD.active_endpoint_revision_id = NEW.active_endpoint_revision_id THEN
        RETURN NEW;
    END IF;
    SELECT deployment.service_definition_version_id,
           deployment.service_release_binding_id,
           definition.source_data_product_version_id
      INTO v_source_definition_id, v_source_release_id,
           v_source_product_version_id
      FROM gda_control.endpoint_revision AS endpoint
      JOIN gda_control.service_deployment_revision AS deployment
        ON deployment.tenant_id = endpoint.tenant_id
       AND deployment.deployment_revision_id = endpoint.deployment_revision_id
      JOIN gda_control.gis_service_definition_version AS definition
        ON definition.tenant_id = deployment.tenant_id
       AND definition.service_definition_version_id =
           deployment.service_definition_version_id
     WHERE endpoint.tenant_id = OLD.tenant_id
       AND endpoint.endpoint_revision_id = OLD.active_endpoint_revision_id;
    SELECT definition.source_data_product_version_id
      INTO v_target_product_version_id
      FROM gda_control.endpoint_revision AS endpoint
      JOIN gda_control.service_deployment_revision AS deployment
        ON deployment.tenant_id = endpoint.tenant_id
       AND deployment.deployment_revision_id = endpoint.deployment_revision_id
      JOIN gda_control.gis_service_definition_version AS definition
        ON definition.tenant_id = deployment.tenant_id
       AND definition.service_definition_version_id =
           deployment.service_definition_version_id
     WHERE endpoint.tenant_id = NEW.tenant_id
       AND endpoint.endpoint_revision_id = NEW.active_endpoint_revision_id;
    IF v_source_product_version_id IS DISTINCT FROM v_target_product_version_id
       AND EXISTS (
           SELECT 1
             FROM gda_control.service_consumer_binding AS binding
            WHERE binding.tenant_id = OLD.tenant_id
              AND binding.service_urn = OLD.service_urn
              AND binding.service_definition_version_id = v_source_definition_id
              AND binding.service_release_binding_id = v_source_release_id
              AND binding.expires_at > clock_timestamp()
              AND NOT EXISTS (
                  SELECT 1
                    FROM gda_control.service_consumer_binding_revocation AS revoked
                   WHERE revoked.tenant_id = binding.tenant_id
                     AND revoked.service_consumer_binding_id =
                         binding.service_consumer_binding_id
              )
              AND NOT EXISTS (
                  SELECT 1
                    FROM gda_control.service_consumer_binding_renewal AS renewed
                   WHERE renewed.tenant_id = binding.tenant_id
                     AND renewed.source_binding_id =
                         binding.service_consumer_binding_id
              )
       )
       AND COALESCE(
           current_setting('gda.gis_service_migration_cutover_id', true), ''
       ) = ''
       AND COALESCE(
           current_setting('gda.gis_service_migration_rollback_id', true), ''
       ) = '' THEN
        RAISE EXCEPTION
            'cross-product GIS endpoint activation requires migration cutover or rollback authority'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;

CREATE FUNCTION gda_control.rollback_gis_service_migration(
    p_tenant_id TEXT,
    p_rollback_id UUID,
    p_cutover_id UUID,
    p_cutover_sha256 TEXT,
    p_service_urn TEXT,
    p_from_endpoint_revision_id UUID,
    p_to_endpoint_revision_id UUID,
    p_expected_state_version INTEGER,
    p_authorization_kind TEXT,
    p_authorization_ref TEXT,
    p_actor_subject TEXT,
    p_reason TEXT,
    p_idempotency_key TEXT,
    p_occurred_at TIMESTAMPTZ
)
RETURNS SETOF gda_control.gis_service_migration_rollback
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, gda_control
SET row_security = on
AS $$
DECLARE
    v_cutover gda_control.gis_service_migration_cutover%ROWTYPE;
    v_service gda_control.gis_service%ROWTYPE;
    v_existing gda_control.gis_service_migration_rollback%ROWTYPE;
    v_result gda_control.gis_service_migration_rollback%ROWTYPE;
    v_from_definition_id UUID;
    v_from_release_id UUID;
    v_from_product_urn TEXT;
    v_from_product_version_id UUID;
    v_to_definition_id UUID;
    v_to_release_id UUID;
    v_to_product_urn TEXT;
    v_to_product_version_id UUID;
    v_to_deployment_state TEXT;
    v_current_binding_count INTEGER;
    v_current_consumer_count INTEGER;
    v_rollback_binding_count INTEGER;
    v_rollback_consumer_count INTEGER;
    v_rollback_binding_set_sha256 TEXT;
    v_authorization_sha256 TEXT;
    v_authorization_status TEXT;
    v_authorization_state_version INTEGER;
    v_incident_subject TEXT;
    v_incident_opened_at TIMESTAMPTZ;
    v_case_target TEXT;
    v_case_action TEXT;
    v_case_context JSONB;
    v_case_decided_at TIMESTAMPTZ;
    v_case_expires_at TIMESTAMPTZ;
    v_operation_sha256 TEXT;
    v_to_state_version INTEGER;
    v_activation_event_id UUID;
    v_activation_idempotency_key TEXT;
    v_rollback_sha256 TEXT;
    v_effective_at TIMESTAMPTZ;
BEGIN
    IF p_tenant_id IS DISTINCT FROM gda_control.current_tenant() THEN
        RAISE EXCEPTION 'GIS service rollback tenant context is missing or mismatched'
            USING ERRCODE = '42501';
    END IF;
    IF p_from_endpoint_revision_id = p_to_endpoint_revision_id
       OR p_authorization_kind NOT IN ('incident', 'approval_case')
       OR NULLIF(btrim(p_authorization_ref), '') IS NULL
       OR p_actor_subject !~ '^(human|workload|agent|service):[^[:space:]]+$'
       OR NULLIF(btrim(p_reason), '') IS NULL
       OR NULLIF(btrim(p_idempotency_key), '') IS NULL THEN
        RAISE EXCEPTION 'GIS service rollback request is incomplete'
            USING ERRCODE = '22023';
    END IF;

    SELECT cutover.* INTO v_cutover
      FROM gda_control.gis_service_migration_cutover AS cutover
     WHERE cutover.tenant_id = p_tenant_id
       AND cutover.cutover_id = p_cutover_id;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'GIS service migration cutover was not found'
            USING ERRCODE = 'P0002';
    END IF;

    -- Match migration 218 lock order to avoid cutover/rollback deadlocks.
    PERFORM pg_advisory_xact_lock(
        hashtextextended(
            'data-product-promotion:' || p_tenant_id || ':' ||
                v_cutover.source_product_urn,
            0
        )
    );
    PERFORM pg_advisory_xact_lock(
        hashtextextended(
            'gis-service-migration:' || p_tenant_id || ':' || p_service_urn,
            0
        )
    );
    v_effective_at := clock_timestamp();

    SELECT cutover.* INTO v_cutover
      FROM gda_control.gis_service_migration_cutover AS cutover
     WHERE cutover.tenant_id = p_tenant_id
       AND cutover.cutover_id = p_cutover_id
     FOR SHARE;
    SELECT * INTO v_service
      FROM gda_control.gis_service
     WHERE tenant_id = p_tenant_id AND service_urn = p_service_urn
     FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'GIS service was not found' USING ERRCODE = 'P0002';
    END IF;

    SELECT rollback.* INTO v_existing
      FROM gda_control.gis_service_migration_rollback AS rollback
     WHERE rollback.tenant_id = p_tenant_id
       AND rollback.service_urn = p_service_urn
       AND (
           rollback.rollback_id = p_rollback_id
           OR rollback.idempotency_key = p_idempotency_key
           OR rollback.cutover_id = p_cutover_id
       )
     ORDER BY (rollback.rollback_id = p_rollback_id) DESC,
              (rollback.idempotency_key = p_idempotency_key) DESC
     LIMIT 1;
    IF FOUND THEN
        IF v_existing.rollback_id IS DISTINCT FROM p_rollback_id
           OR v_existing.cutover_id IS DISTINCT FROM p_cutover_id
           OR v_existing.cutover_sha256 IS DISTINCT FROM p_cutover_sha256
           OR v_existing.service_urn IS DISTINCT FROM p_service_urn
           OR v_existing.from_endpoint_revision_id IS DISTINCT FROM
               p_from_endpoint_revision_id
           OR v_existing.to_endpoint_revision_id IS DISTINCT FROM
               p_to_endpoint_revision_id
           OR v_existing.from_state_version IS DISTINCT FROM
               p_expected_state_version
           OR v_existing.authorization_kind IS DISTINCT FROM
               p_authorization_kind
           OR v_existing.authorization_ref IS DISTINCT FROM
               p_authorization_ref
           OR v_existing.actor_subject IS DISTINCT FROM p_actor_subject
           OR v_existing.reason IS DISTINCT FROM p_reason
           OR v_existing.idempotency_key IS DISTINCT FROM p_idempotency_key
           OR v_existing.occurred_at IS DISTINCT FROM p_occurred_at THEN
            RAISE EXCEPTION 'GIS service rollback identity has different content'
                USING ERRCODE = '23505';
        END IF;
        RETURN NEXT v_existing;
        RETURN;
    END IF;

    IF v_cutover.cutover_sha256 IS DISTINCT FROM p_cutover_sha256
       OR v_cutover.service_urn IS DISTINCT FROM p_service_urn
       OR v_cutover.target_endpoint_revision_id IS DISTINCT FROM
           p_from_endpoint_revision_id
       OR v_cutover.source_endpoint_revision_id IS DISTINCT FROM
           p_to_endpoint_revision_id THEN
        RAISE EXCEPTION 'GIS service rollback does not bind the cutover direction'
            USING ERRCODE = '23514';
    END IF;
    IF v_service.endpoint_state_version <> p_expected_state_version
       OR p_expected_state_version <> v_cutover.to_state_version
       OR v_service.active_endpoint_revision_id IS DISTINCT FROM
           p_from_endpoint_revision_id THEN
        RAISE EXCEPTION 'GIS service rollback pointer CAS conflict'
            USING ERRCODE = '40001';
    END IF;
    IF p_occurred_at < v_service.updated_at
       OR p_occurred_at < v_cutover.occurred_at
       OR p_occurred_at > v_effective_at THEN
        RAISE EXCEPTION 'GIS service rollback time is outside the active pointer window'
            USING ERRCODE = '23514';
    END IF;

    SELECT deployment.service_definition_version_id,
           deployment.service_release_binding_id,
           definition.source_product_urn,
           definition.source_data_product_version_id
      INTO v_from_definition_id, v_from_release_id,
           v_from_product_urn, v_from_product_version_id
      FROM gda_control.endpoint_revision AS endpoint
      JOIN gda_control.service_deployment_revision AS deployment
        ON deployment.tenant_id = endpoint.tenant_id
       AND deployment.deployment_revision_id = endpoint.deployment_revision_id
      JOIN gda_control.gis_service_definition_version AS definition
        ON definition.tenant_id = deployment.tenant_id
       AND definition.service_definition_version_id =
           deployment.service_definition_version_id
     WHERE endpoint.tenant_id = p_tenant_id
       AND endpoint.service_urn = p_service_urn
       AND endpoint.endpoint_revision_id = p_from_endpoint_revision_id;
    SELECT deployment.service_definition_version_id,
           deployment.service_release_binding_id,
           definition.source_product_urn,
           definition.source_data_product_version_id,
           deployment.state
      INTO v_to_definition_id, v_to_release_id,
           v_to_product_urn, v_to_product_version_id,
           v_to_deployment_state
      FROM gda_control.endpoint_revision AS endpoint
      JOIN gda_control.service_deployment_revision AS deployment
        ON deployment.tenant_id = endpoint.tenant_id
       AND deployment.deployment_revision_id = endpoint.deployment_revision_id
      JOIN gda_control.gis_service_definition_version AS definition
        ON definition.tenant_id = deployment.tenant_id
       AND definition.service_definition_version_id =
           deployment.service_definition_version_id
     WHERE endpoint.tenant_id = p_tenant_id
       AND endpoint.service_urn = p_service_urn
       AND endpoint.endpoint_revision_id = p_to_endpoint_revision_id;
    IF v_from_definition_id IS NULL OR v_to_definition_id IS NULL THEN
        RAISE EXCEPTION 'GIS service rollback endpoint lineage was not found'
            USING ERRCODE = 'P0002';
    END IF;
    IF v_from_definition_id IS DISTINCT FROM
           v_cutover.target_service_definition_version_id
       OR v_from_release_id IS DISTINCT FROM
           v_cutover.target_service_release_binding_id
       OR v_to_definition_id IS DISTINCT FROM
           v_cutover.source_service_definition_version_id
       OR v_to_release_id IS DISTINCT FROM
           v_cutover.source_service_release_binding_id
       OR v_from_product_urn IS DISTINCT FROM v_cutover.source_product_urn
       OR v_to_product_urn IS DISTINCT FROM v_cutover.source_product_urn
       OR v_from_product_version_id IS DISTINCT FROM
           v_cutover.to_product_version_id
       OR v_to_product_version_id IS DISTINCT FROM
           v_cutover.from_product_version_id
       OR v_to_deployment_state <> 'ready' THEN
        RAISE EXCEPTION 'GIS service rollback endpoint and release lineage mismatch'
            USING ERRCODE = '23514';
    END IF;

    WITH current_bindings AS (
        SELECT binding.*
          FROM gda_control.service_consumer_binding AS binding
         WHERE binding.tenant_id = p_tenant_id
           AND binding.service_urn = p_service_urn
           AND binding.service_definition_version_id = v_from_definition_id
           AND binding.service_release_binding_id = v_from_release_id
           AND binding.created_at <= p_occurred_at
           AND binding.expires_at > v_effective_at
           AND NOT EXISTS (
               SELECT 1 FROM gda_control.service_consumer_binding_revocation AS r
                WHERE r.tenant_id = binding.tenant_id
                  AND r.service_consumer_binding_id =
                      binding.service_consumer_binding_id
           )
           AND NOT EXISTS (
               SELECT 1 FROM gda_control.service_consumer_binding_renewal AS r
                WHERE r.tenant_id = binding.tenant_id
                  AND r.source_binding_id =
                      binding.service_consumer_binding_id
           )
    )
    SELECT count(*)::INTEGER, count(DISTINCT consumer_ref)::INTEGER
      INTO v_current_binding_count, v_current_consumer_count
      FROM current_bindings;
    IF v_current_binding_count <> v_current_consumer_count THEN
        RAISE EXCEPTION 'GIS service rollback current consumer bindings are ambiguous'
            USING ERRCODE = '23514';
    END IF;

    WITH current_consumers AS (
        SELECT binding.consumer_ref
          FROM gda_control.service_consumer_binding AS binding
         WHERE binding.tenant_id = p_tenant_id
           AND binding.service_urn = p_service_urn
           AND binding.service_definition_version_id = v_from_definition_id
           AND binding.service_release_binding_id = v_from_release_id
           AND binding.created_at <= p_occurred_at
           AND binding.expires_at > v_effective_at
           AND NOT EXISTS (
               SELECT 1 FROM gda_control.service_consumer_binding_revocation AS r
                WHERE r.tenant_id = binding.tenant_id
                  AND r.service_consumer_binding_id =
                      binding.service_consumer_binding_id
           )
           AND NOT EXISTS (
               SELECT 1 FROM gda_control.service_consumer_binding_renewal AS r
                WHERE r.tenant_id = binding.tenant_id
                  AND r.source_binding_id =
                      binding.service_consumer_binding_id
           )
    ), rollback_bindings AS (
        SELECT binding.*
          FROM gda_control.service_consumer_binding AS binding
          JOIN current_consumers AS current
            ON current.consumer_ref = binding.consumer_ref
         WHERE binding.tenant_id = p_tenant_id
           AND binding.service_urn = p_service_urn
           AND binding.service_definition_version_id = v_to_definition_id
           AND binding.service_release_binding_id = v_to_release_id
           AND binding.created_at <= p_occurred_at
           AND binding.expires_at > v_effective_at
           AND NOT EXISTS (
               SELECT 1 FROM gda_control.service_consumer_binding_revocation AS r
                WHERE r.tenant_id = binding.tenant_id
                  AND r.service_consumer_binding_id =
                      binding.service_consumer_binding_id
           )
           AND NOT EXISTS (
               SELECT 1 FROM gda_control.service_consumer_binding_renewal AS r
                WHERE r.tenant_id = binding.tenant_id
                  AND r.source_binding_id =
                      binding.service_consumer_binding_id
           )
    )
    SELECT count(*)::INTEGER,
           count(DISTINCT consumer_ref)::INTEGER,
           encode(public.digest(convert_to(
               COALESCE(string_agg(
                   consumer_ref || ':' ||
                   service_consumer_binding_id::text || ':' ||
                   binding_sha256::text,
                   E'\n' ORDER BY consumer_ref, service_consumer_binding_id
               ), ''), 'UTF8'), 'sha256'), 'hex')
      INTO v_rollback_binding_count, v_rollback_consumer_count,
           v_rollback_binding_set_sha256
      FROM rollback_bindings;
    IF v_rollback_binding_count <> v_current_consumer_count
       OR v_rollback_consumer_count <> v_current_consumer_count THEN
        RAISE EXCEPTION
            'GIS service rollback requires one effective source release binding per current consumer'
            USING ERRCODE = '23514';
    END IF;

    v_operation_sha256 :=
        gda_control.gis_service_migration_rollback_operation_fingerprint(
            p_tenant_id, p_service_urn, p_cutover_id, p_cutover_sha256,
            p_from_endpoint_revision_id, p_to_endpoint_revision_id,
            p_expected_state_version
        );
    IF p_authorization_kind = 'incident' THEN
        IF p_authorization_ref !~
           '^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-5][0-9a-fA-F]{3}-[89aAbB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}$' THEN
            RAISE EXCEPTION 'GIS service rollback Incident reference is invalid'
                USING ERRCODE = '22023';
        END IF;
        SELECT incident.subject_resource_urn, incident.incident_sha256,
               incident.status, incident.state_version, incident.opened_at
          INTO v_incident_subject, v_authorization_sha256,
               v_authorization_status, v_authorization_state_version,
               v_incident_opened_at
          FROM gda_control.data_incident AS incident
         WHERE incident.tenant_id = p_tenant_id
           AND incident.incident_id = p_authorization_ref::uuid
         FOR SHARE;
        IF NOT FOUND
           OR v_incident_subject IS DISTINCT FROM p_service_urn
           OR v_authorization_status NOT IN ('open', 'acknowledged')
           OR v_incident_opened_at > p_occurred_at THEN
            RAISE EXCEPTION
                'GIS service rollback Incident authority is not active and service-bound'
                USING ERRCODE = '23514';
        END IF;
    ELSE
        SELECT approval.target_resource_urn, approval.target_fingerprint,
               approval.action, approval.status, approval.state_version,
               approval.request_context, approval.decided_at,
               approval.expires_at
          INTO v_case_target, v_authorization_sha256, v_case_action,
               v_authorization_status, v_authorization_state_version,
               v_case_context, v_case_decided_at, v_case_expires_at
          FROM gda_control.approval_case AS approval
         WHERE approval.tenant_id = p_tenant_id
           AND approval.approval_case_ref = p_authorization_ref
         FOR SHARE;
        IF NOT FOUND
           OR v_case_target IS DISTINCT FROM p_service_urn
           OR v_authorization_sha256 IS DISTINCT FROM v_operation_sha256
           OR v_case_action IS DISTINCT FROM 'gis_service_migration.rollback'
           OR v_authorization_status IS DISTINCT FROM 'approved'
           OR v_case_decided_at IS NULL
           OR v_case_decided_at > p_occurred_at
           OR p_occurred_at >= v_case_expires_at
           OR v_case_context->>'schema' IS DISTINCT FROM
                'gda.gis_service_migration.rollback.v1'
           OR v_case_context->>'tenant_id' IS DISTINCT FROM p_tenant_id
           OR v_case_context->>'service_urn' IS DISTINCT FROM p_service_urn
           OR v_case_context->>'cutover_id' IS DISTINCT FROM p_cutover_id::text
           OR v_case_context->>'cutover_sha256' IS DISTINCT FROM
                p_cutover_sha256
           OR v_case_context->>'from_endpoint_revision_id' IS DISTINCT FROM
                p_from_endpoint_revision_id::text
           OR v_case_context->>'to_endpoint_revision_id' IS DISTINCT FROM
                p_to_endpoint_revision_id::text
           OR v_case_context->>'from_state_version' IS DISTINCT FROM
                p_expected_state_version::text THEN
            RAISE EXCEPTION
                'GIS service rollback ApprovalCase does not bind this operation'
                USING ERRCODE = '23514';
        END IF;
    END IF;

    -- Freeze all rows used to derive the effective consumer set until commit.
    PERFORM 1
      FROM gda_control.service_consumer_binding AS binding
     WHERE binding.tenant_id = p_tenant_id
       AND binding.service_urn = p_service_urn
       AND binding.service_definition_version_id IN (
           v_from_definition_id, v_to_definition_id
       )
     FOR SHARE;
    PERFORM 1
      FROM gda_control.service_consumer_binding_revocation AS revoked
     WHERE revoked.tenant_id = p_tenant_id
       AND EXISTS (
           SELECT 1 FROM gda_control.service_consumer_binding AS binding
            WHERE binding.tenant_id = revoked.tenant_id
              AND binding.service_consumer_binding_id =
                  revoked.service_consumer_binding_id
              AND binding.service_urn = p_service_urn
       )
     FOR SHARE;
    PERFORM 1
      FROM gda_control.service_consumer_binding_renewal AS renewed
     WHERE renewed.tenant_id = p_tenant_id
       AND EXISTS (
           SELECT 1 FROM gda_control.service_consumer_binding AS binding
            WHERE binding.tenant_id = renewed.tenant_id
              AND binding.service_consumer_binding_id =
                  renewed.source_binding_id
              AND binding.service_urn = p_service_urn
       )
     FOR SHARE;

    v_activation_idempotency_key :=
        'migration-rollback:' || p_rollback_id::text;
    PERFORM set_config(
        'gda.gis_service_migration_rollback_id', p_rollback_id::text, true
    );
    v_to_state_version :=
        gda_control.activate_gis_service_endpoint_unverified(
            p_tenant_id, p_service_urn, p_to_endpoint_revision_id,
            p_expected_state_version, p_actor_subject, p_reason,
            v_activation_idempotency_key, p_occurred_at
        );
    PERFORM set_config('gda.gis_service_migration_rollback_id', '', true);

    SELECT event.event_id INTO v_activation_event_id
      FROM gda_control.gis_service_endpoint_activation_event AS event
     WHERE event.tenant_id = p_tenant_id
       AND event.service_urn = p_service_urn
       AND event.idempotency_key = v_activation_idempotency_key
       AND event.from_endpoint_revision_id = p_from_endpoint_revision_id
       AND event.to_endpoint_revision_id = p_to_endpoint_revision_id
       AND event.from_state_version = p_expected_state_version
       AND event.to_state_version = v_to_state_version;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'GIS service rollback activation event was not recorded'
            USING ERRCODE = '40001';
    END IF;

    v_rollback_sha256 :=
        gda_control.gis_service_migration_rollback_fingerprint(
            p_tenant_id, p_rollback_id, p_cutover_id, p_cutover_sha256,
            p_service_urn, p_from_endpoint_revision_id,
            p_to_endpoint_revision_id, v_from_definition_id,
            v_from_release_id, v_to_definition_id, v_to_release_id,
            v_cutover.source_product_urn, v_from_product_version_id,
            v_to_product_version_id, v_current_binding_count,
            v_current_consumer_count, v_rollback_binding_count,
            v_rollback_consumer_count, v_rollback_binding_set_sha256,
            p_expected_state_version, v_to_state_version,
            v_activation_event_id, 'release_namespace_rollover',
            p_authorization_kind, p_authorization_ref,
            v_authorization_sha256, v_authorization_status,
            v_authorization_state_version, p_actor_subject, p_reason,
            p_idempotency_key, p_occurred_at
        );
    PERFORM set_config(
        'gda.gis_service_migration_rollback_insert_allowed',
        p_rollback_id::text, true
    );
    INSERT INTO gda_control.gis_service_migration_rollback (
        tenant_id, rollback_id, cutover_id, cutover_sha256, service_urn,
        from_endpoint_revision_id, to_endpoint_revision_id,
        from_service_definition_version_id,
        from_service_release_binding_id,
        to_service_definition_version_id, to_service_release_binding_id,
        source_product_urn, from_product_version_id, to_product_version_id,
        current_binding_count, current_consumer_count,
        rollback_binding_count, rollback_consumer_count,
        rollback_binding_set_sha256, from_state_version, to_state_version,
        activation_event_id, cache_transition_mode, authorization_kind,
        authorization_ref, authorization_sha256, authorization_status,
        authorization_state_version, actor_subject, reason, idempotency_key,
        occurred_at, rollback_sha256
    ) VALUES (
        p_tenant_id, p_rollback_id, p_cutover_id, p_cutover_sha256,
        p_service_urn, p_from_endpoint_revision_id,
        p_to_endpoint_revision_id, v_from_definition_id, v_from_release_id,
        v_to_definition_id, v_to_release_id, v_cutover.source_product_urn,
        v_from_product_version_id, v_to_product_version_id,
        v_current_binding_count, v_current_consumer_count,
        v_rollback_binding_count, v_rollback_consumer_count,
        v_rollback_binding_set_sha256, p_expected_state_version,
        v_to_state_version, v_activation_event_id,
        'release_namespace_rollover', p_authorization_kind,
        p_authorization_ref, v_authorization_sha256,
        v_authorization_status, v_authorization_state_version,
        p_actor_subject, p_reason, p_idempotency_key, p_occurred_at,
        v_rollback_sha256
    );
    PERFORM set_config(
        'gda.gis_service_migration_rollback_insert_allowed', '', true
    );
    SELECT * INTO v_result
      FROM gda_control.gis_service_migration_rollback AS rollback
     WHERE rollback.tenant_id = p_tenant_id
       AND rollback.rollback_id = p_rollback_id;
    RETURN NEXT v_result;
END;
$$;

ALTER TABLE gda_control.gis_service_migration_rollback
    ENABLE ROW LEVEL SECURITY;
ALTER TABLE gda_control.gis_service_migration_rollback
    FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation
ON gda_control.gis_service_migration_rollback
USING (tenant_id = gda_control.current_tenant())
WITH CHECK (tenant_id = gda_control.current_tenant());

REVOKE ALL ON TABLE gda_control.gis_service_migration_rollback
    FROM PUBLIC, gda_control_gateway;
GRANT SELECT ON TABLE gda_control.gis_service_migration_rollback
    TO gda_control_gateway;

REVOKE ALL ON FUNCTION
gda_control.gis_service_migration_rollback_operation_fingerprint(
    TEXT, TEXT, UUID, TEXT, UUID, UUID, INTEGER
) FROM PUBLIC, gda_control_gateway;
GRANT EXECUTE ON FUNCTION
gda_control.gis_service_migration_rollback_operation_fingerprint(
    TEXT, TEXT, UUID, TEXT, UUID, UUID, INTEGER
) TO gda_control_gateway;

REVOKE ALL ON FUNCTION gda_control.gis_service_migration_rollback_fingerprint(
    TEXT, UUID, UUID, TEXT, TEXT, UUID, UUID, UUID, UUID, UUID, UUID,
    TEXT, UUID, UUID, INTEGER, INTEGER, INTEGER, INTEGER, TEXT, INTEGER,
    INTEGER, UUID, TEXT, TEXT, TEXT, TEXT, TEXT, INTEGER, TEXT, TEXT,
    TEXT, TIMESTAMPTZ
) FROM PUBLIC, gda_control_gateway;
GRANT EXECUTE ON FUNCTION gda_control.gis_service_migration_rollback_fingerprint(
    TEXT, UUID, UUID, TEXT, TEXT, UUID, UUID, UUID, UUID, UUID, UUID,
    TEXT, UUID, UUID, INTEGER, INTEGER, INTEGER, INTEGER, TEXT, INTEGER,
    INTEGER, UUID, TEXT, TEXT, TEXT, TEXT, TEXT, INTEGER, TEXT, TEXT,
    TEXT, TIMESTAMPTZ
) TO gda_control_gateway;

REVOKE ALL ON FUNCTION gda_control.rollback_gis_service_migration(
    TEXT, UUID, UUID, TEXT, TEXT, UUID, UUID, INTEGER, TEXT, TEXT,
    TEXT, TEXT, TEXT, TIMESTAMPTZ
) FROM PUBLIC, gda_control_gateway;
GRANT EXECUTE ON FUNCTION gda_control.rollback_gis_service_migration(
    TEXT, UUID, UUID, TEXT, TEXT, UUID, UUID, INTEGER, TEXT, TEXT,
    TEXT, TEXT, TEXT, TIMESTAMPTZ
) TO gda_control_gateway;

REVOKE ALL ON FUNCTION
gda_control.guard_gis_service_migration_rollback_insert() FROM PUBLIC;
