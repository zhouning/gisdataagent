"""Extensible, fail-closed source adapters for the GIS preprocessing image.

The adapters in this module deliberately stop at a private, normalized source
contract.  They do not silently turn a customer's geometry into an admitted
hydrodynamic input: units, datum, controls and calibration evidence must be
provided explicitly before a downstream model can consume the artifacts.
"""

from __future__ import annotations

import hashlib
import json
import tempfile
import zipfile
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any

import pandas as pd

SCHEMA = "gwm.gis_preprocess.adapter_manifest.v1"
TARGET_CRS = "EPSG:32640"
MAX_ARCHIVE_MEMBERS = 100_000
MAX_UNCOMPRESSED_BYTES = 100 * 1024**3


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _artifact(path: Path, root: Path, *, record_count: int | None = None) -> dict[str, Any]:
    result: dict[str, Any] = {
        "path": str(path.relative_to(root)),
        "size_bytes": path.stat().st_size,
        "sha256": _sha256(path),
    }
    if record_count is not None:
        result["record_count"] = int(record_count)
    return result


def _safe_extract_gdb_archive(archive: Path, destination: Path) -> Path:
    destination.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive) as source:
        members = source.infolist()
        if len(members) > MAX_ARCHIVE_MEMBERS:
            raise ValueError("gdb_archive_member_limit_exceeded")
        if sum(member.file_size for member in members) > MAX_UNCOMPRESSED_BYTES:
            raise ValueError("gdb_archive_uncompressed_size_limit_exceeded")
        for member in members:
            name = member.filename.replace("\\", "/")
            relative = PurePosixPath(name)
            if relative.is_absolute() or ".." in relative.parts:
                raise ValueError("gdb_archive_unsafe_member_path")
            mode = member.external_attr >> 16
            if mode and (mode & 0o170000) == 0o120000:
                raise ValueError("gdb_archive_symlink_not_allowed")
        source.extractall(destination)
    candidates = sorted(destination.rglob("*.gdb"), key=lambda item: str(item))
    if len(candidates) != 1 or not candidates[0].is_dir():
        raise ValueError("gdb_archive_must_contain_exactly_one_filegdb_directory")
    return candidates[0]


def _field_map(columns: list[str], aliases: dict[str, tuple[str, ...]]) -> dict[str, str | None]:
    by_lower = {str(column).casefold(): str(column) for column in columns}
    return {
        target: next(
            (by_lower[name.casefold()] for name in candidates if name.casefold() in by_lower),
            None,
        )
        for target, candidates in aliases.items()
    }


def _resolve_source(
    source: Path,
    *,
    layer: str | None,
    temporary_root: Path,
) -> tuple[Path, str | None, Path | None]:
    """Return a readable vector source, selected layer and original archive."""

    resolved = source.expanduser().resolve()
    if not resolved.exists():
        raise ValueError("source_path_not_found")
    archive: Path | None = None
    if resolved.is_file() and resolved.suffix.casefold() == ".zip":
        archive = resolved
        resolved = _safe_extract_gdb_archive(resolved, temporary_root)
    if resolved.is_dir() and resolved.suffix.casefold() == ".gdb":
        import pyogrio

        layers = [str(row[0]) for row in pyogrio.list_layers(resolved)]
        if layer is None:
            if len(layers) != 1:
                raise ValueError("vector_layer_required_for_multilayer_source")
            layer = layers[0]
        if layer not in layers:
            raise ValueError(f"vector_layer_not_found:{layer}")
    return resolved, layer, archive


def _write_manifest(root: Path, filename: str, payload: dict[str, Any]) -> dict[str, Any]:
    path = root / filename
    _json(path, payload)
    payload = dict(payload)
    payload["manifest"] = _artifact(path, root)
    return payload


def _source_record(source: Path, archive: Path | None) -> dict[str, Any]:
    logical = archive if archive is not None else source
    if logical.is_dir():
        digest = hashlib.sha256()
        size_bytes = 0
        for path in sorted(item for item in logical.rglob("*") if item.is_file()):
            relative = path.relative_to(logical).as_posix().encode("utf-8")
            digest.update(len(relative).to_bytes(8, "big"))
            digest.update(relative)
            file_digest = _sha256(path)
            digest.update(bytes.fromhex(file_digest))
            size_bytes += path.stat().st_size
        source_hash = digest.hexdigest()
    else:
        size_bytes = logical.stat().st_size
        source_hash = _sha256(logical)
    return {
        "logical_name": logical.name,
        "format": "FileGDB" if source.suffix.casefold() == ".gdb" else source.suffix.lstrip(".").upper(),
        "size_bytes": size_bytes,
        "sha256": source_hash,
    }


def _base_manifest(
    *,
    adapter: str,
    source: Path,
    archive: Path | None,
    output: dict[str, Any],
    field_mapping: dict[str, Any],
    quality: dict[str, Any],
    admitted: bool,
    claim_boundary: list[str],
) -> dict[str, Any]:
    return {
        "schema": SCHEMA,
        "adapter": adapter,
        "status": "completed_admitted_source_contract" if admitted else "completed_diagnostic_only",
        "created_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "source": _source_record(source, archive),
        "output": output,
        "field_mapping": field_mapping,
        "quality": quality,
        "admission": {
            "source_contract_admitted": admitted,
            "model_input_admitted": False,
            "calibration_admitted": False,
        },
        "claim_boundary": claim_boundary,
        "privacy": {
            "customer_derived_rows_are_private": True,
            "source_absolute_paths_persisted": False,
        },
    }


def compile_pump_stations(
    source: Path,
    *,
    output_root: Path,
    layer: str | None = "PS_PUMP",
    target_crs: str = TARGET_CRS,
    flow_unit: str | None = None,
    capacity_unit: str | None = None,
) -> dict[str, Any]:
    """Normalize pump point assets from a GDB/vector source into private GeoParquet."""

    import geopandas as gpd
    import pyogrio

    root = output_root.expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="pump-adapter-") as temporary:
        readable, selected_layer, archive = _resolve_source(
            source, layer=layer, temporary_root=Path(temporary)
        )
        info = pyogrio.read_info(readable, layer=selected_layer)
        if info.get("crs") is None:
            raise ValueError("pump_source_crs_required")
        available_fields = [str(field) for field in info.get("fields", [])]
        mapping = _field_map(
            available_fields,
            {
                "station_id": ("PUMP_STATION_ID", "STATION_ID", "UNITID", "PointCode"),
                "pump_id": ("UNITID", "PROJECTID", "PointCode"),
                "flow_rate": ("FLOW_RATE", "FLOWRATE", "DESIGN_FLOW"),
                "head": ("HEAD", "TOTAL_HEAD"),
                "total_capacity": ("TOTAL_CAPACITY", "CAPACITY"),
                "power_kw": ("POWER_KW", "RATED_POWER"),
                "pump_count": ("NO_OF_PUMPS", "PUMP_COUNT"),
                "status": ("STATUS", "CONDITION"),
                "control_type": ("FLOW_CONTROL_TYPE", "CONTROL_TYPE"),
            },
        )
        if mapping["station_id"] is None and mapping["pump_id"] is None:
            raise ValueError("pump_station_identifier_field_required")
        selected_columns = sorted({field for field in mapping.values() if field is not None})
        frame = pyogrio.read_dataframe(
            readable,
            layer=selected_layer,
            columns=selected_columns,
            use_arrow=True,
        )
        if frame.geometry is None or frame.geometry.isna().all():
            raise ValueError("pump_geometry_required")
        unsupported_geometry = ~frame.geometry.geom_type.isin(["Point", "MultiPoint"])
        if unsupported_geometry.any():
            raise ValueError(
                f"pump_point_geometry_required:{int(unsupported_geometry.sum())}"
            )
        frame = frame.to_crs(target_crs)
        output_columns = {}
        for target, field in mapping.items():
            if field is not None:
                output_columns[target] = frame[field]
            else:
                output_columns[target] = pd.Series([pd.NA] * len(frame), index=frame.index)
        normalized = gpd.GeoDataFrame(output_columns, geometry=frame.geometry, crs=target_crs)
        for field in ("flow_rate", "head", "total_capacity", "power_kw", "pump_count"):
            normalized[field] = pd.to_numeric(normalized[field], errors="coerce")
        normalized["station_id"] = normalized["station_id"].astype("string").str.strip()
        normalized["pump_id"] = normalized["pump_id"].astype("string").str.strip()
        normalized["source_layer"] = selected_layer
        normalized["source_crs"] = str(info.get("crs"))
        output_path = root / "pump_stations.private.geoparquet"
        normalized.to_parquet(output_path, index=False)
        flow_present = int(normalized["flow_rate"].notna().sum())
        capacity_present = int(normalized["total_capacity"].notna().sum())
        admitted = bool(flow_unit and capacity_unit and flow_present > 0 and capacity_present > 0)
        manifest = _base_manifest(
            adapter="pump_stations",
            source=readable,
            archive=archive,
            output=_artifact(output_path, root, record_count=len(normalized)),
            field_mapping={**mapping, "target_crs": target_crs},
            quality={
                "record_count": len(normalized),
                "geometry_null_count": int(normalized.geometry.isna().sum()),
                "flow_rate_present_count": flow_present,
                "capacity_present_count": capacity_present,
                "flow_unit_declared": flow_unit,
                "capacity_unit_declared": capacity_unit,
                "source_crs": str(info.get("crs")),
            },
            admitted=admitted,
            claim_boundary=[
                "pump_geometry_and_attributes_normalized",
                "pump_control_curves_and_runtime_state_not_included",
                "model_consumption_requires_network_mapping_and_engineering_review",
            ],
        )
    return _write_manifest(root, "pump_stations_compile_manifest.json", manifest)


def compile_tide_boundaries(
    source: Path,
    *,
    output_root: Path,
    timestamp_field: str,
    value_field: str,
    boundary_field: str | None = None,
    value_kind: str = "stage",
    value_unit: str | None = None,
    timezone: str = "UTC",
    vertical_datum: str | None = None,
) -> dict[str, Any]:
    """Normalize timestamped tide/stage/flow observations from CSV or Parquet."""

    root = output_root.expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    resolved = source.expanduser().resolve()
    if not resolved.is_file():
        raise ValueError("tide_source_file_required")
    if resolved.suffix.casefold() == ".csv":
        frame = pd.read_csv(resolved)
    elif resolved.suffix.casefold() in {".parquet", ".geoparquet"}:
        frame = pd.read_parquet(resolved)
    else:
        raise ValueError("tide_source_must_be_csv_or_parquet")
    for field in (timestamp_field, value_field):
        if field not in frame.columns:
            raise ValueError(f"tide_required_field_missing:{field}")
    normalized = pd.DataFrame()
    normalized["boundary_id"] = (
        frame[boundary_field].astype("string") if boundary_field else "default"
    )
    parsed_timestamps = pd.to_datetime(frame[timestamp_field], errors="coerce")
    if getattr(parsed_timestamps.dt, "tz", None) is None:
        normalized["timestamp_utc"] = (
            parsed_timestamps.dt.tz_localize(timezone).dt.tz_convert("UTC")
        )
    else:
        normalized["timestamp_utc"] = parsed_timestamps.dt.tz_convert("UTC")
    normalized["value"] = pd.to_numeric(frame[value_field], errors="coerce")
    invalid = normalized["timestamp_utc"].isna() | normalized["value"].isna()
    if invalid.any():
        raise ValueError(f"tide_invalid_timestamp_or_value_count:{int(invalid.sum())}")
    normalized["value_kind"] = value_kind
    normalized["value_unit"] = value_unit or pd.NA
    normalized["timezone"] = timezone
    normalized["vertical_datum"] = vertical_datum or pd.NA
    normalized = normalized.sort_values(["boundary_id", "timestamp_utc"]).reset_index(drop=True)
    duplicate_count = int(normalized.duplicated(["boundary_id", "timestamp_utc"]).sum())
    monotonic = all(
        group["timestamp_utc"].is_monotonic_increasing
        for _, group in normalized.groupby("boundary_id", sort=False)
    )
    output_path = root / "tide_boundaries.private.parquet"
    normalized.to_parquet(output_path, index=False)
    admitted = bool(value_unit and vertical_datum and duplicate_count == 0 and monotonic)
    manifest = _base_manifest(
        adapter="tide_boundaries",
        source=resolved,
        archive=None,
        output=_artifact(output_path, root, record_count=len(normalized)),
        field_mapping={
            "timestamp": timestamp_field,
            "value": value_field,
            "boundary_id": boundary_field,
            "value_kind": value_kind,
            "timezone": timezone,
            "vertical_datum": vertical_datum,
        },
        quality={
            "record_count": len(normalized),
            "boundary_count": int(normalized["boundary_id"].nunique()),
            "duplicate_timestamp_count": duplicate_count,
            "monotonic_by_boundary": monotonic,
            "value_unit_declared": value_unit,
            "vertical_datum_declared": vertical_datum,
        },
        admitted=admitted,
        claim_boundary=[
            "timestamped_boundary_series_normalized_to_utc",
            "datum_conversion_and_coastal_boundary_mapping_not_performed",
            "extreme_event_completeness_and_quality_not_established",
        ],
    )
    return _write_manifest(root, "tide_boundaries_compile_manifest.json", manifest)


def compile_land_use(
    source: Path,
    *,
    output_root: Path,
    layer: str | None = None,
    class_field: str | None = None,
    code_field: str | None = None,
    imperviousness_field: str | None = None,
    target_crs: str = TARGET_CRS,
) -> dict[str, Any]:
    """Normalize polygon land-use features and compute private area metrics."""

    import geopandas as gpd
    import pyogrio

    root = output_root.expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="land-use-adapter-") as temporary:
        readable, selected_layer, archive = _resolve_source(
            source, layer=layer, temporary_root=Path(temporary)
        )
        info = pyogrio.read_info(readable, layer=selected_layer)
        if info.get("crs") is None:
            raise ValueError("land_use_source_crs_required")
        available_fields = [str(field) for field in info.get("fields", [])]
        aliases = _field_map(
            available_fields,
            {
                "land_use_class": ("land_use_class", "LAND_USE", "DLMC", "TYPE", "CLASS"),
                "land_use_code": ("land_use_code", "DLBM", "CODE", "TYPE_CODE"),
                "imperviousness": ("imperviousness", "IMPERVIOUS", "IMPERVIOUSNESS"),
            },
        )
        selected_class = class_field or aliases["land_use_class"]
        selected_code = code_field or aliases["land_use_code"]
        selected_imperviousness = imperviousness_field or aliases["imperviousness"]
        if selected_class is None and selected_code is None:
            raise ValueError("land_use_class_or_code_field_required")
        selected_columns = sorted(
            {
                field
                for field in (selected_class, selected_code, selected_imperviousness)
                if field is not None
            }
        )
        frame = pyogrio.read_dataframe(
            readable,
            layer=selected_layer,
            columns=selected_columns,
            use_arrow=True,
        )
        if frame.geometry is None or frame.geometry.isna().all():
            raise ValueError("land_use_polygon_geometry_required")
        unsupported_geometry = ~frame.geometry.geom_type.isin(["Polygon", "MultiPolygon"])
        if unsupported_geometry.any():
            raise ValueError(
                f"land_use_polygon_geometry_required:{int(unsupported_geometry.sum())}"
            )
        frame = frame.to_crs(target_crs)
        normalized = gpd.GeoDataFrame(
            {
                "land_use_class": frame[selected_class]
                if selected_class
                else pd.Series([pd.NA] * len(frame), index=frame.index),
                "land_use_code": frame[selected_code]
                if selected_code
                else pd.Series([pd.NA] * len(frame), index=frame.index),
                "imperviousness": frame[selected_imperviousness]
                if selected_imperviousness
                else pd.Series([pd.NA] * len(frame), index=frame.index),
            },
            geometry=frame.geometry,
            crs=target_crs,
        )
        normalized["land_use_class"] = normalized["land_use_class"].astype("string").str.strip()
        normalized["land_use_code"] = normalized["land_use_code"].astype("string").str.strip()
        normalized["imperviousness"] = pd.to_numeric(normalized["imperviousness"], errors="coerce")
        normalized["geometry_valid"] = normalized.geometry.is_valid
        normalized["area_m2"] = normalized.geometry.area
        output_path = root / "land_use.private.geoparquet"
        normalized.to_parquet(output_path, index=False)
        invalid_geometry_count = int((~normalized["geometry_valid"]).sum())
        imperviousness_invalid_count = int(
            (
                normalized["imperviousness"].notna()
                & ~normalized["imperviousness"].between(0.0, 1.0, inclusive="both")
            ).sum()
        )
        admitted = bool(invalid_geometry_count == 0 and imperviousness_invalid_count == 0)
        manifest = _base_manifest(
            adapter="land_use",
            source=readable,
            archive=archive,
            output=_artifact(output_path, root, record_count=len(normalized)),
            field_mapping={
                "land_use_class": selected_class,
                "land_use_code": selected_code,
                "imperviousness": selected_imperviousness,
                "target_crs": target_crs,
            },
            quality={
                "record_count": len(normalized),
                "invalid_geometry_count": invalid_geometry_count,
                "imperviousness_present_count": int(normalized["imperviousness"].notna().sum()),
                "imperviousness_invalid_count": imperviousness_invalid_count,
                "total_area_m2": float(normalized["area_m2"].sum()),
                "source_crs": str(info.get("crs")),
            },
            admitted=admitted,
            claim_boundary=[
                "land_use_geometry_and_class_fields_normalized",
                "catchment_overlay_and_hydraulic_parameter_crosswalk_not_performed",
                "imperviousness_is_admitted_only_when_explicitly_supplied_as_fraction",
            ],
        )
    return _write_manifest(root, "land_use_compile_manifest.json", manifest)


__all__ = ["compile_land_use", "compile_pump_stations", "compile_tide_boundaries"]
