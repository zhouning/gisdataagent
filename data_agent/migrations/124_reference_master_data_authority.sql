-- 124: Tenant-scoped reference-master authority and approved golden pointer.
--
-- AI match output is immutable evidence, never an authoritative write. A
-- master entity version becomes active only through an exact ApprovalCase.

CREATE EXTENSION IF NOT EXISTS pgcrypto WITH SCHEMA public;

CREATE TABLE IF NOT EXISTS gda_control.master_source_record (
    tenant_id TEXT NOT NULL,
    source_record_ref TEXT NOT NULL,
    domain TEXT NOT NULL,
    source_system_ref TEXT NOT NULL,
    source_record_id TEXT NOT NULL,
    source_revision TEXT NOT NULL,
    business_key TEXT NOT NULL,
    display_name TEXT NOT NULL,
    parent_business_key TEXT,
    attributes JSONB NOT NULL DEFAULT '{}'::jsonb,
    record_fingerprint CHAR(64) NOT NULL,
    observed_by TEXT NOT NULL,
    observed_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (tenant_id, source_record_ref),
    CONSTRAINT uq_gda_master_source_revision
        UNIQUE (tenant_id, source_system_ref, source_record_id, source_revision),
    CONSTRAINT uq_gda_master_source_fingerprint
        UNIQUE (tenant_id, source_record_ref, record_fingerprint),
    CONSTRAINT ck_gda_master_source_tenant
        CHECK (tenant_id ~ '^[a-z0-9][a-z0-9._-]{0,63}$'),
    CONSTRAINT ck_gda_master_source_ref CHECK (
        source_record_ref ~ '^gda://[a-z0-9][a-z0-9._-]{0,63}/master_source_record/[a-z0-9][a-z0-9._-]{0,127}$'
        AND split_part(source_record_ref, '/', 3) = tenant_id
    ),
    CONSTRAINT ck_gda_master_source_domain
        CHECK (domain IN ('administrative_unit', 'land_use_code')),
    CONSTRAINT ck_gda_master_source_system CHECK (
        source_system_ref ~ '^gda://[a-z0-9][a-z0-9._-]{0,63}/[a-z][a-z0-9_-]{1,31}/[a-z0-9][a-z0-9._-]{0,127}$'
        AND split_part(source_system_ref, '/', 3) = tenant_id
    ),
    CONSTRAINT ck_gda_master_source_record_id
        CHECK (NULLIF(btrim(source_record_id), '') IS NOT NULL),
    CONSTRAINT ck_gda_master_source_revision
        CHECK (source_revision ~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$'),
    CONSTRAINT ck_gda_master_source_business_key
        CHECK (business_key ~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$'),
    CONSTRAINT ck_gda_master_source_parent_key CHECK (
        parent_business_key IS NULL
        OR parent_business_key ~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$'
    ),
    CONSTRAINT ck_gda_master_source_display_name
        CHECK (NULLIF(btrim(display_name), '') IS NOT NULL),
    CONSTRAINT ck_gda_master_source_attributes
        CHECK (jsonb_typeof(attributes) = 'object'),
    CONSTRAINT ck_gda_master_source_fingerprint
        CHECK (record_fingerprint ~ '^[0-9a-f]{64}$'),
    CONSTRAINT ck_gda_master_source_observer
        CHECK (observed_by ~ '^(human|workload|agent):[^[:space:]]{1,128}$')
);

CREATE INDEX IF NOT EXISTS idx_gda_master_source_lookup
    ON gda_control.master_source_record(
        tenant_id, domain, lower(business_key), observed_at DESC
    );

CREATE TABLE IF NOT EXISTS gda_control.master_entity_version (
    tenant_id TEXT NOT NULL,
    entity_ref TEXT NOT NULL,
    entity_version_ref TEXT NOT NULL,
    entity_version INTEGER NOT NULL,
    domain TEXT NOT NULL,
    business_key TEXT NOT NULL,
    canonical_name TEXT NOT NULL,
    parent_entity_ref TEXT,
    attributes JSONB NOT NULL DEFAULT '{}'::jsonb,
    source_record_refs JSONB NOT NULL,
    match_candidate_refs JSONB NOT NULL DEFAULT '[]'::jsonb,
    valid_from DATE NOT NULL,
    valid_to DATE,
    owner_subject TEXT NOT NULL,
    entity_fingerprint CHAR(64) NOT NULL,
    created_by TEXT NOT NULL,
    creation_reason TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (tenant_id, entity_version_ref),
    CONSTRAINT uq_gda_master_entity_version_number
        UNIQUE (tenant_id, entity_ref, entity_version),
    CONSTRAINT uq_gda_master_entity_version_fingerprint
        UNIQUE (tenant_id, entity_version_ref, entity_fingerprint),
    CONSTRAINT ck_gda_master_entity_ref CHECK (
        entity_ref ~ '^gda://[a-z0-9][a-z0-9._-]{0,63}/master_entity/[a-z0-9][a-z0-9._-]{0,127}$'
        AND split_part(entity_ref, '/', 3) = tenant_id
    ),
    CONSTRAINT ck_gda_master_entity_version_ref CHECK (
        entity_version_ref = entity_ref || '.v' || entity_version::text
    ),
    CONSTRAINT ck_gda_master_entity_version
        CHECK (entity_version BETWEEN 1 AND 1000000),
    CONSTRAINT ck_gda_master_entity_domain
        CHECK (domain IN ('administrative_unit', 'land_use_code')),
    CONSTRAINT ck_gda_master_entity_business_key
        CHECK (business_key ~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$'),
    CONSTRAINT ck_gda_master_entity_name
        CHECK (NULLIF(btrim(canonical_name), '') IS NOT NULL),
    CONSTRAINT ck_gda_master_entity_parent CHECK (
        parent_entity_ref IS NULL
        OR (
            parent_entity_ref ~ '^gda://[a-z0-9][a-z0-9._-]{0,63}/master_entity/[a-z0-9][a-z0-9._-]{0,127}$'
            AND split_part(parent_entity_ref, '/', 3) = tenant_id
            AND parent_entity_ref <> entity_ref
        )
    ),
    CONSTRAINT ck_gda_master_entity_attributes
        CHECK (jsonb_typeof(attributes) = 'object'),
    CONSTRAINT ck_gda_master_entity_sources CHECK (
        jsonb_typeof(source_record_refs) = 'array'
        AND jsonb_array_length(source_record_refs) BETWEEN 1 AND 100
    ),
    CONSTRAINT ck_gda_master_entity_matches CHECK (
        jsonb_typeof(match_candidate_refs) = 'array'
        AND jsonb_array_length(match_candidate_refs) BETWEEN 0 AND 100
    ),
    CONSTRAINT ck_gda_master_entity_valid_time
        CHECK (valid_to IS NULL OR valid_to > valid_from),
    CONSTRAINT ck_gda_master_entity_owner
        CHECK (owner_subject ~ '^(human|team):[^[:space:]]{1,128}$'),
    CONSTRAINT ck_gda_master_entity_fingerprint
        CHECK (entity_fingerprint ~ '^[0-9a-f]{64}$'),
    CONSTRAINT ck_gda_master_entity_creator
        CHECK (created_by ~ '^(human|workload|agent):[^[:space:]]{1,128}$'),
    CONSTRAINT ck_gda_master_entity_reason
        CHECK (NULLIF(btrim(creation_reason), '') IS NOT NULL)
);

CREATE INDEX IF NOT EXISTS idx_gda_master_entity_versions
    ON gda_control.master_entity_version(
        tenant_id, domain, lower(business_key), entity_version DESC
    );

CREATE TABLE IF NOT EXISTS gda_control.master_match_candidate (
    tenant_id TEXT NOT NULL,
    match_candidate_ref TEXT NOT NULL,
    source_record_ref TEXT NOT NULL,
    candidate_entity_ref TEXT NOT NULL,
    candidate_version_ref TEXT NOT NULL,
    candidate_fingerprint CHAR(64) NOT NULL,
    algorithm_version TEXT NOT NULL,
    confidence_basis_points INTEGER NOT NULL,
    disposition TEXT NOT NULL,
    evidence JSONB NOT NULL,
    proposal_fingerprint CHAR(64) NOT NULL,
    proposed_by TEXT NOT NULL,
    proposed_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (tenant_id, match_candidate_ref),
    CONSTRAINT uq_gda_master_match_fingerprint
        UNIQUE (tenant_id, match_candidate_ref, proposal_fingerprint),
    CONSTRAINT fk_gda_master_match_source
        FOREIGN KEY (tenant_id, source_record_ref)
        REFERENCES gda_control.master_source_record(tenant_id, source_record_ref),
    CONSTRAINT fk_gda_master_match_version
        FOREIGN KEY (tenant_id, candidate_version_ref, candidate_fingerprint)
        REFERENCES gda_control.master_entity_version(
            tenant_id, entity_version_ref, entity_fingerprint
        ),
    CONSTRAINT ck_gda_master_match_ref CHECK (
        match_candidate_ref ~ '^gda://[a-z0-9][a-z0-9._-]{0,63}/master_match/[a-z0-9][a-z0-9._-]{0,127}$'
        AND split_part(match_candidate_ref, '/', 3) = tenant_id
    ),
    CONSTRAINT ck_gda_master_match_entity CHECK (
        candidate_entity_ref ~ '^gda://[a-z0-9][a-z0-9._-]{0,63}/master_entity/[a-z0-9][a-z0-9._-]{0,127}$'
        AND split_part(candidate_entity_ref, '/', 3) = tenant_id
    ),
    CONSTRAINT ck_gda_master_match_algorithm
        CHECK (algorithm_version = 'master-match-v1'),
    CONSTRAINT ck_gda_master_match_score
        CHECK (confidence_basis_points BETWEEN 0 AND 10000),
    CONSTRAINT ck_gda_master_match_disposition
        CHECK (disposition IN ('recommended', 'review_required', 'conflict')),
    CONSTRAINT ck_gda_master_match_evidence
        CHECK (jsonb_typeof(evidence) = 'object'),
    CONSTRAINT ck_gda_master_match_proposal_fingerprint
        CHECK (proposal_fingerprint ~ '^[0-9a-f]{64}$'),
    CONSTRAINT ck_gda_master_match_proposer
        CHECK (proposed_by ~ '^(workload|agent):[^[:space:]]{1,128}$')
);

CREATE INDEX IF NOT EXISTS idx_gda_master_match_source
    ON gda_control.master_match_candidate(
        tenant_id, source_record_ref, confidence_basis_points DESC
    );

CREATE TABLE IF NOT EXISTS gda_control.master_entity_activation (
    tenant_id TEXT NOT NULL,
    entity_ref TEXT NOT NULL,
    domain TEXT NOT NULL,
    business_key TEXT NOT NULL,
    active_version_ref TEXT NOT NULL,
    active_fingerprint CHAR(64) NOT NULL,
    approval_case_ref TEXT NOT NULL,
    activation_version INTEGER NOT NULL,
    activated_by TEXT NOT NULL,
    activation_reason TEXT NOT NULL,
    activated_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (tenant_id, entity_ref),
    CONSTRAINT uq_gda_master_active_business_key
        UNIQUE (tenant_id, domain, business_key),
    CONSTRAINT fk_gda_master_activation_version
        FOREIGN KEY (tenant_id, active_version_ref, active_fingerprint)
        REFERENCES gda_control.master_entity_version(
            tenant_id, entity_version_ref, entity_fingerprint
        ),
    CONSTRAINT fk_gda_master_activation_approval
        FOREIGN KEY (tenant_id, approval_case_ref)
        REFERENCES gda_control.approval_case(tenant_id, approval_case_ref),
    CONSTRAINT ck_gda_master_activation_domain
        CHECK (domain IN ('administrative_unit', 'land_use_code')),
    CONSTRAINT ck_gda_master_activation_business_key
        CHECK (business_key ~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$'),
    CONSTRAINT ck_gda_master_activation_version
        CHECK (activation_version >= 1),
    CONSTRAINT ck_gda_master_activator
        CHECK (activated_by ~ '^(human|workload|agent):[^[:space:]]{1,128}$'),
    CONSTRAINT ck_gda_master_activation_reason
        CHECK (NULLIF(btrim(activation_reason), '') IS NOT NULL)
);

CREATE TABLE IF NOT EXISTS gda_control.master_data_event (
    tenant_id TEXT NOT NULL,
    master_event_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    subject_ref TEXT NOT NULL,
    subject_fingerprint CHAR(64) NOT NULL,
    event_type TEXT NOT NULL,
    approval_case_ref TEXT,
    actor_subject TEXT NOT NULL,
    reason TEXT NOT NULL,
    details JSONB NOT NULL DEFAULT '{}'::jsonb,
    occurred_at TIMESTAMPTZ NOT NULL,
    CONSTRAINT uq_gda_master_event_tenant_id
        UNIQUE (tenant_id, master_event_id),
    CONSTRAINT fk_gda_master_event_approval
        FOREIGN KEY (tenant_id, approval_case_ref)
        REFERENCES gda_control.approval_case(tenant_id, approval_case_ref),
    CONSTRAINT ck_gda_master_event_subject CHECK (
        subject_ref ~ '^gda://[a-z0-9][a-z0-9._-]{0,63}/(master_source_record|master_match|master_entity)/[a-z0-9][a-z0-9._-]{0,127}$'
        AND split_part(subject_ref, '/', 3) = tenant_id
    ),
    CONSTRAINT ck_gda_master_event_fingerprint
        CHECK (subject_fingerprint ~ '^[0-9a-f]{64}$'),
    CONSTRAINT ck_gda_master_event_type CHECK (
        event_type IN (
            'source_observed', 'match_proposed',
            'version_staged', 'version_activated'
        )
    ),
    CONSTRAINT ck_gda_master_event_approval_binding CHECK (
        (event_type = 'version_activated' AND approval_case_ref IS NOT NULL)
        OR (event_type <> 'version_activated' AND approval_case_ref IS NULL)
    ),
    CONSTRAINT ck_gda_master_event_actor
        CHECK (actor_subject ~ '^(human|workload|agent):[^[:space:]]{1,128}$'),
    CONSTRAINT ck_gda_master_event_reason
        CHECK (NULLIF(btrim(reason), '') IS NOT NULL),
    CONSTRAINT ck_gda_master_event_details
        CHECK (jsonb_typeof(details) = 'object')
);

CREATE INDEX IF NOT EXISTS idx_gda_master_event_subject
    ON gda_control.master_data_event(
        tenant_id, subject_ref, occurred_at, master_event_id
    );

CREATE OR REPLACE FUNCTION gda_control.observe_master_source_record(
    p_tenant_id TEXT,
    p_source_record_ref TEXT,
    p_domain TEXT,
    p_source_system_ref TEXT,
    p_source_record_id TEXT,
    p_source_revision TEXT,
    p_business_key TEXT,
    p_display_name TEXT,
    p_parent_business_key TEXT,
    p_attributes JSONB,
    p_observed_by TEXT,
    p_observed_at TIMESTAMPTZ
)
RETURNS TEXT
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, gda_control, public
SET row_security = on
AS $$
DECLARE
    v_document JSONB;
    v_fingerprint TEXT;
    v_stored gda_control.master_source_record%ROWTYPE;
    v_inserted BOOLEAN := FALSE;
BEGIN
    IF gda_control.current_tenant() IS NULL
       OR p_tenant_id IS DISTINCT FROM gda_control.current_tenant() THEN
        RAISE EXCEPTION 'master source tenant context is missing or mismatched'
            USING ERRCODE = '42501';
    END IF;
    IF p_source_record_ref !~ '^gda://[a-z0-9][a-z0-9._-]{0,63}/master_source_record/[a-z0-9][a-z0-9._-]{0,127}$'
       OR split_part(p_source_record_ref, '/', 3) <> p_tenant_id
       OR p_domain NOT IN ('administrative_unit', 'land_use_code')
       OR p_source_system_ref !~ '^gda://[a-z0-9][a-z0-9._-]{0,63}/[a-z][a-z0-9_-]{1,31}/[a-z0-9][a-z0-9._-]{0,127}$'
       OR split_part(p_source_system_ref, '/', 3) <> p_tenant_id
       OR NULLIF(btrim(p_source_record_id), '') IS NULL
       OR octet_length(p_source_record_id) > 1024
       OR p_source_revision !~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$'
       OR p_business_key !~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$'
       OR (p_parent_business_key IS NOT NULL
           AND p_parent_business_key !~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$')
       OR NULLIF(btrim(p_display_name), '') IS NULL
       OR octet_length(p_display_name) > 1024
       OR jsonb_typeof(p_attributes) <> 'object'
       OR octet_length(p_attributes::text) > 262144
       OR p_observed_by !~ '^(human|workload|agent):[^[:space:]]{1,128}$'
       OR p_observed_at IS NULL THEN
        RAISE EXCEPTION 'master source identity or evidence is invalid'
            USING ERRCODE = '22023';
    END IF;

    v_document := jsonb_build_object(
        'schema_id', 'gda.master_source_record.v1',
        'tenant_id', p_tenant_id,
        'source_record_ref', p_source_record_ref,
        'domain', p_domain,
        'source_system_ref', p_source_system_ref,
        'source_record_id', p_source_record_id,
        'source_revision', p_source_revision,
        'business_key', p_business_key,
        'display_name', p_display_name,
        'parent_business_key', p_parent_business_key,
        'attributes', p_attributes,
        'observed_by', p_observed_by,
        'observed_at', p_observed_at
    );
    v_fingerprint := encode(
        public.digest(convert_to(v_document::text, 'UTF8'), 'sha256'), 'hex'
    );

    INSERT INTO gda_control.master_source_record (
        tenant_id, source_record_ref, domain, source_system_ref,
        source_record_id, source_revision, business_key, display_name,
        parent_business_key, attributes, record_fingerprint,
        observed_by, observed_at
    ) VALUES (
        p_tenant_id, p_source_record_ref, p_domain, p_source_system_ref,
        p_source_record_id, p_source_revision, p_business_key, p_display_name,
        p_parent_business_key, p_attributes, v_fingerprint,
        p_observed_by, p_observed_at
    )
    ON CONFLICT (tenant_id, source_record_ref) DO NOTHING
    RETURNING TRUE INTO v_inserted;

    IF NOT COALESCE(v_inserted, FALSE) THEN
        SELECT * INTO v_stored
        FROM gda_control.master_source_record
        WHERE tenant_id = p_tenant_id
          AND source_record_ref = p_source_record_ref;
        IF NOT FOUND
           OR v_stored.domain IS DISTINCT FROM p_domain
           OR v_stored.source_system_ref IS DISTINCT FROM p_source_system_ref
           OR v_stored.source_record_id IS DISTINCT FROM p_source_record_id
           OR v_stored.source_revision IS DISTINCT FROM p_source_revision
           OR v_stored.business_key IS DISTINCT FROM p_business_key
           OR v_stored.display_name IS DISTINCT FROM p_display_name
           OR v_stored.parent_business_key IS DISTINCT FROM p_parent_business_key
           OR v_stored.attributes IS DISTINCT FROM p_attributes
           OR v_stored.observed_by IS DISTINCT FROM p_observed_by THEN
            RAISE EXCEPTION 'master source revision already has different evidence'
                USING ERRCODE = '40001';
        END IF;
        RETURN v_stored.record_fingerprint;
    END IF;

    INSERT INTO gda_control.master_data_event (
        tenant_id, subject_ref, subject_fingerprint, event_type,
        approval_case_ref, actor_subject, reason, details, occurred_at
    ) VALUES (
        p_tenant_id, p_source_record_ref, v_fingerprint, 'source_observed',
        NULL, p_observed_by, 'observe immutable master source revision',
        jsonb_build_object(
            'domain', p_domain,
            'source_system_ref', p_source_system_ref,
            'source_record_id', p_source_record_id,
            'source_revision', p_source_revision,
            'business_key', p_business_key
        ), p_observed_at
    );
    RETURN v_fingerprint;
END;
$$;

CREATE OR REPLACE FUNCTION gda_control.propose_master_match_candidate(
    p_tenant_id TEXT,
    p_match_candidate_ref TEXT,
    p_source_record_ref TEXT,
    p_candidate_entity_ref TEXT,
    p_candidate_version_ref TEXT,
    p_candidate_fingerprint TEXT,
    p_algorithm_version TEXT,
    p_confidence_basis_points INTEGER,
    p_disposition TEXT,
    p_evidence JSONB,
    p_proposed_by TEXT,
    p_proposed_at TIMESTAMPTZ
)
RETURNS TEXT
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, gda_control, public
SET row_security = on
AS $$
DECLARE
    v_source gda_control.master_source_record%ROWTYPE;
    v_version gda_control.master_entity_version%ROWTYPE;
    v_active gda_control.master_entity_activation%ROWTYPE;
    v_document JSONB;
    v_fingerprint TEXT;
    v_stored gda_control.master_match_candidate%ROWTYPE;
    v_inserted BOOLEAN := FALSE;
BEGIN
    IF gda_control.current_tenant() IS NULL
       OR p_tenant_id IS DISTINCT FROM gda_control.current_tenant() THEN
        RAISE EXCEPTION 'master match tenant context is missing or mismatched'
            USING ERRCODE = '42501';
    END IF;
    IF p_match_candidate_ref !~ '^gda://[a-z0-9][a-z0-9._-]{0,63}/master_match/[a-z0-9][a-z0-9._-]{0,127}$'
       OR split_part(p_match_candidate_ref, '/', 3) <> p_tenant_id
       OR p_candidate_entity_ref !~ '^gda://[a-z0-9][a-z0-9._-]{0,63}/master_entity/[a-z0-9][a-z0-9._-]{0,127}$'
       OR split_part(p_candidate_entity_ref, '/', 3) <> p_tenant_id
       OR p_candidate_fingerprint !~ '^[0-9a-f]{64}$'
       OR p_algorithm_version <> 'master-match-v1'
       OR p_confidence_basis_points NOT BETWEEN 0 AND 10000
       OR p_disposition NOT IN ('recommended', 'review_required', 'conflict')
       OR jsonb_typeof(p_evidence) <> 'object'
       OR octet_length(p_evidence::text) > 65536
       OR p_proposed_by !~ '^(workload|agent):[^[:space:]]{1,128}$'
       OR p_proposed_at IS NULL THEN
        RAISE EXCEPTION 'master match identity, score or evidence is invalid'
            USING ERRCODE = '22023';
    END IF;

    SELECT * INTO v_source
    FROM gda_control.master_source_record
    WHERE tenant_id = p_tenant_id
      AND source_record_ref = p_source_record_ref;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'master source record not found' USING ERRCODE = 'P0002';
    END IF;
    SELECT * INTO v_version
    FROM gda_control.master_entity_version
    WHERE tenant_id = p_tenant_id
      AND entity_version_ref = p_candidate_version_ref
      AND entity_fingerprint = p_candidate_fingerprint;
    IF NOT FOUND
       OR v_version.entity_ref <> p_candidate_entity_ref
       OR v_version.domain <> v_source.domain THEN
        RAISE EXCEPTION 'master match target does not bind the source domain'
            USING ERRCODE = '23514';
    END IF;
    SELECT * INTO v_active
    FROM gda_control.master_entity_activation
    WHERE tenant_id = p_tenant_id
      AND entity_ref = p_candidate_entity_ref;
    IF NOT FOUND
       OR v_active.active_version_ref <> p_candidate_version_ref
       OR v_active.active_fingerprint <> p_candidate_fingerprint THEN
        RAISE EXCEPTION 'master match target is not the exact active version'
            USING ERRCODE = '23514';
    END IF;

    v_document := jsonb_build_object(
        'tenant_id', p_tenant_id,
        'match_candidate_ref', p_match_candidate_ref,
        'source_record_ref', p_source_record_ref,
        'candidate_entity_ref', p_candidate_entity_ref,
        'candidate_version_ref', p_candidate_version_ref,
        'candidate_fingerprint', p_candidate_fingerprint,
        'algorithm_version', p_algorithm_version,
        'confidence_basis_points', p_confidence_basis_points,
        'disposition', p_disposition,
        'evidence', p_evidence,
        'proposed_by', p_proposed_by,
        'proposed_at', p_proposed_at
    );
    v_fingerprint := encode(
        public.digest(convert_to(v_document::text, 'UTF8'), 'sha256'), 'hex'
    );

    INSERT INTO gda_control.master_match_candidate (
        tenant_id, match_candidate_ref, source_record_ref,
        candidate_entity_ref, candidate_version_ref, candidate_fingerprint,
        algorithm_version, confidence_basis_points, disposition, evidence,
        proposal_fingerprint, proposed_by, proposed_at
    ) VALUES (
        p_tenant_id, p_match_candidate_ref, p_source_record_ref,
        p_candidate_entity_ref, p_candidate_version_ref, p_candidate_fingerprint,
        p_algorithm_version, p_confidence_basis_points, p_disposition, p_evidence,
        v_fingerprint, p_proposed_by, p_proposed_at
    )
    ON CONFLICT (tenant_id, match_candidate_ref) DO NOTHING
    RETURNING TRUE INTO v_inserted;

    IF NOT COALESCE(v_inserted, FALSE) THEN
        SELECT * INTO v_stored
        FROM gda_control.master_match_candidate
        WHERE tenant_id = p_tenant_id
          AND match_candidate_ref = p_match_candidate_ref;
        IF NOT FOUND
           OR v_stored.source_record_ref <> p_source_record_ref
           OR v_stored.candidate_entity_ref <> p_candidate_entity_ref
           OR v_stored.candidate_version_ref <> p_candidate_version_ref
           OR v_stored.candidate_fingerprint <> p_candidate_fingerprint
           OR v_stored.algorithm_version <> p_algorithm_version
           OR v_stored.confidence_basis_points <> p_confidence_basis_points
           OR v_stored.disposition <> p_disposition
           OR v_stored.evidence IS DISTINCT FROM p_evidence
           OR v_stored.proposed_by <> p_proposed_by THEN
            RAISE EXCEPTION 'master match identity already has different evidence'
                USING ERRCODE = '40001';
        END IF;
        RETURN v_stored.proposal_fingerprint;
    END IF;

    INSERT INTO gda_control.master_data_event (
        tenant_id, subject_ref, subject_fingerprint, event_type,
        approval_case_ref, actor_subject, reason, details, occurred_at
    ) VALUES (
        p_tenant_id, p_match_candidate_ref, v_fingerprint, 'match_proposed',
        NULL, p_proposed_by, 'propose explainable master match candidate',
        jsonb_build_object(
            'source_record_ref', p_source_record_ref,
            'candidate_entity_ref', p_candidate_entity_ref,
            'candidate_version_ref', p_candidate_version_ref,
            'confidence_basis_points', p_confidence_basis_points,
            'disposition', p_disposition,
            'algorithm_version', p_algorithm_version
        ), p_proposed_at
    );
    RETURN v_fingerprint;
END;
$$;

CREATE OR REPLACE FUNCTION gda_control.stage_master_entity_version(
    p_tenant_id TEXT,
    p_entity_ref TEXT,
    p_entity_version_ref TEXT,
    p_entity_version INTEGER,
    p_domain TEXT,
    p_business_key TEXT,
    p_canonical_name TEXT,
    p_parent_entity_ref TEXT,
    p_attributes JSONB,
    p_source_record_refs JSONB,
    p_match_candidate_refs JSONB,
    p_valid_from DATE,
    p_valid_to DATE,
    p_owner_subject TEXT,
    p_created_by TEXT,
    p_creation_reason TEXT,
    p_created_at TIMESTAMPTZ
)
RETURNS TEXT
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, gda_control, public
SET row_security = on
AS $$
DECLARE
    v_document JSONB;
    v_fingerprint TEXT;
    v_stored gda_control.master_entity_version%ROWTYPE;
    v_inserted BOOLEAN := FALSE;
    v_source_count INTEGER;
    v_match_count INTEGER;
BEGIN
    IF gda_control.current_tenant() IS NULL
       OR p_tenant_id IS DISTINCT FROM gda_control.current_tenant() THEN
        RAISE EXCEPTION 'master entity tenant context is missing or mismatched'
            USING ERRCODE = '42501';
    END IF;
    IF p_entity_ref !~ '^gda://[a-z0-9][a-z0-9._-]{0,63}/master_entity/[a-z0-9][a-z0-9._-]{0,127}$'
       OR split_part(p_entity_ref, '/', 3) <> p_tenant_id
       OR p_entity_version NOT BETWEEN 1 AND 1000000
       OR p_entity_version_ref <> p_entity_ref || '.v' || p_entity_version::text
       OR p_domain NOT IN ('administrative_unit', 'land_use_code')
       OR p_business_key !~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$'
       OR NULLIF(btrim(p_canonical_name), '') IS NULL
       OR octet_length(p_canonical_name) > 1024
       OR (p_parent_entity_ref IS NOT NULL AND (
            p_parent_entity_ref !~ '^gda://[a-z0-9][a-z0-9._-]{0,63}/master_entity/[a-z0-9][a-z0-9._-]{0,127}$'
            OR split_part(p_parent_entity_ref, '/', 3) <> p_tenant_id
            OR p_parent_entity_ref = p_entity_ref
       ))
       OR jsonb_typeof(p_attributes) <> 'object'
       OR octet_length(p_attributes::text) > 262144
       OR p_valid_from IS NULL
       OR (p_valid_to IS NOT NULL AND p_valid_to <= p_valid_from)
       OR p_owner_subject !~ '^(human|team):[^[:space:]]{1,128}$'
       OR p_created_by !~ '^(human|workload|agent):[^[:space:]]{1,128}$'
       OR NULLIF(btrim(p_creation_reason), '') IS NULL
       OR p_created_at IS NULL THEN
        RAISE EXCEPTION 'master entity identity, validity or provenance is invalid'
            USING ERRCODE = '22023';
    END IF;
    IF jsonb_typeof(p_source_record_refs) <> 'array'
       OR jsonb_array_length(p_source_record_refs) NOT BETWEEN 1 AND 100
       OR jsonb_typeof(p_match_candidate_refs) <> 'array'
       OR jsonb_array_length(p_match_candidate_refs) NOT BETWEEN 0 AND 100
       OR EXISTS (
            SELECT 1 FROM jsonb_array_elements(p_source_record_refs) item(value)
            WHERE jsonb_typeof(value) <> 'string'
       )
       OR EXISTS (
            SELECT 1 FROM jsonb_array_elements(p_match_candidate_refs) item(value)
            WHERE jsonb_typeof(value) <> 'string'
       )
       OR (
            SELECT COUNT(*) <> COUNT(DISTINCT value)
                OR array_agg(value) IS DISTINCT FROM array_agg(value ORDER BY value)
            FROM jsonb_array_elements_text(p_source_record_refs) item(value)
       )
       OR (
            SELECT COUNT(*) <> COUNT(DISTINCT value)
                OR array_agg(value) IS DISTINCT FROM array_agg(value ORDER BY value)
            FROM jsonb_array_elements_text(p_match_candidate_refs) item(value)
       ) THEN
        RAISE EXCEPTION 'master entity evidence references must be sorted unique arrays'
            USING ERRCODE = '22023';
    END IF;

    SELECT COUNT(*) INTO v_source_count
    FROM gda_control.master_source_record source
    JOIN jsonb_array_elements_text(p_source_record_refs) requested(ref)
      ON source.source_record_ref = requested.ref
    WHERE source.tenant_id = p_tenant_id
      AND source.domain = p_domain;
    IF v_source_count <> jsonb_array_length(p_source_record_refs) THEN
        RAISE EXCEPTION 'master entity source evidence is missing or cross-domain'
            USING ERRCODE = '23514';
    END IF;

    SELECT COUNT(*) INTO v_match_count
    FROM gda_control.master_match_candidate candidate
    JOIN jsonb_array_elements_text(p_match_candidate_refs) requested(ref)
      ON candidate.match_candidate_ref = requested.ref
    WHERE candidate.tenant_id = p_tenant_id
      AND candidate.candidate_entity_ref = p_entity_ref
      AND p_source_record_refs ? candidate.source_record_ref;
    IF v_match_count <> jsonb_array_length(p_match_candidate_refs) THEN
        RAISE EXCEPTION 'master entity match evidence is missing or mismatched'
            USING ERRCODE = '23514';
    END IF;
    IF p_parent_entity_ref IS NOT NULL AND NOT EXISTS (
        SELECT 1 FROM gda_control.master_entity_activation
        WHERE tenant_id = p_tenant_id
          AND entity_ref = p_parent_entity_ref
          AND domain = p_domain
    ) THEN
        RAISE EXCEPTION 'master entity parent must be active in the same domain'
            USING ERRCODE = '23514';
    END IF;

    v_document := jsonb_build_object(
        'schema_id', 'gda.master_entity_version.v1',
        'tenant_id', p_tenant_id,
        'entity_ref', p_entity_ref,
        'entity_version_ref', p_entity_version_ref,
        'version', p_entity_version,
        'domain', p_domain,
        'business_key', p_business_key,
        'canonical_name', p_canonical_name,
        'parent_entity_ref', p_parent_entity_ref,
        'attributes', p_attributes,
        'source_record_refs', p_source_record_refs,
        'match_candidate_refs', p_match_candidate_refs,
        'valid_from', p_valid_from,
        'valid_to', p_valid_to,
        'owner_subject', p_owner_subject,
        'created_by', p_created_by,
        'creation_reason', p_creation_reason,
        'created_at', p_created_at
    );
    v_fingerprint := encode(
        public.digest(convert_to(v_document::text, 'UTF8'), 'sha256'), 'hex'
    );

    INSERT INTO gda_control.master_entity_version (
        tenant_id, entity_ref, entity_version_ref, entity_version,
        domain, business_key, canonical_name, parent_entity_ref, attributes,
        source_record_refs, match_candidate_refs, valid_from, valid_to,
        owner_subject, entity_fingerprint, created_by, creation_reason, created_at
    ) VALUES (
        p_tenant_id, p_entity_ref, p_entity_version_ref, p_entity_version,
        p_domain, p_business_key, p_canonical_name, p_parent_entity_ref, p_attributes,
        p_source_record_refs, p_match_candidate_refs, p_valid_from, p_valid_to,
        p_owner_subject, v_fingerprint, p_created_by, p_creation_reason, p_created_at
    )
    ON CONFLICT (tenant_id, entity_version_ref) DO NOTHING
    RETURNING TRUE INTO v_inserted;

    IF NOT COALESCE(v_inserted, FALSE) THEN
        SELECT * INTO v_stored
        FROM gda_control.master_entity_version
        WHERE tenant_id = p_tenant_id
          AND entity_version_ref = p_entity_version_ref;
        IF NOT FOUND
           OR v_stored.entity_ref <> p_entity_ref
           OR v_stored.entity_version <> p_entity_version
           OR v_stored.domain <> p_domain
           OR v_stored.business_key <> p_business_key
           OR v_stored.canonical_name <> p_canonical_name
           OR v_stored.parent_entity_ref IS DISTINCT FROM p_parent_entity_ref
           OR v_stored.attributes IS DISTINCT FROM p_attributes
           OR v_stored.source_record_refs IS DISTINCT FROM p_source_record_refs
           OR v_stored.match_candidate_refs IS DISTINCT FROM p_match_candidate_refs
           OR v_stored.valid_from <> p_valid_from
           OR v_stored.valid_to IS DISTINCT FROM p_valid_to
           OR v_stored.owner_subject <> p_owner_subject
           OR v_stored.created_by <> p_created_by
           OR v_stored.creation_reason <> p_creation_reason THEN
            RAISE EXCEPTION 'master entity version already has different evidence'
                USING ERRCODE = '40001';
        END IF;
        RETURN v_stored.entity_fingerprint;
    END IF;

    INSERT INTO gda_control.master_data_event (
        tenant_id, subject_ref, subject_fingerprint, event_type,
        approval_case_ref, actor_subject, reason, details, occurred_at
    ) VALUES (
        p_tenant_id, p_entity_version_ref, v_fingerprint, 'version_staged',
        NULL, p_created_by, p_creation_reason,
        jsonb_build_object(
            'entity_ref', p_entity_ref,
            'version', p_entity_version,
            'domain', p_domain,
            'business_key', p_business_key,
            'source_record_refs', p_source_record_refs,
            'match_candidate_refs', p_match_candidate_refs
        ), p_created_at
    );
    RETURN v_fingerprint;
END;
$$;

CREATE OR REPLACE FUNCTION gda_control.guard_master_activation_mutation()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    IF COALESCE(current_setting('gda.master_activation_allowed', true), '') <> '1' THEN
        RAISE EXCEPTION 'use gda_control.activate_master_entity_version()'
            USING ERRCODE = '55000';
    END IF;
    IF TG_OP = 'UPDATE' AND (
        NEW.tenant_id IS DISTINCT FROM OLD.tenant_id
        OR NEW.entity_ref IS DISTINCT FROM OLD.entity_ref
        OR NEW.activation_version <> OLD.activation_version + 1
    ) THEN
        RAISE EXCEPTION 'master activation identity or CAS sequence is invalid'
            USING ERRCODE = '40001';
    END IF;
    RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION gda_control.activate_master_entity_version(
    p_tenant_id TEXT,
    p_entity_version_ref TEXT,
    p_entity_fingerprint TEXT,
    p_approval_case_ref TEXT,
    p_expected_activation_version INTEGER,
    p_actor_subject TEXT,
    p_reason TEXT
)
RETURNS INTEGER
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, gda_control
SET row_security = on
AS $$
DECLARE
    v_version gda_control.master_entity_version%ROWTYPE;
    v_activation gda_control.master_entity_activation%ROWTYPE;
    v_approval gda_control.approval_case%ROWTYPE;
    v_new_version INTEGER;
    v_now TIMESTAMPTZ;
BEGIN
    IF gda_control.current_tenant() IS NULL
       OR p_tenant_id IS DISTINCT FROM gda_control.current_tenant() THEN
        RAISE EXCEPTION 'master activation tenant context is missing or mismatched'
            USING ERRCODE = '42501';
    END IF;
    IF p_entity_version_ref !~ '^gda://[a-z0-9][a-z0-9._-]{0,63}/master_entity/[a-z0-9][a-z0-9._-]{0,127}\.v[1-9][0-9]*$'
       OR split_part(p_entity_version_ref, '/', 3) <> p_tenant_id
       OR p_entity_fingerprint !~ '^[0-9a-f]{64}$'
       OR p_approval_case_ref !~ '^gda://[a-z0-9][a-z0-9._-]{0,63}/approval_case/[a-z0-9][a-z0-9._-]{0,127}$'
       OR split_part(p_approval_case_ref, '/', 3) <> p_tenant_id
       OR p_expected_activation_version < 0
       OR p_actor_subject !~ '^(human|workload|agent):[^[:space:]]{1,128}$'
       OR NULLIF(btrim(p_reason), '') IS NULL THEN
        RAISE EXCEPTION 'master activation identity, CAS, actor or reason is invalid'
            USING ERRCODE = '22023';
    END IF;

    SELECT * INTO v_version
    FROM gda_control.master_entity_version
    WHERE tenant_id = p_tenant_id
      AND entity_version_ref = p_entity_version_ref;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'master entity version not found' USING ERRCODE = 'P0002';
    END IF;
    IF v_version.entity_fingerprint <> p_entity_fingerprint THEN
        RAISE EXCEPTION 'master entity fingerprint mismatch' USING ERRCODE = '23514';
    END IF;
    v_now := clock_timestamp();
    IF v_version.valid_from > v_now::date
       OR (v_version.valid_to IS NOT NULL AND v_version.valid_to <= v_now::date) THEN
        RAISE EXCEPTION 'master entity version is outside its business validity'
            USING ERRCODE = '23514';
    END IF;

    SELECT * INTO v_activation
    FROM gda_control.master_entity_activation
    WHERE tenant_id = p_tenant_id
      AND entity_ref = v_version.entity_ref
    FOR UPDATE;
    IF FOUND
       AND v_activation.active_version_ref = p_entity_version_ref
       AND v_activation.active_fingerprint = p_entity_fingerprint
       AND v_activation.approval_case_ref = p_approval_case_ref THEN
        RETURN v_activation.activation_version;
    END IF;
    IF (NOT FOUND AND p_expected_activation_version <> 0)
       OR (FOUND AND v_activation.activation_version <> p_expected_activation_version) THEN
        RAISE EXCEPTION 'master activation version conflict' USING ERRCODE = '40001';
    END IF;

    SELECT * INTO v_approval
    FROM gda_control.approval_case
    WHERE tenant_id = p_tenant_id
      AND approval_case_ref = p_approval_case_ref;
    IF NOT FOUND
       OR v_approval.status <> 'approved'
       OR v_approval.action <> 'master_data.entity.activate'
       OR v_approval.target_resource_urn <> p_entity_version_ref
       OR v_approval.target_fingerprint <> p_entity_fingerprint
       OR v_approval.decided_by !~ '^human:[^[:space:]]+$'
       OR v_approval.decided_at IS NULL
       OR v_now >= v_approval.expires_at THEN
        RAISE EXCEPTION 'ApprovalCase does not authorize this master activation'
            USING ERRCODE = '23514';
    END IF;

    IF v_version.parent_entity_ref IS NOT NULL AND EXISTS (
        WITH RECURSIVE ancestors(entity_ref, parent_entity_ref, depth) AS (
            SELECT active.entity_ref, parent.parent_entity_ref, 1
            FROM gda_control.master_entity_activation active
            JOIN gda_control.master_entity_version parent
              ON parent.tenant_id = active.tenant_id
             AND parent.entity_version_ref = active.active_version_ref
             AND parent.entity_fingerprint = active.active_fingerprint
            WHERE active.tenant_id = p_tenant_id
              AND active.entity_ref = v_version.parent_entity_ref
            UNION ALL
            SELECT active.entity_ref, parent.parent_entity_ref, ancestors.depth + 1
            FROM ancestors
            JOIN gda_control.master_entity_activation active
              ON active.tenant_id = p_tenant_id
             AND active.entity_ref = ancestors.parent_entity_ref
            JOIN gda_control.master_entity_version parent
              ON parent.tenant_id = active.tenant_id
             AND parent.entity_version_ref = active.active_version_ref
             AND parent.entity_fingerprint = active.active_fingerprint
            WHERE ancestors.depth < 64
        )
        SELECT 1 FROM ancestors WHERE entity_ref = v_version.entity_ref
    ) THEN
        RAISE EXCEPTION 'master entity hierarchy cycle detected'
            USING ERRCODE = '23514';
    END IF;

    v_new_version := COALESCE(v_activation.activation_version, 0) + 1;
    PERFORM set_config('gda.master_activation_allowed', '1', true);
    INSERT INTO gda_control.master_entity_activation (
        tenant_id, entity_ref, domain, business_key,
        active_version_ref, active_fingerprint, approval_case_ref,
        activation_version, activated_by, activation_reason, activated_at
    ) VALUES (
        p_tenant_id, v_version.entity_ref, v_version.domain, v_version.business_key,
        p_entity_version_ref, p_entity_fingerprint, p_approval_case_ref,
        v_new_version, p_actor_subject, p_reason, v_now
    )
    ON CONFLICT (tenant_id, entity_ref) DO UPDATE
    SET domain = EXCLUDED.domain,
        business_key = EXCLUDED.business_key,
        active_version_ref = EXCLUDED.active_version_ref,
        active_fingerprint = EXCLUDED.active_fingerprint,
        approval_case_ref = EXCLUDED.approval_case_ref,
        activation_version = EXCLUDED.activation_version,
        activated_by = EXCLUDED.activated_by,
        activation_reason = EXCLUDED.activation_reason,
        activated_at = EXCLUDED.activated_at;
    PERFORM set_config('gda.master_activation_allowed', '0', true);

    INSERT INTO gda_control.master_data_event (
        tenant_id, subject_ref, subject_fingerprint, event_type,
        approval_case_ref, actor_subject, reason, details, occurred_at
    ) VALUES (
        p_tenant_id, p_entity_version_ref, p_entity_fingerprint,
        'version_activated', p_approval_case_ref, p_actor_subject, p_reason,
        jsonb_build_object(
            'entity_ref', v_version.entity_ref,
            'domain', v_version.domain,
            'business_key', v_version.business_key,
            'activation_version', v_new_version,
            'valid_from', v_version.valid_from,
            'valid_to', v_version.valid_to
        ), v_now
    );
    RETURN v_new_version;
END;
$$;

DROP TRIGGER IF EXISTS trg_gda_master_source_immutable
    ON gda_control.master_source_record;
CREATE TRIGGER trg_gda_master_source_immutable
BEFORE UPDATE OR DELETE ON gda_control.master_source_record
FOR EACH ROW EXECUTE FUNCTION gda_control.reject_immutable_mutation();

DROP TRIGGER IF EXISTS trg_gda_master_version_immutable
    ON gda_control.master_entity_version;
CREATE TRIGGER trg_gda_master_version_immutable
BEFORE UPDATE OR DELETE ON gda_control.master_entity_version
FOR EACH ROW EXECUTE FUNCTION gda_control.reject_immutable_mutation();

DROP TRIGGER IF EXISTS trg_gda_master_match_immutable
    ON gda_control.master_match_candidate;
CREATE TRIGGER trg_gda_master_match_immutable
BEFORE UPDATE OR DELETE ON gda_control.master_match_candidate
FOR EACH ROW EXECUTE FUNCTION gda_control.reject_immutable_mutation();

DROP TRIGGER IF EXISTS trg_gda_master_activation_guard
    ON gda_control.master_entity_activation;
CREATE TRIGGER trg_gda_master_activation_guard
BEFORE INSERT OR UPDATE ON gda_control.master_entity_activation
FOR EACH ROW EXECUTE FUNCTION gda_control.guard_master_activation_mutation();

DROP TRIGGER IF EXISTS trg_gda_master_activation_delete_guard
    ON gda_control.master_entity_activation;
CREATE TRIGGER trg_gda_master_activation_delete_guard
BEFORE DELETE ON gda_control.master_entity_activation
FOR EACH ROW EXECUTE FUNCTION gda_control.reject_immutable_mutation();

DROP TRIGGER IF EXISTS trg_gda_master_event_immutable
    ON gda_control.master_data_event;
CREATE TRIGGER trg_gda_master_event_immutable
BEFORE UPDATE OR DELETE ON gda_control.master_data_event
FOR EACH ROW EXECUTE FUNCTION gda_control.reject_immutable_mutation();

ALTER TABLE gda_control.master_source_record ENABLE ROW LEVEL SECURITY;
ALTER TABLE gda_control.master_source_record FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON gda_control.master_source_record;
CREATE POLICY tenant_isolation ON gda_control.master_source_record
USING (tenant_id = gda_control.current_tenant())
WITH CHECK (tenant_id = gda_control.current_tenant());

ALTER TABLE gda_control.master_entity_version ENABLE ROW LEVEL SECURITY;
ALTER TABLE gda_control.master_entity_version FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON gda_control.master_entity_version;
CREATE POLICY tenant_isolation ON gda_control.master_entity_version
USING (tenant_id = gda_control.current_tenant())
WITH CHECK (tenant_id = gda_control.current_tenant());

ALTER TABLE gda_control.master_match_candidate ENABLE ROW LEVEL SECURITY;
ALTER TABLE gda_control.master_match_candidate FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON gda_control.master_match_candidate;
CREATE POLICY tenant_isolation ON gda_control.master_match_candidate
USING (tenant_id = gda_control.current_tenant())
WITH CHECK (tenant_id = gda_control.current_tenant());

ALTER TABLE gda_control.master_entity_activation ENABLE ROW LEVEL SECURITY;
ALTER TABLE gda_control.master_entity_activation FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON gda_control.master_entity_activation;
CREATE POLICY tenant_isolation ON gda_control.master_entity_activation
USING (tenant_id = gda_control.current_tenant())
WITH CHECK (tenant_id = gda_control.current_tenant());

ALTER TABLE gda_control.master_data_event ENABLE ROW LEVEL SECURITY;
ALTER TABLE gda_control.master_data_event FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON gda_control.master_data_event;
CREATE POLICY tenant_isolation ON gda_control.master_data_event
USING (tenant_id = gda_control.current_tenant())
WITH CHECK (tenant_id = gda_control.current_tenant());

REVOKE ALL ON TABLE gda_control.master_source_record
    FROM PUBLIC, gda_control_gateway;
REVOKE ALL ON TABLE gda_control.master_entity_version
    FROM PUBLIC, gda_control_gateway;
REVOKE ALL ON TABLE gda_control.master_match_candidate
    FROM PUBLIC, gda_control_gateway;
REVOKE ALL ON TABLE gda_control.master_entity_activation
    FROM PUBLIC, gda_control_gateway;
REVOKE ALL ON TABLE gda_control.master_data_event
    FROM PUBLIC, gda_control_gateway;
GRANT SELECT ON gda_control.master_source_record TO gda_control_gateway;
GRANT SELECT ON gda_control.master_entity_version TO gda_control_gateway;
GRANT SELECT ON gda_control.master_match_candidate TO gda_control_gateway;
GRANT SELECT ON gda_control.master_entity_activation TO gda_control_gateway;
GRANT SELECT ON gda_control.master_data_event TO gda_control_gateway;

REVOKE ALL ON FUNCTION gda_control.guard_master_activation_mutation()
    FROM PUBLIC;
REVOKE ALL ON FUNCTION gda_control.observe_master_source_record(
    TEXT, TEXT, TEXT, TEXT, TEXT, TEXT, TEXT, TEXT, TEXT,
    JSONB, TEXT, TIMESTAMPTZ
) FROM PUBLIC;
REVOKE ALL ON FUNCTION gda_control.propose_master_match_candidate(
    TEXT, TEXT, TEXT, TEXT, TEXT, TEXT, TEXT, INTEGER,
    TEXT, JSONB, TEXT, TIMESTAMPTZ
) FROM PUBLIC;
REVOKE ALL ON FUNCTION gda_control.stage_master_entity_version(
    TEXT, TEXT, TEXT, INTEGER, TEXT, TEXT, TEXT, TEXT,
    JSONB, JSONB, JSONB, DATE, DATE, TEXT, TEXT, TEXT, TIMESTAMPTZ
) FROM PUBLIC;
REVOKE ALL ON FUNCTION gda_control.activate_master_entity_version(
    TEXT, TEXT, TEXT, TEXT, INTEGER, TEXT, TEXT
) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION gda_control.observe_master_source_record(
    TEXT, TEXT, TEXT, TEXT, TEXT, TEXT, TEXT, TEXT, TEXT,
    JSONB, TEXT, TIMESTAMPTZ
) TO gda_control_gateway;
GRANT EXECUTE ON FUNCTION gda_control.propose_master_match_candidate(
    TEXT, TEXT, TEXT, TEXT, TEXT, TEXT, TEXT, INTEGER,
    TEXT, JSONB, TEXT, TIMESTAMPTZ
) TO gda_control_gateway;
GRANT EXECUTE ON FUNCTION gda_control.stage_master_entity_version(
    TEXT, TEXT, TEXT, INTEGER, TEXT, TEXT, TEXT, TEXT,
    JSONB, JSONB, JSONB, DATE, DATE, TEXT, TEXT, TEXT, TIMESTAMPTZ
) TO gda_control_gateway;
GRANT EXECUTE ON FUNCTION gda_control.activate_master_entity_version(
    TEXT, TEXT, TEXT, TEXT, INTEGER, TEXT, TEXT
) TO gda_control_gateway;
