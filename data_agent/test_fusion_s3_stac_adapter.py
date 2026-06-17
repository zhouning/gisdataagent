"""Tests for optional S3/MinIO STAC publisher adapter."""

import importlib.util
import json
import sys
import types
import unittest
from unittest import mock


def _stac_payload() -> dict:
    return {
        "target": "stac",
        "catalog_uri": "s3://gis-agent-lakehouse/catalog/stac",
        "collection": "mmfe-fusion-products",
        "item_id": "sfp-test",
        "item": {
            "type": "Feature",
            "stac_version": "1.0.0",
            "id": "sfp-test",
            "collection": "mmfe-fusion-products",
            "bbox": [],
            "geometry": None,
            "properties": {"datetime": "2026-06-16T00:00:00Z"},
            "assets": {
                "data": {
                    "href": "s3://gis-agent-lakehouse/curated/mmfe/sfp-test.parquet",
                    "type": "application/vnd.apache.parquet",
                    "roles": ["data"],
                }
            },
            "links": [],
        },
    }


class TestS3StacAdapter(unittest.TestCase):
    def test_s3_stac_executor_is_exported_without_importing_boto3(self):
        from data_agent.fusion import build_s3_static_stac_catalog_executor, build_s3_stac_executor
        from data_agent.fusion_engine import (
            build_s3_static_stac_catalog_executor as catalog_proxy,
            build_s3_stac_executor as proxy,
        )

        self.assertTrue(callable(build_s3_stac_executor))
        self.assertTrue(callable(proxy))
        self.assertTrue(callable(build_s3_static_stac_catalog_executor))
        self.assertTrue(callable(catalog_proxy))

    @unittest.skipIf(
        importlib.util.find_spec("boto3") is not None,
        "boto3 installed; missing-dependency path is not applicable",
    )
    def test_publish_stac_payload_reports_missing_boto3(self):
        from data_agent.fusion.s3_stac_adapter import publish_stac_payload_to_s3

        with self.assertRaisesRegex(RuntimeError, "boto3"):
            publish_stac_payload_to_s3(_stac_payload())

    def test_publish_stac_payload_uses_s3_catalog_uri_and_writes_json(self):
        from data_agent.fusion.s3_stac_adapter import publish_stac_payload_to_s3

        calls = []

        class FakeS3Client:
            def put_object(self, **kwargs):
                calls.append(kwargs)

        class FakeBoto3(types.SimpleNamespace):
            def client(self, service, **kwargs):
                self.client_call = {"service": service, "kwargs": kwargs}
                return FakeS3Client()

        fake_boto3 = FakeBoto3()
        fake_botocore = types.ModuleType("botocore")
        fake_config_module = types.ModuleType("botocore.config")

        class FakeBotoConfig:
            def __init__(self, **kwargs):
                self.kwargs = kwargs

        fake_config_module.Config = FakeBotoConfig

        with mock.patch.dict(
            sys.modules,
            {
                "boto3": fake_boto3,
                "botocore": fake_botocore,
                "botocore.config": fake_config_module,
            },
        ):
            result = publish_stac_payload_to_s3(
                _stac_payload(),
                endpoint_url="http://minio:9000",
                access_key_id="minio_admin",
                secret_access_key="local_dev_minio_secret",
            )

        self.assertEqual(fake_boto3.client_call["service"], "s3")
        self.assertEqual(fake_boto3.client_call["kwargs"]["endpoint_url"], "http://minio:9000")
        self.assertEqual(calls[0]["Bucket"], "gis-agent-lakehouse")
        self.assertEqual(calls[0]["Key"], "catalog/stac/mmfe-fusion-products/sfp-test.json")
        self.assertEqual(calls[0]["ContentType"], "application/geo+json")
        item = json.loads(calls[0]["Body"].decode("utf-8"))
        self.assertEqual(item["id"], "sfp-test")
        self.assertEqual(result["item_href"], "s3://gis-agent-lakehouse/catalog/stac/mmfe-fusion-products/sfp-test.json")
        self.assertEqual(result["published_count"], 1)
        self.assertIn("localhost", result["console_hint"].replace("minio", "localhost"))

    def test_build_static_stac_catalog_documents_links_collections_and_items(self):
        from data_agent.fusion.s3_stac_adapter import build_static_stac_catalog_documents

        docs = build_static_stac_catalog_documents(
            catalog_uri="s3://gis-agent-lakehouse/catalog/stac",
            catalog_id="mmfe-local",
            description="MMFE local catalog",
            title="MMFE Local STAC",
            collections=[
                {
                    "id": "mmfe-derived-raster-cog-assets",
                    "title": "Derived raster COG assets",
                    "items": [
                        {
                            "id": "PROJECT_NDVI_COG-PRJ-DEMO-0046-REAL-S2-L2A-NDVI",
                            "href": "s3://gis-agent-lakehouse/catalog/stac/mmfe-derived-raster-cog-assets/item.json",
                            "bbox": [106.0, 29.0, 107.0, 30.0],
                            "datetime": "2026-06-17T00:00:00Z",
                        }
                    ],
                }
            ],
        )

        catalog = docs["catalog"]
        collection = docs["collections"]["mmfe-derived-raster-cog-assets"]
        self.assertEqual(catalog["type"], "Catalog")
        self.assertEqual(catalog["id"], "mmfe-local")
        self.assertEqual(catalog["title"], "MMFE Local STAC")
        self.assertEqual(catalog["links"][0]["href"], "s3://gis-agent-lakehouse/catalog/stac/catalog.json")
        self.assertEqual(catalog["links"][2]["rel"], "child")
        self.assertEqual(
            catalog["links"][2]["href"],
            "s3://gis-agent-lakehouse/catalog/stac/mmfe-derived-raster-cog-assets/collection.json",
        )
        self.assertEqual(collection["type"], "Collection")
        self.assertEqual(collection["extent"]["spatial"]["bbox"], [[106.0, 29.0, 107.0, 30.0]])
        self.assertEqual(
            collection["extent"]["temporal"]["interval"],
            [["2026-06-17T00:00:00Z", "2026-06-17T00:00:00Z"]],
        )
        self.assertEqual(collection["links"][3]["rel"], "item")

    def test_publish_static_stac_catalog_writes_catalog_and_collection_json(self):
        from data_agent.fusion.s3_stac_adapter import publish_static_stac_catalog_to_s3

        calls = []

        class FakeS3Client:
            def put_object(self, **kwargs):
                calls.append(kwargs)

        class FakeBoto3(types.SimpleNamespace):
            def client(self, service, **kwargs):
                self.client_call = {"service": service, "kwargs": kwargs}
                return FakeS3Client()

        fake_boto3 = FakeBoto3()
        fake_botocore = types.ModuleType("botocore")
        fake_config_module = types.ModuleType("botocore.config")

        class FakeBotoConfig:
            def __init__(self, **kwargs):
                self.kwargs = kwargs

        fake_config_module.Config = FakeBotoConfig

        with mock.patch.dict(
            sys.modules,
            {
                "boto3": fake_boto3,
                "botocore": fake_botocore,
                "botocore.config": fake_config_module,
            },
        ):
            result = publish_static_stac_catalog_to_s3(
                {
                    "catalog_uri": "s3://gis-agent-lakehouse/catalog/stac",
                    "catalog_id": "mmfe-local",
                    "collections": [
                        {
                            "id": "mmfe-fusion-products",
                            "items": [
                                {
                                    "id": "sfp-test",
                                    "href": "s3://gis-agent-lakehouse/catalog/stac/mmfe-fusion-products/sfp-test.json",
                                }
                            ],
                        }
                    ],
                },
                endpoint_url="http://minio:9000",
                access_key_id="minio_admin",
                secret_access_key="local_dev_minio_secret",
            )

        self.assertEqual(fake_boto3.client_call["service"], "s3")
        self.assertEqual(calls[0]["Bucket"], "gis-agent-lakehouse")
        self.assertEqual(calls[0]["Key"], "catalog/stac/catalog.json")
        self.assertEqual(calls[0]["ContentType"], "application/json")
        self.assertEqual(calls[1]["Key"], "catalog/stac/mmfe-fusion-products/collection.json")
        catalog = json.loads(calls[0]["Body"].decode("utf-8"))
        collection = json.loads(calls[1]["Body"].decode("utf-8"))
        self.assertEqual(catalog["links"][2]["rel"], "child")
        self.assertEqual(collection["links"][3]["rel"], "item")
        self.assertEqual(result["catalog_href"], "s3://gis-agent-lakehouse/catalog/stac/catalog.json")
        self.assertEqual(result["collections"][0]["item_count"], 1)


if __name__ == "__main__":
    unittest.main()
