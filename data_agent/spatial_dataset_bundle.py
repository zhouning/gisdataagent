"""Path-free content fingerprints and spatial inventory for local datasets."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
from pathlib import Path
from typing import Any

from .platform_contracts import canonical_json_fingerprint

SHAPEFILE_BUNDLE_SCHEMA = "gda.spatial_dataset_bundle.v1"
_REQUIRED_SHAPEFILE_SUFFIXES = frozenset({".shp", ".shx", ".dbf", ".prj"})


class SpatialDatasetBundleError(RuntimeError):
    """A local dataset cannot produce a complete, path-free inventory."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _component_suffix(path: Path, stem_name: str) -> str:
    suffix = path.name[len(stem_name) :].lower()
    if not suffix.startswith("."):
        raise SpatialDatasetBundleError("dataset component has no stable suffix")
    return suffix


def _ogr_inventory(
    shapefile_path: Path,
    *,
    ogrinfo_path: Path,
    proj_data_path: Path | None,
) -> dict[str, Any]:
    environment = os.environ.copy()
    if proj_data_path is not None:
        if not (proj_data_path / "proj.db").is_file():
            raise SpatialDatasetBundleError("PROJ data directory has no proj.db")
        environment["PROJ_DATA"] = str(proj_data_path)
    result = subprocess.run(
        [str(ogrinfo_path), "-json", "-so", str(shapefile_path)],
        check=False,
        capture_output=True,
        text=True,
        env=environment,
    )
    if result.returncode != 0:
        raise SpatialDatasetBundleError("ogrinfo could not inspect the dataset")
    try:
        payload = json.loads(result.stdout)
        layer = payload["layers"][0]
        geometry = layer["geometryFields"][0]
        coordinate_system = geometry["coordinateSystem"]["projjson"]
    except (KeyError, IndexError, TypeError, ValueError) as exc:
        raise SpatialDatasetBundleError("ogrinfo JSON is incomplete") from exc
    authority = coordinate_system.get("id") or {}
    fields = layer.get("fields") or []
    return {
        "driver": payload.get("driverShortName"),
        "geometry_type": geometry.get("type"),
        "feature_count": layer.get("featureCount"),
        "field_count": len(fields),
        "crs": {
            "authority": authority.get("authority"),
            "code": authority.get("code"),
            "name": coordinate_system.get("name"),
        },
        "bounds": geometry.get("extent"),
    }


def build_shapefile_bundle_inventory(
    shapefile_path: Path,
    *,
    source_label: str,
    ogrinfo_path: Path | None = None,
    proj_data_path: Path | None = None,
) -> dict[str, Any]:
    """Hash every same-stem sidecar and omit all source filesystem paths."""
    shapefile_path = shapefile_path.resolve()
    if not shapefile_path.is_file() or shapefile_path.suffix.lower() != ".shp":
        raise SpatialDatasetBundleError("a readable .shp file is required")
    if not source_label.strip() or "/" in source_label or "\\" in source_label:
        raise SpatialDatasetBundleError("source label must be non-path text")
    stem_name = shapefile_path.stem
    components = sorted(
        (
            path
            for path in shapefile_path.parent.iterdir()
            if path.is_file() and path.name.startswith(f"{stem_name}.")
        ),
        key=lambda item: item.name.lower(),
    )
    suffixes = {_component_suffix(path, stem_name) for path in components}
    missing = sorted(_REQUIRED_SHAPEFILE_SUFFIXES - suffixes)
    if missing:
        raise SpatialDatasetBundleError(
            f"required shapefile components are missing: {', '.join(missing)}"
        )
    component_inventory = [
        {
            "component": _component_suffix(path, stem_name),
            "size_bytes": path.stat().st_size,
            "sha256": _sha256(path),
        }
        for path in components
    ]
    stable: dict[str, Any] = {
        "schema": SHAPEFILE_BUNDLE_SCHEMA,
        "source_label": source_label.strip(),
        "format": "ESRI Shapefile",
        "components": component_inventory,
        "spatial_inventory": (
            _ogr_inventory(
                shapefile_path,
                ogrinfo_path=ogrinfo_path,
                proj_data_path=proj_data_path,
            )
            if ogrinfo_path is not None
            else None
        ),
    }
    return {**stable, "content_sha256": canonical_json_fingerprint(stable)}


def validate_shapefile_bundle_inventory(inventory: dict[str, Any]) -> list[str]:
    """Validate checked evidence without requiring the local source dataset."""
    errors: list[str] = []
    stable = {key: value for key, value in inventory.items() if key != "content_sha256"}
    if inventory.get("schema") != SHAPEFILE_BUNDLE_SCHEMA:
        errors.append("spatial dataset bundle schema does not match")
    if inventory.get("content_sha256") != canonical_json_fingerprint(stable):
        errors.append("spatial dataset bundle SHA-256 does not match")
    if any(
        "/" in str(value) or "\\" in str(value)
        for value in (
            inventory.get("source_label", ""),
            *(item.get("component", "") for item in inventory.get("components", [])),
        )
    ):
        errors.append("spatial dataset bundle must not contain source paths")
    suffixes = {item.get("component") for item in inventory.get("components", [])}
    if not _REQUIRED_SHAPEFILE_SUFFIXES.issubset(suffixes):
        errors.append("spatial dataset bundle is missing required components")
    return errors
