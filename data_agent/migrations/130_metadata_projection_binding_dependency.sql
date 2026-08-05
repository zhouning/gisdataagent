-- Keep OpenMetadata lineage changes pending until both endpoint Resources have
-- governance bindings. Missing crosswalks are an unmet dependency, not a
-- provider delivery failure, and must not consume the retry/dead-letter budget.

CREATE OR REPLACE FUNCTION gda_control.metadata_lineage_bindings_ready(
    p_tenant_id TEXT,
    p_lineage_event_id UUID
)
RETURNS BOOLEAN
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog, gda_control
SET row_security = on
AS $$
    SELECT EXISTS (
        SELECT 1
        FROM gda_control.lineage_event AS event
        JOIN gda_control.resource_version AS source_version
          ON source_version.tenant_id = event.tenant_id
         AND source_version.resource_version_id = event.source_resource_version_id
        JOIN gda_control.resource_version AS target_version
          ON target_version.tenant_id = event.tenant_id
         AND target_version.resource_version_id = event.target_resource_version_id
        JOIN gda_control.metadata_fabric_binding AS source_binding
          ON source_binding.tenant_id = source_version.tenant_id
         AND source_binding.resource_urn = source_version.resource_urn
         AND source_binding.system = 'openmetadata'
        JOIN gda_control.metadata_fabric_binding AS target_binding
          ON target_binding.tenant_id = target_version.tenant_id
         AND target_binding.resource_urn = target_version.resource_urn
         AND target_binding.system = 'openmetadata'
        WHERE event.tenant_id = p_tenant_id
          AND event.lineage_event_id = p_lineage_event_id
          AND gda_control.current_tenant() = p_tenant_id
    );
$$;

REVOKE ALL ON FUNCTION gda_control.metadata_lineage_bindings_ready(TEXT, UUID)
    FROM PUBLIC;

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

    -- An older worker may have claimed an event before its bindings existed.
    -- Release that claim and refund the attempt so dependency wait cannot turn
    -- into a dead letter while an operator provisions the external entities.
    UPDATE gda_control.metadata_change_outbox AS change
       SET status = 'pending',
           attempt_count = greatest(change.attempt_count - 1, 0),
           claimed_by = NULL,
           claimed_until = NULL,
           available_at = clock_timestamp(),
           last_error = 'waiting for OpenMetadata source and target bindings'
     WHERE change.tenant_id = p_tenant_id
       AND change.status = 'in_flight'
       AND change.claimed_until <= clock_timestamp()
       AND change.attempt_count < change.max_attempts
       AND NOT gda_control.metadata_lineage_bindings_ready(
           change.tenant_id, change.aggregate_id
       );

    RETURN QUERY
    WITH candidates AS (
        SELECT change.change_id
        FROM gda_control.metadata_change_outbox AS change
        WHERE change.tenant_id = p_tenant_id
          AND change.attempt_count < change.max_attempts
          AND gda_control.metadata_lineage_bindings_ready(
              change.tenant_id, change.aggregate_id
          )
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
