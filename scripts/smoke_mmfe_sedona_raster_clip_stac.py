"""Smoke test STAC registration for Sedona-derived MMFE raster clips.

This builds on ``smoke_mmfe_sedona_raster_clip.py``: first materialize clipped
project-level NDVI GeoTIFFs to the MinIO lakehouse, then register each derived
raster artifact as a STAC item and read the catalog entries back.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import importlib.util
import json
import os
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.smoke_mmfe_sedona_raster_clip import (  # noqa: E402
    DEFAULT_DATA_DIR,
    DEFAULT_OUTPUT,
    DEFAULT_PACKAGES,
    DEFAULT_RASTER,
    run_smoke as run_clip_smoke,
)


DEFAULT_CATALOG_URI = "s3://gis-agent-lakehouse/catalog/stac"
DEFAULT_COLLECTION = "mmfe-derived-raster-assets"


def _load_module(name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load module {name} from {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_lakehouse_publisher = _load_module("mmfe_lakehouse_publisher", REPO_ROOT / "data_agent/fusion/lakehouse_publisher.py")
_s3_stac_adapter = _load_module("mmfe_s3_stac_adapter", REPO_ROOT / "data_agent/fusion/s3_stac_adapter.py")
build_stac_publisher = _lakehouse_publisher.build_stac_publisher
run_stac_publish = _lakehouse_publisher.run_stac_publish
build_s3_stac_executor = _s3_stac_adapter.build_s3_stac_executor


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR)
    parser.add_argument("--projects-file", default="synthetic_projects.geojson")
    parser.add_argument("--raster", type=Path, default=DEFAULT_RASTER)
    parser.add_argument("--output-uri", default=DEFAULT_OUTPUT)
    parser.add_argument("--catalog-uri", default=os.environ.get("MMFE_STAC_CATALOG_URI", DEFAULT_CATALOG_URI))
    parser.add_argument("--collection", default=os.environ.get("MMFE_RASTER_STAC_COLLECTION", DEFAULT_COLLECTION))
    parser.add_argument("--endpoint-url", default=os.environ.get("AWS_ENDPOINT_URL", "http://minio:9000"))
    parser.add_argument("--access-key-id", default=os.environ.get("AWS_ACCESS_KEY_ID", "minio_admin"))
    parser.add_argument("--secret-access-key", default=os.environ.get("AWS_SECRET_ACCESS_KEY", "local_dev_minio_secret"))
    parser.add_argument("--region-name", default=os.environ.get("AWS_REGION", "us-east-1"))
    parser.add_argument("--packages", default=os.environ.get("SEDONA_RASTER_CLIP_SPARK_PACKAGES", DEFAULT_PACKAGES))
    parser.add_argument(
        "--publisher",
        choices=["hadoop-s3a", "boto3"],
        default=os.environ.get("MMFE_RASTER_STAC_PUBLISHER", "hadoop-s3a"),
    )
    parser.add_argument("--source-crs", default="EPSG:4326")
    parser.add_argument("--raster-crs", default="EPSG:32648")
    parser.add_argument("--max-clips", type=int, default=3)
    parser.add_argument("--min-valid-pixels", type=int, default=1)
    args = parser.parse_args()

    summary = run_smoke(args)
    print(json.dumps(summary, ensure_ascii=False, indent=2, default=str))


def run_smoke(args: argparse.Namespace, *, clip_summary: dict[str, Any] | None = None, publisher=None, reader=None) -> dict[str, Any]:
    publisher_mode = getattr(args, "publisher", "hadoop-s3a")
    owns_clip_spark = clip_summary is None
    if clip_summary is None:
        clip_args = argparse.Namespace(
            data_dir=args.data_dir,
            projects_file=args.projects_file,
            raster=args.raster,
            raster_product_id=None,
            raster_alias_zh=None,
            output_uri=args.output_uri,
            local_stage_dir=Path(".tmp/mmfe-sedona-raster-clips"),
            endpoint_url=args.endpoint_url,
            access_key_id=args.access_key_id,
            secret_access_key=args.secret_access_key,
            packages=args.packages,
            source_crs=args.source_crs,
            raster_crs=args.raster_crs,
            max_clips=args.max_clips,
            min_valid_pixels=args.min_valid_pixels,
            keep_spark=publisher_mode == "hadoop-s3a",
        )
        clip_summary = run_clip_smoke(clip_args)

    try:
        artifacts = list(clip_summary.get("artifacts") or [])
        if not artifacts:
            _exit_error("clip summary contains no raster artifacts", clip_summary)

        if publisher is None and publisher_mode == "boto3":
            executor = build_s3_stac_executor(
                endpoint_url=args.endpoint_url,
                access_key_id=args.access_key_id,
                secret_access_key=args.secret_access_key,
                region_name=args.region_name,
            )
            publisher = build_stac_publisher(executor=executor)

        published: list[dict[str, Any]] = []
        read_back_items: list[dict[str, Any]] = []
        for artifact in artifacts:
            item = build_raster_clip_stac_item(
                artifact,
                collection=args.collection,
                catalog_uri=args.catalog_uri,
                clip_summary=clip_summary,
            )
            spec = {
                "schema": "mmfe.stac_publish.v1",
                "target": "stac",
                "storage_layer": "discovery_catalog",
                "catalog_uri": args.catalog_uri,
                "collection": args.collection,
                "product_id": item["id"],
                "item": item,
                "assets": item["assets"],
                "links": item["links"],
                "properties": item["properties"],
                "lineage": item["properties"].get("mmfe:lineage", {}),
                "quality": {},
            }
            if publisher is not None:
                result = run_stac_publish(spec, publisher=publisher)
            else:
                backend = _publish_stac_item_with_hadoop_s3a(clip_summary, args.catalog_uri, args.collection, item)
                result = {
                    "valid": True,
                    "errors": [],
                    "backend_result": backend,
                    "item_id": item["id"],
                }
            if not result.get("valid"):
                _exit_error("raster clip STAC publish failed", result)
            backend = result.get("backend_result") or {}
            read_back = _read_back_item(args, backend, reader=reader)
            _validate_read_back_item(item, read_back)
            published.append(
                {
                    "item_id": item["id"],
                    "item_href": backend.get("item_href"),
                    "bucket": backend.get("bucket"),
                    "key": backend.get("key"),
                    "asset_href": item["assets"]["data"]["href"],
                    "bytes_written": backend.get("bytes_written"),
                }
            )
            read_back_items.append(
                {
                    "id": read_back.get("id"),
                    "collection": read_back.get("collection"),
                    "asset_href": ((read_back.get("assets") or {}).get("data") or {}).get("href"),
                    "proj_epsg": (read_back.get("properties") or {}).get("proj:epsg"),
                }
            )

        return {
            "status": "ok",
            "clip_rows": len(artifacts),
            "published_count": len(published),
            "collection": args.collection,
            "catalog_uri": args.catalog_uri,
            "clip_output_uri": clip_summary.get("output_uri"),
            "clip_manifest_uri": clip_summary.get("manifest_uri"),
            "publisher": publisher_mode,
            "published": published,
            "read_back_items": read_back_items,
        }
    finally:
        if owns_clip_spark and clip_summary.get("_spark") is not None:
            clip_summary["_spark"].stop()


def build_raster_clip_stac_item(
    artifact: dict[str, Any],
    *,
    collection: str,
    catalog_uri: str = "",
    clip_summary: dict[str, Any] | None = None,
    item_datetime: str | None = None,
) -> dict[str, Any]:
    """Build a STAC item for one Sedona-derived clipped GeoTIFF artifact."""

    item_id = str(artifact.get("relation_id") or "")
    if not item_id:
        raise ValueError("artifact.relation_id is required")
    asset_href = str(artifact.get("artifact_href") or artifact.get("artifact_uri") or "")
    if not asset_href:
        raise ValueError("artifact artifact_href/artifact_uri is required")

    epsg = _epsg_from_crs(str(artifact.get("raster_crs") or "")) or _safe_int(artifact.get("raster_srid"))
    properties = {
        "datetime": item_datetime or _utc_now_z(),
        "mmfe:product_type": "derived_raster_asset",
        "mmfe:semantic_metric": artifact.get("semantic_metric"),
        "mmfe:relation_type": artifact.get("relation_type"),
        "mmfe:left_role": artifact.get("left_role"),
        "mmfe:right_role": artifact.get("right_role"),
        "mmfe:computed_by": artifact.get("computed_by"),
        "mmfe:source_product_id": artifact.get("raster_product_id"),
        "mmfe:source_product_alias_zh": artifact.get("raster_alias_zh"),
        "twm:project_id": artifact.get("project_id"),
        "twm:project_name": artifact.get("project_name"),
        "twm:risk_scenario": artifact.get("risk_scenario"),
        "twm:review_priority": artifact.get("review_priority"),
        "twm:not_for_production": bool(artifact.get("not_for_production", True)),
        "raster:width": _safe_int(artifact.get("clipped_width")),
        "raster:height": _safe_int(artifact.get("clipped_height")),
        "raster:valid_pixel_count": _safe_float(artifact.get("ndvi_valid_pixel_count")),
        "raster:bands": 1,
        "ndvi:mean": _safe_float(artifact.get("ndvi_mean")),
        "ndvi:min": _safe_float(artifact.get("ndvi_min")),
        "ndvi:max": _safe_float(artifact.get("ndvi_max")),
        "proj:epsg": epsg,
        "mmfe:lineage": {
            "clip_output_uri": (clip_summary or {}).get("output_uri", ""),
            "clip_manifest_uri": (clip_summary or {}).get("manifest_uri", ""),
            "source_raster_file": (clip_summary or {}).get("raster_file", ""),
        },
    }

    item = {
        "type": "Feature",
        "stac_version": "1.0.0",
        "id": item_id,
        "collection": collection,
        "bbox": [],
        "geometry": None,
        "properties": {key: value for key, value in properties.items() if value not in ("", None, {}, [])},
        "assets": {
            "data": {
                "href": asset_href,
                "type": str(artifact.get("content_type") or "image/tiff; application=geotiff"),
                "roles": ["data", "derived", "raster", "ndvi"],
                "title": f"NDVI clipped GeoTIFF for {artifact.get('project_id', item_id)}",
            }
        },
        "links": _stac_links(catalog_uri, collection),
    }
    return item


def _read_back_item(args: argparse.Namespace, backend: dict[str, Any], *, reader=None) -> dict[str, Any]:
    bucket = backend.get("bucket")
    key = backend.get("key")
    if not bucket or not key:
        raise RuntimeError("publish backend result must include bucket and key")
    if reader is not None:
        return reader(bucket=bucket, key=key)
    if getattr(args, "publisher", "hadoop-s3a") == "hadoop-s3a":
        path = backend.get("item_href_s3a") or f"s3a://{bucket}/{key}"
        return _read_json_with_spark(backend["spark"], path)

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


def _publish_stac_item_with_hadoop_s3a(
    clip_summary: dict[str, Any],
    catalog_uri: str,
    collection: str,
    item: dict[str, Any],
) -> dict[str, Any]:
    spark = clip_summary.get("_spark")
    if spark is None:
        raise RuntimeError("hadoop-s3a STAC publishing requires clip_summary._spark")
    bucket, prefix = _s3_uri_parts(catalog_uri)
    key = "/".join(part.strip("/") for part in [prefix, collection, f"{item['id']}.json"] if part)
    target_uri = f"s3a://{bucket}/{key}"
    body = json.dumps(item, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8")
    _write_bytes_with_spark(spark, target_uri, body)
    return {
        "published": True,
        "published_count": 1,
        "target": "stac",
        "collection": collection,
        "item_id": item["id"],
        "bucket": bucket,
        "key": key,
        "item_href": f"s3://{bucket}/{key}",
        "item_href_s3a": target_uri,
        "bytes_written": len(body),
        "spark": spark,
    }


def _write_bytes_with_spark(spark: Any, target_uri: str, body: bytes) -> None:
    jvm = spark.sparkContext._jvm
    conf = spark.sparkContext._jsc.hadoopConfiguration()
    target = jvm.org.apache.hadoop.fs.Path(target_uri)
    fs = target.getFileSystem(conf)
    parent = target.getParent()
    if parent is not None:
        fs.mkdirs(parent)
    stream = fs.create(target, True)
    try:
        stream.write(bytearray(body))
    finally:
        stream.close()


def _read_json_with_spark(spark: Any, uri: str) -> dict[str, Any]:
    rows = spark.read.text(uri).collect()
    return json.loads("\n".join(row["value"] for row in rows))


def _s3_uri_parts(uri: str) -> tuple[str, str]:
    if not uri.startswith("s3://"):
        raise ValueError("catalog_uri must start with s3:// for hadoop-s3a publisher")
    rest = uri[5:]
    bucket, _, prefix = rest.partition("/")
    if not bucket:
        raise ValueError("catalog_uri bucket is required")
    return bucket, prefix


def _validate_read_back_item(expected: dict[str, Any], actual: dict[str, Any]) -> None:
    if actual.get("id") != expected.get("id"):
        _exit_error("read-back raster STAC item id mismatch", {"expected": expected.get("id"), "actual": actual.get("id")})
    if actual.get("collection") != expected.get("collection"):
        _exit_error(
            "read-back raster STAC collection mismatch",
            {"expected": expected.get("collection"), "actual": actual.get("collection")},
        )
    expected_href = ((expected.get("assets") or {}).get("data") or {}).get("href")
    actual_href = ((actual.get("assets") or {}).get("data") or {}).get("href")
    if actual_href != expected_href:
        _exit_error("read-back raster STAC asset href mismatch", {"expected": expected_href, "actual": actual_href})


def _stac_links(catalog_uri: str, collection: str) -> list[dict[str, Any]]:
    links: list[dict[str, Any]] = []
    if catalog_uri:
        links.append({"rel": "root", "href": catalog_uri, "type": "application/json"})
    if catalog_uri and collection:
        links.append({"rel": "collection", "href": f"{catalog_uri.rstrip('/')}/{collection}", "type": "application/json"})
    return links


def _epsg_from_crs(crs: str) -> int | None:
    value = crs.strip().upper()
    if value.startswith("EPSG:"):
        return _safe_int(value.split(":", 1)[1])
    return None


def _safe_int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _safe_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _utc_now_z() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


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
