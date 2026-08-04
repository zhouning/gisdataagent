-- 112: Authority-safe Metadata Fabric crosswalk and durable lineage projection.

CREATE TABLE IF NOT EXISTS gda_control.metadata_fabric_binding (
    tenant_id TEXT NOT NULL,
    binding_id UUID PRIMARY KEY,
    resource_urn TEXT NOT NULL,
    system TEXT NOT NULL,
    binding_kind TEXT NOT NULL,
    external_namespace TEXT NOT NULL,
    external_object_id TEXT NOT NULL,
    external_object_type TEXT NOT NULL,
    external_version_ref TEXT,
    binding_sha256 CHAR(64) NOT NULL,
    created_by TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    CONSTRAINT uq_gda_metadata_binding_tenant_id
        UNIQUE (tenant_id, binding_id),
    CONSTRAINT uq_gda_metadata_binding_external_object UNIQUE (
        tenant_id, system, external_namespace,
        external_object_type, external_object_id
    ),
    CONSTRAINT uq_gda_metadata_binding_fingerprint
        UNIQUE (tenant_id, binding_sha256),
    CONSTRAINT fk_gda_metadata_binding_resource
        FOREIGN KEY (tenant_id, resource_urn)
        REFERENCES gda_control.resource(tenant_id, resource_urn),
    CONSTRAINT ck_gda_metadata_binding_system
        CHECK (system IN ('openmetadata', 'gravitino')),
    CONSTRAINT ck_gda_metadata_binding_kind CHECK (
        (system = 'openmetadata' AND binding_kind = 'governance_entity')
        OR
        (system = 'gravitino' AND binding_kind = 'technical_object')
    ),
    CONSTRAINT ck_gda_metadata_binding_external_refs CHECK (
        length(btrim(external_namespace)) BETWEEN 1 AND 512
        AND length(btrim(external_object_id)) BETWEEN 1 AND 512
        AND length(btrim(external_object_type)) BETWEEN 1 AND 512
        AND (
            external_version_ref IS NULL
            OR length(btrim(external_version_ref)) BETWEEN 1 AND 512
        )
    ),
    CONSTRAINT ck_gda_metadata_binding_sha256
        CHECK (binding_sha256 ~ '^[0-9a-f]{64}$'),
    CONSTRAINT ck_gda_metadata_binding_actor
        CHECK (length(btrim(created_by)) BETWEEN 1 AND 512)
);

-- A ResourceURN has one governance identity. Gravitino may legitimately expose
-- the same resource through multiple technical catalogs or regions.
CREATE UNIQUE INDEX IF NOT EXISTS uq_gda_openmetadata_resource_binding
    ON gda_control.metadata_fabric_binding(tenant_id, resource_urn)
    WHERE system = 'openmetadata';
CREATE INDEX IF NOT EXISTS idx_gda_metadata_binding_resource
    ON gda_control.metadata_fabric_binding(tenant_id, resource_urn, system);

ALTER TABLE gda_control.metadata_fabric_binding ENABLE ROW LEVEL SECURITY;
ALTER TABLE gda_control.metadata_fabric_binding FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation
    ON gda_control.metadata_fabric_binding;
CREATE POLICY tenant_isolation
    ON gda_control.metadata_fabric_binding
    USING (tenant_id = gda_control.current_tenant())
    WITH CHECK (tenant_id = gda_control.current_tenant());

DROP TRIGGER IF EXISTS trg_gda_metadata_binding_immutable
    ON gda_control.metadata_fabric_binding;
CREATE TRIGGER trg_gda_metadata_binding_immutable
BEFORE UPDATE OR DELETE ON gda_control.metadata_fabric_binding
FOR EACH ROW EXECUTE FUNCTION gda_control.reject_immutable_mutation();

CREATE TABLE IF NOT EXISTS gda_control.metadata_change_outbox (
    tenant_id TEXT NOT NULL,
    change_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    change_type TEXT NOT NULL,
    aggregate_id UUID NOT NULL,
    destination_ref TEXT NOT NULL,
    payload_sha256 CHAR(64) NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    attempt_count INTEGER NOT NULL DEFAULT 0,
    max_attempts INTEGER NOT NULL DEFAULT 10,
    available_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    claimed_by TEXT,
    claimed_until TIMESTAMPTZ,
    last_error TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_at TIMESTAMPTZ,
    CONSTRAINT uq_gda_metadata_change_tenant_id
        UNIQUE (tenant_id, change_id),
    CONSTRAINT uq_gda_metadata_change_delivery
        UNIQUE (tenant_id, change_type, aggregate_id, destination_ref),
    CONSTRAINT fk_gda_metadata_change_lineage
        FOREIGN KEY (tenant_id, aggregate_id)
        REFERENCES gda_control.lineage_event(tenant_id, lineage_event_id),
    CONSTRAINT ck_gda_metadata_change_type
        CHECK (change_type = 'lineage_upsert'),
    CONSTRAINT ck_gda_metadata_change_destination
        CHECK (destination_ref = 'openmetadata:default'),
    CONSTRAINT ck_gda_metadata_change_payload_sha256
        CHECK (payload_sha256 ~ '^[0-9a-f]{64}$'),
    CONSTRAINT ck_gda_metadata_change_status
        CHECK (status IN ('pending', 'in_flight', 'done', 'failed')),
    CONSTRAINT ck_gda_metadata_change_attempt_count
        CHECK (attempt_count >= 0),
    CONSTRAINT ck_gda_metadata_change_max_attempts
        CHECK (max_attempts BETWEEN 1 AND 100),
    CONSTRAINT ck_gda_metadata_change_claim_pair CHECK (
        (claimed_by IS NULL) = (claimed_until IS NULL)
    ),
    CONSTRAINT ck_gda_metadata_change_delivery_state CHECK (
        (status = 'pending' AND claimed_by IS NULL AND completed_at IS NULL)
        OR
        (status = 'in_flight' AND claimed_by IS NOT NULL AND completed_at IS NULL)
        OR
        (status IN ('done', 'failed')
            AND claimed_by IS NULL AND completed_at IS NOT NULL)
    )
);

CREATE INDEX IF NOT EXISTS idx_gda_metadata_change_due
    ON gda_control.metadata_change_outbox(
        tenant_id, available_at, created_at, change_id
    )
    WHERE status IN ('pending', 'in_flight');

CREATE OR REPLACE FUNCTION gda_control.enqueue_lineage_metadata_change()
RETURNS TRIGGER
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, gda_control
SET row_security = on
AS $$
BEGIN
    IF gda_control.current_tenant() IS NULL
       OR NEW.tenant_id IS DISTINCT FROM gda_control.current_tenant() THEN
        RAISE EXCEPTION 'metadata change tenant context is missing or mismatched'
            USING ERRCODE = '42501';
    END IF;
    INSERT INTO gda_control.metadata_change_outbox (
        tenant_id, change_type, aggregate_id, destination_ref,
        payload_sha256, available_at, created_at
    ) VALUES (
        NEW.tenant_id, 'lineage_upsert', NEW.lineage_event_id,
        'openmetadata:default', NEW.event_sha256, NEW.occurred_at, NEW.occurred_at
    )
    ON CONFLICT (tenant_id, change_type, aggregate_id, destination_ref)
    DO NOTHING;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_gda_lineage_metadata_change
    ON gda_control.lineage_event;
CREATE TRIGGER trg_gda_lineage_metadata_change
AFTER INSERT ON gda_control.lineage_event
FOR EACH ROW EXECUTE FUNCTION gda_control.enqueue_lineage_metadata_change();

-- Existing lineage is projection input too. Backfill is idempotent and does
-- not claim that OpenMetadata has already accepted any edge.
INSERT INTO gda_control.metadata_change_outbox (
    tenant_id, change_type, aggregate_id, destination_ref,
    payload_sha256, available_at, created_at
)
SELECT tenant_id, 'lineage_upsert', lineage_event_id,
       'openmetadata:default', event_sha256, occurred_at, occurred_at
FROM gda_control.lineage_event
ON CONFLICT (tenant_id, change_type, aggregate_id, destination_ref)
DO NOTHING;

ALTER TABLE gda_control.metadata_change_outbox ENABLE ROW LEVEL SECURITY;
ALTER TABLE gda_control.metadata_change_outbox FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation
    ON gda_control.metadata_change_outbox;
CREATE POLICY tenant_isolation
    ON gda_control.metadata_change_outbox
    USING (tenant_id = gda_control.current_tenant())
    WITH CHECK (tenant_id = gda_control.current_tenant());

CREATE OR REPLACE FUNCTION gda_control.claim_metadata_changes(
    p_tenant_id TEXT,
    p_worker_id TEXT,
    p_limit INTEGER DEFAULT 10,
    p_lease_seconds INTEGER DEFAULT 60
)
RETURNS SETOF gda_control.metadata_change_outbox
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, gda_control
SET row_security = on
AS $$
BEGIN
    IF gda_control.current_tenant() IS DISTINCT FROM p_tenant_id THEN
        RAISE EXCEPTION 'tenant context mismatch' USING ERRCODE = '42501';
    END IF;
    IF COALESCE(btrim(p_worker_id), '') = '' THEN
        RAISE EXCEPTION 'worker identity is required' USING ERRCODE = '22023';
    END IF;
    IF p_limit IS NULL OR p_limit < 1 OR p_limit > 100 THEN
        RAISE EXCEPTION 'claim limit must be between 1 and 100'
            USING ERRCODE = '22023';
    END IF;
    IF p_lease_seconds IS NULL
       OR p_lease_seconds < 5 OR p_lease_seconds > 3600 THEN
        RAISE EXCEPTION 'lease must be between 5 and 3600 seconds'
            USING ERRCODE = '22023';
    END IF;

    UPDATE gda_control.metadata_change_outbox
       SET status = 'failed',
           claimed_by = NULL,
           claimed_until = NULL,
           last_error = COALESCE(last_error, 'worker lease expired'),
           completed_at = clock_timestamp()
     WHERE tenant_id = p_tenant_id
       AND status = 'in_flight'
       AND claimed_until <= clock_timestamp()
       AND attempt_count >= max_attempts;

    RETURN QUERY
    WITH candidates AS (
        SELECT change.change_id
        FROM gda_control.metadata_change_outbox AS change
        WHERE change.tenant_id = p_tenant_id
          AND change.attempt_count < change.max_attempts
          AND (
              (change.status = 'pending'
                  AND change.available_at <= clock_timestamp())
              OR
              (change.status = 'in_flight'
                  AND change.claimed_until <= clock_timestamp())
          )
        ORDER BY change.available_at, change.created_at, change.change_id
        LIMIT p_limit
        FOR UPDATE SKIP LOCKED
    )
    UPDATE gda_control.metadata_change_outbox AS change
       SET status = 'in_flight',
           attempt_count = change.attempt_count + 1,
           claimed_by = p_worker_id,
           claimed_until = clock_timestamp()
               + make_interval(secs => p_lease_seconds),
           completed_at = NULL
      FROM candidates
     WHERE change.tenant_id = p_tenant_id
       AND change.change_id = candidates.change_id
    RETURNING change.*;
END;
$$;

CREATE OR REPLACE FUNCTION gda_control.complete_metadata_change(
    p_tenant_id TEXT,
    p_change_id UUID,
    p_worker_id TEXT
)
RETURNS SETOF gda_control.metadata_change_outbox
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, gda_control
SET row_security = on
AS $$
BEGIN
    IF gda_control.current_tenant() IS DISTINCT FROM p_tenant_id THEN
        RAISE EXCEPTION 'tenant context mismatch' USING ERRCODE = '42501';
    END IF;
    RETURN QUERY
    UPDATE gda_control.metadata_change_outbox AS change
       SET status = 'done',
           claimed_by = NULL,
           claimed_until = NULL,
           last_error = NULL,
           completed_at = clock_timestamp()
     WHERE change.tenant_id = p_tenant_id
       AND change.change_id = p_change_id
       AND change.status = 'in_flight'
       AND change.claimed_by = p_worker_id
       AND change.claimed_until > clock_timestamp()
    RETURNING change.*;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'metadata change claim is missing, expired, or owned by another worker'
            USING ERRCODE = '40001';
    END IF;
END;
$$;

CREATE OR REPLACE FUNCTION gda_control.fail_metadata_change(
    p_tenant_id TEXT,
    p_change_id UUID,
    p_worker_id TEXT,
    p_error TEXT,
    p_retry_delay_seconds INTEGER DEFAULT 30
)
RETURNS SETOF gda_control.metadata_change_outbox
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, gda_control
SET row_security = on
AS $$
BEGIN
    IF gda_control.current_tenant() IS DISTINCT FROM p_tenant_id THEN
        RAISE EXCEPTION 'tenant context mismatch' USING ERRCODE = '42501';
    END IF;
    IF COALESCE(btrim(p_error), '') = '' THEN
        RAISE EXCEPTION 'failure reason is required' USING ERRCODE = '22023';
    END IF;
    IF p_retry_delay_seconds IS NULL
       OR p_retry_delay_seconds < 0 OR p_retry_delay_seconds > 86400 THEN
        RAISE EXCEPTION 'retry delay must be between 0 and 86400 seconds'
            USING ERRCODE = '22023';
    END IF;
    RETURN QUERY
    UPDATE gda_control.metadata_change_outbox AS change
       SET status = CASE
               WHEN change.attempt_count >= change.max_attempts
               THEN 'failed' ELSE 'pending' END,
           claimed_by = NULL,
           claimed_until = NULL,
           last_error = left(p_error, 512),
           available_at = CASE
               WHEN change.attempt_count >= change.max_attempts
               THEN change.available_at
               ELSE clock_timestamp()
                   + make_interval(secs => p_retry_delay_seconds)
               END,
           completed_at = CASE
               WHEN change.attempt_count >= change.max_attempts
               THEN clock_timestamp() ELSE NULL END
     WHERE change.tenant_id = p_tenant_id
       AND change.change_id = p_change_id
       AND change.status = 'in_flight'
       AND change.claimed_by = p_worker_id
       AND change.claimed_until > clock_timestamp()
    RETURNING change.*;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'metadata change claim is missing, expired, or owned by another worker'
            USING ERRCODE = '40001';
    END IF;
END;
$$;

REVOKE ALL ON TABLE gda_control.metadata_fabric_binding
    FROM PUBLIC, gda_control_gateway;
GRANT SELECT, INSERT ON TABLE gda_control.metadata_fabric_binding
    TO gda_control_gateway;

REVOKE ALL ON TABLE gda_control.metadata_change_outbox
    FROM PUBLIC, gda_control_gateway;
GRANT SELECT ON TABLE gda_control.metadata_change_outbox
    TO gda_control_gateway;

REVOKE ALL ON FUNCTION gda_control.enqueue_lineage_metadata_change()
    FROM PUBLIC;
REVOKE ALL ON FUNCTION gda_control.claim_metadata_changes(
    TEXT, TEXT, INTEGER, INTEGER
) FROM PUBLIC;
REVOKE ALL ON FUNCTION gda_control.complete_metadata_change(
    TEXT, UUID, TEXT
) FROM PUBLIC;
REVOKE ALL ON FUNCTION gda_control.fail_metadata_change(
    TEXT, UUID, TEXT, TEXT, INTEGER
) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION gda_control.claim_metadata_changes(
    TEXT, TEXT, INTEGER, INTEGER
) TO gda_control_gateway;
GRANT EXECUTE ON FUNCTION gda_control.complete_metadata_change(
    TEXT, UUID, TEXT
) TO gda_control_gateway;
GRANT EXECUTE ON FUNCTION gda_control.fail_metadata_change(
    TEXT, UUID, TEXT, TEXT, INTEGER
) TO gda_control_gateway;
