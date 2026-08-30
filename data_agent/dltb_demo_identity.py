"""Dataset identity contract shared by the two-stage DLTB demonstration."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

DATASET_IDS = ("bishan", "dongxing", "chongqing_planning_sample", "ningxia")

_DATASETS: dict[str, dict[str, Any]] = {
    "bishan": {
        "dataset_name": "重庆市璧山区 Paper9 工程验证数据",
        "sample_scope": "Bishan engineering verification dataset; not Ningxia authority data",
        "expected": {
            "dltb": {
                "sha256": "7eccdfb11a98f4e31145e93fd270faea2774bed6ffaef99c66009c4eff9fb677",
                "feature_count": 101657,
                "crs": "EPSG:4326",
                "bbox": [
                    106.04001576200005,
                    29.282454706000067,
                    106.36873229600008,
                    29.887474954000083,
                ],
            },
            "dem": {
                "sha256": "8a1e2071e60ae75f0ffeb5f43fd01c4d1eaa69182c2bff0a36bf215c180d0e11",
            },
            "administrative_units": {
                "sha256": "bb72218b903024f804523877d5c52e0ef5fd20d8e671bdbdf480b500e46da3cb",
                "selection_field": "county_code",
                "selection_value": "500120",
                "selected_feature_count": 15,
                "source_feature_count": 44,
            },
        },
    },
    "dongxing": {
        "dataset_name": "四川省内江市东兴区 Paper9 工程验证数据",
        "sample_scope": "Dongxing engineering verification dataset; not Ningxia authority data",
        "expected": {
            "dltb": {
                "sha256": "eaa71184d9351c8a4099002b3b109c5cee002093c2444e3abadcbdd7fbae8426",
                "feature_count": 134369,
                "crs": "EPSG:4326",
            },
            "administrative_units": {
                "sha256": "bb72218b903024f804523877d5c52e0ef5fd20d8e671bdbdf480b500e46da3cb",
                "selection_field": "county_code",
                "selection_value": "511011",
                "selected_feature_count": 29,
                "source_feature_count": 44,
            },
        },
    },
    "chongqing_planning_sample": {
        "dataset_name": "重庆规划院混合排练样例",
        "sample_scope": (
            "Chongqing planning rehearsal sample; not Bishan, Dongxing, "
            "or Ningxia authority data"
        ),
    },
    "ningxia": {
        "dataset_name": "宁夏现场数据",
        "sample_scope": (
            "Ningxia incoming data; authority is determined by operator-supplied contracts"
        ),
    },
}


def sha256_path(path: str | Path) -> str:
    """Hash a file or directory while retaining directory member names."""

    source = Path(path).expanduser().resolve()
    digest = hashlib.sha256()
    if source.is_file():
        with source.open("rb") as handle:
            for chunk in iter(lambda: handle.read(8 * 1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()
    if not source.is_dir():
        raise FileNotFoundError(str(source))
    for member in sorted(item for item in source.rglob("*") if item.is_file()):
        digest.update(member.relative_to(source).as_posix().encode("utf-8"))
        with member.open("rb") as handle:
            for chunk in iter(lambda: handle.read(8 * 1024 * 1024), b""):
                digest.update(chunk)
    return digest.hexdigest()


def dataset_descriptor(dataset_id: str) -> dict[str, str]:
    if dataset_id not in _DATASETS:
        raise ValueError(f"unsupported dataset_id: {dataset_id}")
    definition = _DATASETS[dataset_id]
    return {
        "dataset_id": dataset_id,
        "dataset_name": str(definition["dataset_name"]),
        "sample_scope": str(definition["sample_scope"]),
    }


def _vector_profile(path: Path, preferred_layers: tuple[str, ...]) -> dict[str, Any]:
    if path.suffix.casefold() in {".parquet", ".geoparquet", ".parq"}:
        import geopandas as gpd

        frame = gpd.read_parquet(path)
        geometry_name = frame.geometry.name
        return {
            "layer": preferred_layers[0],
            "feature_count": int(len(frame)),
            "crs": frame.crs.to_string() if frame.crs is not None else None,
            "bbox": [float(value) for value in frame.total_bounds.tolist()]
            if not frame.empty
            else None,
            "geometry_type": ",".join(
                sorted(str(value) for value in frame.geometry.geom_type.dropna().unique())
            ),
            "columns": [str(column) for column in frame.columns if column != geometry_name],
            "source_layer_count": 1,
            "adapter": "geopandas_geoparquet",
        }
    from .local_gis_runtime import inspect_vector

    layers = inspect_vector(path)
    preferred = {name.casefold() for name in preferred_layers}
    selected = next(
        (
            layer
            for layer in layers
            if str(layer.get("name") or "").casefold() in preferred
        ),
        layers[0] if layers else None,
    )
    if not selected:
        raise ValueError(f"vector dataset has no readable layers: {path}")
    return {
        "layer": selected.get("name"),
        "feature_count": selected.get("feature_count"),
        "crs": selected.get("crs_name")
        or (f"EPSG:{selected['srid']}" if selected.get("srid") else None),
        "bbox": selected.get("extent"),
        "geometry_type": selected.get("geometry_type"),
        "columns": [
            str(field.get("name"))
            for field in selected.get("fields") or []
            if field.get("name")
        ],
        "source_layer_count": len(layers),
    }


def _raster_profile(path: Path) -> dict[str, Any]:
    import rasterio

    with rasterio.open(path) as dataset:
        bounds = dataset.bounds
        return {
            "crs": dataset.crs.to_string() if dataset.crs else None,
            "bbox": [
                float(bounds.left),
                float(bounds.bottom),
                float(bounds.right),
                float(bounds.top),
            ],
            "width": int(dataset.width),
            "height": int(dataset.height),
            "band_count": int(dataset.count),
        }


def _admin_selection(path: Path, expected: dict[str, Any]) -> dict[str, Any] | None:
    field = str(expected.get("selection_field") or "").strip()
    value = str(expected.get("selection_value") or "").strip()
    if not field or not value:
        return None
    import geopandas as gpd

    frame = gpd.read_file(path, columns=[field], ignore_geometry=True)
    selected = frame[field].astype("string").str.strip() == value
    return {
        "field": field,
        "value": value,
        "source_feature_count": int(len(frame)),
        "selected_feature_count": int(selected.sum()),
    }


def _same_bbox(actual: Any, expected: Any, tolerance: float = 1e-8) -> bool:
    if not isinstance(actual, (list, tuple)) or not isinstance(expected, (list, tuple)):
        return False
    if len(actual) != len(expected):
        return False
    try:
        return all(
            abs(float(left) - float(right)) <= tolerance
            for left, right in zip(actual, expected, strict=True)
        )
    except (TypeError, ValueError):
        return False


def build_dataset_identity(
    *,
    dataset_id: str,
    dltb: str | Path,
    dem: str | Path | None,
    administrative_units: str | Path | None,
    reference_years: dict[str, int | None],
    input_mode: str,
    validate_known_sources: bool = True,
) -> dict[str, Any]:
    """Build a durable identity manifest and verify known demo source files."""

    descriptor = dataset_descriptor(dataset_id)
    sources: dict[str, dict[str, Any] | None] = {}
    paths = {
        "dltb": Path(dltb).expanduser().resolve(),
        "dem": Path(dem).expanduser().resolve() if dem else None,
        "administrative_units": (
            Path(administrative_units).expanduser().resolve()
            if administrative_units
            else None
        ),
    }
    for role, path in paths.items():
        if path is None:
            sources[role] = None
            continue
        profile: dict[str, Any]
        if role == "dem":
            profile = _raster_profile(path)
        else:
            profile = _vector_profile(
                path,
                ("DLTB", "JQDLTB", "地类图斑")
                if role == "dltb"
                else ("ADMINISTRATIVE_UNITS", "admin_reference", "XZQ"),
            )
        sources[role] = {
            "path": str(path),
            "sha256": sha256_path(path),
            **profile,
        }

    expected_roles = (_DATASETS[dataset_id].get("expected") or {}) if validate_known_sources else {}
    checks: list[dict[str, Any]] = []
    for role, expected in expected_roles.items():
        actual = sources.get(role)
        if actual is None:
            checks.append(
                {
                    "role": role,
                    "check": "source_present",
                    "passed": False,
                    "expected": True,
                    "actual": False,
                }
            )
            continue
        for key in ("sha256", "feature_count", "crs"):
            if key not in expected:
                continue
            checks.append(
                {
                    "role": role,
                    "check": key,
                    "passed": actual.get(key) == expected[key],
                    "expected": expected[key],
                    "actual": actual.get(key),
                }
            )
        if "bbox" in expected:
            checks.append(
                {
                    "role": role,
                    "check": "bbox",
                    "passed": _same_bbox(actual.get("bbox"), expected["bbox"]),
                    "expected": expected["bbox"],
                    "actual": actual.get("bbox"),
                }
            )
        selection = (
            _admin_selection(paths[role], expected)
            if role == "administrative_units"
            else None
        )
        if selection:
            actual["dataset_selection"] = selection
            for key in ("source_feature_count", "selected_feature_count"):
                if key not in expected:
                    continue
                checks.append(
                    {
                        "role": role,
                        "check": key,
                        "passed": selection[key] == expected[key],
                        "expected": expected[key],
                        "actual": selection[key],
                    }
                )

    mismatches = [check for check in checks if not check["passed"]]
    if expected_roles:
        verification_status = "verified" if not mismatches else "mismatch"
    else:
        verification_status = "operator_declared"
    stable_fingerprints = {
        role: (source or {}).get("sha256") for role, source in sources.items()
    }
    manifest_sha256 = hashlib.sha256(
        json.dumps(
            {"dataset_id": dataset_id, "source_sha256": stable_fingerprints},
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()
    return {
        "schema": "gda.dltb-dataset-identity.v1",
        **descriptor,
        "input_mode": input_mode,
        "reference_years": reference_years,
        "sources": sources,
        "checks": checks,
        "mismatches": mismatches,
        "verification_status": verification_status,
        "identity_verified": verification_status == "verified",
        "manifest_sha256": manifest_sha256,
    }


def require_matching_identity(identity: dict[str, Any]) -> None:
    """Fail before ingest when a registered demo dataset does not match its identity."""

    if identity.get("verification_status") != "mismatch":
        return
    details = "; ".join(
        f"{item.get('role')}.{item.get('check')}: expected={item.get('expected')!r}, "
        f"actual={item.get('actual')!r}"
        for item in identity.get("mismatches") or []
    )
    raise ValueError(f"dataset_id {identity.get('dataset_id')} source identity mismatch: {details}")


def require_upstream_dataset_id(
    upstream: dict[str, Any] | None,
    dataset_id: str,
    *,
    required: bool,
) -> dict[str, Any] | None:
    """Require the phase-2 dataset id to match the phase-1 identity manifest."""

    if not upstream:
        if required:
            raise ValueError("phase-1 report with dataset_identity is required")
        return None
    identity = upstream.get("dataset_identity")
    if not isinstance(identity, dict) or not identity.get("dataset_id"):
        raise ValueError("phase-1 report has no dataset_identity.dataset_id; rerun phase 1")
    upstream_id = str(identity["dataset_id"])
    if upstream_id != dataset_id:
        raise ValueError(
            f"dataset_id mismatch: phase 2 requested {dataset_id!r}, "
            f"phase 1 produced {upstream_id!r}"
        )
    return identity
