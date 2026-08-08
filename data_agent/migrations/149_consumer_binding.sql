-- 149: Formal, immutable DataProduct consumer authority.
--
-- Transitional agent_data_requests grants remain available as a compatibility
-- fallback, but a DataProduct promotion first consults this version-ranged
-- binding ledger. Credentials are references only; secrets stay out of GDA.

CREATE TABLE IF NOT EXISTS gda_control.consumer_binding (
    tenant_id TEXT NOT NULL,
    binding_id UUID NOT NULL,
    product_urn TEXT NOT NULL,
    consumer_ref TEXT NOT NULL,
    purpose TEXT NOT NULL,
    scope JSONB NOT NULL,
    min_product_version TEXT,
    max_product_version TEXT,
    credential_ref TEXT NOT NULL,
    quota JSONB NOT NULL,
    expires_at TIMESTAMPTZ NOT NULL,
    compatibility_fingerprint CHAR(64) NOT NULL,
    compatibility_evidence JSONB NOT NULL,
    binding_sha256 CHAR(64) NOT NULL,
    created_by TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (tenant_id, binding_id),
    CONSTRAINT uq_gda_consumer_binding_id UNIQUE (binding_id),
    CONSTRAINT uq_gda_consumer_binding_fingerprint
        UNIQUE (tenant_id, binding_sha256),
    CONSTRAINT fk_gda_consumer_binding_product
        FOREIGN KEY (tenant_id, product_urn)
        REFERENCES gda_control.data_product(tenant_id, product_urn),
    CONSTRAINT ck_gda_consumer_binding_product_tenant CHECK (
        product_urn ~ '^gda://[a-z0-9][a-z0-9._-]{0,63}/data_product/[a-z0-9][a-z0-9._-]{0,127}$'
        AND split_part(product_urn, '/', 3) = tenant_id
    ),
    CONSTRAINT ck_gda_consumer_binding_consumer CHECK (
        consumer_ref ~ '^(human|workload|agent|service):[^[:space:]]+$'
        AND length(consumer_ref) BETWEEN 7 AND 512
    ),
    CONSTRAINT ck_gda_consumer_binding_text CHECK (
        NULLIF(btrim(purpose), '') IS NOT NULL
        AND NULLIF(btrim(credential_ref), '') IS NOT NULL
        AND NULLIF(btrim(created_by), '') IS NOT NULL
    ),
    CONSTRAINT ck_gda_consumer_binding_scope CHECK (
        jsonb_typeof(scope) = 'object' AND scope <> '{}'::jsonb
    ),
    CONSTRAINT ck_gda_consumer_binding_version_bounds CHECK (
        (min_product_version IS NULL OR min_product_version ~ '^v[0-9]+\.[0-9]+\.[0-9]+$')
        AND (max_product_version IS NULL OR max_product_version ~ '^v[0-9]+\.[0-9]+\.[0-9]+$')
        AND (
            min_product_version IS NULL OR max_product_version IS NULL
            OR string_to_array(substr(min_product_version, 2), '.')::numeric[]
                <= string_to_array(substr(max_product_version, 2), '.')::numeric[]
        )
    ),
    CONSTRAINT ck_gda_consumer_binding_quota CHECK (
        jsonb_typeof(quota) = 'object'
        AND (quota->>'max_packages') ~ '^[0-9]+$'
        AND (quota->>'max_packages')::integer BETWEEN 1 AND 100
        AND (
            quota->>'max_bytes' IS NULL
            OR (quota->>'max_bytes') ~ '^[0-9]+$'
        )
    ),
    CONSTRAINT ck_gda_consumer_binding_expiry CHECK (expires_at > created_at),
    CONSTRAINT ck_gda_consumer_binding_compatibility CHECK (
        compatibility_fingerprint ~ '^[0-9a-f]{64}$'
        AND jsonb_typeof(compatibility_evidence) = 'object'
        AND compatibility_evidence <> '{}'::jsonb
    ),
    CONSTRAINT ck_gda_consumer_binding_sha256 CHECK (
        binding_sha256 ~ '^[0-9a-f]{64}$'
    )
);

CREATE INDEX IF NOT EXISTS idx_gda_consumer_binding_product
    ON gda_control.consumer_binding(
        tenant_id, product_urn, expires_at, consumer_ref, binding_id
    );

CREATE OR REPLACE FUNCTION gda_control.record_consumer_binding(
    p_tenant_id TEXT,
    p_binding_id UUID,
    p_product_urn TEXT,
    p_consumer_ref TEXT,
    p_purpose TEXT,
    p_scope JSONB,
    p_min_product_version TEXT,
    p_max_product_version TEXT,
    p_credential_ref TEXT,
    p_quota JSONB,
    p_expires_at TIMESTAMPTZ,
    p_compatibility_fingerprint CHAR(64),
    p_compatibility_evidence JSONB,
    p_binding_sha256 CHAR(64),
    p_created_by TEXT,
    p_created_at TIMESTAMPTZ
)
RETURNS TABLE(binding_id UUID, created BOOLEAN)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, gda_control
SET row_security = on
AS $$
DECLARE
    v_existing gda_control.consumer_binding%ROWTYPE;
    v_inserted UUID;
BEGIN
    IF p_tenant_id IS DISTINCT FROM gda_control.current_tenant() THEN
        RAISE EXCEPTION 'consumer binding tenant context is missing or mismatched'
            USING ERRCODE = '42501';
    END IF;

    INSERT INTO gda_control.consumer_binding (
        tenant_id, binding_id, product_urn, consumer_ref, purpose, scope,
        min_product_version, max_product_version, credential_ref, quota,
        expires_at, compatibility_fingerprint, compatibility_evidence,
        binding_sha256, created_by, created_at
    ) VALUES (
        p_tenant_id, p_binding_id, p_product_urn, p_consumer_ref, p_purpose,
        p_scope, p_min_product_version, p_max_product_version,
        p_credential_ref, p_quota, p_expires_at, p_compatibility_fingerprint,
        p_compatibility_evidence, p_binding_sha256, p_created_by, p_created_at
    )
    ON CONFLICT DO NOTHING
    RETURNING gda_control.consumer_binding.binding_id INTO v_inserted;

    SELECT binding.* INTO v_existing
      FROM gda_control.consumer_binding AS binding
     WHERE binding.tenant_id = p_tenant_id
       AND (
           binding.binding_id = p_binding_id
           OR binding.binding_sha256 = p_binding_sha256
       )
     ORDER BY (binding.binding_id = p_binding_id) DESC
     LIMIT 1;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'consumer binding write was not visible'
            USING ERRCODE = '40001';
    END IF;

    IF v_existing.binding_id IS DISTINCT FROM p_binding_id
       OR v_existing.product_urn IS DISTINCT FROM p_product_urn
       OR v_existing.consumer_ref IS DISTINCT FROM p_consumer_ref
       OR v_existing.purpose IS DISTINCT FROM p_purpose
       OR v_existing.scope IS DISTINCT FROM p_scope
       OR v_existing.min_product_version IS DISTINCT FROM p_min_product_version
       OR v_existing.max_product_version IS DISTINCT FROM p_max_product_version
       OR v_existing.credential_ref IS DISTINCT FROM p_credential_ref
       OR v_existing.quota IS DISTINCT FROM p_quota
       OR v_existing.expires_at IS DISTINCT FROM p_expires_at
       OR v_existing.compatibility_fingerprint IS DISTINCT FROM p_compatibility_fingerprint
       OR v_existing.compatibility_evidence IS DISTINCT FROM p_compatibility_evidence
       OR v_existing.binding_sha256 IS DISTINCT FROM p_binding_sha256
       OR v_existing.created_by IS DISTINCT FROM p_created_by
       OR v_existing.created_at IS DISTINCT FROM p_created_at THEN
        RAISE EXCEPTION 'ConsumerBinding identity already has a different payload'
            USING ERRCODE = '23505';
    END IF;
    RETURN QUERY SELECT v_existing.binding_id, (v_inserted IS NOT NULL);
END;
$$;

CREATE OR REPLACE FUNCTION gda_control.active_consumer_binding_impact(
    p_tenant_id TEXT,
    p_product_urn TEXT,
    p_version_id UUID
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
    compatibility_evidence JSONB
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
           binding.compatibility_evidence
      FROM gda_control.consumer_binding AS binding
      JOIN gda_control.data_product_version AS version
        ON version.tenant_id = binding.tenant_id
       AND version.product_urn = binding.product_urn
       AND version.data_product_version_id = p_version_id
     WHERE p_tenant_id = gda_control.current_tenant()
       AND binding.tenant_id = p_tenant_id
       AND binding.product_urn = p_product_urn
       AND binding.expires_at > clock_timestamp()
       AND (
           binding.min_product_version IS NULL
           OR string_to_array(substr(version.version_key, 2), '.')::numeric[]
                >= string_to_array(substr(binding.min_product_version, 2), '.')::numeric[]
       )
       AND (
           binding.max_product_version IS NULL
           OR string_to_array(substr(version.version_key, 2), '.')::numeric[]
                <= string_to_array(substr(binding.max_product_version, 2), '.')::numeric[]
       )
     ORDER BY binding.consumer_ref, binding.binding_id
$$;

ALTER TABLE gda_control.consumer_binding ENABLE ROW LEVEL SECURITY;
ALTER TABLE gda_control.consumer_binding FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON gda_control.consumer_binding;
CREATE POLICY tenant_isolation ON gda_control.consumer_binding
    USING (tenant_id = gda_control.current_tenant())
    WITH CHECK (tenant_id = gda_control.current_tenant());

DROP TRIGGER IF EXISTS trg_gda_consumer_binding_immutable
    ON gda_control.consumer_binding;
CREATE TRIGGER trg_gda_consumer_binding_immutable
BEFORE UPDATE OR DELETE ON gda_control.consumer_binding
FOR EACH ROW EXECUTE FUNCTION gda_control.reject_immutable_mutation();

ALTER TABLE gda_control.data_product_promotion_impact
    ADD COLUMN IF NOT EXISTS consumer_authority TEXT NOT NULL
        DEFAULT 'transitional_distribution_grant',
    ADD COLUMN IF NOT EXISTS active_binding_count INTEGER NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS impacted_bindings JSONB NOT NULL DEFAULT '[]'::jsonb;

ALTER TABLE gda_control.data_product_promotion_impact
    ADD CONSTRAINT ck_gda_promotion_impact_consumer_authority CHECK (
        consumer_authority IN (
            'transitional_distribution_grant', 'consumer_binding'
        )
        AND active_binding_count >= 0
        AND jsonb_typeof(impacted_bindings) = 'array'
        AND jsonb_array_length(impacted_bindings) = active_binding_count
        AND (
            consumer_authority = 'transitional_distribution_grant'
            OR (
                active_grant_count = 0
                AND impacted_grants = '[]'::jsonb
            )
        )
    );

REVOKE ALL ON TABLE gda_control.consumer_binding
    FROM PUBLIC, gda_control_gateway;
GRANT SELECT ON TABLE gda_control.consumer_binding TO gda_control_gateway;

REVOKE ALL ON FUNCTION gda_control.record_consumer_binding(
    TEXT, UUID, TEXT, TEXT, TEXT, JSONB, TEXT, TEXT, TEXT, JSONB,
    TIMESTAMPTZ, CHAR(64), JSONB, CHAR(64), TEXT, TIMESTAMPTZ
) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION gda_control.record_consumer_binding(
    TEXT, UUID, TEXT, TEXT, TEXT, JSONB, TEXT, TEXT, TEXT, JSONB,
    TIMESTAMPTZ, CHAR(64), JSONB, CHAR(64), TEXT, TIMESTAMPTZ
) TO gda_control_gateway;

REVOKE ALL ON FUNCTION gda_control.active_consumer_binding_impact(
    TEXT, TEXT, UUID
) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION gda_control.active_consumer_binding_impact(
    TEXT, TEXT, UUID
) TO gda_control_gateway;
