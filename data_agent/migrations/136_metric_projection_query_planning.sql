-- Governed physical projections for exact active metric and data-product versions.

CREATE TABLE IF NOT EXISTS gda_control.metric_projection_version (
    tenant_id TEXT NOT NULL,
    projection_ref TEXT NOT NULL,
    projection_version_ref TEXT NOT NULL,
    projection_version INTEGER NOT NULL,
    projection_document JSONB NOT NULL,
    projection_fingerprint CHAR(64) NOT NULL,
    metric_version_ref TEXT NOT NULL,
    metric_fingerprint CHAR(64) NOT NULL,
    product_urn TEXT NOT NULL,
    data_product_version_id UUID NOT NULL,
    output_resource_version_id UUID NOT NULL,
    source_manifest_sha256 CHAR(64) NOT NULL,
    source_snapshot_ref TEXT NOT NULL,
    created_by TEXT NOT NULL,
    creation_reason TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (tenant_id, projection_version_ref),
    CONSTRAINT uq_gda_metric_projection_version_number
        UNIQUE (tenant_id, projection_ref, projection_version),
    CONSTRAINT uq_gda_metric_projection_fingerprint
        UNIQUE (tenant_id, projection_version_ref, projection_fingerprint),
    CONSTRAINT fk_gda_metric_projection_metric
        FOREIGN KEY (tenant_id, metric_version_ref, metric_fingerprint)
        REFERENCES gda_control.metric_definition_version(
            tenant_id, metric_version_ref, definition_fingerprint
        ),
    CONSTRAINT fk_gda_metric_projection_product
        FOREIGN KEY (tenant_id, product_urn, data_product_version_id)
        REFERENCES gda_control.data_product_version(
            tenant_id, product_urn, data_product_version_id
        ),
    CONSTRAINT fk_gda_metric_projection_output
        FOREIGN KEY (tenant_id, output_resource_version_id)
        REFERENCES gda_control.resource_version(tenant_id, resource_version_id),
    CONSTRAINT ck_gda_metric_projection_tenant CHECK (
        split_part(projection_ref, '/', 3) = tenant_id
        AND split_part(projection_version_ref, '/', 3) = tenant_id
        AND split_part(metric_version_ref, '/', 3) = tenant_id
        AND split_part(product_urn, '/', 3) = tenant_id
    ),
    CONSTRAINT ck_gda_metric_projection_identity CHECK (
        projection_ref
            ~ '^gda://[a-z0-9][a-z0-9._-]{0,63}/metric_projection/[a-z0-9][a-z0-9._-]{0,127}$'
        AND projection_version BETWEEN 1 AND 1000000
        AND projection_version_ref = projection_ref || '.v' || projection_version::text
    ),
    CONSTRAINT ck_gda_metric_projection_document CHECK (
        jsonb_typeof(projection_document) = 'object'
        AND projection_document->>'schema_id' = 'gda.metric_projection.v1'
        AND projection_document->>'metric_version_ref' = metric_version_ref
        AND projection_document->>'metric_fingerprint' = metric_fingerprint
        AND projection_document->>'product_urn' = product_urn
        AND projection_document->>'data_product_version_id'
            = data_product_version_id::text
        AND projection_document->>'output_resource_version_id'
            = output_resource_version_id::text
        AND projection_document->>'source_manifest_sha256'
            = source_manifest_sha256
        AND projection_document->>'source_snapshot_ref' = source_snapshot_ref
    ),
    CONSTRAINT ck_gda_metric_projection_hashes CHECK (
        projection_fingerprint ~ '^[0-9a-f]{64}$'
        AND metric_fingerprint ~ '^[0-9a-f]{64}$'
        AND source_manifest_sha256 ~ '^[0-9a-f]{64}$'
    ),
    CONSTRAINT ck_gda_metric_projection_creator CHECK (
        created_by ~ '^(human|workload|agent):[^[:space:]]{1,128}$'
    ),
    CONSTRAINT ck_gda_metric_projection_reason CHECK (
        NULLIF(btrim(creation_reason), '') IS NOT NULL
    )
);

CREATE INDEX IF NOT EXISTS idx_gda_metric_projection_metric
    ON gda_control.metric_projection_version(
        tenant_id, metric_version_ref, metric_fingerprint
    );
CREATE INDEX IF NOT EXISTS idx_gda_metric_projection_engine_tier
    ON gda_control.metric_projection_version(
        tenant_id,
        (projection_document->>'engine'),
        (projection_document->>'serving_tier')
    );

CREATE TABLE IF NOT EXISTS gda_control.metric_projection_activation (
    tenant_id TEXT NOT NULL,
    projection_ref TEXT NOT NULL,
    active_version_ref TEXT NOT NULL,
    active_fingerprint CHAR(64) NOT NULL,
    activation_version INTEGER NOT NULL,
    activated_by TEXT NOT NULL,
    activation_reason TEXT NOT NULL,
    activated_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (tenant_id, projection_ref),
    CONSTRAINT fk_gda_metric_projection_activation_version
        FOREIGN KEY (tenant_id, active_version_ref, active_fingerprint)
        REFERENCES gda_control.metric_projection_version(
            tenant_id, projection_version_ref, projection_fingerprint
        ),
    CONSTRAINT ck_gda_metric_projection_activation_identity CHECK (
        split_part(projection_ref, '/', 3) = tenant_id
        AND active_version_ref LIKE projection_ref || '.v%'
    ),
    CONSTRAINT ck_gda_metric_projection_activation_version CHECK (
        activation_version >= 1
    ),
    CONSTRAINT ck_gda_metric_projection_activator CHECK (
        activated_by ~ '^(human|workload|agent):[^[:space:]]{1,128}$'
    ),
    CONSTRAINT ck_gda_metric_projection_activation_reason CHECK (
        NULLIF(btrim(activation_reason), '') IS NOT NULL
    )
);

CREATE TABLE IF NOT EXISTS gda_control.metric_projection_event (
    tenant_id TEXT NOT NULL,
    projection_event_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    projection_ref TEXT NOT NULL,
    projection_version_ref TEXT NOT NULL,
    projection_fingerprint CHAR(64) NOT NULL,
    event_type TEXT NOT NULL,
    actor_subject TEXT NOT NULL,
    reason TEXT NOT NULL,
    details JSONB NOT NULL DEFAULT '{}'::jsonb,
    occurred_at TIMESTAMPTZ NOT NULL,
    CONSTRAINT uq_gda_metric_projection_event_tenant_id
        UNIQUE (tenant_id, projection_event_id),
    CONSTRAINT fk_gda_metric_projection_event_version
        FOREIGN KEY (tenant_id, projection_version_ref, projection_fingerprint)
        REFERENCES gda_control.metric_projection_version(
            tenant_id, projection_version_ref, projection_fingerprint
        ),
    CONSTRAINT ck_gda_metric_projection_event_type CHECK (
        event_type IN ('staged', 'activated')
    ),
    CONSTRAINT ck_gda_metric_projection_event_actor CHECK (
        actor_subject ~ '^(human|workload|agent):[^[:space:]]{1,128}$'
    ),
    CONSTRAINT ck_gda_metric_projection_event_reason CHECK (
        NULLIF(btrim(reason), '') IS NOT NULL
    ),
    CONSTRAINT ck_gda_metric_projection_event_details CHECK (
        jsonb_typeof(details) = 'object'
    )
);

CREATE INDEX IF NOT EXISTS idx_gda_metric_projection_event
    ON gda_control.metric_projection_event(
        tenant_id, projection_ref, occurred_at, projection_event_id
    );

CREATE OR REPLACE FUNCTION gda_control.guard_metric_projection_activation_mutation()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    IF COALESCE(current_setting('gda.metric_projection_activation_allowed', true), '')
        <> '1' THEN
        RAISE EXCEPTION 'use gda_control.activate_metric_projection_version()'
            USING ERRCODE = '55000';
    END IF;
    IF TG_OP = 'UPDATE' AND (
        NEW.tenant_id IS DISTINCT FROM OLD.tenant_id
        OR NEW.projection_ref IS DISTINCT FROM OLD.projection_ref
        OR NEW.activation_version <> OLD.activation_version + 1
    ) THEN
        RAISE EXCEPTION 'projection activation identity or CAS sequence is invalid'
            USING ERRCODE = '40001';
    END IF;
    RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION gda_control.stage_metric_projection_version(
    p_tenant_id TEXT,
    p_projection_ref TEXT,
    p_projection_version_ref TEXT,
    p_projection_version INTEGER,
    p_projection_document JSONB,
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
    v_fingerprint TEXT;
    v_stored gda_control.metric_projection_version%ROWTYPE;
    v_inserted BOOLEAN := FALSE;
    v_metric gda_control.metric_definition_version%ROWTYPE;
    v_product gda_control.data_product_version%ROWTYPE;
    v_dimension TEXT;
    v_refreshed_at TIMESTAMPTZ;
BEGIN
    IF gda_control.current_tenant() IS NULL
       OR p_tenant_id IS DISTINCT FROM gda_control.current_tenant() THEN
        RAISE EXCEPTION 'projection tenant context is missing or mismatched'
            USING ERRCODE = '42501';
    END IF;
    IF p_projection_ref IS NULL
       OR p_projection_ref
            !~ '^gda://[a-z0-9][a-z0-9._-]{0,63}/metric_projection/[a-z0-9][a-z0-9._-]{0,127}$'
       OR split_part(p_projection_ref, '/', 3) <> p_tenant_id
       OR p_projection_version NOT BETWEEN 1 AND 1000000
       OR p_projection_version_ref
            <> p_projection_ref || '.v' || p_projection_version::text
       OR p_created_by !~ '^(human|workload|agent):[^[:space:]]{1,128}$'
       OR NULLIF(btrim(p_creation_reason), '') IS NULL
       OR p_created_at IS NULL THEN
        RAISE EXCEPTION 'projection identity, version or provenance is invalid'
            USING ERRCODE = '22023';
    END IF;
    IF jsonb_typeof(p_projection_document) <> 'object'
       OR (
            SELECT array_agg(key ORDER BY key) IS DISTINCT FROM ARRAY[
                'data_product_version_id', 'dimension_columns', 'engine',
                'estimated_rows', 'geometry_column', 'geometry_crs',
                'geometry_srid', 'metric_fingerprint', 'metric_version_ref',
                'output_resource_version_id', 'p95_latency_ms',
                'product_urn', 'projection_dimensions', 'refreshed_at',
                'relation_ref', 'schema_id', 'serving_tier',
                'source_manifest_sha256', 'source_snapshot_ref',
                'time_column', 'time_grain', 'value_column'
            ]::text[]
            FROM jsonb_object_keys(p_projection_document) AS keys(key)
       )
       OR p_projection_document->>'schema_id' <> 'gda.metric_projection.v1'
       OR p_projection_document->>'metric_version_ref'
            !~ '^gda://[a-z0-9][a-z0-9._-]{0,63}/metric_definition/[a-z0-9][a-z0-9._-]{0,127}\.v[1-9][0-9]*$'
       OR split_part(p_projection_document->>'metric_version_ref', '/', 3)
            <> p_tenant_id
       OR p_projection_document->>'metric_fingerprint' !~ '^[0-9a-f]{64}$'
       OR p_projection_document->>'product_urn'
            !~ '^gda://[a-z0-9][a-z0-9._-]{0,63}/data_product/[a-z0-9][a-z0-9._-]{0,127}$'
       OR split_part(p_projection_document->>'product_urn', '/', 3)
            <> p_tenant_id
       OR p_projection_document->>'data_product_version_id'
            !~ '^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$'
       OR p_projection_document->>'output_resource_version_id'
            !~ '^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$'
       OR p_projection_document->>'source_manifest_sha256' !~ '^[0-9a-f]{64}$'
       OR NULLIF(btrim(p_projection_document->>'source_snapshot_ref'), '') IS NULL
       OR length(p_projection_document->>'source_snapshot_ref') > 512
       OR p_projection_document->>'engine'
            NOT IN ('postgis', 'duckdb', 'iceberg_spark')
       OR p_projection_document->>'serving_tier'
            NOT IN ('serving', 'interactive', 'gold', 'batch')
       OR NULLIF(btrim(p_projection_document->>'relation_ref'), '') IS NULL
       OR length(p_projection_document->>'relation_ref') > 512
       OR p_projection_document->>'value_column'
            !~ '^[a-z_][a-z0-9_]{0,62}$'
       OR jsonb_typeof(p_projection_document->'dimension_columns') <> 'object'
       OR jsonb_typeof(p_projection_document->'projection_dimensions') <> 'array'
       OR jsonb_array_length(p_projection_document->'projection_dimensions') > 100
       OR jsonb_typeof(p_projection_document->'estimated_rows') <> 'number'
       OR (p_projection_document->>'estimated_rows')::numeric < 0
       OR (p_projection_document->>'estimated_rows')::numeric > 1000000000000000
       OR jsonb_typeof(p_projection_document->'p95_latency_ms') <> 'number'
       OR (p_projection_document->>'p95_latency_ms')::numeric NOT BETWEEN 1 AND 86400000
       OR jsonb_typeof(p_projection_document->'refreshed_at') <> 'string' THEN
        RAISE EXCEPTION 'projection document is invalid'
            USING ERRCODE = '22023';
    END IF;

    IF (p_projection_document->>'engine' = 'postgis' AND (
            p_projection_document->>'serving_tier' <> 'serving'
            OR p_projection_document->>'relation_ref'
                !~ '^postgis://[a-z0-9][a-z0-9._-]{0,127}/[a-z_][a-z0-9_]{0,62}\.[a-z_][a-z0-9_]{0,62}$'
       )) OR (p_projection_document->>'engine' = 'duckdb' AND (
            p_projection_document->>'serving_tier' <> 'interactive'
            OR p_projection_document->>'relation_ref'
                !~ '^duckdb://[a-z0-9][a-z0-9._-]{0,127}/[a-z0-9][a-z0-9._/-]{0,255}$'
       )) OR (p_projection_document->>'engine' = 'iceberg_spark' AND (
            p_projection_document->>'serving_tier' NOT IN ('gold', 'batch')
            OR p_projection_document->>'relation_ref'
                !~ '^iceberg://[a-z0-9][a-z0-9._-]{0,127}/[a-z0-9][a-z0-9._-]{0,127}/[a-z0-9][a-z0-9._-]{0,127}$'
       )) THEN
        RAISE EXCEPTION 'projection engine, tier and relation are inconsistent'
            USING ERRCODE = '22023';
    END IF;

    IF ((p_projection_document->'time_column') = 'null'::jsonb)
        IS DISTINCT FROM ((p_projection_document->'time_grain') = 'null'::jsonb)
       OR (
            (p_projection_document->'time_column') <> 'null'::jsonb
            AND (
                p_projection_document->>'time_column'
                    !~ '^[a-z_][a-z0-9_]{0,62}$'
                OR p_projection_document->>'time_grain'
                    NOT IN ('minute', 'hour', 'day', 'week', 'month',
                            'quarter', 'year')
            )
       ) THEN
        RAISE EXCEPTION 'projection time binding is invalid'
            USING ERRCODE = '22023';
    END IF;
    IF NOT (
        ((p_projection_document->'geometry_column') = 'null'::jsonb
          AND (p_projection_document->'geometry_srid') = 'null'::jsonb
          AND (p_projection_document->'geometry_crs') = 'null'::jsonb)
        OR
        ((p_projection_document->'geometry_column') <> 'null'::jsonb
          AND (p_projection_document->'geometry_srid') <> 'null'::jsonb
          AND (p_projection_document->'geometry_crs') <> 'null'::jsonb
          AND p_projection_document->>'geometry_column'
                ~ '^[a-z_][a-z0-9_]{0,62}$'
          AND jsonb_typeof(p_projection_document->'geometry_srid') = 'number'
          AND (p_projection_document->>'geometry_srid')::numeric
                BETWEEN 1 AND 999999
          AND p_projection_document->>'geometry_crs'
                ~ '^(EPSG|OGC):[A-Za-z0-9._-]{1,64}$')
    ) THEN
        RAISE EXCEPTION 'projection geometry binding is invalid'
            USING ERRCODE = '22023';
    END IF;
    BEGIN
        v_refreshed_at := (p_projection_document->>'refreshed_at')::timestamptz;
    EXCEPTION WHEN invalid_datetime_format OR datetime_field_overflow THEN
        RAISE EXCEPTION 'projection refresh timestamp is invalid'
            USING ERRCODE = '22023';
    END;
    IF v_refreshed_at > p_created_at THEN
        RAISE EXCEPTION 'projection refresh cannot occur after version registration'
            USING ERRCODE = '22023';
    END IF;

    SELECT * INTO v_metric
    FROM gda_control.metric_definition_version
    WHERE tenant_id = p_tenant_id
      AND metric_version_ref = p_projection_document->>'metric_version_ref'
      AND definition_fingerprint = p_projection_document->>'metric_fingerprint';
    IF NOT FOUND THEN
        RAISE EXCEPTION 'projection must bind an exact MetricDefinitionVersion'
            USING ERRCODE = '23503';
    END IF;
    FOR v_dimension IN
        SELECT jsonb_array_elements_text(
            p_projection_document->'projection_dimensions'
        )
    LOOP
        IF v_dimension !~ '^[a-z][a-z0-9_]{0,127}$'
           OR NOT (v_metric.definition_document->'dimensions' ? v_dimension)
           OR NOT (p_projection_document->'dimension_columns' ? v_dimension)
           OR p_projection_document->'dimension_columns'->>v_dimension
                !~ '^[a-z_][a-z0-9_]{0,62}$' THEN
            RAISE EXCEPTION 'projection dimension is outside the metric contract'
                USING ERRCODE = '22023';
        END IF;
    END LOOP;
    IF (
        SELECT array_agg(value ORDER BY value)
        FROM jsonb_array_elements_text(
            p_projection_document->'projection_dimensions'
        ) AS dimensions(value)
    ) IS DISTINCT FROM (
        SELECT array_agg(key ORDER BY key)
        FROM jsonb_object_keys(
            p_projection_document->'dimension_columns'
        ) AS dimensions(key)
    ) THEN
        RAISE EXCEPTION 'projection dimensions must exactly match dimension mapping'
            USING ERRCODE = '22023';
    END IF;
    IF v_metric.definition_document->'time_semantics' = 'null'::jsonb THEN
        IF (p_projection_document->'time_column') <> 'null'::jsonb THEN
            RAISE EXCEPTION 'projection time binding requires metric time semantics'
                USING ERRCODE = '22023';
        END IF;
    ELSIF (
        p_projection_document->'projection_dimensions'
            ? (v_metric.definition_document->'time_semantics'->>'dimension')
    ) IS DISTINCT FROM (
        (p_projection_document->'time_column') <> 'null'::jsonb
    ) THEN
        RAISE EXCEPTION 'projected metric time dimension and binding must match'
            USING ERRCODE = '22023';
    END IF;
    IF (p_projection_document->'geometry_crs') <> 'null'::jsonb
       AND (
            v_metric.definition_document->'spatial_semantics' = 'null'::jsonb
            OR NOT (
                p_projection_document->'projection_dimensions'
                    ? (v_metric.definition_document->'spatial_semantics'->>'dimension')
            )
            OR p_projection_document->>'geometry_crs'
                <> v_metric.definition_document->'spatial_semantics'->>'crs'
       ) THEN
        RAISE EXCEPTION 'projection geometry CRS must match metric spatial semantics'
            USING ERRCODE = '22023';
    END IF;

    SELECT * INTO v_product
    FROM gda_control.data_product_version
    WHERE tenant_id = p_tenant_id
      AND product_urn = p_projection_document->>'product_urn'
      AND data_product_version_id
            = (p_projection_document->>'data_product_version_id')::uuid
      AND output_resource_version_id
            = (p_projection_document->>'output_resource_version_id')::uuid
      AND manifest_sha256
            = p_projection_document->>'source_manifest_sha256'
      AND quality_verdict = 'passed';
    IF NOT FOUND THEN
        RAISE EXCEPTION 'projection must bind an exact passed DataProductVersion manifest'
            USING ERRCODE = '23503';
    END IF;

    v_fingerprint := encode(
        digest(convert_to(p_projection_document::text, 'UTF8'), 'sha256'),
        'hex'
    );
    INSERT INTO gda_control.metric_projection_version (
        tenant_id, projection_ref, projection_version_ref,
        projection_version, projection_document, projection_fingerprint,
        metric_version_ref, metric_fingerprint, product_urn,
        data_product_version_id, output_resource_version_id,
        source_manifest_sha256, source_snapshot_ref,
        created_by, creation_reason, created_at
    ) VALUES (
        p_tenant_id, p_projection_ref, p_projection_version_ref,
        p_projection_version, p_projection_document, v_fingerprint,
        p_projection_document->>'metric_version_ref',
        p_projection_document->>'metric_fingerprint',
        p_projection_document->>'product_urn',
        (p_projection_document->>'data_product_version_id')::uuid,
        (p_projection_document->>'output_resource_version_id')::uuid,
        p_projection_document->>'source_manifest_sha256',
        p_projection_document->>'source_snapshot_ref',
        p_created_by, p_creation_reason, p_created_at
    )
    ON CONFLICT (tenant_id, projection_version_ref) DO NOTHING
    RETURNING * INTO v_stored;
    v_inserted := FOUND;
    IF NOT v_inserted THEN
        SELECT * INTO STRICT v_stored
        FROM gda_control.metric_projection_version
        WHERE tenant_id = p_tenant_id
          AND projection_version_ref = p_projection_version_ref;
        IF v_stored.projection_ref <> p_projection_ref
           OR v_stored.projection_version <> p_projection_version
           OR v_stored.projection_document <> p_projection_document
           OR v_stored.projection_fingerprint <> v_fingerprint
           OR v_stored.created_by <> p_created_by
           OR v_stored.creation_reason <> p_creation_reason THEN
            RAISE EXCEPTION 'projection version identity has conflicting evidence'
                USING ERRCODE = '23505';
        END IF;
    END IF;
    IF v_inserted THEN
        INSERT INTO gda_control.metric_projection_event (
            tenant_id, projection_ref, projection_version_ref,
            projection_fingerprint, event_type, actor_subject, reason,
            details, occurred_at
        ) VALUES (
            p_tenant_id, p_projection_ref, p_projection_version_ref,
            v_fingerprint, 'staged', p_created_by, p_creation_reason,
            jsonb_build_object(
                'schema', 'gda.metric_projection_event.v1',
                'engine', p_projection_document->>'engine',
                'serving_tier', p_projection_document->>'serving_tier',
                'metric_version_ref', p_projection_document->>'metric_version_ref',
                'data_product_version_id',
                    p_projection_document->>'data_product_version_id',
                'source_manifest_sha256',
                    p_projection_document->>'source_manifest_sha256',
                'source_snapshot_ref',
                    p_projection_document->>'source_snapshot_ref'
            ),
            p_created_at
        );
    END IF;
    RETURN v_fingerprint;
END;
$$;

CREATE OR REPLACE FUNCTION gda_control.activate_metric_projection_version(
    p_tenant_id TEXT,
    p_projection_version_ref TEXT,
    p_projection_fingerprint TEXT,
    p_expected_activation_version INTEGER,
    p_actor_subject TEXT,
    p_reason TEXT
)
RETURNS INTEGER
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, gda_control, public
SET row_security = on
AS $$
DECLARE
    v_projection gda_control.metric_projection_version%ROWTYPE;
    v_activation gda_control.metric_projection_activation%ROWTYPE;
    v_now TIMESTAMPTZ := clock_timestamp();
    v_next_version INTEGER;
BEGIN
    IF gda_control.current_tenant() IS NULL
       OR p_tenant_id IS DISTINCT FROM gda_control.current_tenant() THEN
        RAISE EXCEPTION 'projection tenant context is missing or mismatched'
            USING ERRCODE = '42501';
    END IF;
    IF p_projection_fingerprint !~ '^[0-9a-f]{64}$'
       OR p_expected_activation_version < 0
       OR p_actor_subject !~ '^(human|workload|agent):[^[:space:]]{1,128}$'
       OR NULLIF(btrim(p_reason), '') IS NULL THEN
        RAISE EXCEPTION 'projection activation request is invalid'
            USING ERRCODE = '22023';
    END IF;
    SELECT * INTO v_projection
    FROM gda_control.metric_projection_version
    WHERE tenant_id = p_tenant_id
      AND projection_version_ref = p_projection_version_ref
      AND projection_fingerprint = p_projection_fingerprint;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'metric projection version was not found'
            USING ERRCODE = 'P0002';
    END IF;
    IF NOT EXISTS (
        SELECT 1
        FROM gda_control.metric_definition_activation active_metric
        WHERE active_metric.tenant_id = p_tenant_id
          AND active_metric.active_version_ref = v_projection.metric_version_ref
          AND active_metric.active_fingerprint = v_projection.metric_fingerprint
    ) THEN
        RAISE EXCEPTION 'projection metric must be active at its exact version'
            USING ERRCODE = '22023';
    END IF;
    IF NOT EXISTS (
        SELECT 1
        FROM gda_control.data_product_version product_version
        WHERE product_version.tenant_id = p_tenant_id
          AND product_version.product_urn = v_projection.product_urn
          AND product_version.data_product_version_id
                = v_projection.data_product_version_id
          AND product_version.output_resource_version_id
                = v_projection.output_resource_version_id
          AND product_version.manifest_sha256
                = v_projection.source_manifest_sha256
          AND product_version.quality_verdict = 'passed'
    ) THEN
        RAISE EXCEPTION 'projection DataProductVersion is no longer valid'
            USING ERRCODE = '22023';
    END IF;
    SELECT * INTO v_activation
    FROM gda_control.metric_projection_activation
    WHERE tenant_id = p_tenant_id
      AND projection_ref = v_projection.projection_ref
    FOR UPDATE;
    IF FOUND THEN
        IF v_activation.activation_version <> p_expected_activation_version THEN
            RAISE EXCEPTION 'projection activation CAS conflict'
                USING ERRCODE = '40001';
        END IF;
        IF v_activation.active_version_ref = p_projection_version_ref
           AND v_activation.active_fingerprint = p_projection_fingerprint THEN
            RETURN v_activation.activation_version;
        END IF;
        v_next_version := v_activation.activation_version + 1;
    ELSE
        IF p_expected_activation_version <> 0 THEN
            RAISE EXCEPTION 'projection activation CAS conflict'
                USING ERRCODE = '40001';
        END IF;
        v_next_version := 1;
    END IF;

    PERFORM set_config('gda.metric_projection_activation_allowed', '1', true);
    INSERT INTO gda_control.metric_projection_activation (
        tenant_id, projection_ref, active_version_ref, active_fingerprint,
        activation_version, activated_by, activation_reason, activated_at
    ) VALUES (
        p_tenant_id, v_projection.projection_ref,
        p_projection_version_ref, p_projection_fingerprint,
        v_next_version, p_actor_subject, p_reason, v_now
    )
    ON CONFLICT (tenant_id, projection_ref) DO UPDATE SET
        active_version_ref = EXCLUDED.active_version_ref,
        active_fingerprint = EXCLUDED.active_fingerprint,
        activation_version = EXCLUDED.activation_version,
        activated_by = EXCLUDED.activated_by,
        activation_reason = EXCLUDED.activation_reason,
        activated_at = EXCLUDED.activated_at;
    PERFORM set_config('gda.metric_projection_activation_allowed', '', true);

    INSERT INTO gda_control.metric_projection_event (
        tenant_id, projection_ref, projection_version_ref,
        projection_fingerprint, event_type, actor_subject, reason,
        details, occurred_at
    ) VALUES (
        p_tenant_id, v_projection.projection_ref,
        p_projection_version_ref, p_projection_fingerprint,
        'activated', p_actor_subject, p_reason,
        jsonb_build_object(
            'schema', 'gda.metric_projection_event.v1',
            'activation_version', v_next_version,
            'metric_version_ref', v_projection.metric_version_ref,
            'metric_fingerprint', v_projection.metric_fingerprint,
            'source_manifest_sha256', v_projection.source_manifest_sha256,
            'source_snapshot_ref', v_projection.source_snapshot_ref
        ),
        v_now
    );
    RETURN v_next_version;
END;
$$;

DROP TRIGGER IF EXISTS trg_gda_metric_projection_version_immutable
    ON gda_control.metric_projection_version;
CREATE TRIGGER trg_gda_metric_projection_version_immutable
BEFORE UPDATE OR DELETE ON gda_control.metric_projection_version
FOR EACH ROW EXECUTE FUNCTION gda_control.reject_immutable_mutation();

DROP TRIGGER IF EXISTS trg_gda_metric_projection_activation_guard
    ON gda_control.metric_projection_activation;
CREATE TRIGGER trg_gda_metric_projection_activation_guard
BEFORE INSERT OR UPDATE ON gda_control.metric_projection_activation
FOR EACH ROW EXECUTE FUNCTION gda_control.guard_metric_projection_activation_mutation();

DROP TRIGGER IF EXISTS trg_gda_metric_projection_activation_no_delete
    ON gda_control.metric_projection_activation;
CREATE TRIGGER trg_gda_metric_projection_activation_no_delete
BEFORE DELETE ON gda_control.metric_projection_activation
FOR EACH ROW EXECUTE FUNCTION gda_control.reject_immutable_mutation();

DROP TRIGGER IF EXISTS trg_gda_metric_projection_event_immutable
    ON gda_control.metric_projection_event;
CREATE TRIGGER trg_gda_metric_projection_event_immutable
BEFORE UPDATE OR DELETE ON gda_control.metric_projection_event
FOR EACH ROW EXECUTE FUNCTION gda_control.reject_immutable_mutation();

ALTER TABLE gda_control.metric_projection_version ENABLE ROW LEVEL SECURITY;
ALTER TABLE gda_control.metric_projection_version FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON gda_control.metric_projection_version;
CREATE POLICY tenant_isolation ON gda_control.metric_projection_version
    USING (tenant_id = gda_control.current_tenant())
    WITH CHECK (tenant_id = gda_control.current_tenant());

ALTER TABLE gda_control.metric_projection_activation ENABLE ROW LEVEL SECURITY;
ALTER TABLE gda_control.metric_projection_activation FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON gda_control.metric_projection_activation;
CREATE POLICY tenant_isolation ON gda_control.metric_projection_activation
    USING (tenant_id = gda_control.current_tenant())
    WITH CHECK (tenant_id = gda_control.current_tenant());

ALTER TABLE gda_control.metric_projection_event ENABLE ROW LEVEL SECURITY;
ALTER TABLE gda_control.metric_projection_event FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON gda_control.metric_projection_event;
CREATE POLICY tenant_isolation ON gda_control.metric_projection_event
    USING (tenant_id = gda_control.current_tenant())
    WITH CHECK (tenant_id = gda_control.current_tenant());

REVOKE ALL ON TABLE gda_control.metric_projection_version
    FROM PUBLIC, gda_control_gateway;
REVOKE ALL ON TABLE gda_control.metric_projection_activation
    FROM PUBLIC, gda_control_gateway;
REVOKE ALL ON TABLE gda_control.metric_projection_event
    FROM PUBLIC, gda_control_gateway;
GRANT SELECT ON gda_control.metric_projection_version TO gda_control_gateway;
GRANT SELECT ON gda_control.metric_projection_activation TO gda_control_gateway;
GRANT SELECT ON gda_control.metric_projection_event TO gda_control_gateway;

REVOKE ALL ON FUNCTION gda_control.guard_metric_projection_activation_mutation()
    FROM PUBLIC, gda_control_gateway;
REVOKE ALL ON FUNCTION gda_control.stage_metric_projection_version(
    TEXT, TEXT, TEXT, INTEGER, JSONB, TEXT, TEXT, TIMESTAMPTZ
) FROM PUBLIC;
REVOKE ALL ON FUNCTION gda_control.activate_metric_projection_version(
    TEXT, TEXT, TEXT, INTEGER, TEXT, TEXT
) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION gda_control.stage_metric_projection_version(
    TEXT, TEXT, TEXT, INTEGER, JSONB, TEXT, TEXT, TIMESTAMPTZ
) TO gda_control_gateway;
GRANT EXECUTE ON FUNCTION gda_control.activate_metric_projection_version(
    TEXT, TEXT, TEXT, INTEGER, TEXT, TEXT
) TO gda_control_gateway;
