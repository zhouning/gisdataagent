"""Tests for MMFE analytical lakehouse publisher contracts."""

import unittest


def _semantic_manifest() -> dict:
    return {
        "product_type": "semantic_fusion_product",
        "version": "1.1",
        "product_id": "sfp-lakehouse-test",
        "business_output": {
            "path": "s3://geo-lake/curated/fusion/run-001/fused.parquet",
            "format": "GeoParquet",
            "row_count": 2,
            "column_count": 4,
            "crs": "EPSG:4326",
        },
        "sources": [
            {"path": "s3://geo-lake/raw/parcels/date=2026-06-16/data.parquet", "data_type": "vector"},
            {"path": "s3://geo-lake/raw/zoning/date=2026-06-16/data.parquet", "data_type": "vector"},
        ],
        "lineage": {
            "operation": "spatial_join",
            "source_count": 2,
        },
        "quality": {
            "score": 0.97,
            "warnings": [],
        },
        "ai_metadata": {
            "embedding_ready": True,
            "chunks": [
                {
                    "chunk_id": "fusion:product",
                    "text": "Semantic fusion product generated with spatial_join.",
                    "metadata": {"strategy": "spatial_join"},
                }
            ],
        },
    }


def _semantic_manifest_with_lakehouse() -> dict:
    manifest = _semantic_manifest()
    manifest["lakehouse"] = {
        "iceberg": {
            "storage_layer": "analytical_lakehouse",
            "object_store": "s3",
            "catalog": "prod",
            "namespace": "gis.fusion",
            "table": "semantic_products",
            "table_identifier": "prod.gis.fusion.semantic_products",
            "warehouse_uri": "s3://geo-lake/warehouse",
            "snapshot_id": "snap-001",
            "spatial_engine": "sedona",
        }
    }
    return manifest


def _production_ready_semantic_manifest() -> dict:
    manifest = _semantic_manifest()
    manifest["mmfe_bundle"] = {
        "semantic_diagnostic_summary": {
            "readiness_score": 1.0,
            "validation_ready": True,
            "production_ready": True,
            "status": "production_ready",
            "check_count": 1,
            "pass_count": 1,
            "warn_count": 0,
            "fail_count": 0,
        },
        "semantic_diagnostic_top_gaps": [],
    }
    return manifest


def _validation_only_semantic_manifest() -> dict:
    manifest = _semantic_manifest()
    manifest["mmfe_bundle"] = {
        "semantic_diagnostic_summary": {
            "readiness_score": 0.9,
            "validation_ready": True,
            "production_ready": False,
            "status": "validation_ready_with_production_gaps",
            "check_count": 2,
            "pass_count": 1,
            "warn_count": 1,
            "fail_count": 0,
        },
        "semantic_diagnostic_top_gaps": [
            {
                "check_id": "production_authority",
                "status": "warn",
                "severity": "critical",
                "message_zh": "进入生产时必须替换为真实权威自然资源数据。",
            }
        ],
    }
    return manifest


class TestLakehousePublisher(unittest.TestCase):
    def test_build_iceberg_publish_spec_from_semantic_manifest(self):
        from data_agent.fusion.lakehouse_publisher import (
            ICEBERG_PUBLISH_SCHEMA,
            build_iceberg_publish_spec,
        )

        spec = build_iceberg_publish_spec(
            _semantic_manifest(),
            catalog="prod",
            namespace="gis.fusion",
            table="semantic_products",
            warehouse_uri="s3://geo-lake/warehouse",
            object_store="s3",
            spatial_engine="sedona",
            partition_by=["product_id"],
            metadata={"run_id": "lakehouse-test"},
        )

        self.assertEqual(spec["schema"], ICEBERG_PUBLISH_SCHEMA)
        self.assertEqual(spec["target"], "iceberg")
        self.assertEqual(spec["object_store"], "s3")
        self.assertEqual(spec["warehouse_uri"], "s3://geo-lake/warehouse")
        self.assertEqual(spec["catalog"], "prod")
        self.assertEqual(spec["namespace"], "gis.fusion")
        self.assertEqual(spec["table"], "semantic_products")
        self.assertEqual(spec["table_identifier"], "prod.gis.fusion.semantic_products")
        self.assertEqual(spec["spatial_engine"], "sedona")
        self.assertEqual(spec["partition_by"], ["product_id"])
        self.assertEqual(spec["product_id"], "sfp-lakehouse-test")
        self.assertEqual(spec["business_output"]["format"], "GeoParquet")
        self.assertEqual(spec["business_output"]["path"], "s3://geo-lake/curated/fusion/run-001/fused.parquet")
        self.assertEqual(spec["lineage"]["operation"], "spatial_join")
        self.assertEqual(spec["metadata"]["run_id"], "lakehouse-test")

    def test_run_iceberg_publish_uses_injected_executor(self):
        from data_agent.fusion.lakehouse_publisher import (
            build_iceberg_publish_spec,
            build_iceberg_publisher,
            run_iceberg_publish,
        )

        spec = build_iceberg_publish_spec(
            _semantic_manifest(),
            catalog="prod",
            namespace="gis.fusion",
            table="semantic_products",
            warehouse_uri="s3://geo-lake/warehouse",
            spatial_engine="sedona",
        )
        calls = []

        def executor(payload):
            calls.append(payload)
            return {"committed": True, "snapshot_id": "snap-001", "rows_written": payload["row_count"]}

        publisher = build_iceberg_publisher(executor=executor)

        result = run_iceberg_publish(spec, publisher=publisher)

        self.assertTrue(result["valid"])
        self.assertEqual(result["target"], "iceberg")
        self.assertEqual(result["table_identifier"], "prod.gis.fusion.semantic_products")
        self.assertEqual(result["rows_written"], 2)
        self.assertEqual(calls[0]["target"], "iceberg")
        self.assertEqual(calls[0]["storage_layer"], "analytical_lakehouse")
        self.assertEqual(calls[0]["object_store"], "s3")
        self.assertEqual(calls[0]["spatial_engine"], "sedona")
        self.assertEqual(calls[0]["source_path"], "s3://geo-lake/curated/fusion/run-001/fused.parquet")
        self.assertEqual(calls[0]["source_format"], "GeoParquet")
        self.assertEqual(calls[0]["row_count"], 2)
        self.assertEqual(calls[0]["lineage"]["operation"], "spatial_join")
        self.assertEqual(result["backend_result"]["snapshot_id"], "snap-001")

    def test_run_iceberg_publish_returns_manifest_patch_for_dual_lake_lineage(self):
        from data_agent.fusion.lakehouse_publisher import (
            build_iceberg_publish_spec,
            build_iceberg_publisher,
            run_iceberg_publish,
        )

        spec = build_iceberg_publish_spec(
            _semantic_manifest(),
            catalog="prod",
            namespace="gis.fusion",
            table="semantic_products",
            warehouse_uri="s3://geo-lake/warehouse",
            spatial_engine="sedona",
            partition_by=["product_id"],
        )
        publisher = build_iceberg_publisher(
            executor=lambda payload: {
                "committed": True,
                "snapshot_id": "snap-001",
                "rows_written": payload["row_count"],
                "partition": {"product_id": payload["product_id"]},
            }
        )

        result = run_iceberg_publish(spec, publisher=publisher)

        self.assertTrue(result["valid"])
        patch = result["manifest_patch"]
        iceberg = patch["lakehouse"]["iceberg"]
        self.assertEqual(iceberg["storage_layer"], "analytical_lakehouse")
        self.assertEqual(iceberg["object_store"], "s3")
        self.assertEqual(iceberg["catalog"], "prod")
        self.assertEqual(iceberg["namespace"], "gis.fusion")
        self.assertEqual(iceberg["table"], "semantic_products")
        self.assertEqual(iceberg["table_identifier"], "prod.gis.fusion.semantic_products")
        self.assertEqual(iceberg["warehouse_uri"], "s3://geo-lake/warehouse")
        self.assertEqual(iceberg["snapshot_id"], "snap-001")
        self.assertEqual(iceberg["partition"], {"product_id": "sfp-lakehouse-test"})
        self.assertEqual(iceberg["spatial_engine"], "sedona")

    def test_apply_iceberg_manifest_patch_merges_without_mutating_original(self):
        from data_agent.fusion.lakehouse_publisher import (
            apply_iceberg_manifest_patch,
            build_iceberg_publish_spec,
            build_iceberg_publisher,
            run_iceberg_publish,
        )

        manifest = _semantic_manifest()
        spec = build_iceberg_publish_spec(
            manifest,
            catalog="prod",
            namespace="gis.fusion",
            table="semantic_products",
            warehouse_uri="s3://geo-lake/warehouse",
        )
        result = run_iceberg_publish(
            spec,
            publisher=build_iceberg_publisher(
                executor=lambda payload: {"snapshot_id": "snap-001", "rows_written": payload["row_count"]}
            ),
        )

        updated = apply_iceberg_manifest_patch(manifest, result["manifest_patch"])

        self.assertNotIn("lakehouse", manifest)
        self.assertEqual(updated["lakehouse"]["iceberg"]["snapshot_id"], "snap-001")
        self.assertEqual(updated["lakehouse"]["iceberg"]["table_identifier"], "prod.gis.fusion.semantic_products")
        self.assertEqual(updated["product_id"], "sfp-lakehouse-test")

    def test_iceberg_publish_requires_executor_and_valid_spec(self):
        from data_agent.fusion.lakehouse_publisher import (
            build_iceberg_publish_spec,
            build_iceberg_publisher,
            run_iceberg_publish,
            validate_iceberg_publish_spec,
        )

        invalid_errors = validate_iceberg_publish_spec(
            {
                "schema": "mmfe.iceberg_publish.v1",
                "target": "iceberg",
                "catalog": "",
                "namespace": "",
                "table": "",
                "warehouse_uri": "",
                "business_output": {"path": "", "format": ""},
            }
        )

        self.assertTrue(any("catalog" in error for error in invalid_errors))
        self.assertTrue(any("namespace" in error for error in invalid_errors))
        self.assertTrue(any("table" in error for error in invalid_errors))
        self.assertTrue(any("warehouse_uri" in error for error in invalid_errors))
        self.assertTrue(any("business_output.path" in error for error in invalid_errors))

        spec = build_iceberg_publish_spec(
            _semantic_manifest(),
            catalog="prod",
            namespace="gis.fusion",
            table="semantic_products",
            warehouse_uri="s3://geo-lake/warehouse",
        )
        publisher = build_iceberg_publisher()

        result = run_iceberg_publish(spec, publisher=publisher)

        self.assertFalse(result["valid"])
        self.assertTrue(any("executor is required" in error for error in result["errors"]))

    def test_build_sedona_iceberg_runner_spec_for_spatial_sql(self):
        from data_agent.fusion.lakehouse_publisher import (
            SEDONA_ICEBERG_RUNNER_SCHEMA,
            build_sedona_iceberg_runner_spec,
        )

        spec = build_sedona_iceberg_runner_spec(
            task="spatial_join",
            catalog="prod",
            warehouse_uri="s3://geo-lake/warehouse",
            input_tables=["prod.raw.parcels", "prod.raw.zoning"],
            output_table="prod.gis.fusion.semantic_products",
            sql="SELECT /* sedona */ * FROM parcels p JOIN zoning z ON ST_Intersects(p.geom, z.geom)",
            spatial_engine="sedona",
            spark_conf={"spark.sql.catalog.prod": "org.apache.iceberg.spark.SparkCatalog"},
            metadata={"run_id": "sedona-test"},
        )

        self.assertEqual(spec["schema"], SEDONA_ICEBERG_RUNNER_SCHEMA)
        self.assertEqual(spec["task"], "spatial_join")
        self.assertEqual(spec["target"], "iceberg")
        self.assertEqual(spec["spatial_engine"], "sedona")
        self.assertEqual(spec["catalog"], "prod")
        self.assertEqual(spec["warehouse_uri"], "s3://geo-lake/warehouse")
        self.assertEqual(spec["input_tables"], ["prod.raw.parcels", "prod.raw.zoning"])
        self.assertEqual(spec["output_table"], "prod.gis.fusion.semantic_products")
        self.assertIn("ST_Intersects", spec["sql"])
        self.assertEqual(spec["spark_conf"]["spark.sql.catalog.prod"], "org.apache.iceberg.spark.SparkCatalog")
        self.assertEqual(spec["metadata"]["run_id"], "sedona-test")

    def test_run_sedona_iceberg_job_uses_injected_executor(self):
        from data_agent.fusion.lakehouse_publisher import (
            build_sedona_iceberg_runner_spec,
            run_sedona_iceberg_job,
        )

        spec = build_sedona_iceberg_runner_spec(
            task="spatial_join",
            catalog="prod",
            warehouse_uri="s3://geo-lake/warehouse",
            input_tables=["prod.raw.parcels", "prod.raw.zoning"],
            output_table="prod.gis.fusion.semantic_products",
            sql="SELECT * FROM parcels p JOIN zoning z ON ST_Intersects(p.geom, z.geom)",
        )
        calls = []

        def executor(payload):
            calls.append(payload)
            return {"returncode": 0, "rows_written": 2, "snapshot_id": "snap-002", "stdout": "ok", "stderr": ""}

        result = run_sedona_iceberg_job(spec, executor=executor)

        self.assertTrue(result["valid"])
        self.assertEqual(result["target"], "iceberg")
        self.assertEqual(result["spatial_engine"], "sedona")
        self.assertEqual(result["output_table"], "prod.gis.fusion.semantic_products")
        self.assertEqual(result["rows_written"], 2)
        self.assertEqual(result["snapshot_id"], "snap-002")
        self.assertEqual(calls[0]["schema"], spec["schema"])
        self.assertEqual(calls[0]["input_tables"], ["prod.raw.parcels", "prod.raw.zoning"])
        self.assertIn("ST_Intersects", calls[0]["sql"])

    def test_sedona_iceberg_runner_requires_valid_spec_and_executor(self):
        from data_agent.fusion.lakehouse_publisher import (
            build_sedona_iceberg_runner_spec,
            run_sedona_iceberg_job,
            validate_sedona_iceberg_runner_spec,
        )

        errors = validate_sedona_iceberg_runner_spec(
            {
                "schema": "mmfe.sedona_iceberg_runner.v1",
                "target": "iceberg",
                "spatial_engine": "sedona",
                "task": "",
                "catalog": "",
                "warehouse_uri": "",
                "input_tables": [],
                "output_table": "",
                "sql": "",
            }
        )

        self.assertTrue(any("task" in error for error in errors))
        self.assertTrue(any("catalog" in error for error in errors))
        self.assertTrue(any("warehouse_uri" in error for error in errors))
        self.assertTrue(any("input_tables" in error for error in errors))
        self.assertTrue(any("output_table" in error for error in errors))
        self.assertTrue(any("sql" in error for error in errors))

        spec = build_sedona_iceberg_runner_spec(
            task="spatial_join",
            catalog="prod",
            warehouse_uri="s3://geo-lake/warehouse",
            input_tables=["prod.raw.parcels"],
            output_table="prod.gis.fusion.semantic_products",
            sql="SELECT * FROM parcels",
        )

        result = run_sedona_iceberg_job(spec)

        self.assertFalse(result["valid"])
        self.assertTrue(any("executor is required" in error for error in result["errors"]))

    def test_lakehouse_publisher_helpers_are_reexported(self):
        from data_agent.fusion import (
            SEDONA_ICEBERG_RUNNER_SCHEMA,
            apply_iceberg_manifest_patch,
            build_iceberg_publish_spec,
            build_iceberg_publisher,
            build_sedona_iceberg_runner_spec,
            run_iceberg_publish,
            run_sedona_iceberg_job,
            validate_sedona_iceberg_runner_spec,
        )
        from data_agent.fusion_engine import (
            SEDONA_ICEBERG_RUNNER_SCHEMA as proxy_sedona_runner_schema,
            apply_iceberg_manifest_patch as proxy_apply_iceberg_manifest_patch,
            build_iceberg_publish_spec as proxy_build_iceberg_publish_spec,
            build_iceberg_publisher as proxy_build_iceberg_publisher,
            build_sedona_iceberg_runner_spec as proxy_build_sedona_iceberg_runner_spec,
            run_iceberg_publish as proxy_run_iceberg_publish,
            run_sedona_iceberg_job as proxy_run_sedona_iceberg_job,
        )

        self.assertEqual(SEDONA_ICEBERG_RUNNER_SCHEMA, proxy_sedona_runner_schema)
        self.assertTrue(callable(apply_iceberg_manifest_patch))
        self.assertTrue(callable(proxy_apply_iceberg_manifest_patch))
        self.assertTrue(callable(build_iceberg_publish_spec))
        self.assertTrue(callable(build_iceberg_publisher))
        self.assertTrue(callable(build_sedona_iceberg_runner_spec))
        self.assertTrue(callable(proxy_build_sedona_iceberg_runner_spec))
        self.assertTrue(callable(run_iceberg_publish))
        self.assertTrue(callable(run_sedona_iceberg_job))
        self.assertTrue(callable(proxy_run_sedona_iceberg_job))
        self.assertTrue(callable(validate_sedona_iceberg_runner_spec))
        self.assertTrue(callable(proxy_build_iceberg_publish_spec))
        self.assertTrue(callable(proxy_build_iceberg_publisher))
        self.assertTrue(callable(proxy_run_iceberg_publish))

    def test_build_stac_publish_spec_from_semantic_manifest(self):
        from data_agent.fusion.lakehouse_publisher import (
            STAC_PUBLISH_SCHEMA,
            build_stac_publish_spec,
        )

        spec = build_stac_publish_spec(
            _semantic_manifest_with_lakehouse(),
            collection="mmfe-fusion-products",
            catalog_uri="s3://geo-lake/catalog/stac",
            item_datetime="2026-06-16T00:00:00Z",
            bbox=[100.0, 20.0, 101.0, 21.0],
            geometry={
                "type": "Polygon",
                "coordinates": [
                    [[100.0, 20.0], [101.0, 20.0], [101.0, 21.0], [100.0, 21.0], [100.0, 20.0]]
                ],
            },
            metadata={"run_id": "stac-test"},
        )

        self.assertEqual(spec["schema"], STAC_PUBLISH_SCHEMA)
        self.assertEqual(spec["target"], "stac")
        self.assertEqual(spec["storage_layer"], "discovery_catalog")
        self.assertEqual(spec["collection"], "mmfe-fusion-products")
        self.assertEqual(spec["catalog_uri"], "s3://geo-lake/catalog/stac")
        self.assertEqual(spec["product_id"], "sfp-lakehouse-test")
        self.assertEqual(spec["metadata"]["run_id"], "stac-test")

        item = spec["item"]
        self.assertEqual(item["type"], "Feature")
        self.assertEqual(item["stac_version"], "1.0.0")
        self.assertEqual(item["id"], "sfp-lakehouse-test")
        self.assertEqual(item["collection"], "mmfe-fusion-products")
        self.assertEqual(item["bbox"], [100.0, 20.0, 101.0, 21.0])
        self.assertEqual(item["geometry"]["type"], "Polygon")
        self.assertEqual(item["properties"]["datetime"], "2026-06-16T00:00:00Z")
        self.assertEqual(item["properties"]["mmfe:product_type"], "semantic_fusion_product")
        self.assertEqual(item["properties"]["mmfe:product_version"], "1.1")
        self.assertEqual(item["properties"]["proj:epsg"], 4326)
        self.assertEqual(item["properties"]["mmfe:quality_score"], 0.97)
        self.assertEqual(item["assets"]["data"]["href"], "s3://geo-lake/curated/fusion/run-001/fused.parquet")
        self.assertEqual(item["assets"]["data"]["type"], "application/vnd.apache.parquet")
        self.assertEqual(item["assets"]["data"]["roles"], ["data"])
        self.assertEqual(item["properties"]["mmfe:authoritative_lakehouse"]["target"], "iceberg")
        self.assertEqual(
            item["properties"]["mmfe:authoritative_lakehouse"]["table_identifier"],
            "prod.gis.fusion.semantic_products",
        )

    def test_build_stac_publish_spec_can_point_to_materialized_s3_asset(self):
        from data_agent.fusion.lakehouse_publisher import build_stac_publish_spec

        spec = build_stac_publish_spec(
            _semantic_manifest(),
            collection="mmfe-fusion-products",
            catalog_uri="s3://geo-lake/catalog/stac",
            asset_href="s3://geo-lake/curated/mmfe/sfp-lakehouse-test/fused.parquet",
        )

        self.assertEqual(
            spec["item"]["assets"]["data"]["href"],
            "s3://geo-lake/curated/mmfe/sfp-lakehouse-test/fused.parquet",
        )
        self.assertEqual(spec["item"]["assets"]["data"]["type"], "application/vnd.apache.parquet")

    def test_run_stac_publish_uses_injected_executor(self):
        from data_agent.fusion.lakehouse_publisher import (
            build_stac_publish_spec,
            build_stac_publisher,
            run_stac_publish,
        )

        spec = build_stac_publish_spec(
            _semantic_manifest_with_lakehouse(),
            collection="mmfe-fusion-products",
            catalog_uri="s3://geo-lake/catalog/stac",
            item_datetime="2026-06-16T00:00:00Z",
            bbox=[100.0, 20.0, 101.0, 21.0],
        )
        calls = []

        def executor(payload):
            calls.append(payload)
            return {
                "published": True,
                "item_href": "s3://geo-lake/catalog/stac/mmfe-fusion-products/sfp-lakehouse-test.json",
            }

        result = run_stac_publish(spec, publisher=build_stac_publisher(executor=executor))

        self.assertTrue(result["valid"])
        self.assertEqual(result["target"], "stac")
        self.assertEqual(result["collection"], "mmfe-fusion-products")
        self.assertEqual(result["item_id"], "sfp-lakehouse-test")
        self.assertEqual(result["published_count"], 1)
        self.assertEqual(calls[0]["target"], "stac")
        self.assertEqual(calls[0]["catalog_uri"], "s3://geo-lake/catalog/stac")
        self.assertEqual(calls[0]["collection"], "mmfe-fusion-products")
        self.assertEqual(calls[0]["item"]["id"], "sfp-lakehouse-test")
        self.assertEqual(calls[0]["assets"]["data"]["href"], "s3://geo-lake/curated/fusion/run-001/fused.parquet")
        self.assertEqual(calls[0]["properties"]["mmfe:authoritative_lakehouse"]["snapshot_id"], "snap-001")
        self.assertEqual(
            result["manifest_patch"]["catalog"]["stac"]["item_href"],
            "s3://geo-lake/catalog/stac/mmfe-fusion-products/sfp-lakehouse-test.json",
        )

    def test_stac_publish_requires_executor_and_valid_spec(self):
        from data_agent.fusion.lakehouse_publisher import (
            build_stac_publish_spec,
            build_stac_publisher,
            run_stac_publish,
            validate_stac_publish_spec,
        )

        errors = validate_stac_publish_spec(
            {
                "schema": "mmfe.stac_publish.v1",
                "target": "stac",
                "collection": "",
                "product_id": "",
                "item": {"type": "Feature", "assets": {}},
            }
        )

        self.assertTrue(any("collection" in error for error in errors))
        self.assertTrue(any("product_id" in error for error in errors))
        self.assertTrue(any("item.id" in error for error in errors))
        self.assertTrue(any("assets" in error for error in errors))

        spec = build_stac_publish_spec(
            _semantic_manifest(),
            collection="mmfe-fusion-products",
            catalog_uri="s3://geo-lake/catalog/stac",
        )
        result = run_stac_publish(spec, publisher=build_stac_publisher())

        self.assertFalse(result["valid"])
        self.assertTrue(any("executor is required" in error for error in result["errors"]))

    def test_stac_publish_can_use_s3_executor_adapter(self):
        from data_agent.fusion.lakehouse_publisher import (
            build_stac_publish_spec,
            build_stac_publisher,
            run_stac_publish,
        )

        spec = build_stac_publish_spec(
            _semantic_manifest_with_lakehouse(),
            collection="mmfe-fusion-products",
            catalog_uri="s3://gis-agent-lakehouse/catalog/stac",
            item_datetime="2026-06-16T00:00:00Z",
        )

        def s3_executor(payload):
            return {
                "published": True,
                "published_count": 1,
                "item_href": f"{payload['catalog_uri']}/{payload['collection']}/{payload['item_id']}.json",
                "bucket": "gis-agent-lakehouse",
                "key": f"catalog/stac/{payload['collection']}/{payload['item_id']}.json",
            }

        result = run_stac_publish(spec, publisher=build_stac_publisher(executor=s3_executor))

        self.assertTrue(result["valid"])
        self.assertEqual(result["published_count"], 1)
        self.assertEqual(
            result["manifest_patch"]["catalog"]["stac"]["item_href"],
            "s3://gis-agent-lakehouse/catalog/stac/mmfe-fusion-products/sfp-lakehouse-test.json",
        )
        self.assertEqual(result["backend_result"]["bucket"], "gis-agent-lakehouse")

    def test_stac_publisher_helpers_are_reexported(self):
        from data_agent.fusion import (
            STAC_PUBLISH_SCHEMA,
            build_s3_stac_executor,
            build_stac_publish_spec,
            build_stac_publisher,
            publish_stac_payload_to_s3,
            run_stac_publish,
            validate_stac_publish_spec,
        )
        from data_agent.fusion_engine import (
            STAC_PUBLISH_SCHEMA as proxy_stac_publish_schema,
            build_s3_stac_executor as proxy_build_s3_stac_executor,
            build_stac_publish_spec as proxy_build_stac_publish_spec,
            build_stac_publisher as proxy_build_stac_publisher,
            publish_stac_payload_to_s3 as proxy_publish_stac_payload_to_s3,
            run_stac_publish as proxy_run_stac_publish,
            validate_stac_publish_spec as proxy_validate_stac_publish_spec,
        )

        self.assertEqual(STAC_PUBLISH_SCHEMA, proxy_stac_publish_schema)
        self.assertTrue(callable(build_stac_publish_spec))
        self.assertTrue(callable(build_stac_publisher))
        self.assertTrue(callable(build_s3_stac_executor))
        self.assertTrue(callable(publish_stac_payload_to_s3))
        self.assertTrue(callable(run_stac_publish))
        self.assertTrue(callable(validate_stac_publish_spec))
        self.assertTrue(callable(proxy_build_stac_publish_spec))
        self.assertTrue(callable(proxy_build_stac_publisher))
        self.assertTrue(callable(proxy_build_s3_stac_executor))
        self.assertTrue(callable(proxy_publish_stac_payload_to_s3))
        self.assertTrue(callable(proxy_run_stac_publish))
        self.assertTrue(callable(proxy_validate_stac_publish_spec))

    def test_publish_semantic_product_routes_lakehouse_catalog_and_vector_targets(self):
        from data_agent.fusion.lakehouse_publisher import (
            build_iceberg_publisher,
            build_stac_publisher,
            publish_semantic_product,
        )
        from data_agent.fusion.semantic_publisher import build_lancedb_publisher

        calls = []

        def iceberg_executor(payload):
            calls.append(("iceberg", payload))
            return {
                "rows_written": payload["row_count"],
                "snapshot_id": "snap-003",
                "partition": {"product_id": payload["product_id"]},
            }

        def stac_executor(payload):
            calls.append(("stac", payload))
            return {"item_href": f"{payload['catalog_uri']}/{payload['collection']}/{payload['item_id']}.json"}

        def lancedb_executor(payload):
            calls.append(("lancedb", payload))
            return {"inserted": len(payload["rows"])}

        result = publish_semantic_product(
            _production_ready_semantic_manifest(),
            targets=["iceberg", "stac", "lancedb"],
            iceberg={
                "catalog": "prod",
                "namespace": "gis.fusion",
                "table": "semantic_products",
                "warehouse_uri": "s3://geo-lake/warehouse",
                "publisher": build_iceberg_publisher(executor=iceberg_executor),
            },
            stac={
                "collection": "mmfe-fusion-products",
                "catalog_uri": "s3://geo-lake/catalog/stac",
                "item_datetime": "2026-06-16T00:00:00Z",
                "bbox": [100.0, 20.0, 101.0, 21.0],
                "publisher": build_stac_publisher(executor=stac_executor),
            },
            vector={
                "target": "lancedb",
                "collection": "mmfe_products",
                "embedding_model": "mock-embedder",
                "embedder": lambda texts, **kwargs: [[1.0, 0.0] for _ in texts],
                "publisher": build_lancedb_publisher(
                    dataset_uri="file:///tmp/mmfe_vectors.lance",
                    table="semantic_products",
                    executor=lancedb_executor,
                ),
            },
        )

        self.assertTrue(result["valid"])
        self.assertEqual(result["publish_environment"], "production")
        self.assertTrue(result["production_gate"]["valid"])
        self.assertTrue(result["production_gate"]["diagnostic_summary"]["production_ready"])
        self.assertTrue(result["infrastructure_preflight"]["valid"])
        self.assertEqual([name for name, _ in calls], ["iceberg", "stac", "lancedb"])
        self.assertEqual(result["targets"], ["iceberg", "stac", "lancedb"])
        self.assertEqual(result["results"]["iceberg"]["manifest_patch"]["lakehouse"]["iceberg"]["snapshot_id"], "snap-003")
        self.assertEqual(result["manifest"]["lakehouse"]["iceberg"]["snapshot_id"], "snap-003")
        self.assertEqual(result["manifest"]["catalog"]["stac"]["collection"], "mmfe-fusion-products")
        self.assertEqual(
            calls[1][1]["properties"]["mmfe:authoritative_lakehouse"]["table_identifier"],
            "prod.gis.fusion.semantic_products",
        )
        self.assertEqual(
            calls[2][1]["rows"][0]["metadata"]["authoritative_lakehouse"]["snapshot_id"],
            "snap-003",
        )
        self.assertEqual(result["results"]["lancedb"]["published_count"], 1)
        self.assertFalse(result["errors"])

    def test_publish_semantic_product_includes_valid_infrastructure_preflight(self):
        from data_agent.fusion.lakehouse_publisher import (
            build_iceberg_publisher,
            publish_semantic_product,
        )

        calls = []

        def iceberg_executor(payload):
            calls.append(payload)
            return {"rows_written": payload["row_count"], "snapshot_id": "snap-infra-valid"}

        result = publish_semantic_product(
            _production_ready_semantic_manifest(),
            targets=["iceberg"],
            iceberg={
                "catalog": "prod",
                "namespace": "gis.fusion",
                "table": "semantic_products",
                "warehouse_uri": "s3://geo-lake/warehouse",
                "publisher": build_iceberg_publisher(executor=iceberg_executor),
            },
            publish_environment="production",
        )

        self.assertTrue(result["valid"])
        self.assertTrue(result["infrastructure_preflight"]["valid"])
        self.assertEqual(result["infrastructure_preflight"]["schema"], "mmfe.infrastructure_preflight.v1")
        self.assertEqual(result["infrastructure_preflight"]["environment"], "production")
        self.assertEqual(len(calls), 1)

    def test_publish_semantic_product_blocks_local_infrastructure_in_production(self):
        from data_agent.fusion.lakehouse_config import build_lakehouse_publish_defaults
        from data_agent.fusion.lakehouse_publisher import (
            build_iceberg_publisher,
            publish_semantic_product,
        )

        calls = []

        def iceberg_executor(payload):
            calls.append(payload)
            return {"rows_written": payload["row_count"], "snapshot_id": "should-not-run"}

        result = publish_semantic_product(
            _production_ready_semantic_manifest(),
            targets=["iceberg"],
            iceberg={
                "catalog": "prod",
                "namespace": "gis.fusion",
                "table": "semantic_products",
                "warehouse_uri": "s3://gis-agent-lakehouse/warehouse",
                "publisher": build_iceberg_publisher(executor=iceberg_executor),
            },
            infrastructure=build_lakehouse_publish_defaults(
                {
                    "AWS_ENDPOINT_URL": "http://minio:9000",
                    "AWS_ACCESS_KEY_ID": "minio_admin",
                    "AWS_SECRET_ACCESS_KEY": "local_dev_minio_secret",
                    "MMFE_LAKEHOUSE_BUCKET": "gis-agent-lakehouse",
                }
            ),
            publish_environment="production",
        )

        self.assertFalse(result["valid"])
        self.assertFalse(result["infrastructure_preflight"]["valid"])
        self.assertTrue(
            any(error["target"] == "infrastructure_preflight" for error in result["errors"])
        )
        self.assertFalse(result["results"])
        self.assertEqual(calls, [])

    def test_publish_semantic_product_allows_local_infrastructure_in_validation(self):
        from data_agent.fusion.lakehouse_config import build_lakehouse_publish_defaults
        from data_agent.fusion.lakehouse_publisher import (
            build_iceberg_publisher,
            publish_semantic_product,
        )

        calls = []

        def iceberg_executor(payload):
            calls.append(payload)
            return {"rows_written": payload["row_count"], "snapshot_id": "validation-local-snap"}

        result = publish_semantic_product(
            _validation_only_semantic_manifest(),
            targets=["iceberg"],
            iceberg={
                "catalog": "dev",
                "namespace": "gis.validation",
                "table": "semantic_products",
                "warehouse_uri": "s3://gis-agent-lakehouse/warehouse",
                "publisher": build_iceberg_publisher(executor=iceberg_executor),
            },
            infrastructure=build_lakehouse_publish_defaults(
                {
                    "AWS_ENDPOINT_URL": "http://minio:9000",
                    "AWS_ACCESS_KEY_ID": "minio_admin",
                    "AWS_SECRET_ACCESS_KEY": "local_dev_minio_secret",
                    "MMFE_LAKEHOUSE_BUCKET": "gis-agent-lakehouse",
                }
            ),
            publish_environment="validation",
        )

        self.assertTrue(result["valid"])
        self.assertTrue(result["infrastructure_preflight"]["valid"])
        self.assertTrue(result["infrastructure_preflight"]["summary"]["warn_count"])
        self.assertEqual(len(calls), 1)
        self.assertEqual(
            result["results"]["iceberg"]["manifest_patch"]["lakehouse"]["iceberg"]["snapshot_id"],
            "validation-local-snap",
        )

    def test_publish_semantic_product_blocks_validation_only_product_in_production(self):
        from data_agent.fusion.lakehouse_publisher import (
            build_iceberg_publisher,
            publish_semantic_product,
        )

        calls = []

        def iceberg_executor(payload):
            calls.append(payload)
            return {"rows_written": payload["row_count"]}

        result = publish_semantic_product(
            _validation_only_semantic_manifest(),
            targets=["iceberg"],
            iceberg={
                "catalog": "prod",
                "namespace": "gis.fusion",
                "table": "semantic_products",
                "warehouse_uri": "s3://geo-lake/warehouse",
                "publisher": build_iceberg_publisher(executor=iceberg_executor),
            },
        )

        self.assertFalse(result["valid"])
        self.assertEqual(result["publish_environment"], "production")
        self.assertFalse(result["production_gate"]["valid"])
        self.assertTrue(result["infrastructure_preflight"]["valid"])
        self.assertIn("semantic product is not production_ready", result["production_gate"]["errors"])
        self.assertTrue(any(error["target"] == "production_gate" for error in result["errors"]))
        self.assertFalse(result["results"])
        self.assertEqual(calls, [])

    def test_publish_semantic_product_allows_validation_environment_with_warnings(self):
        from data_agent.fusion.lakehouse_publisher import (
            build_iceberg_publisher,
            publish_semantic_product,
        )

        calls = []

        def iceberg_executor(payload):
            calls.append(payload)
            return {"rows_written": payload["row_count"], "snapshot_id": "validation-snap"}

        result = publish_semantic_product(
            _validation_only_semantic_manifest(),
            targets=["iceberg"],
            publish_environment="validation",
            iceberg={
                "catalog": "dev",
                "namespace": "gis.validation",
                "table": "semantic_products",
                "warehouse_uri": "s3://geo-lake/validation-warehouse",
                "publisher": build_iceberg_publisher(executor=iceberg_executor),
            },
        )

        self.assertTrue(result["valid"])
        self.assertEqual(result["publish_environment"], "validation")
        self.assertTrue(result["production_gate"]["valid"])
        self.assertFalse(result["production_gate"]["diagnostic_summary"]["production_ready"])
        self.assertTrue(result["production_gate"]["warnings"])
        self.assertTrue(result["infrastructure_preflight"]["valid"])
        self.assertEqual(len(calls), 1)
        self.assertEqual(result["results"]["iceberg"]["manifest_patch"]["lakehouse"]["iceberg"]["snapshot_id"], "validation-snap")

    def test_publish_semantic_product_reports_target_errors_without_running_dependents(self):
        from data_agent.fusion.lakehouse_publisher import publish_semantic_product

        result = publish_semantic_product(
            _production_ready_semantic_manifest(),
            targets=["iceberg", "stac", "pgvector"],
            iceberg={
                "catalog": "prod",
                "namespace": "gis.fusion",
                "table": "semantic_products",
                "warehouse_uri": "s3://geo-lake/warehouse",
            },
            stac={
                "collection": "mmfe-fusion-products",
                "catalog_uri": "s3://geo-lake/catalog/stac",
            },
            vector={
                "target": "pgvector",
                "collection": "mmfe_products",
            },
        )

        self.assertFalse(result["valid"])
        self.assertEqual(result["targets"], ["iceberg", "stac", "pgvector"])
        self.assertIn("iceberg", result["results"])
        self.assertNotIn("stac", result["results"])
        self.assertNotIn("pgvector", result["results"])
        self.assertTrue(any(error["target"] == "iceberg" for error in result["errors"]))
        self.assertTrue(any("publisher is required" in message for error in result["errors"] for message in error["errors"]))

    def test_publish_semantic_product_helpers_are_reexported(self):
        from data_agent.fusion import publish_semantic_product
        from data_agent.fusion_engine import publish_semantic_product as proxy_publish_semantic_product

        self.assertTrue(callable(publish_semantic_product))
        self.assertTrue(callable(proxy_publish_semantic_product))

    def test_build_semantic_product_publish_plan_describes_specs_and_dependencies(self):
        from data_agent.fusion.lakehouse_publisher import build_semantic_product_publish_plan

        plan = build_semantic_product_publish_plan(
            _production_ready_semantic_manifest(),
            targets=["iceberg", "stac", "lancedb"],
            iceberg={
                "catalog": "prod",
                "namespace": "gis.fusion",
                "table": "semantic_products",
                "warehouse_uri": "s3://geo-lake/warehouse",
                "publisher": object(),
            },
            stac={
                "collection": "mmfe-fusion-products",
                "catalog_uri": "s3://geo-lake/catalog/stac",
                "item_datetime": "2026-06-16T00:00:00Z",
                "bbox": [100.0, 20.0, 101.0, 21.0],
                "publisher": object(),
            },
            vector={
                "target": "lancedb",
                "collection": "mmfe_products",
                "embedding_model": "mock-embedder",
                "embedder": object(),
                "publisher": object(),
            },
        )

        self.assertTrue(plan["valid"])
        self.assertEqual(plan["targets"], ["iceberg", "stac", "lancedb"])
        self.assertFalse(plan["errors"])
        self.assertEqual(plan["publish_environment"], "production")
        self.assertTrue(plan["production_gate"]["valid"])
        self.assertTrue(plan["production_gate"]["diagnostic_summary"]["production_ready"])
        self.assertTrue(plan["infrastructure_preflight"]["valid"])
        self.assertEqual(
            [step["target"] for step in plan["steps"]],
            ["production_gate", "infrastructure_preflight", "iceberg", "stac", "lancedb"],
        )
        self.assertEqual(plan["steps"][0]["depends_on"], [])
        self.assertEqual(plan["steps"][1]["depends_on"], ["production_gate"])
        self.assertEqual(plan["steps"][2]["depends_on"], [])
        self.assertEqual(plan["steps"][3]["depends_on"], ["iceberg"])
        self.assertEqual(plan["steps"][4]["depends_on"], ["iceberg"])
        self.assertEqual(plan["steps"][0]["schema"], "mmfe.production_publish_gate.v1")
        self.assertEqual(plan["steps"][1]["schema"], "mmfe.infrastructure_preflight.v1")
        self.assertEqual(plan["steps"][2]["schema"], "mmfe.iceberg_publish.v1")
        self.assertEqual(plan["steps"][3]["schema"], "mmfe.stac_publish.v1")
        self.assertEqual(plan["steps"][4]["schema"], "mmfe.semantic_vector_publish.v1")
        self.assertEqual(plan["steps"][2]["spec"]["table_identifier"], "prod.gis.fusion.semantic_products")
        self.assertEqual(plan["steps"][3]["spec"]["item"]["collection"], "mmfe-fusion-products")
        self.assertEqual(plan["steps"][4]["spec"]["target"], "lancedb")
        self.assertTrue(plan["steps"][2]["execution"]["publisher_configured"])
        self.assertTrue(plan["steps"][3]["execution"]["publisher_configured"])
        self.assertTrue(plan["steps"][4]["execution"]["publisher_configured"])
        self.assertTrue(plan["steps"][4]["execution"]["embedder_configured"])

    def test_build_semantic_product_publish_plan_blocks_validation_only_product_in_production(self):
        from data_agent.fusion.lakehouse_publisher import build_semantic_product_publish_plan

        plan = build_semantic_product_publish_plan(
            _validation_only_semantic_manifest(),
            targets=["iceberg"],
            iceberg={
                "catalog": "prod",
                "namespace": "gis.fusion",
                "table": "semantic_products",
                "warehouse_uri": "s3://geo-lake/warehouse",
                "publisher": object(),
            },
        )

        self.assertFalse(plan["valid"])
        self.assertEqual(plan["production_gate"]["publish_environment"], "production")
        self.assertFalse(plan["production_gate"]["valid"])
        self.assertIn("semantic product is not production_ready", plan["production_gate"]["errors"])
        self.assertTrue(
            any(error["target"] == "production_gate" for error in plan["errors"])
        )

    def test_build_semantic_product_publish_plan_allows_validation_environment_with_warnings(self):
        from data_agent.fusion.lakehouse_publisher import build_semantic_product_publish_plan

        plan = build_semantic_product_publish_plan(
            _validation_only_semantic_manifest(),
            targets=["iceberg"],
            publish_environment="validation",
            iceberg={
                "catalog": "dev",
                "namespace": "gis.validation",
                "table": "semantic_products",
                "warehouse_uri": "s3://geo-lake/validation-warehouse",
                "publisher": object(),
            },
        )

        self.assertTrue(plan["valid"])
        self.assertEqual(plan["production_gate"]["publish_environment"], "validation")
        self.assertTrue(plan["production_gate"]["valid"])
        self.assertFalse(plan["production_gate"]["diagnostic_summary"]["production_ready"])
        self.assertTrue(plan["production_gate"]["warnings"])
        self.assertTrue(plan["infrastructure_preflight"]["valid"])

    def test_build_semantic_product_publish_plan_blocks_local_infrastructure_in_production(self):
        from data_agent.fusion.lakehouse_config import build_lakehouse_publish_defaults
        from data_agent.fusion.lakehouse_publisher import build_semantic_product_publish_plan

        plan = build_semantic_product_publish_plan(
            _production_ready_semantic_manifest(),
            targets=["iceberg"],
            iceberg={
                "catalog": "prod",
                "namespace": "gis.fusion",
                "table": "semantic_products",
                "warehouse_uri": "s3://gis-agent-lakehouse/warehouse",
                "publisher": object(),
            },
            infrastructure=build_lakehouse_publish_defaults(
                {
                    "AWS_ENDPOINT_URL": "http://minio:9000",
                    "AWS_ACCESS_KEY_ID": "minio_admin",
                    "AWS_SECRET_ACCESS_KEY": "local_dev_minio_secret",
                    "MMFE_LAKEHOUSE_BUCKET": "gis-agent-lakehouse",
                }
            ),
            publish_environment="production",
        )

        self.assertFalse(plan["valid"])
        self.assertFalse(plan["infrastructure_preflight"]["valid"])
        self.assertTrue(
            any(error["target"] == "infrastructure_preflight" for error in plan["errors"])
        )
        preflight_checks = {
            check["check_id"]: check
            for check in plan["infrastructure_preflight"]["checks"]
        }
        self.assertEqual(preflight_checks["production_endpoint"]["status"], "fail")
        self.assertEqual(preflight_checks["production_credentials"]["status"], "fail")

    def test_build_semantic_product_publish_plan_reports_missing_configuration(self):
        from data_agent.fusion.lakehouse_publisher import build_semantic_product_publish_plan

        plan = build_semantic_product_publish_plan(
            _semantic_manifest(),
            targets=["iceberg", "stac", "pgvector", "unsupported"],
            iceberg={"catalog": "prod"},
            stac={},
            vector={"target": "pgvector"},
            publish_environment="validation",
        )

        self.assertFalse(plan["valid"])
        self.assertEqual(plan["targets"], ["iceberg", "stac", "pgvector", "unsupported"])
        self.assertEqual(
            [step["target"] for step in plan["steps"]],
            ["production_gate", "infrastructure_preflight", "iceberg", "stac", "pgvector"],
        )
        self.assertTrue(any(error["target"] == "iceberg" for error in plan["errors"]))
        self.assertTrue(any(error["target"] == "stac" for error in plan["errors"]))
        self.assertTrue(any(error["target"] == "pgvector" for error in plan["errors"]))
        self.assertTrue(any(error["target"] == "unsupported" for error in plan["errors"]))
        self.assertTrue(any("publisher is required" in message for error in plan["errors"] for message in error["errors"]))
        self.assertTrue(any("embedder is required" in message for error in plan["errors"] for message in error["errors"]))

    def test_semantic_product_publish_plan_helpers_are_reexported(self):
        from data_agent.fusion import build_semantic_product_publish_plan
        from data_agent.fusion_engine import (
            build_semantic_product_publish_plan as proxy_build_semantic_product_publish_plan,
        )

        self.assertTrue(callable(build_semantic_product_publish_plan))
        self.assertTrue(callable(proxy_build_semantic_product_publish_plan))


if __name__ == "__main__":
    unittest.main()
