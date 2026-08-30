"""Tests for optional S3/MinIO MMFE object materialization adapter."""

import hashlib
import importlib.util
import io
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock


class TestS3MaterializationAdapter(unittest.TestCase):
    def test_s3_materialization_executor_is_exported_without_importing_boto3(self):
        from data_agent.fusion import build_s3_materialization_executor, materialize_file_to_s3
        from data_agent.fusion_engine import build_s3_materialization_executor as proxy

        self.assertTrue(callable(build_s3_materialization_executor))
        self.assertTrue(callable(proxy))
        self.assertTrue(callable(materialize_file_to_s3))

    @unittest.skipIf(
        importlib.util.find_spec("boto3") is not None,
        "boto3 installed; missing-dependency path is not applicable",
    )
    def test_materialize_file_reports_missing_boto3(self):
        from data_agent.fusion.s3_materialization_adapter import materialize_file_to_s3

        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "sample.csv"
            source.write_text("a,b\n1,2\n", encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError, "boto3"):
                materialize_file_to_s3(
                    {
                        "source_path": str(source),
                        "target_uri": "s3://gis-agent-lakehouse/curated/mmfe/sample.csv",
                    }
                )

    def test_materialize_file_uploads_to_s3_uri_prefix_and_returns_checksum(self):
        from data_agent.fusion.s3_materialization_adapter import materialize_file_to_s3

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

        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "sample.csv"
            body = "a,b\n1,2\n"
            source.write_text(body, encoding="utf-8")
            with mock.patch.dict(
                sys.modules,
                {
                    "boto3": fake_boto3,
                    "botocore": fake_botocore,
                    "botocore.config": fake_config_module,
                },
            ):
                result = materialize_file_to_s3(
                    {
                        "source_path": str(source),
                        "target_uri": "s3://gis-agent-lakehouse/curated/mmfe/",
                    },
                    endpoint_url="http://minio:9000",
                    access_key_id="minio_admin",
                    secret_access_key="local_dev_minio_secret",
                )

        self.assertEqual(fake_boto3.client_call["service"], "s3")
        self.assertEqual(fake_boto3.client_call["kwargs"]["endpoint_url"], "http://minio:9000")
        self.assertEqual(calls[0]["Bucket"], "gis-agent-lakehouse")
        self.assertEqual(calls[0]["Key"], "curated/mmfe/sample.csv")
        self.assertEqual(calls[0]["ContentType"], "text/csv")
        self.assertEqual(calls[0]["Body"], body.encode("utf-8"))
        self.assertEqual(result["target_uri"], "s3://gis-agent-lakehouse/curated/mmfe/sample.csv")
        self.assertEqual(result["bytes_written"], len(body.encode("utf-8")))
        self.assertEqual(result["sha256"], hashlib.sha256(body.encode("utf-8")).hexdigest())

    def test_materialize_file_marks_geoparquet_as_parquet_media_type(self):
        from data_agent.fusion.s3_materialization_adapter import materialize_file_to_s3

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

        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "sample.geoparquet"
            body = b"PAR1geo"
            source.write_bytes(body)
            with mock.patch.dict(
                sys.modules,
                {
                    "boto3": fake_boto3,
                    "botocore": fake_botocore,
                    "botocore.config": fake_config_module,
                },
            ):
                result = materialize_file_to_s3(
                    {
                        "source_path": str(source),
                        "target_uri": "s3://gis-agent-lakehouse/curated/mmfe/sample.geoparquet",
                    }
                )

        self.assertEqual(calls[0]["ContentType"], "application/vnd.apache.parquet")
        self.assertEqual(calls[0]["Body"], body)
        self.assertEqual(result["content_type"], "application/vnd.apache.parquet")
        self.assertEqual(
            result["target_uri"],
            "s3://gis-agent-lakehouse/curated/mmfe/sample.geoparquet",
        )

    def test_immutable_materialization_verifies_readback_and_skips_same_bytes(self):
        from data_agent.fusion.s3_materialization_adapter import materialize_file_to_s3

        stored = {}

        class MissingObject(Exception):
            response = {"Error": {"Code": "NoSuchKey"}}

        class FakeS3Client:
            def get_object(self, *, Bucket, Key):
                try:
                    body = stored[(Bucket, Key)]
                except KeyError as exc:
                    raise MissingObject() from exc
                return {"Body": io.BytesIO(body)}

            def put_object(self, *, Bucket, Key, Body, **kwargs):
                stored[(Bucket, Key)] = Body

        class FakeBoto3(types.SimpleNamespace):
            def client(self, service, **kwargs):
                return FakeS3Client()

        fake_botocore = types.ModuleType("botocore")
        fake_config_module = types.ModuleType("botocore.config")

        class FakeBotoConfig:
            def __init__(self, **kwargs):
                self.kwargs = kwargs

        fake_config_module.Config = FakeBotoConfig
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "snapshot.json"
            source.write_text('{"records":2}\n', encoding="utf-8")
            modules = {
                "boto3": FakeBoto3(),
                "botocore": fake_botocore,
                "botocore.config": fake_config_module,
            }
            with mock.patch.dict(sys.modules, modules):
                first = materialize_file_to_s3(
                    {
                        "source_path": str(source),
                        "target_uri": "s3://gis-agent-lakehouse/ods/snapshot.json",
                        "immutable": True,
                    }
                )
                second = materialize_file_to_s3(
                    {
                        "source_path": str(source),
                        "target_uri": "s3://gis-agent-lakehouse/ods/snapshot.json",
                        "immutable": True,
                    }
                )

        self.assertTrue(first["created"])
        self.assertTrue(first["verified"])
        self.assertFalse(second["created"])
        self.assertTrue(second["verified"])


if __name__ == "__main__":
    unittest.main()
