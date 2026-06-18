"""Smoke test COG optimization for Sedona-derived MMFE raster clips.

This is a host-side optional raster publishing smoke. The baked Spark runtime
already validates Sedona clipping and STAC registration for derived GeoTIFFs;
this script validates the next asset-publication step where those clips are
rewritten as Cloud-Optimized GeoTIFFs, uploaded to MinIO/S3, registered in
STAC, and read back for checksum and catalog consistency.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import importlib.machinery
import importlib.util
import json
import os
from pathlib import Path
import sys
import types
from typing import Any, Callable

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


DEFAULT_DATA_DIR = Path("data_agent/test_data/twm_bishan_demo")
DEFAULT_SOURCE_DIR = Path(".tmp/mmfe-sedona-raster-clips")
DEFAULT_LOCAL_OUTPUT_DIR = Path(".tmp/mmfe-raster-cog")
DEFAULT_TARGET_URI = (
    "s3://gis-agent-lakehouse/curated/mmfe/sfp-twm-dc2a707aabda0c01/"
    "spark_smoke/sedona_project_ndvi_clips/cog"
)
DEFAULT_SOURCE_ASSET_BASE_URI = (
    "s3://gis-agent-lakehouse/curated/mmfe/sfp-twm-dc2a707aabda0c01/"
    "spark_smoke/sedona_project_ndvi_clips/geotiff"
)
DEFAULT_CATALOG_URI = "s3://gis-agent-lakehouse/catalog/stac"
DEFAULT_COLLECTION = "mmfe-derived-raster-cog-assets"
COG_MEDIA_TYPE = "image/tiff; application=geotiff; profile=cloud-optimized"


def _ensure_package_stub(name: str, path: Path) -> None:
    existing = sys.modules.get(name)
    if existing is not None and hasattr(existing, "__path__"):
        paths = list(getattr(existing, "__path__", []))
        if str(path) not in paths:
            paths.append(str(path))
            existing.__path__ = paths
        return
    module = types.ModuleType(name)
    module.__path__ = [str(path)]
    module.__package__ = name
    module.__spec__ = importlib.machinery.ModuleSpec(name, loader=None, is_package=True)
    sys.modules[name] = module


def _load_fusion_submodule(module_name: str) -> Any:
    _ensure_package_stub("data_agent", REPO_ROOT / "data_agent")
    _ensure_package_stub("data_agent.fusion", REPO_ROOT / "data_agent/fusion")
    qualified_name = f"data_agent.fusion.{module_name}"
    if qualified_name in sys.modules:
        return sys.modules[qualified_name]
    path = REPO_ROOT / "data_agent/fusion" / f"{module_name}.py"
    spec = importlib.util.spec_from_file_location(qualified_name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load module {qualified_name} from {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[qualified_name] = module
    spec.loader.exec_module(module)
    return module


_lakehouse_publisher = _load_fusion_submodule("lakehouse_publisher")
_s3_materialization_adapter = _load_fusion_submodule("s3_materialization_adapter")
_s3_stac_adapter = _load_fusion_submodule("s3_stac_adapter")
build_s3_materialization_executor = _s3_materialization_adapter.build_s3_materialization_executor
build_s3_static_stac_catalog_executor = _s3_stac_adapter.build_s3_static_stac_catalog_executor
build_s3_stac_executor = _s3_stac_adapter.build_s3_stac_executor
build_stac_publisher = _lakehouse_publisher.build_stac_publisher
run_stac_publish = _lakehouse_publisher.run_stac_publish


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dir", type=Path, default=DEFAULT_SOURCE_DIR)
    parser.add_argument("--source-glob", default="*_ndvi_clip.tif")
    parser.add_argument("--local-output-dir", type=Path, default=DEFAULT_LOCAL_OUTPUT_DIR)
    parser.add_argument("--target-uri", default=os.environ.get("MMFE_RASTER_COG_TARGET_URI", DEFAULT_TARGET_URI))
    parser.add_argument("--source-asset-base-uri", default=DEFAULT_SOURCE_ASSET_BASE_URI)
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR)
    parser.add_argument("--projects-file", default="synthetic_projects.geojson")
    parser.add_argument("--real-imagery-manifest", type=Path, default=DEFAULT_DATA_DIR / "real_imagery_manifest.json")
    parser.add_argument("--catalog-uri", default=os.environ.get("MMFE_STAC_CATALOG_URI", DEFAULT_CATALOG_URI))
    parser.add_argument("--collection", default=os.environ.get("MMFE_RASTER_COG_STAC_COLLECTION", DEFAULT_COLLECTION))
    parser.add_argument("--endpoint-url", default=os.environ.get("AWS_ENDPOINT_URL", "http://localhost:9000"))
    parser.add_argument("--access-key-id", default=os.environ.get("AWS_ACCESS_KEY_ID", "minio_admin"))
    parser.add_argument("--secret-access-key", default=os.environ.get("AWS_SECRET_ACCESS_KEY", "local_dev_minio_secret"))
    parser.add_argument("--region-name", default=os.environ.get("AWS_REGION", "us-east-1"))
    parser.add_argument("--compress", default="DEFLATE")
    parser.add_argument("--blocksize", type=int, default=512)
    parser.add_argument("--max-assets", type=int, default=0)
    args = parser.parse_args()

    summary = run_smoke(args)
    print(json.dumps(summary, ensure_ascii=False, indent=2, default=str))


def run_smoke(
    args: argparse.Namespace,
    *,
    converter: Callable[..., dict[str, Any]] | None = None,
    materializer=None,
    object_reader=None,
    stac_publisher=None,
    stac_reader=None,
    catalog_publisher=None,
    catalog_reader=None,
) -> dict[str, Any]:
    source_files = discover_clip_files(args.source_dir, args.source_glob, max_assets=getattr(args, "max_assets", 0))
    if not source_files:
        _exit_error(
            "no source GeoTIFF clips found; run scripts/smoke_mmfe_sedona_raster_clip.py first",
            {"source_dir": str(args.source_dir), "source_glob": args.source_glob},
        )

    project_lookup = load_project_lookup(args.data_dir / args.projects_file)
    raster_lookup = load_raster_product_lookup(args.real_imagery_manifest)
    converter = converter or convert_geotiff_to_cog
    materializer = materializer or build_s3_materialization_executor(
        endpoint_url=args.endpoint_url,
        access_key_id=args.access_key_id,
        secret_access_key=args.secret_access_key,
        region_name=args.region_name,
    )
    if stac_publisher is None:
        stac_executor = build_s3_stac_executor(
            endpoint_url=args.endpoint_url,
            access_key_id=args.access_key_id,
            secret_access_key=args.secret_access_key,
            region_name=args.region_name,
        )
        stac_publisher = build_stac_publisher(executor=stac_executor)

    args.local_output_dir.mkdir(parents=True, exist_ok=True)
    published: list[dict[str, Any]] = []
    read_back_items: list[dict[str, Any]] = []
    catalog_items: list[dict[str, Any]] = []
    for source_path in source_files:
        project_id, raster_product_id = parse_clip_filename(source_path)
        cog_path = args.local_output_dir / source_path.with_suffix(".cog.tif").name
        cog_metadata = converter(
            source_path,
            cog_path,
            compress=args.compress,
            blocksize=args.blocksize,
        )
        target_uri = _join_uri(_s3a_to_s3_uri(args.target_uri), cog_path.name)
        materialized = materializer(
            {
                "source_path": str(cog_path),
                "target_uri": target_uri,
                "content_type": COG_MEDIA_TYPE,
            }
        )
        if not materialized.get("materialized"):
            _exit_error("COG materialization failed", materialized)
        verify_s3_object_checksum(args, materialized, cog_path, reader=object_reader)

        project = project_lookup.get(project_id, {})
        raster_product = raster_lookup.get(raster_product_id, {})
        artifact = build_cog_artifact(
            source_path=source_path,
            cog_path=cog_path,
            project_id=project_id,
            raster_product_id=raster_product_id,
            project=project,
            raster_product=raster_product,
            cog_metadata=cog_metadata,
            materialized=materialized,
            source_asset_base_uri=getattr(args, "source_asset_base_uri", ""),
        )
        item = build_cog_stac_item(
            artifact,
            collection=args.collection,
            catalog_uri=args.catalog_uri,
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
        result = run_stac_publish(spec, publisher=stac_publisher)
        if not result.get("valid"):
            _exit_error("COG STAC publish failed", result)
        backend = result.get("backend_result") or {}
        read_back = read_back_stac_item(args, backend, reader=stac_reader)
        validate_read_back_item(item, read_back)

        published.append(
            {
                "item_id": item["id"],
                "project_id": project_id,
                "asset_href": item["assets"]["data"]["href"],
                "item_href": backend.get("item_href"),
                "bytes_written": materialized.get("bytes_written"),
                "sha256": materialized.get("sha256"),
                "layout": cog_metadata.get("layout"),
                "tiled": cog_metadata.get("tiled"),
                "proj_epsg": cog_metadata.get("epsg"),
            }
        )
        catalog_items.append(
            {
                "id": item["id"],
                "href": backend.get("item_href"),
                "bbox": item.get("bbox", []),
                "datetime": item.get("properties", {}).get("datetime"),
            }
        )
        read_back_items.append(
            {
                "id": read_back.get("id"),
                "collection": read_back.get("collection"),
                "asset_href": ((read_back.get("assets") or {}).get("data") or {}).get("href"),
                "roles": ((read_back.get("assets") or {}).get("data") or {}).get("roles"),
            }
        )

    if catalog_publisher is None:
        catalog_publisher = build_s3_static_stac_catalog_executor(
            endpoint_url=args.endpoint_url,
            access_key_id=args.access_key_id,
            secret_access_key=args.secret_access_key,
            region_name=args.region_name,
        )
    catalog_result = catalog_publisher(
        {
            "catalog_uri": args.catalog_uri,
            "catalog_id": "mmfe-local-static-stac",
            "title": "MMFE Local STAC Catalog",
            "description": "Static STAC catalog for MMFE-derived local lakehouse assets.",
            "collections": [
                {
                    "id": args.collection,
                    "title": "MMFE derived raster COG assets",
                    "description": "Cloud-Optimized GeoTIFF assets derived from MMFE raster semantic fusion.",
                    "items": catalog_items,
                }
            ],
        }
    )
    if not catalog_result.get("published"):
        _exit_error("COG static STAC catalog publish failed", catalog_result)
    catalog_readback = read_back_static_catalog(args, catalog_result, reader=catalog_reader)
    validate_static_catalog_readback(args.collection, catalog_items, catalog_readback)

    return {
        "status": "ok",
        "source_dir": str(args.source_dir),
        "local_output_dir": str(args.local_output_dir),
        "source_count": len(source_files),
        "cog_count": len(published),
        "materialized_count": len(published),
        "stac_published_count": len(published),
        "target_uri": _s3a_to_s3_uri(args.target_uri),
        "catalog_uri": args.catalog_uri,
        "collection": args.collection,
        "published": published,
        "read_back_items": read_back_items,
        "static_catalog": {
            "catalog_href": catalog_result.get("catalog_href"),
            "published_count": catalog_result.get("published_count"),
            "collections": catalog_result.get("collections", []),
            "read_back_catalog_id": catalog_readback["catalog"].get("id"),
        },
    }


def discover_clip_files(source_dir: Path, source_glob: str, *, max_assets: int = 0) -> list[Path]:
    if not source_dir.exists():
        return []
    files = sorted(path for path in source_dir.glob(source_glob) if path.is_file() and ".cog." not in path.name)
    if max_assets and max_assets > 0:
        return files[:max_assets]
    return files


def convert_geotiff_to_cog(
    source_path: Path,
    target_path: Path,
    *,
    compress: str = "DEFLATE",
    blocksize: int = 512,
) -> dict[str, Any]:
    try:
        from rasterio.shutil import copy as rio_copy
    except Exception as exc:  # pragma: no cover - exercised when optional deps absent.
        raise RuntimeError("COG conversion requires optional dependency: rasterio") from exc

    target_path.parent.mkdir(parents=True, exist_ok=True)
    rio_copy(
        str(source_path),
        str(target_path),
        driver="COG",
        compress=compress,
        blocksize=blocksize,
        overview_resampling="nearest",
        BIGTIFF="IF_SAFER",
    )
    return validate_cog_metadata(target_path, source_path=source_path)


def validate_cog_metadata(cog_path: Path, *, source_path: Path | None = None) -> dict[str, Any]:
    try:
        import rasterio
    except Exception as exc:  # pragma: no cover - exercised when optional deps absent.
        raise RuntimeError("COG validation requires optional dependency: rasterio") from exc

    with rasterio.open(cog_path) as cog:
        metadata = raster_metadata(cog)

    errors: list[str] = []
    if str(metadata.get("layout", "")).upper() != "COG":
        errors.append("COG IMAGE_STRUCTURE LAYOUT tag is missing")
    if not metadata.get("tiled"):
        errors.append("COG output is not tiled")
    if source_path is not None:
        with rasterio.open(source_path) as src:
            source = raster_metadata(src, include_stats=False)
        for field in ("width", "height", "count", "dtype", "epsg"):
            if metadata.get(field) != source.get(field):
                errors.append(f"{field} changed during COG conversion")
    if errors:
        raise ValueError(f"invalid COG output {cog_path}: {'; '.join(errors)}")
    return metadata


def raster_metadata(dataset: Any, *, include_stats: bool = True) -> dict[str, Any]:
    image_structure = dataset.tags(ns="IMAGE_STRUCTURE") or {}
    epsg = dataset.crs.to_epsg() if dataset.crs else None
    block_shape = dataset.block_shapes[0] if dataset.block_shapes else (None, None)
    metadata: dict[str, Any] = {
        "driver": dataset.driver,
        "width": int(dataset.width),
        "height": int(dataset.height),
        "count": int(dataset.count),
        "dtype": dataset.dtypes[0] if dataset.dtypes else "",
        "crs": dataset.crs.to_string() if dataset.crs else "",
        "epsg": epsg,
        "nodata": dataset.nodata,
        "bounds": [float(dataset.bounds.left), float(dataset.bounds.bottom), float(dataset.bounds.right), float(dataset.bounds.top)],
        "transform": [float(value) for value in dataset.transform[:6]],
        "layout": image_structure.get("LAYOUT", ""),
        "compression": image_structure.get("COMPRESSION", ""),
        "interleave": image_structure.get("INTERLEAVE", ""),
        "tiled": bool(dataset.profile.get("tiled")),
        "blockysize": block_shape[0],
        "blockxsize": block_shape[1],
        "overviews": list(dataset.overviews(1)) if dataset.count else [],
    }
    if include_stats and dataset.count:
        data = dataset.read(1, masked=True)
        values = data.compressed()
        metadata["valid_pixel_count"] = int(values.size)
        if values.size:
            metadata["min"] = float(values.min())
            metadata["mean"] = float(values.mean())
            metadata["max"] = float(values.max())
    return metadata


def build_cog_artifact(
    *,
    source_path: Path,
    cog_path: Path,
    project_id: str,
    raster_product_id: str,
    project: dict[str, Any],
    raster_product: dict[str, Any],
    cog_metadata: dict[str, Any],
    materialized: dict[str, Any],
    source_asset_base_uri: str = "",
) -> dict[str, Any]:
    return {
        "relation_id": f"PROJECT_NDVI_COG-{project_id}-{raster_product_id}",
        "project_id": project_id,
        "project_name": project.get("project_name") or project.get("XMMC"),
        "xmdm": project.get("XMDM"),
        "xmmc": project.get("XMMC"),
        "risk_scenario": project.get("risk_scenario"),
        "review_priority": project.get("review_priority"),
        "raster_product_id": raster_product_id,
        "raster_alias_zh": raster_product.get("alias_zh") or default_raster_alias_zh(raster_product, raster_product_id),
        "source_local_path": str(source_path),
        "source_asset_href": _join_uri(source_asset_base_uri, source_path.name) if source_asset_base_uri else "",
        "local_cog_path": str(cog_path),
        "artifact_href": materialized.get("target_uri"),
        "bucket": materialized.get("bucket"),
        "key": materialized.get("key"),
        "sha256": materialized.get("sha256"),
        "bytes_written": materialized.get("bytes_written"),
        "content_type": COG_MEDIA_TYPE,
        "cog_metadata": cog_metadata,
        "relation_type": "PROJECT_NDVI_CLIPPED_COG",
        "left_role": "territorial_project",
        "right_role": "remote_sensing_ndvi_observation",
        "semantic_metric": "project_ndvi_clipped_cog",
        "computed_by": "rasterio_cog_driver",
        "not_for_production": True,
    }


def build_cog_stac_item(
    artifact: dict[str, Any],
    *,
    collection: str,
    catalog_uri: str = "",
    item_datetime: str | None = None,
) -> dict[str, Any]:
    item_id = str(artifact.get("relation_id") or "")
    if not item_id:
        raise ValueError("artifact.relation_id is required")
    asset_href = str(artifact.get("artifact_href") or "")
    if not asset_href:
        raise ValueError("artifact.artifact_href is required")

    metadata = dict(artifact.get("cog_metadata") or {})
    properties = {
        "datetime": item_datetime or utc_now_z(),
        "mmfe:product_type": "derived_raster_cog_asset",
        "mmfe:semantic_metric": artifact.get("semantic_metric"),
        "mmfe:relation_type": artifact.get("relation_type"),
        "mmfe:left_role": artifact.get("left_role"),
        "mmfe:right_role": artifact.get("right_role"),
        "mmfe:computed_by": artifact.get("computed_by"),
        "mmfe:source_product_id": artifact.get("raster_product_id"),
        "mmfe:source_product_alias_zh": artifact.get("raster_alias_zh"),
        "mmfe:source_asset_href": artifact.get("source_asset_href"),
        "twm:project_id": artifact.get("project_id"),
        "twm:project_name": artifact.get("project_name"),
        "twm:risk_scenario": artifact.get("risk_scenario"),
        "twm:review_priority": artifact.get("review_priority"),
        "twm:not_for_production": bool(artifact.get("not_for_production", True)),
        "proj:epsg": safe_int(metadata.get("epsg")),
        "proj:bbox": metadata.get("bounds"),
        "proj:shape": [metadata.get("height"), metadata.get("width")],
        "proj:transform": metadata.get("transform"),
        "raster:width": safe_int(metadata.get("width")),
        "raster:height": safe_int(metadata.get("height")),
        "raster:bands": safe_int(metadata.get("count")),
        "raster:dtype": metadata.get("dtype"),
        "raster:nodata": metadata.get("nodata"),
        "raster:valid_pixel_count": safe_int(metadata.get("valid_pixel_count")),
        "raster:layout": metadata.get("layout"),
        "raster:compression": metadata.get("compression"),
        "raster:tiled": bool(metadata.get("tiled")),
        "raster:blockxsize": safe_int(metadata.get("blockxsize")),
        "raster:blockysize": safe_int(metadata.get("blockysize")),
        "raster:overviews": metadata.get("overviews"),
        "ndvi:mean": safe_float(metadata.get("mean")),
        "ndvi:min": safe_float(metadata.get("min")),
        "ndvi:max": safe_float(metadata.get("max")),
        "file:size": safe_int(artifact.get("bytes_written")),
        "file:checksum_sha256": artifact.get("sha256"),
        "mmfe:lineage": {
            "source_local_path": artifact.get("source_local_path", ""),
            "source_asset_href": artifact.get("source_asset_href", ""),
            "local_cog_path": artifact.get("local_cog_path", ""),
            "cog_driver": "rasterio.shutil.copy(driver=COG)",
        },
    }

    return {
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
                "type": COG_MEDIA_TYPE,
                "roles": ["data", "derived", "raster", "ndvi", "cog"],
                "title": f"NDVI clipped COG for {artifact.get('project_id', item_id)}",
                "raster:bands": [
                    {
                        "data_type": metadata.get("dtype"),
                        "nodata": metadata.get("nodata"),
                        "statistics": {
                            "minimum": safe_float(metadata.get("min")),
                            "mean": safe_float(metadata.get("mean")),
                            "maximum": safe_float(metadata.get("max")),
                        },
                    }
                ],
            }
        },
        "links": stac_links(catalog_uri, collection),
    }


def verify_s3_object_checksum(
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
        actual = read_s3_object(args, result["bucket"], result["key"])
    expected_sha256 = hashlib.sha256(expected).hexdigest()
    actual_sha256 = hashlib.sha256(actual).hexdigest()
    if actual_sha256 != expected_sha256:
        _exit_error(
            "COG read-back checksum mismatch",
            {
                "target_uri": result.get("target_uri"),
                "expected_sha256": expected_sha256,
                "actual_sha256": actual_sha256,
            },
        )


def read_back_stac_item(args: argparse.Namespace, backend: dict[str, Any], *, reader=None) -> dict[str, Any]:
    bucket = backend.get("bucket")
    key = backend.get("key")
    if not bucket or not key:
        raise RuntimeError("publish backend result must include bucket and key")
    if reader is not None:
        return reader(bucket=bucket, key=key)
    return json.loads(read_s3_object(args, bucket, key).decode("utf-8"))


def read_back_static_catalog(args: argparse.Namespace, backend: dict[str, Any], *, reader=None) -> dict[str, Any]:
    bucket = backend.get("bucket")
    catalog_key = backend.get("catalog_key")
    collections = list(backend.get("collections") or [])
    if not bucket or not catalog_key:
        raise RuntimeError("static catalog backend result must include bucket and catalog_key")
    if reader is not None:
        catalog = reader(bucket=bucket, key=catalog_key)
        collection_docs = {entry["collection"]: reader(bucket=bucket, key=entry["key"]) for entry in collections}
    else:
        catalog = json.loads(read_s3_object(args, bucket, catalog_key).decode("utf-8"))
        collection_docs = {
            entry["collection"]: json.loads(read_s3_object(args, bucket, entry["key"]).decode("utf-8"))
            for entry in collections
        }
    return {"catalog": catalog, "collections": collection_docs}


def read_s3_object(args: argparse.Namespace, bucket: str, key: str) -> bytes:
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
    return response["Body"].read()


def validate_read_back_item(expected: dict[str, Any], actual: dict[str, Any]) -> None:
    if actual.get("id") != expected.get("id"):
        _exit_error("read-back COG STAC item id mismatch", {"expected": expected.get("id"), "actual": actual.get("id")})
    if actual.get("collection") != expected.get("collection"):
        _exit_error(
            "read-back COG STAC collection mismatch",
            {"expected": expected.get("collection"), "actual": actual.get("collection")},
        )
    expected_asset = (expected.get("assets") or {}).get("data") or {}
    actual_asset = (actual.get("assets") or {}).get("data") or {}
    if actual_asset.get("href") != expected_asset.get("href"):
        _exit_error(
            "read-back COG STAC asset href mismatch",
            {"expected": expected_asset.get("href"), "actual": actual_asset.get("href")},
        )
    if "cog" not in list(actual_asset.get("roles") or []):
        _exit_error("read-back COG STAC asset roles missing cog", {"roles": actual_asset.get("roles")})


def validate_static_catalog_readback(
    collection: str,
    expected_items: list[dict[str, Any]],
    actual: dict[str, Any],
) -> None:
    catalog = actual.get("catalog") or {}
    collections = actual.get("collections") or {}
    if catalog.get("type") != "Catalog":
        _exit_error("read-back static STAC catalog type mismatch", {"actual": catalog.get("type")})
    collection_doc = collections.get(collection)
    if not isinstance(collection_doc, dict):
        _exit_error("read-back static STAC collection is missing", {"collection": collection})
    if collection_doc.get("type") != "Collection":
        _exit_error("read-back static STAC collection type mismatch", {"actual": collection_doc.get("type")})
    item_links = [link for link in collection_doc.get("links", []) if link.get("rel") == "item"]
    if len(item_links) != len(expected_items):
        _exit_error(
            "read-back static STAC item link count mismatch",
            {"expected": len(expected_items), "actual": len(item_links)},
        )
    expected_hrefs = sorted(str(item.get("href")) for item in expected_items)
    actual_hrefs = sorted(str(link.get("href")) for link in item_links)
    if actual_hrefs != expected_hrefs:
        _exit_error("read-back static STAC item href mismatch", {"expected": expected_hrefs, "actual": actual_hrefs})


def load_project_lookup(projects_path: Path) -> dict[str, dict[str, Any]]:
    if not projects_path.exists():
        return {}
    data = json.loads(projects_path.read_text(encoding="utf-8"))
    lookup: dict[str, dict[str, Any]] = {}
    for feature in data.get("features") or []:
        props = feature.get("properties") or {}
        project_id = str(props.get("project_id") or "")
        if project_id:
            lookup[project_id] = dict(props)
    return lookup


def load_raster_product_lookup(manifest_path: Path) -> dict[str, dict[str, Any]]:
    if not manifest_path.exists():
        return {}
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    lookup: dict[str, dict[str, Any]] = {}
    for product in (data.get("products") or {}).values():
        if not isinstance(product, dict):
            continue
        product_id = str(product.get("product_id") or "")
        if product_id:
            lookup[product_id] = dict(product)
    return lookup


def parse_clip_filename(path: Path) -> tuple[str, str]:
    stem = path.name
    suffix = "_ndvi_clip.tif"
    if not stem.endswith(suffix):
        raise ValueError(f"clip filename must end with {suffix}: {path.name}")
    core = stem[: -len(suffix)]
    project_id, sep, raster_product_id = core.partition("_")
    if not sep or not project_id or not raster_product_id:
        raise ValueError(f"clip filename must be <project>_<raster>_ndvi_clip.tif: {path.name}")
    return project_id, raster_product_id


def default_raster_alias_zh(product: dict[str, Any], product_id: str) -> str:
    product_type = str(product.get("type") or "").lower()
    formula = str(product.get("formula") or "").lower()
    if product_id == "REAL-S2-L2A-NDVI" or "ndvi" in formula:
        return "Sentinel-2 L2A NDVI\u89c2\u6d4b\u6805\u683c"
    if product_type:
        return f"{product_id} {product_type}"
    return product_id


def stac_links(catalog_uri: str, collection: str) -> list[dict[str, Any]]:
    links: list[dict[str, Any]] = []
    if catalog_uri:
        links.append({"rel": "root", "href": catalog_uri, "type": "application/json"})
    if catalog_uri and collection:
        links.append({"rel": "collection", "href": f"{catalog_uri.rstrip('/')}/{collection}", "type": "application/json"})
    return links


def _join_uri(base_uri: str, *parts: str) -> str:
    base = base_uri.rstrip("/")
    clean_parts = [str(part).strip("/") for part in parts if str(part).strip("/")]
    if not clean_parts:
        return base
    return "/".join([base, *clean_parts])


def _s3a_to_s3_uri(uri: str) -> str:
    if uri.startswith("s3a://"):
        return "s3://" + uri[6:]
    return uri


def safe_int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def safe_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def utc_now_z() -> str:
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
