-- 150: Append-only consumer migration state for DataProduct promotion.
--
-- Compatibility, notification delivery, migration deadlines and consumer
-- acknowledgements are facts about a specific from/to version transition, not
-- mutable columns on the durable ConsumerBinding. Every change is therefore a
-- new CAS-linked state row and shares the product promotion advisory lock.

CREATE TABLE IF NOT EXISTS gda_control.consumer_binding_migration_state (
    tenant_id TEXT NOT NULL,
    migration_state_id UUID NOT NULL,
    binding_id UUID NOT NULL,
    product_urn TEXT NOT NULL,
    from_product_version_id UUID NOT NULL,
    to_product_version_id UUID NOT NULL,
    state_version INTEGER NOT NULL,
    compatibility_conclusion TEXT NOT NULL,
    compatibility_evidence JSONB NOT NULL,
    notification_status TEXT NOT NULL,
    notification_evidence JSONB NOT NULL,
    migration_deadline TIMESTAMPTZ,
    consumer_acknowledgement JSONB,
    previous_state_sha256 CHAR(64),
    recorded_by TEXT NOT NULL,
    recorded_at TIMESTAMPTZ NOT NULL,
    state_sha256 CHAR(64) NOT NULL,
    PRIMARY KEY (tenant_id, migration_state_id),
    CONSTRAINT uq_gda_consumer_migration_state_id
        UNIQUE (migration_state_id),
    CONSTRAINT uq_gda_consumer_migration_state_version
        UNIQUE (
            tenant_id, binding_id, from_product_version_id,
            to_product_version_id, state_version
        ),
    CONSTRAINT uq_gda_consumer_migration_state_sha
        UNIQUE (tenant_id, state_sha256),
    CONSTRAINT fk_gda_consumer_migration_state_binding
        FOREIGN KEY (tenant_id, binding_id)
        REFERENCES gda_control.consumer_binding(tenant_id, binding_id),
    CONSTRAINT fk_gda_consumer_migration_state_from_version
        FOREIGN KEY (tenant_id, product_urn, from_product_version_id)
        REFERENCES gda_control.data_product_version(
            tenant_id, product_urn, data_product_version_id
        ),
    CONSTRAINT fk_gda_consumer_migration_state_to_version
        FOREIGN KEY (tenant_id, product_urn, to_product_version_id)
        REFERENCES gda_control.data_product_version(
            tenant_id, product_urn, data_product_version_id
        ),
    CONSTRAINT ck_gda_consumer_migration_state_product_tenant CHECK (
        product_urn ~ '^gda://[a-z0-9][a-z0-9._-]{0,63}/data_product/[a-z0-9][a-z0-9._-]{0,127}$'
        AND split_part(product_urn, '/', 3) = tenant_id
    ),
    CONSTRAINT ck_gda_consumer_migration_state_versions CHECK (
        from_product_version_id <> to_product_version_id
        AND state_version >= 1
        AND (
            (state_version = 1 AND previous_state_sha256 IS NULL)
            OR (state_version > 1 AND previous_state_sha256 IS NOT NULL)
        )
    ),
    CONSTRAINT ck_gda_consumer_migration_state_conclusion CHECK (
        compatibility_conclusion IN (
            'backward_compatible', 'breaking', 'indeterminate'
        )
        AND jsonb_typeof(compatibility_evidence) = 'object'
        AND compatibility_evidence <> '{}'::jsonb
    ),
    CONSTRAINT ck_gda_consumer_migration_state_notification CHECK (
        notification_status IN (
            'not_required', 'pending', 'delivered', 'failed'
        )
        AND jsonb_typeof(notification_evidence) = 'object'
        AND (
            notification_status IN ('delivered', 'failed')
            OR notification_evidence = '{}'::jsonb
        )
        AND (
            notification_status NOT IN ('delivered', 'failed')
            OR notification_evidence <> '{}'::jsonb
        )
    ),
    CONSTRAINT ck_gda_consumer_migration_state_acknowledgement CHECK (
        consumer_acknowledgement IS NULL
        OR (
            jsonb_typeof(consumer_acknowledgement) = 'object'
            AND consumer_acknowledgement <> '{}'::jsonb
            AND consumer_acknowledgement->>'consumer_ref'
                ~ '^(human|workload|agent|service):[^[:space:]]+$'
            AND NULLIF(
                btrim(consumer_acknowledgement->>'acknowledgement_ref'), ''
            ) IS NOT NULL
            AND jsonb_typeof(consumer_acknowledgement->'evidence') = 'object'
            AND consumer_acknowledgement->'evidence' <> '{}'::jsonb
            AND (consumer_acknowledgement->>'acknowledged_at')::TIMESTAMPTZ
                <= recorded_at
        )
    ),
    CONSTRAINT ck_gda_consumer_migration_state_semantics CHECK (
        (
            compatibility_conclusion = 'backward_compatible'
            AND notification_status = 'not_required'
            AND notification_evidence = '{}'::jsonb
            AND migration_deadline IS NULL
            AND consumer_acknowledgement IS NULL
        )
        OR (
            compatibility_conclusion = 'breaking'
            AND notification_status <> 'not_required'
            AND migration_deadline IS NOT NULL
            AND (
                consumer_acknowledgement IS NULL
                OR notification_status = 'delivered'
            )
        )
        OR (
            compatibility_conclusion = 'indeterminate'
            AND consumer_acknowledgement IS NULL
        )
    ),
    CONSTRAINT ck_gda_consumer_migration_state_actor CHECK (
        recorded_by ~ '^(human|workload|agent|service):[^[:space:]]+$'
    ),
    CONSTRAINT ck_gda_consumer_migration_state_sha CHECK (
        state_sha256 ~ '^[0-9a-f]{64}$'
        AND (
            previous_state_sha256 IS NULL
            OR previous_state_sha256 ~ '^[0-9a-f]{64}$'
        )
    )
);

CREATE INDEX IF NOT EXISTS idx_gda_consumer_migration_state_transition
    ON gda_control.consumer_binding_migration_state(
        tenant_id, product_urn, from_product_version_id,
        to_product_version_id, binding_id, state_version DESC
    );

CREATE OR REPLACE FUNCTION gda_control.lock_consumer_binding_promotion_scope()
RETURNS TRIGGER
LANGUAGE plpgsql
SET search_path = pg_catalog, gda_control
AS $$
BEGIN
    PERFORM pg_advisory_xact_lock(
        hashtextextended(
            'data-product-promotion:' || NEW.tenant_id || ':' || NEW.product_urn,
            0
        )
    );
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_gda_consumer_binding_promotion_lock
    ON gda_control.consumer_binding;
CREATE TRIGGER trg_gda_consumer_binding_promotion_lock
BEFORE INSERT ON gda_control.consumer_binding
FOR EACH ROW EXECUTE FUNCTION gda_control.lock_consumer_binding_promotion_scope();

CREATE OR REPLACE FUNCTION gda_control.guard_consumer_migration_state_insert()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    IF COALESCE(
        current_setting('gda.consumer_migration_state_allowed', true), ''
    ) <> '1' THEN
        RAISE EXCEPTION
            'use gda_control.record_consumer_binding_migration_state()'
            USING ERRCODE = '55000';
    END IF;
    IF gda_control.current_tenant() IS NULL
       OR NEW.tenant_id IS DISTINCT FROM gda_control.current_tenant() THEN
        RAISE EXCEPTION 'consumer migration state tenant is mismatched'
            USING ERRCODE = '42501';
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER trg_gda_consumer_migration_state_insert
BEFORE INSERT ON gda_control.consumer_binding_migration_state
FOR EACH ROW EXECUTE FUNCTION gda_control.guard_consumer_migration_state_insert();

CREATE TRIGGER trg_gda_consumer_migration_state_immutable
BEFORE UPDATE OR DELETE ON gda_control.consumer_binding_migration_state
FOR EACH ROW EXECUTE FUNCTION gda_control.reject_immutable_mutation();

CREATE OR REPLACE FUNCTION gda_control.record_consumer_binding_migration_state(
    p_tenant_id TEXT,
    p_migration_state_id UUID,
    p_binding_id UUID,
    p_product_urn TEXT,
    p_from_product_version_id UUID,
    p_to_product_version_id UUID,
    p_state_version INTEGER,
    p_compatibility_conclusion TEXT,
    p_compatibility_evidence JSONB,
    p_notification_status TEXT,
    p_notification_evidence JSONB,
    p_migration_deadline TIMESTAMPTZ,
    p_consumer_acknowledgement JSONB,
    p_previous_state_sha256 CHAR(64),
    p_recorded_by TEXT,
    p_recorded_at TIMESTAMPTZ,
    p_state_sha256 CHAR(64)
)
RETURNS TABLE(migration_state_id UUID, created BOOLEAN)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, gda_control
SET row_security = on
AS $$
DECLARE
    v_binding gda_control.consumer_binding%ROWTYPE;
    v_existing gda_control.consumer_binding_migration_state%ROWTYPE;
    v_latest gda_control.consumer_binding_migration_state%ROWTYPE;
    v_inserted UUID;
BEGIN
    IF p_tenant_id IS DISTINCT FROM gda_control.current_tenant() THEN
        RAISE EXCEPTION
            'consumer migration state tenant context is missing or mismatched'
            USING ERRCODE = '42501';
    END IF;

    PERFORM pg_advisory_xact_lock(
        hashtextextended(
            'data-product-promotion:' || p_tenant_id || ':' || p_product_urn,
            0
        )
    );

    SELECT binding.* INTO v_binding
      FROM gda_control.consumer_binding AS binding
     WHERE binding.tenant_id = p_tenant_id
       AND binding.binding_id = p_binding_id;
    IF NOT FOUND
       OR v_binding.product_urn IS DISTINCT FROM p_product_urn THEN
        RAISE EXCEPTION 'ConsumerBinding was not found for migration state'
            USING ERRCODE = 'P0002';
    END IF;
    IF p_consumer_acknowledgement IS NOT NULL
       AND p_consumer_acknowledgement->>'consumer_ref'
           IS DISTINCT FROM v_binding.consumer_ref THEN
        RAISE EXCEPTION
            'consumer acknowledgement actor does not match ConsumerBinding'
            USING ERRCODE = '42501';
    END IF;
    IF p_consumer_acknowledgement IS NOT NULL
       AND p_recorded_by IS DISTINCT FROM v_binding.consumer_ref THEN
        RAISE EXCEPTION
            'consumer acknowledgement must be recorded by the bound consumer'
            USING ERRCODE = '42501';
    END IF;

    SELECT state.* INTO v_existing
      FROM gda_control.consumer_binding_migration_state AS state
     WHERE state.tenant_id = p_tenant_id
       AND state.migration_state_id = p_migration_state_id;
    IF FOUND THEN
        IF v_existing.binding_id IS DISTINCT FROM p_binding_id
           OR v_existing.product_urn IS DISTINCT FROM p_product_urn
           OR v_existing.from_product_version_id
                IS DISTINCT FROM p_from_product_version_id
           OR v_existing.to_product_version_id
                IS DISTINCT FROM p_to_product_version_id
           OR v_existing.state_version IS DISTINCT FROM p_state_version
           OR v_existing.compatibility_conclusion
                IS DISTINCT FROM p_compatibility_conclusion
           OR v_existing.compatibility_evidence
                IS DISTINCT FROM p_compatibility_evidence
           OR v_existing.notification_status IS DISTINCT FROM p_notification_status
           OR v_existing.notification_evidence
                IS DISTINCT FROM p_notification_evidence
           OR v_existing.migration_deadline IS DISTINCT FROM p_migration_deadline
           OR v_existing.consumer_acknowledgement
                IS DISTINCT FROM p_consumer_acknowledgement
           OR v_existing.previous_state_sha256
                IS DISTINCT FROM p_previous_state_sha256
           OR v_existing.recorded_by IS DISTINCT FROM p_recorded_by
           OR v_existing.recorded_at IS DISTINCT FROM p_recorded_at
           OR v_existing.state_sha256 IS DISTINCT FROM p_state_sha256 THEN
            RAISE EXCEPTION
                'consumer migration state identity already has a different payload'
                USING ERRCODE = '23505';
        END IF;
        RETURN QUERY SELECT v_existing.migration_state_id, FALSE;
        RETURN;
    END IF;

    SELECT state.* INTO v_existing
      FROM gda_control.consumer_binding_migration_state AS state
     WHERE state.tenant_id = p_tenant_id
       AND state.state_sha256 = p_state_sha256;
    IF FOUND THEN
        RAISE EXCEPTION
            'consumer migration state fingerprint has a different identity'
            USING ERRCODE = '23505';
    END IF;

    SELECT state.* INTO v_latest
      FROM gda_control.consumer_binding_migration_state AS state
     WHERE state.tenant_id = p_tenant_id
       AND state.binding_id = p_binding_id
       AND state.from_product_version_id = p_from_product_version_id
       AND state.to_product_version_id = p_to_product_version_id
     ORDER BY state.state_version DESC
     LIMIT 1
     FOR UPDATE;
    IF FOUND THEN
        IF p_state_version <> v_latest.state_version + 1
           OR p_previous_state_sha256 IS DISTINCT FROM v_latest.state_sha256 THEN
            RAISE EXCEPTION
                'consumer migration state compare-and-swap precondition failed'
                USING ERRCODE = '40001';
        END IF;
    ELSIF p_state_version <> 1 OR p_previous_state_sha256 IS NOT NULL THEN
        RAISE EXCEPTION 'initial consumer migration state must start at version 1'
            USING ERRCODE = '40001';
    END IF;

    PERFORM set_config('gda.consumer_migration_state_allowed', '1', true);
    INSERT INTO gda_control.consumer_binding_migration_state (
        tenant_id, migration_state_id, binding_id, product_urn,
        from_product_version_id, to_product_version_id, state_version,
        compatibility_conclusion, compatibility_evidence,
        notification_status, notification_evidence, migration_deadline,
        consumer_acknowledgement, previous_state_sha256,
        recorded_by, recorded_at, state_sha256
    ) VALUES (
        p_tenant_id, p_migration_state_id, p_binding_id, p_product_urn,
        p_from_product_version_id, p_to_product_version_id, p_state_version,
        p_compatibility_conclusion, p_compatibility_evidence,
        p_notification_status, p_notification_evidence, p_migration_deadline,
        p_consumer_acknowledgement, p_previous_state_sha256,
        p_recorded_by, p_recorded_at, p_state_sha256
    )
    RETURNING
        gda_control.consumer_binding_migration_state.migration_state_id
        INTO v_inserted;
    PERFORM set_config('gda.consumer_migration_state_allowed', '0', true);

    RETURN QUERY SELECT v_inserted, TRUE;
END;
$$;

CREATE OR REPLACE FUNCTION gda_control.active_consumer_binding_impact(
    p_tenant_id TEXT,
    p_product_urn TEXT,
    p_from_product_version_id UUID,
    p_to_product_version_id UUID
)
RETURNS TABLE (
    binding_id UUID,
    consumer_ref TEXT,
    purpose TEXT,
    scope JSONB,
    min_product_version TEXT,
    max_product_version TEXT,
    credential_ref TEXT,
    quota JSONB,
    expires_at TIMESTAMPTZ,
    compatibility_fingerprint CHAR(64),
    binding_compatibility_evidence JSONB,
    migration_state_id UUID,
    migration_state_version INTEGER,
    compatibility_conclusion TEXT,
    transition_compatibility_evidence JSONB,
    notification_status TEXT,
    notification_evidence JSONB,
    migration_deadline TIMESTAMPTZ,
    consumer_acknowledgement JSONB,
    migration_state_sha256 CHAR(64)
)
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog, gda_control
SET row_security = on
AS $$
    SELECT binding.binding_id,
           binding.consumer_ref,
           binding.purpose,
           binding.scope,
           binding.min_product_version,
           binding.max_product_version,
           binding.credential_ref,
           binding.quota,
           binding.expires_at,
           binding.compatibility_fingerprint,
           binding.compatibility_evidence,
           state.migration_state_id,
           state.state_version,
           COALESCE(state.compatibility_conclusion, 'indeterminate'),
           COALESCE(
               state.compatibility_evidence,
               binding.compatibility_evidence
           ),
           COALESCE(state.notification_status, 'pending'),
           COALESCE(state.notification_evidence, '{}'::jsonb),
           state.migration_deadline,
           state.consumer_acknowledgement,
           state.state_sha256
      FROM gda_control.consumer_binding AS binding
      JOIN gda_control.data_product_version AS source
        ON source.tenant_id = binding.tenant_id
       AND source.product_urn = binding.product_urn
       AND source.data_product_version_id = p_from_product_version_id
      JOIN gda_control.data_product_version AS target
        ON target.tenant_id = binding.tenant_id
       AND target.product_urn = binding.product_urn
       AND target.data_product_version_id = p_to_product_version_id
      LEFT JOIN LATERAL (
          SELECT migration.*
            FROM gda_control.consumer_binding_migration_state AS migration
           WHERE migration.tenant_id = binding.tenant_id
             AND migration.binding_id = binding.binding_id
             AND migration.from_product_version_id = p_from_product_version_id
             AND migration.to_product_version_id = p_to_product_version_id
           ORDER BY migration.state_version DESC
           LIMIT 1
      ) AS state ON TRUE
     WHERE p_tenant_id = gda_control.current_tenant()
       AND binding.tenant_id = p_tenant_id
       AND binding.product_urn = p_product_urn
       AND binding.expires_at > clock_timestamp()
       AND (
           binding.min_product_version IS NULL
           OR string_to_array(substr(source.version_key, 2), '.')::numeric[]
                >= string_to_array(
                    substr(binding.min_product_version, 2), '.'
                )::numeric[]
       )
       AND (
           binding.max_product_version IS NULL
           OR string_to_array(substr(source.version_key, 2), '.')::numeric[]
                <= string_to_array(
                    substr(binding.max_product_version, 2), '.'
                )::numeric[]
       )
     ORDER BY binding.consumer_ref, binding.binding_id
$$;

ALTER TABLE gda_control.data_product_promotion_impact
    DROP CONSTRAINT ck_gda_promotion_impact_counts;

ALTER TABLE gda_control.data_product_promotion_impact
    ADD CONSTRAINT ck_gda_promotion_impact_counts CHECK (
        active_grant_count >= 0
        AND active_binding_count >= 0
        AND impacted_consumer_count >= 0
        AND remaining_package_quota >= 0
        AND (
            (
                consumer_authority = 'consumer_binding'
                AND impacted_consumer_count <= active_binding_count
            )
            OR (
                consumer_authority = 'transitional_distribution_grant'
                AND impacted_consumer_count <= active_grant_count
            )
        )
    );

ALTER TABLE gda_control.data_product_promotion_impact
    ADD COLUMN IF NOT EXISTS consumer_migration_ready BOOLEAN NOT NULL
        DEFAULT TRUE,
    ADD COLUMN IF NOT EXISTS promotion_blockers JSONB NOT NULL
        DEFAULT '[]'::jsonb;

ALTER TABLE gda_control.data_product_promotion_impact
    ADD CONSTRAINT ck_gda_promotion_impact_migration_readiness CHECK (
        jsonb_typeof(promotion_blockers) = 'array'
        AND (
            consumer_migration_ready
            OR jsonb_array_length(promotion_blockers) > 0
        )
        AND (
            NOT consumer_migration_ready
            OR jsonb_array_length(promotion_blockers) = 0
        )
    );

ALTER TABLE gda_control.consumer_binding_migration_state
    ENABLE ROW LEVEL SECURITY;
ALTER TABLE gda_control.consumer_binding_migration_state
    FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation
    ON gda_control.consumer_binding_migration_state
    USING (tenant_id = gda_control.current_tenant())
    WITH CHECK (tenant_id = gda_control.current_tenant());

REVOKE ALL ON TABLE gda_control.consumer_binding_migration_state
    FROM PUBLIC, gda_control_gateway;
GRANT SELECT ON TABLE gda_control.consumer_binding_migration_state
    TO gda_control_gateway;

REVOKE ALL ON FUNCTION gda_control.record_consumer_binding_migration_state(
    TEXT, UUID, UUID, TEXT, UUID, UUID, INTEGER, TEXT, JSONB, TEXT, JSONB,
    TIMESTAMPTZ, JSONB, CHAR(64), TEXT, TIMESTAMPTZ, CHAR(64)
) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION gda_control.record_consumer_binding_migration_state(
    TEXT, UUID, UUID, TEXT, UUID, UUID, INTEGER, TEXT, JSONB, TEXT, JSONB,
    TIMESTAMPTZ, JSONB, CHAR(64), TEXT, TIMESTAMPTZ, CHAR(64)
) TO gda_control_gateway;

REVOKE ALL ON FUNCTION gda_control.active_consumer_binding_impact(
    TEXT, TEXT, UUID, UUID
) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION gda_control.active_consumer_binding_impact(
    TEXT, TEXT, UUID, UUID
) TO gda_control_gateway;
