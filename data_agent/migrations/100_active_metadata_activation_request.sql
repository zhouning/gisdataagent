-- 100: Durable Active Metadata activation requests.
--
-- A MetadataChangeEvent may be marked processed only when its deterministic
-- activation request is persisted in the same transaction. The request is
-- deliberately inert: authorization, scheduler submission and provider
-- mutation remain separate, evidence-gated operations.

CREATE TABLE IF NOT EXISTS gda_control.metadata_activation_request (
    tenant_id TEXT NOT NULL,
    request_id UUID PRIMARY KEY,
    event_id UUID NOT NULL,
    event_sha256 CHAR(64) NOT NULL,
    resource_urn TEXT NOT NULL,
    resource_version_id UUID NOT NULL,
    content_sha256 CHAR(64) NOT NULL,
    activation_intent_sha256 CHAR(64) NOT NULL,
    route TEXT NOT NULL,
    requested_by TEXT NOT NULL,
    request JSONB NOT NULL,
    request_sha256 CHAR(64) NOT NULL,
    status TEXT NOT NULL DEFAULT 'awaiting_authorization',
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT uq_gda_metadata_activation_tenant_request
        UNIQUE (tenant_id, request_id),
    CONSTRAINT uq_gda_metadata_activation_event
        UNIQUE (tenant_id, event_id),
    CONSTRAINT uq_gda_metadata_activation_request_sha
        UNIQUE (tenant_id, request_sha256),
    CONSTRAINT fk_gda_metadata_activation_event
        FOREIGN KEY (tenant_id, event_id)
        REFERENCES gda_control.metadata_change_outbox(tenant_id, event_id),
    CONSTRAINT fk_gda_metadata_activation_version
        FOREIGN KEY (
            tenant_id, resource_urn, resource_version_id, content_sha256
        ) REFERENCES gda_control.resource_version(
            tenant_id, resource_urn, resource_version_id, content_sha256
        ),
    CONSTRAINT ck_gda_metadata_activation_hashes CHECK (
        event_sha256 ~ '^[0-9a-f]{64}$'
        AND content_sha256 ~ '^[0-9a-f]{64}$'
        AND activation_intent_sha256 ~ '^[0-9a-f]{64}$'
        AND request_sha256 ~ '^[0-9a-f]{64}$'
    ),
    CONSTRAINT ck_gda_metadata_activation_route CHECK (
        route = 'metadata_fabric.projection_plan'
    ),
    CONSTRAINT ck_gda_metadata_activation_requester CHECK (
        requested_by ~ '^workload:.+'
    ),
    CONSTRAINT ck_gda_metadata_activation_status CHECK (
        status = 'awaiting_authorization'
    ),
    CONSTRAINT ck_gda_metadata_activation_document CHECK (
        jsonb_typeof(request) = 'object'
        AND request ?& ARRAY[
            'schema', 'request_id', 'intent', 'status',
            'provider_apply_authorized', 'provider_mutations_executed',
            'production_scheduler_submission_verified',
            'production_ingestion_verified', 'production_ready',
            'request_sha256'
        ]
        AND request - ARRAY[
            'schema', 'request_id', 'intent', 'status',
            'provider_apply_authorized', 'provider_mutations_executed',
            'production_scheduler_submission_verified',
            'production_ingestion_verified', 'production_ready',
            'request_sha256'
        ] = '{}'::jsonb
        AND request->>'schema' = 'gda.metadata_activation_request.v1'
        AND request->>'request_id' = request_id::text
        AND request->>'status' = status
        AND request->>'request_sha256' = request_sha256
        AND (request->>'provider_apply_authorized')::boolean = false
        AND (request->>'provider_mutations_executed')::boolean = false
        AND (
            request->>'production_scheduler_submission_verified'
        )::boolean = false
        AND (request->>'production_ingestion_verified')::boolean = false
        AND (request->>'production_ready')::boolean = false
        AND jsonb_typeof(request->'intent') = 'object'
        AND (request->'intent') ?& ARRAY[
            'schema', 'event_id', 'event_sha256', 'tenant_id',
            'resource_urn', 'resource_version_id', 'content_sha256',
            'route', 'routed_by', 'provider_apply_authorized',
            'provider_mutations_executed',
            'production_ingestion_verified', 'intent_sha256'
        ]
        AND (request->'intent') - ARRAY[
            'schema', 'event_id', 'event_sha256', 'tenant_id',
            'resource_urn', 'resource_version_id', 'content_sha256',
            'route', 'routed_by', 'provider_apply_authorized',
            'provider_mutations_executed',
            'production_ingestion_verified', 'intent_sha256'
        ] = '{}'::jsonb
        AND request->'intent'->>'schema' = 'gda.metadata_activation_intent.v1'
        AND request->'intent'->>'event_id' = event_id::text
        AND request->'intent'->>'event_sha256' = event_sha256
        AND request->'intent'->>'tenant_id' = tenant_id
        AND request->'intent'->>'resource_urn' = resource_urn
        AND request->'intent'->>'resource_version_id' = resource_version_id::text
        AND request->'intent'->>'content_sha256' = content_sha256
        AND request->'intent'->>'intent_sha256' = activation_intent_sha256
        AND request->'intent'->>'route' = route
        AND request->'intent'->>'routed_by' = requested_by
        AND (
            request->'intent'->>'provider_apply_authorized'
        )::boolean = false
        AND (
            request->'intent'->>'provider_mutations_executed'
        )::boolean = false
        AND (
            request->'intent'->>'production_ingestion_verified'
        )::boolean = false
    )
);

CREATE INDEX IF NOT EXISTS idx_gda_metadata_activation_pending
    ON gda_control.metadata_activation_request(
        tenant_id, status, created_at, request_id
    );
CREATE INDEX IF NOT EXISTS idx_gda_metadata_activation_resource
    ON gda_control.metadata_activation_request(
        tenant_id, resource_urn, created_at DESC
    );

ALTER TABLE gda_control.metadata_activation_request ENABLE ROW LEVEL SECURITY;
ALTER TABLE gda_control.metadata_activation_request FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS gda_metadata_activation_tenant_isolation
    ON gda_control.metadata_activation_request;
CREATE POLICY gda_metadata_activation_tenant_isolation
    ON gda_control.metadata_activation_request
    USING (tenant_id = gda_control.current_tenant())
    WITH CHECK (tenant_id = gda_control.current_tenant());

CREATE OR REPLACE FUNCTION gda_control.stage_metadata_activation_request(
    p_tenant_id TEXT,
    p_event_id UUID,
    p_worker_id TEXT,
    p_request JSONB
)
RETURNS TABLE(activation_request JSONB, created BOOLEAN)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, gda_control
SET row_security = on
AS $$
DECLARE
    delivery gda_control.metadata_change_outbox%ROWTYPE;
    stored gda_control.metadata_activation_request%ROWTYPE;
    inserted_rows INTEGER := 0;
BEGIN
    IF gda_control.current_tenant() IS DISTINCT FROM p_tenant_id THEN
        RAISE EXCEPTION 'tenant context mismatch' USING ERRCODE = '42501';
    END IF;
    IF COALESCE(btrim(p_worker_id), '') !~ '^worker:.+' THEN
        RAISE EXCEPTION 'worker identity is invalid' USING ERRCODE = '22023';
    END IF;
    IF jsonb_typeof(p_request) IS DISTINCT FROM 'object' THEN
        RAISE EXCEPTION 'activation request must be an object'
            USING ERRCODE = '22023';
    END IF;

    SELECT *
      INTO delivery
      FROM gda_control.metadata_change_outbox
     WHERE tenant_id = p_tenant_id
       AND event_id = p_event_id
     FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'metadata change was not found' USING ERRCODE = 'P0002';
    END IF;

    IF delivery.status = 'processed' THEN
        SELECT *
          INTO stored
          FROM gda_control.metadata_activation_request
         WHERE tenant_id = p_tenant_id
           AND event_id = p_event_id;
        IF NOT FOUND
           OR stored.request IS DISTINCT FROM p_request
           OR stored.activation_intent_sha256 IS DISTINCT FROM
                delivery.activation_intent_sha256 THEN
            RAISE EXCEPTION 'processed metadata change has no exact activation request'
                USING ERRCODE = '23505';
        END IF;
        RETURN QUERY SELECT stored.request, false;
        RETURN;
    END IF;

    IF delivery.status <> 'in_flight'
       OR delivery.claimed_by IS DISTINCT FROM p_worker_id
       OR delivery.claimed_until <= clock_timestamp() THEN
        RAISE EXCEPTION 'metadata change claim is missing, expired, or owned by another worker'
            USING ERRCODE = '40001';
    END IF;

    INSERT INTO gda_control.metadata_activation_request (
        tenant_id, request_id, event_id, event_sha256, resource_urn,
        resource_version_id, content_sha256, activation_intent_sha256,
        route, requested_by, request, request_sha256, status
    ) VALUES (
        p_tenant_id,
        (p_request->>'request_id')::uuid,
        p_event_id,
        delivery.event_sha256,
        delivery.resource_urn,
        delivery.resource_version_id,
        delivery.content_sha256,
        p_request->'intent'->>'intent_sha256',
        p_request->'intent'->>'route',
        p_request->'intent'->>'routed_by',
        p_request,
        p_request->>'request_sha256',
        p_request->>'status'
    )
    ON CONFLICT DO NOTHING;
    GET DIAGNOSTICS inserted_rows = ROW_COUNT;

    SELECT *
      INTO stored
      FROM gda_control.metadata_activation_request
     WHERE tenant_id = p_tenant_id
       AND event_id = p_event_id;
    IF NOT FOUND OR stored.request IS DISTINCT FROM p_request THEN
        RAISE EXCEPTION 'activation request identity already has different content'
            USING ERRCODE = '23505';
    END IF;

    UPDATE gda_control.metadata_change_outbox
       SET status = 'processed',
           claimed_by = NULL,
           claimed_until = NULL,
           last_error_code = NULL,
           activation_intent_sha256 = stored.activation_intent_sha256,
           completed_at = clock_timestamp()
     WHERE tenant_id = p_tenant_id
       AND event_id = p_event_id
       AND status = 'in_flight'
       AND claimed_by = p_worker_id
       AND claimed_until > clock_timestamp();
    IF NOT FOUND THEN
        RAISE EXCEPTION 'metadata change claim changed during activation staging'
            USING ERRCODE = '40001';
    END IF;

    RETURN QUERY SELECT stored.request, inserted_rows = 1;
END;
$$;

-- Migration 099 allowed completion with only an intent fingerprint. Once this
-- migration is present, completion also requires the durable request row.
CREATE OR REPLACE FUNCTION gda_control.complete_metadata_change(
    p_tenant_id TEXT,
    p_event_id UUID,
    p_worker_id TEXT,
    p_activation_intent_sha256 TEXT
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
    IF p_activation_intent_sha256 !~ '^[0-9a-f]{64}$' THEN
        RAISE EXCEPTION 'activation intent fingerprint is invalid'
            USING ERRCODE = '22023';
    END IF;
    IF NOT EXISTS (
        SELECT 1
          FROM gda_control.metadata_activation_request
         WHERE tenant_id = p_tenant_id
           AND event_id = p_event_id
           AND activation_intent_sha256 = p_activation_intent_sha256
           AND status = 'awaiting_authorization'
    ) THEN
        RAISE EXCEPTION 'durable activation request is required before completion'
            USING ERRCODE = '22023';
    END IF;
    RETURN QUERY
    UPDATE gda_control.metadata_change_outbox AS delivery
       SET status = 'processed',
           claimed_by = NULL,
           claimed_until = NULL,
           last_error_code = NULL,
           activation_intent_sha256 = p_activation_intent_sha256,
           completed_at = clock_timestamp()
     WHERE delivery.tenant_id = p_tenant_id
       AND delivery.event_id = p_event_id
       AND delivery.status = 'in_flight'
       AND delivery.claimed_by = p_worker_id
       AND delivery.claimed_until > clock_timestamp()
    RETURNING delivery.*;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'metadata change claim is missing, expired, or owned by another worker'
            USING ERRCODE = '40001';
    END IF;
END;
$$;

REVOKE ALL ON TABLE gda_control.metadata_activation_request FROM PUBLIC;
REVOKE ALL ON TABLE gda_control.metadata_activation_request
    FROM gda_control_gateway;
GRANT SELECT, INSERT ON gda_control.metadata_activation_request
    TO gda_control_gateway;

REVOKE ALL ON FUNCTION gda_control.stage_metadata_activation_request(
    text, uuid, text, jsonb
) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION gda_control.stage_metadata_activation_request(
    text, uuid, text, jsonb
) TO gda_control_gateway;

REVOKE ALL ON FUNCTION gda_control.complete_metadata_change(
    text, uuid, text, text
) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION gda_control.complete_metadata_change(
    text, uuid, text, text
) TO gda_control_gateway;
