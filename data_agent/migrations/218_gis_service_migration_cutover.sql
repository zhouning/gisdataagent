-- 218: Atomically cut a GIS service across a product-version migration.
--
-- The source and target releases, product notice, consumer acknowledgement,
-- exact-release grants, active pointer and activation event already have their
-- own authorities.  This migration adds the all-consumer gate and one
-- append-only cutover receipt; it does not build providers or purge shared
-- caches.

CREATE TABLE gda_control.gis_service_migration_cutover (
    tenant_id TEXT NOT NULL,
    cutover_id UUID NOT NULL,
    service_urn TEXT NOT NULL,
    source_endpoint_revision_id UUID NOT NULL,
    target_endpoint_revision_id UUID NOT NULL,
    source_service_definition_version_id UUID NOT NULL,
    source_service_release_binding_id UUID NOT NULL,
    target_service_definition_version_id UUID NOT NULL,
    target_service_release_binding_id UUID NOT NULL,
    source_product_urn TEXT NOT NULL,
    from_product_version_id UUID NOT NULL,
    to_product_version_id UUID NOT NULL,
    source_binding_count INTEGER NOT NULL,
    impact_count INTEGER NOT NULL,
    acknowledged_count INTEGER NOT NULL,
    target_binding_count INTEGER NOT NULL,
    impact_set_sha256 CHAR(64) NOT NULL,
    acknowledgement_set_sha256 CHAR(64) NOT NULL,
    target_binding_set_sha256 CHAR(64) NOT NULL,
    from_state_version INTEGER NOT NULL,
    to_state_version INTEGER NOT NULL,
    activation_event_id UUID NOT NULL,
    cache_transition_mode TEXT NOT NULL,
    actor_subject TEXT NOT NULL,
    reason TEXT NOT NULL,
    idempotency_key TEXT NOT NULL,
    occurred_at TIMESTAMPTZ NOT NULL,
    cutover_sha256 CHAR(64) NOT NULL,
    CONSTRAINT pk_gda_gis_service_migration_cutover
        PRIMARY KEY (tenant_id, cutover_id),
    CONSTRAINT uq_gda_gis_service_migration_cutover_id UNIQUE (cutover_id),
    CONSTRAINT uq_gda_gis_service_migration_cutover_idempotency
        UNIQUE (tenant_id, service_urn, idempotency_key),
    CONSTRAINT uq_gda_gis_service_migration_cutover_activation
        UNIQUE (tenant_id, activation_event_id),
    CONSTRAINT uq_gda_gis_service_migration_cutover_sha
        UNIQUE (tenant_id, cutover_sha256),
    CONSTRAINT fk_gda_gis_service_migration_cutover_service
        FOREIGN KEY (tenant_id, service_urn)
        REFERENCES gda_control.gis_service(tenant_id, service_urn),
    CONSTRAINT fk_gda_gis_service_migration_cutover_source_endpoint
        FOREIGN KEY (tenant_id, service_urn, source_endpoint_revision_id)
        REFERENCES gda_control.endpoint_revision(
            tenant_id, service_urn, endpoint_revision_id
        ),
    CONSTRAINT fk_gda_gis_service_migration_cutover_target_endpoint
        FOREIGN KEY (tenant_id, service_urn, target_endpoint_revision_id)
        REFERENCES gda_control.endpoint_revision(
            tenant_id, service_urn, endpoint_revision_id
        ),
    CONSTRAINT fk_gda_gis_service_migration_cutover_source_release
        FOREIGN KEY (
            tenant_id, source_service_definition_version_id,
            source_service_release_binding_id
        ) REFERENCES gda_control.service_release_binding(
            tenant_id, service_definition_version_id,
            service_release_binding_id
        ),
    CONSTRAINT fk_gda_gis_service_migration_cutover_target_release
        FOREIGN KEY (
            tenant_id, target_service_definition_version_id,
            target_service_release_binding_id
        ) REFERENCES gda_control.service_release_binding(
            tenant_id, service_definition_version_id,
            service_release_binding_id
        ),
    CONSTRAINT fk_gda_gis_service_migration_cutover_from_product
        FOREIGN KEY (tenant_id, source_product_urn, from_product_version_id)
        REFERENCES gda_control.data_product_version(
            tenant_id, product_urn, data_product_version_id
        ),
    CONSTRAINT fk_gda_gis_service_migration_cutover_to_product
        FOREIGN KEY (tenant_id, source_product_urn, to_product_version_id)
        REFERENCES gda_control.data_product_version(
            tenant_id, product_urn, data_product_version_id
        ),
    CONSTRAINT fk_gda_gis_service_migration_cutover_activation_event
        FOREIGN KEY (tenant_id, activation_event_id)
        REFERENCES gda_control.gis_service_endpoint_activation_event(
            tenant_id, event_id
        ),
    CONSTRAINT ck_gda_gis_service_migration_cutover_service CHECK (
        service_urn ~ '^gda://[a-z0-9][a-z0-9._-]{0,63}/gis_service/[a-z0-9][a-z0-9._-]{0,127}$'
        AND split_part(service_urn, '/', 3) = tenant_id
    ),
    CONSTRAINT ck_gda_gis_service_migration_cutover_product CHECK (
        source_product_urn ~ '^gda://[a-z0-9][a-z0-9._-]{0,63}/data_product/[a-z0-9][a-z0-9._-]{0,127}$'
        AND split_part(source_product_urn, '/', 3) = tenant_id
        AND from_product_version_id <> to_product_version_id
    ),
    CONSTRAINT ck_gda_gis_service_migration_cutover_distinct CHECK (
        source_endpoint_revision_id <> target_endpoint_revision_id
        AND source_service_definition_version_id <>
            target_service_definition_version_id
        AND source_service_release_binding_id <>
            target_service_release_binding_id
    ),
    CONSTRAINT ck_gda_gis_service_migration_cutover_counts CHECK (
        source_binding_count > 0
        AND source_binding_count = impact_count
        AND source_binding_count = acknowledged_count
        AND source_binding_count = target_binding_count
    ),
    CONSTRAINT ck_gda_gis_service_migration_cutover_state CHECK (
        from_state_version >= 0
        AND to_state_version = from_state_version + 1
    ),
    CONSTRAINT ck_gda_gis_service_migration_cutover_cache CHECK (
        cache_transition_mode = 'release_namespace_rollover'
    ),
    CONSTRAINT ck_gda_gis_service_migration_cutover_actor CHECK (
        actor_subject ~ '^(human|workload|agent|service):[^[:space:]]+$'
        AND NULLIF(btrim(reason), '') IS NOT NULL
        AND NULLIF(btrim(idempotency_key), '') IS NOT NULL
    ),
    CONSTRAINT ck_gda_gis_service_migration_cutover_hash CHECK (
        impact_set_sha256 ~ '^[0-9a-f]{64}$'
        AND acknowledgement_set_sha256 ~ '^[0-9a-f]{64}$'
        AND target_binding_set_sha256 ~ '^[0-9a-f]{64}$'
        AND cutover_sha256 ~ '^[0-9a-f]{64}$'
    )
);

CREATE INDEX idx_gda_gis_service_migration_cutover_service
    ON gda_control.gis_service_migration_cutover(
        tenant_id, service_urn, occurred_at DESC, cutover_id
    );

CREATE OR REPLACE FUNCTION gda_control.gis_service_migration_cutover_fingerprint(
    p_tenant_id TEXT,
    p_cutover_id UUID,
    p_service_urn TEXT,
    p_source_endpoint_revision_id UUID,
    p_target_endpoint_revision_id UUID,
    p_source_service_definition_version_id UUID,
    p_source_service_release_binding_id UUID,
    p_target_service_definition_version_id UUID,
    p_target_service_release_binding_id UUID,
    p_source_product_urn TEXT,
    p_from_product_version_id UUID,
    p_to_product_version_id UUID,
    p_source_binding_count INTEGER,
    p_impact_count INTEGER,
    p_acknowledged_count INTEGER,
    p_target_binding_count INTEGER,
    p_impact_set_sha256 TEXT,
    p_acknowledgement_set_sha256 TEXT,
    p_target_binding_set_sha256 TEXT,
    p_from_state_version INTEGER,
    p_to_state_version INTEGER,
    p_activation_event_id UUID,
    p_cache_transition_mode TEXT,
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
            'acknowledged_count', p_acknowledged_count,
            'acknowledgement_set_sha256', p_acknowledgement_set_sha256,
            'activation_event_id', p_activation_event_id::text,
            'actor_subject', p_actor_subject,
            'cache_transition_mode', p_cache_transition_mode,
            'cutover_id', p_cutover_id::text,
            'from_product_version_id', p_from_product_version_id::text,
            'from_state_version', p_from_state_version,
            'idempotency_key', p_idempotency_key,
            'impact_count', p_impact_count,
            'impact_set_sha256', p_impact_set_sha256,
            'occurred_at', to_char(
                p_occurred_at AT TIME ZONE 'UTC',
                'YYYY-MM-DD"T"HH24:MI:SS.US'
            ) || '+00:00',
            'reason', p_reason,
            'schema', 'gda.gis_service_migration_cutover.v1',
            'service_urn', p_service_urn,
            'source_binding_count', p_source_binding_count,
            'source_endpoint_revision_id',
                p_source_endpoint_revision_id::text,
            'source_product_urn', p_source_product_urn,
            'source_service_definition_version_id',
                p_source_service_definition_version_id::text,
            'source_service_release_binding_id',
                p_source_service_release_binding_id::text,
            'target_binding_count', p_target_binding_count,
            'target_binding_set_sha256', p_target_binding_set_sha256,
            'target_endpoint_revision_id',
                p_target_endpoint_revision_id::text,
            'target_service_definition_version_id',
                p_target_service_definition_version_id::text,
            'target_service_release_binding_id',
                p_target_service_release_binding_id::text,
            'tenant_id', p_tenant_id,
            'to_product_version_id', p_to_product_version_id::text,
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
                    )
                      FROM jsonb_each(payload.object)
                ) || '}',
                'UTF8'
            ),
            'sha256'
        ),
        'hex'
    )
      FROM payload
$$;

CREATE OR REPLACE FUNCTION gda_control.guard_gis_service_migration_cutover_insert()
RETURNS TRIGGER
LANGUAGE plpgsql
SET search_path = pg_catalog, gda_control
AS $$
BEGIN
    IF COALESCE(
        current_setting('gda.gis_service_migration_cutover_insert_allowed', true),
        ''
    ) <> '1' THEN
        RAISE EXCEPTION 'use gda_control.cutover_gis_service_migration()'
            USING ERRCODE = '55000';
    END IF;
    IF gda_control.current_tenant() IS NULL
       OR NEW.tenant_id IS DISTINCT FROM gda_control.current_tenant() THEN
        RAISE EXCEPTION 'GIS service cutover tenant context is missing or mismatched'
            USING ERRCODE = '42501';
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER trg_gda_gis_service_migration_cutover_insert
BEFORE INSERT ON gda_control.gis_service_migration_cutover
FOR EACH ROW EXECUTE FUNCTION
    gda_control.guard_gis_service_migration_cutover_insert();

CREATE TRIGGER trg_gda_gis_service_migration_cutover_immutable
BEFORE UPDATE OR DELETE ON gda_control.gis_service_migration_cutover
FOR EACH ROW EXECUTE FUNCTION gda_control.reject_immutable_mutation();

-- Every append-only change that can alter the effective consumer set takes
-- the same service lock as cutover.  This closes revocation, renewal and new
-- grant races while the endpoint pointer is being changed.
CREATE OR REPLACE FUNCTION gda_control.lock_gis_service_migration_scope()
RETURNS TRIGGER
LANGUAGE plpgsql
SET search_path = pg_catalog, gda_control
AS $$
DECLARE
    v_tenant_id TEXT;
    v_service_urn TEXT;
BEGIN
    v_tenant_id := NEW.tenant_id;
    IF TG_TABLE_NAME IN (
        'service_consumer_binding',
        'gis_service_consumer_binding_migration_impact'
    ) THEN
        v_service_urn := NEW.service_urn;
    ELSIF TG_TABLE_NAME = 'service_consumer_binding_revocation' THEN
        SELECT binding.service_urn INTO v_service_urn
          FROM gda_control.service_consumer_binding AS binding
         WHERE binding.tenant_id = NEW.tenant_id
           AND binding.service_consumer_binding_id =
               NEW.service_consumer_binding_id;
    ELSIF TG_TABLE_NAME = 'service_consumer_binding_renewal' THEN
        SELECT binding.service_urn INTO v_service_urn
          FROM gda_control.service_consumer_binding AS binding
         WHERE binding.tenant_id = NEW.tenant_id
           AND binding.service_consumer_binding_id = NEW.source_binding_id;
    END IF;
    IF v_service_urn IS NULL THEN
        RAISE EXCEPTION 'GIS service migration lock scope was not found'
            USING ERRCODE = 'P0002';
    END IF;
    PERFORM pg_advisory_xact_lock(
        hashtextextended(
            'gis-service-migration:' || v_tenant_id || ':' || v_service_urn,
            0
        )
    );
    RETURN NEW;
END;
$$;

CREATE TRIGGER trg_gda_00_service_consumer_binding_migration_lock
BEFORE INSERT ON gda_control.service_consumer_binding
FOR EACH ROW EXECUTE FUNCTION gda_control.lock_gis_service_migration_scope();
CREATE TRIGGER trg_gda_00_service_consumer_binding_revocation_migration_lock
BEFORE INSERT ON gda_control.service_consumer_binding_revocation
FOR EACH ROW EXECUTE FUNCTION gda_control.lock_gis_service_migration_scope();
CREATE TRIGGER trg_gda_00_service_consumer_binding_renewal_migration_lock
BEFORE INSERT ON gda_control.service_consumer_binding_renewal
FOR EACH ROW EXECUTE FUNCTION gda_control.lock_gis_service_migration_scope();
CREATE TRIGGER trg_gda_00_gis_service_migration_impact_lock
BEFORE INSERT ON gda_control.gis_service_consumer_binding_migration_impact
FOR EACH ROW EXECUTE FUNCTION gda_control.lock_gis_service_migration_scope();

-- A table-level guard provides defence in depth around the original pointer
-- implementation.  Gateway callers cannot invoke that private implementation;
-- the marker is set only while the cutover function owns the service lock.
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
       ) = '' THEN
        RAISE EXCEPTION
            'cross-product GIS endpoint activation requires migration cutover authority'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER trg_gda_gis_service_migration_pointer_update
BEFORE UPDATE ON gda_control.gis_service
FOR EACH ROW EXECUTE FUNCTION
    gda_control.guard_gis_service_migration_pointer_update();

ALTER FUNCTION gda_control.activate_gis_service_endpoint(
    TEXT, TEXT, UUID, INTEGER, TEXT, TEXT, TEXT, TIMESTAMPTZ
) RENAME TO activate_gis_service_endpoint_unverified;

CREATE FUNCTION gda_control.activate_gis_service_endpoint(
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
    v_source_definition_id UUID;
    v_source_release_id UUID;
    v_source_product_version_id UUID;
    v_target_product_version_id UUID;
BEGIN
    IF p_tenant_id IS DISTINCT FROM gda_control.current_tenant() THEN
        RAISE EXCEPTION 'endpoint activation tenant context is missing or mismatched'
            USING ERRCODE = '42501';
    END IF;
    PERFORM pg_advisory_xact_lock(
        hashtextextended(
            'gis-service-migration:' || p_tenant_id || ':' || p_service_urn,
            0
        )
    );
    SELECT * INTO v_service
      FROM gda_control.gis_service
     WHERE tenant_id = p_tenant_id AND service_urn = p_service_urn
     FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'GIS service was not found' USING ERRCODE = 'P0002';
    END IF;
    IF v_service.active_endpoint_revision_id IS NOT NULL THEN
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
         WHERE endpoint.tenant_id = p_tenant_id
           AND endpoint.endpoint_revision_id =
               v_service.active_endpoint_revision_id;
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
         WHERE endpoint.tenant_id = p_tenant_id
           AND endpoint.endpoint_revision_id = p_endpoint_revision_id;
        IF v_source_product_version_id IS DISTINCT FROM
               v_target_product_version_id
           AND EXISTS (
               SELECT 1
                 FROM gda_control.service_consumer_binding AS binding
                WHERE binding.tenant_id = p_tenant_id
                  AND binding.service_urn = p_service_urn
                  AND binding.service_definition_version_id =
                      v_source_definition_id
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
           ) THEN
            RAISE EXCEPTION
                'cross-product GIS endpoint activation requires migration cutover authority'
                USING ERRCODE = '23514';
        END IF;
    END IF;
    RETURN gda_control.activate_gis_service_endpoint_unverified(
        p_tenant_id, p_service_urn, p_endpoint_revision_id,
        p_expected_state_version, p_actor_subject, p_reason,
        p_idempotency_key, p_occurred_at
    );
END;
$$;

CREATE FUNCTION gda_control.cutover_gis_service_migration(
    p_tenant_id TEXT,
    p_cutover_id UUID,
    p_service_urn TEXT,
    p_source_endpoint_revision_id UUID,
    p_target_endpoint_revision_id UUID,
    p_source_service_definition_version_id UUID,
    p_source_service_release_binding_id UUID,
    p_target_service_definition_version_id UUID,
    p_target_service_release_binding_id UUID,
    p_source_product_urn TEXT,
    p_from_product_version_id UUID,
    p_to_product_version_id UUID,
    p_expected_state_version INTEGER,
    p_actor_subject TEXT,
    p_reason TEXT,
    p_idempotency_key TEXT,
    p_occurred_at TIMESTAMPTZ
)
RETURNS SETOF gda_control.gis_service_migration_cutover
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, gda_control
SET row_security = on
AS $$
DECLARE
    v_service gda_control.gis_service%ROWTYPE;
    v_existing gda_control.gis_service_migration_cutover%ROWTYPE;
    v_result gda_control.gis_service_migration_cutover%ROWTYPE;
    v_source_definition_id UUID;
    v_source_release_id UUID;
    v_source_product_urn TEXT;
    v_source_product_version_id UUID;
    v_target_definition_id UUID;
    v_target_release_id UUID;
    v_target_product_urn TEXT;
    v_target_product_version_id UUID;
    v_target_deployment_state TEXT;
    v_source_binding_count INTEGER;
    v_source_consumer_count INTEGER;
    v_impact_count INTEGER;
    v_impact_binding_count INTEGER;
    v_acknowledged_count INTEGER;
    v_acknowledged_binding_count INTEGER;
    v_target_binding_count INTEGER;
    v_target_consumer_count INTEGER;
    v_impact_set_sha256 TEXT;
    v_acknowledgement_set_sha256 TEXT;
    v_target_binding_set_sha256 TEXT;
    v_to_state_version INTEGER;
    v_activation_event_id UUID;
    v_activation_idempotency_key TEXT;
    v_cutover_sha256 TEXT;
    v_effective_at TIMESTAMPTZ;
BEGIN
    IF p_tenant_id IS DISTINCT FROM gda_control.current_tenant() THEN
        RAISE EXCEPTION 'GIS service cutover tenant context is missing or mismatched'
            USING ERRCODE = '42501';
    END IF;
    IF p_source_endpoint_revision_id = p_target_endpoint_revision_id
       OR p_source_service_definition_version_id =
           p_target_service_definition_version_id
       OR p_source_service_release_binding_id =
           p_target_service_release_binding_id
       OR p_from_product_version_id = p_to_product_version_id
       OR NULLIF(btrim(p_actor_subject), '') IS NULL
       OR NULLIF(btrim(p_reason), '') IS NULL
       OR NULLIF(btrim(p_idempotency_key), '') IS NULL THEN
        RAISE EXCEPTION 'GIS service cutover request is incomplete or not a migration'
            USING ERRCODE = '22023';
    END IF;

    PERFORM pg_advisory_xact_lock(
        hashtextextended(
            'data-product-promotion:' || p_tenant_id || ':' ||
                p_source_product_urn,
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

    SELECT * INTO v_service
      FROM gda_control.gis_service
     WHERE tenant_id = p_tenant_id AND service_urn = p_service_urn
     FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'GIS service was not found' USING ERRCODE = 'P0002';
    END IF;

    SELECT cutover.* INTO v_existing
      FROM gda_control.gis_service_migration_cutover AS cutover
     WHERE cutover.tenant_id = p_tenant_id
       AND cutover.service_urn = p_service_urn
       AND (
           cutover.cutover_id = p_cutover_id
           OR cutover.idempotency_key = p_idempotency_key
       )
     ORDER BY (cutover.cutover_id = p_cutover_id) DESC
     LIMIT 1;
    IF FOUND THEN
        IF v_existing.cutover_id IS DISTINCT FROM p_cutover_id
           OR v_existing.source_endpoint_revision_id IS DISTINCT FROM
               p_source_endpoint_revision_id
           OR v_existing.target_endpoint_revision_id IS DISTINCT FROM
               p_target_endpoint_revision_id
           OR v_existing.source_service_definition_version_id IS DISTINCT FROM
               p_source_service_definition_version_id
           OR v_existing.source_service_release_binding_id IS DISTINCT FROM
               p_source_service_release_binding_id
           OR v_existing.target_service_definition_version_id IS DISTINCT FROM
               p_target_service_definition_version_id
           OR v_existing.target_service_release_binding_id IS DISTINCT FROM
               p_target_service_release_binding_id
           OR v_existing.source_product_urn IS DISTINCT FROM p_source_product_urn
           OR v_existing.from_product_version_id IS DISTINCT FROM
               p_from_product_version_id
           OR v_existing.to_product_version_id IS DISTINCT FROM
               p_to_product_version_id
           OR v_existing.from_state_version IS DISTINCT FROM
               p_expected_state_version
           OR v_existing.actor_subject IS DISTINCT FROM p_actor_subject
           OR v_existing.reason IS DISTINCT FROM p_reason
           OR v_existing.idempotency_key IS DISTINCT FROM p_idempotency_key
           OR v_existing.occurred_at IS DISTINCT FROM p_occurred_at THEN
            RAISE EXCEPTION 'GIS service cutover identity has different content'
                USING ERRCODE = '23505';
        END IF;
        RETURN NEXT v_existing;
        RETURN;
    END IF;

    IF v_service.endpoint_state_version <> p_expected_state_version
       OR v_service.active_endpoint_revision_id IS DISTINCT FROM
           p_source_endpoint_revision_id THEN
        RAISE EXCEPTION 'GIS service cutover source pointer CAS conflict'
            USING ERRCODE = '40001';
    END IF;
    IF p_occurred_at < v_service.updated_at OR p_occurred_at > v_effective_at THEN
        RAISE EXCEPTION 'GIS service cutover time is outside the active pointer window'
            USING ERRCODE = '23514';
    END IF;

    SELECT deployment.service_definition_version_id,
           deployment.service_release_binding_id,
           definition.source_product_urn,
           definition.source_data_product_version_id
      INTO v_source_definition_id, v_source_release_id,
           v_source_product_urn, v_source_product_version_id
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
       AND endpoint.endpoint_revision_id = p_source_endpoint_revision_id;
    SELECT deployment.service_definition_version_id,
           deployment.service_release_binding_id,
           definition.source_product_urn,
           definition.source_data_product_version_id,
           deployment.state
      INTO v_target_definition_id, v_target_release_id,
           v_target_product_urn, v_target_product_version_id,
           v_target_deployment_state
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
       AND endpoint.endpoint_revision_id = p_target_endpoint_revision_id;
    IF v_source_definition_id IS NULL OR v_target_definition_id IS NULL THEN
        RAISE EXCEPTION 'GIS service cutover endpoint lineage was not found'
            USING ERRCODE = 'P0002';
    END IF;
    IF v_source_definition_id IS DISTINCT FROM
           p_source_service_definition_version_id
       OR v_source_release_id IS DISTINCT FROM
           p_source_service_release_binding_id
       OR v_target_definition_id IS DISTINCT FROM
           p_target_service_definition_version_id
       OR v_target_release_id IS DISTINCT FROM
           p_target_service_release_binding_id
       OR v_source_product_urn IS DISTINCT FROM p_source_product_urn
       OR v_target_product_urn IS DISTINCT FROM p_source_product_urn
       OR v_source_product_version_id IS DISTINCT FROM p_from_product_version_id
       OR v_target_product_version_id IS DISTINCT FROM p_to_product_version_id
       OR v_target_deployment_state <> 'ready' THEN
        RAISE EXCEPTION 'GIS service cutover endpoint and release lineage mismatch'
            USING ERRCODE = '23514';
    END IF;

    WITH source_bindings AS (
        SELECT binding.*
          FROM gda_control.service_consumer_binding AS binding
         WHERE binding.tenant_id = p_tenant_id
           AND binding.service_urn = p_service_urn
           AND binding.service_definition_version_id =
               p_source_service_definition_version_id
           AND binding.service_release_binding_id =
               p_source_service_release_binding_id
           AND binding.created_at <= p_occurred_at
           AND binding.expires_at > v_effective_at
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
    SELECT count(*)::INTEGER, count(DISTINCT consumer_ref)::INTEGER
      INTO v_source_binding_count, v_source_consumer_count
      FROM source_bindings;
    IF v_source_binding_count = 0 THEN
        RAISE EXCEPTION 'GIS service cutover has no effective source consumers'
            USING ERRCODE = '23514';
    END IF;
    IF v_source_consumer_count <> v_source_binding_count THEN
        RAISE EXCEPTION 'GIS service cutover source consumer bindings are ambiguous'
            USING ERRCODE = '23514';
    END IF;

    WITH source_bindings AS (
        SELECT binding.service_consumer_binding_id
          FROM gda_control.service_consumer_binding AS binding
         WHERE binding.tenant_id = p_tenant_id
           AND binding.service_urn = p_service_urn
           AND binding.service_definition_version_id =
               p_source_service_definition_version_id
           AND binding.service_release_binding_id =
               p_source_service_release_binding_id
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
                  AND r.source_binding_id = binding.service_consumer_binding_id
           )
    ), impacts AS (
        SELECT impact.*
          FROM gda_control.gis_service_consumer_binding_migration_impact AS impact
          JOIN source_bindings AS source
            ON source.service_consumer_binding_id =
               impact.source_service_consumer_binding_id
         WHERE impact.tenant_id = p_tenant_id
           AND impact.service_urn = p_service_urn
           AND impact.source_service_definition_version_id =
               p_source_service_definition_version_id
           AND impact.source_service_release_binding_id =
               p_source_service_release_binding_id
           AND impact.target_service_definition_version_id =
               p_target_service_definition_version_id
           AND impact.target_service_release_binding_id =
               p_target_service_release_binding_id
           AND impact.source_product_urn = p_source_product_urn
           AND impact.from_product_version_id = p_from_product_version_id
           AND impact.to_product_version_id = p_to_product_version_id
           AND impact.recorded_at <= p_occurred_at
    )
    SELECT count(*)::INTEGER,
           count(DISTINCT source_service_consumer_binding_id)::INTEGER,
           encode(public.digest(convert_to(
               string_agg(
                   source_service_consumer_binding_id::text || ':' ||
                   impact_id::text || ':' || impact_sha256::text,
                   E'\n' ORDER BY source_service_consumer_binding_id, impact_id
               ), 'UTF8'), 'sha256'), 'hex')
      INTO v_impact_count, v_impact_binding_count, v_impact_set_sha256
      FROM impacts;
    IF v_impact_count <> v_source_binding_count
       OR v_impact_binding_count <> v_source_binding_count THEN
        RAISE EXCEPTION 'GIS service cutover impact set is incomplete or ambiguous'
            USING ERRCODE = '23514';
    END IF;

    WITH impacts AS (
        SELECT impact.*
          FROM gda_control.gis_service_consumer_binding_migration_impact AS impact
          JOIN gda_control.service_consumer_binding AS source
            ON source.tenant_id = impact.tenant_id
           AND source.service_consumer_binding_id =
               impact.source_service_consumer_binding_id
         WHERE impact.tenant_id = p_tenant_id
           AND impact.service_urn = p_service_urn
           AND impact.source_service_definition_version_id =
               p_source_service_definition_version_id
           AND impact.source_service_release_binding_id =
               p_source_service_release_binding_id
           AND impact.target_service_definition_version_id =
               p_target_service_definition_version_id
           AND impact.target_service_release_binding_id =
               p_target_service_release_binding_id
           AND impact.source_product_urn = p_source_product_urn
           AND impact.from_product_version_id = p_from_product_version_id
           AND impact.to_product_version_id = p_to_product_version_id
           AND impact.recorded_at <= p_occurred_at
           AND source.created_at <= p_occurred_at
           AND source.expires_at > v_effective_at
           AND NOT EXISTS (
               SELECT 1 FROM gda_control.service_consumer_binding_revocation AS r
                WHERE r.tenant_id = source.tenant_id
                  AND r.service_consumer_binding_id =
                      source.service_consumer_binding_id
           )
           AND NOT EXISTS (
               SELECT 1 FROM gda_control.service_consumer_binding_renewal AS r
                WHERE r.tenant_id = source.tenant_id
                  AND r.source_binding_id = source.service_consumer_binding_id
           )
    ), acknowledged AS (
        SELECT impact.source_service_consumer_binding_id,
               latest.migration_state_id, latest.state_sha256,
               latest.consumer_acknowledgement
          FROM impacts AS impact
          JOIN gda_control.consumer_binding_migration_notification_outbox AS notice
            ON notice.tenant_id = impact.tenant_id
           AND notice.notification_id = impact.notification_id
           AND notice.status = 'done'
           AND notice.receipt_sha256 IS NOT NULL
           AND notice.completed_at <= p_occurred_at
          JOIN gda_control.consumer_binding_migration_state AS source_state
            ON source_state.tenant_id = impact.tenant_id
           AND source_state.migration_state_id = impact.migration_state_id
          JOIN LATERAL (
              SELECT state.*
                FROM gda_control.consumer_binding_migration_state AS state
               WHERE state.tenant_id = source_state.tenant_id
                 AND state.binding_id = source_state.binding_id
                 AND state.from_product_version_id =
                     impact.from_product_version_id
                 AND state.to_product_version_id = impact.to_product_version_id
               ORDER BY state.state_version DESC
               LIMIT 1
          ) AS latest ON TRUE
         WHERE latest.notification_status = 'delivered'
           AND latest.consumer_acknowledgement IS NOT NULL
           AND latest.recorded_at <= p_occurred_at
           AND latest.consumer_acknowledgement->>'consumer_ref' =
               impact.consumer_ref
    )
    SELECT count(*)::INTEGER,
           count(DISTINCT source_service_consumer_binding_id)::INTEGER,
           encode(public.digest(convert_to(
               string_agg(
                   source_service_consumer_binding_id::text || ':' ||
                   migration_state_id::text || ':' || state_sha256::text || ':' ||
                   (consumer_acknowledgement->>'acknowledgement_ref'),
                   E'\n' ORDER BY source_service_consumer_binding_id,
                       migration_state_id
               ), 'UTF8'), 'sha256'), 'hex')
      INTO v_acknowledged_count, v_acknowledged_binding_count,
           v_acknowledgement_set_sha256
      FROM acknowledged;
    IF v_acknowledged_count <> v_source_binding_count
       OR v_acknowledged_binding_count <> v_source_binding_count THEN
        RAISE EXCEPTION
            'GIS service cutover requires delivered notice and current acknowledgement for every consumer'
            USING ERRCODE = '23514';
    END IF;

    WITH source_consumers AS (
        SELECT binding.consumer_ref
          FROM gda_control.service_consumer_binding AS binding
         WHERE binding.tenant_id = p_tenant_id
           AND binding.service_urn = p_service_urn
           AND binding.service_definition_version_id =
               p_source_service_definition_version_id
           AND binding.service_release_binding_id =
               p_source_service_release_binding_id
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
                  AND r.source_binding_id = binding.service_consumer_binding_id
           )
    ), target_bindings AS (
        SELECT binding.*
          FROM gda_control.service_consumer_binding AS binding
          JOIN source_consumers AS source
            ON source.consumer_ref = binding.consumer_ref
         WHERE binding.tenant_id = p_tenant_id
           AND binding.service_urn = p_service_urn
           AND binding.service_definition_version_id =
               p_target_service_definition_version_id
           AND binding.service_release_binding_id =
               p_target_service_release_binding_id
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
                  AND r.source_binding_id = binding.service_consumer_binding_id
           )
    )
    SELECT count(*)::INTEGER, count(DISTINCT consumer_ref)::INTEGER,
           encode(public.digest(convert_to(
               string_agg(
                   service_consumer_binding_id::text || ':' ||
                   binding_sha256::text,
                   E'\n' ORDER BY consumer_ref, service_consumer_binding_id
               ), 'UTF8'), 'sha256'), 'hex')
      INTO v_target_binding_count, v_target_consumer_count,
           v_target_binding_set_sha256
      FROM target_bindings;
    IF v_target_binding_count <> v_source_binding_count
       OR v_target_consumer_count <> v_source_binding_count THEN
        RAISE EXCEPTION
            'GIS service cutover requires one effective target-release binding per source consumer'
            USING ERRCODE = '23514';
    END IF;

    -- Lock every relation row used by the gate.  Product-state appends are
    -- already excluded by the product advisory lock; service grant lifecycle
    -- appends are excluded by the service advisory lock above.
    PERFORM 1
      FROM gda_control.gis_service_consumer_binding_migration_impact AS impact
     WHERE impact.tenant_id = p_tenant_id
       AND impact.service_urn = p_service_urn
       AND impact.source_service_definition_version_id =
           p_source_service_definition_version_id
       AND impact.source_service_release_binding_id =
           p_source_service_release_binding_id
       AND impact.target_service_definition_version_id =
           p_target_service_definition_version_id
       AND impact.target_service_release_binding_id =
           p_target_service_release_binding_id
     FOR SHARE;
    PERFORM 1
      FROM gda_control.consumer_binding_migration_notification_outbox AS notice
     WHERE notice.tenant_id = p_tenant_id
       AND EXISTS (
           SELECT 1
             FROM gda_control.gis_service_consumer_binding_migration_impact AS impact
            WHERE impact.tenant_id = notice.tenant_id
              AND impact.notification_id = notice.notification_id
              AND impact.service_urn = p_service_urn
              AND impact.target_service_release_binding_id =
                  p_target_service_release_binding_id
       )
     FOR SHARE;

    v_activation_idempotency_key :=
        'migration-cutover:' || p_cutover_id::text;
    PERFORM set_config(
        'gda.gis_service_migration_cutover_id', p_cutover_id::text, true
    );
    v_to_state_version :=
        gda_control.activate_gis_service_endpoint_unverified(
            p_tenant_id, p_service_urn, p_target_endpoint_revision_id,
            p_expected_state_version, p_actor_subject, p_reason,
            v_activation_idempotency_key, p_occurred_at
        );
    PERFORM set_config('gda.gis_service_migration_cutover_id', '', true);

    SELECT event.event_id INTO v_activation_event_id
      FROM gda_control.gis_service_endpoint_activation_event AS event
     WHERE event.tenant_id = p_tenant_id
       AND event.service_urn = p_service_urn
       AND event.idempotency_key = v_activation_idempotency_key
       AND event.from_endpoint_revision_id = p_source_endpoint_revision_id
       AND event.to_endpoint_revision_id = p_target_endpoint_revision_id
       AND event.from_state_version = p_expected_state_version
       AND event.to_state_version = v_to_state_version;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'GIS service cutover activation event was not recorded'
            USING ERRCODE = '40001';
    END IF;

    v_cutover_sha256 := gda_control.gis_service_migration_cutover_fingerprint(
        p_tenant_id, p_cutover_id, p_service_urn,
        p_source_endpoint_revision_id, p_target_endpoint_revision_id,
        p_source_service_definition_version_id,
        p_source_service_release_binding_id,
        p_target_service_definition_version_id,
        p_target_service_release_binding_id, p_source_product_urn,
        p_from_product_version_id, p_to_product_version_id,
        v_source_binding_count, v_impact_count, v_acknowledged_count,
        v_target_binding_count, v_impact_set_sha256,
        v_acknowledgement_set_sha256, v_target_binding_set_sha256,
        p_expected_state_version, v_to_state_version,
        v_activation_event_id, 'release_namespace_rollover',
        p_actor_subject, p_reason, p_idempotency_key, p_occurred_at
    );
    PERFORM set_config(
        'gda.gis_service_migration_cutover_insert_allowed', '1', true
    );
    INSERT INTO gda_control.gis_service_migration_cutover (
        tenant_id, cutover_id, service_urn,
        source_endpoint_revision_id, target_endpoint_revision_id,
        source_service_definition_version_id,
        source_service_release_binding_id,
        target_service_definition_version_id,
        target_service_release_binding_id, source_product_urn,
        from_product_version_id, to_product_version_id,
        source_binding_count, impact_count, acknowledged_count,
        target_binding_count, impact_set_sha256,
        acknowledgement_set_sha256, target_binding_set_sha256,
        from_state_version, to_state_version, activation_event_id,
        cache_transition_mode, actor_subject, reason, idempotency_key,
        occurred_at, cutover_sha256
    ) VALUES (
        p_tenant_id, p_cutover_id, p_service_urn,
        p_source_endpoint_revision_id, p_target_endpoint_revision_id,
        p_source_service_definition_version_id,
        p_source_service_release_binding_id,
        p_target_service_definition_version_id,
        p_target_service_release_binding_id, p_source_product_urn,
        p_from_product_version_id, p_to_product_version_id,
        v_source_binding_count, v_impact_count, v_acknowledged_count,
        v_target_binding_count, v_impact_set_sha256,
        v_acknowledgement_set_sha256, v_target_binding_set_sha256,
        p_expected_state_version, v_to_state_version,
        v_activation_event_id, 'release_namespace_rollover',
        p_actor_subject, p_reason, p_idempotency_key, p_occurred_at,
        v_cutover_sha256
    );
    PERFORM set_config(
        'gda.gis_service_migration_cutover_insert_allowed', '0', true
    );
    SELECT * INTO v_result
      FROM gda_control.gis_service_migration_cutover AS cutover
     WHERE cutover.tenant_id = p_tenant_id
       AND cutover.cutover_id = p_cutover_id;
    RETURN NEXT v_result;
END;
$$;

ALTER TABLE gda_control.gis_service_migration_cutover
    ENABLE ROW LEVEL SECURITY;
ALTER TABLE gda_control.gis_service_migration_cutover
    FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation
    ON gda_control.gis_service_migration_cutover
    USING (tenant_id = gda_control.current_tenant())
    WITH CHECK (tenant_id = gda_control.current_tenant());

REVOKE ALL ON TABLE gda_control.gis_service_migration_cutover
    FROM PUBLIC, gda_control_gateway;
GRANT SELECT ON TABLE gda_control.gis_service_migration_cutover
    TO gda_control_gateway;

REVOKE ALL ON FUNCTION gda_control.activate_gis_service_endpoint_unverified(
    TEXT, TEXT, UUID, INTEGER, TEXT, TEXT, TEXT, TIMESTAMPTZ
) FROM PUBLIC, gda_control_gateway;
REVOKE ALL ON FUNCTION gda_control.activate_gis_service_endpoint(
    TEXT, TEXT, UUID, INTEGER, TEXT, TEXT, TEXT, TIMESTAMPTZ
) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION gda_control.activate_gis_service_endpoint(
    TEXT, TEXT, UUID, INTEGER, TEXT, TEXT, TEXT, TIMESTAMPTZ
) TO gda_control_gateway;

REVOKE ALL ON FUNCTION gda_control.gis_service_migration_cutover_fingerprint(
    TEXT, UUID, TEXT, UUID, UUID, UUID, UUID, UUID, UUID, TEXT, UUID, UUID,
    INTEGER, INTEGER, INTEGER, INTEGER, TEXT, TEXT, TEXT, INTEGER, INTEGER,
    UUID, TEXT, TEXT, TEXT, TEXT, TIMESTAMPTZ
) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION gda_control.gis_service_migration_cutover_fingerprint(
    TEXT, UUID, TEXT, UUID, UUID, UUID, UUID, UUID, UUID, TEXT, UUID, UUID,
    INTEGER, INTEGER, INTEGER, INTEGER, TEXT, TEXT, TEXT, INTEGER, INTEGER,
    UUID, TEXT, TEXT, TEXT, TEXT, TIMESTAMPTZ
) TO gda_control_gateway;
REVOKE ALL ON FUNCTION gda_control.cutover_gis_service_migration(
    TEXT, UUID, TEXT, UUID, UUID, UUID, UUID, UUID, UUID, TEXT, UUID, UUID,
    INTEGER, TEXT, TEXT, TEXT, TIMESTAMPTZ
) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION gda_control.cutover_gis_service_migration(
    TEXT, UUID, TEXT, UUID, UUID, UUID, UUID, UUID, UUID, TEXT, UUID, UUID,
    INTEGER, TEXT, TEXT, TEXT, TIMESTAMPTZ
) TO gda_control_gateway;

REVOKE ALL ON FUNCTION gda_control.guard_gis_service_migration_cutover_insert()
    FROM PUBLIC;
REVOKE ALL ON FUNCTION gda_control.lock_gis_service_migration_scope()
    FROM PUBLIC;
REVOKE ALL ON FUNCTION gda_control.guard_gis_service_migration_pointer_update()
    FROM PUBLIC;
