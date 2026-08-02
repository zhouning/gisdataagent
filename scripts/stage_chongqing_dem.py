#!/usr/bin/env python3
"""Stage the restricted Chongqing DEM bundle without altering source bytes."""

from __future__ import annotations

import argparse
import json
import math
import os
import shutil
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
    CHONGQING_DEM_SOURCE_ADAPTER,
    resolve_source_adapter,
    sealed_bundle_identity,
)
from data_agent.standards_platform.application.acceptance import (  # noqa: E402
    sha256_file,
)

SOURCE_RELATIVE_PATH = Path(
    ".tmp/twm_standard_1128/自然资源一张图数据库标准1128/"
    "规划院提供数据样例及Demo系统功能演示建议/01数据样例/"
    "01重庆市DEM数据2020年/Chongqing_aster_gdem_80m.tif"
)
DEFAULT_SOURCE = REPO_ROOT / SOURCE_RELATIVE_PATH
DEFAULT_OUTPUT_ROOT = REPO_ROOT / ".tmp/dolphinscheduler-sandbox/chongqing-dem-ods-v1/source"
EXPECTED_BUNDLE_SHA256 = (
    "7e2cdcb92263283167e2305542dd1208e7fc907c56de365ea3b83cddcc60e333"
)
EXPECTED_PRIMARY_SHA256 = (
    "d3d167bc94f5d6ed52053942f0e98737557e94c8761497d74d58eb88bf9bd09f"
)
EXPECTED_VALID_PIXEL_COUNT = 998698
DEFAULT_BUCKET = "gis-agent-lakehouse"
OBJECT_PREFIX = "raw/planning/chongqing_dem_2020"


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
        default=os.environ.get("AWS_SECRET_ACCESS_KEY", "local_dev_minio_secret"),
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
        expected_primary_sha256=(
            None if args.allow_unsealed_source else EXPECTED_PRIMARY_SHA256
        ),
        expected_valid_pixel_count=(
            None if args.allow_unsealed_source else EXPECTED_VALID_PIXEL_COUNT
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
    expected_primary_sha256: str | None,
    expected_valid_pixel_count: int | None,
) -> dict[str, Any]:
    source = source_path.resolve(strict=True)
    adapter = resolve_source_adapter(CHONGQING_DEM_SOURCE_ADAPTER.adapter_id, source)
    identity = sealed_bundle_identity(source, adapter)
    bundle_sha256 = str(identity["bundle_sha256"])
    if expected_bundle_sha256 and bundle_sha256 != expected_bundle_sha256:
        raise RuntimeError("DEM source bundle identity does not match the seal")

    primary_sha256 = str(identity["members"][0]["sha256"])
    if expected_primary_sha256 and primary_sha256 != expected_primary_sha256:
        raise RuntimeError("DEM primary TIFF identity does not match the seal")

    profile = profile_raster(source)
    resolve_source_adapter(
        adapter.adapter_id,
        source,
        observed_driver=str(profile["driver"]),
    )
    first_band = profile["bands"][0]
    if (
        expected_valid_pixel_count is not None
        and first_band["valid_pixel_count"] != expected_valid_pixel_count
    ):
        raise RuntimeError("DEM valid pixel count does not match the seal")

    staging_root = output_root.resolve() / f"bundle-sha256-{bundle_sha256}"
    snapshots = []
    for member in identity["members"]:
        source_member = source.parent / str(member["name"])
        snapshots.append(
            _stage_member(
                source_path=source_member,
                member=member,
                staging_root=staging_root,
                bundle_sha256=bundle_sha256,
                bucket=bucket,
                materializer=materializer,
            )
        )

    manifest = {
        "schema": "gda.chongqing_dem_source_snapshot.v1",
        "status": "ready",
        "classification": adapter.classification,
        "snapshot_stage": "raw",
        "logical_target_stage": adapter.logical_target_stage,
        "publication_eligible": False,
        "standardization_status": "unmatched_holdout",
        "source_adapter": adapter.reference(),
        "source_bundle": identity,
        "source_profile": profile,
        "bundle_snapshot": {
            "member_count": len(snapshots),
            "members": snapshots,
            "all_readback_verified": all(item["readback_verified"] for item in snapshots),
        },
        "quality_state": {
            "raw_source_integrity": "passed",
            "full_pixel_scan": "passed",
            "cog_conformance": "not_evaluated",
            "ods_admission": "not_evaluated",
            "standard_mapping": "not_evaluated",
            "promotion": "blocked",
            "promotion_blockers": list(adapter.promotion_policy.blockers),
        },
    }
    manifest_path = output_root.resolve() / "source-snapshot-manifest.json"
    _write_json(manifest_path, manifest)
    return {**manifest, "manifest_path": str(manifest_path)}


def profile_raster(source_path: Path) -> dict[str, Any]:
    """Scan every full-resolution pixel and record the raster grid contract."""

    import numpy as np
    import rasterio

    band_profiles: list[dict[str, Any]] = []
    with rasterio.open(source_path) as dataset:
        for band_index in dataset.indexes:
            valid_pixel_count = 0
            nodata_pixel_count = 0
            value_sum = 0.0
            value_min: float | int | None = None
            value_max: float | int | None = None
            for _, window in dataset.block_windows(band_index):
                block = dataset.read(band_index, window=window, masked=True)
                values = block.compressed()
                valid_pixel_count += int(values.size)
                nodata_pixel_count += int(block.size - values.size)
                if values.size:
                    block_min = values.min().item()
                    block_max = values.max().item()
                    value_min = block_min if value_min is None else min(value_min, block_min)
                    value_max = block_max if value_max is None else max(value_max, block_max)
                    value_sum += float(values.astype(np.float64).sum())

            pixel_count = dataset.width * dataset.height
            if valid_pixel_count + nodata_pixel_count != pixel_count:
                raise RuntimeError("raster pixel accounting is not exact")
            band_profiles.append(
                {
                    "band": band_index,
                    "dtype": dataset.dtypes[band_index - 1],
                    "nodata": _json_number(dataset.nodatavals[band_index - 1]),
                    "pixel_count": pixel_count,
                    "valid_pixel_count": valid_pixel_count,
                    "nodata_pixel_count": nodata_pixel_count,
                    "min": _json_number(value_min),
                    "max": _json_number(value_max),
                    "mean": (
                        value_sum / valid_pixel_count if valid_pixel_count else None
                    ),
                    "overviews": dataset.overviews(band_index),
                    "mask_flags": [
                        flag.name for flag in dataset.mask_flag_enums[band_index - 1]
                    ],
                }
            )

        compression = dataset.compression.value if dataset.compression else None
        interleaving = dataset.interleaving.value if dataset.interleaving else None
        crs = dataset.crs.to_string() if dataset.crs else None
        epsg = dataset.crs.to_epsg() if dataset.crs else None
        transform = dataset.transform
        profile = {
            "driver": dataset.driver,
            "width": dataset.width,
            "height": dataset.height,
            "band_count": dataset.count,
            "crs": crs,
            "epsg": epsg,
            "bounds": [float(value) for value in dataset.bounds],
            "transform": [
                transform.a,
                transform.b,
                transform.c,
                transform.d,
                transform.e,
                transform.f,
            ],
            "pixel_size": [abs(transform.a), abs(transform.e)],
            "is_tiled": bool(dataset.profile.get("tiled", False)),
            "block_shapes": [list(shape) for shape in dataset.block_shapes],
            "compression": compression,
            "interleaving": interleaving,
            "bands": band_profiles,
            "full_resolution_scan": True,
            "samples_persisted": False,
        }
    if profile["crs"] is None:
        raise RuntimeError("DEM source must declare a CRS")
    return profile


def _stage_member(
    *,
    source_path: Path,
    member: dict[str, Any],
    staging_root: Path,
    bundle_sha256: str,
    bucket: str,
    materializer,
) -> dict[str, Any]:
    physical_sha256 = str(member["sha256"])
    immutable_dir = staging_root / f"physical-sha256-{physical_sha256}"
    immutable_dir.mkdir(parents=True, exist_ok=True)
    output_path = immutable_dir / source_path.name
    if output_path.exists():
        if sha256_file(output_path) != physical_sha256:
            raise RuntimeError("immutable local DEM member contains different bytes")
        local_created = False
    else:
        temporary = immutable_dir / f".{source_path.name}.{os.getpid()}.tmp"
        shutil.copyfile(source_path, temporary)
        if sha256_file(temporary) != physical_sha256:
            temporary.unlink(missing_ok=True)
            raise RuntimeError("copied DEM member checksum differs from source bundle")
        temporary.chmod(0o640)
        os.replace(temporary, output_path)
        local_created = True

    object_key = (
        f"{OBJECT_PREFIX}/bundle-sha256-{bundle_sha256}/"
        f"physical-sha256-{physical_sha256}/{source_path.name}"
    )
    upload = materializer(
        {
            "source_path": str(output_path),
            "target_uri": f"s3://{bucket}/{object_key}",
            "content_type": _content_type(source_path),
            "immutable": True,
            "verify_readback": True,
        }
    )
    if not upload.get("materialized") or not upload.get("verified"):
        raise RuntimeError("DEM bundle member upload was not verified")
    if str(upload.get("sha256")) != physical_sha256:
        raise RuntimeError("DEM bundle member readback differs from source")
    return {
        "name": source_path.name,
        "local_path": str(output_path),
        "physical_sha256": physical_sha256,
        "size_bytes": output_path.stat().st_size,
        "storage_uri": upload["target_uri"],
        "local_created": local_created,
        "object_created": bool(upload.get("created")),
        "readback_verified": True,
    }


def _content_type(path: Path) -> str:
    name = path.name.casefold()
    if name.endswith((".tif", ".tiff")):
        return "image/tiff"
    if name.endswith(".xml"):
        return "application/xml"
    if name.endswith(".tfw"):
        return "text/plain"
    return "application/octet-stream"


def _json_number(value: Any) -> float | int | None:
    if value is None:
        return None
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    content = json.dumps(value, ensure_ascii=True, indent=2, sort_keys=True) + "\n"
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(content, encoding="utf-8")
    temporary.chmod(0o640)
    os.replace(temporary, path)


if __name__ == "__main__":
    main()
