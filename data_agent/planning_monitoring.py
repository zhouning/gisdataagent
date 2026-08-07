"""Auditable spatial-unit monitoring evaluation for planning implementation.

The module is intentionally a small deterministic model, not a chat feature or
a legal compliance engine.  It consumes governed GeoParquet/COG outputs and
produces indicators, relative diagnostics, quality evidence and lineage.  A
deployment can replace the grid with an approved administrative/planning-unit
contract later without changing the indicator contract.
"""

from __future__ import annotations

import hashlib
import json
import math
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from importlib.resources import files
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

MODEL_ID = "gda.nr.planning-monitoring.current-state"
MODEL_VERSION = "1.0.0"
CONTRACT_RESOURCE = "model_contracts/planning_monitoring_current_state.v1.json"
SEMANTIC_MAPPING_RESOURCE = "model_contracts/planning_monitoring_semantic_mapping.v1.json"


def _now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _json_clean(value: Any) -> Any:
    """Convert numpy values and non-finite floats before strict JSON output."""

    if isinstance(value, dict):
        return {str(key): _json_clean(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_clean(item) for item in value]
    if isinstance(value, (np.integer, np.floating)):
        value = value.item()
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, (pd.Timestamp, datetime)):
        return value.isoformat()
    return value


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(_json_clean(value), ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while block := handle.read(8 * 1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def load_model_contract() -> dict[str, Any]:
    resource = files("data_agent").joinpath(CONTRACT_RESOURCE)
    return json.loads(resource.read_text(encoding="utf-8"))


def _contract_hash(contract: dict[str, Any]) -> str:
    payload = json.dumps(contract, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class MonitoringConfig:
    """Runtime choices which must be recorded in the model evidence."""

    cell_size_m: int = 5000
    analysis_crs: str | None = None
    dem_resolution_m: int = 250
    sample_scope: str = "chongqing_demo"
    authority_mode: str = "rehearsal"
    ontology_binding_path: str | None = None
    semantic_mapping_path: str | None = None
    ontology_package_dir: str | None = None
    validate_ontology: bool = True


def discover_materialized_inputs(materialization_path: str | Path) -> dict[str, Any]:
    """Map materialization targets to model roles using conservative aliases.

    The mapping is a model input adapter, not an EA contract.  Every selected
    target keeps its original target id, source asset id and declared hash.
    """

    payload = json.loads(Path(materialization_path).read_text(encoding="utf-8"))
    targets = payload.get("outputs") or payload.get("targets") or []
    candidates: dict[str, list[dict[str, Any]]] = {
        "building": [],
        "poi": [],
        "road": [],
        "land_cover": [],
        "dem": [],
    }
    for target in targets:
        if target.get("execution_status") not in {None, "succeeded"}:
            continue
        path = str(target.get("target_path") or "")
        if not path or not Path(path).is_file():
            continue
        text = " ".join(
            str(target.get(key) or "")
            for key in ("target_name", "source_layer", "source_raw_path", "canonical_dataset")
        ).lower()
        role = None
        if path.lower().endswith((".tif", ".tiff")):
            if any(token in text for token in ("clcd", "landcover", "土地覆盖", "土地利用")):
                role = "land_cover"
            elif any(token in text for token in ("dem", "gdem", "elevation", "高程")):
                role = "dem"
        else:
            if any(token in text for token in ("建筑", "building", "zrz", "自然幢")):
                role = "building"
            elif any(token in text for token in ("poi", "兴趣点", "高德地图")):
                role = "poi"
            elif any(token in text for token in ("osm", "road", "道路", "路网")):
                role = "road"
        if role:
            candidates[role].append(target)

    # Prefer the largest/most complete target when a batch contains duplicates.
    selected: dict[str, dict[str, Any] | None] = {}
    for role, values in candidates.items():
        selected[role] = max(
            values,
            key=lambda item: int(
                (item.get("materialization_profile") or {}).get("feature_count") or 0
            )
            if not str(item.get("target_path", "")).lower().endswith((".tif", ".tiff"))
            else int(item.get("target_size") or 0),
            default=None,
        )
    return {
        "materialization": str(Path(materialization_path).resolve()),
        "targets": targets,
        "roles": selected,
    }


def load_semantic_mapping_contract(path: str | Path | None = None) -> dict[str, Any]:
    """Load the model's role-to-ontology mapping contract from the bundle."""

    if path:
        return json.loads(Path(path).expanduser().read_text(encoding="utf-8"))
    resource = files("data_agent").joinpath(SEMANTIC_MAPPING_RESOURCE)
    return json.loads(resource.read_text(encoding="utf-8"))


def _semantic_contract_hash(contract: dict[str, Any]) -> str:
    payload = json.dumps(contract, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _fold(value: Any) -> str:
    return str(value or "").strip().casefold()


def _binding_status_accepted(value: Any) -> bool:
    return _fold(value) in {
        "accepted",
        "accepted_for_rehearsal",
        "succeeded",
        "published",
    }


def _binding_matches_target(binding: dict[str, Any], target: dict[str, Any]) -> bool:
    """Match a binding entry to a materialization target without filename guessing."""

    target_id = str(target.get("target_id") or "")
    target_path = str(target.get("target_path") or "")
    source_asset_id = str(target.get("source_asset_id") or "")
    binding_target_id = str(binding.get("target_id") or "")
    binding_target_path = str(binding.get("target_path") or "")
    binding_source_asset_id = str(binding.get("source_asset_id") or "")
    # Prefer the immutable target identity.  A FileGDB bundle can contain many
    # layers with one source_asset_id, so source-only matching is a last resort.
    if binding_target_id:
        return bool(target_id and target_id == binding_target_id)
    if binding_target_path:
        return bool(
            target_path
            and Path(target_path).resolve() == Path(binding_target_path).resolve()
        )
    return bool(source_asset_id and source_asset_id == binding_source_asset_id)


def _load_ontology_runtime(
    semantic_mapping: dict[str, Any], config: MonitoringConfig
) -> tuple[dict[str, Any], list[str], list[str]]:
    """Validate referenced concepts/properties against the pinned ontology package.

    This is deliberately best-effort in rehearsal because a customer may first
    install the model bundle and then install the authority package. Production
    treats an unavailable or hash-invalid package as a hard semantic gate.
    """

    runtime: dict[str, Any] = {
        "status": "not_checked",
        "backend": None,
        "ontology_version": None,
        "content_sha256": None,
        "package_dir": config.ontology_package_dir,
    }
    errors: list[str] = []
    warnings: list[str] = []
    if not config.validate_ontology:
        runtime["status"] = "validation_disabled"
        warnings.append("ontology_runtime_validation_disabled")
        return runtime, errors, warnings
    try:
        from .ontology.service import OntologyService

        service = OntologyService(config.ontology_package_dir)
        status = service.status()
        runtime.update(
            {
                "status": "available",
                "backend": status.get("backend"),
                "ontology_version": status.get("semantic_version"),
                "ontology_version_id": status.get("ontology_version_id"),
                "content_sha256": status.get("content_sha256"),
                "authority_state": status.get("authority_state"),
            }
        )
        expected_version = str(semantic_mapping.get("ontology_version") or "")
        if expected_version and runtime["ontology_version"] != expected_version:
            errors.append(
                f"ontology_version_mismatch:expected={expected_version}:actual={runtime['ontology_version']}"
            )
        for role, role_spec in (semantic_mapping.get("roles") or {}).items():
            concept_id = role_spec.get("ontology_concept_id")
            if concept_id and service.get_concept(concept_id) is None:
                errors.append(f"ontology_concept_missing:{role}:{concept_id}")
            for property_spec in (role_spec.get("properties") or {}).values():
                property_id = property_spec.get("semantic_property_id")
                if not property_id or not concept_id:
                    continue
                properties = service.get_properties(
                    concept_id, include_effective=True
                ).get("items", [])
                if not any(item.get("property_id") == property_id for item in properties):
                    errors.append(f"ontology_property_missing:{role}:{property_id}")
            property_id = role_spec.get("semantic_property_id")
            if property_id and concept_id:
                properties = service.get_properties(
                    concept_id, include_effective=True
                ).get("items", [])
                if not any(item.get("property_id") == property_id for item in properties):
                    errors.append(f"ontology_property_missing:{role}:{property_id}")
    except Exception as exc:  # package hash/dependency/authority errors are evidence
        runtime.update({"status": "unavailable", "error": str(exc)})
        errors.append(f"ontology_runtime_unavailable:{exc}")
    if errors and config.authority_mode != "production":
        warnings.extend(errors)
        errors = []
        runtime["status"] = (
            "available_with_review"
            if runtime.get("status") == "available"
            else runtime["status"]
        )
    return runtime, errors, warnings


def validate_semantic_inputs(
    materialization_path: str | Path,
    inputs: dict[str, Any],
    config: MonitoringConfig,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Resolve model roles through an ontology binding and enforce its gate.

    Rehearsal may use explicit name aliases for inputs that have no accepted
    ontology binding, but the report records that fact and remains non-production.
    Production requires a binding for every selected input, including a hash of
    the exact materialized target, so a deployment cannot silently use a stale file.
    """

    semantic_mapping = load_semantic_mapping_contract(config.semantic_mapping_path)
    runtime, runtime_errors, runtime_warnings = _load_ontology_runtime(semantic_mapping, config)
    gate: dict[str, Any] = {
        "status": "pass",
        "authority_mode": config.authority_mode,
        "mapping_contract_id": semantic_mapping.get("contract_id"),
        "mapping_contract_hash": _semantic_contract_hash(semantic_mapping),
        "ontology": runtime,
        "roles": {},
        "errors": list(runtime_errors),
        "warnings": list(runtime_warnings),
        "binding_path": None,
        "binding_id": None,
        "binding_status": None,
    }
    binding: dict[str, Any] | None = None
    binding_path = config.ontology_binding_path
    if binding_path:
        path = Path(binding_path).expanduser().resolve()
        gate["binding_path"] = str(path)
        if not path.is_file():
            gate["errors"].append(f"ontology_binding_missing:{path}")
        else:
            try:
                binding = json.loads(path.read_text(encoding="utf-8"))
                gate["binding_id"] = binding.get("binding_id")
                gate["binding_status"] = binding.get("status")
                if not _binding_status_accepted(binding.get("status")):
                    gate["errors"].append(f"ontology_binding_status_not_accepted:{binding.get('status')}")
                if config.authority_mode == "production":
                    if (
                        binding.get("binding_mode") != "production"
                        or binding.get("production_eligible") is not True
                    ):
                        gate["errors"].append("ontology_binding_not_production_eligible")
                    if _fold(binding.get("ontology_version")) in {
                        "",
                        "natural-resource-ontology-pending",
                    }:
                        gate["errors"].append("ontology_binding_version_not_pinned")
                    expected_version = str(semantic_mapping.get("ontology_version") or "")
                    if expected_version and _fold(binding.get("ontology_version")) != _fold(
                        expected_version
                    ):
                        gate["errors"].append("ontology_binding_version_mismatch")
                    binding_content_hash = str(
                        binding.get("ontology_content_sha256") or ""
                    )
                    runtime_content_hash = str(runtime.get("content_sha256") or "")
                    if not binding_content_hash:
                        gate["errors"].append("ontology_binding_content_hash_required")
                    elif (
                        runtime_content_hash
                        and binding_content_hash != runtime_content_hash
                    ):
                        gate["errors"].append("ontology_binding_content_hash_mismatch")
            except (OSError, json.JSONDecodeError) as exc:
                gate["errors"].append(f"ontology_binding_invalid:{exc}")
    elif config.authority_mode == "production":
        gate["errors"].append("ontology_binding_required_in_production")
    else:
        gate["warnings"].append("ontology_binding_not_supplied_rehearsal_only")

    binding_entries = (binding or {}).get("bindings") or []
    skipped_ids = {
        str(item.get("target_id") or "") for item in ((binding or {}).get("skipped") or [])
    }
    targets = [
        target for target in (inputs.get("targets") or [])
        if target.get("execution_status") in {None, "succeeded"}
        and target.get("target_path")
        and Path(str(target["target_path"])).is_file()
    ]
    resolved_roles: dict[str, dict[str, Any] | None] = {}
    for role, role_spec in (semantic_mapping.get("roles") or {}).items():
        alias_target = (inputs.get("roles") or {}).get(role)
        accepted_codes = {_fold(code) for code in (role_spec.get("accepted_schema_codes") or [])}
        direct_candidates = []
        for target in targets:
            for entry in binding_entries:
                if not _binding_matches_target(entry, target):
                    continue
                canonical = _fold(entry.get("canonical_dataset"))
                concept_id = str(entry.get("ontology_concept_id") or "")
                if canonical in accepted_codes or concept_id == role_spec.get(
                    "ontology_concept_id"
                ):
                    direct_candidates.append((target, entry))
                    break
        chosen: dict[str, Any] | None = None
        role_resolution = "unresolved"
        if direct_candidates:
            target, entry = direct_candidates[0]
            chosen = dict(target)
            chosen["semantic_binding"] = dict(entry)
            chosen["role_resolution"] = "ontology_binding"
            role_resolution = "ontology_binding"
            declared_target_hash = target.get("target_sha256")
            binding_hash = entry.get("target_sha256")
            if binding_hash and declared_target_hash and binding_hash != declared_target_hash:
                gate["errors"].append(f"target_hash_mismatch:{role}:{target.get('target_id')}")
            if config.authority_mode == "production" and not binding_hash:
                gate["errors"].append(f"binding_target_hash_required:{role}:{target.get('target_id')}")
        elif (
            alias_target
            and config.authority_mode != "production"
            and role_spec.get("rehearsal_alias_fallback")
        ):
            chosen = dict(alias_target)
            chosen["role_resolution"] = "name_alias_rehearsal"
            role_resolution = "name_alias_rehearsal"
            gate["warnings"].append(f"role_resolved_by_alias_only:{role}")
        elif alias_target and config.authority_mode == "production":
            gate["errors"].append(f"role_target_not_bound:{role}:{alias_target.get('target_id')}")
        if alias_target and str(alias_target.get("target_id") or "") in skipped_ids:
            message = f"role_target_explicitly_skipped:{role}:{alias_target.get('target_id')}"
            if config.authority_mode == "production":
                gate["errors"].append(message)
            else:
                gate["warnings"].append(message)
        if role_spec.get("required") and chosen is None:
            gate["errors"].append(f"required_role_unresolved:{role}")
        resolved_roles[role] = chosen
        gate["roles"][role] = {
            "role": role,
            "required": bool(role_spec.get("required")),
            "ontology_concept_id": role_spec.get("ontology_concept_id"),
            "semantic_property_id": role_spec.get("semantic_property_id"),
            "target_id": chosen.get("target_id") if chosen else None,
            "target_path": chosen.get("target_path") if chosen else None,
            "canonical_dataset": (
                (chosen.get("semantic_binding") or {}).get("canonical_dataset")
                if chosen
                else None
            ),
            "role_resolution": role_resolution,
            "binding_hash_verified": bool(
                chosen
                and chosen.get("semantic_binding", {}).get("target_sha256")
                and chosen.get("target_sha256")
                == chosen.get("semantic_binding", {}).get("target_sha256")
            ),
        }
    if gate["errors"]:
        gate["status"] = "blocked"
    elif gate["warnings"]:
        gate["status"] = "review"
    inputs = dict(inputs)
    inputs["roles"] = resolved_roles
    inputs["semantic_mapping"] = semantic_mapping
    inputs["semantic_gate"] = gate
    return inputs, gate


def _read_vector(path: Path, *, columns: list[str] | None = None):
    import geopandas as gpd

    if path.suffix.lower() == ".parquet":
        kwargs = {"columns": columns} if columns else {}
        return gpd.read_parquet(path, **kwargs)
    from .local_gis_runtime import read_vector

    return read_vector(path)


def _role_target(inputs: dict[str, Any], role: str) -> tuple[Path | None, dict[str, Any] | None]:
    target = (inputs.get("roles") or {}).get(role)
    if not target:
        return None, None
    path = Path(str(target["target_path"])).expanduser().resolve()
    return path, target


def _select_analysis_crs(buildings, configured: str | None) -> str:
    if configured:
        return configured
    estimated = buildings.estimate_utm_crs()
    if estimated is None:
        raise ValueError("building layer has no usable CRS; analysis_crs is required")
    return estimated.to_string()


def _make_grid(buildings, analysis_crs: str, cell_size: int):
    import geopandas as gpd
    from shapely.geometry import box

    projected = buildings.to_crs(analysis_crs)
    minx, miny, maxx, maxy = projected.total_bounds
    if not np.isfinite([minx, miny, maxx, maxy]).all():
        raise ValueError("building extent is empty or non-finite")
    origin_x = math.floor(minx / cell_size) * cell_size
    origin_y = math.floor(miny / cell_size) * cell_size
    ncols = max(1, math.ceil((maxx - origin_x) / cell_size))
    nrows = max(1, math.ceil((maxy - origin_y) / cell_size))
    if nrows * ncols > 10000:
        raise ValueError("building extent produces more than 10,000 monitoring units")
    rows = []
    for row in range(nrows):
        for col in range(ncols):
            rows.append(
                {
                    "unit_id": f"U{row:04d}_{col:04d}",
                    "grid_row": row,
                    "grid_col": col,
                    "geometry": box(
                        origin_x + col * cell_size,
                        origin_y + row * cell_size,
                        origin_x + (col + 1) * cell_size,
                        origin_y + (row + 1) * cell_size,
                    ),
                }
            )
    return gpd.GeoDataFrame(rows, crs=analysis_crs), projected, {
        "origin_x": origin_x,
        "origin_y": origin_y,
        "nrows": nrows,
        "ncols": ncols,
    }


def _unit_indices(
    frame, grid_meta: dict[str, Any], cell_size: int
) -> tuple[np.ndarray, np.ndarray]:
    points = frame.geometry.representative_point()
    x = points.x.to_numpy()
    y = points.y.to_numpy()
    cols = np.floor((x - grid_meta["origin_x"]) / cell_size).astype("int64")
    rows = np.floor((y - grid_meta["origin_y"]) / cell_size).astype("int64")
    return rows, cols


def _aggregate_buildings(buildings, grid, grid_meta: dict[str, Any], cell_size: int):
    projected = buildings.to_crs(grid.crs).copy()
    original_count = len(projected)
    null_count = int(projected.geometry.isna().sum())
    non_null = projected[~projected.geometry.isna()].copy()
    empty_count = int(non_null.geometry.is_empty.sum())
    invalid_count = int((~non_null.geometry.is_valid).sum())
    non_null = non_null[~non_null.geometry.is_empty].copy()
    if invalid_count:
        non_null["geometry"] = non_null.geometry.make_valid()
    non_null = non_null[non_null.geometry.geom_type.isin(["Polygon", "MultiPolygon"])].copy()
    rows, cols = _unit_indices(non_null, grid_meta, cell_size)
    in_bounds = (
        (rows >= 0)
        & (rows < grid_meta["nrows"])
        & (cols >= 0)
        & (cols < grid_meta["ncols"])
    )
    non_null = non_null.loc[in_bounds].copy()
    non_null["grid_row"] = rows[in_bounds]
    non_null["grid_col"] = cols[in_bounds]
    non_null["__area_m2"] = non_null.geometry.area
    floor_col = next(
        (name for name in ("Floor", "floor", "层数", "总层数") if name in non_null), None
    )
    if floor_col:
        floors = pd.to_numeric(non_null[floor_col], errors="coerce")
        floors = floors.where((floors > 0) & (floors <= 200))
    else:
        floors = pd.Series(np.nan, index=non_null.index)
    non_null["__floor"] = floors
    non_null["__floor_area"] = non_null["__area_m2"] * non_null["__floor"]
    grouped = non_null.groupby(["grid_row", "grid_col"], dropna=False)
    aggregates = grouped.agg(
        building_count=("__area_m2", "size"),
        building_footprint_m2=("__area_m2", "sum"),
        avg_floors=("__floor", "mean"),
        estimated_floor_area_m2=("__floor_area", "sum"),
        valid_floor_count=("__floor", "count"),
    ).reset_index()
    result = grid.merge(aggregates, on=["grid_row", "grid_col"], how="left")
    for column in ("building_count", "building_footprint_m2", "valid_floor_count"):
        result[column] = result[column].fillna(0)
    result["unit_area_m2"] = result.geometry.area
    result["building_coverage_pct"] = result["building_footprint_m2"] / result["unit_area_m2"] * 100
    result["estimated_far"] = result["estimated_floor_area_m2"] / result["unit_area_m2"]
    return result, {
        "input_feature_count": original_count,
        "null_geometry_count": null_count,
        "empty_geometry_count": empty_count,
        "invalid_geometry_count": invalid_count,
        "geometry_used_count": int(len(non_null)),
        "floor_field": floor_col,
        "missing_or_invalid_floor_count": int(len(non_null) - floors.notna().sum()),
    }


def _aggregate_points(path: Path, grid, config: MonitoringConfig, grid_meta: dict[str, Any]):
    frame = _read_vector(path, columns=["geometry"])
    if frame.crs is None:
        raise ValueError(f"point source has no CRS: {path}")
    projected = frame.to_crs(grid.crs)
    rows, cols = _unit_indices(projected, grid_meta, config.cell_size_m)
    valid = (
        (~projected.geometry.isna().to_numpy())
        & (~projected.geometry.is_empty.to_numpy())
        & (rows >= 0)
        & (rows < grid_meta["nrows"])
        & (cols >= 0)
        & (cols < grid_meta["ncols"])
    )
    counts = pd.DataFrame({"grid_row": rows[valid], "grid_col": cols[valid]}).value_counts()
    result = grid[["unit_id"]].copy()
    result["poi_count"] = [
        int(counts.get((row, col), 0))
        for row, col in grid[["grid_row", "grid_col"]].itertuples(index=False)
    ]
    return result, {
        "input_feature_count": int(len(frame)),
        "valid_geometry_count": int(valid.sum()),
        "outside_grid_count": int((~valid).sum()),
    }


def _aggregate_roads(path: Path, grid):
    import geopandas as gpd

    frame = _read_vector(path)
    if frame.crs is None:
        raise ValueError(f"road source has no CRS: {path}")
    projected = frame.to_crs(grid.crs)
    projected = projected[~projected.geometry.isna() & ~projected.geometry.is_empty].copy()
    # Spatial intersection is needed here: assigning a long road to its
    # centroid would materially undercount boundary-crossing units.
    joined = gpd.overlay(
        projected[["geometry"]],
        grid[["unit_id", "geometry"]],
        how="intersection",
        keep_geom_type=False,
    )
    if len(joined):
        joined["__length_km"] = joined.geometry.length / 1000
        lengths = joined.groupby("unit_id")["__length_km"].sum()
    else:
        lengths = pd.Series(dtype="float64")
    result = grid[["unit_id"]].copy()
    result["road_length_km"] = result["unit_id"].map(lengths).fillna(0.0)
    return result, {
        "input_feature_count": int(len(frame)),
        "geometry_used_count": int(len(projected)),
        "intersected_piece_count": int(len(joined)),
    }


def _raster_unit_stats(path: Path, grid, *, role: str, dem_resolution_m: int):
    import rasterio
    from pyproj import Transformer
    from rasterio.mask import geometry_mask, mask
    from rasterio.vrt import WarpedVRT
    from shapely.geometry import mapping
    from shapely.ops import transform as shapely_transform

    stats: list[dict[str, Any]] = []
    if role == "dem":
        source = rasterio.open(path)
        transform_to_grid = Transformer.from_crs(grid.crs, source.crs, always_xy=True).transform
        try:
            with WarpedVRT(
                source,
                crs=grid.crs,
                resampling=rasterio.enums.Resampling.bilinear,
                resolution=(dem_resolution_m, dem_resolution_m),
            ) as dataset:
                for row in grid.itertuples(index=False):
                    try:
                        data, affine = mask(
                            dataset,
                            [mapping(row.geometry)],
                            crop=True,
                            filled=False,
                            indexes=1,
                        )
                    except ValueError:
                        stats.append(
                            {
                                "unit_id": row.unit_id,
                                "mean_elevation_m": np.nan,
                                "mean_slope_deg": np.nan,
                                "dem_valid_fraction": 0.0,
                            }
                        )
                        continue
                    inside = geometry_mask(
                        [mapping(row.geometry)],
                        out_shape=data.shape,
                        transform=affine,
                        invert=True,
                    )
                    values = np.asarray(data.data, dtype="float64")
                    valid = inside & ~np.ma.getmaskarray(data) & np.isfinite(values)
                    if not valid.any():
                        stats.append(
                            {
                                "unit_id": row.unit_id,
                                "mean_elevation_m": np.nan,
                                "mean_slope_deg": np.nan,
                                "dem_valid_fraction": 0.0,
                            }
                        )
                        continue
                    values[~valid] = np.nan
                    gy, gx = np.gradient(values, abs(affine.e), abs(affine.a))
                    slope = np.degrees(np.arctan(np.hypot(gx, gy)))
                    slope_valid = valid & np.isfinite(slope)
                    stats.append(
                        {
                            "unit_id": row.unit_id,
                            "mean_elevation_m": float(np.nanmean(values[valid])),
                            "mean_slope_deg": (
                                float(np.nanmean(slope[slope_valid]))
                                if slope_valid.any()
                                else np.nan
                            ),
                            "dem_valid_fraction": float(
                                valid.sum() / max(int(inside.sum()), 1)
                            ),
                        }
                    )
        finally:
            source.close()
        return pd.DataFrame(stats), {"input_path": str(path), "role": role}

    with rasterio.open(path) as dataset:
        transform_to_grid = Transformer.from_crs(grid.crs, dataset.crs, always_xy=True).transform
        for row in grid.itertuples(index=False):
            geom = shapely_transform(transform_to_grid, row.geometry)
            try:
                data, affine = mask(
                    dataset, [mapping(geom)], crop=True, filled=False, indexes=1
                )
            except ValueError:
                stats.append(
                    {
                        "unit_id": row.unit_id,
                        "impervious_share_pct": np.nan,
                        "water_share_pct": np.nan,
                        "land_cover_valid_fraction": 0.0,
                    }
                )
                continue
            inside = geometry_mask(
                [mapping(geom)], out_shape=data.shape, transform=affine, invert=True
            )
            values = np.asarray(data.data)
            valid = inside & ~np.ma.getmaskarray(data) & np.isfinite(values)
            total = int(valid.sum())
            stats.append(
                {
                    "unit_id": row.unit_id,
                    "impervious_share_pct": (
                        float((values[valid] == 8).sum() / total * 100) if total else np.nan
                    ),
                    "water_share_pct": (
                        float((values[valid] == 5).sum() / total * 100) if total else np.nan
                    ),
                    "land_cover_valid_fraction": float(total / max(int(inside.sum()), 1)),
                }
            )
    return pd.DataFrame(stats), {"input_path": str(path), "role": role}


def _percentile(series: pd.Series, quantile: float) -> float | None:
    values = pd.to_numeric(series, errors="coerce").dropna()
    return float(values.quantile(quantile)) if len(values) else None


def _relative_diagnostics(frame: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, Any]]:
    import pandas.api.types as ptypes

    thresholds = {
        "far_p25": _percentile(frame["estimated_far"], 0.25),
        "far_p75": _percentile(frame["estimated_far"], 0.75),
        "poi_p25": _percentile(frame["poi_density_km2"], 0.25),
        "road_p25": _percentile(frame["road_density_km_km2"], 0.25),
        "slope_p75": _percentile(frame["mean_slope_deg"], 0.75),
        "impervious_p75": _percentile(frame["impervious_share_pct"], 0.75),
    }
    diagnostics: list[list[str]] = []
    far_high = thresholds["far_p75"]
    poi_low = thresholds["poi_p25"]
    road_low = thresholds["road_p25"]
    slope_high = thresholds["slope_p75"]
    impervious_high = thresholds["impervious_p75"]
    for row in frame.itertuples(index=False):
        values: list[str] = []
        if (
            far_high is not None
            and poi_low is not None
            and pd.notna(row.estimated_far)
            and pd.notna(row.poi_density_km2)
            and row.estimated_far >= far_high
            and row.poi_density_km2 <= poi_low
        ):
            values.append("HIGH_BUILD_LOW_SERVICE")
        if (
            road_low is not None
            and pd.notna(row.road_density_km_km2)
            and row.road_density_km_km2 <= road_low
        ):
            values.append("LOW_ROAD_DENSITY")
        if (
            slope_high is not None
            and pd.notna(row.mean_slope_deg)
            and row.mean_slope_deg >= slope_high
        ):
            values.append("HIGH_TERRAIN_CONSTRAINT")
        if (
            impervious_high is not None
            and pd.notna(row.impervious_share_pct)
            and row.impervious_share_pct >= impervious_high
        ):
            values.append("HIGH_IMPERVIOUS_PRESSURE")
        diagnostics.append(values)
    frame = frame.copy()
    frame["diagnostic_codes"] = diagnostics
    frame["diagnostic_count"] = [len(item) for item in diagnostics]

    score_parts = []
    for column, weight in (
        ("estimated_far", 0.4),
        ("poi_density_km2", 0.3),
        ("road_density_km_km2", 0.3),
    ):
        if column not in frame:
            continue
        values = pd.to_numeric(frame[column], errors="coerce")
        if ptypes.is_numeric_dtype(values) and values.notna().sum() >= 2:
            score_parts.append(values.rank(pct=True) * weight)
    frame["current_state_intensity_score"] = sum(score_parts) * 100 if score_parts else np.nan
    frame["current_state_intensity_rank"] = (
        frame["current_state_intensity_score"]
        .rank(method="min", ascending=False)
        .where(frame["current_state_intensity_score"].notna())
    )
    return frame, thresholds


def _blocked_summary(
    output: Path,
    run_id: str,
    contract: dict[str, Any],
    config: MonitoringConfig,
    gate: dict[str, Any],
) -> dict[str, Any]:
    """Persist a deterministic blocked result so operators have actionable evidence."""

    quality_path = output / "quality_report.json"
    quality = {
        "run_id": run_id,
        "status": "blocked",
        "checks": {"semantic_gate": gate},
        "limitations": ["模型计算未执行；请先修复语义绑定闸门"],
    }
    _write_json(quality_path, quality)
    _write_json(output / "semantic_gate_report.json", gate)
    summary = {
        "run_id": run_id,
        "model_id": MODEL_ID,
        "model_version": MODEL_VERSION,
        "contract_id": contract.get("contract_id"),
        "contract_hash": _contract_hash(contract),
        "sample_scope": config.sample_scope,
        "authority_mode": config.authority_mode,
        "production_eligible": False,
        "status": "blocked",
        "unit_count": 0,
        "semantic_gate": gate,
        "semantic_mapping_contract_hash": gate.get("mapping_contract_hash"),
        "quality_report": str(quality_path),
        "started_at": _now(),
    }
    _write_json(output / "monitoring_evaluation_report.json", summary)
    (output / "monitoring_evaluation_report.md").write_text(
        "# 规划实施智能监测评估模型：执行阻断\n\n"
        f"- 运行：`{run_id}`；状态：`blocked`\n"
        f"- 原因：`{'; '.join(gate.get('errors') or ['semantic_gate_blocked'])}`\n"
        "- 未生成指标结果；修复语义绑定、本体版本或目标哈希后重新执行。\n",
        encoding="utf-8",
    )
    return summary


def _record_source_property_mappings(
    gate: dict[str, Any], role: str, frame: Any, semantic_mapping: dict[str, Any]
) -> None:
    """Record source column -> ontology property -> model field mappings."""

    role_spec = (semantic_mapping.get("roles") or {}).get(role) or {}
    role_gate = (gate.get("roles") or {}).get(role)
    if role_gate is None:
        return
    columns = {str(column).casefold(): str(column) for column in getattr(frame, "columns", [])}
    mappings = []
    for model_field, property_spec in (role_spec.get("properties") or {}).items():
        aliases = property_spec.get("source_aliases") or []
        source_column = next(
            (columns[_fold(alias)] for alias in aliases if _fold(alias) in columns),
            None,
        )
        mappings.append(
            {
                "model_field": property_spec.get("model_field") or model_field,
                "semantic_property_id": property_spec.get("semantic_property_id"),
                "source_column": source_column,
                "status": "resolved" if source_column else "unresolved",
                "required": bool(property_spec.get("required")),
                "used_by_indicators": property_spec.get("used_by_indicators") or [],
            }
        )
        if property_spec.get("required") and source_column is None:
            gate.setdefault("errors", []).append(
                f"required_source_property_missing:{role}:{property_spec.get('semantic_property_id')}"
            )
    role_gate["property_mappings"] = mappings


def _record_raster_property_mappings(gate: dict[str, Any], role: str, dataset: Any) -> None:
    role_gate = (gate.get("roles") or {}).get(role)
    if role_gate is None:
        return
    role_gate["property_mappings"] = [
        {
            "model_field": "raster_band_1",
            "semantic_property_id": role_gate.get("semantic_property_id"),
            "source_column": None,
            "source_band": 1,
            "status": "resolved" if getattr(dataset, "count", 0) >= 1 else "unresolved",
            "required": role == "dem",
            "crs": str(getattr(dataset, "crs", None) or ""),
            "nodata": getattr(dataset, "nodata", None),
        }
    ]


def run_monitoring_evaluation(
    materialization_path: str | Path,
    output_dir: str | Path,
    *,
    config: MonitoringConfig | None = None,
) -> dict[str, Any]:
    """Run the model and persist all evidence under ``output_dir``."""

    config = config or MonitoringConfig()
    output = Path(output_dir).expanduser().resolve()
    output.mkdir(parents=True, exist_ok=True)
    contract = load_model_contract()
    inputs = discover_materialized_inputs(materialization_path)
    run_id = f"monitor-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex[:8]}"
    if config.authority_mode not in {"rehearsal", "production"}:
        raise ValueError("authority_mode must be rehearsal or production")
    inputs, semantic_gate = validate_semantic_inputs(materialization_path, inputs, config)
    if semantic_gate["status"] == "blocked":
        return _blocked_summary(output, run_id, contract, config, semantic_gate)
    input_evidence: dict[str, Any] = {}
    for role, target in (inputs.get("roles") or {}).items():
        if not target:
            continue
        path = Path(str(target["target_path"])).resolve()
        actual_hash = _sha256(path)
        declared_hash = target.get("target_sha256")
        input_evidence[role] = {
            "role": role,
            "path": str(path),
            "target_id": target.get("target_id"),
            "source_asset_id": target.get("source_asset_id"),
            "declared_sha256": declared_hash,
            "actual_sha256": actual_hash,
            "sha256_verified": not declared_hash or declared_hash == actual_hash,
            "target_name": target.get("target_name"),
            "canonical_dataset": (target.get("semantic_binding") or {}).get(
                "canonical_dataset"
            ),
            "ontology_concept_id": semantic_gate["roles"][role].get(
                "ontology_concept_id"
            ),
            "role_resolution": target.get("role_resolution"),
            "binding_id": semantic_gate.get("binding_id"),
        }
    if config.authority_mode == "production":
        hash_failures = [
            role for role, evidence in input_evidence.items() if not evidence["sha256_verified"]
        ]
        if hash_failures:
            semantic_gate["errors"].extend(
                f"materialized_target_hash_mismatch:{role}" for role in hash_failures
            )
            semantic_gate["status"] = "blocked"
            return _blocked_summary(output, run_id, contract, config, semantic_gate)
    building_path, _ = _role_target(inputs, "building")
    if not building_path:
        raise ValueError("no building target found; model requires a polygon building source")

    raw_buildings = _read_vector(building_path)
    if raw_buildings.empty:
        raise ValueError("building source is empty")
    semantic_mapping = inputs["semantic_mapping"]
    _record_source_property_mappings(
        semantic_gate, "building", raw_buildings, semantic_mapping
    )
    if semantic_gate.get("errors"):
        semantic_gate["status"] = "blocked"
        return _blocked_summary(output, run_id, contract, config, semantic_gate)
    for raster_role in ("land_cover", "dem"):
        raster_path, _ = _role_target(inputs, raster_role)
        if not raster_path:
            continue
        import rasterio

        with rasterio.open(raster_path) as dataset:
            _record_raster_property_mappings(semantic_gate, raster_role, dataset)
    analysis_crs = _select_analysis_crs(raw_buildings, config.analysis_crs)
    grid, _, grid_meta = _make_grid(raw_buildings, analysis_crs, config.cell_size_m)
    units, building_quality = _aggregate_buildings(
        raw_buildings, grid, grid_meta, config.cell_size_m
    )
    units = units[units["building_count"] > 0].copy()
    # The grid's active cells are the observed building extent.  This avoids
    # claiming that empty cells represent planned land or administrative area.
    if units.empty:
        raise ValueError("no valid building geometry could be assigned to monitoring units")

    role_quality: dict[str, Any] = {"building": building_quality}
    for role, columns in (
        ("poi", ["poi_count"]),
        ("road", ["road_length_km"]),
        ("land_cover", ["impervious_share_pct", "water_share_pct"]),
        ("dem", ["mean_elevation_m", "mean_slope_deg"]),
    ):
        path, _ = _role_target(inputs, role)
        if not path:
            for column in columns:
                units[column] = np.nan
            continue
        if role == "poi":
            aggregate, quality = _aggregate_points(path, grid, config, grid_meta)
        elif role == "road":
            aggregate, quality = _aggregate_roads(path, grid)
        else:
            aggregate, quality = _raster_unit_stats(
                path, grid, role=role, dem_resolution_m=config.dem_resolution_m
            )
        units = units.merge(aggregate, on=["unit_id"], how="left")
        role_quality[role] = quality

    units["poi_density_km2"] = units["poi_count"] / (units["unit_area_m2"] / 1_000_000)
    units["road_density_km_km2"] = units["road_length_km"] / (units["unit_area_m2"] / 1_000_000)
    units, thresholds = _relative_diagnostics(units)
    units = units.sort_values(["current_state_intensity_rank", "unit_id"], na_position="last")

    # Keep the spatial output small enough for the offline UI while retaining
    # every computed indicator and a stable unit identifier.
    spatial_path = output / "spatial_units.parquet"
    units.to_parquet(spatial_path, index=False)
    units.to_file(output / "spatial_units.geojson", driver="GeoJSON")
    csv_path = output / "indicators.csv"
    units.drop(columns="geometry").to_csv(csv_path, index=False, encoding="utf-8-sig")

    role_status = {
        role: "available" if evidence
        else "missing"
        for role, evidence in input_evidence.items()
    }
    missing_optional = [
        role for role in ("poi", "road", "land_cover", "dem") if role not in input_evidence
    ]
    quality_status = "pass"
    if (
        missing_optional
        or building_quality["null_geometry_count"]
        or building_quality["empty_geometry_count"]
        or building_quality["invalid_geometry_count"]
        or building_quality["missing_or_invalid_floor_count"]
    ):
        quality_status = "review"
    for role in ("land_cover", "dem"):
        if role in role_quality:
            fraction_column = (
                "land_cover_valid_fraction"
                if role == "land_cover"
                else "dem_valid_fraction"
            )
            fractions = units[fraction_column]
            if fractions.notna().any() and float(fractions.median()) < 0.8:
                quality_status = "review"
    hash_verified = all(item["sha256_verified"] for item in input_evidence.values())
    if not hash_verified:
        quality_status = "blocked"
    if semantic_gate.get("status") == "review" and quality_status == "pass":
        quality_status = "review"
    if semantic_gate.get("status") == "blocked":
        quality_status = "blocked"

    outputs = []
    for path, kind in (
        (spatial_path, "geoparquet"),
        (output / "spatial_units.geojson", "geojson"),
        (csv_path, "csv"),
    ):
        outputs.append(
            {
                "path": str(path),
                "kind": kind,
                "sha256": _sha256(path),
                "size": path.stat().st_size,
            }
        )
    lineage = {
        "lineage_id": f"lineage:{run_id}",
        "run_id": run_id,
        "model_id": MODEL_ID,
        "model_version": MODEL_VERSION,
        "contract_hash": _contract_hash(contract),
        "semantic_mapping_contract_hash": semantic_gate.get("mapping_contract_hash"),
        "ontology": semantic_gate.get("ontology"),
        "binding_id": semantic_gate.get("binding_id"),
        "edges": [
            {
                "source": evidence["target_id"] or evidence["actual_sha256"],
                "source_role": role,
                "source_sha256": evidence["actual_sha256"],
                "target": f"model-run:{run_id}",
                "relation": "consumed_by_model",
            }
            for role, evidence in input_evidence.items()
        ]
        + [
            {
                "source": role_evidence.get("target_id") or role,
                "target": role_evidence.get("ontology_concept_id"),
                "relation": "semantically_bound_to",
                "role": role,
                "resolution": role_evidence.get("role_resolution"),
            }
            for role, role_evidence in (semantic_gate.get("roles") or {}).items()
            if role_evidence.get("target_id") and role_evidence.get("ontology_concept_id")
        ]
        + [
            {"source": f"model-run:{run_id}", "target": item["path"], "relation": "materialized"}
            for item in outputs
        ],
    }
    _write_json(output / "lineage.json", lineage)
    quality = {
        "run_id": run_id,
        "status": quality_status,
        "checks": {
            "input_hashes": {
                role: item["sha256_verified"] for role, item in input_evidence.items()
            },
            "building": building_quality,
            "role_availability": role_status,
            "missing_optional_roles": missing_optional,
            "land_cover_median_valid_fraction": (
                float(units["land_cover_valid_fraction"].median())
                if "land_cover_valid_fraction" in units
                and units["land_cover_valid_fraction"].notna().any()
                else None
            ),
            "dem_median_valid_fraction": (
                float(units["dem_valid_fraction"].median())
                if "dem_valid_fraction" in units
                and units["dem_valid_fraction"].notna().any()
                else None
            ),
        },
        "role_quality": role_quality,
        "semantic_gate": semantic_gate,
        "limitations": [
            "重庆样例不是宁夏权威数据",
            "空间单元为建筑范围规则网格，不是法定行政区或规划评估单元",
            "诊断阈值为样例内部P25/P75，不是政策阈值",
            "单期数据不能证明规划目标达成趋势或年度变化",
        ],
    }
    _write_json(output / "quality_report.json", quality)
    _write_json(output / "semantic_gate_report.json", semantic_gate)

    diagnostic_counts = (
        pd.Series([code for codes in units["diagnostic_codes"] for code in codes])
        .value_counts()
        .to_dict()
    )
    semantic_roles = semantic_gate.get("roles") or {}
    production_eligible = bool(
        config.authority_mode == "production"
        and quality_status == "pass"
        and semantic_gate.get("status") == "pass"
        and semantic_gate.get("ontology", {}).get("status") == "available"
        and all(
            evidence.get("role_resolution") == "ontology_binding"
            and evidence.get("binding_hash_verified")
            for evidence in semantic_roles.values()
            if evidence.get("target_id")
        )
    )
    summary = {
        "run_id": run_id,
        "model_id": MODEL_ID,
        "model_version": MODEL_VERSION,
        "contract_id": contract.get("contract_id"),
        "contract_hash": _contract_hash(contract),
        "sample_scope": config.sample_scope,
        "authority_mode": config.authority_mode,
        "production_eligible": production_eligible,
        "status": "succeeded_with_review" if quality_status == "review" else quality_status,
        "analysis_crs": analysis_crs,
        "cell_size_m": config.cell_size_m,
        "unit_count": int(len(units)),
        "input_evidence": input_evidence,
        "semantic_gate": semantic_gate,
        "semantic_mapping_contract_hash": semantic_gate.get("mapping_contract_hash"),
        "ontology": semantic_gate.get("ontology"),
        "ontology_binding_id": semantic_gate.get("binding_id"),
        "metric_semantics": [
            {
                "metric_code": indicator.get("code"),
                "source_roles": indicator.get("source_roles") or [],
                "source_concepts": [
                    semantic_roles.get(role, {}).get("ontology_concept_id")
                    for role in (indicator.get("source_roles") or [])
                    if semantic_roles.get(role, {}).get("ontology_concept_id")
                ],
                "spatial_unit_concept_id": "gda:nr:class:SpatialUnit",
                "formula_contract": indicator.get("formula"),
                "unit": indicator.get("unit"),
                "period": indicator.get("period"),
            }
            for indicator in (contract.get("indicators") or [])
        ],
        "role_quality": role_quality,
        "relative_thresholds": thresholds,
        "diagnostic_counts": {str(key): int(value) for key, value in diagnostic_counts.items()},
        "outputs": outputs,
        "quality_report": str(output / "quality_report.json"),
        "lineage": str(output / "lineage.json"),
        "started_at": _now(),
        "limitations": quality["limitations"],
    }
    _write_json(output / "monitoring_evaluation_report.json", summary)
    _write_markdown(output / "monitoring_evaluation_report.md", summary, units)
    return summary


def _write_markdown(path: Path, summary: dict[str, Any], units) -> None:
    top = units.head(10)
    lines = [
        "# 规划实施智能监测评估模型：重庆样例现状演练",
        "",
        f"- 模型：`{summary['model_id']}@{summary['model_version']}`",
        f"- 运行：`{summary['run_id']}`；状态：`{summary['status']}`",
        f"- 样例范围：{summary['sample_scope']}；生产发布：`{summary['production_eligible']}`",
        f"- 语义闸门：`{(summary.get('semantic_gate') or {}).get('status', 'not_recorded')}`；"
        f"本体：`{(summary.get('ontology') or {}).get('ontology_version') or 'unavailable'}`",
        f"- 空间单元：{summary['unit_count']} 个规则网格，边长 "
        f"{summary['cell_size_m']} m，投影 `{summary['analysis_crs']}`",
        "",
        "## 已计算指标",
        "",
        "建筑数量、建筑占地面积、建筑覆盖率、建筑平均层数、估算建筑面积、估算容积率、"
        "设施点数量与密度、道路长度与路网密度、土地覆盖不透水面/水体占比、平均海拔和平均坡度"
        "均按指标合同计算。",
        "",
        "## 相对诊断",
        "",
        "诊断只使用重庆样例内部 P25/P75 分位数，表示同一批样例单元的相对差异，"
        "不表示规划合规、审批结论或政策阈值。",
        "",
        f"诊断计数：{json.dumps(summary['diagnostic_counts'], ensure_ascii=False)}。",
        "",
        "## 最高强度单元（前10）",
        "",
        "| 单元 | 建筑数 | 估算容积率 | 设施密度(个/km2) | 路网密度(km/km2) | 诊断 |",
        "|---|---:|---:|---:|---:|---|",
    ]
    for row in top.itertuples(index=False):
        lines.append(
            f"| {row.unit_id} | {int(row.building_count)} | {_fmt(row.estimated_far)} | "
            f"{_fmt(row.poi_density_km2)} | {_fmt(row.road_density_km_km2)} | "
            f"{', '.join(row.diagnostic_codes) or '无'} |"
        )
    lines.extend(
        [
            "",
            "## 不能由本次演练证明的内容",
            "",
            "1. 不能证明宁夏数据的完整性、现势性或规划目标达成率。",
            "2. 不能替代永久基本农田、生态保护红线、城镇开发边界等法定约束的合规审查。",
            "3. 不能生成有法律效力的规划实施评估结论；正式运行需要年度序列、目标值、"
            "指标字典、空间矛盾规则和建议政策库。",
            "4. 原始记录仍在数据湖/治理表中，本模型只保存输入引用、指标结果和血缘，"
            "不将全部记录复制进本体库。",
            "",
            "完整机器报告位于输出目录的 `monitoring_evaluation_report.json`。",
            "语义绑定和角色解析证据位于 `semantic_gate_report.json`；生产运行不得使用 "
            "`name_alias_rehearsal`。",
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _fmt(value: Any) -> str:
    if value is None or pd.isna(value):
        return "-"
    return f"{float(value):.3f}"
