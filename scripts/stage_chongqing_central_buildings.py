#!/usr/bin/env python3
"""Stage the restricted Chongqing central-building source as immutable GeoJSON."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from data_agent.fusion.s3_materialization_adapter import (  # noqa: E402
    build_s3_materialization_executor,
)
from data_agent.source_adapter_registry import (  # noqa: E402
    CENTRAL_BUILDINGS_SOURCE_ADAPTER,
    resolve_source_adapter,
    sealed_bundle_identity,
)
from data_agent.standards_platform.application.acceptance import (  # noqa: E402
    sha256_file,
)

SOURCE_RELATIVE_PATH = Path(
    ".tmp/twm_standard_1128/自然资源一张图数据库标准1128/"
    "规划院提供数据样例及Demo系统功能演示建议/01数据样例/"
    "04重庆市中心城区建筑物轮廓数据2021年/中心城区建筑数据带层高.shp"
)
DEFAULT_SOURCE = REPO_ROOT / SOURCE_RELATIVE_PATH
DEFAULT_OUTPUT_ROOT = (
    REPO_ROOT
    / ".tmp/dolphinscheduler-sandbox/central-buildings-ods-v1/source"
)
EXPECTED_BUNDLE_SHA256 = (
    "e2697e8215a26de4b5c2a526eb9bce7401ebc27e1fc64d5f6c30bf85ff149c0d"
)
EXPECTED_FEATURE_COUNT = 107452
DEFAULT_BUCKET = "gis-agent-lakehouse"
OBJECT_PREFIX = "raw/planning/chongqing_central_buildings_2021"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--bucket", default=DEFAULT_BUCKET)
    parser.add_argument(
        "--endpoint-url",
        default=os.environ.get("AWS_ENDPOINT_URL", "http://localhost:9000"),
    )
    parser.add_argument(
        "--access-key-id",
        default=os.environ.get("AWS_ACCESS_KEY_ID", "minio_admin"),
    )
    parser.add_argument(
        "--secret-access-key",
        default=os.environ.get(
            "AWS_SECRET_ACCESS_KEY", "local_dev_minio_secret"
        ),
    )
    parser.add_argument("--allow-unsealed-source", action="store_true")
    args = parser.parse_args()
    materializer = build_s3_materialization_executor(
        endpoint_url=args.endpoint_url,
        access_key_id=args.access_key_id,
        secret_access_key=args.secret_access_key,
    )
    result = stage_source(
        source_path=args.source,
        output_root=args.output_root,
        bucket=args.bucket,
        materializer=materializer,
        expected_bundle_sha256=(
            None if args.allow_unsealed_source else EXPECTED_BUNDLE_SHA256
        ),
        expected_feature_count=(
            None if args.allow_unsealed_source else EXPECTED_FEATURE_COUNT
        ),
    )
    print(json.dumps(result, ensure_ascii=True, indent=2, sort_keys=True))


def stage_source(
    *,
    source_path: Path,
    output_root: Path,
    bucket: str,
    materializer,
    expected_bundle_sha256: str | None,
    expected_feature_count: int | None,
) -> dict[str, Any]:
    source = source_path.resolve(strict=True)
    adapter = resolve_source_adapter(
        CENTRAL_BUILDINGS_SOURCE_ADAPTER.adapter_id,
        source,
    )
    identity = sealed_bundle_identity(source, adapter)
    bundle_sha256 = str(identity["bundle_sha256"])
    if expected_bundle_sha256 and bundle_sha256 != expected_bundle_sha256:
        raise RuntimeError("building source bundle identity does not match the seal")

    staging_dir = output_root.resolve() / f"bundle-sha256-{bundle_sha256}"
    staging_dir.mkdir(parents=True, exist_ok=True)
    temporary = staging_dir / ".chongqing-central-buildings-2021.geojson.tmp"
    profile = _write_geojson(source, temporary)
    resolve_source_adapter(
        adapter.adapter_id,
        source,
        observed_driver=str(profile["driver"]),
    )
    if expected_feature_count and profile["feature_count"] != expected_feature_count:
        temporary.unlink(missing_ok=True)
        raise RuntimeError("building source feature count does not match the seal")

    physical_sha256 = sha256_file(temporary)
    immutable_dir = staging_dir / f"physical-sha256-{physical_sha256}"
    immutable_dir.mkdir(parents=True, exist_ok=True)
    output_path = immutable_dir / "chongqing-central-buildings-2021.geojson"
    if output_path.exists():
        if sha256_file(output_path) != physical_sha256:
            raise RuntimeError("immutable local building target contains different bytes")
        temporary.unlink()
        local_created = False
    else:
        os.replace(temporary, output_path)
        output_path.chmod(0o640)
        local_created = True

    object_key = (
        f"{OBJECT_PREFIX}/bundle-sha256-{bundle_sha256}/"
        f"physical-sha256-{physical_sha256}/{output_path.name}"
    )
    upload = materializer(
        {
            "source_path": str(output_path),
            "target_uri": f"s3://{bucket}/{object_key}",
            "content_type": "application/geo+json",
            "immutable": True,
            "verify_readback": True,
        }
    )
    if not upload.get("materialized") or not upload.get("verified"):
        raise RuntimeError("building source upload was not verified")
    if str(upload.get("sha256")) != physical_sha256:
        raise RuntimeError("building source upload checksum differs from local snapshot")

    manifest = {
        "schema": "gda.chongqing_central_buildings_source_snapshot.v1",
        "status": "ready",
        "classification": "restricted",
        "publication_eligible": False,
        "standardization_status": "unmatched_holdout",
        "source_adapter": adapter.reference(),
        "source_bundle": identity,
        "source_profile": profile,
        "snapshot": {
            "local_path": str(output_path),
            "physical_sha256": physical_sha256,
            "size_bytes": output_path.stat().st_size,
            "storage_uri": upload["target_uri"],
            "local_created": local_created,
            "object_created": bool(upload.get("created")),
            "readback_verified": True,
        },
    }
    manifest_path = output_root.resolve() / "source-snapshot-manifest.json"
    _write_json(manifest_path, manifest)
    return {**manifest, "manifest_path": str(manifest_path)}


def _write_geojson(source_path: Path, target_path: Path) -> dict[str, Any]:
    import fiona
    from fiona.model import to_dict
    from shapely.geometry import shape

    geometry_value_counts: dict[str, int] = {}
    non_null_geometry_counts: dict[str, int] = {}
    feature_ids: set[int] = set()
    source_ids: set[int] = set()
    feature_count = 0
    null_geometry = 0
    empty_geometry = 0
    invalid_geometry = 0
    source_geometry_types: dict[str, int] = {}
    floor_min: int | None = None
    floor_max: int | None = None
    bounds: list[float] | None = None

    with fiona.open(source_path) as collection, target_path.open(
        "w", encoding="utf-8", newline="\n"
    ) as stream:
        crs = collection.crs.to_string() if collection.crs else None
        driver = collection.driver
        stream.write(
            '{"type":"FeatureCollection","name":"chongqing_central_buildings_2021",'
            '"crs":{"type":"name","properties":{"name":"urn:ogc:def:crs:'
            'OGC:1.3:CRS84"}},"features":['
        )
        first = True
        for feature in collection:
            try:
                source_fid = int(feature.id)
            except (TypeError, ValueError) as exc:
                raise RuntimeError("building source feature.id must be numeric") from exc
            if source_fid in feature_ids:
                raise RuntimeError("building source feature.id is not unique")
            feature_ids.add(source_fid)
            properties = feature.properties
            source_id = int(properties["Id"])
            floor_count = (
                int(properties["Floor"])
                if properties["Floor"] is not None
                else None
            )
            source_ids.add(source_id)
            if floor_count is not None:
                floor_min = floor_count if floor_min is None else min(floor_min, floor_count)
                floor_max = floor_count if floor_max is None else max(floor_max, floor_count)

            geometry = to_dict(feature.geometry) if feature.geometry is not None else None
            if geometry is None:
                null_geometry += 1
                geometry_value_counts["null"] = geometry_value_counts.get("null", 0) + 1
            else:
                source_geometry_type = str(geometry["type"])
                source_geometry_types[source_geometry_type] = (
                    source_geometry_types.get(source_geometry_type, 0) + 1
                )
                if source_geometry_type == "Polygon":
                    geometry = {
                        "type": "MultiPolygon",
                        "coordinates": [geometry["coordinates"]],
                    }
                elif source_geometry_type != "MultiPolygon":
                    raise RuntimeError(
                        "building source contains an unsupported geometry type: "
                        f"{source_geometry_type}"
                    )
                geometry_bytes = json.dumps(
                    geometry,
                    ensure_ascii=True,
                    separators=(",", ":"),
                    sort_keys=True,
                ).encode("ascii")
                geometry_sha256 = hashlib.sha256(geometry_bytes).hexdigest()
                geometry_key = f"sha256:{geometry_sha256}"
                geometry_value_counts[geometry_key] = (
                    geometry_value_counts.get(geometry_key, 0) + 1
                )
                non_null_geometry_counts[geometry_sha256] = (
                    non_null_geometry_counts.get(geometry_sha256, 0) + 1
                )
                shaped = shape(geometry)
                empty_geometry += int(shaped.is_empty)
                invalid_geometry += int(not shaped.is_valid)
                if not shaped.is_empty:
                    xmin, ymin, xmax, ymax = shaped.bounds
                    if bounds is None:
                        bounds = [xmin, ymin, xmax, ymax]
                    else:
                        bounds = [
                            min(bounds[0], xmin),
                            min(bounds[1], ymin),
                            max(bounds[2], xmax),
                            max(bounds[3], ymax),
                        ]

            document = {
                "type": "Feature",
                "id": source_fid,
                "properties": {
                    "source_fid": source_fid,
                    "source_id": source_id,
                    "floor_count": floor_count,
                },
                "geometry": geometry,
            }
            if not first:
                stream.write(",")
            stream.write(
                json.dumps(
                    document,
                    ensure_ascii=True,
                    separators=(",", ":"),
                    sort_keys=True,
                )
            )
            first = False
            feature_count += 1
        stream.write("]}")

    duplicate_geometry = sum(
        count - 1 for count in geometry_value_counts.values() if count > 1
    )
    duplicate_non_null_geometry = sum(
        count - 1 for count in non_null_geometry_counts.values() if count > 1
    )
    return {
        "feature_count": feature_count,
        "driver": driver,
        "distinct_source_fids": len(feature_ids),
        "distinct_source_ids": len(source_ids),
        "crs": crs,
        "source_geometry_types": dict(sorted(source_geometry_types.items())),
        "snapshot_geometry_type": "MultiPolygon",
        "bbox": bounds,
        "null_geometry": null_geometry,
        "empty_geometry": empty_geometry,
        "invalid_geometry": invalid_geometry,
        "duplicate_geometry": duplicate_geometry,
        "duplicate_non_null_geometry": duplicate_non_null_geometry,
        "floor_min": floor_min,
        "floor_max": floor_max,
    }


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    content = json.dumps(value, ensure_ascii=True, indent=2, sort_keys=True) + "\n"
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(content, encoding="utf-8")
    temporary.chmod(0o640)
    os.replace(temporary, path)


if __name__ == "__main__":
    main()
