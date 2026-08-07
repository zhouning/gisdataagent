-- 135: Canonical immutable metric definitions and approved active pointers.
--
-- Legacy metric registries remain read-compatible projections. This authority
-- is the only write path for newly governed metric definitions.

CREATE EXTENSION IF NOT EXISTS pgcrypto WITH SCHEMA public;

CREATE TABLE IF NOT EXISTS gda_control.metric_definition_version (
    tenant_id TEXT NOT NULL,
    metric_ref TEXT NOT NULL,
    metric_version_ref TEXT NOT NULL,
    definition_version INTEGER NOT NULL,
    definition_document JSONB NOT NULL,
    definition_fingerprint CHAR(64) NOT NULL,
    created_by TEXT NOT NULL,
    creation_reason TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (tenant_id, metric_version_ref),
    CONSTRAINT uq_gda_metric_definition_version_number
        UNIQUE (tenant_id, metric_ref, definition_version),
    CONSTRAINT uq_gda_metric_definition_fingerprint
        UNIQUE (tenant_id, metric_version_ref, definition_fingerprint),
    CONSTRAINT ck_gda_metric_definition_tenant
        CHECK (tenant_id ~ '^[a-z0-9][a-z0-9._-]{0,63}$'),
    CONSTRAINT ck_gda_metric_ref CHECK (
        metric_ref ~ '^gda://[a-z0-9][a-z0-9._-]{0,63}/metric_definition/[a-z0-9][a-z0-9._-]{0,127}$'
        AND split_part(metric_ref, '/', 3) = tenant_id
    ),
    CONSTRAINT ck_gda_metric_version_ref CHECK (
        metric_version_ref = metric_ref || '.v' || definition_version::text
    ),
    CONSTRAINT ck_gda_metric_definition_version
        CHECK (definition_version BETWEEN 1 AND 1000000),
    CONSTRAINT ck_gda_metric_definition_document CHECK (
        jsonb_typeof(definition_document) = 'object'
        AND definition_document->>'schema_id' = 'gda.metric_definition.v1'
        AND definition_document->>'canonical_name' ~ '^[a-z][a-z0-9_]{0,127}$'
        AND NULLIF(btrim(definition_document->>'display_name'), '') IS NOT NULL
        AND NULLIF(btrim(definition_document->>'description'), '') IS NOT NULL
        AND definition_document->>'domain' ~ '^[a-z][a-z0-9_]{0,127}$'
        AND definition_document->>'formula_language' = 'semantic_expression_v1'
        AND NULLIF(btrim(definition_document->>'formula_expression'), '') IS NOT NULL
        AND definition_document->>'value_type' IN (
            'integer', 'decimal', 'percentage', 'duration', 'currency'
        )
        AND NULLIF(btrim(definition_document->>'unit'), '') IS NOT NULL
        AND jsonb_typeof(definition_document->'aggregation') = 'object'
        AND jsonb_typeof(definition_document->'aliases') = 'array'
        AND jsonb_typeof(definition_document->'dimensions') = 'array'
        AND jsonb_typeof(definition_document->'measures') = 'array'
        AND jsonb_array_length(definition_document->'measures') BETWEEN 1 AND 100
        AND jsonb_typeof(definition_document->'source_bindings') = 'array'
        AND jsonb_array_length(definition_document->'source_bindings') BETWEEN 1 AND 100
        AND jsonb_typeof(definition_document->'dependency_version_refs') = 'array'
        AND jsonb_typeof(definition_document->'quality_policy') = 'object'
        AND jsonb_typeof(definition_document->'materialization_policy') = 'object'
        AND (
            definition_document->'time_semantics' = 'null'::jsonb
            OR jsonb_typeof(definition_document->'time_semantics') = 'object'
        )
        AND (
            definition_document->'spatial_semantics' = 'null'::jsonb
            OR jsonb_typeof(definition_document->'spatial_semantics') = 'object'
        )
        AND definition_document->>'null_policy' IN ('ignore', 'zero', 'error')
        AND definition_document->>'distinct_policy' IN (
            'not_applicable', 'exact', 'approximate'
        )
        AND definition_document->>'security_classification' IN (
            'public', 'internal', 'confidential', 'restricted'
        )
        AND definition_document->>'owner_subject' ~ '^(human|team):[^[:space:]]{1,128}$'
        AND definition_document->>'steward_subject' ~ '^(human|team):[^[:space:]]{1,128}$'
        AND definition_document->>'semantic_model_version_ref'
            ~ '^gda://[a-z0-9][a-z0-9._-]{0,63}/semantic_model/[a-z0-9][a-z0-9._-]{0,127}\.v[1-9][0-9]*$'
        AND split_part(
            definition_document->>'semantic_model_version_ref', '/', 3
        ) = tenant_id
    ),
    CONSTRAINT ck_gda_metric_definition_fingerprint
        CHECK (definition_fingerprint ~ '^[0-9a-f]{64}$'),
    CONSTRAINT ck_gda_metric_definition_creator
        CHECK (created_by ~ '^(human|workload|agent):[^[:space:]]{1,128}$'),
    CONSTRAINT ck_gda_metric_definition_reason
        CHECK (NULLIF(btrim(creation_reason), '') IS NOT NULL)
);

CREATE INDEX IF NOT EXISTS idx_gda_metric_definition_name
    ON gda_control.metric_definition_version(
        tenant_id, lower(definition_document->>'canonical_name'),
        definition_version DESC
    );
CREATE INDEX IF NOT EXISTS idx_gda_metric_definition_domain
    ON gda_control.metric_definition_version(
        tenant_id, (definition_document->>'domain'), definition_version DESC
    );
CREATE INDEX IF NOT EXISTS idx_gda_metric_definition_display_name
    ON gda_control.metric_definition_version(
        tenant_id, lower(definition_document->>'display_name')
    );

CREATE TABLE IF NOT EXISTS gda_control.metric_definition_activation (
    tenant_id TEXT NOT NULL,
    metric_ref TEXT NOT NULL,
    canonical_name TEXT NOT NULL,
    active_version_ref TEXT NOT NULL,
    active_fingerprint CHAR(64) NOT NULL,
    approval_case_ref TEXT NOT NULL,
    activation_version INTEGER NOT NULL,
    activated_by TEXT NOT NULL,
    activation_reason TEXT NOT NULL,
    activated_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (tenant_id, metric_ref),
    CONSTRAINT uq_gda_metric_active_canonical_name
        UNIQUE (tenant_id, canonical_name),
    CONSTRAINT fk_gda_metric_activation_version
        FOREIGN KEY (tenant_id, active_version_ref, active_fingerprint)
        REFERENCES gda_control.metric_definition_version(
            tenant_id, metric_version_ref, definition_fingerprint
        ),
    CONSTRAINT fk_gda_metric_activation_approval
        FOREIGN KEY (tenant_id, approval_case_ref)
        REFERENCES gda_control.approval_case(tenant_id, approval_case_ref),
    CONSTRAINT ck_gda_metric_activation_name
        CHECK (canonical_name ~ '^[a-z][a-z0-9_]{0,127}$'),
    CONSTRAINT ck_gda_metric_activation_version
        CHECK (activation_version >= 1),
    CONSTRAINT ck_gda_metric_activator
        CHECK (activated_by ~ '^(human|workload|agent):[^[:space:]]{1,128}$'),
    CONSTRAINT ck_gda_metric_activation_reason
        CHECK (NULLIF(btrim(activation_reason), '') IS NOT NULL)
);

CREATE TABLE IF NOT EXISTS gda_control.metric_definition_event (
    tenant_id TEXT NOT NULL,
    metric_event_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    metric_ref TEXT NOT NULL,
    metric_version_ref TEXT NOT NULL,
    definition_fingerprint CHAR(64) NOT NULL,
    event_type TEXT NOT NULL,
    approval_case_ref TEXT,
    actor_subject TEXT NOT NULL,
    reason TEXT NOT NULL,
    details JSONB NOT NULL DEFAULT '{}'::jsonb,
    occurred_at TIMESTAMPTZ NOT NULL,
    CONSTRAINT uq_gda_metric_event_tenant_id
        UNIQUE (tenant_id, metric_event_id),
    CONSTRAINT fk_gda_metric_event_version
        FOREIGN KEY (tenant_id, metric_version_ref, definition_fingerprint)
        REFERENCES gda_control.metric_definition_version(
            tenant_id, metric_version_ref, definition_fingerprint
        ),
    CONSTRAINT fk_gda_metric_event_approval
        FOREIGN KEY (tenant_id, approval_case_ref)
        REFERENCES gda_control.approval_case(tenant_id, approval_case_ref),
    CONSTRAINT ck_gda_metric_event_type
        CHECK (event_type IN ('staged', 'activated')),
    CONSTRAINT ck_gda_metric_event_approval_binding CHECK (
        (event_type = 'staged' AND approval_case_ref IS NULL)
        OR (event_type = 'activated' AND approval_case_ref IS NOT NULL)
    ),
    CONSTRAINT ck_gda_metric_event_actor
        CHECK (actor_subject ~ '^(human|workload|agent):[^[:space:]]{1,128}$'),
    CONSTRAINT ck_gda_metric_event_reason
        CHECK (NULLIF(btrim(reason), '') IS NOT NULL),
    CONSTRAINT ck_gda_metric_event_details
        CHECK (jsonb_typeof(details) = 'object')
);

CREATE INDEX IF NOT EXISTS idx_gda_metric_definition_event
    ON gda_control.metric_definition_event(
        tenant_id, metric_ref, occurred_at, metric_event_id
    );

CREATE OR REPLACE FUNCTION gda_control.guard_metric_activation_mutation()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    IF COALESCE(current_setting('gda.metric_activation_allowed', true), '') <> '1' THEN
        RAISE EXCEPTION 'use gda_control.activate_metric_definition_version()'
            USING ERRCODE = '55000';
    END IF;
    IF TG_OP = 'UPDATE' AND (
        NEW.tenant_id IS DISTINCT FROM OLD.tenant_id
        OR NEW.metric_ref IS DISTINCT FROM OLD.metric_ref
        OR NEW.activation_version <> OLD.activation_version + 1
    ) THEN
        RAISE EXCEPTION 'metric activation identity or CAS sequence is invalid'
            USING ERRCODE = '40001';
    END IF;
    RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION gda_control.stage_metric_definition_version(
    p_tenant_id TEXT,
    p_metric_ref TEXT,
    p_metric_version_ref TEXT,
    p_definition_version INTEGER,
    p_definition_document JSONB,
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
    v_stored gda_control.metric_definition_version%ROWTYPE;
    v_inserted BOOLEAN := FALSE;
    v_source JSONB;
    v_measure JSONB;
    v_dependency TEXT;
BEGIN
    IF gda_control.current_tenant() IS NULL
       OR p_tenant_id IS DISTINCT FROM gda_control.current_tenant() THEN
        RAISE EXCEPTION 'metric tenant context is missing or mismatched'
            USING ERRCODE = '42501';
    END IF;
    IF p_metric_ref IS NULL
       OR p_metric_ref !~ '^gda://[a-z0-9][a-z0-9._-]{0,63}/metric_definition/[a-z0-9][a-z0-9._-]{0,127}$'
       OR split_part(p_metric_ref, '/', 3) <> p_tenant_id
       OR p_definition_version NOT BETWEEN 1 AND 1000000
       OR p_metric_version_ref <> p_metric_ref || '.v' || p_definition_version::text
       OR p_created_by !~ '^(human|workload|agent):[^[:space:]]{1,128}$'
       OR NULLIF(btrim(p_creation_reason), '') IS NULL
       OR p_created_at IS NULL THEN
        RAISE EXCEPTION 'metric identity, version or provenance is invalid'
            USING ERRCODE = '22023';
    END IF;
    IF jsonb_typeof(p_definition_document) <> 'object'
       OR (
            SELECT array_agg(key ORDER BY key) IS DISTINCT FROM ARRAY[
                'aggregation', 'aliases', 'canonical_name',
                'dependency_version_refs', 'description', 'dimensions',
                'display_name', 'distinct_policy', 'domain',
                'formula_expression', 'formula_language',
                'materialization_policy', 'measures', 'null_policy',
                'owner_subject', 'quality_policy', 'schema_id',
                'security_classification', 'semantic_model_version_ref',
                'source_bindings', 'spatial_semantics', 'steward_subject',
                'time_semantics', 'unit', 'value_type'
            ]::text[]
            FROM jsonb_object_keys(p_definition_document) AS keys(key)
       )
       OR p_definition_document->>'schema_id' <> 'gda.metric_definition.v1'
       OR p_definition_document->>'canonical_name' !~ '^[a-z][a-z0-9_]{0,127}$'
       OR NULLIF(btrim(p_definition_document->>'display_name'), '') IS NULL
       OR NULLIF(btrim(p_definition_document->>'description'), '') IS NULL
       OR p_definition_document->>'domain' !~ '^[a-z][a-z0-9_]{0,127}$'
       OR p_definition_document->>'formula_language' <> 'semantic_expression_v1'
       OR NULLIF(btrim(p_definition_document->>'formula_expression'), '') IS NULL
       OR strpos(p_definition_document->>'formula_expression', ';') > 0
       OR p_definition_document->>'value_type' NOT IN (
            'integer', 'decimal', 'percentage', 'duration', 'currency'
       )
       OR NULLIF(btrim(p_definition_document->>'unit'), '') IS NULL
       OR jsonb_typeof(p_definition_document->'aggregation') <> 'object'
       OR jsonb_typeof(p_definition_document->'aliases') <> 'array'
       OR jsonb_typeof(p_definition_document->'dimensions') <> 'array'
       OR jsonb_typeof(p_definition_document->'measures') <> 'array'
       OR jsonb_array_length(p_definition_document->'measures') NOT BETWEEN 1 AND 100
       OR jsonb_typeof(p_definition_document->'source_bindings') <> 'array'
       OR jsonb_array_length(p_definition_document->'source_bindings') NOT BETWEEN 1 AND 100
       OR jsonb_typeof(p_definition_document->'dependency_version_refs') <> 'array'
       OR jsonb_typeof(p_definition_document->'quality_policy') <> 'object'
       OR jsonb_typeof(p_definition_document->'materialization_policy') <> 'object'
       OR p_definition_document->>'null_policy' NOT IN ('ignore', 'zero', 'error')
       OR p_definition_document->>'distinct_policy' NOT IN (
            'not_applicable', 'exact', 'approximate'
       )
       OR p_definition_document->>'security_classification' NOT IN (
            'public', 'internal', 'confidential', 'restricted'
       )
       OR p_definition_document->>'owner_subject' !~ '^(human|team):[^[:space:]]{1,128}$'
       OR p_definition_document->>'steward_subject' !~ '^(human|team):[^[:space:]]{1,128}$'
       OR p_definition_document->>'semantic_model_version_ref'
            !~ '^gda://[a-z0-9][a-z0-9._-]{0,63}/semantic_model/[a-z0-9][a-z0-9._-]{0,127}\.v[1-9][0-9]*$'
       OR split_part(
            p_definition_document->>'semantic_model_version_ref', '/', 3
       ) <> p_tenant_id THEN
        RAISE EXCEPTION 'metric definition document is invalid'
            USING ERRCODE = '22023';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM gda_control.metric_definition_version existing
        WHERE existing.tenant_id = p_tenant_id
          AND existing.metric_ref = p_metric_ref
          AND existing.definition_document->>'canonical_name'
              <> p_definition_document->>'canonical_name'
    ) THEN
        RAISE EXCEPTION 'metric canonical name cannot change across versions'
            USING ERRCODE = '23514';
    END IF;

    FOR v_source IN
        SELECT value FROM jsonb_array_elements(
            p_definition_document->'source_bindings'
        ) source(value)
    LOOP
        IF jsonb_typeof(v_source) <> 'object'
           OR (
                SELECT array_agg(key ORDER BY key) IS DISTINCT FROM ARRAY[
                    'data_product_version_id', 'output_resource_version_id',
                    'product_urn', 'version_key'
                ]::text[]
                FROM jsonb_object_keys(v_source) AS keys(key)
           )
           OR v_source->>'product_urn'
                !~ '^gda://[a-z0-9][a-z0-9._-]{0,63}/data_product/[a-z0-9][a-z0-9._-]{0,127}$'
           OR split_part(v_source->>'product_urn', '/', 3) <> p_tenant_id
           OR v_source->>'data_product_version_id'
                !~ '^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-5][0-9a-fA-F]{3}-[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}$'
           OR v_source->>'output_resource_version_id'
                !~ '^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-5][0-9a-fA-F]{3}-[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}$'
           OR v_source->>'version_key' !~ '^v[0-9]+\.[0-9]+\.[0-9]+$'
           OR NOT EXISTS (
                SELECT 1
                FROM gda_control.data_product_version product_version
                WHERE product_version.tenant_id = p_tenant_id
                  AND product_version.product_urn = v_source->>'product_urn'
                  AND product_version.data_product_version_id =
                      (v_source->>'data_product_version_id')::uuid
                  AND product_version.version_key = v_source->>'version_key'
                  AND product_version.output_resource_version_id =
                      (v_source->>'output_resource_version_id')::uuid
           ) THEN
            RAISE EXCEPTION 'metric source does not bind an immutable DataProductVersion'
                USING ERRCODE = '23514';
        END IF;
    END LOOP;

    FOR v_measure IN
        SELECT value FROM jsonb_array_elements(
            p_definition_document->'measures'
        ) measure(value)
    LOOP
        IF jsonb_typeof(v_measure) <> 'object'
           OR (
                SELECT array_agg(key ORDER BY key) IS DISTINCT FROM ARRAY[
                    'binding_name', 'measure_name', 'semantic_model_version_ref'
                ]::text[]
                FROM jsonb_object_keys(v_measure) AS keys(key)
           )
           OR v_measure->>'binding_name' !~ '^[a-z][a-z0-9_]{0,127}$'
           OR v_measure->>'measure_name' !~ '^[a-z][a-z0-9_]{0,127}$'
           OR v_measure->>'semantic_model_version_ref'
                !~ '^gda://[a-z0-9][a-z0-9._-]{0,63}/semantic_model/[a-z0-9][a-z0-9._-]{0,127}\.v[1-9][0-9]*$'
           OR split_part(
                v_measure->>'semantic_model_version_ref', '/', 3
           ) <> p_tenant_id THEN
            RAISE EXCEPTION 'metric measure binding is invalid'
                USING ERRCODE = '22023';
        END IF;
    END LOOP;

    FOR v_dependency IN
        SELECT value FROM jsonb_array_elements_text(
            p_definition_document->'dependency_version_refs'
        ) dependency(value)
    LOOP
        IF v_dependency
                !~ '^gda://[a-z0-9][a-z0-9._-]{0,63}/metric_definition/[a-z0-9][a-z0-9._-]{0,127}\.v[1-9][0-9]*$'
           OR split_part(v_dependency, '/', 3) <> p_tenant_id
           OR regexp_replace(v_dependency, '\.v[1-9][0-9]*$', '') = p_metric_ref
           OR NOT EXISTS (
                SELECT 1
                FROM gda_control.metric_definition_version dependency_version
                WHERE dependency_version.tenant_id = p_tenant_id
                  AND dependency_version.metric_version_ref = v_dependency
           ) THEN
            RAISE EXCEPTION 'metric dependency is missing, cross-tenant or cyclic'
                USING ERRCODE = '23514';
        END IF;
    END LOOP;

    v_document := jsonb_build_object(
        'tenant_id', p_tenant_id,
        'metric_ref', p_metric_ref,
        'metric_version_ref', p_metric_version_ref,
        'definition_version', p_definition_version,
        'definition', p_definition_document
    );
    v_fingerprint := encode(
        digest(convert_to(v_document::text, 'UTF8'), 'sha256'), 'hex'
    );

    INSERT INTO gda_control.metric_definition_version (
        tenant_id, metric_ref, metric_version_ref, definition_version,
        definition_document, definition_fingerprint,
        created_by, creation_reason, created_at
    ) VALUES (
        p_tenant_id, p_metric_ref, p_metric_version_ref, p_definition_version,
        p_definition_document, v_fingerprint,
        p_created_by, p_creation_reason, p_created_at
    )
    ON CONFLICT (tenant_id, metric_version_ref) DO NOTHING
    RETURNING TRUE INTO v_inserted;

    IF NOT COALESCE(v_inserted, FALSE) THEN
        SELECT * INTO v_stored
        FROM gda_control.metric_definition_version
        WHERE tenant_id = p_tenant_id
          AND metric_version_ref = p_metric_version_ref;
        IF NOT FOUND
           OR v_stored.metric_ref IS DISTINCT FROM p_metric_ref
           OR v_stored.definition_version IS DISTINCT FROM p_definition_version
           OR v_stored.definition_document IS DISTINCT FROM p_definition_document
           OR v_stored.created_by IS DISTINCT FROM p_created_by
           OR v_stored.creation_reason IS DISTINCT FROM p_creation_reason THEN
            RAISE EXCEPTION 'metric version identity already has different evidence'
                USING ERRCODE = '40001';
        END IF;
        RETURN v_stored.definition_fingerprint;
    END IF;

    INSERT INTO gda_control.metric_definition_event (
        tenant_id, metric_ref, metric_version_ref, definition_fingerprint,
        event_type, approval_case_ref, actor_subject, reason,
        details, occurred_at
    ) VALUES (
        p_tenant_id, p_metric_ref, p_metric_version_ref, v_fingerprint,
        'staged', NULL, p_created_by, p_creation_reason,
        jsonb_build_object(
            'definition_version', p_definition_version,
            'canonical_name', p_definition_document->>'canonical_name',
            'domain', p_definition_document->>'domain',
            'semantic_model_version_ref',
                p_definition_document->>'semantic_model_version_ref',
            'source_count',
                jsonb_array_length(p_definition_document->'source_bindings'),
            'dependency_count',
                jsonb_array_length(p_definition_document->'dependency_version_refs')
        ),
        p_created_at
    );
    RETURN v_fingerprint;
END;
$$;

CREATE OR REPLACE FUNCTION gda_control.activate_metric_definition_version(
    p_tenant_id TEXT,
    p_metric_version_ref TEXT,
    p_definition_fingerprint TEXT,
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
    v_definition gda_control.metric_definition_version%ROWTYPE;
    v_activation gda_control.metric_definition_activation%ROWTYPE;
    v_approval gda_control.approval_case%ROWTYPE;
    v_new_version INTEGER;
    v_now TIMESTAMPTZ;
BEGIN
    IF gda_control.current_tenant() IS NULL
       OR p_tenant_id IS DISTINCT FROM gda_control.current_tenant() THEN
        RAISE EXCEPTION 'metric tenant context is missing or mismatched'
            USING ERRCODE = '42501';
    END IF;
    IF p_metric_version_ref IS NULL
       OR p_metric_version_ref
            !~ '^gda://[a-z0-9][a-z0-9._-]{0,63}/metric_definition/[a-z0-9][a-z0-9._-]{0,127}\.v[1-9][0-9]*$'
       OR split_part(p_metric_version_ref, '/', 3) <> p_tenant_id
       OR p_definition_fingerprint !~ '^[0-9a-f]{64}$'
       OR p_approval_case_ref
            !~ '^gda://[a-z0-9][a-z0-9._-]{0,63}/approval_case/[a-z0-9][a-z0-9._-]{0,127}$'
       OR split_part(p_approval_case_ref, '/', 3) <> p_tenant_id
       OR p_expected_activation_version < 0
       OR p_actor_subject !~ '^(human|workload|agent):[^[:space:]]{1,128}$'
       OR NULLIF(btrim(p_reason), '') IS NULL THEN
        RAISE EXCEPTION 'metric activation identity, CAS, actor or reason is invalid'
            USING ERRCODE = '22023';
    END IF;

    SELECT * INTO v_definition
    FROM gda_control.metric_definition_version
    WHERE tenant_id = p_tenant_id
      AND metric_version_ref = p_metric_version_ref;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'metric definition version % not found', p_metric_version_ref
            USING ERRCODE = 'P0002';
    END IF;
    IF v_definition.definition_fingerprint <> p_definition_fingerprint THEN
        RAISE EXCEPTION 'metric definition fingerprint mismatch'
            USING ERRCODE = '23514';
    END IF;

    SELECT * INTO v_activation
    FROM gda_control.metric_definition_activation
    WHERE tenant_id = p_tenant_id
      AND metric_ref = v_definition.metric_ref
    FOR UPDATE;
    IF FOUND
       AND v_activation.active_version_ref = p_metric_version_ref
       AND v_activation.active_fingerprint = p_definition_fingerprint
       AND v_activation.approval_case_ref = p_approval_case_ref THEN
        RETURN v_activation.activation_version;
    END IF;
    IF (NOT FOUND AND p_expected_activation_version <> 0)
       OR (FOUND AND v_activation.activation_version <> p_expected_activation_version) THEN
        RAISE EXCEPTION 'metric activation version conflict'
            USING ERRCODE = '40001';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM jsonb_array_elements_text(
            v_definition.definition_document->'dependency_version_refs'
        ) dependency(version_ref)
        JOIN gda_control.metric_definition_version dependency_version
          ON dependency_version.tenant_id = p_tenant_id
         AND dependency_version.metric_version_ref = dependency.version_ref
        LEFT JOIN gda_control.metric_definition_activation dependency_activation
          ON dependency_activation.tenant_id = p_tenant_id
         AND dependency_activation.metric_ref = dependency_version.metric_ref
         AND dependency_activation.active_version_ref = dependency.version_ref
         AND dependency_activation.active_fingerprint =
             dependency_version.definition_fingerprint
        WHERE dependency_activation.metric_ref IS NULL
    ) THEN
        RAISE EXCEPTION 'metric dependencies must be active at their exact versions'
            USING ERRCODE = '23514';
    END IF;

    SELECT * INTO v_approval
    FROM gda_control.approval_case
    WHERE tenant_id = p_tenant_id
      AND approval_case_ref = p_approval_case_ref;
    v_now := clock_timestamp();
    IF NOT FOUND
       OR v_approval.status <> 'approved'
       OR v_approval.action <> 'metric_definition.activate'
       OR v_approval.target_resource_urn <> p_metric_version_ref
       OR v_approval.target_fingerprint <> p_definition_fingerprint
       OR v_approval.decided_by !~ '^human:[^[:space:]]+$'
       OR v_approval.decided_at IS NULL
       OR v_now >= v_approval.expires_at THEN
        RAISE EXCEPTION 'ApprovalCase does not authorize this metric activation'
            USING ERRCODE = '23514';
    END IF;

    v_new_version := COALESCE(v_activation.activation_version, 0) + 1;
    PERFORM set_config('gda.metric_activation_allowed', '1', true);
    INSERT INTO gda_control.metric_definition_activation (
        tenant_id, metric_ref, canonical_name, active_version_ref,
        active_fingerprint, approval_case_ref, activation_version,
        activated_by, activation_reason, activated_at
    ) VALUES (
        p_tenant_id, v_definition.metric_ref,
        v_definition.definition_document->>'canonical_name',
        p_metric_version_ref, p_definition_fingerprint,
        p_approval_case_ref, v_new_version, p_actor_subject, p_reason, v_now
    )
    ON CONFLICT (tenant_id, metric_ref) DO UPDATE
    SET canonical_name = EXCLUDED.canonical_name,
        active_version_ref = EXCLUDED.active_version_ref,
        active_fingerprint = EXCLUDED.active_fingerprint,
        approval_case_ref = EXCLUDED.approval_case_ref,
        activation_version = EXCLUDED.activation_version,
        activated_by = EXCLUDED.activated_by,
        activation_reason = EXCLUDED.activation_reason,
        activated_at = EXCLUDED.activated_at;
    PERFORM set_config('gda.metric_activation_allowed', '0', true);

    INSERT INTO gda_control.metric_definition_event (
        tenant_id, metric_ref, metric_version_ref, definition_fingerprint,
        event_type, approval_case_ref, actor_subject, reason,
        details, occurred_at
    ) VALUES (
        p_tenant_id, v_definition.metric_ref, p_metric_version_ref,
        p_definition_fingerprint, 'activated', p_approval_case_ref,
        p_actor_subject, p_reason,
        jsonb_build_object(
            'activation_version', v_new_version,
            'approval_decided_by', v_approval.decided_by,
            'approval_decided_at', v_approval.decided_at,
            'canonical_name', v_definition.definition_document->>'canonical_name',
            'owner_subject', v_definition.definition_document->>'owner_subject',
            'steward_subject', v_definition.definition_document->>'steward_subject'
        ),
        v_now
    );
    RETURN v_new_version;
EXCEPTION WHEN OTHERS THEN
    PERFORM set_config('gda.metric_activation_allowed', '0', true);
    RAISE;
END;
$$;

DROP TRIGGER IF EXISTS trg_gda_metric_definition_immutable
    ON gda_control.metric_definition_version;
CREATE TRIGGER trg_gda_metric_definition_immutable
BEFORE UPDATE OR DELETE ON gda_control.metric_definition_version
FOR EACH ROW EXECUTE FUNCTION gda_control.reject_immutable_mutation();

DROP TRIGGER IF EXISTS trg_gda_metric_activation_guard
    ON gda_control.metric_definition_activation;
CREATE TRIGGER trg_gda_metric_activation_guard
BEFORE INSERT OR UPDATE ON gda_control.metric_definition_activation
FOR EACH ROW EXECUTE FUNCTION gda_control.guard_metric_activation_mutation();

DROP TRIGGER IF EXISTS trg_gda_metric_activation_delete_guard
    ON gda_control.metric_definition_activation;
CREATE TRIGGER trg_gda_metric_activation_delete_guard
BEFORE DELETE ON gda_control.metric_definition_activation
FOR EACH ROW EXECUTE FUNCTION gda_control.reject_immutable_mutation();

DROP TRIGGER IF EXISTS trg_gda_metric_event_immutable
    ON gda_control.metric_definition_event;
CREATE TRIGGER trg_gda_metric_event_immutable
BEFORE UPDATE OR DELETE ON gda_control.metric_definition_event
FOR EACH ROW EXECUTE FUNCTION gda_control.reject_immutable_mutation();

ALTER TABLE gda_control.metric_definition_version ENABLE ROW LEVEL SECURITY;
ALTER TABLE gda_control.metric_definition_version FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON gda_control.metric_definition_version;
CREATE POLICY tenant_isolation ON gda_control.metric_definition_version
USING (tenant_id = gda_control.current_tenant())
WITH CHECK (tenant_id = gda_control.current_tenant());

ALTER TABLE gda_control.metric_definition_activation ENABLE ROW LEVEL SECURITY;
ALTER TABLE gda_control.metric_definition_activation FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON gda_control.metric_definition_activation;
CREATE POLICY tenant_isolation ON gda_control.metric_definition_activation
USING (tenant_id = gda_control.current_tenant())
WITH CHECK (tenant_id = gda_control.current_tenant());

ALTER TABLE gda_control.metric_definition_event ENABLE ROW LEVEL SECURITY;
ALTER TABLE gda_control.metric_definition_event FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON gda_control.metric_definition_event;
CREATE POLICY tenant_isolation ON gda_control.metric_definition_event
USING (tenant_id = gda_control.current_tenant())
WITH CHECK (tenant_id = gda_control.current_tenant());

REVOKE ALL ON TABLE gda_control.metric_definition_version
    FROM PUBLIC, gda_control_gateway;
REVOKE ALL ON TABLE gda_control.metric_definition_activation
    FROM PUBLIC, gda_control_gateway;
REVOKE ALL ON TABLE gda_control.metric_definition_event
    FROM PUBLIC, gda_control_gateway;
GRANT SELECT ON gda_control.metric_definition_version TO gda_control_gateway;
GRANT SELECT ON gda_control.metric_definition_activation TO gda_control_gateway;
GRANT SELECT ON gda_control.metric_definition_event TO gda_control_gateway;

REVOKE ALL ON FUNCTION gda_control.guard_metric_activation_mutation()
    FROM PUBLIC;
REVOKE ALL ON FUNCTION gda_control.stage_metric_definition_version(
    TEXT, TEXT, TEXT, INTEGER, JSONB, TEXT, TEXT, TIMESTAMPTZ
) FROM PUBLIC;
REVOKE ALL ON FUNCTION gda_control.activate_metric_definition_version(
    TEXT, TEXT, TEXT, TEXT, INTEGER, TEXT, TEXT
) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION gda_control.stage_metric_definition_version(
    TEXT, TEXT, TEXT, INTEGER, JSONB, TEXT, TEXT, TIMESTAMPTZ
) TO gda_control_gateway;
GRANT EXECUTE ON FUNCTION gda_control.activate_metric_definition_version(
    TEXT, TEXT, TEXT, TEXT, INTEGER, TEXT, TEXT
) TO gda_control_gateway;
