-- 201: Require immutable object-version evidence for S3 DuckDB Blueprint output.
--
-- The provider success function remains the Run transition authority. These
-- row-local constraints prevent a caller from presenting a stable S3 URI
-- without the exact VersionId/ETag that the provider and gateway verified.

ALTER TABLE gda_control.artifact
    ADD CONSTRAINT ck_gda_artifact_blueprint_duckdb_s3_evidence
    CHECK (
        CASE
            WHEN manifest ->> 'schema' = 'gda.blueprint_duckdb_output.v1'
             AND storage_uri ~ '^s3://'
            THEN
                jsonb_typeof(manifest -> 'storage_evidence') = 'object'
                AND manifest -> 'storage_evidence' ->> 'schema' =
                    'gda.s3_object_version.v1'
                AND NULLIF(
                    btrim(manifest -> 'storage_evidence' ->> 'version_id'),
                    ''
                ) IS NOT NULL
                AND manifest -> 'storage_evidence' ->> 'version_id' <> 'null'
                AND NULLIF(
                    btrim(manifest -> 'storage_evidence' ->> 'etag'),
                    ''
                ) IS NOT NULL
                AND manifest -> 'provider_receipt' ->> 'output_uri' = storage_uri
                AND manifest -> 'provider_receipt' -> 'output_storage_evidence' =
                    manifest -> 'storage_evidence'
            ELSE TRUE
        END
    ) NOT VALID;

ALTER TABLE gda_control.artifact
    VALIDATE CONSTRAINT ck_gda_artifact_blueprint_duckdb_s3_evidence;

ALTER TABLE gda_control.framework_attempt_observation
    ADD CONSTRAINT ck_gda_observation_blueprint_duckdb_s3_evidence
    CHECK (
        CASE
            WHEN evidence ->> 'schema' =
                    'gda.data_product_blueprint_duckdb_provider_receipt.v1'
             AND evidence ->> 'output_uri' ~ '^s3://'
            THEN
                jsonb_typeof(evidence -> 'output_storage_evidence') = 'object'
                AND evidence -> 'output_storage_evidence' ->> 'schema' =
                    'gda.s3_object_version.v1'
                AND NULLIF(
                    btrim(evidence -> 'output_storage_evidence' ->> 'version_id'),
                    ''
                ) IS NOT NULL
                AND evidence -> 'output_storage_evidence' ->> 'version_id' <> 'null'
                AND NULLIF(
                    btrim(evidence -> 'output_storage_evidence' ->> 'etag'),
                    ''
                ) IS NOT NULL
            ELSE TRUE
        END
    ) NOT VALID;

ALTER TABLE gda_control.framework_attempt_observation
    VALIDATE CONSTRAINT ck_gda_observation_blueprint_duckdb_s3_evidence;
