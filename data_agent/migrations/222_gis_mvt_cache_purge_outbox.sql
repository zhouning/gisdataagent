-- 222: Durable cleanup of retired GIS MVT cache generations.
--
-- Cutover and rollback remain PostgreSQL transactions and never wait for
-- Redis.  Their immutable receipts enqueue one tenant-scoped cleanup task;
-- a dedicated worker later purges the exact retired generation.

CREATE TABLE gda_control.gis_mvt_cache_purge_outbox (
    tenant_id TEXT NOT NULL,
    purge_task_id UUID NOT NULL,
    source_kind TEXT NOT NULL,
    source_receipt_id UUID NOT NULL,
    source_receipt_sha256 CHAR(64) NOT NULL,
    service_urn TEXT NOT NULL,
    endpoint_revision_id UUID NOT NULL,
    service_definition_version_id UUID NOT NULL,
    service_release_binding_id UUID NOT NULL,
    endpoint_state_version INTEGER NOT NULL,
    cache_namespace TEXT,
    cache_context JSONB,
    generation_token CHAR(64),
    status TEXT NOT NULL,
    bypass_reason TEXT,
    attempt_count INTEGER NOT NULL DEFAULT 0,
    max_attempts INTEGER NOT NULL DEFAULT 5,
    available_at TIMESTAMPTZ NOT NULL,
    claimed_by TEXT,
    claimed_until TIMESTAMPTZ,
    last_error TEXT,
    matched_keys INTEGER,
    deleted_keys INTEGER,
    remaining_keys INTEGER,
    created_at TIMESTAMPTZ NOT NULL,
    completed_at TIMESTAMPTZ,
    CONSTRAINT pk_gda_gis_mvt_cache_purge
        PRIMARY KEY (tenant_id, purge_task_id),
    CONSTRAINT uq_gda_gis_mvt_cache_purge_id UNIQUE (purge_task_id),
    CONSTRAINT uq_gda_gis_mvt_cache_purge_receipt
        UNIQUE (tenant_id, source_kind, source_receipt_id),
    CONSTRAINT fk_gda_gis_mvt_cache_purge_service
        FOREIGN KEY (tenant_id, service_urn)
        REFERENCES gda_control.gis_service(tenant_id, service_urn),
    CONSTRAINT fk_gda_gis_mvt_cache_purge_endpoint
        FOREIGN KEY (tenant_id, service_urn, endpoint_revision_id)
        REFERENCES gda_control.endpoint_revision(
            tenant_id, service_urn, endpoint_revision_id
        ),
    CONSTRAINT fk_gda_gis_mvt_cache_purge_release
        FOREIGN KEY (
            tenant_id, service_definition_version_id,
            service_release_binding_id
        ) REFERENCES gda_control.service_release_binding(
            tenant_id, service_definition_version_id,
            service_release_binding_id
        ),
    CONSTRAINT ck_gda_gis_mvt_cache_purge_source CHECK (
        source_kind IN ('cutover', 'rollback')
        AND source_receipt_sha256 ~ '^[0-9a-f]{64}$'
    ),
    CONSTRAINT ck_gda_gis_mvt_cache_purge_service CHECK (
        service_urn ~ '^gda://[a-z0-9][a-z0-9._-]{0,63}/gis_service/[a-z0-9][a-z0-9._-]{0,127}$'
        AND split_part(service_urn, '/', 3) = tenant_id
        AND endpoint_state_version >= 0
    ),
    CONSTRAINT ck_gda_gis_mvt_cache_purge_status CHECK (
        status IN ('pending', 'in_flight', 'done', 'failed', 'bypassed')
    ),
    CONSTRAINT ck_gda_gis_mvt_cache_purge_attempts CHECK (
        attempt_count >= 0 AND max_attempts BETWEEN 1 AND 100
    ),
    CONSTRAINT ck_gda_gis_mvt_cache_purge_claim CHECK (
        (claimed_by IS NULL) = (claimed_until IS NULL)
    ),
    CONSTRAINT ck_gda_gis_mvt_cache_purge_context CHECK (
        (
            status <> 'bypassed'
            AND cache_namespace ~ '^[a-z0-9][a-z0-9._-]{0,127}$'
            AND jsonb_typeof(cache_context) = 'object'
            AND cache_context->>'schema' = 'gda.gis_mvt_cache_namespace.v1'
            AND generation_token ~ '^[0-9a-f]{64}$'
            AND bypass_reason IS NULL
        ) OR (
            status = 'bypassed'
            AND cache_namespace IS NULL
            AND cache_context IS NULL
            AND generation_token IS NULL
            AND NULLIF(btrim(bypass_reason), '') IS NOT NULL
        )
    ),
    CONSTRAINT ck_gda_gis_mvt_cache_purge_delivery CHECK (
        (
            status = 'pending' AND claimed_by IS NULL
            AND completed_at IS NULL
            AND matched_keys IS NULL AND deleted_keys IS NULL
            AND remaining_keys IS NULL
        ) OR (
            status = 'in_flight' AND claimed_by IS NOT NULL
            AND completed_at IS NULL
            AND matched_keys IS NULL AND deleted_keys IS NULL
            AND remaining_keys IS NULL
        ) OR (
            status = 'done' AND claimed_by IS NULL
            AND completed_at IS NOT NULL
            AND matched_keys >= 0 AND deleted_keys >= 0
            AND deleted_keys <= matched_keys AND remaining_keys = 0
        ) OR (
            status = 'failed' AND claimed_by IS NULL
            AND completed_at IS NOT NULL
            AND NULLIF(btrim(last_error), '') IS NOT NULL
            AND matched_keys IS NULL AND deleted_keys IS NULL
            AND remaining_keys IS NULL
        ) OR (
            status = 'bypassed' AND claimed_by IS NULL
            AND completed_at IS NOT NULL
            AND matched_keys IS NULL AND deleted_keys IS NULL
            AND remaining_keys IS NULL
        )
    )
);

CREATE INDEX idx_gda_gis_mvt_cache_purge_due
    ON gda_control.gis_mvt_cache_purge_outbox(
        tenant_id, available_at, created_at, purge_task_id
    ) WHERE status = 'pending';
CREATE INDEX idx_gda_gis_mvt_cache_purge_lease
    ON gda_control.gis_mvt_cache_purge_outbox(tenant_id, claimed_until)
    WHERE status = 'in_flight';
CREATE UNIQUE INDEX uq_gda_gis_mvt_cache_purge_generation
    ON gda_control.gis_mvt_cache_purge_outbox(tenant_id, generation_token)
    WHERE generation_token IS NOT NULL;

CREATE OR REPLACE FUNCTION gda_control.gis_mvt_cache_generation(
    p_cache_namespace TEXT,
    p_tenant_id TEXT,
    p_service_urn TEXT,
    p_service_release_binding_id UUID,
    p_service_release_sha256 TEXT,
    p_cache_policy_version_id UUID,
    p_cache_policy_sha256 TEXT,
    p_service_policy_binding_id UUID,
    p_service_policy_sha256 TEXT,
    p_mvt_serving_projection_version_id UUID,
    p_mvt_serving_projection_sha256 TEXT,
    p_endpoint_state_version INTEGER,
    p_endpoint_revision_id UUID,
    p_endpoint_sha256 TEXT
)
RETURNS TEXT
LANGUAGE sql
IMMUTABLE
SET search_path = pg_catalog, public
AS $$
    WITH payload AS (
        SELECT jsonb_build_object(
            'cache_policy_sha256', p_cache_policy_sha256,
            'cache_policy_version_id', p_cache_policy_version_id::text,
            'endpoint_revision_id', p_endpoint_revision_id::text,
            'endpoint_sha256', p_endpoint_sha256,
            'endpoint_state_version', p_endpoint_state_version,
            'mvt_serving_projection_sha256',
                p_mvt_serving_projection_sha256,
            'mvt_serving_projection_version_id',
                p_mvt_serving_projection_version_id::text,
            'namespace', p_cache_namespace,
            'schema', 'gda.gis_mvt_cache_namespace.v1',
            'service_policy_binding_id', p_service_policy_binding_id::text,
            'service_policy_sha256', p_service_policy_sha256,
            'service_release_binding_id',
                p_service_release_binding_id::text,
            'service_release_sha256', p_service_release_sha256,
            'service_urn', p_service_urn,
            'tenant_id', p_tenant_id
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

CREATE OR REPLACE FUNCTION gda_control.guard_gis_mvt_cache_purge_insert()
RETURNS TRIGGER
LANGUAGE plpgsql
SET search_path = pg_catalog, gda_control
AS $$
BEGIN
    IF COALESCE(
        current_setting('gda.gis_mvt_cache_purge_insert_allowed', true), ''
    ) <> NEW.source_kind || ':' || NEW.source_receipt_id::text THEN
        RAISE EXCEPTION 'cache purge tasks are created from transition receipts'
            USING ERRCODE = '55000';
    END IF;
    IF gda_control.current_tenant() IS NULL
       OR NEW.tenant_id IS DISTINCT FROM gda_control.current_tenant() THEN
        RAISE EXCEPTION 'cache purge tenant context is missing or mismatched'
            USING ERRCODE = '42501';
    END IF;
    IF NEW.generation_token IS NOT NULL
       AND NEW.generation_token IS DISTINCT FROM
           gda_control.gis_mvt_cache_generation(
               NEW.cache_context->>'namespace',
               NEW.cache_context->>'tenant_id',
               NEW.cache_context->>'service_urn',
               (NEW.cache_context->>'service_release_binding_id')::UUID,
               NEW.cache_context->>'service_release_sha256',
               (NEW.cache_context->>'cache_policy_version_id')::UUID,
               NEW.cache_context->>'cache_policy_sha256',
               (NEW.cache_context->>'service_policy_binding_id')::UUID,
               NEW.cache_context->>'service_policy_sha256',
               (NEW.cache_context->>'mvt_serving_projection_version_id')::UUID,
               NEW.cache_context->>'mvt_serving_projection_sha256',
               (NEW.cache_context->>'endpoint_state_version')::INTEGER,
               (NEW.cache_context->>'endpoint_revision_id')::UUID,
               NEW.cache_context->>'endpoint_sha256'
           ) THEN
        RAISE EXCEPTION 'cache purge generation does not match its context'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER trg_gda_gis_mvt_cache_purge_insert
BEFORE INSERT ON gda_control.gis_mvt_cache_purge_outbox
FOR EACH ROW EXECUTE FUNCTION gda_control.guard_gis_mvt_cache_purge_insert();

CREATE FUNCTION gda_control.enqueue_gis_mvt_cache_purge(
    p_tenant_id TEXT,
    p_source_kind TEXT,
    p_source_receipt_id UUID,
    p_source_receipt_sha256 TEXT,
    p_service_urn TEXT,
    p_endpoint_revision_id UUID,
    p_service_definition_version_id UUID,
    p_service_release_binding_id UUID,
    p_endpoint_state_version INTEGER,
    p_created_at TIMESTAMPTZ
)
RETURNS UUID
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, gda_control
SET row_security = on
AS $$
DECLARE
    v_existing gda_control.gis_mvt_cache_purge_outbox%ROWTYPE;
    v_service_type TEXT;
    v_release_sha256 TEXT;
    v_cache_policy_id UUID;
    v_cache_namespace TEXT;
    v_cache_policy_sha256 TEXT;
    v_service_policy_id UUID;
    v_service_policy_sha256 TEXT;
    v_projection_id UUID;
    v_projection_sha256 TEXT;
    v_endpoint_sha256 TEXT;
    v_context JSONB;
    v_generation TEXT;
    v_task_id UUID;
    v_status TEXT;
    v_bypass_reason TEXT;
BEGIN
    IF gda_control.current_tenant() IS DISTINCT FROM p_tenant_id THEN
        RAISE EXCEPTION 'cache purge tenant context is missing or mismatched'
            USING ERRCODE = '42501';
    END IF;
    IF p_source_kind NOT IN ('cutover', 'rollback') THEN
        RAISE EXCEPTION 'cache purge source kind is invalid'
            USING ERRCODE = '22023';
    END IF;

    SELECT * INTO v_existing
      FROM gda_control.gis_mvt_cache_purge_outbox
     WHERE tenant_id = p_tenant_id
       AND source_kind = p_source_kind
       AND source_receipt_id = p_source_receipt_id;
    IF FOUND THEN
        IF v_existing.source_receipt_sha256 IS DISTINCT FROM
               p_source_receipt_sha256
           OR v_existing.service_urn IS DISTINCT FROM p_service_urn
           OR v_existing.endpoint_revision_id IS DISTINCT FROM
               p_endpoint_revision_id
           OR v_existing.service_definition_version_id IS DISTINCT FROM
               p_service_definition_version_id
           OR v_existing.service_release_binding_id IS DISTINCT FROM
               p_service_release_binding_id
           OR v_existing.endpoint_state_version IS DISTINCT FROM
               p_endpoint_state_version THEN
            RAISE EXCEPTION 'cache purge receipt identity has different content'
                USING ERRCODE = '23505';
        END IF;
        RETURN v_existing.purge_task_id;
    END IF;

    SELECT definition.service_type, release.binding_sha256,
           release.cache_policy_version_id, cache.cache_namespace,
           cache.policy_sha256, policy.service_policy_binding_id,
           policy.policy_sha256, release.mvt_serving_projection_version_id,
           projection.projection_sha256, endpoint.endpoint_sha256
      INTO v_service_type, v_release_sha256, v_cache_policy_id,
           v_cache_namespace, v_cache_policy_sha256, v_service_policy_id,
           v_service_policy_sha256, v_projection_id, v_projection_sha256,
           v_endpoint_sha256
      FROM gda_control.gis_service_definition_version AS definition
      JOIN gda_control.service_release_binding AS release
        ON release.tenant_id = definition.tenant_id
       AND release.service_definition_version_id =
           definition.service_definition_version_id
       AND release.service_release_binding_id =
           p_service_release_binding_id
      JOIN gda_control.endpoint_revision AS endpoint
        ON endpoint.tenant_id = definition.tenant_id
       AND endpoint.service_urn = p_service_urn
       AND endpoint.endpoint_revision_id = p_endpoint_revision_id
      LEFT JOIN gda_control.cache_policy_version AS cache
        ON cache.tenant_id = release.tenant_id
       AND cache.service_definition_version_id =
           release.service_definition_version_id
       AND cache.cache_policy_version_id = release.cache_policy_version_id
      LEFT JOIN gda_control.service_policy_binding AS policy
        ON policy.tenant_id = release.tenant_id
       AND policy.service_definition_version_id =
           release.service_definition_version_id
       AND policy.service_release_binding_id =
           release.service_release_binding_id
      LEFT JOIN gda_control.mvt_serving_projection_version AS projection
        ON projection.tenant_id = release.tenant_id
       AND projection.service_definition_version_id =
           release.service_definition_version_id
       AND projection.mvt_serving_projection_version_id =
           release.mvt_serving_projection_version_id
     WHERE definition.tenant_id = p_tenant_id
       AND definition.service_definition_version_id =
           p_service_definition_version_id
       AND definition.service_urn = p_service_urn;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'retired GIS endpoint release context was not found'
            USING ERRCODE = 'P0002';
    END IF;

    IF v_service_type <> 'vector_tile' THEN
        v_status := 'bypassed';
        v_bypass_reason := 'service_type_not_vector_tile';
    ELSIF v_cache_policy_id IS NULL OR v_cache_namespace IS NULL
       OR v_cache_policy_sha256 IS NULL OR v_service_policy_id IS NULL
       OR v_service_policy_sha256 IS NULL OR v_projection_id IS NULL
       OR v_projection_sha256 IS NULL THEN
        v_status := 'bypassed';
        v_bypass_reason := 'legacy_cache_context_incomplete';
    ELSE
        v_status := 'pending';
        v_context := jsonb_build_object(
            'cache_policy_sha256', v_cache_policy_sha256,
            'cache_policy_version_id', v_cache_policy_id::text,
            'endpoint_revision_id', p_endpoint_revision_id::text,
            'endpoint_sha256', v_endpoint_sha256,
            'endpoint_state_version', p_endpoint_state_version,
            'mvt_serving_projection_sha256', v_projection_sha256,
            'mvt_serving_projection_version_id', v_projection_id::text,
            'namespace', v_cache_namespace,
            'schema', 'gda.gis_mvt_cache_namespace.v1',
            'service_policy_binding_id', v_service_policy_id::text,
            'service_policy_sha256', v_service_policy_sha256,
            'service_release_binding_id',
                p_service_release_binding_id::text,
            'service_release_sha256', v_release_sha256,
            'service_urn', p_service_urn,
            'tenant_id', p_tenant_id
        );
        v_generation := gda_control.gis_mvt_cache_generation(
            v_cache_namespace, p_tenant_id, p_service_urn,
            p_service_release_binding_id, v_release_sha256,
            v_cache_policy_id, v_cache_policy_sha256,
            v_service_policy_id, v_service_policy_sha256,
            v_projection_id, v_projection_sha256,
            p_endpoint_state_version, p_endpoint_revision_id,
            v_endpoint_sha256
        );
    END IF;

    IF v_status = 'bypassed' THEN
        v_cache_namespace := NULL;
    END IF;

    v_task_id := gen_random_uuid();
    PERFORM set_config(
        'gda.gis_mvt_cache_purge_insert_allowed',
        p_source_kind || ':' || p_source_receipt_id::text,
        true
    );
    INSERT INTO gda_control.gis_mvt_cache_purge_outbox (
        tenant_id, purge_task_id, source_kind, source_receipt_id,
        source_receipt_sha256, service_urn, endpoint_revision_id,
        service_definition_version_id, service_release_binding_id,
        endpoint_state_version, cache_namespace, cache_context,
        generation_token, status, bypass_reason, available_at,
        created_at, completed_at
    ) VALUES (
        p_tenant_id, v_task_id, p_source_kind, p_source_receipt_id,
        p_source_receipt_sha256, p_service_urn, p_endpoint_revision_id,
        p_service_definition_version_id, p_service_release_binding_id,
        p_endpoint_state_version, v_cache_namespace, v_context,
        v_generation, v_status, v_bypass_reason, p_created_at,
        p_created_at,
        CASE WHEN v_status = 'bypassed' THEN p_created_at ELSE NULL END
    );
    RETURN v_task_id;
END;
$$;

CREATE FUNCTION gda_control.enqueue_cutover_mvt_cache_purge()
RETURNS TRIGGER
LANGUAGE plpgsql
SET search_path = pg_catalog, gda_control
AS $$
BEGIN
    PERFORM gda_control.enqueue_gis_mvt_cache_purge(
        NEW.tenant_id, 'cutover', NEW.cutover_id, NEW.cutover_sha256,
        NEW.service_urn, NEW.source_endpoint_revision_id,
        NEW.source_service_definition_version_id,
        NEW.source_service_release_binding_id,
        NEW.from_state_version, NEW.occurred_at
    );
    RETURN NEW;
END;
$$;

CREATE FUNCTION gda_control.enqueue_rollback_mvt_cache_purge()
RETURNS TRIGGER
LANGUAGE plpgsql
SET search_path = pg_catalog, gda_control
AS $$
BEGIN
    PERFORM gda_control.enqueue_gis_mvt_cache_purge(
        NEW.tenant_id, 'rollback', NEW.rollback_id, NEW.rollback_sha256,
        NEW.service_urn, NEW.from_endpoint_revision_id,
        NEW.from_service_definition_version_id,
        NEW.from_service_release_binding_id,
        NEW.from_state_version, NEW.occurred_at
    );
    RETURN NEW;
END;
$$;

CREATE TRIGGER trg_gda_cutover_mvt_cache_purge
AFTER INSERT ON gda_control.gis_service_migration_cutover
FOR EACH ROW EXECUTE FUNCTION gda_control.enqueue_cutover_mvt_cache_purge();
CREATE TRIGGER trg_gda_rollback_mvt_cache_purge
AFTER INSERT ON gda_control.gis_service_migration_rollback
FOR EACH ROW EXECUTE FUNCTION gda_control.enqueue_rollback_mvt_cache_purge();

CREATE FUNCTION gda_control.claim_gis_mvt_cache_purges(
    p_tenant_id TEXT,
    p_actor_subject TEXT,
    p_worker_id TEXT,
    p_limit INTEGER DEFAULT 10,
    p_lease_seconds INTEGER DEFAULT 60
)
RETURNS SETOF gda_control.gis_mvt_cache_purge_outbox
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, gda_control
SET row_security = on
AS $$
BEGIN
    IF gda_control.current_tenant() IS DISTINCT FROM p_tenant_id THEN
        RAISE EXCEPTION 'cache purge tenant context mismatch'
            USING ERRCODE = '42501';
    END IF;
    IF p_actor_subject <> 'workload:gis-mvt-cache-purge-controller'
       OR NULLIF(btrim(p_worker_id), '') IS NULL THEN
        RAISE EXCEPTION 'cache purge worker authority is invalid'
            USING ERRCODE = '42501';
    END IF;
    IF p_limit IS NULL OR p_limit < 1 OR p_limit > 100
       OR p_lease_seconds IS NULL
       OR p_lease_seconds < 5 OR p_lease_seconds > 3600 THEN
        RAISE EXCEPTION 'cache purge claim bounds are invalid'
            USING ERRCODE = '22023';
    END IF;

    UPDATE gda_control.gis_mvt_cache_purge_outbox
       SET status = CASE
               WHEN attempt_count >= max_attempts THEN 'failed'
               ELSE 'pending'
           END,
           available_at = clock_timestamp(),
           claimed_by = NULL,
           claimed_until = NULL,
           last_error = COALESCE(last_error, 'worker lease expired'),
           completed_at = CASE
               WHEN attempt_count >= max_attempts THEN clock_timestamp()
               ELSE NULL
           END
     WHERE tenant_id = p_tenant_id
       AND status = 'in_flight'
       AND claimed_until <= clock_timestamp();

    RETURN QUERY
    WITH due AS (
        SELECT purge_task_id
          FROM gda_control.gis_mvt_cache_purge_outbox
         WHERE tenant_id = p_tenant_id
           AND status = 'pending'
           AND available_at <= clock_timestamp()
         ORDER BY available_at, created_at, purge_task_id
         FOR UPDATE SKIP LOCKED
         LIMIT p_limit
    )
    UPDATE gda_control.gis_mvt_cache_purge_outbox AS task
       SET status = 'in_flight',
           attempt_count = task.attempt_count + 1,
           claimed_by = p_worker_id,
           claimed_until = clock_timestamp() +
               make_interval(secs => p_lease_seconds),
           last_error = NULL
      FROM due
     WHERE task.tenant_id = p_tenant_id
       AND task.purge_task_id = due.purge_task_id
    RETURNING task.*;
END;
$$;

CREATE FUNCTION gda_control.complete_gis_mvt_cache_purge(
    p_tenant_id TEXT,
    p_purge_task_id UUID,
    p_worker_id TEXT,
    p_matched_keys INTEGER,
    p_deleted_keys INTEGER,
    p_remaining_keys INTEGER
)
RETURNS SETOF gda_control.gis_mvt_cache_purge_outbox
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, gda_control
SET row_security = on
AS $$
DECLARE
    v_task gda_control.gis_mvt_cache_purge_outbox%ROWTYPE;
BEGIN
    IF gda_control.current_tenant() IS DISTINCT FROM p_tenant_id THEN
        RAISE EXCEPTION 'cache purge tenant context mismatch'
            USING ERRCODE = '42501';
    END IF;
    SELECT * INTO v_task
      FROM gda_control.gis_mvt_cache_purge_outbox
     WHERE tenant_id = p_tenant_id AND purge_task_id = p_purge_task_id
     FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'cache purge task was not found' USING ERRCODE = 'P0002';
    END IF;
    IF v_task.status = 'done'
       AND v_task.matched_keys = p_matched_keys
       AND v_task.deleted_keys = p_deleted_keys
       AND v_task.remaining_keys = p_remaining_keys THEN
        RETURN NEXT v_task;
        RETURN;
    END IF;
    IF v_task.status <> 'in_flight'
       OR v_task.claimed_by IS DISTINCT FROM p_worker_id
       OR v_task.claimed_until <= clock_timestamp() THEN
        RAISE EXCEPTION 'cache purge task is not held by this worker'
            USING ERRCODE = '40001';
    END IF;
    IF p_matched_keys < 0 OR p_deleted_keys < 0
       OR p_deleted_keys > p_matched_keys OR p_remaining_keys <> 0 THEN
        RAISE EXCEPTION 'cache purge result is not complete'
            USING ERRCODE = '22023';
    END IF;
    UPDATE gda_control.gis_mvt_cache_purge_outbox
       SET status = 'done', claimed_by = NULL, claimed_until = NULL,
           matched_keys = p_matched_keys, deleted_keys = p_deleted_keys,
           remaining_keys = p_remaining_keys,
           completed_at = clock_timestamp()
     WHERE tenant_id = p_tenant_id AND purge_task_id = p_purge_task_id
     RETURNING * INTO v_task;
    RETURN NEXT v_task;
END;
$$;

CREATE FUNCTION gda_control.fail_gis_mvt_cache_purge(
    p_tenant_id TEXT,
    p_purge_task_id UUID,
    p_worker_id TEXT,
    p_error TEXT,
    p_retry_delay_seconds INTEGER DEFAULT 30
)
RETURNS SETOF gda_control.gis_mvt_cache_purge_outbox
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, gda_control
SET row_security = on
AS $$
DECLARE
    v_task gda_control.gis_mvt_cache_purge_outbox%ROWTYPE;
BEGIN
    IF gda_control.current_tenant() IS DISTINCT FROM p_tenant_id THEN
        RAISE EXCEPTION 'cache purge tenant context mismatch'
            USING ERRCODE = '42501';
    END IF;
    IF NULLIF(btrim(p_error), '') IS NULL OR length(p_error) > 2048
       OR p_retry_delay_seconds < 0 OR p_retry_delay_seconds > 86400 THEN
        RAISE EXCEPTION 'cache purge failure details are invalid'
            USING ERRCODE = '22023';
    END IF;
    SELECT * INTO v_task
      FROM gda_control.gis_mvt_cache_purge_outbox
     WHERE tenant_id = p_tenant_id AND purge_task_id = p_purge_task_id
     FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'cache purge task was not found' USING ERRCODE = 'P0002';
    END IF;
    IF v_task.status <> 'in_flight'
       OR v_task.claimed_by IS DISTINCT FROM p_worker_id
       OR v_task.claimed_until <= clock_timestamp() THEN
        RAISE EXCEPTION 'cache purge task is not held by this worker'
            USING ERRCODE = '40001';
    END IF;
    UPDATE gda_control.gis_mvt_cache_purge_outbox
       SET status = CASE
               WHEN attempt_count >= max_attempts THEN 'failed'
               ELSE 'pending'
           END,
           available_at = clock_timestamp() +
               make_interval(secs => p_retry_delay_seconds),
           claimed_by = NULL, claimed_until = NULL,
           last_error = p_error,
           completed_at = CASE
               WHEN attempt_count >= max_attempts THEN clock_timestamp()
               ELSE NULL
           END
     WHERE tenant_id = p_tenant_id AND purge_task_id = p_purge_task_id
     RETURNING * INTO v_task;
    RETURN NEXT v_task;
END;
$$;

ALTER TABLE gda_control.gis_mvt_cache_purge_outbox ENABLE ROW LEVEL SECURITY;
ALTER TABLE gda_control.gis_mvt_cache_purge_outbox FORCE ROW LEVEL SECURITY;
CREATE POLICY gda_gis_mvt_cache_purge_tenant_isolation
    ON gda_control.gis_mvt_cache_purge_outbox
    USING (tenant_id = gda_control.current_tenant())
    WITH CHECK (tenant_id = gda_control.current_tenant());

REVOKE ALL ON TABLE gda_control.gis_mvt_cache_purge_outbox
    FROM PUBLIC, gda_control_gateway;
GRANT SELECT ON TABLE gda_control.gis_mvt_cache_purge_outbox
    TO gda_control_gateway;
REVOKE ALL ON FUNCTION gda_control.enqueue_gis_mvt_cache_purge(
    TEXT, TEXT, UUID, TEXT, TEXT, UUID, UUID, UUID, INTEGER, TIMESTAMPTZ
) FROM PUBLIC, gda_control_gateway;
REVOKE ALL ON FUNCTION gda_control.claim_gis_mvt_cache_purges(
    TEXT, TEXT, TEXT, INTEGER, INTEGER
) FROM PUBLIC, gda_control_gateway;
GRANT EXECUTE ON FUNCTION gda_control.claim_gis_mvt_cache_purges(
    TEXT, TEXT, TEXT, INTEGER, INTEGER
) TO gda_control_gateway;
REVOKE ALL ON FUNCTION gda_control.complete_gis_mvt_cache_purge(
    TEXT, UUID, TEXT, INTEGER, INTEGER, INTEGER
) FROM PUBLIC, gda_control_gateway;
GRANT EXECUTE ON FUNCTION gda_control.complete_gis_mvt_cache_purge(
    TEXT, UUID, TEXT, INTEGER, INTEGER, INTEGER
) TO gda_control_gateway;
REVOKE ALL ON FUNCTION gda_control.fail_gis_mvt_cache_purge(
    TEXT, UUID, TEXT, TEXT, INTEGER
) FROM PUBLIC, gda_control_gateway;
GRANT EXECUTE ON FUNCTION gda_control.fail_gis_mvt_cache_purge(
    TEXT, UUID, TEXT, TEXT, INTEGER
) TO gda_control_gateway;
