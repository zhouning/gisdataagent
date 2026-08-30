-- 217: Bind product migration notifications to exact GIS service releases.
--
-- The product ConsumerBinding migration outbox remains the only provider
-- delivery authority. This append-only fact records which exact GIS service
-- consumer binding and source/target releases are affected by that notice.

CREATE TABLE gda_control.gis_service_consumer_binding_migration_impact (
    tenant_id TEXT NOT NULL,
    impact_id UUID NOT NULL,
    source_service_consumer_binding_id UUID NOT NULL,
    source_binding_sha256 CHAR(64) NOT NULL,
    service_urn TEXT NOT NULL,
    consumer_ref TEXT NOT NULL,
    source_service_definition_version_id UUID NOT NULL,
    source_service_release_binding_id UUID NOT NULL,
    target_service_definition_version_id UUID NOT NULL,
    target_service_release_binding_id UUID NOT NULL,
    source_product_urn TEXT NOT NULL,
    from_product_version_id UUID NOT NULL,
    to_product_version_id UUID NOT NULL,
    migration_state_id UUID NOT NULL,
    notification_id UUID NOT NULL,
    recorded_by TEXT NOT NULL,
    recorded_at TIMESTAMPTZ NOT NULL,
    impact_sha256 CHAR(64) NOT NULL,
    CONSTRAINT pk_gda_gis_service_consumer_binding_migration_impact
        PRIMARY KEY (tenant_id, impact_id),
    CONSTRAINT uq_gda_gis_service_consumer_binding_migration_impact_id
        UNIQUE (impact_id),
    CONSTRAINT uq_gda_gis_service_consumer_binding_migration_impact_sha
        UNIQUE (tenant_id, impact_sha256),
    CONSTRAINT uq_gda_gis_service_consumer_binding_migration_impact_identity
        UNIQUE (
            tenant_id, source_service_consumer_binding_id,
            migration_state_id, target_service_release_binding_id
        ),
    CONSTRAINT fk_gda_gis_service_consumer_binding_migration_impact_binding
        FOREIGN KEY (tenant_id, source_service_consumer_binding_id)
        REFERENCES gda_control.service_consumer_binding(
            tenant_id, service_consumer_binding_id
        ),
    CONSTRAINT fk_gda_gis_service_consumer_binding_migration_impact_source_def
        FOREIGN KEY (tenant_id, source_service_definition_version_id)
        REFERENCES gda_control.gis_service_definition_version(
            tenant_id, service_definition_version_id
        ),
    CONSTRAINT fk_gda_gis_service_consumer_binding_migration_impact_target_def
        FOREIGN KEY (tenant_id, target_service_definition_version_id)
        REFERENCES gda_control.gis_service_definition_version(
            tenant_id, service_definition_version_id
        ),
    CONSTRAINT fk_gda_gis_service_consumer_binding_migration_impact_source_release
        FOREIGN KEY (
            tenant_id, source_service_definition_version_id,
            source_service_release_binding_id
        ) REFERENCES gda_control.service_release_binding(
            tenant_id, service_definition_version_id,
            service_release_binding_id
        ),
    CONSTRAINT fk_gda_gis_service_consumer_binding_migration_impact_target_release
        FOREIGN KEY (
            tenant_id, target_service_definition_version_id,
            target_service_release_binding_id
        ) REFERENCES gda_control.service_release_binding(
            tenant_id, service_definition_version_id,
            service_release_binding_id
        ),
    CONSTRAINT fk_gda_gis_service_consumer_binding_migration_impact_state
        FOREIGN KEY (tenant_id, migration_state_id)
        REFERENCES gda_control.consumer_binding_migration_state(
            tenant_id, migration_state_id
        ),
    CONSTRAINT fk_gda_gis_service_consumer_binding_migration_impact_notice
        FOREIGN KEY (tenant_id, notification_id)
        REFERENCES gda_control.consumer_binding_migration_notification_outbox(
            tenant_id, notification_id
        ),
    CONSTRAINT fk_gda_gis_service_consumer_binding_migration_impact_from_product
        FOREIGN KEY (tenant_id, source_product_urn, from_product_version_id)
        REFERENCES gda_control.data_product_version(
            tenant_id, product_urn, data_product_version_id
        ),
    CONSTRAINT fk_gda_gis_service_consumer_binding_migration_impact_to_product
        FOREIGN KEY (tenant_id, source_product_urn, to_product_version_id)
        REFERENCES gda_control.data_product_version(
            tenant_id, product_urn, data_product_version_id
        ),
    CONSTRAINT ck_gda_gis_service_consumer_binding_migration_impact_service
        CHECK (
            service_urn ~ '^gda://[a-z0-9][a-z0-9._-]{0,63}/gis_service/[a-z0-9][a-z0-9._-]{0,127}$'
            AND split_part(service_urn, '/', 3) = tenant_id
        ),
    CONSTRAINT ck_gda_gis_service_consumer_binding_migration_impact_consumer
        CHECK (
            consumer_ref ~ '^(human|workload|agent|service):[^[:space:]]+$'
            AND length(consumer_ref) BETWEEN 7 AND 512
        ),
    CONSTRAINT ck_gda_gis_service_consumer_binding_migration_impact_product
        CHECK (
            source_product_urn ~ '^gda://[a-z0-9][a-z0-9._-]{0,63}/data_product/[a-z0-9][a-z0-9._-]{0,127}$'
            AND split_part(source_product_urn, '/', 3) = tenant_id
            AND from_product_version_id <> to_product_version_id
        ),
    CONSTRAINT ck_gda_gis_service_consumer_binding_migration_impact_distinct
        CHECK (
            source_service_definition_version_id <> target_service_definition_version_id
            AND source_service_release_binding_id <> target_service_release_binding_id
        ),
    CONSTRAINT ck_gda_gis_service_consumer_binding_migration_impact_actor
        CHECK (recorded_by ~ '^(human|workload|agent|service):[^[:space:]]+$'),
    CONSTRAINT ck_gda_gis_service_consumer_binding_migration_impact_hash
        CHECK (
            source_binding_sha256 ~ '^[0-9a-f]{64}$'
            AND impact_sha256 ~ '^[0-9a-f]{64}$'
        )
);

CREATE INDEX idx_gda_gis_service_consumer_binding_migration_impact_notice
    ON gda_control.gis_service_consumer_binding_migration_impact(
        tenant_id, notification_id, recorded_at, impact_id
    );
CREATE INDEX idx_gda_gis_service_consumer_binding_migration_impact_service
    ON gda_control.gis_service_consumer_binding_migration_impact(
        tenant_id, service_urn, consumer_ref, recorded_at, impact_id
    );

CREATE OR REPLACE FUNCTION gda_control.gis_service_consumer_binding_migration_impact_fingerprint(
    p_tenant_id TEXT,
    p_impact_id UUID,
    p_source_service_consumer_binding_id UUID,
    p_source_binding_sha256 TEXT,
    p_service_urn TEXT,
    p_consumer_ref TEXT,
    p_source_service_definition_version_id UUID,
    p_source_service_release_binding_id UUID,
    p_target_service_definition_version_id UUID,
    p_target_service_release_binding_id UUID,
    p_source_product_urn TEXT,
    p_from_product_version_id UUID,
    p_to_product_version_id UUID,
    p_migration_state_id UUID,
    p_notification_id UUID
)
RETURNS TEXT
LANGUAGE sql
IMMUTABLE
SET search_path = pg_catalog, public
AS $$
    WITH payload AS (
        SELECT jsonb_build_object(
            'from_product_version_id', p_from_product_version_id::text,
            'impact_id', p_impact_id::text,
            'migration_state_id', p_migration_state_id::text,
            'notification_id', p_notification_id::text,
            'schema', 'gda.gis_service_consumer_binding_migration_impact.v1',
            'service_urn', p_service_urn,
            'source_binding_sha256', p_source_binding_sha256,
            'source_product_urn', p_source_product_urn,
            'source_service_consumer_binding_id',
                p_source_service_consumer_binding_id::text,
            'source_service_definition_version_id',
                p_source_service_definition_version_id::text,
            'source_service_release_binding_id',
                p_source_service_release_binding_id::text,
            'target_service_definition_version_id',
                p_target_service_definition_version_id::text,
            'target_service_release_binding_id',
                p_target_service_release_binding_id::text,
            'tenant_id', p_tenant_id,
            'to_product_version_id', p_to_product_version_id::text,
            'consumer_ref', p_consumer_ref
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

CREATE OR REPLACE FUNCTION gda_control.guard_gis_service_consumer_binding_migration_impact_insert()
RETURNS TRIGGER
LANGUAGE plpgsql
SET search_path = pg_catalog, gda_control
AS $$
BEGIN
    IF COALESCE(
        current_setting('gda.gis_service_consumer_binding_migration_impact_allowed', true), ''
    ) <> '1' THEN
        RAISE EXCEPTION
            'use gda_control.record_gis_service_consumer_binding_migration_impact()'
            USING ERRCODE = '55000';
    END IF;
    IF gda_control.current_tenant() IS NULL
       OR NEW.tenant_id IS DISTINCT FROM gda_control.current_tenant() THEN
        RAISE EXCEPTION 'GIS service migration impact tenant context is missing or mismatched'
            USING ERRCODE = '42501';
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER trg_gda_gis_service_consumer_binding_migration_impact_insert
BEFORE INSERT ON gda_control.gis_service_consumer_binding_migration_impact
FOR EACH ROW EXECUTE FUNCTION
    gda_control.guard_gis_service_consumer_binding_migration_impact_insert();

CREATE TRIGGER trg_gda_gis_service_consumer_binding_migration_impact_immutable
BEFORE UPDATE OR DELETE
ON gda_control.gis_service_consumer_binding_migration_impact
FOR EACH ROW EXECUTE FUNCTION gda_control.reject_immutable_mutation();

CREATE OR REPLACE FUNCTION gda_control.record_gis_service_consumer_binding_migration_impact(
    p_tenant_id TEXT,
    p_impact_id UUID,
    p_source_service_consumer_binding_id UUID,
    p_source_binding_sha256 CHAR(64),
    p_service_urn TEXT,
    p_consumer_ref TEXT,
    p_source_service_definition_version_id UUID,
    p_source_service_release_binding_id UUID,
    p_target_service_definition_version_id UUID,
    p_target_service_release_binding_id UUID,
    p_source_product_urn TEXT,
    p_from_product_version_id UUID,
    p_to_product_version_id UUID,
    p_migration_state_id UUID,
    p_notification_id UUID,
    p_recorded_by TEXT,
    p_recorded_at TIMESTAMPTZ,
    p_impact_sha256 CHAR(64)
)
RETURNS TABLE(impact_id UUID, created BOOLEAN)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, gda_control
SET row_security = on
AS $$
DECLARE
    v_service_binding gda_control.service_consumer_binding%ROWTYPE;
    v_source_definition gda_control.gis_service_definition_version%ROWTYPE;
    v_target_definition gda_control.gis_service_definition_version%ROWTYPE;
    v_state gda_control.consumer_binding_migration_state%ROWTYPE;
    v_notification gda_control.consumer_binding_migration_notification_outbox%ROWTYPE;
    v_product_binding gda_control.consumer_binding%ROWTYPE;
    v_existing gda_control.gis_service_consumer_binding_migration_impact%ROWTYPE;
    v_inserted UUID;
BEGIN
    IF p_tenant_id IS DISTINCT FROM gda_control.current_tenant() THEN
        RAISE EXCEPTION 'GIS service migration impact tenant context is missing or mismatched'
            USING ERRCODE = '42501';
    END IF;
    IF p_source_service_definition_version_id = p_target_service_definition_version_id
       OR p_source_service_release_binding_id = p_target_service_release_binding_id THEN
        RAISE EXCEPTION 'GIS service migration impact source and target must differ'
            USING ERRCODE = '22023';
    END IF;
    IF gda_control.gis_service_consumer_binding_migration_impact_fingerprint(
        p_tenant_id, p_impact_id, p_source_service_consumer_binding_id,
        p_source_binding_sha256, p_service_urn, p_consumer_ref,
        p_source_service_definition_version_id, p_source_service_release_binding_id,
        p_target_service_definition_version_id, p_target_service_release_binding_id,
        p_source_product_urn, p_from_product_version_id, p_to_product_version_id,
        p_migration_state_id, p_notification_id
    ) IS DISTINCT FROM p_impact_sha256::TEXT THEN
        RAISE EXCEPTION 'GIS service migration impact fingerprint does not match payload'
            USING ERRCODE = '23514';
    END IF;

    SELECT binding.* INTO v_service_binding
      FROM gda_control.service_consumer_binding AS binding
     WHERE binding.tenant_id = p_tenant_id
       AND binding.service_consumer_binding_id = p_source_service_consumer_binding_id
     FOR SHARE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'source GIS ServiceConsumerBinding was not found'
            USING ERRCODE = 'P0002';
    END IF;
    IF v_service_binding.binding_sha256 IS DISTINCT FROM p_source_binding_sha256
       OR v_service_binding.service_urn IS DISTINCT FROM p_service_urn
       OR v_service_binding.service_definition_version_id
            IS DISTINCT FROM p_source_service_definition_version_id
       OR v_service_binding.service_release_binding_id
            IS DISTINCT FROM p_source_service_release_binding_id
       OR v_service_binding.consumer_ref IS DISTINCT FROM p_consumer_ref THEN
        RAISE EXCEPTION 'GIS service migration impact source binding identity mismatch'
            USING ERRCODE = '23514';
    END IF;

    SELECT definition.* INTO v_source_definition
      FROM gda_control.gis_service_definition_version AS definition
     WHERE definition.tenant_id = p_tenant_id
       AND definition.service_definition_version_id =
           p_source_service_definition_version_id
     FOR SHARE;
    SELECT definition.* INTO v_target_definition
      FROM gda_control.gis_service_definition_version AS definition
     WHERE definition.tenant_id = p_tenant_id
       AND definition.service_definition_version_id =
           p_target_service_definition_version_id
     FOR SHARE;
    IF NOT FOUND OR v_source_definition.service_definition_version_id IS NULL THEN
        RAISE EXCEPTION 'GIS service migration impact definition was not found'
            USING ERRCODE = 'P0002';
    END IF;
    IF v_source_definition.service_urn IS DISTINCT FROM p_service_urn
       OR v_target_definition.service_urn IS DISTINCT FROM p_service_urn
       OR v_source_definition.service_type <> 'vector_tile'
       OR v_target_definition.service_type <> 'vector_tile'
       OR v_source_definition.source_product_urn IS DISTINCT FROM p_source_product_urn
       OR v_target_definition.source_product_urn IS DISTINCT FROM p_source_product_urn
       OR v_source_definition.source_data_product_version_id
            IS DISTINCT FROM p_from_product_version_id
       OR v_target_definition.source_data_product_version_id
            IS DISTINCT FROM p_to_product_version_id THEN
        RAISE EXCEPTION 'GIS service migration impact definition lineage mismatch'
            USING ERRCODE = '23514';
    END IF;

    PERFORM 1
      FROM gda_control.service_release_binding AS release
     WHERE release.tenant_id = p_tenant_id
       AND release.service_definition_version_id = p_source_service_definition_version_id
       AND release.service_release_binding_id = p_source_service_release_binding_id;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'source GIS service release was not found'
            USING ERRCODE = 'P0002';
    END IF;
    PERFORM 1
      FROM gda_control.service_release_binding AS release
     WHERE release.tenant_id = p_tenant_id
       AND release.service_definition_version_id = p_target_service_definition_version_id
       AND release.service_release_binding_id = p_target_service_release_binding_id;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'target GIS service release was not found'
            USING ERRCODE = 'P0002';
    END IF;

    SELECT state.* INTO v_state
      FROM gda_control.consumer_binding_migration_state AS state
     WHERE state.tenant_id = p_tenant_id
       AND state.migration_state_id = p_migration_state_id
     FOR SHARE;
    IF NOT FOUND
       OR v_state.product_urn IS DISTINCT FROM p_source_product_urn
       OR v_state.from_product_version_id IS DISTINCT FROM p_from_product_version_id
       OR v_state.to_product_version_id IS DISTINCT FROM p_to_product_version_id THEN
        RAISE EXCEPTION 'GIS service migration impact product migration state mismatch'
            USING ERRCODE = '23514';
    END IF;
    SELECT binding.* INTO v_product_binding
      FROM gda_control.consumer_binding AS binding
     WHERE binding.tenant_id = p_tenant_id
       AND binding.binding_id = v_state.binding_id
     FOR SHARE;
    IF NOT FOUND OR v_product_binding.consumer_ref IS DISTINCT FROM p_consumer_ref THEN
        RAISE EXCEPTION 'GIS service and product migration consumers do not match'
            USING ERRCODE = '23514';
    END IF;

    SELECT notification.* INTO v_notification
      FROM gda_control.consumer_binding_migration_notification_outbox AS notification
     WHERE notification.tenant_id = p_tenant_id
       AND notification.notification_id = p_notification_id
     FOR SHARE;
    IF NOT FOUND
       OR v_notification.migration_state_id IS DISTINCT FROM p_migration_state_id
       OR v_notification.binding_id IS DISTINCT FROM v_state.binding_id
       OR v_notification.product_urn IS DISTINCT FROM p_source_product_urn
       OR v_notification.from_product_version_id IS DISTINCT FROM p_from_product_version_id
       OR v_notification.to_product_version_id IS DISTINCT FROM p_to_product_version_id THEN
        RAISE EXCEPTION 'GIS service migration impact notification mismatch'
            USING ERRCODE = '23514';
    END IF;

    SELECT impact.* INTO v_existing
      FROM gda_control.gis_service_consumer_binding_migration_impact AS impact
     WHERE impact.tenant_id = p_tenant_id
       AND (
           impact.impact_id = p_impact_id
           OR impact.impact_sha256 = p_impact_sha256
           OR (
               impact.source_service_consumer_binding_id =
                   p_source_service_consumer_binding_id
               AND impact.migration_state_id = p_migration_state_id
               AND impact.target_service_release_binding_id =
                   p_target_service_release_binding_id
           )
       )
     ORDER BY (impact.impact_id = p_impact_id) DESC
     LIMIT 1;
    IF FOUND THEN
        IF v_existing.impact_id <> p_impact_id
           OR v_existing.source_binding_sha256 IS DISTINCT FROM p_source_binding_sha256
           OR v_existing.service_urn IS DISTINCT FROM p_service_urn
           OR v_existing.consumer_ref IS DISTINCT FROM p_consumer_ref
           OR v_existing.source_service_definition_version_id
                IS DISTINCT FROM p_source_service_definition_version_id
           OR v_existing.source_service_release_binding_id
                IS DISTINCT FROM p_source_service_release_binding_id
           OR v_existing.target_service_definition_version_id
                IS DISTINCT FROM p_target_service_definition_version_id
           OR v_existing.target_service_release_binding_id
                IS DISTINCT FROM p_target_service_release_binding_id
           OR v_existing.source_product_urn IS DISTINCT FROM p_source_product_urn
           OR v_existing.from_product_version_id IS DISTINCT FROM p_from_product_version_id
           OR v_existing.to_product_version_id IS DISTINCT FROM p_to_product_version_id
           OR v_existing.migration_state_id IS DISTINCT FROM p_migration_state_id
           OR v_existing.notification_id IS DISTINCT FROM p_notification_id
           OR v_existing.recorded_by IS DISTINCT FROM p_recorded_by
           OR v_existing.recorded_at IS DISTINCT FROM p_recorded_at
           OR v_existing.impact_sha256 IS DISTINCT FROM p_impact_sha256 THEN
            RAISE EXCEPTION 'GIS service migration impact identity has different content'
                USING ERRCODE = '23505';
        END IF;
        RETURN QUERY SELECT v_existing.impact_id, FALSE;
        RETURN;
    END IF;

    PERFORM set_config(
        'gda.gis_service_consumer_binding_migration_impact_allowed', '1', true
    );
    INSERT INTO gda_control.gis_service_consumer_binding_migration_impact (
        tenant_id, impact_id, source_service_consumer_binding_id,
        source_binding_sha256, service_urn, consumer_ref,
        source_service_definition_version_id, source_service_release_binding_id,
        target_service_definition_version_id, target_service_release_binding_id,
        source_product_urn, from_product_version_id, to_product_version_id,
        migration_state_id, notification_id, recorded_by, recorded_at,
        impact_sha256
    ) VALUES (
        p_tenant_id, p_impact_id, p_source_service_consumer_binding_id,
        p_source_binding_sha256, p_service_urn, p_consumer_ref,
        p_source_service_definition_version_id, p_source_service_release_binding_id,
        p_target_service_definition_version_id, p_target_service_release_binding_id,
        p_source_product_urn, p_from_product_version_id, p_to_product_version_id,
        p_migration_state_id, p_notification_id, p_recorded_by, p_recorded_at,
        p_impact_sha256
    ) RETURNING gis_service_consumer_binding_migration_impact.impact_id
        INTO v_inserted;
    PERFORM set_config(
        'gda.gis_service_consumer_binding_migration_impact_allowed', '0', true
    );
    RETURN QUERY SELECT v_inserted, TRUE;
END;
$$;

ALTER TABLE gda_control.gis_service_consumer_binding_migration_impact
    ENABLE ROW LEVEL SECURITY;
ALTER TABLE gda_control.gis_service_consumer_binding_migration_impact
    FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation
    ON gda_control.gis_service_consumer_binding_migration_impact
    USING (tenant_id = gda_control.current_tenant())
    WITH CHECK (tenant_id = gda_control.current_tenant());

REVOKE ALL ON TABLE gda_control.gis_service_consumer_binding_migration_impact
    FROM PUBLIC, gda_control_gateway;
GRANT SELECT ON TABLE gda_control.gis_service_consumer_binding_migration_impact
    TO gda_control_gateway;
REVOKE ALL ON FUNCTION gda_control.record_gis_service_consumer_binding_migration_impact(
    TEXT, UUID, UUID, CHAR(64), TEXT, TEXT, UUID, UUID, UUID, UUID, TEXT,
    UUID, UUID, UUID, UUID, TEXT, TIMESTAMPTZ, CHAR(64)
) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION gda_control.record_gis_service_consumer_binding_migration_impact(
    TEXT, UUID, UUID, CHAR(64), TEXT, TEXT, UUID, UUID, UUID, UUID, TEXT,
    UUID, UUID, UUID, UUID, TEXT, TIMESTAMPTZ, CHAR(64)
) TO gda_control_gateway;
