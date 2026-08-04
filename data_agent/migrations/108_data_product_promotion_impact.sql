-- 108: Snapshot active consumer impact before advancing a DataProductVersion.
--
-- Existing version-locked distribution grants remain the transitional consumer
-- evidence. The gateway receives only a tenant-scoped function, not direct
-- access to the full request table.

ALTER TABLE gda_control.data_product_event
    DROP CONSTRAINT ck_gda_data_product_event_type;

ALTER TABLE gda_control.data_product_event
    ADD CONSTRAINT ck_gda_data_product_event_type CHECK (
        event_type IN (
            'published', 'advanced', 'staged', 'rolled_back', 'promoted'
        )
    );

CREATE TABLE gda_control.data_product_promotion_impact (
    tenant_id TEXT NOT NULL,
    impact_id UUID NOT NULL,
    product_urn TEXT NOT NULL,
    from_version_id UUID NOT NULL,
    to_version_id UUID NOT NULL,
    impact_fingerprint CHAR(64) NOT NULL,
    active_grant_count INTEGER NOT NULL,
    impacted_consumer_count INTEGER NOT NULL,
    remaining_package_quota INTEGER NOT NULL,
    impacted_grants JSONB NOT NULL,
    acknowledgement_mode TEXT NOT NULL,
    assessed_by TEXT NOT NULL,
    assessed_at TIMESTAMPTZ NOT NULL,
    acknowledged_at TIMESTAMPTZ,
    PRIMARY KEY (tenant_id, impact_id),
    CONSTRAINT fk_gda_promotion_impact_product
        FOREIGN KEY (tenant_id, product_urn)
        REFERENCES gda_control.data_product(tenant_id, product_urn),
    CONSTRAINT fk_gda_promotion_impact_from_version
        FOREIGN KEY (tenant_id, product_urn, from_version_id)
        REFERENCES gda_control.data_product_version(
            tenant_id, product_urn, data_product_version_id
        ),
    CONSTRAINT fk_gda_promotion_impact_to_version
        FOREIGN KEY (tenant_id, product_urn, to_version_id)
        REFERENCES gda_control.data_product_version(
            tenant_id, product_urn, data_product_version_id
        ),
    CONSTRAINT ck_gda_promotion_impact_versions CHECK (
        from_version_id <> to_version_id
    ),
    CONSTRAINT ck_gda_promotion_impact_fingerprint CHECK (
        impact_fingerprint ~ '^[0-9a-f]{64}$'
    ),
    CONSTRAINT ck_gda_promotion_impact_counts CHECK (
        active_grant_count >= 0
        AND impacted_consumer_count >= 0
        AND impacted_consumer_count <= active_grant_count
        AND remaining_package_quota >= 0
    ),
    CONSTRAINT ck_gda_promotion_impact_grants CHECK (
        jsonb_typeof(impacted_grants) = 'array'
        AND jsonb_array_length(impacted_grants) = active_grant_count
    ),
    CONSTRAINT ck_gda_promotion_impact_acknowledgement CHECK (
        (
            acknowledgement_mode = 'pending'
            AND acknowledged_at IS NULL
        )
        OR (
            acknowledgement_mode IN ('not_required', 'explicit')
            AND acknowledged_at IS NOT NULL
        )
    ),
    CONSTRAINT ck_gda_promotion_impact_actor CHECK (
        NULLIF(btrim(assessed_by), '') IS NOT NULL
    )
);

ALTER TABLE gda_control.data_product_event
    ADD COLUMN promotion_impact_id UUID;

ALTER TABLE gda_control.data_product_event
    ADD CONSTRAINT fk_gda_data_product_event_promotion_impact
    FOREIGN KEY (tenant_id, promotion_impact_id)
    REFERENCES gda_control.data_product_promotion_impact(tenant_id, impact_id);

CREATE INDEX idx_gda_promotion_impact_product
    ON gda_control.data_product_promotion_impact(
        tenant_id, product_urn, assessed_at DESC
    );

CREATE INDEX idx_dreq_active_product_version_consumer
    ON agent_data_requests(
        product_tenant_id, product_urn, data_product_version_id, expires_at
    )
    WHERE status = 'approved' AND revoked_at IS NULL;

CREATE FUNCTION gda_control.active_distribution_grant_impact(
    p_tenant_id TEXT,
    p_product_urn TEXT,
    p_version_id UUID
)
RETURNS TABLE (
    request_id INTEGER,
    requester TEXT,
    asset_id INTEGER,
    locked_version_key TEXT,
    expires_at TIMESTAMP,
    granted_package_quota INTEGER,
    packages_created BIGINT,
    packages_remaining INTEGER
)
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog
AS $$
    SELECT request.id,
           request.requester::text,
           request.asset_id,
           request.data_product_version_key,
           request.expires_at,
           request.granted_package_quota,
           COUNT(DISTINCT item.package_id) AS packages_created,
           GREATEST(
               request.granted_package_quota
                   - COUNT(DISTINCT item.package_id)::integer,
               0
           ) AS packages_remaining
      FROM public.agent_data_requests request
      LEFT JOIN public.agent_distribution_package_items item
        ON item.grant_request_id = request.id
     WHERE p_tenant_id = gda_control.current_tenant()
       AND request.product_tenant_id = p_tenant_id
       AND request.product_urn = p_product_urn
       AND request.data_product_version_id = p_version_id
       AND request.status = 'approved'
       AND request.revoked_at IS NULL
       AND request.expires_at > now()
     GROUP BY request.id, request.requester, request.asset_id,
              request.data_product_version_key, request.expires_at,
              request.granted_package_quota
     ORDER BY request.requester, request.id
$$;

CREATE TRIGGER trg_gda_data_product_promotion_impact_immutable
BEFORE UPDATE OR DELETE ON gda_control.data_product_promotion_impact
FOR EACH ROW EXECUTE FUNCTION gda_control.reject_immutable_mutation();

ALTER TABLE gda_control.data_product_promotion_impact ENABLE ROW LEVEL SECURITY;
ALTER TABLE gda_control.data_product_promotion_impact FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation
    ON gda_control.data_product_promotion_impact
    USING (tenant_id = gda_control.current_tenant())
    WITH CHECK (tenant_id = gda_control.current_tenant());

REVOKE ALL ON FUNCTION gda_control.active_distribution_grant_impact(
    TEXT, TEXT, UUID
) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION gda_control.active_distribution_grant_impact(
    TEXT, TEXT, UUID
) TO gda_control_gateway;
GRANT SELECT, INSERT ON gda_control.data_product_promotion_impact
    TO gda_control_gateway;
