-- 164: Append-only entity merge, split, replacement, and Link propagation.

CREATE EXTENSION IF NOT EXISTS pgcrypto WITH SCHEMA public;

CREATE TABLE IF NOT EXISTS gda_control.entity_lineage_event (
    tenant_id TEXT NOT NULL,
    event_id UUID NOT NULL DEFAULT gen_random_uuid(),
    event_ref TEXT NOT NULL,
    lineage_kind TEXT NOT NULL,
    effective_at TIMESTAMPTZ NOT NULL,
    source_entity_refs JSONB NOT NULL,
    target_entity_refs JSONB NOT NULL,
    source_version_refs JSONB NOT NULL,
    ontology_package_id TEXT NOT NULL,
    ontology_package_sha256 CHAR(64) NOT NULL,
    ontology_review_status TEXT NOT NULL,
    decision_status TEXT NOT NULL,
    idempotency_key TEXT NOT NULL,
    owner_subject TEXT NOT NULL,
    recorded_by TEXT NOT NULL,
    reason TEXT NOT NULL,
    request_document JSONB NOT NULL,
    event_sha256 CHAR(64) NOT NULL,
    recorded_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (tenant_id, event_id),
    CONSTRAINT uq_gda_entity_lineage_event_ref UNIQUE (tenant_id, event_ref),
    CONSTRAINT uq_gda_entity_lineage_idempotency
        UNIQUE (tenant_id, idempotency_key),
    CONSTRAINT ck_gda_entity_lineage_event_ref CHECK (
        event_ref ~ '^gda://[a-z0-9][a-z0-9._-]{0,63}/entity_lineage/[a-z0-9][a-z0-9._-]{0,127}$'
        AND split_part(event_ref, '/', 3) = tenant_id
    ),
    CONSTRAINT ck_gda_entity_lineage_kind
        CHECK (lineage_kind IN ('merge', 'split', 'replacement')),
    CONSTRAINT ck_gda_entity_lineage_arrays CHECK (
        jsonb_typeof(source_entity_refs) = 'array'
        AND jsonb_array_length(source_entity_refs) BETWEEN 1 AND 100
        AND jsonb_typeof(target_entity_refs) = 'array'
        AND jsonb_array_length(target_entity_refs) BETWEEN 1 AND 100
        AND jsonb_typeof(source_version_refs) = 'array'
        AND jsonb_array_length(source_version_refs) BETWEEN 1 AND 100
    ),
    CONSTRAINT ck_gda_entity_lineage_ontology CHECK (
        ontology_package_id = 'natural-resource-one-map:2.3.0:587915868b1221af'
        AND ontology_package_sha256 =
            '587915868b1221af2315508ede7bf7babced063cba8b261de2f10afa23841019'
        AND ontology_review_status = 'technical_baseline_unreviewed'
        AND decision_status = 'assisted_precheck_not_for_production_decision'
    ),
    CONSTRAINT ck_gda_entity_lineage_idempotency CHECK (
        idempotency_key ~ '^[A-Za-z0-9][A-Za-z0-9._:-]{2,127}$'
    ),
    CONSTRAINT ck_gda_entity_lineage_owner CHECK (
        owner_subject ~ '^(human|team):[^[:space:]]{1,128}$'
    ),
    CONSTRAINT ck_gda_entity_lineage_recorder CHECK (
        recorded_by ~ '^(human|workload|agent):[^[:space:]]{1,128}$'
    ),
    CONSTRAINT ck_gda_entity_lineage_reason CHECK (
        NULLIF(btrim(reason), '') IS NOT NULL AND char_length(reason) <= 512
    ),
    CONSTRAINT ck_gda_entity_lineage_document
        CHECK (jsonb_typeof(request_document) = 'object'),
    CONSTRAINT ck_gda_entity_lineage_sha256
        CHECK (event_sha256 ~ '^[0-9a-f]{64}$')
);

CREATE TABLE IF NOT EXISTS gda_control.entity_lineage_member (
    tenant_id TEXT NOT NULL,
    event_ref TEXT NOT NULL,
    member_role TEXT NOT NULL,
    entity_ref TEXT NOT NULL,
    object_type TEXT NOT NULL,
    ordinal INTEGER NOT NULL,
    lifecycle_assertion_id UUID NOT NULL,
    recorded_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (tenant_id, event_ref, member_role, entity_ref),
    CONSTRAINT fk_gda_entity_lineage_member_event
        FOREIGN KEY (tenant_id, event_ref)
        REFERENCES gda_control.entity_lineage_event(tenant_id, event_ref),
    CONSTRAINT fk_gda_entity_lineage_member_entity
        FOREIGN KEY (tenant_id, entity_ref)
        REFERENCES gda_control.temporal_entity_identity(tenant_id, entity_ref),
    CONSTRAINT fk_gda_entity_lineage_member_assertion
        FOREIGN KEY (tenant_id, lifecycle_assertion_id)
        REFERENCES gda_control.temporal_entity_assertion(tenant_id, assertion_id),
    CONSTRAINT ck_gda_entity_lineage_member_role
        CHECK (member_role IN ('source', 'target')),
    CONSTRAINT ck_gda_entity_lineage_member_type
        CHECK (object_type ~ '^[a-z][a-z0-9_.-]{2,127}$'),
    CONSTRAINT ck_gda_entity_lineage_member_ordinal CHECK (ordinal >= 1)
);

CREATE TABLE IF NOT EXISTS gda_control.entity_link_propagation (
    tenant_id TEXT NOT NULL,
    propagation_id UUID NOT NULL DEFAULT gen_random_uuid(),
    event_ref TEXT NOT NULL,
    source_link_ref TEXT NOT NULL,
    source_retraction_assertion_id UUID NOT NULL,
    disposition TEXT NOT NULL,
    target_link_ref TEXT,
    target_assertion_id UUID,
    evidence JSONB NOT NULL,
    reason TEXT NOT NULL,
    propagation_sha256 CHAR(64) NOT NULL,
    recorded_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (tenant_id, propagation_id),
    CONSTRAINT uq_gda_entity_link_propagation_source
        UNIQUE (tenant_id, event_ref, source_link_ref),
    CONSTRAINT fk_gda_entity_link_propagation_event
        FOREIGN KEY (tenant_id, event_ref)
        REFERENCES gda_control.entity_lineage_event(tenant_id, event_ref),
    CONSTRAINT fk_gda_entity_link_propagation_source_link
        FOREIGN KEY (tenant_id, source_link_ref)
        REFERENCES gda_control.entity_link_identity(tenant_id, link_ref),
    CONSTRAINT fk_gda_entity_link_propagation_source_assertion
        FOREIGN KEY (tenant_id, source_retraction_assertion_id)
        REFERENCES gda_control.entity_link_assertion(tenant_id, assertion_id),
    CONSTRAINT fk_gda_entity_link_propagation_target_link
        FOREIGN KEY (tenant_id, target_link_ref)
        REFERENCES gda_control.entity_link_identity(tenant_id, link_ref),
    CONSTRAINT fk_gda_entity_link_propagation_target_assertion
        FOREIGN KEY (tenant_id, target_assertion_id)
        REFERENCES gda_control.entity_link_assertion(tenant_id, assertion_id),
    CONSTRAINT ck_gda_entity_link_propagation_disposition CHECK (
        disposition IN ('redirect', 'deduplicate', 'retract_only')
    ),
    CONSTRAINT ck_gda_entity_link_propagation_shape CHECK (
        (disposition = 'retract_only'
            AND target_link_ref IS NULL AND target_assertion_id IS NULL)
        OR (disposition IN ('redirect', 'deduplicate')
            AND target_link_ref IS NOT NULL AND target_assertion_id IS NOT NULL)
    ),
    CONSTRAINT ck_gda_entity_link_propagation_evidence
        CHECK (jsonb_typeof(evidence) = 'object'),
    CONSTRAINT ck_gda_entity_link_propagation_reason CHECK (
        NULLIF(btrim(reason), '') IS NOT NULL AND char_length(reason) <= 512
    ),
    CONSTRAINT ck_gda_entity_link_propagation_sha256
        CHECK (propagation_sha256 ~ '^[0-9a-f]{64}$')
);

CREATE TABLE IF NOT EXISTS gda_control.entity_source_identity_redirect (
    tenant_id TEXT NOT NULL,
    redirect_id UUID NOT NULL DEFAULT gen_random_uuid(),
    event_ref TEXT NOT NULL,
    source_identity_ref TEXT NOT NULL,
    prior_entity_ref TEXT NOT NULL,
    target_entity_ref TEXT NOT NULL,
    valid_from TIMESTAMPTZ NOT NULL,
    source_version_refs JSONB NOT NULL,
    evidence JSONB NOT NULL,
    reason TEXT NOT NULL,
    redirect_sha256 CHAR(64) NOT NULL,
    recorded_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (tenant_id, redirect_id),
    CONSTRAINT uq_gda_entity_source_redirect_event
        UNIQUE (tenant_id, event_ref, source_identity_ref),
    CONSTRAINT uq_gda_entity_source_redirect_time
        UNIQUE (tenant_id, source_identity_ref, valid_from),
    CONSTRAINT fk_gda_entity_source_redirect_event
        FOREIGN KEY (tenant_id, event_ref)
        REFERENCES gda_control.entity_lineage_event(tenant_id, event_ref),
    CONSTRAINT fk_gda_entity_source_redirect_identity
        FOREIGN KEY (tenant_id, source_identity_ref)
        REFERENCES gda_control.entity_source_identity(tenant_id, source_identity_ref),
    CONSTRAINT fk_gda_entity_source_redirect_prior
        FOREIGN KEY (tenant_id, prior_entity_ref)
        REFERENCES gda_control.temporal_entity_identity(tenant_id, entity_ref),
    CONSTRAINT fk_gda_entity_source_redirect_target
        FOREIGN KEY (tenant_id, target_entity_ref)
        REFERENCES gda_control.temporal_entity_identity(tenant_id, entity_ref),
    CONSTRAINT ck_gda_entity_source_redirect_changed
        CHECK (prior_entity_ref <> target_entity_ref),
    CONSTRAINT ck_gda_entity_source_redirect_sources CHECK (
        jsonb_typeof(source_version_refs) = 'array'
        AND jsonb_array_length(source_version_refs) BETWEEN 1 AND 100
    ),
    CONSTRAINT ck_gda_entity_source_redirect_evidence
        CHECK (jsonb_typeof(evidence) = 'object'),
    CONSTRAINT ck_gda_entity_source_redirect_reason CHECK (
        NULLIF(btrim(reason), '') IS NOT NULL AND char_length(reason) <= 512
    ),
    CONSTRAINT ck_gda_entity_source_redirect_sha256
        CHECK (redirect_sha256 ~ '^[0-9a-f]{64}$')
);

CREATE INDEX IF NOT EXISTS idx_gda_entity_lineage_member_entity
    ON gda_control.entity_lineage_member(tenant_id, entity_ref, recorded_at DESC);
CREATE INDEX IF NOT EXISTS idx_gda_entity_link_propagation_target
    ON gda_control.entity_link_propagation(tenant_id, target_link_ref);
CREATE INDEX IF NOT EXISTS idx_gda_entity_source_redirect_resolution
    ON gda_control.entity_source_identity_redirect(
        tenant_id, source_identity_ref, valid_from DESC, recorded_at DESC
    );

CREATE OR REPLACE FUNCTION gda_control.resolve_entity_source_identity(
    p_tenant_id TEXT,
    p_source_identity_ref TEXT,
    p_valid_at TIMESTAMPTZ
)
RETURNS TABLE (
    tenant_id TEXT,
    source_identity_ref TEXT,
    original_entity_ref TEXT,
    resolved_entity_ref TEXT,
    lineage_event_ref TEXT,
    resolved_valid_from TIMESTAMPTZ
)
LANGUAGE plpgsql
SECURITY DEFINER
STABLE
SET search_path = pg_catalog, gda_control
SET row_security = on
AS $$
DECLARE
    v_identity gda_control.entity_source_identity%ROWTYPE;
    v_redirect gda_control.entity_source_identity_redirect%ROWTYPE;
BEGIN
    IF gda_control.current_tenant() IS NULL
       OR p_tenant_id IS DISTINCT FROM gda_control.current_tenant() THEN
        RAISE EXCEPTION 'source identity resolution tenant is missing or mismatched'
            USING ERRCODE = '42501';
    END IF;
    IF p_valid_at IS NULL THEN
        RAISE EXCEPTION 'source identity resolution requires valid_at'
            USING ERRCODE = '22023';
    END IF;
    SELECT identity.* INTO v_identity
    FROM gda_control.entity_source_identity AS identity
    WHERE identity.tenant_id = p_tenant_id
      AND identity.source_identity_ref = p_source_identity_ref;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'source identity was not found'
            USING ERRCODE = 'P0002';
    END IF;
    SELECT redirect.* INTO v_redirect
    FROM gda_control.entity_source_identity_redirect AS redirect
    WHERE redirect.tenant_id = p_tenant_id
      AND redirect.source_identity_ref = p_source_identity_ref
      AND redirect.valid_from <= p_valid_at
    ORDER BY redirect.valid_from DESC, redirect.recorded_at DESC
    LIMIT 1;
    RETURN QUERY SELECT
        p_tenant_id,
        p_source_identity_ref,
        v_identity.entity_ref,
        COALESCE(v_redirect.target_entity_ref, v_identity.entity_ref),
        v_redirect.event_ref,
        v_redirect.valid_from;
END;
$$;

CREATE OR REPLACE FUNCTION gda_control.record_entity_lineage_event(
    p_tenant_id TEXT,
    p_request JSONB
)
RETURNS JSONB
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, gda_control, public
SET row_security = on
AS $$
DECLARE
    v_event_ref TEXT := p_request ->> 'event_ref';
    v_kind TEXT := p_request ->> 'lineage_kind';
    v_effective_at TIMESTAMPTZ;
    v_sources JSONB := p_request -> 'source_entity_refs';
    v_targets JSONB := p_request -> 'target_entity_refs';
    v_source_versions JSONB := p_request -> 'source_version_refs';
    v_link_plans JSONB := COALESCE(p_request -> 'link_propagations', '[]'::jsonb);
    v_redirect_plans JSONB := COALESCE(
        p_request -> 'source_identity_redirects', '[]'::jsonb
    );
    v_idempotency_key TEXT := p_request ->> 'idempotency_key';
    v_owner_subject TEXT := p_request ->> 'owner_subject';
    v_recorded_by TEXT := p_request ->> 'recorded_by';
    v_reason TEXT := p_request ->> 'reason';
    v_event_sha256 TEXT;
    v_recorded_at TIMESTAMPTZ := clock_timestamp();
    v_existing gda_control.entity_lineage_event%ROWTYPE;
    v_identity gda_control.temporal_entity_identity%ROWTYPE;
    v_entity_assertion gda_control.temporal_entity_assertion%ROWTYPE;
    v_retired_assertion gda_control.temporal_entity_assertion%ROWTYPE;
    v_old_link gda_control.entity_link_identity%ROWTYPE;
    v_target_link gda_control.entity_link_identity%ROWTYPE;
    v_old_assertion gda_control.entity_link_assertion%ROWTYPE;
    v_retracted_assertion gda_control.entity_link_assertion%ROWTYPE;
    v_new_assertion gda_control.entity_link_assertion%ROWTYPE;
    v_source_identity gda_control.entity_source_identity%ROWTYPE;
    v_latest_redirect gda_control.entity_source_identity_redirect%ROWTYPE;
    v_item JSONB;
    v_ref TEXT;
    v_target_ref TEXT;
    v_expected JSONB;
    v_provided JSONB;
    v_document JSONB;
    v_propagation_sha256 TEXT;
    v_redirect_sha256 TEXT;
    v_ordinal INTEGER := 0;
    v_object_type_count INTEGER;
BEGIN
    IF gda_control.current_tenant() IS NULL
       OR p_tenant_id IS DISTINCT FROM gda_control.current_tenant() THEN
        RAISE EXCEPTION 'entity lineage tenant context is missing or mismatched'
            USING ERRCODE = '42501';
    END IF;
    IF p_request IS NULL OR jsonb_typeof(p_request) <> 'object'
       OR p_request ->> 'schema_id' <> 'gda.entity-lineage-request.v1'
       OR v_event_ref !~ '^gda://[a-z0-9][a-z0-9._-]{0,63}/entity_lineage/[a-z0-9][a-z0-9._-]{0,127}$'
       OR split_part(v_event_ref, '/', 3) <> p_tenant_id
       OR v_kind NOT IN ('merge', 'split', 'replacement')
       OR p_request ->> 'ontology_package_id'
            <> 'natural-resource-one-map:2.3.0:587915868b1221af'
       OR p_request ->> 'ontology_package_sha256'
            <> '587915868b1221af2315508ede7bf7babced063cba8b261de2f10afa23841019'
       OR p_request ->> 'ontology_review_status'
            <> 'technical_baseline_unreviewed'
       OR p_request ->> 'decision_status'
            <> 'assisted_precheck_not_for_production_decision'
       OR v_idempotency_key !~ '^[A-Za-z0-9][A-Za-z0-9._:-]{2,127}$'
       OR v_owner_subject !~ '^(human|team):[^[:space:]]{1,128}$'
       OR v_recorded_by !~ '^(human|workload|agent):[^[:space:]]{1,128}$'
       OR NULLIF(btrim(v_reason), '') IS NULL
       OR char_length(v_reason) > 512 THEN
        RAISE EXCEPTION 'entity lineage identity, baseline or provenance is invalid'
            USING ERRCODE = '22023';
    END IF;
    BEGIN
        v_effective_at := (p_request ->> 'effective_at')::timestamptz;
    EXCEPTION WHEN OTHERS THEN
        RAISE EXCEPTION 'entity lineage effective_at is invalid'
            USING ERRCODE = '22023';
    END;
    IF v_effective_at IS NULL
       OR jsonb_typeof(v_sources) <> 'array'
       OR jsonb_array_length(v_sources) NOT BETWEEN 1 AND 100
       OR jsonb_typeof(v_targets) <> 'array'
       OR jsonb_array_length(v_targets) NOT BETWEEN 1 AND 100
       OR jsonb_typeof(v_source_versions) <> 'array'
       OR jsonb_array_length(v_source_versions) NOT BETWEEN 1 AND 100
       OR jsonb_typeof(v_link_plans) <> 'array'
       OR jsonb_array_length(v_link_plans) > 5000
       OR jsonb_typeof(v_redirect_plans) <> 'array'
       OR jsonb_array_length(v_redirect_plans) > 5000 THEN
        RAISE EXCEPTION 'entity lineage arrays are invalid or exceed limits'
            USING ERRCODE = '22023';
    END IF;
    IF (v_kind = 'merge' AND (
            jsonb_array_length(v_sources) < 2
            OR jsonb_array_length(v_targets) <> 1
       )) OR (v_kind = 'split' AND (
            jsonb_array_length(v_sources) <> 1
            OR jsonb_array_length(v_targets) < 2
       )) OR (v_kind = 'replacement' AND (
            jsonb_array_length(v_sources) <> 1
            OR jsonb_array_length(v_targets) <> 1
       )) THEN
        RAISE EXCEPTION 'entity lineage kind has invalid source/target cardinality'
            USING ERRCODE = '23514';
    END IF;

    IF EXISTS (
        SELECT 1 FROM jsonb_array_elements(v_sources) item(value)
        WHERE jsonb_typeof(value) <> 'string'
    ) OR EXISTS (
        SELECT 1 FROM jsonb_array_elements_text(v_sources) item(value)
        WHERE value !~ '^gda://[a-z0-9][a-z0-9._-]{0,63}/entity/[a-z0-9][a-z0-9._-]{0,127}$'
           OR split_part(value, '/', 3) <> p_tenant_id
    ) OR EXISTS (
        SELECT 1 FROM jsonb_array_elements(v_targets) item(value)
        WHERE jsonb_typeof(value) <> 'string'
    ) OR EXISTS (
        SELECT 1 FROM jsonb_array_elements_text(v_targets) item(value)
        WHERE value !~ '^gda://[a-z0-9][a-z0-9._-]{0,63}/entity/[a-z0-9][a-z0-9._-]{0,127}$'
           OR split_part(value, '/', 3) <> p_tenant_id
    ) OR EXISTS (
        SELECT 1 FROM jsonb_array_elements(v_source_versions) item(value)
        WHERE jsonb_typeof(value) <> 'string'
    ) OR EXISTS (
        SELECT 1 FROM jsonb_array_elements_text(v_source_versions) item(value)
        WHERE value !~ '^gda://[a-z0-9][a-z0-9._-]{0,63}/resource_version/[a-z0-9][a-z0-9._-]{0,127}$'
           OR split_part(value, '/', 3) <> p_tenant_id
    ) THEN
        RAISE EXCEPTION 'entity lineage references must be tenant-bound canonical URNs'
            USING ERRCODE = '22023';
    END IF;
    SELECT jsonb_agg(value ORDER BY value) INTO v_expected
    FROM (SELECT DISTINCT value FROM jsonb_array_elements_text(v_sources)) values;
    IF v_expected IS DISTINCT FROM v_sources THEN
        RAISE EXCEPTION 'source entity references must be sorted and unique'
            USING ERRCODE = '22023';
    END IF;
    SELECT jsonb_agg(value ORDER BY value) INTO v_expected
    FROM (SELECT DISTINCT value FROM jsonb_array_elements_text(v_targets)) values;
    IF v_expected IS DISTINCT FROM v_targets THEN
        RAISE EXCEPTION 'target entity references must be sorted and unique'
            USING ERRCODE = '22023';
    END IF;
    SELECT jsonb_agg(value ORDER BY value) INTO v_expected
    FROM (
        SELECT DISTINCT value FROM jsonb_array_elements_text(v_source_versions)
    ) values;
    IF v_expected IS DISTINCT FROM v_source_versions THEN
        RAISE EXCEPTION 'source version references must be sorted and unique'
            USING ERRCODE = '22023';
    END IF;
    IF EXISTS (
        SELECT 1
        FROM jsonb_array_elements_text(v_sources) source(value)
        JOIN jsonb_array_elements_text(v_targets) target(value)
          ON target.value = source.value
    ) THEN
        RAISE EXCEPTION 'source and target entities must be disjoint'
            USING ERRCODE = '23514';
    END IF;

    IF EXISTS (
        SELECT 1 FROM jsonb_array_elements(v_link_plans) plan(value)
        WHERE jsonb_typeof(value) <> 'object'
           OR value ->> 'schema_id' <> 'gda.entity-link-propagation-draft.v1'
           OR value ->> 'source_link_ref' !~ '^gda://[a-z0-9][a-z0-9._-]{0,63}/entity_link/[a-z0-9][a-z0-9._-]{0,127}$'
           OR split_part(value ->> 'source_link_ref', '/', 3) <> p_tenant_id
           OR value ->> 'disposition' NOT IN (
                'redirect', 'deduplicate', 'retract_only'
           )
           OR jsonb_typeof(value -> 'evidence') <> 'object'
           OR octet_length((value -> 'evidence')::text) > 65536
           OR NULLIF(btrim(value ->> 'reason'), '') IS NULL
           OR char_length(value ->> 'reason') > 512
    ) THEN
        RAISE EXCEPTION 'entity Link propagation plan is invalid'
            USING ERRCODE = '22023';
    END IF;
    IF EXISTS (
        SELECT 1 FROM jsonb_array_elements(v_redirect_plans) plan(value)
        WHERE jsonb_typeof(value) <> 'object'
           OR value ->> 'schema_id'
                <> 'gda.entity-source-identity-redirect-draft.v1'
           OR value ->> 'source_identity_ref' !~ '^gda://[a-z0-9][a-z0-9._-]{0,63}/source_identity/[a-z0-9][a-z0-9._-]{0,127}$'
           OR split_part(value ->> 'source_identity_ref', '/', 3) <> p_tenant_id
           OR value ->> 'target_entity_ref' !~ '^gda://[a-z0-9][a-z0-9._-]{0,63}/entity/[a-z0-9][a-z0-9._-]{0,127}$'
           OR split_part(value ->> 'target_entity_ref', '/', 3) <> p_tenant_id
           OR jsonb_typeof(value -> 'evidence') <> 'object'
           OR octet_length((value -> 'evidence')::text) > 65536
           OR NULLIF(btrim(value ->> 'reason'), '') IS NULL
           OR char_length(value ->> 'reason') > 512
    ) THEN
        RAISE EXCEPTION 'source identity redirect plan is invalid'
            USING ERRCODE = '22023';
    END IF;
    SELECT COALESCE(jsonb_agg(value ORDER BY value), '[]'::jsonb) INTO v_provided
    FROM (
        SELECT DISTINCT plan.value ->> 'source_link_ref' AS value
        FROM jsonb_array_elements(v_link_plans) plan(value)
    ) values;
    IF jsonb_array_length(v_provided) <> jsonb_array_length(v_link_plans)
       OR v_provided IS DISTINCT FROM (
            SELECT COALESCE(
                jsonb_agg(plan.value ->> 'source_link_ref' ORDER BY plan.value ->> 'source_link_ref'),
                '[]'::jsonb
            )
            FROM jsonb_array_elements(v_link_plans) plan(value)
       ) THEN
        RAISE EXCEPTION 'Link propagations must be sorted and unique by source Link'
            USING ERRCODE = '22023';
    END IF;
    SELECT COALESCE(jsonb_agg(value ORDER BY value), '[]'::jsonb) INTO v_provided
    FROM (
        SELECT DISTINCT plan.value ->> 'source_identity_ref' AS value
        FROM jsonb_array_elements(v_redirect_plans) plan(value)
    ) values;
    IF jsonb_array_length(v_provided) <> jsonb_array_length(v_redirect_plans)
       OR v_provided IS DISTINCT FROM (
            SELECT COALESCE(
                jsonb_agg(plan.value ->> 'source_identity_ref' ORDER BY plan.value ->> 'source_identity_ref'),
                '[]'::jsonb
            )
            FROM jsonb_array_elements(v_redirect_plans) plan(value)
       ) THEN
        RAISE EXCEPTION 'source identity redirects must be sorted and unique'
            USING ERRCODE = '22023';
    END IF;

    v_event_sha256 := encode(
        public.digest(convert_to(p_request::text, 'UTF8'), 'sha256'),
        'hex'
    );
    PERFORM pg_advisory_xact_lock(hashtextextended(
        'entity-lineage-idempotency|' || p_tenant_id || '|' || v_idempotency_key,
        0
    ));
    SELECT event.* INTO v_existing
    FROM gda_control.entity_lineage_event AS event
    WHERE event.tenant_id = p_tenant_id
      AND event.idempotency_key = v_idempotency_key;
    IF FOUND THEN
        IF v_existing.event_sha256 <> v_event_sha256 THEN
            RAISE EXCEPTION 'entity lineage idempotency key has different evidence'
                USING ERRCODE = '40001';
        END IF;
        RETURN jsonb_build_object(
            'schema_id', 'gda.entity-lineage-receipt.v1',
            'tenant_id', v_existing.tenant_id,
            'event_id', v_existing.event_id,
            'event_ref', v_existing.event_ref,
            'lineage_kind', v_existing.lineage_kind,
            'effective_at', v_existing.effective_at,
            'event_sha256', v_existing.event_sha256,
            'recorded_at', v_existing.recorded_at,
            'source_count', jsonb_array_length(v_existing.source_entity_refs),
            'target_count', jsonb_array_length(v_existing.target_entity_refs),
            'retired_source_count', (
                SELECT count(*) FROM gda_control.entity_lineage_member member
                WHERE member.tenant_id = p_tenant_id
                  AND member.event_ref = v_existing.event_ref
                  AND member.member_role = 'source'
            ),
            'link_retraction_count', (
                SELECT count(*) FROM gda_control.entity_link_propagation propagation
                WHERE propagation.tenant_id = p_tenant_id
                  AND propagation.event_ref = v_existing.event_ref
            ),
            'link_creation_count', (
                SELECT count(*) FROM gda_control.entity_link_propagation propagation
                WHERE propagation.tenant_id = p_tenant_id
                  AND propagation.event_ref = v_existing.event_ref
                  AND propagation.disposition = 'redirect'
            ),
            'link_deduplication_count', (
                SELECT count(*) FROM gda_control.entity_link_propagation propagation
                WHERE propagation.tenant_id = p_tenant_id
                  AND propagation.event_ref = v_existing.event_ref
                  AND propagation.disposition = 'deduplicate'
            ),
            'link_retract_only_count', (
                SELECT count(*) FROM gda_control.entity_link_propagation propagation
                WHERE propagation.tenant_id = p_tenant_id
                  AND propagation.event_ref = v_existing.event_ref
                  AND propagation.disposition = 'retract_only'
            ),
            'source_identity_redirect_count', (
                SELECT count(*)
                FROM gda_control.entity_source_identity_redirect redirect
                WHERE redirect.tenant_id = p_tenant_id
                  AND redirect.event_ref = v_existing.event_ref
            ),
            'idempotency_status', 'authority_idempotency_enforced',
            'technical_baseline_status', 'technical_baseline_unreviewed',
            'decision_status', 'assisted_precheck_not_for_production_decision'
        );
    END IF;

    FOR v_ref IN
        SELECT value FROM (
            SELECT value FROM jsonb_array_elements_text(v_sources)
            UNION ALL
            SELECT value FROM jsonb_array_elements_text(v_targets)
        ) refs ORDER BY value
    LOOP
        PERFORM pg_advisory_xact_lock(hashtextextended(
            'entity-lineage-member|' || p_tenant_id || '|' || v_ref,
            0
        ));
    END LOOP;

    IF (
        SELECT count(*) FROM gda_control.temporal_entity_identity identity
        WHERE identity.tenant_id = p_tenant_id
          AND identity.entity_ref IN (
              SELECT value FROM jsonb_array_elements_text(v_sources)
          )
    ) <> jsonb_array_length(v_sources) OR (
        SELECT count(*) FROM gda_control.temporal_entity_identity identity
        WHERE identity.tenant_id = p_tenant_id
          AND identity.entity_ref IN (
              SELECT value FROM jsonb_array_elements_text(v_targets)
          )
    ) <> jsonb_array_length(v_targets) THEN
        RAISE EXCEPTION 'entity lineage source or target identity was not found'
            USING ERRCODE = 'P0002';
    END IF;
    SELECT count(DISTINCT identity.object_type) INTO v_object_type_count
    FROM gda_control.temporal_entity_identity identity
    WHERE identity.tenant_id = p_tenant_id
      AND identity.entity_ref IN (
          SELECT value FROM jsonb_array_elements_text(v_sources)
          UNION ALL
          SELECT value FROM jsonb_array_elements_text(v_targets)
      );
    IF v_object_type_count <> 1 OR EXISTS (
        SELECT 1 FROM gda_control.temporal_entity_identity identity
        WHERE identity.tenant_id = p_tenant_id
          AND identity.entity_ref IN (
              SELECT value FROM jsonb_array_elements_text(v_sources)
              UNION ALL
              SELECT value FROM jsonb_array_elements_text(v_targets)
          )
          AND identity.owner_subject <> v_owner_subject
    ) THEN
        RAISE EXCEPTION 'lineage members must share one object type and owner'
            USING ERRCODE = '23514';
    END IF;
    IF EXISTS (
        SELECT 1 FROM jsonb_array_elements_text(v_sources) source(value)
        LEFT JOIN LATERAL (
            SELECT assertion.lifecycle_state, assertion.valid_to
            FROM gda_control.temporal_entity_assertion assertion
            WHERE assertion.tenant_id = p_tenant_id
              AND assertion.entity_ref = source.value
              AND assertion.valid_from <= v_effective_at
              AND NOT EXISTS (
                  SELECT 1 FROM gda_control.temporal_entity_assertion child
                  WHERE child.tenant_id = assertion.tenant_id
                    AND child.supersedes_assertion_id = assertion.assertion_id
              )
            ORDER BY assertion.valid_from DESC, assertion.recorded_at DESC
            LIMIT 1
        ) state ON TRUE
        WHERE state.lifecycle_state IS NULL
           OR state.lifecycle_state NOT IN ('active', 'suspended')
           OR (state.valid_to IS NOT NULL AND v_effective_at >= state.valid_to)
    ) THEN
        RAISE EXCEPTION 'lineage source must be active or suspended at effective_at'
            USING ERRCODE = '23514';
    END IF;
    IF EXISTS (
        SELECT 1 FROM jsonb_array_elements_text(v_targets) target(value)
        LEFT JOIN LATERAL (
            SELECT assertion.lifecycle_state, assertion.valid_to
            FROM gda_control.temporal_entity_assertion assertion
            WHERE assertion.tenant_id = p_tenant_id
              AND assertion.entity_ref = target.value
              AND assertion.valid_from <= v_effective_at
              AND NOT EXISTS (
                  SELECT 1 FROM gda_control.temporal_entity_assertion child
                  WHERE child.tenant_id = assertion.tenant_id
                    AND child.supersedes_assertion_id = assertion.assertion_id
              )
            ORDER BY assertion.valid_from DESC, assertion.recorded_at DESC
            LIMIT 1
        ) state ON TRUE
        WHERE state.lifecycle_state IS NULL
           OR state.lifecycle_state <> 'active'
           OR (state.valid_to IS NOT NULL AND v_effective_at >= state.valid_to)
    ) THEN
        RAISE EXCEPTION 'lineage target must be active at effective_at'
            USING ERRCODE = '23514';
    END IF;

    SELECT COALESCE(jsonb_agg(link_ref ORDER BY link_ref), '[]'::jsonb)
    INTO v_expected
    FROM (
        SELECT identity.link_ref
        FROM gda_control.entity_link_identity identity
        JOIN LATERAL (
            SELECT assertion.lifecycle_state, assertion.valid_to
            FROM gda_control.entity_link_assertion assertion
            WHERE assertion.tenant_id = identity.tenant_id
              AND assertion.link_ref = identity.link_ref
              AND assertion.valid_from <= v_effective_at
              AND NOT EXISTS (
                  SELECT 1 FROM gda_control.entity_link_assertion child
                  WHERE child.tenant_id = assertion.tenant_id
                    AND child.supersedes_assertion_id = assertion.assertion_id
              )
            ORDER BY assertion.valid_from DESC, assertion.recorded_at DESC
            LIMIT 1
        ) state ON TRUE
        WHERE identity.tenant_id = p_tenant_id
          AND (
              identity.source_entity_ref IN (
                  SELECT value FROM jsonb_array_elements_text(v_sources)
              ) OR identity.target_entity_ref IN (
                  SELECT value FROM jsonb_array_elements_text(v_sources)
              )
          )
          AND state.lifecycle_state = 'active'
          AND (state.valid_to IS NULL OR v_effective_at < state.valid_to)
    ) active_links;
    SELECT COALESCE(
        jsonb_agg(plan.value ->> 'source_link_ref' ORDER BY plan.value ->> 'source_link_ref'),
        '[]'::jsonb
    ) INTO v_provided
    FROM jsonb_array_elements(v_link_plans) plan(value);
    IF v_expected IS DISTINCT FROM v_provided THEN
        RAISE EXCEPTION 'all active source Links require one explicit propagation'
            USING ERRCODE = '23514';
    END IF;

    SELECT COALESCE(jsonb_agg(source_identity_ref ORDER BY source_identity_ref), '[]'::jsonb)
    INTO v_expected
    FROM (
        SELECT identity.source_identity_ref
        FROM gda_control.entity_source_identity identity
        LEFT JOIN LATERAL (
            SELECT redirect.target_entity_ref
            FROM gda_control.entity_source_identity_redirect redirect
            WHERE redirect.tenant_id = identity.tenant_id
              AND redirect.source_identity_ref = identity.source_identity_ref
              AND redirect.valid_from <= v_effective_at
            ORDER BY redirect.valid_from DESC, redirect.recorded_at DESC
            LIMIT 1
        ) latest ON TRUE
        WHERE identity.tenant_id = p_tenant_id
          AND COALESCE(latest.target_entity_ref, identity.entity_ref) IN (
              SELECT value FROM jsonb_array_elements_text(v_sources)
          )
    ) source_identities;
    SELECT COALESCE(
        jsonb_agg(plan.value ->> 'source_identity_ref' ORDER BY plan.value ->> 'source_identity_ref'),
        '[]'::jsonb
    ) INTO v_provided
    FROM jsonb_array_elements(v_redirect_plans) plan(value);
    IF v_expected IS DISTINCT FROM v_provided THEN
        RAISE EXCEPTION 'all effective source identities require one explicit redirect'
            USING ERRCODE = '23514';
    END IF;

    INSERT INTO gda_control.entity_lineage_event (
        tenant_id, event_ref, lineage_kind, effective_at,
        source_entity_refs, target_entity_refs, source_version_refs,
        ontology_package_id, ontology_package_sha256,
        ontology_review_status, decision_status, idempotency_key,
        owner_subject, recorded_by, reason, request_document,
        event_sha256, recorded_at
    ) VALUES (
        p_tenant_id, v_event_ref, v_kind, v_effective_at,
        v_sources, v_targets, v_source_versions,
        p_request ->> 'ontology_package_id',
        p_request ->> 'ontology_package_sha256',
        p_request ->> 'ontology_review_status',
        p_request ->> 'decision_status', v_idempotency_key,
        v_owner_subject, v_recorded_by, v_reason, p_request,
        v_event_sha256, v_recorded_at
    ) RETURNING * INTO v_existing;

    v_ordinal := 0;
    FOR v_ref IN SELECT value FROM jsonb_array_elements_text(v_sources) ORDER BY value
    LOOP
        v_ordinal := v_ordinal + 1;
        SELECT identity.* INTO v_identity
        FROM gda_control.temporal_entity_identity identity
        WHERE identity.tenant_id = p_tenant_id AND identity.entity_ref = v_ref;
        SELECT assertion.* INTO v_entity_assertion
        FROM gda_control.temporal_entity_assertion assertion
        WHERE assertion.tenant_id = p_tenant_id
          AND assertion.entity_ref = v_ref
          AND assertion.valid_from <= v_effective_at
          AND NOT EXISTS (
              SELECT 1 FROM gda_control.temporal_entity_assertion child
              WHERE child.tenant_id = assertion.tenant_id
                AND child.supersedes_assertion_id = assertion.assertion_id
          )
        ORDER BY assertion.valid_from DESC, assertion.recorded_at DESC
        LIMIT 1;
        SELECT * INTO v_retired_assertion
        FROM gda_control.record_temporal_entity_assertion(
            p_tenant_id, v_ref, v_identity.object_type, 'retired',
            v_entity_assertion.attributes, v_effective_at, NULL,
            v_source_versions, 'transition', NULL,
            'lineage.entity.' || substr(v_event_sha256, 1, 16) || '.' ||
                substr(encode(public.digest(v_ref, 'sha256'), 'hex'), 1, 16),
            v_owner_subject, v_recorded_by, v_reason
        );
        INSERT INTO gda_control.entity_lineage_member (
            tenant_id, event_ref, member_role, entity_ref, object_type,
            ordinal, lifecycle_assertion_id, recorded_at
        ) VALUES (
            p_tenant_id, v_event_ref, 'source', v_ref, v_identity.object_type,
            v_ordinal, v_retired_assertion.assertion_id, v_recorded_at
        );
    END LOOP;

    v_ordinal := 0;
    FOR v_ref IN SELECT value FROM jsonb_array_elements_text(v_targets) ORDER BY value
    LOOP
        v_ordinal := v_ordinal + 1;
        SELECT identity.* INTO v_identity
        FROM gda_control.temporal_entity_identity identity
        WHERE identity.tenant_id = p_tenant_id AND identity.entity_ref = v_ref;
        SELECT assertion.* INTO v_entity_assertion
        FROM gda_control.temporal_entity_assertion assertion
        WHERE assertion.tenant_id = p_tenant_id
          AND assertion.entity_ref = v_ref
          AND assertion.valid_from <= v_effective_at
          AND NOT EXISTS (
              SELECT 1 FROM gda_control.temporal_entity_assertion child
              WHERE child.tenant_id = assertion.tenant_id
                AND child.supersedes_assertion_id = assertion.assertion_id
          )
        ORDER BY assertion.valid_from DESC, assertion.recorded_at DESC
        LIMIT 1;
        INSERT INTO gda_control.entity_lineage_member (
            tenant_id, event_ref, member_role, entity_ref, object_type,
            ordinal, lifecycle_assertion_id, recorded_at
        ) VALUES (
            p_tenant_id, v_event_ref, 'target', v_ref, v_identity.object_type,
            v_ordinal, v_entity_assertion.assertion_id, v_recorded_at
        );
    END LOOP;

    FOR v_item IN
        SELECT value FROM jsonb_array_elements(v_link_plans)
        ORDER BY value ->> 'source_link_ref'
    LOOP
        v_ref := v_item ->> 'source_link_ref';
        SELECT identity.* INTO v_old_link
        FROM gda_control.entity_link_identity identity
        WHERE identity.tenant_id = p_tenant_id AND identity.link_ref = v_ref;
        SELECT assertion.* INTO v_old_assertion
        FROM gda_control.entity_link_assertion assertion
        WHERE assertion.tenant_id = p_tenant_id
          AND assertion.link_ref = v_ref
          AND assertion.valid_from <= v_effective_at
          AND NOT EXISTS (
              SELECT 1 FROM gda_control.entity_link_assertion child
              WHERE child.tenant_id = assertion.tenant_id
                AND child.supersedes_assertion_id = assertion.assertion_id
          )
        ORDER BY assertion.valid_from DESC, assertion.recorded_at DESC
        LIMIT 1;
        SELECT * INTO v_retracted_assertion
        FROM gda_control.record_entity_link_assertion(
            p_tenant_id, v_old_link.link_ref, v_old_link.link_type_ref,
            v_old_link.source_entity_ref, v_old_link.target_entity_ref,
            'retracted', v_old_assertion.attributes, v_effective_at, NULL,
            v_source_versions, 'transition', NULL,
            v_old_assertion.confidence_basis_points,
            v_old_assertion.evidence || jsonb_build_object(
                'lineage_event_ref', v_event_ref,
                'lineage_disposition', v_item ->> 'disposition'
            ),
            'lineage.link.retract.' || substr(v_event_sha256, 1, 16) || '.' ||
                substr(encode(public.digest(v_ref, 'sha256'), 'hex'), 1, 16),
            v_owner_subject, v_recorded_by, v_item ->> 'reason'
        );
    END LOOP;

    FOR v_item IN
        SELECT value FROM jsonb_array_elements(v_link_plans)
        WHERE value ->> 'disposition' = 'redirect'
        ORDER BY value ->> 'source_link_ref'
    LOOP
        v_ref := v_item ->> 'source_link_ref';
        SELECT identity.* INTO v_old_link
        FROM gda_control.entity_link_identity identity
        WHERE identity.tenant_id = p_tenant_id AND identity.link_ref = v_ref;
        IF v_item ->> 'target_link_ref' IS NULL
           OR v_item ->> 'target_link_ref' = v_ref
           OR v_item ->> 'target_source_entity_ref' IS NULL
           OR v_item ->> 'target_target_entity_ref' IS NULL
           OR NOT (
                (
                    (v_old_link.source_entity_ref IN (
                        SELECT value FROM jsonb_array_elements_text(v_sources)
                    ) AND v_item ->> 'target_source_entity_ref' IN (
                        SELECT value FROM jsonb_array_elements_text(v_targets)
                    )) OR (
                        v_old_link.source_entity_ref NOT IN (
                            SELECT value FROM jsonb_array_elements_text(v_sources)
                        ) AND v_item ->> 'target_source_entity_ref'
                            = v_old_link.source_entity_ref
                    )
                ) AND (
                    (v_old_link.target_entity_ref IN (
                        SELECT value FROM jsonb_array_elements_text(v_sources)
                    ) AND v_item ->> 'target_target_entity_ref' IN (
                        SELECT value FROM jsonb_array_elements_text(v_targets)
                    )) OR (
                        v_old_link.target_entity_ref NOT IN (
                            SELECT value FROM jsonb_array_elements_text(v_sources)
                        ) AND v_item ->> 'target_target_entity_ref'
                            = v_old_link.target_entity_ref
                    )
                )
           ) THEN
            RAISE EXCEPTION 'redirect must replace only source endpoints with targets'
                USING ERRCODE = '23514';
        END IF;
        SELECT assertion.* INTO v_old_assertion
        FROM gda_control.entity_link_assertion assertion
        WHERE assertion.tenant_id = p_tenant_id
          AND assertion.link_ref = v_ref
          AND assertion.valid_from < v_effective_at
        ORDER BY assertion.valid_from DESC, assertion.recorded_at DESC
        LIMIT 1;
        SELECT * INTO v_new_assertion
        FROM gda_control.record_entity_link_assertion(
            p_tenant_id, v_item ->> 'target_link_ref', v_old_link.link_type_ref,
            v_item ->> 'target_source_entity_ref',
            v_item ->> 'target_target_entity_ref',
            'active', v_old_assertion.attributes, v_effective_at, NULL,
            v_source_versions, 'initial', NULL,
            v_old_assertion.confidence_basis_points,
            v_old_assertion.evidence || jsonb_build_object(
                'lineage_event_ref', v_event_ref,
                'propagated_from_link_ref', v_ref,
                'lineage_evidence', v_item -> 'evidence'
            ),
            'lineage.link.create.' || substr(v_event_sha256, 1, 16) || '.' ||
                substr(encode(public.digest(v_ref, 'sha256'), 'hex'), 1, 16),
            v_owner_subject, v_recorded_by, v_item ->> 'reason'
        );
    END LOOP;

    FOR v_item IN
        SELECT value FROM jsonb_array_elements(v_link_plans)
        ORDER BY value ->> 'source_link_ref'
    LOOP
        v_ref := v_item ->> 'source_link_ref';
        v_target_ref := v_item ->> 'target_link_ref';
        SELECT identity.* INTO v_old_link
        FROM gda_control.entity_link_identity identity
        WHERE identity.tenant_id = p_tenant_id AND identity.link_ref = v_ref;
        SELECT assertion.* INTO v_retracted_assertion
        FROM gda_control.entity_link_assertion assertion
        WHERE assertion.tenant_id = p_tenant_id
          AND assertion.idempotency_key =
              'lineage.link.retract.' || substr(v_event_sha256, 1, 16) || '.' ||
              substr(encode(public.digest(v_ref, 'sha256'), 'hex'), 1, 16);
        v_new_assertion.assertion_id := NULL;
        IF v_item ->> 'disposition' = 'redirect' THEN
            SELECT assertion.* INTO v_new_assertion
            FROM gda_control.entity_link_assertion assertion
            WHERE assertion.tenant_id = p_tenant_id
              AND assertion.idempotency_key =
                  'lineage.link.create.' || substr(v_event_sha256, 1, 16) || '.' ||
                  substr(encode(public.digest(v_ref, 'sha256'), 'hex'), 1, 16);
        ELSIF v_item ->> 'disposition' = 'deduplicate' THEN
            IF v_target_ref IS NULL OR v_target_ref = v_ref THEN
                RAISE EXCEPTION 'deduplicate requires a different target Link'
                    USING ERRCODE = '23514';
            END IF;
            SELECT identity.* INTO v_target_link
            FROM gda_control.entity_link_identity identity
            WHERE identity.tenant_id = p_tenant_id
              AND identity.link_ref = v_target_ref;
            IF NOT FOUND OR v_target_link.link_type_ref <> v_old_link.link_type_ref
               OR v_target_link.owner_subject <> v_owner_subject
               OR NOT (
                    (
                        (v_old_link.source_entity_ref IN (
                            SELECT value FROM jsonb_array_elements_text(v_sources)
                        ) AND v_target_link.source_entity_ref IN (
                            SELECT value FROM jsonb_array_elements_text(v_targets)
                        )) OR (
                            v_old_link.source_entity_ref NOT IN (
                                SELECT value FROM jsonb_array_elements_text(v_sources)
                            ) AND v_target_link.source_entity_ref
                                = v_old_link.source_entity_ref
                        )
                    ) AND (
                        (v_old_link.target_entity_ref IN (
                            SELECT value FROM jsonb_array_elements_text(v_sources)
                        ) AND v_target_link.target_entity_ref IN (
                            SELECT value FROM jsonb_array_elements_text(v_targets)
                        )) OR (
                            v_old_link.target_entity_ref NOT IN (
                                SELECT value FROM jsonb_array_elements_text(v_sources)
                            ) AND v_target_link.target_entity_ref
                                = v_old_link.target_entity_ref
                        )
                    )
               ) THEN
                RAISE EXCEPTION 'deduplicate target Link is not an equivalent propagation'
                    USING ERRCODE = '23514';
            END IF;
            SELECT assertion.* INTO v_new_assertion
            FROM gda_control.entity_link_assertion assertion
            WHERE assertion.tenant_id = p_tenant_id
              AND assertion.link_ref = v_target_ref
              AND assertion.valid_from <= v_effective_at
              AND NOT EXISTS (
                  SELECT 1 FROM gda_control.entity_link_assertion child
                  WHERE child.tenant_id = assertion.tenant_id
                    AND child.supersedes_assertion_id = assertion.assertion_id
              )
            ORDER BY assertion.valid_from DESC, assertion.recorded_at DESC
            LIMIT 1;
            IF NOT FOUND OR v_new_assertion.lifecycle_state <> 'active'
               OR (v_new_assertion.valid_to IS NOT NULL
                    AND v_effective_at >= v_new_assertion.valid_to) THEN
                RAISE EXCEPTION 'deduplicate target Link is not active at effective_at'
                    USING ERRCODE = '23514';
            END IF;
        ELSIF v_item ->> 'target_link_ref' IS NOT NULL THEN
            RAISE EXCEPTION 'retract_only cannot name a target Link'
                USING ERRCODE = '23514';
        END IF;
        v_document := jsonb_build_object(
            'schema_id', 'gda.entity-link-propagation.v1',
            'tenant_id', p_tenant_id,
            'event_ref', v_event_ref,
            'source_link_ref', v_ref,
            'source_retraction_assertion_id', v_retracted_assertion.assertion_id,
            'disposition', v_item ->> 'disposition',
            'target_link_ref', v_target_ref,
            'target_assertion_id', v_new_assertion.assertion_id,
            'evidence', v_item -> 'evidence',
            'reason', v_item ->> 'reason'
        );
        v_propagation_sha256 := encode(
            public.digest(convert_to(v_document::text, 'UTF8'), 'sha256'), 'hex'
        );
        INSERT INTO gda_control.entity_link_propagation (
            tenant_id, event_ref, source_link_ref,
            source_retraction_assertion_id, disposition, target_link_ref,
            target_assertion_id, evidence, reason, propagation_sha256,
            recorded_at
        ) VALUES (
            p_tenant_id, v_event_ref, v_ref,
            v_retracted_assertion.assertion_id, v_item ->> 'disposition',
            v_target_ref, v_new_assertion.assertion_id,
            v_item -> 'evidence', v_item ->> 'reason',
            v_propagation_sha256, v_recorded_at
        );
    END LOOP;

    FOR v_item IN
        SELECT value FROM jsonb_array_elements(v_redirect_plans)
        ORDER BY value ->> 'source_identity_ref'
    LOOP
        v_ref := v_item ->> 'source_identity_ref';
        v_target_ref := v_item ->> 'target_entity_ref';
        SELECT identity.* INTO v_source_identity
        FROM gda_control.entity_source_identity identity
        WHERE identity.tenant_id = p_tenant_id
          AND identity.source_identity_ref = v_ref;
        SELECT redirect.* INTO v_latest_redirect
        FROM gda_control.entity_source_identity_redirect redirect
        WHERE redirect.tenant_id = p_tenant_id
          AND redirect.source_identity_ref = v_ref
          AND redirect.valid_from <= v_effective_at
        ORDER BY redirect.valid_from DESC, redirect.recorded_at DESC
        LIMIT 1;
        v_ref := COALESCE(v_latest_redirect.target_entity_ref, v_source_identity.entity_ref);
        IF v_ref NOT IN (
            SELECT value FROM jsonb_array_elements_text(v_sources)
        ) OR v_target_ref NOT IN (
            SELECT value FROM jsonb_array_elements_text(v_targets)
        ) OR v_ref = v_target_ref THEN
            RAISE EXCEPTION 'source identity redirect does not match lineage members'
                USING ERRCODE = '23514';
        END IF;
        v_document := jsonb_build_object(
            'schema_id', 'gda.entity-source-identity-redirect.v1',
            'tenant_id', p_tenant_id,
            'event_ref', v_event_ref,
            'source_identity_ref', v_item ->> 'source_identity_ref',
            'prior_entity_ref', v_ref,
            'target_entity_ref', v_target_ref,
            'valid_from', v_effective_at,
            'source_version_refs', v_source_versions,
            'evidence', v_item -> 'evidence',
            'reason', v_item ->> 'reason'
        );
        v_redirect_sha256 := encode(
            public.digest(convert_to(v_document::text, 'UTF8'), 'sha256'), 'hex'
        );
        INSERT INTO gda_control.entity_source_identity_redirect (
            tenant_id, event_ref, source_identity_ref, prior_entity_ref,
            target_entity_ref, valid_from, source_version_refs, evidence,
            reason, redirect_sha256, recorded_at
        ) VALUES (
            p_tenant_id, v_event_ref, v_item ->> 'source_identity_ref', v_ref,
            v_target_ref, v_effective_at, v_source_versions,
            v_item -> 'evidence', v_item ->> 'reason', v_redirect_sha256,
            v_recorded_at
        );
    END LOOP;

    RETURN jsonb_build_object(
        'schema_id', 'gda.entity-lineage-receipt.v1',
        'tenant_id', p_tenant_id,
        'event_id', v_existing.event_id,
        'event_ref', v_event_ref,
        'lineage_kind', v_kind,
        'effective_at', v_effective_at,
        'event_sha256', v_event_sha256,
        'recorded_at', v_recorded_at,
        'source_count', jsonb_array_length(v_sources),
        'target_count', jsonb_array_length(v_targets),
        'retired_source_count', jsonb_array_length(v_sources),
        'link_retraction_count', jsonb_array_length(v_link_plans),
        'link_creation_count', (
            SELECT count(*) FROM jsonb_array_elements(v_link_plans) plan(value)
            WHERE value ->> 'disposition' = 'redirect'
        ),
        'link_deduplication_count', (
            SELECT count(*) FROM jsonb_array_elements(v_link_plans) plan(value)
            WHERE value ->> 'disposition' = 'deduplicate'
        ),
        'link_retract_only_count', (
            SELECT count(*) FROM jsonb_array_elements(v_link_plans) plan(value)
            WHERE value ->> 'disposition' = 'retract_only'
        ),
        'source_identity_redirect_count', jsonb_array_length(v_redirect_plans),
        'idempotency_status', 'authority_idempotency_enforced',
        'technical_baseline_status', 'technical_baseline_unreviewed',
        'decision_status', 'assisted_precheck_not_for_production_decision'
    );
END;
$$;

DO $$
DECLARE
    relation_name TEXT;
BEGIN
    FOREACH relation_name IN ARRAY ARRAY[
        'entity_lineage_event',
        'entity_lineage_member',
        'entity_link_propagation',
        'entity_source_identity_redirect'
    ]
    LOOP
        EXECUTE format(
            'ALTER TABLE gda_control.%I ENABLE ROW LEVEL SECURITY', relation_name
        );
        EXECUTE format(
            'ALTER TABLE gda_control.%I FORCE ROW LEVEL SECURITY', relation_name
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
            relation_name, relation_name
        );
        EXECUTE format(
            'CREATE TRIGGER trg_gda_%s_immutable BEFORE UPDATE OR DELETE ON '
            'gda_control.%I FOR EACH ROW EXECUTE FUNCTION '
            'gda_control.reject_immutable_mutation()',
            relation_name, relation_name
        );
    END LOOP;
END;
$$;

REVOKE ALL ON TABLE gda_control.entity_lineage_event
    FROM PUBLIC, gda_control_gateway;
REVOKE ALL ON TABLE gda_control.entity_lineage_member
    FROM PUBLIC, gda_control_gateway;
REVOKE ALL ON TABLE gda_control.entity_link_propagation
    FROM PUBLIC, gda_control_gateway;
REVOKE ALL ON TABLE gda_control.entity_source_identity_redirect
    FROM PUBLIC, gda_control_gateway;
REVOKE ALL ON FUNCTION gda_control.resolve_entity_source_identity(
    TEXT, TEXT, TIMESTAMPTZ
) FROM PUBLIC;
REVOKE ALL ON FUNCTION gda_control.record_entity_lineage_event(
    TEXT, JSONB
) FROM PUBLIC;

GRANT SELECT ON TABLE gda_control.entity_lineage_event
    TO gda_control_gateway;
GRANT SELECT ON TABLE gda_control.entity_lineage_member
    TO gda_control_gateway;
GRANT SELECT ON TABLE gda_control.entity_link_propagation
    TO gda_control_gateway;
GRANT SELECT ON TABLE gda_control.entity_source_identity_redirect
    TO gda_control_gateway;
GRANT EXECUTE ON FUNCTION gda_control.resolve_entity_source_identity(
    TEXT, TEXT, TIMESTAMPTZ
) TO gda_control_gateway;
GRANT EXECUTE ON FUNCTION gda_control.record_entity_lineage_event(
    TEXT, JSONB
) TO gda_control_gateway;
