-- 162: Atomic bounded batches for temporal entities, source identities and links.
--
-- Each function delegates validation and mutation to the existing single-item
-- authority. The enclosing function call is one PostgreSQL transaction: any
-- rejected item rolls back every earlier item in the same batch.

CREATE OR REPLACE FUNCTION gda_control.record_temporal_entity_assertion_batch(
    p_tenant_id TEXT,
    p_items JSONB
)
RETURNS JSONB
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, gda_control, public
SET row_security = on
AS $$
DECLARE
    v_item JSONB;
    v_result JSONB;
    v_results JSONB := '[]'::JSONB;
BEGIN
    IF gda_control.current_tenant() IS NULL
       OR p_tenant_id IS DISTINCT FROM gda_control.current_tenant() THEN
        RAISE EXCEPTION 'temporal entity batch tenant context is missing or mismatched'
            USING ERRCODE = '42501';
    END IF;
    IF p_items IS NULL
       OR jsonb_typeof(p_items) <> 'array'
       OR jsonb_array_length(p_items) NOT BETWEEN 1 AND 500
       OR EXISTS (
            SELECT 1
            FROM jsonb_array_elements(p_items) AS item(value)
            WHERE jsonb_typeof(value) <> 'object'
       ) THEN
        RAISE EXCEPTION 'temporal entity batch must contain 1..500 objects'
            USING ERRCODE = '22023';
    END IF;

    FOR v_item IN
        SELECT value
        FROM jsonb_array_elements(p_items) WITH ORDINALITY AS item(value, ordinal)
        ORDER BY ordinal
    LOOP
        SELECT to_jsonb(result) INTO STRICT v_result
        FROM gda_control.record_temporal_entity_assertion(
            p_tenant_id,
            v_item->>'entity_ref',
            v_item->>'object_type',
            v_item->>'lifecycle_state',
            v_item->'attributes',
            (v_item->>'valid_from')::TIMESTAMPTZ,
            (v_item->>'valid_to')::TIMESTAMPTZ,
            v_item->'source_version_refs',
            v_item->>'mutation_kind',
            (v_item->>'supersedes_assertion_id')::UUID,
            v_item->>'idempotency_key',
            v_item->>'owner_subject',
            v_item->>'recorded_by',
            v_item->>'reason'
        ) AS result;
        v_results := v_results || jsonb_build_array(v_result);
    END LOOP;
    RETURN v_results;
END;
$$;

CREATE OR REPLACE FUNCTION gda_control.bind_entity_source_identity_batch(
    p_tenant_id TEXT,
    p_items JSONB
)
RETURNS JSONB
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, gda_control, public
SET row_security = on
AS $$
DECLARE
    v_item JSONB;
    v_result JSONB;
    v_results JSONB := '[]'::JSONB;
BEGIN
    IF gda_control.current_tenant() IS NULL
       OR p_tenant_id IS DISTINCT FROM gda_control.current_tenant() THEN
        RAISE EXCEPTION 'source identity batch tenant context is missing or mismatched'
            USING ERRCODE = '42501';
    END IF;
    IF p_items IS NULL
       OR jsonb_typeof(p_items) <> 'array'
       OR jsonb_array_length(p_items) NOT BETWEEN 1 AND 500
       OR EXISTS (
            SELECT 1
            FROM jsonb_array_elements(p_items) AS item(value)
            WHERE jsonb_typeof(value) <> 'object'
       ) THEN
        RAISE EXCEPTION 'source identity batch must contain 1..500 objects'
            USING ERRCODE = '22023';
    END IF;

    FOR v_item IN
        SELECT value
        FROM jsonb_array_elements(p_items) WITH ORDINALITY AS item(value, ordinal)
        ORDER BY ordinal
    LOOP
        SELECT to_jsonb(result) INTO STRICT v_result
        FROM gda_control.bind_entity_source_identity(
            p_tenant_id,
            v_item->>'source_identity_ref',
            v_item->>'source_system_ref',
            v_item->>'source_object_type',
            v_item->>'source_object_id',
            v_item->>'entity_ref',
            v_item->>'entity_object_type',
            v_item->>'ontology_class_uri',
            v_item->>'source_version_ref',
            (v_item->>'valid_from')::TIMESTAMPTZ,
            (v_item->>'valid_to')::TIMESTAMPTZ,
            v_item->>'resolution_method',
            (v_item->>'confidence_basis_points')::INTEGER,
            v_item->'evidence',
            v_item->>'idempotency_key',
            v_item->>'owner_subject',
            v_item->>'recorded_by',
            v_item->>'reason'
        ) AS result;
        v_results := v_results || jsonb_build_array(v_result);
    END LOOP;
    RETURN v_results;
END;
$$;

CREATE OR REPLACE FUNCTION gda_control.register_entity_link_type_batch(
    p_tenant_id TEXT,
    p_items JSONB
)
RETURNS JSONB
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, gda_control, public
SET row_security = on
AS $$
DECLARE
    v_item JSONB;
    v_result JSONB;
    v_results JSONB := '[]'::JSONB;
BEGIN
    IF gda_control.current_tenant() IS NULL
       OR p_tenant_id IS DISTINCT FROM gda_control.current_tenant() THEN
        RAISE EXCEPTION 'link type batch tenant context is missing or mismatched'
            USING ERRCODE = '42501';
    END IF;
    IF p_items IS NULL
       OR jsonb_typeof(p_items) <> 'array'
       OR jsonb_array_length(p_items) NOT BETWEEN 1 AND 500
       OR EXISTS (
            SELECT 1
            FROM jsonb_array_elements(p_items) AS item(value)
            WHERE jsonb_typeof(value) <> 'object'
       ) THEN
        RAISE EXCEPTION 'link type batch must contain 1..500 objects'
            USING ERRCODE = '22023';
    END IF;

    FOR v_item IN
        SELECT value
        FROM jsonb_array_elements(p_items) WITH ORDINALITY AS item(value, ordinal)
        ORDER BY ordinal
    LOOP
        SELECT to_jsonb(result) INTO STRICT v_result
        FROM gda_control.register_entity_link_type(
            p_tenant_id,
            v_item->>'link_type_ref',
            v_item->>'predicate_uri',
            v_item->>'link_kind',
            v_item->>'source_object_type',
            v_item->>'target_object_type',
            v_item->>'source_ontology_class_uri',
            v_item->>'target_ontology_class_uri',
            v_item->>'ontology_package_id',
            v_item->>'ontology_package_sha256',
            v_item->>'ontology_review_status',
            (v_item->>'directed')::BOOLEAN,
            (v_item->>'allow_self')::BOOLEAN,
            (v_item->>'max_targets_per_source')::INTEGER,
            (v_item->>'max_sources_per_target')::INTEGER,
            v_item->>'owner_subject',
            v_item->>'created_by',
            v_item->>'reason'
        ) AS result;
        v_results := v_results || jsonb_build_array(v_result);
    END LOOP;
    RETURN v_results;
END;
$$;

CREATE OR REPLACE FUNCTION gda_control.record_entity_link_assertion_batch(
    p_tenant_id TEXT,
    p_items JSONB
)
RETURNS JSONB
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, gda_control, public
SET row_security = on
AS $$
DECLARE
    v_item JSONB;
    v_result JSONB;
    v_results JSONB := '[]'::JSONB;
BEGIN
    IF gda_control.current_tenant() IS NULL
       OR p_tenant_id IS DISTINCT FROM gda_control.current_tenant() THEN
        RAISE EXCEPTION 'entity link batch tenant context is missing or mismatched'
            USING ERRCODE = '42501';
    END IF;
    IF p_items IS NULL
       OR jsonb_typeof(p_items) <> 'array'
       OR jsonb_array_length(p_items) NOT BETWEEN 1 AND 500
       OR EXISTS (
            SELECT 1
            FROM jsonb_array_elements(p_items) AS item(value)
            WHERE jsonb_typeof(value) <> 'object'
       ) THEN
        RAISE EXCEPTION 'entity link batch must contain 1..500 objects'
            USING ERRCODE = '22023';
    END IF;

    FOR v_item IN
        SELECT value
        FROM jsonb_array_elements(p_items) WITH ORDINALITY AS item(value, ordinal)
        ORDER BY ordinal
    LOOP
        SELECT to_jsonb(result) INTO STRICT v_result
        FROM gda_control.record_entity_link_assertion(
            p_tenant_id,
            v_item->>'link_ref',
            v_item->>'link_type_ref',
            v_item->>'source_entity_ref',
            v_item->>'target_entity_ref',
            v_item->>'lifecycle_state',
            v_item->'attributes',
            (v_item->>'valid_from')::TIMESTAMPTZ,
            (v_item->>'valid_to')::TIMESTAMPTZ,
            v_item->'source_version_refs',
            v_item->>'mutation_kind',
            (v_item->>'supersedes_assertion_id')::UUID,
            (v_item->>'confidence_basis_points')::INTEGER,
            v_item->'evidence',
            v_item->>'idempotency_key',
            v_item->>'owner_subject',
            v_item->>'recorded_by',
            v_item->>'reason'
        ) AS result;
        v_results := v_results || jsonb_build_array(v_result);
    END LOOP;
    RETURN v_results;
END;
$$;

REVOKE ALL ON FUNCTION gda_control.record_temporal_entity_assertion_batch(
    TEXT, JSONB
) FROM PUBLIC;
REVOKE ALL ON FUNCTION gda_control.bind_entity_source_identity_batch(
    TEXT, JSONB
) FROM PUBLIC;
REVOKE ALL ON FUNCTION gda_control.register_entity_link_type_batch(
    TEXT, JSONB
) FROM PUBLIC;
REVOKE ALL ON FUNCTION gda_control.record_entity_link_assertion_batch(
    TEXT, JSONB
) FROM PUBLIC;

GRANT EXECUTE ON FUNCTION gda_control.record_temporal_entity_assertion_batch(
    TEXT, JSONB
) TO gda_control_gateway;
GRANT EXECUTE ON FUNCTION gda_control.bind_entity_source_identity_batch(
    TEXT, JSONB
) TO gda_control_gateway;
GRANT EXECUTE ON FUNCTION gda_control.register_entity_link_type_batch(
    TEXT, JSONB
) TO gda_control_gateway;
GRANT EXECUTE ON FUNCTION gda_control.record_entity_link_assertion_batch(
    TEXT, JSONB
) TO gda_control_gateway;
