-- 100: Governed DataProductVersion registry.
--
-- A DataProductVersion exists only after standard mapping and quality gates
-- pass. Versions and lifecycle events are append-only; rollback moves the
-- product's current pointer without rewriting published evidence.

CREATE TABLE gda_control.data_product (
    tenant_id TEXT NOT NULL,
    product_urn TEXT NOT NULL,
    product_slug TEXT NOT NULL,
    title TEXT NOT NULL,
    description TEXT NOT NULL,
    domain TEXT NOT NULL,
    owner_ref TEXT NOT NULL,
    governance_ref JSONB NOT NULL,
    current_version_id UUID,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (tenant_id, product_urn),
    CONSTRAINT uq_gda_data_product_slug UNIQUE (tenant_id, product_slug),
    CONSTRAINT ck_gda_data_product_urn CHECK (
        product_urn ~ '^gda://[a-z0-9][a-z0-9._-]{0,63}/data_product/[a-z0-9][a-z0-9._-]{0,127}$'
        AND split_part(product_urn, '/', 3) = tenant_id
    ),
    CONSTRAINT ck_gda_data_product_slug CHECK (
        product_slug ~ '^[a-z0-9][a-z0-9-]{1,127}$'
    ),
    CONSTRAINT ck_gda_data_product_text CHECK (
        NULLIF(btrim(title), '') IS NOT NULL
        AND NULLIF(btrim(description), '') IS NOT NULL
        AND NULLIF(btrim(domain), '') IS NOT NULL
        AND NULLIF(btrim(owner_ref), '') IS NOT NULL
    ),
    CONSTRAINT ck_gda_data_product_governance CHECK (
        jsonb_typeof(governance_ref) = 'object'
        AND NULLIF(btrim(governance_ref->>'classification'), '') IS NOT NULL
        AND NULLIF(btrim(governance_ref->>'visibility'), '') IS NOT NULL
        AND NULLIF(btrim(governance_ref->>'license_id'), '') IS NOT NULL
        AND NULLIF(btrim(governance_ref->>'attribution'), '') IS NOT NULL
    )
);

CREATE TABLE gda_control.data_product_version (
    tenant_id TEXT NOT NULL,
    data_product_version_id UUID PRIMARY KEY,
    product_urn TEXT NOT NULL,
    version_key TEXT NOT NULL,
    predecessor_version_id UUID,
    source_resource_version_id UUID NOT NULL,
    output_resource_version_id UUID NOT NULL,
    standard_version_ref TEXT NOT NULL,
    mapping_contract JSONB NOT NULL,
    quality_contract JSONB NOT NULL,
    quality_verdict TEXT NOT NULL,
    quality_evidence_artifact_id UUID NOT NULL,
    distribution_manifest JSONB NOT NULL,
    manifest_sha256 CHAR(64) NOT NULL,
    published_by TEXT NOT NULL,
    published_at TIMESTAMPTZ NOT NULL,
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_gda_data_product_version_tenant_id
        UNIQUE (tenant_id, data_product_version_id),
    CONSTRAINT uq_gda_data_product_version_product_id
        UNIQUE (tenant_id, product_urn, data_product_version_id),
    CONSTRAINT uq_gda_data_product_version_key
        UNIQUE (tenant_id, product_urn, version_key),
    CONSTRAINT fk_gda_data_product_version_product
        FOREIGN KEY (tenant_id, product_urn)
        REFERENCES gda_control.data_product(tenant_id, product_urn),
    CONSTRAINT fk_gda_data_product_version_predecessor
        FOREIGN KEY (tenant_id, product_urn, predecessor_version_id)
        REFERENCES gda_control.data_product_version(
            tenant_id, product_urn, data_product_version_id
        ),
    CONSTRAINT fk_gda_data_product_version_source
        FOREIGN KEY (tenant_id, source_resource_version_id)
        REFERENCES gda_control.resource_version(tenant_id, resource_version_id),
    CONSTRAINT fk_gda_data_product_version_output
        FOREIGN KEY (tenant_id, output_resource_version_id)
        REFERENCES gda_control.resource_version(tenant_id, resource_version_id),
    CONSTRAINT fk_gda_data_product_version_quality_artifact
        FOREIGN KEY (tenant_id, quality_evidence_artifact_id)
        REFERENCES gda_control.artifact(tenant_id, artifact_id),
    CONSTRAINT ck_gda_data_product_version_key CHECK (
        version_key ~ '^v[0-9]+\.[0-9]+\.[0-9]+$'
    ),
    CONSTRAINT ck_gda_data_product_version_resources CHECK (
        source_resource_version_id <> output_resource_version_id
    ),
    CONSTRAINT ck_gda_data_product_version_standard CHECK (
        NULLIF(btrim(standard_version_ref), '') IS NOT NULL
    ),
    CONSTRAINT ck_gda_data_product_version_mapping CHECK (
        jsonb_typeof(mapping_contract) = 'object'
        AND mapping_contract <> '{}'::jsonb
    ),
    CONSTRAINT ck_gda_data_product_version_quality CHECK (
        quality_verdict = 'passed'
        AND jsonb_typeof(quality_contract) = 'object'
        AND quality_contract <> '{}'::jsonb
        AND quality_contract->>'verdict' = 'passed'
    ),
    CONSTRAINT ck_gda_data_product_version_distribution CHECK (
        jsonb_typeof(distribution_manifest) = 'object'
        AND distribution_manifest <> '{}'::jsonb
    ),
    CONSTRAINT ck_gda_data_product_version_sha256 CHECK (
        manifest_sha256 ~ '^[0-9a-f]{64}$'
    ),
    CONSTRAINT ck_gda_data_product_version_actor CHECK (
        NULLIF(btrim(published_by), '') IS NOT NULL
    ),
    CONSTRAINT ck_gda_data_product_version_not_self_predecessor CHECK (
        predecessor_version_id IS NULL
        OR predecessor_version_id <> data_product_version_id
    )
);

ALTER TABLE gda_control.data_product
    ADD CONSTRAINT fk_gda_data_product_current_version
    FOREIGN KEY (tenant_id, product_urn, current_version_id)
    REFERENCES gda_control.data_product_version(
        tenant_id, product_urn, data_product_version_id
    );

CREATE TABLE gda_control.data_product_event (
    tenant_id TEXT NOT NULL,
    event_id UUID PRIMARY KEY,
    product_urn TEXT NOT NULL,
    event_type TEXT NOT NULL,
    from_version_id UUID,
    to_version_id UUID NOT NULL,
    actor_subject TEXT NOT NULL,
    reason TEXT NOT NULL,
    idempotency_key TEXT NOT NULL,
    occurred_at TIMESTAMPTZ NOT NULL,
    CONSTRAINT uq_gda_data_product_event_tenant_id UNIQUE (tenant_id, event_id),
    CONSTRAINT uq_gda_data_product_event_idempotency
        UNIQUE (tenant_id, product_urn, idempotency_key),
    CONSTRAINT fk_gda_data_product_event_product
        FOREIGN KEY (tenant_id, product_urn)
        REFERENCES gda_control.data_product(tenant_id, product_urn),
    CONSTRAINT fk_gda_data_product_event_from_version
        FOREIGN KEY (tenant_id, product_urn, from_version_id)
        REFERENCES gda_control.data_product_version(
            tenant_id, product_urn, data_product_version_id
        ),
    CONSTRAINT fk_gda_data_product_event_to_version
        FOREIGN KEY (tenant_id, product_urn, to_version_id)
        REFERENCES gda_control.data_product_version(
            tenant_id, product_urn, data_product_version_id
        ),
    CONSTRAINT ck_gda_data_product_event_type CHECK (
        event_type IN ('published', 'advanced', 'rolled_back')
    ),
    CONSTRAINT ck_gda_data_product_event_actor CHECK (
        NULLIF(btrim(actor_subject), '') IS NOT NULL
        AND NULLIF(btrim(reason), '') IS NOT NULL
        AND NULLIF(btrim(idempotency_key), '') IS NOT NULL
    ),
    CONSTRAINT ck_gda_data_product_event_versions CHECK (
        (event_type = 'published' AND from_version_id IS NULL)
        OR
        (event_type <> 'published' AND from_version_id IS NOT NULL
            AND from_version_id <> to_version_id)
    )
);

CREATE INDEX idx_gda_data_product_version_product
    ON gda_control.data_product_version(tenant_id, product_urn, published_at DESC);
CREATE INDEX idx_gda_data_product_event_product
    ON gda_control.data_product_event(tenant_id, product_urn, occurred_at DESC);

CREATE OR REPLACE FUNCTION gda_control.guard_data_product_update()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    IF NEW.tenant_id IS DISTINCT FROM OLD.tenant_id
       OR NEW.product_urn IS DISTINCT FROM OLD.product_urn
       OR NEW.product_slug IS DISTINCT FROM OLD.product_slug
       OR NEW.title IS DISTINCT FROM OLD.title
       OR NEW.description IS DISTINCT FROM OLD.description
       OR NEW.domain IS DISTINCT FROM OLD.domain
       OR NEW.owner_ref IS DISTINCT FROM OLD.owner_ref
       OR NEW.governance_ref IS DISTINCT FROM OLD.governance_ref
       OR NEW.created_at IS DISTINCT FROM OLD.created_at THEN
        RAISE EXCEPTION 'only the DataProduct current version pointer may change'
            USING ERRCODE = '55000';
    END IF;
    IF NEW.current_version_id IS NOT DISTINCT FROM OLD.current_version_id
       OR NEW.updated_at < OLD.updated_at THEN
        RAISE EXCEPTION 'DataProduct pointer update must advance updated_at'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER trg_gda_data_product_update
BEFORE UPDATE ON gda_control.data_product
FOR EACH ROW EXECUTE FUNCTION gda_control.guard_data_product_update();

CREATE TRIGGER trg_gda_data_product_version_immutable
BEFORE UPDATE OR DELETE ON gda_control.data_product_version
FOR EACH ROW EXECUTE FUNCTION gda_control.reject_immutable_mutation();

CREATE TRIGGER trg_gda_data_product_event_immutable
BEFORE UPDATE OR DELETE ON gda_control.data_product_event
FOR EACH ROW EXECUTE FUNCTION gda_control.reject_immutable_mutation();

CREATE SCHEMA IF NOT EXISTS data_products;
GRANT USAGE, CREATE ON SCHEMA data_products TO agent_user;

ALTER TABLE gda_control.data_product ENABLE ROW LEVEL SECURITY;
ALTER TABLE gda_control.data_product FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON gda_control.data_product
    USING (tenant_id = gda_control.current_tenant())
    WITH CHECK (tenant_id = gda_control.current_tenant());

ALTER TABLE gda_control.data_product_version ENABLE ROW LEVEL SECURITY;
ALTER TABLE gda_control.data_product_version FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON gda_control.data_product_version
    USING (tenant_id = gda_control.current_tenant())
    WITH CHECK (tenant_id = gda_control.current_tenant());

ALTER TABLE gda_control.data_product_event ENABLE ROW LEVEL SECURITY;
ALTER TABLE gda_control.data_product_event FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON gda_control.data_product_event
    USING (tenant_id = gda_control.current_tenant())
    WITH CHECK (tenant_id = gda_control.current_tenant());

GRANT SELECT, INSERT, UPDATE ON gda_control.data_product TO gda_control_gateway;
GRANT SELECT, INSERT ON gda_control.data_product_version TO gda_control_gateway;
GRANT SELECT, INSERT ON gda_control.data_product_event TO gda_control_gateway;
