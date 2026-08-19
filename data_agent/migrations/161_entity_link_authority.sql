-- 161: Tenant-bound source identity evidence and bitemporal instance links.
--
-- Ontology review status is evidence, not a deployment gate. A technically
-- verified package may be used as an unreviewed baseline while every link
-- remains traceable to its exact package hash and source versions.

CREATE EXTENSION IF NOT EXISTS pgcrypto WITH SCHEMA public;

CREATE TABLE IF NOT EXISTS gda_control.entity_source_identity (
    tenant_id TEXT NOT NULL,
    source_identity_ref TEXT NOT NULL,
    source_system_ref TEXT NOT NULL,
    source_object_type TEXT NOT NULL,
    source_object_id TEXT NOT NULL,
    entity_ref TEXT NOT NULL,
    entity_object_type TEXT NOT NULL,
    ontology_class_uri TEXT NOT NULL,
    owner_subject TEXT NOT NULL,
    created_by TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (tenant_id, source_identity_ref),
    CONSTRAINT uq_gda_entity_source_natural_key UNIQUE (
        tenant_id, source_system_ref, source_object_type, source_object_id
    ),
    CONSTRAINT fk_gda_entity_source_entity
        FOREIGN KEY (tenant_id, entity_ref)
        REFERENCES gda_control.temporal_entity_identity(tenant_id, entity_ref),
    CONSTRAINT ck_gda_entity_source_identity_ref CHECK (
        source_identity_ref ~ '^gda://[a-z0-9][a-z0-9._-]{0,63}/source_identity/[a-z0-9][a-z0-9._-]{0,127}$'
        AND split_part(source_identity_ref, '/', 3) = tenant_id
    ),
    CONSTRAINT ck_gda_entity_source_system_ref CHECK (
        source_system_ref ~ '^gda://[a-z0-9][a-z0-9._-]{0,63}/resource/[a-z0-9][a-z0-9._-]{0,127}$'
        AND split_part(source_system_ref, '/', 3) = tenant_id
    ),
    CONSTRAINT ck_gda_entity_source_entity_ref CHECK (
        entity_ref ~ '^gda://[a-z0-9][a-z0-9._-]{0,63}/entity/[a-z0-9][a-z0-9._-]{0,127}$'
        AND split_part(entity_ref, '/', 3) = tenant_id
    ),
    CONSTRAINT ck_gda_entity_source_types CHECK (
        source_object_type ~ '^[a-z][a-z0-9_.-]{2,127}$'
        AND entity_object_type ~ '^[a-z][a-z0-9_.-]{2,127}$'
    ),
    CONSTRAINT ck_gda_entity_source_object_id CHECK (
        NULLIF(btrim(source_object_id), '') IS NOT NULL
        AND char_length(source_object_id) <= 256
    ),
    CONSTRAINT ck_gda_entity_source_class_uri CHECK (
        ontology_class_uri ~ '^https?://[^[:space:]]+$'
        AND char_length(ontology_class_uri) BETWEEN 12 AND 512
    ),
    CONSTRAINT ck_gda_entity_source_owner CHECK (
        owner_subject ~ '^(human|team):[^[:space:]]{1,128}$'
    ),
    CONSTRAINT ck_gda_entity_source_creator CHECK (
        created_by ~ '^(human|workload|agent):[^[:space:]]{1,128}$'
    )
);

CREATE TABLE IF NOT EXISTS gda_control.entity_source_binding_evidence (
    tenant_id TEXT NOT NULL,
    binding_id UUID NOT NULL DEFAULT gen_random_uuid(),
    source_identity_ref TEXT NOT NULL,
    source_version_ref TEXT NOT NULL,
    valid_from TIMESTAMPTZ NOT NULL,
    valid_to TIMESTAMPTZ,
    resolution_method TEXT NOT NULL,
    confidence_basis_points INTEGER NOT NULL,
    evidence JSONB NOT NULL,
    idempotency_key TEXT NOT NULL,
    recorded_by TEXT NOT NULL,
    reason TEXT NOT NULL,
    binding_sha256 CHAR(64) NOT NULL,
    recorded_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (tenant_id, binding_id),
    CONSTRAINT uq_gda_entity_source_binding_idempotency
        UNIQUE (tenant_id, idempotency_key),
    CONSTRAINT fk_gda_entity_source_binding_identity
        FOREIGN KEY (tenant_id, source_identity_ref)
        REFERENCES gda_control.entity_source_identity(tenant_id, source_identity_ref),
    CONSTRAINT ck_gda_entity_source_version_ref CHECK (
        source_version_ref ~ '^gda://[a-z0-9][a-z0-9._-]{0,63}/resource_version/[a-z0-9][a-z0-9._-]{0,127}$'
        AND split_part(source_version_ref, '/', 3) = tenant_id
    ),
    CONSTRAINT ck_gda_entity_source_binding_time
        CHECK (valid_to IS NULL OR valid_to > valid_from),
    CONSTRAINT ck_gda_entity_source_resolution CHECK (
        resolution_method IN (
            'authoritative_identifier', 'authoritative_composite_key',
            'spatial_overlay', 'reviewed_match'
        )
    ),
    CONSTRAINT ck_gda_entity_source_confidence
        CHECK (confidence_basis_points BETWEEN 0 AND 10000),
    CONSTRAINT ck_gda_entity_source_evidence
        CHECK (jsonb_typeof(evidence) = 'object'),
    CONSTRAINT ck_gda_entity_source_idempotency CHECK (
        idempotency_key ~ '^[A-Za-z0-9][A-Za-z0-9._:-]{2,127}$'
    ),
    CONSTRAINT ck_gda_entity_source_recorder CHECK (
        recorded_by ~ '^(human|workload|agent):[^[:space:]]{1,128}$'
    ),
    CONSTRAINT ck_gda_entity_source_reason CHECK (
        NULLIF(btrim(reason), '') IS NOT NULL AND char_length(reason) <= 512
    ),
    CONSTRAINT ck_gda_entity_source_binding_sha256 CHECK (
        binding_sha256 ~ '^[0-9a-f]{64}$'
    )
);

CREATE INDEX IF NOT EXISTS idx_gda_entity_source_binding_identity
    ON gda_control.entity_source_binding_evidence(
        tenant_id, source_identity_ref, valid_from DESC, recorded_at DESC
    );

CREATE TABLE IF NOT EXISTS gda_control.entity_link_type (
    tenant_id TEXT NOT NULL,
    link_type_ref TEXT NOT NULL,
    predicate_uri TEXT NOT NULL,
    link_kind TEXT NOT NULL,
    source_object_type TEXT NOT NULL,
    target_object_type TEXT NOT NULL,
    source_ontology_class_uri TEXT NOT NULL,
    target_ontology_class_uri TEXT NOT NULL,
    ontology_package_id TEXT NOT NULL,
    ontology_package_sha256 CHAR(64) NOT NULL,
    ontology_review_status TEXT NOT NULL,
    directed BOOLEAN NOT NULL,
    allow_self BOOLEAN NOT NULL,
    max_targets_per_source INTEGER,
    max_sources_per_target INTEGER,
    owner_subject TEXT NOT NULL,
    created_by TEXT NOT NULL,
    reason TEXT NOT NULL,
    type_sha256 CHAR(64) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (tenant_id, link_type_ref),
    CONSTRAINT ck_gda_entity_link_type_ref CHECK (
        link_type_ref ~ '^gda://[a-z0-9][a-z0-9._-]{0,63}/link_type/[a-z0-9][a-z0-9._-]{0,127}$'
        AND split_part(link_type_ref, '/', 3) = tenant_id
    ),
    CONSTRAINT ck_gda_entity_link_predicate CHECK (
        predicate_uri ~ '^https?://[^[:space:]]+$'
        AND char_length(predicate_uri) BETWEEN 12 AND 512
    ),
    CONSTRAINT ck_gda_entity_link_kind CHECK (
        link_kind IN ('spatial', 'semantic', 'temporal', 'hierarchical', 'identifier')
    ),
    CONSTRAINT ck_gda_entity_link_object_types CHECK (
        source_object_type ~ '^[a-z][a-z0-9_.-]{2,127}$'
        AND target_object_type ~ '^[a-z][a-z0-9_.-]{2,127}$'
    ),
    CONSTRAINT ck_gda_entity_link_class_uris CHECK (
        source_ontology_class_uri ~ '^https?://[^[:space:]]+$'
        AND target_ontology_class_uri ~ '^https?://[^[:space:]]+$'
        AND char_length(source_ontology_class_uri) BETWEEN 12 AND 512
        AND char_length(target_ontology_class_uri) BETWEEN 12 AND 512
    ),
    CONSTRAINT ck_gda_entity_link_ontology_package CHECK (
        NULLIF(btrim(ontology_package_id), '') IS NOT NULL
        AND char_length(ontology_package_id) BETWEEN 3 AND 256
        AND ontology_package_sha256 ~ '^[0-9a-f]{64}$'
        AND ontology_review_status IN (
            'technical_baseline_unreviewed', 'domain_approved'
        )
    ),
    CONSTRAINT ck_gda_entity_link_cardinality CHECK (
        (max_targets_per_source IS NULL
            OR max_targets_per_source BETWEEN 1 AND 100000)
        AND (max_sources_per_target IS NULL
            OR max_sources_per_target BETWEEN 1 AND 100000)
    ),
    CONSTRAINT ck_gda_entity_link_type_owner CHECK (
        owner_subject ~ '^(human|team):[^[:space:]]{1,128}$'
    ),
    CONSTRAINT ck_gda_entity_link_type_creator CHECK (
        created_by ~ '^(human|workload|agent):[^[:space:]]{1,128}$'
    ),
    CONSTRAINT ck_gda_entity_link_type_reason CHECK (
        NULLIF(btrim(reason), '') IS NOT NULL AND char_length(reason) <= 512
    ),
    CONSTRAINT ck_gda_entity_link_type_sha256 CHECK (
        type_sha256 ~ '^[0-9a-f]{64}$'
    )
);

CREATE TABLE IF NOT EXISTS gda_control.entity_link_identity (
    tenant_id TEXT NOT NULL,
    link_ref TEXT NOT NULL,
    link_type_ref TEXT NOT NULL,
    source_entity_ref TEXT NOT NULL,
    target_entity_ref TEXT NOT NULL,
    owner_subject TEXT NOT NULL,
    created_by TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (tenant_id, link_ref),
    CONSTRAINT uq_gda_entity_link_logical_identity UNIQUE (
        tenant_id, link_type_ref, source_entity_ref, target_entity_ref
    ),
    CONSTRAINT uq_gda_entity_link_assertion_identity UNIQUE (
        tenant_id, link_ref, link_type_ref, source_entity_ref,
        target_entity_ref, owner_subject
    ),
    CONSTRAINT fk_gda_entity_link_identity_type
        FOREIGN KEY (tenant_id, link_type_ref)
        REFERENCES gda_control.entity_link_type(tenant_id, link_type_ref),
    CONSTRAINT fk_gda_entity_link_source
        FOREIGN KEY (tenant_id, source_entity_ref)
        REFERENCES gda_control.temporal_entity_identity(tenant_id, entity_ref),
    CONSTRAINT fk_gda_entity_link_target
        FOREIGN KEY (tenant_id, target_entity_ref)
        REFERENCES gda_control.temporal_entity_identity(tenant_id, entity_ref),
    CONSTRAINT ck_gda_entity_link_ref CHECK (
        link_ref ~ '^gda://[a-z0-9][a-z0-9._-]{0,63}/entity_link/[a-z0-9][a-z0-9._-]{0,127}$'
        AND split_part(link_ref, '/', 3) = tenant_id
    ),
    CONSTRAINT ck_gda_entity_link_endpoint_tenants CHECK (
        split_part(source_entity_ref, '/', 3) = tenant_id
        AND split_part(target_entity_ref, '/', 3) = tenant_id
    ),
    CONSTRAINT ck_gda_entity_link_owner CHECK (
        owner_subject ~ '^(human|team):[^[:space:]]{1,128}$'
    ),
    CONSTRAINT ck_gda_entity_link_creator CHECK (
        created_by ~ '^(human|workload|agent):[^[:space:]]{1,128}$'
    )
);

CREATE INDEX IF NOT EXISTS idx_gda_entity_link_source
    ON gda_control.entity_link_identity(
        tenant_id, link_type_ref, source_entity_ref
    );
CREATE INDEX IF NOT EXISTS idx_gda_entity_link_target
    ON gda_control.entity_link_identity(
        tenant_id, link_type_ref, target_entity_ref
    );

CREATE TABLE IF NOT EXISTS gda_control.entity_link_assertion (
    tenant_id TEXT NOT NULL,
    assertion_id UUID NOT NULL DEFAULT gen_random_uuid(),
    link_ref TEXT NOT NULL,
    link_type_ref TEXT NOT NULL,
    source_entity_ref TEXT NOT NULL,
    target_entity_ref TEXT NOT NULL,
    lifecycle_state TEXT NOT NULL,
    attributes JSONB NOT NULL,
    valid_from TIMESTAMPTZ NOT NULL,
    valid_to TIMESTAMPTZ,
    source_version_refs JSONB NOT NULL,
    mutation_kind TEXT NOT NULL,
    supersedes_assertion_id UUID,
    confidence_basis_points INTEGER NOT NULL,
    evidence JSONB NOT NULL,
    idempotency_key TEXT NOT NULL,
    owner_subject TEXT NOT NULL,
    recorded_by TEXT NOT NULL,
    reason TEXT NOT NULL,
    assertion_sha256 CHAR(64) NOT NULL,
    recorded_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (tenant_id, assertion_id),
    CONSTRAINT uq_gda_entity_link_idempotency
        UNIQUE (tenant_id, idempotency_key),
    CONSTRAINT fk_gda_entity_link_assertion_identity FOREIGN KEY (
        tenant_id, link_ref, link_type_ref, source_entity_ref,
        target_entity_ref, owner_subject
    ) REFERENCES gda_control.entity_link_identity(
        tenant_id, link_ref, link_type_ref, source_entity_ref,
        target_entity_ref, owner_subject
    ),
    CONSTRAINT fk_gda_entity_link_assertion_supersedes
        FOREIGN KEY (tenant_id, supersedes_assertion_id)
        REFERENCES gda_control.entity_link_assertion(tenant_id, assertion_id),
    CONSTRAINT ck_gda_entity_link_lifecycle
        CHECK (lifecycle_state IN ('active', 'retracted')),
    CONSTRAINT ck_gda_entity_link_attributes
        CHECK (jsonb_typeof(attributes) = 'object'),
    CONSTRAINT ck_gda_entity_link_valid_time
        CHECK (valid_to IS NULL OR valid_to > valid_from),
    CONSTRAINT ck_gda_entity_link_sources CHECK (
        jsonb_typeof(source_version_refs) = 'array'
        AND jsonb_array_length(source_version_refs) BETWEEN 1 AND 100
    ),
    CONSTRAINT ck_gda_entity_link_mutation CHECK (
        mutation_kind IN ('initial', 'transition', 'correction')
        AND ((mutation_kind = 'correction') = (supersedes_assertion_id IS NOT NULL))
    ),
    CONSTRAINT ck_gda_entity_link_confidence
        CHECK (confidence_basis_points BETWEEN 0 AND 10000),
    CONSTRAINT ck_gda_entity_link_evidence
        CHECK (jsonb_typeof(evidence) = 'object'),
    CONSTRAINT ck_gda_entity_link_assertion_idempotency CHECK (
        idempotency_key ~ '^[A-Za-z0-9][A-Za-z0-9._:-]{2,127}$'
    ),
    CONSTRAINT ck_gda_entity_link_assertion_recorder CHECK (
        recorded_by ~ '^(human|workload|agent):[^[:space:]]{1,128}$'
    ),
    CONSTRAINT ck_gda_entity_link_assertion_reason CHECK (
        NULLIF(btrim(reason), '') IS NOT NULL AND char_length(reason) <= 512
    ),
    CONSTRAINT ck_gda_entity_link_assertion_sha256 CHECK (
        assertion_sha256 ~ '^[0-9a-f]{64}$'
    )
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_gda_entity_link_base_event
    ON gda_control.entity_link_assertion(tenant_id, link_ref, valid_from)
    WHERE supersedes_assertion_id IS NULL;

CREATE UNIQUE INDEX IF NOT EXISTS uq_gda_entity_link_correction_target
    ON gda_control.entity_link_assertion(tenant_id, supersedes_assertion_id)
    WHERE supersedes_assertion_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_gda_entity_link_valid_time
    ON gda_control.entity_link_assertion(
        tenant_id, link_ref, valid_from DESC, recorded_at DESC
    );

CREATE INDEX IF NOT EXISTS idx_gda_entity_link_known_time
    ON gda_control.entity_link_assertion(
        tenant_id, link_ref, recorded_at DESC
    );

CREATE OR REPLACE FUNCTION gda_control.bind_entity_source_identity(
    p_tenant_id TEXT,
    p_source_identity_ref TEXT,
    p_source_system_ref TEXT,
    p_source_object_type TEXT,
    p_source_object_id TEXT,
    p_entity_ref TEXT,
    p_entity_object_type TEXT,
    p_ontology_class_uri TEXT,
    p_source_version_ref TEXT,
    p_valid_from TIMESTAMPTZ,
    p_valid_to TIMESTAMPTZ,
    p_resolution_method TEXT,
    p_confidence_basis_points INTEGER,
    p_evidence JSONB,
    p_idempotency_key TEXT,
    p_owner_subject TEXT,
    p_recorded_by TEXT,
    p_reason TEXT
)
RETURNS TABLE (
    tenant_id TEXT,
    source_identity_ref TEXT,
    source_system_ref TEXT,
    source_object_type TEXT,
    source_object_id TEXT,
    entity_ref TEXT,
    entity_object_type TEXT,
    ontology_class_uri TEXT,
    source_version_ref TEXT,
    valid_from TIMESTAMPTZ,
    valid_to TIMESTAMPTZ,
    resolution_method TEXT,
    confidence_basis_points INTEGER,
    evidence JSONB,
    idempotency_key TEXT,
    owner_subject TEXT,
    recorded_by TEXT,
    reason TEXT,
    binding_id UUID,
    binding_sha256 CHAR(64),
    recorded_at TIMESTAMPTZ
)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, gda_control, public
SET row_security = on
AS $$
DECLARE
    v_identity gda_control.entity_source_identity%ROWTYPE;
    v_natural_identity gda_control.entity_source_identity%ROWTYPE;
    v_entity gda_control.temporal_entity_identity%ROWTYPE;
    v_binding gda_control.entity_source_binding_evidence%ROWTYPE;
    v_document JSONB;
    v_fingerprint TEXT;
    v_recorded_at TIMESTAMPTZ := clock_timestamp();
BEGIN
    IF gda_control.current_tenant() IS NULL
       OR p_tenant_id IS DISTINCT FROM gda_control.current_tenant() THEN
        RAISE EXCEPTION 'entity source tenant context is missing or mismatched'
            USING ERRCODE = '42501';
    END IF;
    IF p_source_identity_ref !~ '^gda://[a-z0-9][a-z0-9._-]{0,63}/source_identity/[a-z0-9][a-z0-9._-]{0,127}$'
       OR split_part(p_source_identity_ref, '/', 3) <> p_tenant_id
       OR p_source_system_ref !~ '^gda://[a-z0-9][a-z0-9._-]{0,63}/resource/[a-z0-9][a-z0-9._-]{0,127}$'
       OR split_part(p_source_system_ref, '/', 3) <> p_tenant_id
       OR p_source_object_type !~ '^[a-z][a-z0-9_.-]{2,127}$'
       OR NULLIF(btrim(p_source_object_id), '') IS NULL
       OR char_length(p_source_object_id) > 256
       OR p_entity_ref !~ '^gda://[a-z0-9][a-z0-9._-]{0,63}/entity/[a-z0-9][a-z0-9._-]{0,127}$'
       OR split_part(p_entity_ref, '/', 3) <> p_tenant_id
       OR p_entity_object_type !~ '^[a-z][a-z0-9_.-]{2,127}$'
       OR p_ontology_class_uri !~ '^https?://[^[:space:]]+$'
       OR char_length(p_ontology_class_uri) NOT BETWEEN 12 AND 512
       OR p_source_version_ref !~ '^gda://[a-z0-9][a-z0-9._-]{0,63}/resource_version/[a-z0-9][a-z0-9._-]{0,127}$'
       OR split_part(p_source_version_ref, '/', 3) <> p_tenant_id
       OR p_valid_from IS NULL
       OR (p_valid_to IS NOT NULL AND p_valid_to <= p_valid_from)
       OR p_resolution_method NOT IN (
            'authoritative_identifier', 'authoritative_composite_key',
            'spatial_overlay', 'reviewed_match'
       )
       OR p_confidence_basis_points NOT BETWEEN 0 AND 10000
       OR jsonb_typeof(p_evidence) <> 'object'
       OR octet_length(p_evidence::text) > 65536
       OR p_idempotency_key !~ '^[A-Za-z0-9][A-Za-z0-9._:-]{2,127}$'
       OR p_owner_subject !~ '^(human|team):[^[:space:]]{1,128}$'
       OR p_recorded_by !~ '^(human|workload|agent):[^[:space:]]{1,128}$'
       OR NULLIF(btrim(p_reason), '') IS NULL
       OR char_length(p_reason) > 512 THEN
        RAISE EXCEPTION 'entity source identity or evidence is invalid'
            USING ERRCODE = '22023';
    END IF;

    v_document := jsonb_build_object(
        'schema_id', 'gda.entity-source-binding.v1',
        'tenant_id', p_tenant_id,
        'source_identity_ref', p_source_identity_ref,
        'source_system_ref', p_source_system_ref,
        'source_object_type', p_source_object_type,
        'source_object_id', p_source_object_id,
        'entity_ref', p_entity_ref,
        'entity_object_type', p_entity_object_type,
        'ontology_class_uri', p_ontology_class_uri,
        'source_version_ref', p_source_version_ref,
        'valid_from', p_valid_from,
        'valid_to', p_valid_to,
        'resolution_method', p_resolution_method,
        'confidence_basis_points', p_confidence_basis_points,
        'evidence', p_evidence,
        'idempotency_key', p_idempotency_key,
        'owner_subject', p_owner_subject,
        'recorded_by', p_recorded_by,
        'reason', p_reason
    );
    v_fingerprint := encode(
        public.digest(convert_to(v_document::text, 'UTF8'), 'sha256'),
        'hex'
    );

    PERFORM pg_advisory_xact_lock(hashtextextended(
        'entity-source-idempotency|' || p_tenant_id || '|' || p_idempotency_key,
        0
    ));
    PERFORM pg_advisory_xact_lock(hashtextextended(
        'entity-source-natural|' || p_tenant_id || '|' || p_source_system_ref
        || '|' || p_source_object_type || '|' || p_source_object_id,
        0
    ));

    SELECT binding.* INTO v_binding
    FROM gda_control.entity_source_binding_evidence AS binding
    WHERE binding.tenant_id = p_tenant_id
      AND binding.idempotency_key = p_idempotency_key;
    IF FOUND THEN
        IF v_binding.binding_sha256 <> v_fingerprint THEN
            RAISE EXCEPTION 'entity source idempotency key has different evidence'
                USING ERRCODE = '40001';
        END IF;
        RETURN QUERY
        SELECT identity.tenant_id, identity.source_identity_ref,
               identity.source_system_ref, identity.source_object_type,
               identity.source_object_id, identity.entity_ref,
               identity.entity_object_type, identity.ontology_class_uri,
               binding.source_version_ref, binding.valid_from, binding.valid_to,
               binding.resolution_method, binding.confidence_basis_points,
               binding.evidence, binding.idempotency_key, identity.owner_subject,
               binding.recorded_by, binding.reason, binding.binding_id,
               binding.binding_sha256, binding.recorded_at
        FROM gda_control.entity_source_identity AS identity
        JOIN gda_control.entity_source_binding_evidence AS binding
          ON binding.tenant_id = identity.tenant_id
         AND binding.source_identity_ref = identity.source_identity_ref
        WHERE binding.tenant_id = p_tenant_id
          AND binding.binding_id = v_binding.binding_id;
        RETURN;
    END IF;

    SELECT entity.* INTO v_entity
    FROM gda_control.temporal_entity_identity AS entity
    WHERE entity.tenant_id = p_tenant_id
      AND entity.entity_ref = p_entity_ref;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'source binding target entity was not found'
            USING ERRCODE = 'P0002';
    END IF;
    IF v_entity.object_type <> p_entity_object_type
       OR v_entity.owner_subject <> p_owner_subject THEN
        RAISE EXCEPTION 'source binding entity type or owner is inconsistent'
            USING ERRCODE = '23514';
    END IF;

    SELECT identity.* INTO v_identity
    FROM gda_control.entity_source_identity AS identity
    WHERE identity.tenant_id = p_tenant_id
      AND identity.source_identity_ref = p_source_identity_ref;

    SELECT identity.* INTO v_natural_identity
    FROM gda_control.entity_source_identity AS identity
    WHERE identity.tenant_id = p_tenant_id
      AND identity.source_system_ref = p_source_system_ref
      AND identity.source_object_type = p_source_object_type
      AND identity.source_object_id = p_source_object_id;

    IF v_identity.source_identity_ref IS NOT NULL
       AND (v_identity.source_system_ref <> p_source_system_ref
            OR v_identity.source_object_type <> p_source_object_type
            OR v_identity.source_object_id <> p_source_object_id
            OR v_identity.entity_ref <> p_entity_ref
            OR v_identity.entity_object_type <> p_entity_object_type
            OR v_identity.ontology_class_uri <> p_ontology_class_uri
            OR v_identity.owner_subject <> p_owner_subject) THEN
        RAISE EXCEPTION 'source identity is already bound to different semantics'
            USING ERRCODE = '40001';
    END IF;
    IF v_natural_identity.source_identity_ref IS NOT NULL
       AND v_natural_identity.source_identity_ref <> p_source_identity_ref THEN
        RAISE EXCEPTION 'source object already maps to another source identity'
            USING ERRCODE = '40001';
    END IF;

    IF v_identity.source_identity_ref IS NULL THEN
        INSERT INTO gda_control.entity_source_identity (
            tenant_id, source_identity_ref, source_system_ref,
            source_object_type, source_object_id, entity_ref,
            entity_object_type, ontology_class_uri, owner_subject,
            created_by, created_at
        ) VALUES (
            p_tenant_id, p_source_identity_ref, p_source_system_ref,
            p_source_object_type, p_source_object_id, p_entity_ref,
            p_entity_object_type, p_ontology_class_uri, p_owner_subject,
            p_recorded_by, v_recorded_at
        )
        RETURNING * INTO v_identity;
    END IF;

    INSERT INTO gda_control.entity_source_binding_evidence (
        tenant_id, source_identity_ref, source_version_ref, valid_from,
        valid_to, resolution_method, confidence_basis_points, evidence,
        idempotency_key, recorded_by, reason, binding_sha256, recorded_at
    ) VALUES (
        p_tenant_id, p_source_identity_ref, p_source_version_ref, p_valid_from,
        p_valid_to, p_resolution_method, p_confidence_basis_points, p_evidence,
        p_idempotency_key, p_recorded_by, p_reason, v_fingerprint, v_recorded_at
    )
    RETURNING * INTO v_binding;

    RETURN QUERY
    SELECT v_identity.tenant_id, v_identity.source_identity_ref,
           v_identity.source_system_ref, v_identity.source_object_type,
           v_identity.source_object_id, v_identity.entity_ref,
           v_identity.entity_object_type, v_identity.ontology_class_uri,
           v_binding.source_version_ref, v_binding.valid_from, v_binding.valid_to,
           v_binding.resolution_method, v_binding.confidence_basis_points,
           v_binding.evidence, v_binding.idempotency_key, v_identity.owner_subject,
           v_binding.recorded_by, v_binding.reason, v_binding.binding_id,
           v_binding.binding_sha256, v_binding.recorded_at;
END;
$$;

CREATE OR REPLACE FUNCTION gda_control.register_entity_link_type(
    p_tenant_id TEXT,
    p_link_type_ref TEXT,
    p_predicate_uri TEXT,
    p_link_kind TEXT,
    p_source_object_type TEXT,
    p_target_object_type TEXT,
    p_source_ontology_class_uri TEXT,
    p_target_ontology_class_uri TEXT,
    p_ontology_package_id TEXT,
    p_ontology_package_sha256 TEXT,
    p_ontology_review_status TEXT,
    p_directed BOOLEAN,
    p_allow_self BOOLEAN,
    p_max_targets_per_source INTEGER,
    p_max_sources_per_target INTEGER,
    p_owner_subject TEXT,
    p_created_by TEXT,
    p_reason TEXT
)
RETURNS gda_control.entity_link_type
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, gda_control, public
SET row_security = on
AS $$
DECLARE
    v_existing gda_control.entity_link_type%ROWTYPE;
    v_document JSONB;
    v_fingerprint TEXT;
BEGIN
    IF gda_control.current_tenant() IS NULL
       OR p_tenant_id IS DISTINCT FROM gda_control.current_tenant() THEN
        RAISE EXCEPTION 'entity link type tenant context is missing or mismatched'
            USING ERRCODE = '42501';
    END IF;
    IF p_link_type_ref !~ '^gda://[a-z0-9][a-z0-9._-]{0,63}/link_type/[a-z0-9][a-z0-9._-]{0,127}$'
       OR split_part(p_link_type_ref, '/', 3) <> p_tenant_id
       OR p_predicate_uri !~ '^https?://[^[:space:]]+$'
       OR char_length(p_predicate_uri) NOT BETWEEN 12 AND 512
       OR p_link_kind NOT IN (
            'spatial', 'semantic', 'temporal', 'hierarchical', 'identifier'
       )
       OR p_source_object_type !~ '^[a-z][a-z0-9_.-]{2,127}$'
       OR p_target_object_type !~ '^[a-z][a-z0-9_.-]{2,127}$'
       OR p_source_ontology_class_uri !~ '^https?://[^[:space:]]+$'
       OR p_target_ontology_class_uri !~ '^https?://[^[:space:]]+$'
       OR char_length(p_source_ontology_class_uri) NOT BETWEEN 12 AND 512
       OR char_length(p_target_ontology_class_uri) NOT BETWEEN 12 AND 512
       OR NULLIF(btrim(p_ontology_package_id), '') IS NULL
       OR char_length(p_ontology_package_id) NOT BETWEEN 3 AND 256
       OR p_ontology_package_sha256 !~ '^[0-9a-f]{64}$'
       OR p_ontology_review_status NOT IN (
            'technical_baseline_unreviewed', 'domain_approved'
       )
       OR p_directed IS NULL
       OR p_allow_self IS NULL
       OR (p_max_targets_per_source IS NOT NULL
            AND p_max_targets_per_source NOT BETWEEN 1 AND 100000)
       OR (p_max_sources_per_target IS NOT NULL
            AND p_max_sources_per_target NOT BETWEEN 1 AND 100000)
       OR p_owner_subject !~ '^(human|team):[^[:space:]]{1,128}$'
       OR p_created_by !~ '^(human|workload|agent):[^[:space:]]{1,128}$'
       OR NULLIF(btrim(p_reason), '') IS NULL
       OR char_length(p_reason) > 512 THEN
        RAISE EXCEPTION 'entity link type is invalid'
            USING ERRCODE = '22023';
    END IF;

    v_document := jsonb_build_object(
        'schema_id', 'gda.instance-link-type.v1',
        'tenant_id', p_tenant_id,
        'link_type_ref', p_link_type_ref,
        'predicate_uri', p_predicate_uri,
        'link_kind', p_link_kind,
        'source_object_type', p_source_object_type,
        'target_object_type', p_target_object_type,
        'source_ontology_class_uri', p_source_ontology_class_uri,
        'target_ontology_class_uri', p_target_ontology_class_uri,
        'ontology_package_id', p_ontology_package_id,
        'ontology_package_sha256', p_ontology_package_sha256,
        'ontology_review_status', p_ontology_review_status,
        'directed', p_directed,
        'allow_self', p_allow_self,
        'max_targets_per_source', p_max_targets_per_source,
        'max_sources_per_target', p_max_sources_per_target,
        'owner_subject', p_owner_subject,
        'created_by', p_created_by,
        'reason', p_reason
    );
    v_fingerprint := encode(
        public.digest(convert_to(v_document::text, 'UTF8'), 'sha256'),
        'hex'
    );

    PERFORM pg_advisory_xact_lock(hashtextextended(
        'entity-link-type|' || p_tenant_id || '|' || p_link_type_ref,
        0
    ));
    SELECT link_type.* INTO v_existing
    FROM gda_control.entity_link_type AS link_type
    WHERE link_type.tenant_id = p_tenant_id
      AND link_type.link_type_ref = p_link_type_ref;
    IF FOUND THEN
        IF v_existing.type_sha256 <> v_fingerprint THEN
            RAISE EXCEPTION 'entity link type identity has different semantics'
                USING ERRCODE = '40001';
        END IF;
        RETURN v_existing;
    END IF;

    INSERT INTO gda_control.entity_link_type (
        tenant_id, link_type_ref, predicate_uri, link_kind,
        source_object_type, target_object_type,
        source_ontology_class_uri, target_ontology_class_uri,
        ontology_package_id, ontology_package_sha256,
        ontology_review_status, directed, allow_self,
        max_targets_per_source, max_sources_per_target,
        owner_subject, created_by, reason, type_sha256, created_at
    ) VALUES (
        p_tenant_id, p_link_type_ref, p_predicate_uri, p_link_kind,
        p_source_object_type, p_target_object_type,
        p_source_ontology_class_uri, p_target_ontology_class_uri,
        p_ontology_package_id, p_ontology_package_sha256,
        p_ontology_review_status, p_directed, p_allow_self,
        p_max_targets_per_source, p_max_sources_per_target,
        p_owner_subject, p_created_by, p_reason, v_fingerprint, clock_timestamp()
    )
    RETURNING * INTO v_existing;
    RETURN v_existing;
END;
$$;

CREATE OR REPLACE FUNCTION gda_control.entity_link_transition_allowed(
    p_from TEXT,
    p_to TEXT
)
RETURNS BOOLEAN
LANGUAGE sql
IMMUTABLE
STRICT
SET search_path = pg_catalog
AS $$
    SELECT (p_from = 'active' AND p_to = 'retracted')
        OR (p_from = 'retracted' AND p_to = 'active')
$$;

CREATE OR REPLACE FUNCTION gda_control.record_entity_link_assertion(
    p_tenant_id TEXT,
    p_link_ref TEXT,
    p_link_type_ref TEXT,
    p_source_entity_ref TEXT,
    p_target_entity_ref TEXT,
    p_lifecycle_state TEXT,
    p_attributes JSONB,
    p_valid_from TIMESTAMPTZ,
    p_valid_to TIMESTAMPTZ,
    p_source_version_refs JSONB,
    p_mutation_kind TEXT,
    p_supersedes_assertion_id UUID,
    p_confidence_basis_points INTEGER,
    p_evidence JSONB,
    p_idempotency_key TEXT,
    p_owner_subject TEXT,
    p_recorded_by TEXT,
    p_reason TEXT
)
RETURNS gda_control.entity_link_assertion
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, gda_control, public
SET row_security = on
AS $$
DECLARE
    v_type gda_control.entity_link_type%ROWTYPE;
    v_identity gda_control.entity_link_identity%ROWTYPE;
    v_source gda_control.temporal_entity_identity%ROWTYPE;
    v_target_entity gda_control.temporal_entity_identity%ROWTYPE;
    v_existing gda_control.entity_link_assertion%ROWTYPE;
    v_target_assertion gda_control.entity_link_assertion%ROWTYPE;
    v_previous gda_control.entity_link_assertion%ROWTYPE;
    v_next gda_control.entity_link_assertion%ROWTYPE;
    v_document JSONB;
    v_fingerprint TEXT;
    v_active_count INTEGER;
    v_recorded_at TIMESTAMPTZ := clock_timestamp();
BEGIN
    IF gda_control.current_tenant() IS NULL
       OR p_tenant_id IS DISTINCT FROM gda_control.current_tenant() THEN
        RAISE EXCEPTION 'entity link tenant context is missing or mismatched'
            USING ERRCODE = '42501';
    END IF;
    IF p_link_ref !~ '^gda://[a-z0-9][a-z0-9._-]{0,63}/entity_link/[a-z0-9][a-z0-9._-]{0,127}$'
       OR split_part(p_link_ref, '/', 3) <> p_tenant_id
       OR p_link_type_ref !~ '^gda://[a-z0-9][a-z0-9._-]{0,63}/link_type/[a-z0-9][a-z0-9._-]{0,127}$'
       OR split_part(p_link_type_ref, '/', 3) <> p_tenant_id
       OR p_source_entity_ref !~ '^gda://[a-z0-9][a-z0-9._-]{0,63}/entity/[a-z0-9][a-z0-9._-]{0,127}$'
       OR split_part(p_source_entity_ref, '/', 3) <> p_tenant_id
       OR p_target_entity_ref !~ '^gda://[a-z0-9][a-z0-9._-]{0,63}/entity/[a-z0-9][a-z0-9._-]{0,127}$'
       OR split_part(p_target_entity_ref, '/', 3) <> p_tenant_id
       OR p_lifecycle_state NOT IN ('active', 'retracted')
       OR jsonb_typeof(p_attributes) <> 'object'
       OR octet_length(p_attributes::text) > 65536
       OR p_valid_from IS NULL
       OR (p_valid_to IS NOT NULL AND p_valid_to <= p_valid_from)
       OR p_mutation_kind NOT IN ('initial', 'transition', 'correction')
       OR ((p_mutation_kind = 'correction')
            <> (p_supersedes_assertion_id IS NOT NULL))
       OR p_confidence_basis_points NOT BETWEEN 0 AND 10000
       OR jsonb_typeof(p_evidence) <> 'object'
       OR octet_length(p_evidence::text) > 65536
       OR p_idempotency_key !~ '^[A-Za-z0-9][A-Za-z0-9._:-]{2,127}$'
       OR p_owner_subject !~ '^(human|team):[^[:space:]]{1,128}$'
       OR p_recorded_by !~ '^(human|workload|agent):[^[:space:]]{1,128}$'
       OR NULLIF(btrim(p_reason), '') IS NULL
       OR char_length(p_reason) > 512 THEN
        RAISE EXCEPTION 'entity link identity, time or evidence is invalid'
            USING ERRCODE = '22023';
    END IF;
    IF jsonb_typeof(p_source_version_refs) <> 'array'
       OR jsonb_array_length(p_source_version_refs) NOT BETWEEN 1 AND 100
       OR EXISTS (
            SELECT 1
            FROM jsonb_array_elements(p_source_version_refs) AS item(value)
            WHERE jsonb_typeof(item.value) <> 'string'
       )
       OR EXISTS (
            SELECT 1
            FROM jsonb_array_elements_text(p_source_version_refs) AS item(value)
            WHERE item.value !~ '^gda://[a-z0-9][a-z0-9._-]{0,63}/resource_version/[a-z0-9][a-z0-9._-]{0,127}$'
               OR split_part(item.value, '/', 3) <> p_tenant_id
       )
       OR (
            SELECT COUNT(*) <> COUNT(DISTINCT item.value)
                OR array_agg(item.value) IS DISTINCT FROM
                    array_agg(item.value ORDER BY item.value)
            FROM jsonb_array_elements_text(p_source_version_refs) AS item(value)
       ) THEN
        RAISE EXCEPTION 'link source versions must be sorted unique tenant URNs'
            USING ERRCODE = '22023';
    END IF;

    v_document := jsonb_build_object(
        'schema_id', 'gda.instance-link-assertion.v1',
        'tenant_id', p_tenant_id,
        'link_ref', p_link_ref,
        'link_type_ref', p_link_type_ref,
        'source_entity_ref', p_source_entity_ref,
        'target_entity_ref', p_target_entity_ref,
        'lifecycle_state', p_lifecycle_state,
        'attributes', p_attributes,
        'valid_from', p_valid_from,
        'valid_to', p_valid_to,
        'source_version_refs', p_source_version_refs,
        'mutation_kind', p_mutation_kind,
        'supersedes_assertion_id', p_supersedes_assertion_id,
        'confidence_basis_points', p_confidence_basis_points,
        'evidence', p_evidence,
        'idempotency_key', p_idempotency_key,
        'owner_subject', p_owner_subject,
        'recorded_by', p_recorded_by,
        'reason', p_reason
    );
    v_fingerprint := encode(
        public.digest(convert_to(v_document::text, 'UTF8'), 'sha256'),
        'hex'
    );

    PERFORM pg_advisory_xact_lock(hashtextextended(
        'entity-link-idempotency|' || p_tenant_id || '|' || p_idempotency_key,
        0
    ));
    PERFORM pg_advisory_xact_lock(hashtextextended(
        'entity-link|' || p_tenant_id || '|' || p_link_ref,
        0
    ));
    PERFORM pg_advisory_xact_lock(hashtextextended(
        'entity-link-source|' || p_tenant_id || '|' || p_link_type_ref
        || '|' || p_source_entity_ref,
        0
    ));
    PERFORM pg_advisory_xact_lock(hashtextextended(
        'entity-link-target|' || p_tenant_id || '|' || p_link_type_ref
        || '|' || p_target_entity_ref,
        0
    ));

    SELECT assertion.* INTO v_existing
    FROM gda_control.entity_link_assertion AS assertion
    WHERE assertion.tenant_id = p_tenant_id
      AND assertion.idempotency_key = p_idempotency_key;
    IF FOUND THEN
        IF v_existing.assertion_sha256 <> v_fingerprint THEN
            RAISE EXCEPTION 'entity link idempotency key has different evidence'
                USING ERRCODE = '40001';
        END IF;
        RETURN v_existing;
    END IF;

    SELECT link_type.* INTO v_type
    FROM gda_control.entity_link_type AS link_type
    WHERE link_type.tenant_id = p_tenant_id
      AND link_type.link_type_ref = p_link_type_ref;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'entity link type was not found'
            USING ERRCODE = 'P0002';
    END IF;

    SELECT entity.* INTO v_source
    FROM gda_control.temporal_entity_identity AS entity
    WHERE entity.tenant_id = p_tenant_id
      AND entity.entity_ref = p_source_entity_ref;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'entity link source endpoint was not found'
            USING ERRCODE = 'P0002';
    END IF;
    SELECT entity.* INTO v_target_entity
    FROM gda_control.temporal_entity_identity AS entity
    WHERE entity.tenant_id = p_tenant_id
      AND entity.entity_ref = p_target_entity_ref;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'entity link target endpoint was not found'
            USING ERRCODE = 'P0002';
    END IF;
    IF v_source.object_type <> v_type.source_object_type
       OR v_target_entity.object_type <> v_type.target_object_type THEN
        RAISE EXCEPTION 'entity link endpoint type does not match link type'
            USING ERRCODE = '23514';
    END IF;
    IF p_source_entity_ref = p_target_entity_ref AND NOT v_type.allow_self THEN
        RAISE EXCEPTION 'entity link type does not allow self links'
            USING ERRCODE = '23514';
    END IF;

    SELECT identity.* INTO v_identity
    FROM gda_control.entity_link_identity AS identity
    WHERE identity.tenant_id = p_tenant_id
      AND identity.link_ref = p_link_ref;

    IF p_mutation_kind = 'initial' THEN
        IF p_lifecycle_state <> 'active' THEN
            RAISE EXCEPTION 'initial entity link lifecycle must be active'
                USING ERRCODE = '23514';
        END IF;
        IF v_identity.link_ref IS NOT NULL OR EXISTS (
            SELECT 1
            FROM gda_control.entity_link_assertion AS assertion
            WHERE assertion.tenant_id = p_tenant_id
              AND assertion.link_ref = p_link_ref
        ) THEN
            RAISE EXCEPTION 'initial assertion requires a new link identity'
                USING ERRCODE = '40001';
        END IF;
        INSERT INTO gda_control.entity_link_identity (
            tenant_id, link_ref, link_type_ref, source_entity_ref,
            target_entity_ref, owner_subject, created_by, created_at
        ) VALUES (
            p_tenant_id, p_link_ref, p_link_type_ref, p_source_entity_ref,
            p_target_entity_ref, p_owner_subject, p_recorded_by, v_recorded_at
        )
        RETURNING * INTO v_identity;
    ELSE
        IF v_identity.link_ref IS NULL THEN
            RAISE EXCEPTION 'entity link identity was not found'
                USING ERRCODE = 'P0002';
        END IF;
        IF v_identity.link_type_ref <> p_link_type_ref
           OR v_identity.source_entity_ref <> p_source_entity_ref
           OR v_identity.target_entity_ref <> p_target_entity_ref
           OR v_identity.owner_subject <> p_owner_subject THEN
            RAISE EXCEPTION 'stable entity link identity or owner cannot change'
                USING ERRCODE = '23514';
        END IF;
    END IF;

    IF p_mutation_kind = 'correction' THEN
        SELECT assertion.* INTO v_target_assertion
        FROM gda_control.entity_link_assertion AS assertion
        WHERE assertion.tenant_id = p_tenant_id
          AND assertion.assertion_id = p_supersedes_assertion_id
        FOR UPDATE;
        IF NOT FOUND
           OR v_target_assertion.link_ref <> p_link_ref
           OR v_target_assertion.link_type_ref <> p_link_type_ref
           OR v_target_assertion.source_entity_ref <> p_source_entity_ref
           OR v_target_assertion.target_entity_ref <> p_target_entity_ref THEN
            RAISE EXCEPTION 'link correction target was not found for this identity'
                USING ERRCODE = 'P0002';
        END IF;
        IF v_target_assertion.valid_from <> p_valid_from
           OR v_target_assertion.valid_to IS DISTINCT FROM p_valid_to
           OR v_target_assertion.lifecycle_state <> p_lifecycle_state THEN
            RAISE EXCEPTION 'link correction cannot change effective time or lifecycle'
                USING ERRCODE = '23514';
        END IF;
        IF EXISTS (
            SELECT 1
            FROM gda_control.entity_link_assertion AS child
            WHERE child.tenant_id = p_tenant_id
              AND child.supersedes_assertion_id = v_target_assertion.assertion_id
        ) THEN
            RAISE EXCEPTION 'link correction target has already been superseded'
                USING ERRCODE = '40001';
        END IF;
        v_recorded_at := GREATEST(
            v_recorded_at,
            v_target_assertion.recorded_at + INTERVAL '1 microsecond'
        );
    ELSIF p_mutation_kind = 'transition' THEN
        SELECT candidate.* INTO v_previous
        FROM gda_control.entity_link_assertion AS candidate
        WHERE candidate.tenant_id = p_tenant_id
          AND candidate.link_ref = p_link_ref
          AND candidate.valid_from < p_valid_from
          AND NOT EXISTS (
              SELECT 1
              FROM gda_control.entity_link_assertion AS child
              WHERE child.tenant_id = candidate.tenant_id
                AND child.supersedes_assertion_id = candidate.assertion_id
          )
        ORDER BY candidate.valid_from DESC, candidate.recorded_at DESC
        LIMIT 1;
        IF NOT FOUND THEN
            RAISE EXCEPTION 'link transition requires a prior lifecycle event'
                USING ERRCODE = '23514';
        END IF;
        IF NOT gda_control.entity_link_transition_allowed(
            v_previous.lifecycle_state, p_lifecycle_state
        ) THEN
            RAISE EXCEPTION 'entity link lifecycle transition is not allowed'
                USING ERRCODE = '23514';
        END IF;
        SELECT candidate.* INTO v_next
        FROM gda_control.entity_link_assertion AS candidate
        WHERE candidate.tenant_id = p_tenant_id
          AND candidate.link_ref = p_link_ref
          AND candidate.valid_from > p_valid_from
          AND NOT EXISTS (
              SELECT 1
              FROM gda_control.entity_link_assertion AS child
              WHERE child.tenant_id = candidate.tenant_id
                AND child.supersedes_assertion_id = candidate.assertion_id
          )
        ORDER BY candidate.valid_from ASC, candidate.recorded_at DESC
        LIMIT 1;
        IF FOUND AND NOT gda_control.entity_link_transition_allowed(
            p_lifecycle_state, v_next.lifecycle_state
        ) THEN
            RAISE EXCEPTION 'late link transition invalidates its successor'
                USING ERRCODE = '23514';
        END IF;
    END IF;

    IF p_lifecycle_state = 'active' AND p_mutation_kind <> 'correction' THEN
        IF v_type.max_targets_per_source IS NOT NULL THEN
            SELECT COUNT(*) INTO v_active_count
            FROM gda_control.entity_link_identity AS identity
            JOIN LATERAL (
                SELECT assertion.lifecycle_state, assertion.valid_to
                FROM gda_control.entity_link_assertion AS assertion
                WHERE assertion.tenant_id = identity.tenant_id
                  AND assertion.link_ref = identity.link_ref
                  AND assertion.valid_from <= p_valid_from
                  AND NOT EXISTS (
                      SELECT 1
                      FROM gda_control.entity_link_assertion AS child
                      WHERE child.tenant_id = assertion.tenant_id
                        AND child.supersedes_assertion_id = assertion.assertion_id
                  )
                ORDER BY assertion.valid_from DESC, assertion.recorded_at DESC
                LIMIT 1
            ) AS state ON TRUE
            WHERE identity.tenant_id = p_tenant_id
              AND identity.link_type_ref = p_link_type_ref
              AND identity.source_entity_ref = p_source_entity_ref
              AND identity.link_ref <> p_link_ref
              AND state.lifecycle_state = 'active'
              AND (state.valid_to IS NULL OR p_valid_from < state.valid_to);
            IF v_active_count >= v_type.max_targets_per_source THEN
                RAISE EXCEPTION 'maximum targets per source would be exceeded'
                    USING ERRCODE = '23514';
            END IF;
        END IF;
        IF v_type.max_sources_per_target IS NOT NULL THEN
            SELECT COUNT(*) INTO v_active_count
            FROM gda_control.entity_link_identity AS identity
            JOIN LATERAL (
                SELECT assertion.lifecycle_state, assertion.valid_to
                FROM gda_control.entity_link_assertion AS assertion
                WHERE assertion.tenant_id = identity.tenant_id
                  AND assertion.link_ref = identity.link_ref
                  AND assertion.valid_from <= p_valid_from
                  AND NOT EXISTS (
                      SELECT 1
                      FROM gda_control.entity_link_assertion AS child
                      WHERE child.tenant_id = assertion.tenant_id
                        AND child.supersedes_assertion_id = assertion.assertion_id
                  )
                ORDER BY assertion.valid_from DESC, assertion.recorded_at DESC
                LIMIT 1
            ) AS state ON TRUE
            WHERE identity.tenant_id = p_tenant_id
              AND identity.link_type_ref = p_link_type_ref
              AND identity.target_entity_ref = p_target_entity_ref
              AND identity.link_ref <> p_link_ref
              AND state.lifecycle_state = 'active'
              AND (state.valid_to IS NULL OR p_valid_from < state.valid_to);
            IF v_active_count >= v_type.max_sources_per_target THEN
                RAISE EXCEPTION 'maximum sources per target would be exceeded'
                    USING ERRCODE = '23514';
            END IF;
        END IF;
    END IF;

    INSERT INTO gda_control.entity_link_assertion (
        tenant_id, link_ref, link_type_ref, source_entity_ref,
        target_entity_ref, lifecycle_state, attributes, valid_from,
        valid_to, source_version_refs, mutation_kind,
        supersedes_assertion_id, confidence_basis_points, evidence,
        idempotency_key, owner_subject, recorded_by, reason,
        assertion_sha256, recorded_at
    ) VALUES (
        p_tenant_id, p_link_ref, p_link_type_ref, p_source_entity_ref,
        p_target_entity_ref, p_lifecycle_state, p_attributes, p_valid_from,
        p_valid_to, p_source_version_refs, p_mutation_kind,
        p_supersedes_assertion_id, p_confidence_basis_points, p_evidence,
        p_idempotency_key, p_owner_subject, p_recorded_by, p_reason,
        v_fingerprint, v_recorded_at
    )
    RETURNING * INTO v_existing;
    RETURN v_existing;
END;
$$;

DO $$
DECLARE
    relation_name TEXT;
BEGIN
    FOREACH relation_name IN ARRAY ARRAY[
        'entity_source_identity',
        'entity_source_binding_evidence',
        'entity_link_type',
        'entity_link_identity',
        'entity_link_assertion'
    ]
    LOOP
        EXECUTE format(
            'ALTER TABLE gda_control.%I ENABLE ROW LEVEL SECURITY',
            relation_name
        );
        EXECUTE format(
            'ALTER TABLE gda_control.%I FORCE ROW LEVEL SECURITY',
            relation_name
        );
        EXECUTE format(
            'DROP POLICY IF EXISTS tenant_isolation ON gda_control.%I',
            relation_name
        );
        EXECUTE format(
            'CREATE POLICY tenant_isolation ON gda_control.%I '
            'USING (tenant_id = gda_control.current_tenant()) '
            'WITH CHECK (tenant_id = gda_control.current_tenant())',
            relation_name
        );
        EXECUTE format(
            'DROP TRIGGER IF EXISTS trg_gda_%s_immutable ON gda_control.%I',
            relation_name,
            relation_name
        );
        EXECUTE format(
            'CREATE TRIGGER trg_gda_%s_immutable BEFORE UPDATE OR DELETE ON '
            'gda_control.%I FOR EACH ROW EXECUTE FUNCTION '
            'gda_control.reject_immutable_mutation()',
            relation_name,
            relation_name
        );
    END LOOP;
END;
$$;

REVOKE ALL ON TABLE gda_control.entity_source_identity
    FROM PUBLIC, gda_control_gateway;
REVOKE ALL ON TABLE gda_control.entity_source_binding_evidence
    FROM PUBLIC, gda_control_gateway;
REVOKE ALL ON TABLE gda_control.entity_link_type
    FROM PUBLIC, gda_control_gateway;
REVOKE ALL ON TABLE gda_control.entity_link_identity
    FROM PUBLIC, gda_control_gateway;
REVOKE ALL ON TABLE gda_control.entity_link_assertion
    FROM PUBLIC, gda_control_gateway;

REVOKE ALL ON FUNCTION gda_control.bind_entity_source_identity(
    TEXT, TEXT, TEXT, TEXT, TEXT, TEXT, TEXT, TEXT, TEXT,
    TIMESTAMPTZ, TIMESTAMPTZ, TEXT, INTEGER, JSONB, TEXT, TEXT, TEXT, TEXT
) FROM PUBLIC;
REVOKE ALL ON FUNCTION gda_control.register_entity_link_type(
    TEXT, TEXT, TEXT, TEXT, TEXT, TEXT, TEXT, TEXT, TEXT, TEXT,
    TEXT, BOOLEAN, BOOLEAN, INTEGER, INTEGER, TEXT, TEXT, TEXT
) FROM PUBLIC;
REVOKE ALL ON FUNCTION gda_control.entity_link_transition_allowed(TEXT, TEXT)
    FROM PUBLIC;
REVOKE ALL ON FUNCTION gda_control.record_entity_link_assertion(
    TEXT, TEXT, TEXT, TEXT, TEXT, TEXT, JSONB, TIMESTAMPTZ, TIMESTAMPTZ,
    JSONB, TEXT, UUID, INTEGER, JSONB, TEXT, TEXT, TEXT, TEXT
) FROM PUBLIC;

GRANT SELECT ON TABLE gda_control.entity_source_identity
    TO gda_control_gateway;
GRANT SELECT ON TABLE gda_control.entity_source_binding_evidence
    TO gda_control_gateway;
GRANT SELECT ON TABLE gda_control.entity_link_type
    TO gda_control_gateway;
GRANT SELECT ON TABLE gda_control.entity_link_identity
    TO gda_control_gateway;
GRANT SELECT ON TABLE gda_control.entity_link_assertion
    TO gda_control_gateway;

GRANT EXECUTE ON FUNCTION gda_control.bind_entity_source_identity(
    TEXT, TEXT, TEXT, TEXT, TEXT, TEXT, TEXT, TEXT, TEXT,
    TIMESTAMPTZ, TIMESTAMPTZ, TEXT, INTEGER, JSONB, TEXT, TEXT, TEXT, TEXT
) TO gda_control_gateway;
GRANT EXECUTE ON FUNCTION gda_control.register_entity_link_type(
    TEXT, TEXT, TEXT, TEXT, TEXT, TEXT, TEXT, TEXT, TEXT, TEXT,
    TEXT, BOOLEAN, BOOLEAN, INTEGER, INTEGER, TEXT, TEXT, TEXT
) TO gda_control_gateway;
GRANT EXECUTE ON FUNCTION gda_control.record_entity_link_assertion(
    TEXT, TEXT, TEXT, TEXT, TEXT, TEXT, JSONB, TIMESTAMPTZ, TIMESTAMPTZ,
    JSONB, TEXT, UUID, INTEGER, JSONB, TEXT, TEXT, TEXT, TEXT
) TO gda_control_gateway;
