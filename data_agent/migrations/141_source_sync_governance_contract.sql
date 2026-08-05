-- 141: Make ingestion governance executable in the SourceSync authority.

ALTER TABLE gda_control.source_sync_definition
    ADD COLUMN IF NOT EXISTS governance_contract JSONB;

CREATE OR REPLACE FUNCTION gda_control.source_sync_quality_refs_valid(p_refs JSONB)
RETURNS BOOLEAN
LANGUAGE sql
IMMUTABLE
PARALLEL SAFE
SET search_path = pg_catalog
AS $$
    SELECT
        jsonb_typeof(p_refs) = 'array'
        AND jsonb_array_length(p_refs) > 0
        AND NOT EXISTS (
            SELECT 1
            FROM jsonb_array_elements(p_refs) AS item
            WHERE jsonb_typeof(item) <> 'string'
               OR length(btrim(item #>> '{}')) = 0
        )
        AND jsonb_array_length(p_refs) = (
            SELECT count(DISTINCT item #>> '{}')
            FROM jsonb_array_elements(p_refs) AS item
        );
$$;

ALTER TABLE gda_control.source_sync_definition
    ADD CONSTRAINT ck_gda_source_sync_governance_contract CHECK (
        governance_contract IS NULL
        OR (
            jsonb_typeof(governance_contract) = 'object'
            AND governance_contract ?& ARRAY[
                'schema',
                'target_layer',
                'data_kind',
                'capture_kind',
                'source_adapter',
                'standard_mapping_contract_id',
                'standard_version_id',
                'data_model_version_id',
                'quality_rule_version_refs',
                'classification_policy_version_ref',
                'retention_policy_version_ref',
                'schema_change_policy',
                'promotion_mode',
                'quarantine_resource_urn',
                'event_time_field',
                'watermark_delay_seconds'
            ]
            AND governance_contract - ARRAY[
                'schema',
                'target_layer',
                'data_kind',
                'capture_kind',
                'source_adapter',
                'standard_mapping_contract_id',
                'standard_version_id',
                'data_model_version_id',
                'quality_rule_version_refs',
                'classification_policy_version_ref',
                'retention_policy_version_ref',
                'schema_change_policy',
                'promotion_mode',
                'quarantine_resource_urn',
                'event_time_field',
                'watermark_delay_seconds'
            ] = '{}'::jsonb
            AND governance_contract->>'schema' = 'gda.source_sync_governance.v1'
            AND governance_contract->>'target_layer'
                IN ('landing', 'ods', 'silver', 'gold')
            AND governance_contract->>'data_kind' IN (
                'tabular', 'vector', 'raster', 'document', 'image', 'video',
                'point_cloud', 'timeseries'
            )
            AND governance_contract->>'capture_kind'
                IN ('batch', 'micro_batch', 'cdc', 'event_stream')
            AND governance_contract->>'schema_change_policy'
                IN ('reject', 'approval_required', 'additive_compatible')
            AND governance_contract->>'promotion_mode'
                IN ('blocked', 'quality_gated', 'approval_gated')
            AND jsonb_typeof(governance_contract->'source_adapter') = 'object'
            AND governance_contract->'source_adapter' ?& ARRAY[
                'adapter_id', 'adapter_version', 'adapter_fingerprint'
            ]
            AND (governance_contract->'source_adapter') - ARRAY[
                'adapter_id', 'adapter_version', 'adapter_fingerprint'
            ] = '{}'::jsonb
            AND length(btrim(governance_contract->'source_adapter'->>'adapter_id')) > 0
            AND length(btrim(governance_contract->'source_adapter'->>'adapter_version')) > 0
            AND governance_contract->'source_adapter'->>'adapter_fingerprint'
                ~ '^[0-9a-f]{64}$'
            AND gda_control.source_sync_quality_refs_valid(
                governance_contract->'quality_rule_version_refs'
            )
            AND length(
                btrim(governance_contract->>'classification_policy_version_ref')
            ) > 0
            AND length(
                btrim(governance_contract->>'retention_policy_version_ref')
            ) > 0
            AND (
                (
                    governance_contract->'standard_mapping_contract_id' = 'null'::jsonb
                    AND governance_contract->'standard_version_id' = 'null'::jsonb
                ) OR (
                    governance_contract->>'standard_mapping_contract_id'
                        ~ '^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$'
                    AND governance_contract->>'standard_version_id'
                        ~ '^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$'
                )
            )
            AND (
                governance_contract->'data_model_version_id' = 'null'::jsonb
                OR governance_contract->>'data_model_version_id'
                    ~ '^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$'
            )
            AND (
                governance_contract->'quarantine_resource_urn' = 'null'::jsonb
                OR (
                    governance_contract->>'quarantine_resource_urn'
                        ~ '^gda://[a-z0-9][a-z0-9._-]{0,63}/[a-z][a-z0-9_-]{1,31}/[a-z0-9][a-z0-9._-]{0,127}$'
                    AND split_part(
                        governance_contract->>'quarantine_resource_urn', '/', 3
                    ) = tenant_id
                )
            )
            AND (
                (
                    governance_contract->>'target_layer' IN ('landing', 'ods')
                    AND governance_contract->>'promotion_mode' = 'blocked'
                ) OR (
                    governance_contract->>'target_layer' = 'silver'
                    AND governance_contract->>'promotion_mode'
                        IN ('quality_gated', 'approval_gated')
                    AND governance_contract->'standard_mapping_contract_id'
                        <> 'null'::jsonb
                    AND governance_contract->'standard_version_id' <> 'null'::jsonb
                    AND governance_contract->'data_model_version_id' <> 'null'::jsonb
                    AND governance_contract->'quarantine_resource_urn' <> 'null'::jsonb
                ) OR (
                    governance_contract->>'target_layer' = 'gold'
                    AND governance_contract->>'promotion_mode' = 'approval_gated'
                    AND governance_contract->'standard_mapping_contract_id'
                        <> 'null'::jsonb
                    AND governance_contract->'standard_version_id' <> 'null'::jsonb
                    AND governance_contract->'data_model_version_id' <> 'null'::jsonb
                    AND governance_contract->'quarantine_resource_urn' <> 'null'::jsonb
                )
            )
            AND (
                (
                    governance_contract->>'capture_kind' = 'event_stream'
                    AND length(btrim(governance_contract->>'event_time_field')) > 0
                    AND jsonb_typeof(
                        governance_contract->'watermark_delay_seconds'
                    ) = 'number'
                    AND (governance_contract->>'watermark_delay_seconds')::numeric >= 0
                ) OR (
                    governance_contract->>'capture_kind' <> 'event_stream'
                    AND governance_contract->'event_time_field' = 'null'::jsonb
                    AND governance_contract->'watermark_delay_seconds' = 'null'::jsonb
                )
            )
            AND (mode <> 'full' OR governance_contract->>'capture_kind' = 'batch')
            AND (
                governance_contract->>'capture_kind' = 'batch'
                OR mode = 'incremental'
            )
            AND (
                governance_contract->>'capture_kind' NOT IN ('cdc', 'event_stream')
                OR cursor_kind IN ('provider_token', 'offset')
            )
            AND (
                governance_contract->>'data_kind' NOT IN (
                    'raster', 'document', 'image', 'video', 'point_cloud'
                )
                OR (
                    write_disposition <> 'merge'
                    AND governance_contract->>'capture_kind' <> 'event_stream'
                )
            )
        )
    );

CREATE OR REPLACE FUNCTION gda_control.guard_source_sync_definition_insert()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
DECLARE
    v_resource gda_control.resource%ROWTYPE;
BEGIN
    IF gda_control.current_tenant() IS NULL
       OR NEW.tenant_id IS DISTINCT FROM gda_control.current_tenant() THEN
        RAISE EXCEPTION 'source sync tenant context is missing or mismatched'
            USING ERRCODE = '42501';
    END IF;
    IF NEW.governance_contract IS NULL THEN
        RAISE EXCEPTION 'new source sync definition requires governance contract'
            USING ERRCODE = '23514';
    END IF;
    SELECT * INTO v_resource
    FROM gda_control.resource
    WHERE tenant_id = NEW.tenant_id
      AND resource_urn = NEW.sync_definition_urn;
    IF NOT FOUND
       OR v_resource.resource_kind <> 'sync_definition'
       OR v_resource.authority_system <> 'gda_control'
       OR v_resource.authority_locator <> NEW.sync_definition_urn THEN
        RAISE EXCEPTION 'source sync definition requires its canonical Resource'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;

REVOKE ALL ON FUNCTION gda_control.source_sync_quality_refs_valid(JSONB)
    FROM PUBLIC;
GRANT EXECUTE ON FUNCTION gda_control.source_sync_quality_refs_valid(JSONB)
    TO gda_control_gateway;
REVOKE ALL ON FUNCTION gda_control.guard_source_sync_definition_insert()
    FROM PUBLIC;
