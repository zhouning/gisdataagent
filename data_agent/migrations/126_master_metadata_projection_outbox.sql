-- 126: Durable OpenMetadata projection delivery for active master versions.
--
-- The outbox is intentionally separate from metadata_change_outbox, whose
-- aggregate is constrained to LineageEvent. Master activation remains the
-- authority; this table only tracks eventually consistent provider delivery.

CREATE TABLE IF NOT EXISTS gda_control.master_metadata_projection_outbox (
    tenant_id TEXT NOT NULL,
    projection_change_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    entity_ref TEXT NOT NULL,
    activation_version INTEGER NOT NULL,
    resource_version_id UUID NOT NULL,
    entity_fingerprint CHAR(64) NOT NULL,
    destination_ref TEXT NOT NULL,
    payload_sha256 CHAR(64) NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    attempt_count INTEGER NOT NULL DEFAULT 0,
    max_attempts INTEGER NOT NULL DEFAULT 10,
    available_at TIMESTAMPTZ NOT NULL,
    claimed_by TEXT,
    claimed_until TIMESTAMPTZ,
    last_error TEXT,
    created_at TIMESTAMPTZ NOT NULL,
    completed_at TIMESTAMPTZ,
    CONSTRAINT uq_gda_master_metadata_projection_tenant_id
        UNIQUE (tenant_id, projection_change_id),
    CONSTRAINT uq_gda_master_metadata_projection_delivery UNIQUE (
        tenant_id, entity_ref, activation_version, destination_ref
    ),
    CONSTRAINT fk_gda_master_metadata_projection_source
        FOREIGN KEY (
            tenant_id, entity_ref, activation_version,
            resource_version_id, entity_fingerprint
        )
        REFERENCES gda_control.master_resource_projection(
            tenant_id, entity_ref, activation_version,
            resource_version_id, entity_fingerprint
        ),
    CONSTRAINT ck_gda_master_metadata_projection_destination
        CHECK (destination_ref = 'openmetadata:default'),
    CONSTRAINT ck_gda_master_metadata_projection_payload CHECK (
        payload_sha256 = entity_fingerprint
        AND payload_sha256 ~ '^[0-9a-f]{64}$'
    ),
    CONSTRAINT ck_gda_master_metadata_projection_status
        CHECK (status IN ('pending', 'in_flight', 'done', 'failed')),
    CONSTRAINT ck_gda_master_metadata_projection_attempt_count
        CHECK (attempt_count >= 0),
    CONSTRAINT ck_gda_master_metadata_projection_max_attempts
        CHECK (max_attempts BETWEEN 1 AND 100),
    CONSTRAINT ck_gda_master_metadata_projection_claim_pair CHECK (
        (claimed_by IS NULL) = (claimed_until IS NULL)
    ),
    CONSTRAINT ck_gda_master_metadata_projection_delivery_state CHECK (
        (status = 'pending' AND claimed_by IS NULL AND completed_at IS NULL)
        OR
        (status = 'in_flight' AND claimed_by IS NOT NULL AND completed_at IS NULL)
        OR
        (status IN ('done', 'failed')
            AND claimed_by IS NULL AND completed_at IS NOT NULL)
    )
);

CREATE INDEX IF NOT EXISTS idx_gda_master_metadata_projection_due
    ON gda_control.master_metadata_projection_outbox(
        tenant_id, available_at, created_at, projection_change_id
    )
    WHERE status IN ('pending', 'in_flight');

CREATE OR REPLACE FUNCTION gda_control.enqueue_master_metadata_projection()
RETURNS TRIGGER
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, gda_control
SET row_security = on
AS $$
BEGIN
    IF gda_control.current_tenant() IS NULL
       OR NEW.tenant_id IS DISTINCT FROM gda_control.current_tenant() THEN
        RAISE EXCEPTION 'master metadata projection tenant context is missing or mismatched'
            USING ERRCODE = '42501';
    END IF;
    INSERT INTO gda_control.master_metadata_projection_outbox (
        tenant_id, entity_ref, activation_version, resource_version_id,
        entity_fingerprint, destination_ref, payload_sha256,
        available_at, created_at
    ) VALUES (
        NEW.tenant_id, NEW.entity_ref, NEW.activation_version,
        NEW.resource_version_id, NEW.entity_fingerprint,
        'openmetadata:default', NEW.entity_fingerprint,
        NEW.projected_at, NEW.projected_at
    )
    ON CONFLICT (
        tenant_id, entity_ref, activation_version, destination_ref
    ) DO NOTHING;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_gda_master_metadata_projection_enqueue
    ON gda_control.master_resource_projection;
CREATE TRIGGER trg_gda_master_metadata_projection_enqueue
AFTER INSERT ON gda_control.master_resource_projection
FOR EACH ROW EXECUTE FUNCTION gda_control.enqueue_master_metadata_projection();

-- Existing repositories receive work only for projection rows that migration
-- 125 could prove. This does not reconstruct unprojected activation history.
INSERT INTO gda_control.master_metadata_projection_outbox (
    tenant_id, entity_ref, activation_version, resource_version_id,
    entity_fingerprint, destination_ref, payload_sha256,
    available_at, created_at
)
SELECT tenant_id, entity_ref, activation_version, resource_version_id,
       entity_fingerprint, 'openmetadata:default', entity_fingerprint,
       projected_at, projected_at
FROM gda_control.master_resource_projection
ON CONFLICT (
    tenant_id, entity_ref, activation_version, destination_ref
) DO NOTHING;

ALTER TABLE gda_control.master_metadata_projection_outbox
    ENABLE ROW LEVEL SECURITY;
ALTER TABLE gda_control.master_metadata_projection_outbox
    FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation
    ON gda_control.master_metadata_projection_outbox;
CREATE POLICY tenant_isolation
    ON gda_control.master_metadata_projection_outbox
    USING (tenant_id = gda_control.current_tenant())
    WITH CHECK (tenant_id = gda_control.current_tenant());

CREATE OR REPLACE FUNCTION gda_control.claim_master_metadata_projections(
    p_tenant_id TEXT,
    p_worker_id TEXT,
    p_limit INTEGER DEFAULT 10,
    p_lease_seconds INTEGER DEFAULT 60
)
RETURNS SETOF gda_control.master_metadata_projection_outbox
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

    UPDATE gda_control.master_metadata_projection_outbox
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
        SELECT change.projection_change_id
        FROM gda_control.master_metadata_projection_outbox AS change
        WHERE change.tenant_id = p_tenant_id
          AND change.attempt_count < change.max_attempts
          AND (
              (change.status = 'pending'
                  AND change.available_at <= clock_timestamp())
              OR
              (change.status = 'in_flight'
                  AND change.claimed_until <= clock_timestamp())
          )
        ORDER BY change.available_at, change.created_at,
                 change.projection_change_id
        LIMIT p_limit
        FOR UPDATE SKIP LOCKED
    )
    UPDATE gda_control.master_metadata_projection_outbox AS change
       SET status = 'in_flight',
           attempt_count = change.attempt_count + 1,
           claimed_by = p_worker_id,
           claimed_until = clock_timestamp()
               + make_interval(secs => p_lease_seconds),
           completed_at = NULL
      FROM candidates
     WHERE change.tenant_id = p_tenant_id
       AND change.projection_change_id = candidates.projection_change_id
    RETURNING change.*;
END;
$$;

CREATE OR REPLACE FUNCTION gda_control.complete_master_metadata_projection(
    p_tenant_id TEXT,
    p_projection_change_id UUID,
    p_worker_id TEXT
)
RETURNS SETOF gda_control.master_metadata_projection_outbox
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
    UPDATE gda_control.master_metadata_projection_outbox AS change
       SET status = 'done',
           claimed_by = NULL,
           claimed_until = NULL,
           last_error = NULL,
           completed_at = clock_timestamp()
     WHERE change.tenant_id = p_tenant_id
       AND change.projection_change_id = p_projection_change_id
       AND change.status = 'in_flight'
       AND change.claimed_by = p_worker_id
       AND change.claimed_until > clock_timestamp()
    RETURNING change.*;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'master metadata projection claim is missing, expired, or owned by another worker'
            USING ERRCODE = '40001';
    END IF;
END;
$$;

CREATE OR REPLACE FUNCTION gda_control.fail_master_metadata_projection(
    p_tenant_id TEXT,
    p_projection_change_id UUID,
    p_worker_id TEXT,
    p_error TEXT,
    p_retry_delay_seconds INTEGER DEFAULT 30
)
RETURNS SETOF gda_control.master_metadata_projection_outbox
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
    UPDATE gda_control.master_metadata_projection_outbox AS change
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
       AND change.projection_change_id = p_projection_change_id
       AND change.status = 'in_flight'
       AND change.claimed_by = p_worker_id
       AND change.claimed_until > clock_timestamp()
    RETURNING change.*;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'master metadata projection claim is missing, expired, or owned by another worker'
            USING ERRCODE = '40001';
    END IF;
END;
$$;

REVOKE ALL ON TABLE gda_control.master_metadata_projection_outbox
    FROM PUBLIC, gda_control_gateway;
GRANT SELECT ON TABLE gda_control.master_metadata_projection_outbox
    TO gda_control_gateway;

REVOKE ALL ON FUNCTION gda_control.enqueue_master_metadata_projection()
    FROM PUBLIC;
REVOKE ALL ON FUNCTION gda_control.claim_master_metadata_projections(
    TEXT, TEXT, INTEGER, INTEGER
) FROM PUBLIC;
REVOKE ALL ON FUNCTION gda_control.complete_master_metadata_projection(
    TEXT, UUID, TEXT
) FROM PUBLIC;
REVOKE ALL ON FUNCTION gda_control.fail_master_metadata_projection(
    TEXT, UUID, TEXT, TEXT, INTEGER
) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION gda_control.claim_master_metadata_projections(
    TEXT, TEXT, INTEGER, INTEGER
) TO gda_control_gateway;
GRANT EXECUTE ON FUNCTION gda_control.complete_master_metadata_projection(
    TEXT, UUID, TEXT
) TO gda_control_gateway;
GRANT EXECUTE ON FUNCTION gda_control.fail_master_metadata_projection(
    TEXT, UUID, TEXT, TEXT, INTEGER
) TO gda_control_gateway;
