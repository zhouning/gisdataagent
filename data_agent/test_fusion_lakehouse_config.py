"""Tests for MMFE local S3/MinIO lakehouse configuration helpers."""

import unittest


class TestLakehouseConfig(unittest.TestCase):
    def test_build_lakehouse_publish_defaults_for_minio_env(self):
        from data_agent.fusion.lakehouse_config import build_lakehouse_publish_defaults

        env = {
            "CLOUD_STORAGE_PROVIDER": "aws",
            "AWS_ENDPOINT_URL": "http://minio:9000",
            "AWS_ACCESS_KEY_ID": "minio_admin",
            "AWS_SECRET_ACCESS_KEY": "local_dev_minio_secret",
            "AWS_S3_BUCKET": "gis-agent-uploads",
            "MMFE_LAKEHOUSE_BUCKET": "gis-agent-lakehouse",
            "MMFE_ICEBERG_CATALOG": "local",
            "MMFE_ICEBERG_NAMESPACE": "gis.fusion",
            "MMFE_ICEBERG_TABLE": "semantic_products",
        }

        defaults = build_lakehouse_publish_defaults(env)

        self.assertEqual(defaults["object_store"]["endpoint_url"], "http://minio:9000")
        self.assertEqual(defaults["object_store"]["uploads_bucket"], "gis-agent-uploads")
        self.assertEqual(defaults["object_store"]["lakehouse_bucket"], "gis-agent-lakehouse")
        self.assertEqual(defaults["object_store"]["warehouse_uri"], "s3://gis-agent-lakehouse/warehouse")
        self.assertEqual(defaults["object_store"]["stac_catalog_uri"], "s3://gis-agent-lakehouse/catalog/stac")
        self.assertTrue(defaults["object_store"]["path_style_access"])
        self.assertTrue(defaults["object_store"]["credentials_configured"])

        self.assertEqual(defaults["iceberg"]["catalog"], "local")
        self.assertEqual(defaults["iceberg"]["namespace"], "gis.fusion")
        self.assertEqual(defaults["iceberg"]["table"], "semantic_products")
        self.assertEqual(defaults["iceberg"]["warehouse_uri"], "s3://gis-agent-lakehouse/warehouse")
        self.assertEqual(defaults["iceberg"]["partition_by"], ["product_id"])

        self.assertEqual(defaults["stac"]["collection"], "mmfe-fusion-products")
        self.assertEqual(defaults["stac"]["catalog_uri"], "s3://gis-agent-lakehouse/catalog/stac")

    def test_build_sedona_s3a_spark_conf_for_minio(self):
        from data_agent.fusion.lakehouse_config import build_sedona_s3a_spark_conf

        conf = build_sedona_s3a_spark_conf(
            {
                "AWS_ENDPOINT_URL": "http://minio:9000",
                "AWS_ACCESS_KEY_ID": "minio_admin",
                "AWS_SECRET_ACCESS_KEY": "local_dev_minio_secret",
            }
        )

        self.assertEqual(conf["spark.hadoop.fs.s3a.endpoint"], "http://minio:9000")
        self.assertEqual(conf["spark.hadoop.fs.s3a.path.style.access"], "true")
        self.assertEqual(conf["spark.hadoop.fs.s3a.connection.ssl.enabled"], "false")
        self.assertEqual(conf["spark.hadoop.fs.s3a.access.key"], "minio_admin")
        self.assertEqual(conf["spark.hadoop.fs.s3a.secret.key"], "local_dev_minio_secret")

    def test_lakehouse_infrastructure_preflight_warns_for_local_development(self):
        from data_agent.fusion.lakehouse_config import (
            INFRASTRUCTURE_PREFLIGHT_SCHEMA,
            build_lakehouse_infrastructure_preflight,
            build_lakehouse_publish_defaults,
            validate_lakehouse_infrastructure_preflight,
        )

        defaults = build_lakehouse_publish_defaults(
            {
                "AWS_ENDPOINT_URL": "http://minio:9000",
                "AWS_ACCESS_KEY_ID": "minio_admin",
                "AWS_SECRET_ACCESS_KEY": "local_dev_minio_secret",
                "MMFE_LAKEHOUSE_BUCKET": "gis-agent-lakehouse",
            }
        )
        preflight = build_lakehouse_infrastructure_preflight(
            defaults,
            environment="development",
            timestamp="2026-06-17T00:00:00+00:00",
        )
        validation = validate_lakehouse_infrastructure_preflight(preflight)

        self.assertTrue(validation["valid"], validation["errors"])
        self.assertEqual(preflight["schema"], INFRASTRUCTURE_PREFLIGHT_SCHEMA)
        self.assertTrue(preflight["valid"])
        self.assertEqual(preflight["summary"]["fail_count"], 0)
        self.assertEqual(
            {check["check_id"]: check for check in preflight["checks"]}["development_endpoint"]["status"],
            "warn",
        )
        self.assertEqual(
            {check["check_id"]: check for check in preflight["checks"]}["iceberg_warehouse_consistency"]["status"],
            "pass",
        )
        self.assertEqual(
            {check["check_id"]: check for check in preflight["checks"]}["stac_catalog_consistency"]["status"],
            "pass",
        )
        self.assertEqual(
            {check["check_id"]: check for check in preflight["checks"]}["spark_endpoint_consistency"]["status"],
            "pass",
        )
        self.assertEqual(
            {check["check_id"]: check for check in preflight["checks"]}["spark_s3a_credentials"]["status"],
            "pass",
        )
        self.assertEqual(
            {check["check_id"]: check for check in preflight["checks"]}["spark_credentials_consistency"]["status"],
            "pass",
        )
        self.assertEqual(
            {check["check_id"]: check for check in preflight["checks"]}["spark_path_style_consistency"]["status"],
            "pass",
        )
        self.assertEqual(
            {check["check_id"]: check for check in preflight["checks"]}["spark_ssl_consistency"]["status"],
            "pass",
        )
        self.assertNotEqual(
            preflight["sanitized_config"]["object_store"]["secret_access_key"],
            "local_dev_minio_secret",
        )
        self.assertNotEqual(
            preflight["sanitized_config"]["sedona_spark_conf"]["spark.hadoop.fs.s3a.secret.key"],
            "local_dev_minio_secret",
        )
        self.assertEqual(preflight["config_fingerprint"]["algorithm"], "sha256")
        self.assertEqual(
            preflight["config_fingerprint"]["material_version"],
            "mmfe.lakehouse_config_fingerprint.v1",
        )
        self.assertNotIn("local_dev_minio_secret", str(preflight["config_fingerprint"]))
        self.assertNotIn("minio_admin", str(preflight["config_fingerprint"]))

    def test_lakehouse_infrastructure_preflight_blocks_local_production(self):
        from data_agent.fusion.lakehouse_config import (
            build_lakehouse_infrastructure_preflight,
            build_lakehouse_publish_defaults,
        )

        preflight = build_lakehouse_infrastructure_preflight(
            build_lakehouse_publish_defaults(
                {
                    "AWS_ENDPOINT_URL": "http://minio:9000",
                    "AWS_ACCESS_KEY_ID": "minio_admin",
                    "AWS_SECRET_ACCESS_KEY": "local_dev_minio_secret",
                }
            ),
            environment="production",
        )
        checks = {check["check_id"]: check for check in preflight["checks"]}

        self.assertFalse(preflight["valid"])
        self.assertEqual(checks["production_endpoint"]["status"], "fail")
        self.assertEqual(checks["production_credentials"]["status"], "fail")
        self.assertGreaterEqual(preflight["summary"]["critical_fail_count"], 2)

    def test_lakehouse_infrastructure_preflight_passes_remote_production_config(self):
        from data_agent.fusion.lakehouse_config import (
            build_lakehouse_infrastructure_preflight,
            build_lakehouse_publish_defaults,
        )

        defaults = build_lakehouse_publish_defaults(
            {
                "AWS_ENDPOINT_URL": "https://s3.us-east-1.amazonaws.com",
                "AWS_ACCESS_KEY_ID": "AKIAEXAMPLE",
                "AWS_SECRET_ACCESS_KEY": "prod-secret-value",
                "AWS_REGION": "us-east-1",
                "MMFE_LAKEHOUSE_BUCKET": "prod-gis-lakehouse",
                "MMFE_LAKEHOUSE_WAREHOUSE_URI": "s3://prod-gis-lakehouse/warehouse",
                "MMFE_STAC_CATALOG_URI": "s3://prod-gis-lakehouse/catalog/stac",
            }
        )

        preflight = build_lakehouse_infrastructure_preflight(defaults, environment="production")
        checks = {check["check_id"]: check for check in preflight["checks"]}

        self.assertTrue(preflight["valid"])
        self.assertEqual(preflight["summary"]["fail_count"], 0)
        self.assertEqual(checks["production_endpoint"]["status"], "pass")
        self.assertEqual(checks["production_credentials"]["status"], "pass")
        self.assertEqual(
            preflight["sanitized_config"]["object_store"]["access_key_id"],
            "AK***LE",
        )
        self.assertEqual(len(preflight["config_fingerprint"]["value"]), 64)

    def test_lakehouse_infrastructure_preflight_fingerprint_is_stable_and_non_secret(self):
        from data_agent.fusion.lakehouse_config import (
            build_lakehouse_infrastructure_preflight,
            build_lakehouse_publish_defaults,
            validate_lakehouse_infrastructure_preflight,
        )

        defaults = build_lakehouse_publish_defaults(
            {
                "AWS_ENDPOINT_URL": "https://s3.us-east-1.amazonaws.com",
                "AWS_ACCESS_KEY_ID": "AKIAEXAMPLE",
                "AWS_SECRET_ACCESS_KEY": "prod-secret-value",
                "MMFE_LAKEHOUSE_BUCKET": "prod-gis-lakehouse",
            }
        )
        first = build_lakehouse_infrastructure_preflight(
            defaults,
            environment="production",
            timestamp="2026-06-17T00:00:00+00:00",
        )
        second = build_lakehouse_infrastructure_preflight(
            defaults,
            environment="validation",
            timestamp="2026-06-18T00:00:00+00:00",
        )

        self.assertTrue(validate_lakehouse_infrastructure_preflight(first)["valid"])
        self.assertEqual(first["config_fingerprint"]["value"], second["config_fingerprint"]["value"])
        self.assertNotIn("AKIAEXAMPLE", str(first["config_fingerprint"]))
        self.assertNotIn("prod-secret-value", str(first["config_fingerprint"]))

    def test_lakehouse_infrastructure_preflight_fingerprint_changes_when_location_changes(self):
        from data_agent.fusion.lakehouse_config import (
            build_lakehouse_infrastructure_preflight,
            build_lakehouse_publish_defaults,
        )

        base = build_lakehouse_publish_defaults(
            {
                "AWS_ENDPOINT_URL": "https://s3.us-east-1.amazonaws.com",
                "AWS_ACCESS_KEY_ID": "AKIAEXAMPLE",
                "AWS_SECRET_ACCESS_KEY": "prod-secret-value",
                "MMFE_LAKEHOUSE_BUCKET": "prod-gis-lakehouse",
            }
        )
        changed = build_lakehouse_publish_defaults(
            {
                "AWS_ENDPOINT_URL": "https://s3.us-east-1.amazonaws.com",
                "AWS_ACCESS_KEY_ID": "AKIAEXAMPLE",
                "AWS_SECRET_ACCESS_KEY": "prod-secret-value",
                "MMFE_LAKEHOUSE_BUCKET": "prod-gis-lakehouse-v2",
            }
        )

        base_preflight = build_lakehouse_infrastructure_preflight(base, environment="production")
        changed_preflight = build_lakehouse_infrastructure_preflight(changed, environment="production")

        self.assertNotEqual(
            base_preflight["config_fingerprint"]["value"],
            changed_preflight["config_fingerprint"]["value"],
        )

    def test_lakehouse_infrastructure_preflight_blocks_missing_spark_simple_credentials(self):
        from data_agent.fusion.lakehouse_config import (
            build_lakehouse_infrastructure_preflight,
            build_lakehouse_publish_defaults,
        )

        defaults = build_lakehouse_publish_defaults(
            {
                "AWS_ENDPOINT_URL": "https://s3.us-east-1.amazonaws.com",
                "AWS_ACCESS_KEY_ID": "AKIAEXAMPLE",
                "AWS_SECRET_ACCESS_KEY": "prod-secret-value",
                "MMFE_LAKEHOUSE_BUCKET": "prod-gis-lakehouse",
            }
        )
        defaults["sedona_spark_conf"].pop("spark.hadoop.fs.s3a.access.key")
        defaults["sedona_spark_conf"].pop("spark.hadoop.fs.s3a.secret.key")

        preflight = build_lakehouse_infrastructure_preflight(defaults, environment="production")
        checks = {check["check_id"]: check for check in preflight["checks"]}

        self.assertFalse(preflight["valid"])
        self.assertEqual(checks["spark_s3a"]["status"], "pass")
        self.assertEqual(checks["spark_s3a_credentials"]["status"], "fail")
        self.assertFalse(checks["spark_s3a_credentials"]["evidence"]["access_key_configured"])
        self.assertFalse(checks["spark_s3a_credentials"]["evidence"]["secret_key_configured"])

    def test_lakehouse_infrastructure_preflight_blocks_inconsistent_warehouse_bucket(self):
        from data_agent.fusion.lakehouse_config import (
            build_lakehouse_infrastructure_preflight,
            build_lakehouse_publish_defaults,
        )

        defaults = build_lakehouse_publish_defaults(
            {
                "AWS_ENDPOINT_URL": "https://s3.us-east-1.amazonaws.com",
                "AWS_ACCESS_KEY_ID": "AKIAEXAMPLE",
                "AWS_SECRET_ACCESS_KEY": "prod-secret-value",
                "MMFE_LAKEHOUSE_BUCKET": "prod-gis-lakehouse",
                "MMFE_LAKEHOUSE_WAREHOUSE_URI": "s3://other-gis-lakehouse/warehouse",
            }
        )

        preflight = build_lakehouse_infrastructure_preflight(defaults, environment="production")
        checks = {check["check_id"]: check for check in preflight["checks"]}

        self.assertFalse(preflight["valid"])
        self.assertEqual(checks["iceberg_warehouse_consistency"]["status"], "pass")
        self.assertEqual(checks["lakehouse_bucket_consistency"]["status"], "fail")
        self.assertEqual(checks["lakehouse_bucket_consistency"]["severity"], "high")
        self.assertEqual(checks["lakehouse_bucket_consistency"]["evidence"]["lakehouse_bucket"], "prod-gis-lakehouse")
        self.assertEqual(
            checks["lakehouse_bucket_consistency"]["evidence"]["iceberg_warehouse_bucket"],
            "other-gis-lakehouse",
        )

    def test_lakehouse_infrastructure_preflight_blocks_inconsistent_stac_and_spark_endpoints(self):
        from data_agent.fusion.lakehouse_config import (
            build_lakehouse_infrastructure_preflight,
            build_lakehouse_publish_defaults,
        )

        defaults = build_lakehouse_publish_defaults(
            {
                "AWS_ENDPOINT_URL": "https://s3.us-east-1.amazonaws.com",
                "AWS_ACCESS_KEY_ID": "AKIAEXAMPLE",
                "AWS_SECRET_ACCESS_KEY": "prod-secret-value",
                "MMFE_LAKEHOUSE_BUCKET": "prod-gis-lakehouse",
            }
        )
        defaults["stac"]["catalog_uri"] = "s3://other-gis-lakehouse/catalog/stac"
        defaults["sedona_spark_conf"]["spark.hadoop.fs.s3a.endpoint"] = "https://s3.us-west-2.amazonaws.com"

        preflight = build_lakehouse_infrastructure_preflight(defaults, environment="production")
        checks = {check["check_id"]: check for check in preflight["checks"]}

        self.assertFalse(preflight["valid"])
        self.assertEqual(checks["stac_catalog_consistency"]["status"], "fail")
        self.assertEqual(checks["spark_endpoint_consistency"]["status"], "fail")
        self.assertEqual(
            checks["stac_catalog_consistency"]["evidence"]["object_store_stac_catalog_uri"],
            "s3://prod-gis-lakehouse/catalog/stac",
        )
        self.assertEqual(
            checks["spark_endpoint_consistency"]["evidence"]["spark_s3a_endpoint"],
            "https://s3.us-west-2.amazonaws.com",
        )

    def test_lakehouse_infrastructure_preflight_blocks_inconsistent_spark_runtime_settings(self):
        from data_agent.fusion.lakehouse_config import (
            build_lakehouse_infrastructure_preflight,
            build_lakehouse_publish_defaults,
        )

        defaults = build_lakehouse_publish_defaults(
            {
                "AWS_ENDPOINT_URL": "https://s3.us-east-1.amazonaws.com",
                "AWS_ACCESS_KEY_ID": "AKIAEXAMPLE",
                "AWS_SECRET_ACCESS_KEY": "prod-secret-value",
                "MMFE_LAKEHOUSE_BUCKET": "prod-gis-lakehouse",
            }
        )
        defaults["sedona_spark_conf"]["spark.hadoop.fs.s3a.access.key"] = "DIFFERENTKEY"
        defaults["sedona_spark_conf"]["spark.hadoop.fs.s3a.path.style.access"] = "false"
        defaults["sedona_spark_conf"]["spark.hadoop.fs.s3a.connection.ssl.enabled"] = "false"

        preflight = build_lakehouse_infrastructure_preflight(defaults, environment="production")
        checks = {check["check_id"]: check for check in preflight["checks"]}

        self.assertFalse(preflight["valid"])
        self.assertEqual(checks["spark_credentials_consistency"]["status"], "fail")
        self.assertEqual(checks["spark_path_style_consistency"]["status"], "fail")
        self.assertEqual(checks["spark_ssl_consistency"]["status"], "fail")
        self.assertEqual(checks["spark_ssl_consistency"]["evidence"]["expected_spark_ssl_enabled"], "true")
        self.assertEqual(checks["spark_ssl_consistency"]["evidence"]["spark_s3a_ssl_enabled"], "false")

    def test_lakehouse_config_helpers_are_reexported(self):
        from data_agent.fusion import (
            INFRASTRUCTURE_PREFLIGHT_SCHEMA,
            build_default_iceberg_publish_config,
            build_default_stac_publish_config,
            build_lakehouse_infrastructure_preflight,
            build_lakehouse_object_store_config,
            build_lakehouse_publish_defaults,
            build_sedona_s3a_spark_conf,
            validate_lakehouse_infrastructure_preflight,
        )
        from data_agent.fusion_engine import (
            build_lakehouse_infrastructure_preflight as proxy_build_lakehouse_infrastructure_preflight,
            build_lakehouse_publish_defaults as proxy_build_lakehouse_publish_defaults,
        )

        self.assertEqual(INFRASTRUCTURE_PREFLIGHT_SCHEMA, "mmfe.infrastructure_preflight.v1")
        self.assertTrue(callable(build_default_iceberg_publish_config))
        self.assertTrue(callable(build_default_stac_publish_config))
        self.assertTrue(callable(build_lakehouse_infrastructure_preflight))
        self.assertTrue(callable(build_lakehouse_object_store_config))
        self.assertTrue(callable(build_lakehouse_publish_defaults))
        self.assertTrue(callable(build_sedona_s3a_spark_conf))
        self.assertTrue(callable(validate_lakehouse_infrastructure_preflight))
        self.assertTrue(callable(proxy_build_lakehouse_publish_defaults))
        self.assertTrue(callable(proxy_build_lakehouse_infrastructure_preflight))


if __name__ == "__main__":
    unittest.main()
