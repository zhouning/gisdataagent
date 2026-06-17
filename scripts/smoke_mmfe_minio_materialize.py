"""Smoke test MMFE asset materialization to MinIO through the Python boto3 adapter."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from data_agent.fusion import build_s3_materialization_executor  # noqa: E402


DEFAULT_MANIFEST = Path("data_agent/test_data/twm_bishan_demo/mmfe_semantic_fusion/twm_mmfe_semantic_product.json")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--endpoint-url", default=os.environ.get("AWS_ENDPOINT_URL", "http://localhost:9000"))
    parser.add_argument("--access-key-id", default=os.environ.get("AWS_ACCESS_KEY_ID", "minio_admin"))
    parser.add_argument("--secret-access-key", default=os.environ.get("AWS_SECRET_ACCESS_KEY", "local_dev_minio_secret"))
    parser.add_argument("--region-name", default=os.environ.get("AWS_REGION", "us-east-1"))
    parser.add_argument("--bucket", default=os.environ.get("MMFE_LAKEHOUSE_BUCKET", "gis-agent-lakehouse"))
    parser.add_argument("--prefix", default="curated/mmfe")
    parser.add_argument(
        "--include-geoparquet",
        action="store_true",
        help="Generate and materialize a tiny GeoParquet validation artifact.",
    )
    args = parser.parse_args()

    summary = run_smoke(args)
    print(json.dumps(summary, ensure_ascii=False, indent=2, default=str))


def run_smoke(args: argparse.Namespace, *, executor=None, reader=None) -> dict[str, Any]:
    manifest = _read_manifest(args.manifest)
    product_id = str(manifest.get("product_id") or "")
    if not product_id:
        raise SystemExit("manifest.product_id is required")
    business_path = Path(str((manifest.get("business_output") or {}).get("path") or ""))
    if not business_path.exists():
        raise SystemExit(f"business output not found: {business_path}")

    executor = executor or build_s3_materialization_executor(
        endpoint_url=args.endpoint_url,
        access_key_id=args.access_key_id,
        secret_access_key=args.secret_access_key,
        region_name=args.region_name,
    )
    uploads = []
    with tempfile.TemporaryDirectory(prefix="mmfe-geoparquet-smoke-") as tmp:
        source_paths = [args.manifest, business_path]
        if getattr(args, "include_geoparquet", False):
            source_paths.append(_write_geoparquet_fixture(Path(tmp), product_id))

        for source_path in source_paths:
            target_uri = f"s3://{args.bucket}/{args.prefix.strip('/')}/{product_id}/{source_path.name}"
            result = executor({"source_path": str(source_path), "target_uri": target_uri})
            if not result.get("materialized"):
                _exit_error("materialization failed", result)
            _verify_read_back(args, result, source_path, reader=reader)
            uploads.append(result)

    return {
        "status": "ok",
        "product_id": product_id,
        "bucket": args.bucket,
        "prefix": f"{args.prefix.strip('/')}/{product_id}",
        "uploaded_count": len(uploads),
        "geoparquet_included": bool(getattr(args, "include_geoparquet", False)),
        "uploads": [
            {
                "source_path": upload.get("source_path"),
                "target_uri": upload.get("target_uri"),
                "bytes_written": upload.get("bytes_written"),
                "sha256": upload.get("sha256"),
                "content_type": upload.get("content_type"),
            }
            for upload in uploads
        ],
    }


def _read_manifest(path: Path) -> dict:
    if not path.exists():
        raise SystemExit(f"manifest not found: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def _write_geoparquet_fixture(tmp_dir: Path, product_id: str) -> Path:
    path = tmp_dir / f"{product_id}_lakehouse_validation.geoparquet"
    try:
        import geopandas as gpd
        from shapely.geometry import Point
    except Exception as exc:  # pragma: no cover - depends on optional local GIS deps.
        raise SystemExit(
            "--include-geoparquet requires geopandas, shapely, and pyarrow in the active environment"
        ) from exc

    gdf = gpd.GeoDataFrame(
        {
            "product_id": [product_id],
            "asset_role": ["mmfe_lakehouse_materialization_smoke"],
            "value": [1],
        },
        geometry=[Point(103.85, 1.35)],
    )
    gdf.to_parquet(path, index=False)
    return path


def _verify_read_back(
    args: argparse.Namespace,
    result: dict[str, Any],
    source_path: Path,
    *,
    reader=None,
) -> None:
    expected = source_path.read_bytes()
    if reader is not None:
        actual = reader(bucket=result["bucket"], key=result["key"])
    else:
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
        response = client.get_object(Bucket=result["bucket"], Key=result["key"])
        actual = response["Body"].read()
    if hashlib.sha256(actual).hexdigest() != hashlib.sha256(expected).hexdigest():
        _exit_error(
            "read-back checksum mismatch",
            {
                "target_uri": result.get("target_uri"),
                "expected_sha256": hashlib.sha256(expected).hexdigest(),
                "actual_sha256": hashlib.sha256(actual).hexdigest(),
            },
        )


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
