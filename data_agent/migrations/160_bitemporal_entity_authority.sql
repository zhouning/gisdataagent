-- 160: Append-only bitemporal entity identity and lifecycle authority.

CREATE EXTENSION IF NOT EXISTS pgcrypto WITH SCHEMA public;

CREATE TABLE IF NOT EXISTS gda_control.temporal_entity_identity (
    tenant_id TEXT NOT NULL,
    entity_ref TEXT NOT NULL,
    object_type TEXT NOT NULL,
    owner_subject TEXT NOT NULL,
    created_by TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (tenant_id, entity_ref),
    CONSTRAINT ck_gda_temporal_entity_ref CHECK (
        entity_ref ~ '^gda://[a-z0-9][a-z0-9._-]{0,63}/entity/[a-z0-9][a-z0-9._-]{0,127}$'
        AND split_part(entity_ref, '/', 3) = tenant_id
    ),
    CONSTRAINT ck_gda_temporal_entity_type
        CHECK (object_type ~ '^[a-z][a-z0-9_.-]{2,127}$'),
    CONSTRAINT ck_gda_temporal_entity_owner
        CHECK (owner_subject ~ '^(human|team):[^[:space:]]{1,128}$'),
    CONSTRAINT ck_gda_temporal_entity_creator
        CHECK (created_by ~ '^(human|workload|agent):[^[:space:]]{1,128}$')
);

CREATE TABLE IF NOT EXISTS gda_control.temporal_entity_assertion (
    tenant_id TEXT NOT NULL,
    assertion_id UUID NOT NULL DEFAULT gen_random_uuid(),
    entity_ref TEXT NOT NULL,
    object_type TEXT NOT NULL,
    lifecycle_state TEXT NOT NULL,
    attributes JSONB NOT NULL,
    valid_from TIMESTAMPTZ NOT NULL,
    valid_to TIMESTAMPTZ,
    source_version_refs JSONB NOT NULL,
    mutation_kind TEXT NOT NULL,
    supersedes_assertion_id UUID,
    idempotency_key TEXT NOT NULL,
    owner_subject TEXT NOT NULL,
    recorded_by TEXT NOT NULL,
    reason TEXT NOT NULL,
    assertion_sha256 CHAR(64) NOT NULL,
    recorded_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (tenant_id, assertion_id),
    CONSTRAINT uq_gda_temporal_entity_idempotency
        UNIQUE (tenant_id, idempotency_key),
    CONSTRAINT fk_gda_temporal_assertion_identity
        FOREIGN KEY (tenant_id, entity_ref)
        REFERENCES gda_control.temporal_entity_identity(tenant_id, entity_ref),
    CONSTRAINT fk_gda_temporal_assertion_supersedes
        FOREIGN KEY (tenant_id, supersedes_assertion_id)
        REFERENCES gda_control.temporal_entity_assertion(tenant_id, assertion_id),
    CONSTRAINT ck_gda_temporal_assertion_type
        CHECK (object_type ~ '^[a-z][a-z0-9_.-]{2,127}$'),
    CONSTRAINT ck_gda_temporal_assertion_state
        CHECK (lifecycle_state IN ('draft', 'active', 'suspended', 'retired', 'deleted')),
    CONSTRAINT ck_gda_temporal_assertion_attributes
        CHECK (jsonb_typeof(attributes) = 'object'),
    CONSTRAINT ck_gda_temporal_assertion_valid_time
        CHECK (valid_to IS NULL OR valid_to > valid_from),
    CONSTRAINT ck_gda_temporal_assertion_sources CHECK (
        jsonb_typeof(source_version_refs) = 'array'
        AND jsonb_array_length(source_version_refs) BETWEEN 1 AND 100
    ),
    CONSTRAINT ck_gda_temporal_assertion_mutation CHECK (
        mutation_kind IN ('initial', 'transition', 'correction')
        AND ((mutation_kind = 'correction') = (supersedes_assertion_id IS NOT NULL))
    ),
    CONSTRAINT ck_gda_temporal_assertion_idempotency
        CHECK (idempotency_key ~ '^[A-Za-z0-9][A-Za-z0-9._:-]{2,127}$'),
    CONSTRAINT ck_gda_temporal_assertion_owner
        CHECK (owner_subject ~ '^(human|team):[^[:space:]]{1,128}$'),
    CONSTRAINT ck_gda_temporal_assertion_recorder
        CHECK (recorded_by ~ '^(human|workload|agent):[^[:space:]]{1,128}$'),
    CONSTRAINT ck_gda_temporal_assertion_reason
        CHECK (NULLIF(btrim(reason), '') IS NOT NULL),
    CONSTRAINT ck_gda_temporal_assertion_sha256
        CHECK (assertion_sha256 ~ '^[0-9a-f]{64}$')
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_gda_temporal_entity_base_event
    ON gda_control.temporal_entity_assertion(tenant_id, entity_ref, valid_from)
    WHERE supersedes_assertion_id IS NULL;

CREATE UNIQUE INDEX IF NOT EXISTS uq_gda_temporal_entity_correction_target
    ON gda_control.temporal_entity_assertion(tenant_id, supersedes_assertion_id)
    WHERE supersedes_assertion_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_gda_temporal_entity_valid_time
    ON gda_control.temporal_entity_assertion(
        tenant_id, entity_ref, valid_from DESC, recorded_at DESC
    );

CREATE INDEX IF NOT EXISTS idx_gda_temporal_entity_known_time
    ON gda_control.temporal_entity_assertion(
        tenant_id, entity_ref, recorded_at DESC
    );

CREATE OR REPLACE FUNCTION gda_control.temporal_transition_allowed(
    p_from TEXT,
    p_to TEXT
)
RETURNS BOOLEAN
LANGUAGE sql
IMMUTABLE
STRICT
SET search_path = pg_catalog
AS $$
    SELECT CASE p_from
        WHEN 'draft' THEN p_to IN ('active', 'deleted')
        WHEN 'active' THEN p_to IN ('suspended', 'retired', 'deleted')
        WHEN 'suspended' THEN p_to IN ('active', 'retired', 'deleted')
        ELSE FALSE
    END
$$;

CREATE OR REPLACE FUNCTION gda_control.record_temporal_entity_assertion(
    p_tenant_id TEXT,
    p_entity_ref TEXT,
    p_object_type TEXT,
    p_lifecycle_state TEXT,
    p_attributes JSONB,
    p_valid_from TIMESTAMPTZ,
    p_valid_to TIMESTAMPTZ,
    p_source_version_refs JSONB,
    p_mutation_kind TEXT,
    p_supersedes_assertion_id UUID,
    p_idempotency_key TEXT,
    p_owner_subject TEXT,
    p_recorded_by TEXT,
    p_reason TEXT
)
RETURNS gda_control.temporal_entity_assertion
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, gda_control, public
SET row_security = on
AS $$
DECLARE
    v_identity gda_control.temporal_entity_identity%ROWTYPE;
    v_existing gda_control.temporal_entity_assertion%ROWTYPE;
    v_target gda_control.temporal_entity_assertion%ROWTYPE;
    v_previous gda_control.temporal_entity_assertion%ROWTYPE;
    v_next gda_control.temporal_entity_assertion%ROWTYPE;
    v_document JSONB;
    v_fingerprint TEXT;
    v_recorded_at TIMESTAMPTZ := clock_timestamp();
BEGIN
    IF gda_control.current_tenant() IS NULL
       OR p_tenant_id IS DISTINCT FROM gda_control.current_tenant() THEN
        RAISE EXCEPTION 'temporal entity tenant context is missing or mismatched'
            USING ERRCODE = '42501';
    END IF;
    IF p_entity_ref IS NULL
       OR p_object_type IS NULL
       OR p_lifecycle_state IS NULL
       OR p_attributes IS NULL
       OR p_source_version_refs IS NULL
       OR p_mutation_kind IS NULL
       OR p_idempotency_key IS NULL
       OR p_owner_subject IS NULL
       OR p_recorded_by IS NULL
       OR p_reason IS NULL
       OR p_entity_ref !~ '^gda://[a-z0-9][a-z0-9._-]{0,63}/entity/[a-z0-9][a-z0-9._-]{0,127}$'
       OR split_part(p_entity_ref, '/', 3) <> p_tenant_id
       OR p_object_type !~ '^[a-z][a-z0-9_.-]{2,127}$'
       OR p_lifecycle_state NOT IN ('draft', 'active', 'suspended', 'retired', 'deleted')
       OR jsonb_typeof(p_attributes) <> 'object'
       OR octet_length(p_attributes::text) > 262144
       OR p_valid_from IS NULL
       OR (p_valid_to IS NOT NULL AND p_valid_to <= p_valid_from)
       OR p_mutation_kind NOT IN ('initial', 'transition', 'correction')
       OR ((p_mutation_kind = 'correction') <> (p_supersedes_assertion_id IS NOT NULL))
       OR p_idempotency_key !~ '^[A-Za-z0-9][A-Za-z0-9._:-]{2,127}$'
       OR p_owner_subject !~ '^(human|team):[^[:space:]]{1,128}$'
       OR p_recorded_by !~ '^(human|workload|agent):[^[:space:]]{1,128}$'
       OR NULLIF(btrim(p_reason), '') IS NULL
       OR char_length(p_reason) > 512
       OR octet_length(p_reason) > 2048 THEN
        RAISE EXCEPTION 'temporal entity identity, time or provenance is invalid'
            USING ERRCODE = '22023';
    END IF;
    IF jsonb_typeof(p_source_version_refs) <> 'array'
       OR jsonb_array_length(p_source_version_refs) NOT BETWEEN 1 AND 100
       OR EXISTS (
            SELECT 1
            FROM jsonb_array_elements(p_source_version_refs) item(value)
            WHERE jsonb_typeof(value) <> 'string'
       )
       OR EXISTS (
            SELECT 1
            FROM jsonb_array_elements_text(p_source_version_refs) item(value)
            WHERE value !~ '^gda://[a-z0-9][a-z0-9._-]{0,63}/[a-z][a-z0-9_-]{1,31}/[a-z0-9][a-z0-9._-]{0,127}$'
               OR split_part(value, '/', 3) <> p_tenant_id
       )
       OR (
            SELECT COUNT(*) <> COUNT(DISTINCT value)
                OR array_agg(value) IS DISTINCT FROM array_agg(value ORDER BY value)
            FROM jsonb_array_elements_text(p_source_version_refs) item(value)
       ) THEN
        RAISE EXCEPTION 'temporal source versions must be sorted unique tenant URNs'
            USING ERRCODE = '22023';
    END IF;

    v_document := jsonb_build_object(
        'schema_id', 'gda.temporal-entity-assertion.v1',
        'tenant_id', p_tenant_id,
        'entity_ref', p_entity_ref,
        'object_type', p_object_type,
        'lifecycle_state', p_lifecycle_state,
        'attributes', p_attributes,
        'valid_from', p_valid_from,
        'valid_to', p_valid_to,
        'source_version_refs', p_source_version_refs,
        'mutation_kind', p_mutation_kind,
        'supersedes_assertion_id', p_supersedes_assertion_id,
        'idempotency_key', p_idempotency_key,
        'owner_subject', p_owner_subject,
        'recorded_by', p_recorded_by,
        'reason', p_reason
    );
    v_fingerprint := encode(
        public.digest(convert_to(v_document::text, 'UTF8'), 'sha256'),
        'hex'
    );

    PERFORM pg_advisory_xact_lock(
        hashtextextended(
            'temporal-idempotency|' || p_tenant_id || '|' || p_idempotency_key,
            0
        )
    );
    PERFORM pg_advisory_xact_lock(
        hashtextextended('temporal-entity|' || p_tenant_id || '|' || p_entity_ref, 0)
    );

    SELECT * INTO v_existing
    FROM gda_control.temporal_entity_assertion
    WHERE tenant_id = p_tenant_id
      AND idempotency_key = p_idempotency_key;
    IF FOUND THEN
        IF v_existing.assertion_sha256 <> v_fingerprint THEN
            RAISE EXCEPTION 'temporal idempotency key already has different evidence'
                USING ERRCODE = '40001';
        END IF;
        RETURN v_existing;
    END IF;

    SELECT * INTO v_identity
    FROM gda_control.temporal_entity_identity
    WHERE tenant_id = p_tenant_id AND entity_ref = p_entity_ref;

    IF p_mutation_kind = 'initial' THEN
        IF FOUND OR EXISTS (
            SELECT 1 FROM gda_control.temporal_entity_assertion
            WHERE tenant_id = p_tenant_id AND entity_ref = p_entity_ref
        ) THEN
            RAISE EXCEPTION 'initial assertion requires a new stable entity identity'
                USING ERRCODE = '40001';
        END IF;
        INSERT INTO gda_control.temporal_entity_identity (
            tenant_id, entity_ref, object_type, owner_subject, created_by, created_at
        ) VALUES (
            p_tenant_id, p_entity_ref, p_object_type, p_owner_subject,
            p_recorded_by, v_recorded_at
        );
    ELSE
        IF NOT FOUND THEN
            RAISE EXCEPTION 'temporal entity identity was not found'
                USING ERRCODE = 'P0002';
        END IF;
        IF v_identity.object_type <> p_object_type
           OR v_identity.owner_subject <> p_owner_subject THEN
            RAISE EXCEPTION 'stable temporal entity type or owner cannot change'
                USING ERRCODE = '23514';
        END IF;
    END IF;

    IF p_mutation_kind = 'correction' THEN
        SELECT * INTO v_target
        FROM gda_control.temporal_entity_assertion
        WHERE tenant_id = p_tenant_id
          AND assertion_id = p_supersedes_assertion_id
        FOR UPDATE;
        IF NOT FOUND
           OR v_target.entity_ref <> p_entity_ref
           OR v_target.object_type <> p_object_type THEN
            RAISE EXCEPTION 'correction target was not found for this entity'
                USING ERRCODE = 'P0002';
        END IF;
        IF v_target.valid_from <> p_valid_from
           OR v_target.lifecycle_state <> p_lifecycle_state THEN
            RAISE EXCEPTION 'correction cannot move an event or change its lifecycle transition'
                USING ERRCODE = '23514';
        END IF;
        IF EXISTS (
            SELECT 1 FROM gda_control.temporal_entity_assertion child
            WHERE child.tenant_id = p_tenant_id
              AND child.supersedes_assertion_id = v_target.assertion_id
        ) THEN
            RAISE EXCEPTION 'correction target has already been superseded'
                USING ERRCODE = '40001';
        END IF;
        v_recorded_at := GREATEST(
            v_recorded_at,
            v_target.recorded_at + INTERVAL '1 microsecond'
        );
    ELSIF p_mutation_kind = 'transition' THEN
        SELECT candidate.* INTO v_previous
        FROM gda_control.temporal_entity_assertion candidate
        WHERE candidate.tenant_id = p_tenant_id
          AND candidate.entity_ref = p_entity_ref
          AND candidate.valid_from < p_valid_from
          AND NOT EXISTS (
              SELECT 1 FROM gda_control.temporal_entity_assertion child
              WHERE child.tenant_id = candidate.tenant_id
                AND child.supersedes_assertion_id = candidate.assertion_id
          )
        ORDER BY candidate.valid_from DESC, candidate.recorded_at DESC
        LIMIT 1;
        IF NOT FOUND THEN
            RAISE EXCEPTION 'transition requires a prior visible lifecycle event'
                USING ERRCODE = '23514';
        END IF;
        IF NOT gda_control.temporal_transition_allowed(
            v_previous.lifecycle_state,
            p_lifecycle_state
        ) THEN
            RAISE EXCEPTION 'temporal lifecycle transition is not allowed'
                USING ERRCODE = '23514';
        END IF;
        SELECT candidate.* INTO v_next
        FROM gda_control.temporal_entity_assertion candidate
        WHERE candidate.tenant_id = p_tenant_id
          AND candidate.entity_ref = p_entity_ref
          AND candidate.valid_from > p_valid_from
          AND NOT EXISTS (
              SELECT 1 FROM gda_control.temporal_entity_assertion child
              WHERE child.tenant_id = candidate.tenant_id
                AND child.supersedes_assertion_id = candidate.assertion_id
          )
        ORDER BY candidate.valid_from ASC, candidate.recorded_at DESC
        LIMIT 1;
        IF FOUND AND NOT gda_control.temporal_transition_allowed(
            p_lifecycle_state,
            v_next.lifecycle_state
        ) THEN
            RAISE EXCEPTION 'late temporal transition invalidates its successor'
                USING ERRCODE = '23514';
        END IF;
    END IF;

    INSERT INTO gda_control.temporal_entity_assertion (
        tenant_id, entity_ref, object_type, lifecycle_state, attributes,
        valid_from, valid_to, source_version_refs, mutation_kind,
        supersedes_assertion_id, idempotency_key, owner_subject,
        recorded_by, reason, assertion_sha256, recorded_at
    ) VALUES (
        p_tenant_id, p_entity_ref, p_object_type, p_lifecycle_state, p_attributes,
        p_valid_from, p_valid_to, p_source_version_refs, p_mutation_kind,
        p_supersedes_assertion_id, p_idempotency_key, p_owner_subject,
        p_recorded_by, p_reason, v_fingerprint, v_recorded_at
    )
    RETURNING * INTO v_existing;
    RETURN v_existing;
END;
$$;

ALTER TABLE gda_control.temporal_entity_identity ENABLE ROW LEVEL SECURITY;
ALTER TABLE gda_control.temporal_entity_identity FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON gda_control.temporal_entity_identity;
CREATE POLICY tenant_isolation ON gda_control.temporal_entity_identity
    USING (tenant_id = gda_control.current_tenant())
    WITH CHECK (tenant_id = gda_control.current_tenant());

ALTER TABLE gda_control.temporal_entity_assertion ENABLE ROW LEVEL SECURITY;
ALTER TABLE gda_control.temporal_entity_assertion FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON gda_control.temporal_entity_assertion;
CREATE POLICY tenant_isolation ON gda_control.temporal_entity_assertion
    USING (tenant_id = gda_control.current_tenant())
    WITH CHECK (tenant_id = gda_control.current_tenant());

DROP TRIGGER IF EXISTS trg_gda_temporal_entity_identity_immutable
    ON gda_control.temporal_entity_identity;
CREATE TRIGGER trg_gda_temporal_entity_identity_immutable
BEFORE UPDATE OR DELETE ON gda_control.temporal_entity_identity
FOR EACH ROW EXECUTE FUNCTION gda_control.reject_immutable_mutation();

DROP TRIGGER IF EXISTS trg_gda_temporal_entity_assertion_immutable
    ON gda_control.temporal_entity_assertion;
CREATE TRIGGER trg_gda_temporal_entity_assertion_immutable
BEFORE UPDATE OR DELETE ON gda_control.temporal_entity_assertion
FOR EACH ROW EXECUTE FUNCTION gda_control.reject_immutable_mutation();

REVOKE ALL ON TABLE gda_control.temporal_entity_identity
    FROM PUBLIC, gda_control_gateway;
REVOKE ALL ON TABLE gda_control.temporal_entity_assertion
    FROM PUBLIC, gda_control_gateway;
REVOKE ALL ON FUNCTION gda_control.record_temporal_entity_assertion(
    TEXT, TEXT, TEXT, TEXT, JSONB, TIMESTAMPTZ, TIMESTAMPTZ, JSONB,
    TEXT, UUID, TEXT, TEXT, TEXT, TEXT
) FROM PUBLIC;

GRANT SELECT ON TABLE gda_control.temporal_entity_identity
    TO gda_control_gateway;
GRANT SELECT ON TABLE gda_control.temporal_entity_assertion
    TO gda_control_gateway;
GRANT EXECUTE ON FUNCTION gda_control.record_temporal_entity_assertion(
    TEXT, TEXT, TEXT, TEXT, JSONB, TIMESTAMPTZ, TIMESTAMPTZ, JSONB,
    TEXT, UUID, TEXT, TEXT, TEXT, TEXT
) TO gda_control_gateway;
