-- 202: Bind DuckDB Spatial extension and portable GeoParquet evidence to success.
--
-- Spatial execution remains optional per Blueprint, but once requested it must
-- be completed by the real DuckDB provider with a preinstalled extension and
-- the cross-engine WKB/SRID/bbox output contract. This does not create a new
-- Run or provider authority; the existing terminal transition remains the only
-- success authority.

ALTER TABLE gda_control.artifact
    ADD CONSTRAINT ck_gda_artifact_blueprint_duckdb_spatial_evidence
    CHECK (
        CASE
            WHEN manifest ->> 'schema' = 'gda.blueprint_duckdb_output.v1'
            THEN
                CASE
                    WHEN manifest -> 'provider_receipt' ->> 'spatial_extension_loaded' = 'true'
                    THEN
                        jsonb_typeof(manifest -> 'provider_receipt' -> 'spatial_extension_evidence') = 'object'
                        AND manifest -> 'provider_receipt' -> 'spatial_extension_evidence' ->> 'schema' =
                            'gda.duckdb_spatial_extension.v1'
                        AND manifest -> 'provider_receipt' -> 'spatial_extension_evidence' ->> 'extension_name' = 'spatial'
                        AND COALESCE(manifest -> 'provider_receipt' -> 'spatial_extension_evidence' ->> 'binary_sha256', '')
                            ~ '^[0-9a-f]{64}$'
                        AND manifest -> 'provider_receipt' -> 'spatial_extension_evidence' ->> 'autoinstall_enabled' = 'false'
                        AND manifest -> 'provider_receipt' -> 'spatial_extension_evidence' ->> 'autoload_enabled' = 'false'
                        AND jsonb_typeof(manifest -> 'provider_receipt' -> 'spatial_output_evidence') = 'object'
                        AND manifest -> 'provider_receipt' -> 'spatial_output_evidence' ->> 'schema' =
                            'gda.geoparquet_spatial_output.v1'
                        AND manifest -> 'provider_receipt' -> 'spatial_output_evidence' ->> 'geometry_column' = 'geometry_wkb'
                        AND manifest -> 'provider_receipt' -> 'spatial_output_evidence' ->> 'srid_column' = 'srid'
                        AND manifest -> 'provider_receipt' -> 'spatial_output_evidence' ->> 'bbox_column' = 'bbox'
                        AND manifest -> 'provider_receipt' -> 'spatial_output_evidence' ->> 'geoparquet_version' = '1.1.0'
                        AND COALESCE(manifest -> 'provider_receipt' -> 'spatial_output_evidence' ->> 'crs_sha256', '')
                            ~ '^[0-9a-f]{64}$'
                        AND COALESCE(manifest -> 'provider_receipt' -> 'spatial_output_evidence' ->> 'geo_metadata_sha256', '')
                            ~ '^[0-9a-f]{64}$'
                    WHEN manifest -> 'provider_receipt' ->> 'spatial_extension_loaded' = 'false'
                    THEN
                        manifest -> 'provider_receipt' -> 'spatial_extension_evidence' IS NULL
                        AND manifest -> 'provider_receipt' -> 'spatial_output_evidence' IS NULL
                    ELSE FALSE
                END
            ELSE TRUE
        END
    ) NOT VALID;

ALTER TABLE gda_control.artifact
    VALIDATE CONSTRAINT ck_gda_artifact_blueprint_duckdb_spatial_evidence;

ALTER TABLE gda_control.framework_attempt_observation
    ADD CONSTRAINT ck_gda_observation_blueprint_duckdb_spatial_evidence
    CHECK (
        CASE
            WHEN evidence ->> 'schema' = 'gda.data_product_blueprint_duckdb_provider_receipt.v1'
            THEN
                CASE
                    WHEN evidence ->> 'spatial_extension_loaded' = 'true'
                    THEN
                        jsonb_typeof(evidence -> 'spatial_extension_evidence') = 'object'
                        AND evidence -> 'spatial_extension_evidence' ->> 'schema' =
                            'gda.duckdb_spatial_extension.v1'
                        AND evidence -> 'spatial_extension_evidence' ->> 'extension_name' = 'spatial'
                        AND COALESCE(evidence -> 'spatial_extension_evidence' ->> 'binary_sha256', '')
                            ~ '^[0-9a-f]{64}$'
                        AND evidence -> 'spatial_extension_evidence' ->> 'autoinstall_enabled' = 'false'
                        AND evidence -> 'spatial_extension_evidence' ->> 'autoload_enabled' = 'false'
                        AND jsonb_typeof(evidence -> 'spatial_output_evidence') = 'object'
                        AND evidence -> 'spatial_output_evidence' ->> 'schema' =
                            'gda.geoparquet_spatial_output.v1'
                        AND evidence -> 'spatial_output_evidence' ->> 'geometry_column' = 'geometry_wkb'
                        AND evidence -> 'spatial_output_evidence' ->> 'srid_column' = 'srid'
                        AND evidence -> 'spatial_output_evidence' ->> 'bbox_column' = 'bbox'
                        AND evidence -> 'spatial_output_evidence' ->> 'geoparquet_version' = '1.1.0'
                        AND COALESCE(evidence -> 'spatial_output_evidence' ->> 'crs_sha256', '')
                            ~ '^[0-9a-f]{64}$'
                        AND COALESCE(evidence -> 'spatial_output_evidence' ->> 'geo_metadata_sha256', '')
                            ~ '^[0-9a-f]{64}$'
                    WHEN evidence ->> 'spatial_extension_loaded' = 'false'
                    THEN
                        evidence -> 'spatial_extension_evidence' IS NULL
                        AND evidence -> 'spatial_output_evidence' IS NULL
                    ELSE FALSE
                END
            ELSE TRUE
        END
    ) NOT VALID;

ALTER TABLE gda_control.framework_attempt_observation
    VALIDATE CONSTRAINT ck_gda_observation_blueprint_duckdb_spatial_evidence;

CREATE OR REPLACE FUNCTION gda_control.enforce_blueprint_duckdb_spatial_success()
RETURNS TRIGGER
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, gda_control
SET row_security = on
AS $$
DECLARE
    v_definition JSONB;
    v_receipt JSONB;
    v_spatial_required BOOLEAN;
    v_expected_srid TEXT;
BEGIN
    IF NEW.to_status <> 'succeeded'
       OR NEW.details ->> 'schema' <> 'gda.run_success_evidence.v1' THEN
        RETURN NEW;
    END IF;

    SELECT definition.definition_document, observation.evidence
      INTO v_definition, v_receipt
      FROM gda_control.platform_run AS run
      JOIN gda_control.platform_definition_version AS definition
        ON definition.tenant_id = run.tenant_id
       AND definition.definition_version_id = run.definition_version_id
      LEFT JOIN gda_control.framework_attempt_observation AS observation
        ON observation.tenant_id = run.tenant_id
       AND observation.run_id = run.run_id
       AND observation.observation_id = (NEW.details ->> 'attempt_observation_id')::uuid
     WHERE run.tenant_id = NEW.tenant_id
       AND run.run_id = NEW.run_id;

    IF v_definition IS NULL
       OR v_definition -> 'pipeline' ->> 'engine' IS DISTINCT FROM 'duckdb' THEN
        RETURN NEW;
    END IF;

    v_spatial_required := COALESCE(
        (v_definition -> 'pipeline' ->> 'require_spatial') = 'true',
        FALSE
    );
    v_expected_srid := v_definition -> 'pipeline' ->> 'spatial_output_srid';

    IF v_spatial_required THEN
        IF v_expected_srid IS NULL
           OR v_receipt ->> 'schema' IS DISTINCT FROM
                'gda.data_product_blueprint_duckdb_provider_receipt.v1'
           OR v_receipt ->> 'spatial_extension_loaded' IS DISTINCT FROM 'true'
           OR v_receipt -> 'spatial_extension_evidence' ->> 'schema' IS DISTINCT FROM
                'gda.duckdb_spatial_extension.v1'
           OR v_receipt -> 'spatial_output_evidence' ->> 'schema' IS DISTINCT FROM
                'gda.geoparquet_spatial_output.v1'
           OR v_receipt -> 'spatial_output_evidence' ->> 'srid' IS DISTINCT FROM v_expected_srid
        THEN
            RAISE EXCEPTION 'DuckDB Spatial Blueprint success lacks bound extension and output evidence'
                USING ERRCODE = '23514';
        END IF;
    ELSIF v_receipt ->> 'schema' = 'gda.data_product_blueprint_duckdb_provider_receipt.v1'
       AND (
            v_receipt ->> 'spatial_extension_loaded' IS DISTINCT FROM 'false'
            OR v_receipt -> 'spatial_extension_evidence' IS NOT NULL
            OR v_receipt -> 'spatial_output_evidence' IS NOT NULL
       ) THEN
        RAISE EXCEPTION 'non-spatial DuckDB Blueprint success cannot carry spatial evidence'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_gda_enforce_blueprint_duckdb_spatial_success
    ON gda_control.platform_run_event;

CREATE TRIGGER trg_gda_enforce_blueprint_duckdb_spatial_success
BEFORE INSERT ON gda_control.platform_run_event
FOR EACH ROW
EXECUTE FUNCTION gda_control.enforce_blueprint_duckdb_spatial_success();
