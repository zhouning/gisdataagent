"""Smoke test MMFE STAC publishing to MinIO through the Python boto3 adapter."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from data_agent.fusion import (  # noqa: E402
    build_s3_stac_executor,
    build_stac_publish_spec,
    build_stac_publisher,
    run_stac_publish,
)


DEFAULT_MANIFEST = Path("data_agent/test_data/twm_bishan_demo/mmfe_semantic_fusion/twm_mmfe_semantic_product.json")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--endpoint-url", default=os.environ.get("AWS_ENDPOINT_URL", "http://localhost:9000"))
    parser.add_argument("--access-key-id", default=os.environ.get("AWS_ACCESS_KEY_ID", "minio_admin"))
    parser.add_argument("--secret-access-key", default=os.environ.get("AWS_SECRET_ACCESS_KEY", "local_dev_minio_secret"))
    parser.add_argument("--region-name", default=os.environ.get("AWS_REGION", "us-east-1"))
    parser.add_argument("--catalog-uri", default=os.environ.get("MMFE_STAC_CATALOG_URI", "s3://gis-agent-lakehouse/catalog/stac"))
    parser.add_argument("--collection", default=os.environ.get("MMFE_STAC_COLLECTION", "mmfe-fusion-products"))
    parser.add_argument("--asset-href", default="")
    parser.add_argument("--expect-product-id", default="")
    args = parser.parse_args()

    summary = run_smoke(args)
    print(json.dumps(summary, ensure_ascii=False, indent=2, default=str))


def run_smoke(args: argparse.Namespace, *, publisher=None, reader=None) -> dict[str, Any]:
    manifest = _read_manifest(args.manifest)
    spec = build_stac_publish_spec(
        manifest,
        collection=args.collection,
        catalog_uri=args.catalog_uri,
        asset_href=args.asset_href or None,
        metadata={"smoke": "mmfe_minio_stac_python"},
    )
    if publisher is None:
        executor = build_s3_stac_executor(
            endpoint_url=args.endpoint_url,
            access_key_id=args.access_key_id,
            secret_access_key=args.secret_access_key,
            region_name=args.region_name,
        )
        publisher = build_stac_publisher(executor=executor)
    result = run_stac_publish(spec, publisher=publisher)
    if not result.get("valid"):
        _exit_error("STAC publish failed", result)

    backend = result.get("backend_result") or {}
    item = _read_back_item(args, backend, reader=reader)
    product_id = str(spec.get("product_id") or "")
    if args.expect_product_id and product_id != args.expect_product_id:
        _exit_error("unexpected product id", {"expected": args.expect_product_id, "actual": product_id})
    if item.get("id") != product_id:
        _exit_error("read-back STAC item id mismatch", {"expected": product_id, "actual": item.get("id")})
    if item.get("collection") != args.collection:
        _exit_error(
            "read-back STAC collection mismatch",
            {"expected": args.collection, "actual": item.get("collection")},
        )

    data_asset = (item.get("assets") or {}).get("data") or {}
    return {
        "status": "ok",
        "manifest": str(args.manifest),
        "product_id": product_id,
        "collection": args.collection,
        "catalog_uri": args.catalog_uri,
        "item_href": backend.get("item_href"),
        "bucket": backend.get("bucket"),
        "key": backend.get("key"),
        "endpoint_url": backend.get("endpoint_url"),
        "bytes_written": backend.get("bytes_written"),
        "read_back_id": item.get("id"),
        "asset_href": data_asset.get("href"),
        "asset_type": data_asset.get("type"),
    }


def _read_manifest(path: Path) -> dict:
    if not path.exists():
        raise SystemExit(f"manifest not found: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def _read_back_item(args: argparse.Namespace, backend: dict[str, Any], *, reader=None) -> dict[str, Any]:
    bucket = backend.get("bucket")
    key = backend.get("key")
    if not bucket or not key:
        raise RuntimeError("publish backend result must include bucket and key")
    if reader is not None:
        return reader(bucket=bucket, key=key)

    import boto3
    from botocore.config import Config as BotoConfig

    client = boto3.client(
        "s3",
        endpoint_url=args.endpoint_url,
        aws_access_key_id=args.access_key_id,
        aws_secret_access_key=args.secret_access_key,
        region_name=args.region_name,
        config=BotoConfig(s3={"addressing_style": "path"}),
    )
    response = client.get_object(Bucket=bucket, Key=key)
    return json.loads(response["Body"].read().decode("utf-8"))


def _exit_error(message: str, payload: dict[str, Any]) -> None:
    print(
        json.dumps(
            {"status": "error", "message": message, "details": payload},
            ensure_ascii=False,
            indent=2,
            default=str,
        ),
        file=sys.stderr,
    )
    raise SystemExit(1)


if __name__ == "__main__":
    main()
