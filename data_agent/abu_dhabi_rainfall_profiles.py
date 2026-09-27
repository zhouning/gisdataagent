"""Product contract for Abu Dhabi/UAE rainfall profiles.

This module keeps rainfall definition independent from the hydraulic solver.
It is intentionally conservative about climate-zone evidence: the repository
contains an auditable Abu Dhabi Zone B DDF extract, while no authoritative
Zone A IDF/DDF table has been registered yet.  Zone A is therefore exposed as
an explicit, selectable *pending* catalog entry and cannot silently generate
numbers.

The contract uses millimetres per interval for temporal values and optional
polygon GeoJSON for spatial zones.  Solver adapters can consume the validated
contract without knowing whether it came from a template, a user-edited curve,
or an imported observation series.
"""

from __future__ import annotations

import hashlib
import csv
import io
import json
import math
import os
import re
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

from .abu_dhabi_zone_b_design_storm import (
    SUPPORTED_RETURN_PERIODS,
    ZONE_B_DDF_DEPTH_MM,
    official_depth_mm,
    zone_b_180_minute_hyetograph,
)


RAINFALL_PROFILE_SCHEMA = "gwm.abu_dhabi_rainfall_profile.v1"
DEFAULT_PROFILE_ROOT = Path(
    os.environ.get(
        "ABU_DHABI_RAINFALL_PROFILE_ROOT",
        str(Path.home() / ".local/share/gisdataagent/private/abu_dhabi_stormwater/rainfall_profiles"),
    )
).expanduser()
SPATIAL_MODES = {"uniform", "zones", "raster"}
TEMPORAL_PATTERNS = {
    "uniform",
    "front_loaded",
    "back_loaded",
    "central_peak",
    "double_peak",
    "alternating_block",
    "official_zone_b_ddf_abm",
    "custom",
}

CLIMATE_ZONE_CATALOG: dict[str, dict[str, Any]] = {
    "zone_a": {
        "id": "zone_a",
        "label_zh": "Zone A（东部山区/内陆，待权威雨量表）",
        "label_en": "Zone A (eastern mountainous/inland; authority pending)",
        "status": "pending_authoritative_idf_ddf",
        "source_reference": None,
        "supported_return_periods": [],
        "supported_durations_minutes": [],
        "claim_boundary": "Climate-zone selection is reserved; no Zone A IDF/DDF values are registered.",
    },
    "zone_b": {
        "id": "zone_b",
        "label_zh": "Zone B（沿海/阿布扎比城市现有表）",
        "label_en": "Zone B (coastal/registered Abu Dhabi table)",
        "status": "registered_official_extract",
        "source_reference": "Abu Dhabi 2022 official Zone B DDF Table 3-6",
        "supported_return_periods": list(SUPPORTED_RETURN_PERIODS),
        "supported_durations_minutes": [5, 10, 15, 30, 60, 120, 180, 360, 720, 1440],
        "claim_boundary": "DDF depths are registered evidence; complete temporal hyetographs remain model assumptions unless separately supplied.",
    },
}

PATTERN_CATALOG: dict[str, dict[str, str]] = {
    "uniform": {"label_zh": "均匀雨型", "label_en": "Uniform"},
    "front_loaded": {"label_zh": "前峰雨型", "label_en": "Front-loaded"},
    "back_loaded": {"label_zh": "后峰雨型", "label_en": "Back-loaded"},
    "central_peak": {"label_zh": "中央峰雨型", "label_en": "Central peak"},
    "double_peak": {"label_zh": "双峰雨型", "label_en": "Double peak"},
    "alternating_block": {"label_zh": "交替块雨型", "label_en": "Alternating block"},
    "official_zone_b_ddf_abm": {"label_zh": "Zone B 官方 DDF 交替块", "label_en": "Official Zone B DDF alternating block"},
    "custom": {"label_zh": "人工/导入雨型", "label_en": "Custom/imported"},
}


def list_rainfall_profiles() -> dict[str, Any]:
    """Return a JSON-safe catalog for the UI and API."""

    profiles = []
    for return_period in SUPPORTED_RETURN_PERIODS:
        profiles.append(
            {
                "profile_id": f"uae-zone-b-rp{return_period}-180min-v1",
                "name": f"Zone B {return_period}-year / 180-minute",
                "climate_zone": "zone_b",
                "source_type": "official_ddf",
                "source_reference": "Abu Dhabi 2022 official Zone B DDF Table 3-6",
                "duration_minutes": 180,
                "interval_minutes": 5,
                "total_depth_mm": ZONE_B_DDF_DEPTH_MM[return_period][6],
                "return_period_years": return_period,
                "temporal_pattern": "official_zone_b_ddf_abm",
                "spatial_mode": "uniform",
                "status": "ready",
            }
        )
    return {
        "schema": RAINFALL_PROFILE_SCHEMA,
        "climate_zones": list(CLIMATE_ZONE_CATALOG.values()),
        "temporal_patterns": [
            {"id": key, **value} for key, value in PATTERN_CATALOG.items()
        ],
        "profiles": profiles,
        "spatial_modes": [
            {"id": "uniform", "label_zh": "全域均匀", "label_en": "Uniform"},
            {"id": "zones", "label_zh": "地图分区", "label_en": "Polygon zones"},
            {"id": "raster", "label_zh": "栅格雨量场（待接入）", "label_en": "Raster field (pending)"},
        ],
    }


def _profile_registry_root(root: Path | None = None) -> Path:
    return (root or DEFAULT_PROFILE_ROOT).expanduser().resolve()


def rainfall_profile_root_for_current_user(*, root: Path | None = None) -> Path:
    """Return an isolated registry directory for the authenticated subject.

    Direct library callers can continue to pass an explicit ``root`` to the
    save/load/list functions.  HTTP routes use this helper so one tenant/user
    cannot enumerate another user's saved rainfall plans.
    """

    try:
        from .user_context import current_tenant_id, current_user_id

        tenant = str(current_tenant_id.get() or "default")
        subject = str(current_user_id.get() or "anonymous")
    except Exception:
        tenant, subject = "default", "anonymous"
    token = re.sub(r"[^A-Za-z0-9._:-]+", "_", f"{tenant}__{subject}").strip("._") or "anonymous"
    return _profile_registry_root(root) / "users" / token


def _profile_digest(profile: dict[str, Any]) -> str:
    canonical = json.dumps(profile, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _profile_id(profile: dict[str, Any]) -> str:
    supplied = str(profile.get("profile_id") or "").strip()
    if supplied:
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}", supplied):
            raise ValueError("rainfall_profile_id_invalid")
        return supplied
    return f"rainfall-{_profile_digest(profile)[:16]}"


def _profile_csv(profile: dict[str, Any]) -> str:
    # The exported CSV deliberately uses elapsed minutes rather than a fake
    # wall-clock timestamp.  A rainfall profile has no event start time until
    # it is bound to a solver run, so labelling an integer as ``timestamp``
    # would make the file look more authoritative than it is.
    rows = ["elapsed_minutes,depth_mm_per_interval"]
    for index, depth in enumerate(profile["values_mm_per_interval"]):
        rows.append(f"{index * int(profile['interval_minutes'])},{float(depth):.10f}")
    return "\n".join(rows) + "\n"


def rainfall_profile_csv(profile: dict[str, Any]) -> str:
    """Export a validated profile as the documented interchange CSV."""

    return _profile_csv(build_rainfall_profile(profile))


def import_rainfall_profile_csv(
    csv_text: str,
    *,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Import a deterministic elapsed-time rainfall CSV.

    The importer accepts either ``depth_mm_per_interval`` *or*
    ``intensity_mm_per_hour`` as the value column, never both.  Time may be
    expressed as ``elapsed_minutes`` or ISO-8601 ``timestamp``.  A regular
    five-minute-or-longer interval is required because the current SWMM and
    ANUGA adapters use a fixed temporal grid.
    """

    if not isinstance(csv_text, str) or not csv_text.strip():
        raise ValueError("rainfall_csv_required")
    try:
        reader = csv.DictReader(io.StringIO(csv_text))
    except csv.Error as error:
        raise ValueError("rainfall_csv_invalid") from error
    if not reader.fieldnames:
        raise ValueError("rainfall_csv_header_required")

    aliases = {
        str(name).strip().lower(): str(name)
        for name in reader.fieldnames
        if name is not None and str(name).strip()
    }

    def pick(*names: str) -> str | None:
        for name in names:
            if name in aliases:
                return aliases[name]
        return None

    elapsed_column = pick("elapsed_minutes", "elapsed_min", "minutes")
    timestamp_column = pick("timestamp", "time", "datetime")
    if elapsed_column and timestamp_column:
        raise ValueError("rainfall_csv_time_columns_mutually_exclusive")
    time_column = elapsed_column or timestamp_column
    if not time_column:
        raise ValueError("rainfall_csv_time_column_required")

    depth_column = pick("depth_mm_per_interval", "depth_mm", "rainfall_mm")
    intensity_column = pick("intensity_mm_per_hour", "intensity_mm_h", "rainfall_intensity_mm_per_hour")
    if depth_column and intensity_column:
        raise ValueError("rainfall_csv_value_columns_mutually_exclusive")
    value_column = depth_column or intensity_column
    if not value_column:
        raise ValueError("rainfall_csv_value_column_required")

    rows: list[tuple[float, float]] = []
    first_stamp: datetime | None = None
    for index, raw in enumerate(reader, start=2):
        if not isinstance(raw, dict) or not any(str(value or "").strip() for value in raw.values()):
            continue
        raw_time = str(raw.get(time_column, "")).strip()
        raw_value = str(raw.get(value_column, "")).strip()
        if not raw_time or not raw_value:
            raise ValueError(f"rainfall_csv_row_{index}_missing_value")
        try:
            if elapsed_column:
                elapsed = float(raw_time)
            else:
                normalized = raw_time.replace("Z", "+00:00")
                stamp = datetime.fromisoformat(normalized)
                if stamp.tzinfo is not None:
                    stamp = stamp.astimezone(timezone.utc).replace(tzinfo=None)
                if first_stamp is None:
                    first_stamp = stamp
                assert first_stamp is not None
                elapsed = (stamp - first_stamp).total_seconds() / 60.0
            value = float(raw_value)
        except (TypeError, ValueError) as error:
            raise ValueError(f"rainfall_csv_row_{index}_number_or_timestamp_invalid") from error
        if not math.isfinite(elapsed) or not math.isfinite(value) or elapsed < 0:
            raise ValueError(f"rainfall_csv_row_{index}_out_of_range")
        if value < 0:
            raise ValueError(f"rainfall_csv_row_{index}_rainfall_negative")
        rows.append((elapsed, value))

    if not rows:
        raise ValueError("rainfall_csv_rows_required")
    elapsed_values = [item[0] for item in rows]
    if any(elapsed_values[index] <= elapsed_values[index - 1] for index in range(1, len(elapsed_values))):
        if len(set(elapsed_values)) != len(elapsed_values):
            raise ValueError("rainfall_csv_duplicate_time")
        raise ValueError("rainfall_csv_time_not_monotonic")
    if len(set(elapsed_values)) != len(elapsed_values):
        raise ValueError("rainfall_csv_duplicate_time")
    if len(rows) == 1:
        interval_minutes = int((metadata or {}).get("interval_minutes", (metadata or {}).get("intervalMinutes", 5)))
    else:
        deltas = [elapsed_values[index + 1] - elapsed_values[index] for index in range(len(rows) - 1)]
        interval_minutes = int(round(deltas[0]))
        if interval_minutes <= 0 or any(abs(delta - interval_minutes) > 1e-6 for delta in deltas):
            raise ValueError("rainfall_csv_interval_not_regular")
    if interval_minutes < 5 or interval_minutes % 5:
        raise ValueError("rainfall_csv_interval_minutes_must_be_positive_multiple_of_5")

    values = [value if depth_column else value * interval_minutes / 60.0 for _elapsed, value in rows]
    payload = dict(metadata or {})
    payload.update(
        {
            "temporal_pattern": "custom",
            "source_type": payload.get("source_type", "csv_import"),
            "source_reference": payload.get("source_reference", "user_uploaded_csv"),
            "interval_minutes": interval_minutes,
            "duration_minutes": interval_minutes * len(values),
            "values_mm_per_interval": values,
        }
    )
    return build_rainfall_profile(payload)


def disaggregate_hourly_rainfall_naturally(
    hourly_depths_mm: Iterable[float],
    *,
    interval_minutes: int = 5,
    phase_seed: int = 0,
    maximum_intensity_factor: float = 1.6,
) -> list[float]:
    """Create a deterministic, mass-conserving sub-hourly proxy curve.

    The method is intended only when the source evidence is hourly.  It uses
    neighbouring hours to shape rising and falling limbs, adds a bounded
    deterministic pulse modulation, and then normalises every hour back to
    its authoritative hourly depth.  It therefore looks less like twelve
    identical blocks while preserving every hourly total exactly.  The
    result remains synthetic disaggregation, not observed five-minute rain.
    """

    if interval_minutes < 5 or 60 % interval_minutes:
        raise ValueError("rainfall_disaggregation_interval_must_divide_60")
    maximum_factor = _finite_number(
        maximum_intensity_factor,
        "rainfall_disaggregation_maximum_intensity_factor",
        minimum=1.0,
    )
    hourly = [
        _finite_number(value, "hourly_rainfall_depth", minimum=0.0)
        for value in hourly_depths_mm
    ]
    if not hourly:
        raise ValueError("hourly_rainfall_values_required")
    slots = 60 // interval_minutes
    result: list[float] = []
    for hour_index, depth in enumerate(hourly):
        if depth == 0.0:
            result.extend([0.0] * slots)
            continue
        previous = hourly[hour_index - 1] if hour_index else 0.0
        following = hourly[hour_index + 1] if hour_index + 1 < len(hourly) else 0.0
        if following > depth * 1.1:
            peak_position = 0.72
        elif previous > depth * 1.1:
            peak_position = 0.28
        elif depth >= previous and depth >= following:
            peak_position = 0.38 + 0.18 * (((hour_index * 37 + phase_seed * 17) % 101) / 100.0)
        else:
            peak_position = 0.5
        neighbour_ratio = min(1.0, (previous + following) / max(2.0 * depth, 1e-12))
        pulse_width = 0.17 + 0.10 * neighbour_ratio
        phase = 2.0 * math.pi * (((hour_index * 29 + phase_seed * 11) % 113) / 113.0)
        weights: list[float] = []
        for slot_index in range(slots):
            fraction = (slot_index + 0.5) / slots
            if fraction <= 0.5:
                trend = previous + (depth - previous) * (fraction + 0.5)
            else:
                trend = depth + (following - depth) * (fraction - 0.5)
            trend_ratio = max(0.04, trend / depth)
            pulse = 0.68 + 0.62 * math.exp(-((fraction - peak_position) / pulse_width) ** 2)
            onset_taper = 1.0 if previous > 0.0 else min(1.0, 0.04 + 2.1 * fraction)
            ending_taper = 1.0 if following > 0.0 else min(1.0, 0.04 + 2.1 * (1.0 - fraction))
            modulation = (
                1.0
                + 0.11 * math.sin(2.0 * math.pi * 2.0 * fraction + phase)
                + 0.05 * math.sin(2.0 * math.pi * 5.0 * fraction + phase * 0.7)
            )
            weights.append(
                max(1e-12, trend_ratio * pulse * onset_taper * ending_taper * modulation)
            )
        weight_sum = sum(weights)
        values = [depth * weight / weight_sum for weight in weights]
        # Hourly-only evidence cannot justify an arbitrarily sharp synthetic
        # five-minute spike.  Bound the peak relative to the hourly mean and
        # redistribute any excess into the remaining slots without changing
        # the authoritative hourly accumulation.
        cap = depth / slots * maximum_factor
        for _iteration in range(slots):
            excess = sum(max(0.0, value - cap) for value in values)
            if excess <= 1e-15:
                break
            values = [min(value, cap) for value in values]
            available = [max(0.0, cap - value) for value in values]
            available_sum = sum(available)
            if available_sum <= 0.0:
                break
            values = [
                value + excess * room / available_sum
                for value, room in zip(values, available, strict=True)
            ]
        # Put the final floating-point residual in the last slot so each
        # hourly block is exactly mass-conserving under ordinary summation.
        values[-1] += depth - sum(values)
        result.extend(values)
    return result


def save_rainfall_profile(profile: dict[str, Any], *, root: Path | None = None) -> dict[str, Any]:
    """Persist an immutable, content-addressed rainfall profile snapshot."""

    checked = build_rainfall_profile(profile)
    profile_id = _profile_id(checked)
    checked["profile_id"] = profile_id
    checked["profile_hash_sha256"] = _profile_digest(checked)
    checked["saved_at_utc"] = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    registry_root = _profile_registry_root(root)
    profile_dir = registry_root / profile_id
    existing_path = profile_dir / "profile.json"
    if existing_path.is_file():
        try:
            existing_raw = json.loads(existing_path.read_text(encoding="utf-8"))
            existing_checked = build_rainfall_profile(existing_raw)
            existing_checked["profile_id"] = profile_id
            existing_hash = _profile_digest(existing_checked)
        except (OSError, ValueError) as error:
            raise ValueError("rainfall_profile_existing_snapshot_invalid") from error
        if existing_hash != checked["profile_hash_sha256"]:
            raise ValueError("rainfall_profile_id_conflict")
        checked["saved_at_utc"] = existing_raw.get("saved_at_utc") or checked["saved_at_utc"]
        checked["profile_hash_sha256"] = existing_hash
        return _saved_profile_summary(checked)
    _write_profile_snapshot(checked, profile_dir)
    return _saved_profile_summary(checked)


def _write_profile_snapshot(checked: dict[str, Any], profile_dir: Path) -> None:
    """Write the JSON and CSV snapshot with per-file atomic replacement.

    Rainfall plans are intentionally stored as auditable file snapshots rather
    than mutable database rows.  PUT uses this same writer so an update cannot
    leave a half-written JSON or CSV file behind if a process is interrupted.
    """

    profile_dir.mkdir(parents=True, exist_ok=True)
    json_path = profile_dir / "profile.json"
    csv_path = profile_dir / "rainfall.csv"
    json_tmp = profile_dir / ".profile.json.tmp"
    csv_tmp = profile_dir / ".rainfall.csv.tmp"
    try:
        json_tmp.write_text(
            json.dumps(checked, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        csv_tmp.write_text(_profile_csv(checked), encoding="utf-8")
        os.replace(json_tmp, json_path)
        os.replace(csv_tmp, csv_path)
    finally:
        for temporary in (json_tmp, csv_tmp):
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass


def update_rainfall_profile(
    profile_id: str,
    profile: dict[str, Any],
    *,
    root: Path | None = None,
) -> dict[str, Any]:
    """Replace one saved profile in an explicit, auditable PUT operation.

    POST remains content-addressed and creates a new snapshot when the
    content changes.  PUT is the explicit mutable CRUD operation: it keeps the
    selected profile id, recalculates the content hash and refreshes the saved
    timestamp.  The existing snapshot must exist, preventing accidental
    creation through an update route.
    """

    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}", str(profile_id or "")):
        raise ValueError("rainfall_profile_id_invalid")
    registry_root = _profile_registry_root(root)
    profile_dir = registry_root / str(profile_id)
    existing = load_rainfall_profile(str(profile_id), root=registry_root)
    if not isinstance(profile, dict):
        raise ValueError("rainfall_profile_payload_invalid")
    expected_hash = str(
        profile.get("expected_profile_hash_sha256")
        or profile.get("expectedProfileHashSha256")
        or ""
    ).strip()
    if expected_hash and expected_hash != str(existing.get("profile_hash_sha256") or ""):
        raise ValueError("rainfall_profile_conflict")
    candidate = dict(profile)
    candidate.pop("expected_profile_hash_sha256", None)
    candidate.pop("expectedProfileHashSha256", None)
    candidate["profile_id"] = str(profile_id)
    checked = build_rainfall_profile(candidate)
    checked["profile_id"] = str(profile_id)
    new_hash = _profile_digest(checked)
    checked["profile_hash_sha256"] = new_hash
    checked["saved_at_utc"] = (
        existing.get("saved_at_utc")
        if existing.get("profile_hash_sha256") == new_hash
        else datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    )
    _write_profile_snapshot(checked, profile_dir)
    return _saved_profile_summary(checked)


def delete_rainfall_profile(profile_id: str, *, root: Path | None = None) -> dict[str, Any]:
    """Delete one saved profile and return a deletion receipt."""

    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}", str(profile_id or "")):
        raise ValueError("rainfall_profile_id_invalid")
    registry_root = _profile_registry_root(root)
    profile_dir = registry_root / str(profile_id)
    existing = load_rainfall_profile(str(profile_id), root=registry_root)
    shutil.rmtree(profile_dir)
    return {
        "profile_id": str(profile_id),
        "profile_hash_sha256": existing.get("profile_hash_sha256"),
        "deleted": True,
    }


def _saved_profile_summary(checked: dict[str, Any]) -> dict[str, Any]:
    return {
        "profile_id": checked["profile_id"],
        "profile_hash_sha256": checked["profile_hash_sha256"],
        "schema": checked["schema"],
        "name": checked["name"],
        "climate_zone": checked["climate_zone"],
        "duration_minutes": checked["duration_minutes"],
        "interval_minutes": checked["interval_minutes"],
        "total_depth_mm": checked["total_depth_mm"],
        "source_type": checked["source_type"],
        "source_reference": checked.get("source_reference"),
        "temporal_pattern": checked.get("temporal_pattern"),
        "spatial_mode": checked.get("spatial_mode"),
        "spatial_zone_count": len(checked.get("zones") or []),
        "evidence_class": (checked.get("provenance") or {}).get("evidence_class"),
        "saved_at_utc": checked.get("saved_at_utc"),
        "status": "saved",
    }


def load_rainfall_profile(profile_id: str, *, root: Path | None = None) -> dict[str, Any]:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}", str(profile_id or "")):
        raise ValueError("rainfall_profile_id_invalid")
    path = _profile_registry_root(root) / str(profile_id) / "profile.json"
    if not path.is_file():
        raise KeyError("rainfall_profile_not_found")
    try:
        profile = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise ValueError("rainfall_profile_persisted_json_invalid") from error
    checked = build_rainfall_profile(profile)
    checked["profile_id"] = str(profile_id)
    calculated_hash = _profile_digest(checked)
    persisted_hash = str(profile.get("profile_hash_sha256") or "")
    if persisted_hash and persisted_hash != calculated_hash:
        raise ValueError("rainfall_profile_persisted_integrity_mismatch")
    checked["profile_hash_sha256"] = persisted_hash or calculated_hash
    checked["saved_at_utc"] = profile.get("saved_at_utc")
    return checked


def list_saved_rainfall_profiles(*, root: Path | None = None) -> list[dict[str, Any]]:
    registry_root = _profile_registry_root(root)
    if not registry_root.is_dir():
        return []
    result: list[dict[str, Any]] = []
    for child in sorted(registry_root.iterdir(), key=lambda path: path.name):
        if not child.is_dir() or not (child / "profile.json").is_file():
            continue
        try:
            profile = load_rainfall_profile(child.name, root=registry_root)
        except (KeyError, ValueError):
            continue
        result.append(_saved_profile_summary(profile))
    return result


def _finite_number(value: Any, name: str, *, minimum: float | None = None) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
        raise ValueError(f"{name}_invalid")
    result = float(value)
    if minimum is not None and result < minimum:
        raise ValueError(f"{name}_out_of_range")
    return result


def _intervals_from_profile(profile: dict[str, Any]) -> list[float]:
    values = profile.get("values_mm_per_interval", profile.get("values"))
    if not isinstance(values, list) or not values:
        raise ValueError("rainfall_profile_values_required")
    result = [_finite_number(value, "rainfall_value", minimum=0.0) for value in values]
    return result


def _polygon_area_hint(geometry: Any) -> bool:
    if not isinstance(geometry, dict) or geometry.get("type") not in {"Polygon", "MultiPolygon"}:
        return False
    coordinates = geometry.get("coordinates")
    return isinstance(coordinates, list) and bool(coordinates)


def validate_spatial_rainfall_zones(
    zones: Any,
    *,
    spatial_mode: str = "zones",
    allow_overlaps: bool = False,
) -> list[dict[str, Any]]:
    """Validate map-drawn rainfall zones without pretending to rasterize them."""

    if spatial_mode not in SPATIAL_MODES:
        raise ValueError("spatial_mode_invalid")
    if spatial_mode == "uniform":
        if zones not in (None, []):
            raise ValueError("uniform_spatial_mode_cannot_have_zones")
        return []
    if spatial_mode == "raster":
        raise ValueError("raster_spatial_rainfall_not_available")
    if not isinstance(zones, list) or not zones:
        raise ValueError("spatial_rainfall_zones_required")
    result: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for index, raw in enumerate(zones):
        if not isinstance(raw, dict):
            raise ValueError(f"spatial_zone_{index}_invalid")
        if raw.get("type") == "Feature":
            feature_properties = raw.get("properties") if isinstance(raw.get("properties"), dict) else {}
            raw = {**feature_properties, **raw, "geometry": raw.get("geometry")}
        zone_id = str(raw.get("zone_id", raw.get("id", f"zone_{index + 1}"))).strip()
        if not zone_id or zone_id in seen_ids:
            raise ValueError("spatial_zone_id_duplicate_or_empty")
        seen_ids.add(zone_id)
        geometry = raw.get("geometry", raw.get("geojson"))
        if not _polygon_area_hint(geometry):
            raise ValueError(f"spatial_zone_{zone_id}_geometry_invalid")
        factor = _finite_number(raw.get("rainfall_factor", 1.0), "rainfall_factor", minimum=0.0)
        if factor > 20.0:
            raise ValueError("rainfall_factor_out_of_range")
        temporal_pattern_id = str(raw.get("temporal_pattern_id", "")).strip() or None
        if temporal_pattern_id and len(temporal_pattern_id) > 128:
            raise ValueError("temporal_pattern_id_invalid")
        if temporal_pattern_id and temporal_pattern_id not in TEMPORAL_PATTERNS and temporal_pattern_id not in {"inherit", "base"}:
            raise ValueError("temporal_pattern_id_not_supported")
        custom_values = raw.get("values_mm_per_interval", raw.get("valuesMmPerInterval"))
        if custom_values is not None:
            if not isinstance(custom_values, list) or not custom_values:
                raise ValueError("spatial_zone_custom_values_invalid")
            custom_values = [_finite_number(value, "spatial_zone_custom_value", minimum=0.0) for value in custom_values]
        result.append(
            {
                "zone_id": zone_id,
                "geometry": geometry,
                "crs": str(raw.get("crs", "EPSG:4326")),
                "rainfall_factor": factor,
                "temporal_pattern_id": temporal_pattern_id,
                "values_mm_per_interval": custom_values,
                "priority": int(raw.get("priority", index)),
            }
        )
    if not allow_overlaps and len(result) > 1:
        # Geometry intersection requires a GIS engine; force an explicit
        # policy instead of silently applying an arbitrary ordering.
        priorities = [row["priority"] for row in result]
        if len(set(priorities)) != len(priorities):
            raise ValueError("spatial_zone_overlap_policy_required")
    return result


def spatial_rainfall_preview_geojson(
    zones: Any,
    *,
    default_crs: str = "EPSG:4326",
) -> dict[str, Any]:
    """Return rainfall-zone polygons in browser-safe WGS84 GeoJSON.

    Saved historical profiles use the hydraulic model CRS (EPSG:32640), while
    polygons drawn in Leaflet already use EPSG:4326. Keeping this conversion
    on the server avoids duplicating CRS logic in the browser and makes the
    preview explicitly read-only: no saved profile geometry is rewritten.
    """

    if isinstance(zones, dict) and zones.get("type") == "FeatureCollection":
        zones = zones.get("features")
    if not isinstance(zones, list) or not zones:
        raise ValueError("spatial_rainfall_zones_required")
    if len(zones) > 200:
        raise ValueError("spatial_rainfall_zone_count_out_of_range")

    try:
        from pyproj import CRS, Transformer
    except ImportError as error:  # pragma: no cover - deployment dependency
        raise ValueError("spatial_preview_projection_unavailable") from error

    target_crs = CRS.from_epsg(4326)
    transformer_cache: dict[str, Any] = {}

    def transform_coordinates(value: Any, transformer: Any) -> Any:
        if (
            isinstance(value, (list, tuple))
            and len(value) >= 2
            and isinstance(value[0], (int, float))
            and not isinstance(value[0], bool)
            and isinstance(value[1], (int, float))
            and not isinstance(value[1], bool)
        ):
            x = float(value[0])
            y = float(value[1])
            if not math.isfinite(x) or not math.isfinite(y):
                raise ValueError("spatial_preview_coordinate_invalid")
            lon, lat = transformer.transform(x, y) if transformer else (x, y)
            if not math.isfinite(lon) or not math.isfinite(lat):
                raise ValueError("spatial_preview_coordinate_invalid")
            return [float(lon), float(lat), *list(value[2:])]
        if isinstance(value, (list, tuple)):
            return [transform_coordinates(item, transformer) for item in value]
        raise ValueError("spatial_preview_coordinate_invalid")

    features: list[dict[str, Any]] = []
    for index, raw_zone in enumerate(zones):
        if not isinstance(raw_zone, dict):
            raise ValueError(f"spatial_zone_{index}_invalid")
        is_feature = raw_zone.get("type") == "Feature"
        properties = dict(raw_zone.get("properties") or {}) if is_feature else {
            key: value
            for key, value in raw_zone.items()
            if key not in {"geometry", "geojson", "type"}
        }
        geometry = raw_zone.get("geometry", raw_zone.get("geojson"))
        if not _polygon_area_hint(geometry):
            zone_id = str(properties.get("zone_id", raw_zone.get("zone_id", index + 1)))
            raise ValueError(f"spatial_zone_{zone_id}_geometry_invalid")

        source_name = str(
            raw_zone.get("crs")
            or properties.get("crs")
            or default_crs
            or "EPSG:4326"
        ).strip()
        try:
            source_crs = CRS.from_user_input(source_name)
        except Exception as error:
            raise ValueError("spatial_preview_crs_invalid") from error
        source_key = source_crs.to_string()
        if source_key not in transformer_cache:
            transformer_cache[source_key] = (
                None
                if source_crs.equals(target_crs)
                else Transformer.from_crs(source_crs, target_crs, always_xy=True)
            )
        transformed_geometry = {
            "type": geometry["type"],
            "coordinates": transform_coordinates(
                geometry.get("coordinates"),
                transformer_cache[source_key],
            ),
        }

        # Do not echo hundreds of temporal values into a Leaflet feature. The
        # chart remains the temporal preview; map properties stay lightweight.
        properties.pop("values_mm_per_interval", None)
        properties.pop("valuesMmPerInterval", None)
        for key in (
            "zone_id",
            "rainfall_factor",
            "temporal_pattern_id",
            "priority",
            "total_depth_mm",
            "peak_elapsed_minutes",
            "peak_time",
        ):
            if key not in properties and key in raw_zone:
                properties[key] = raw_zone[key]
        zone_id = str(properties.get("zone_id") or raw_zone.get("id") or f"zone_{index + 1}")
        properties.update(
            {
                "zone_id": zone_id,
                "source_crs": source_key,
                "preview_crs": "EPSG:4326",
                "preview_index": index,
            }
        )
        features.append(
            {
                "type": "Feature",
                "id": zone_id,
                "geometry": transformed_geometry,
                "properties": properties,
            }
        )

    return {
        "type": "FeatureCollection",
        "name": "rainfall_spatial_preview",
        "features": features,
    }


def spatial_zone_values_mm_per_interval(
    base_values_mm_per_interval: Iterable[float],
    zone: dict[str, Any],
    *,
    default_peak_position_percent: float = 40.0,
) -> list[float]:
    """Materialize one zone's 5-minute depths from a shared rainfall profile.

    A zone can inherit the base temporal curve, apply only a rainfall factor,
    or select one of the registered template shapes.  The zone total is the
    base total multiplied by ``rainfall_factor``.  This keeps the spatial
    contract deterministic for SWMM, ANUGA and later commercial adapters.
    """

    base = [_finite_number(value, "rainfall_value", minimum=0.0) for value in base_values_mm_per_interval]
    if not base:
        raise ValueError("rainfall_profile_values_required")
    factor = _finite_number(zone.get("rainfall_factor", 1.0), "rainfall_factor", minimum=0.0)
    pattern = str(zone.get("temporal_pattern_id") or "inherit").strip().lower()
    if pattern in {"", "inherit", "base"}:
        return [value * factor for value in base]
    if pattern == "custom":
        custom_values = zone.get("values_mm_per_interval")
        if not isinstance(custom_values, list) or not custom_values:
            raise ValueError("spatial_zone_custom_values_required")
        if len(custom_values) != len(base):
            raise ValueError("spatial_zone_custom_values_duration_mismatch")
        custom = [_finite_number(value, "spatial_zone_custom_value", minimum=0.0) for value in custom_values]
        custom_total = sum(custom)
        if custom_total <= 0:
            return [0.0 for _value in custom]
        return [value * factor for value in custom]
    if pattern == "official_zone_b_ddf_abm":
        # A zone-specific custom/DDF curve must be supplied as a separate
        # profile reference; until then retain the selected base curve and
        # make the factor explicit rather than fabricating a second curve.
        return [value * factor for value in base]
    peak = float(zone.get("peak_position_percent", default_peak_position_percent))
    return _build_template_values(sum(base) * factor, len(base), pattern, peak)


def _build_template_values(total_depth_mm: float, count: int, pattern: str, peak_position_percent: float) -> list[float]:
    if count <= 0:
        raise ValueError("rainfall_interval_count_invalid")
    peak = min(1.0, max(0.0, peak_position_percent / 100.0))
    weights: list[float] = []
    for index in range(count):
        x = (index + 0.5) / count
        if pattern == "uniform":
            weight = 1.0
        elif pattern == "front_loaded":
            weight = max(0.05, 2.0 - 1.5 * x)
        elif pattern == "back_loaded":
            weight = max(0.05, 0.5 + 1.5 * x)
        elif pattern == "double_peak":
            weight = max(0.05, 0.35 + 1.5 * (math.exp(-((x - 0.25) / 0.12) ** 2) + math.exp(-((x - 0.75) / 0.12) ** 2)))
        elif pattern == "alternating_block":
            # Alternating-block ordering is applied after sorting block
            # depths from largest to smallest around the requested peak.
            # The weights here provide a deterministic nested-DDF-like shape
            # for generic templates; the official Zone B path uses the
            # registered DDF extractor above.
            weight = max(0.05, 1.0 + (1.0 - abs(x - peak) * 2.0))
        elif pattern in {"central_peak", "custom"}:
            weight = max(0.05, 2.0 - abs(x - peak) * 5.0)
        else:
            raise ValueError("rainfall_template_pattern_not_supported")
        weights.append(weight)
    total_weight = sum(weights)
    return [total_depth_mm * weight / total_weight for weight in weights]


def build_custom_rainfall_series(
    *,
    start: datetime,
    values_mm_per_interval: Iterable[float],
    interval_minutes: int = 5,
    tail_minutes: int = 0,
) -> tuple[list[tuple[datetime, float]], dict[str, Any]]:
    """Convert user values in mm/interval to SWMM intensity in mm/h."""

    if interval_minutes <= 0 or interval_minutes % 5:
        raise ValueError("rainfall_interval_minutes_must_be_positive_multiple_of_5")
    if tail_minutes < 0 or tail_minutes % 5:
        raise ValueError("rainfall_tail_minutes_invalid")
    values = [_finite_number(value, "rainfall_value", minimum=0.0) for value in values_mm_per_interval]
    if not values:
        raise ValueError("rainfall_profile_values_required")
    series = [
        (start + timedelta(minutes=index * interval_minutes), value * 60.0 / interval_minutes)
        for index, value in enumerate(values)
    ]
    end = start + timedelta(minutes=len(values) * interval_minutes)
    series.append((end, 0.0))
    if tail_minutes:
        series.append((end + timedelta(minutes=tail_minutes), 0.0))
    return series, {
        "source": "rainfall_profile",
        "source_label": "雨型产品化方案",
        "source_authority": "validated_profile_contract",
        "native_interval_minutes": interval_minutes,
        "generated_intervals": len(values),
        "generated_total_depth_mm": float(sum(values)),
        "peak_intensity_mm_per_hour": float(max(values) * 60.0 / interval_minutes),
        "temporal_distribution_method": "validated_values_mm_per_interval",
    }


def build_rainfall_profile(payload: dict[str, Any]) -> dict[str, Any]:
    """Build and validate a complete profile suitable for solver adapters."""

    if not isinstance(payload, dict):
        raise ValueError("rainfall_profile_payload_invalid")
    climate_zone = str(payload.get("climate_zone", payload.get("climateZone", "zone_b"))).lower()
    if climate_zone not in CLIMATE_ZONE_CATALOG:
        raise ValueError("climate_zone_invalid")
    pattern = str(payload.get("temporal_pattern", payload.get("temporalPattern", "uniform"))).lower()
    if pattern not in TEMPORAL_PATTERNS:
        raise ValueError("temporal_pattern_invalid")
    spatial_mode = str(payload.get("spatial_mode", payload.get("spatialMode", "uniform"))).lower()
    duration = int(_finite_number(payload.get("duration_minutes", payload.get("durationMinutes", 180)), "duration_minutes", minimum=5))
    interval = int(_finite_number(payload.get("interval_minutes", payload.get("intervalMinutes", 5)), "interval_minutes", minimum=5))
    if duration % interval or interval % 5:
        raise ValueError("duration_must_align_interval")
    return_period = payload.get("return_period_years", payload.get("returnPeriodYears"))
    if return_period is not None:
        return_period = int(_finite_number(return_period, "return_period_years", minimum=1))
    if climate_zone == "zone_a" and (pattern == "official_zone_b_ddf_abm" or return_period is not None):
        raise ValueError("zone_a_authoritative_idf_ddf_not_available")
    if climate_zone == "zone_b" and pattern == "official_zone_b_ddf_abm":
        if return_period not in SUPPORTED_RETURN_PERIODS:
            raise ValueError("return_period_years_not_supported")
        if duration != 180 or interval != 5:
            raise ValueError("official_zone_b_ddf_requires_180_minute_duration_and_5_minute_step")
        peak_position = float(payload.get("peak_position_percent", payload.get("peakPosition", 40)))
        values = [depth for _, depth in zone_b_180_minute_hyetograph(return_period, start=datetime(2000, 1, 1), peak_position_percent=peak_position)[0][:-1]]
        values = [value / 12.0 for value in values]
        source_type = "official_ddf"
        source_reference = "Abu Dhabi 2022 official Zone B DDF Table 3-6"
    elif "values_mm_per_interval" in payload or "values" in payload:
        values = _intervals_from_profile(payload)
        if len(values) * interval != duration:
            raise ValueError("rainfall_profile_duration_mismatch")
        source_type = str(payload.get("source_type", "custom"))
        source_reference = payload.get("source_reference")
    else:
        total_depth = _finite_number(payload.get("total_depth_mm", payload.get("totalDepthMm")), "total_depth_mm", minimum=0.0)
        values = _build_template_values(total_depth, duration // interval, pattern, float(payload.get("peak_position_percent", payload.get("peakPosition", 40))))
        source_type = "template"
        source_reference = "product_template"
    zones = validate_spatial_rainfall_zones(payload.get("zones", payload.get("spatialRainfallZones")), spatial_mode=spatial_mode)
    total_depth = float(sum(values))
    profile = {
        "schema": RAINFALL_PROFILE_SCHEMA,
        "profile_id": str(payload.get("profile_id", payload.get("profileId", ""))).strip() or None,
        "name": str(payload.get("name", "未命名雨型方案")),
        "climate_zone": climate_zone,
        "source_type": source_type,
        "source_reference": source_reference,
        "duration_minutes": duration,
        "interval_minutes": interval,
        "total_depth_mm": total_depth,
        "return_period_years": return_period,
        "peak_position_percent": float(payload.get("peak_position_percent", payload.get("peakPosition", 40))),
        "temporal_pattern": pattern,
        "values_mm_per_interval": values,
        "spatial_mode": spatial_mode,
        "zones": zones,
        "default_zone": payload.get("default_zone", payload.get("defaultZone", {"rainfall_factor": 1.0})),
        "model_mapping": payload.get(
            "model_mapping",
            {
                "swmm": {"units": "mm_per_hour", "timeseries_interval_minutes": interval, "spatial_mapping": "subcatchment_raingage_pending"},
                "anuga": {"units": "m_per_second", "timeseries_interval_minutes": interval, "spatial_mapping": "cell_center_polygon"},
                "commercial": {"status": "adapter_contract_pending_vendor_confirmation"},
            },
        ),
        "provenance": payload.get("provenance", {}),
        "validation": {
            "non_negative": all(value >= 0 for value in values),
            "interval_aligned": len(values) * interval == duration,
            "total_depth_mm": total_depth,
            "status": "ready" if climate_zone != "zone_a" or source_type == "custom" else "pending_authoritative_zone_data",
        },
    }
    return profile


def rainfall_profile_series(profile: dict[str, Any], *, start: datetime, tail_minutes: int = 0) -> tuple[list[tuple[datetime, float]], dict[str, Any]]:
    """Materialize a validated profile for a solver."""

    checked = build_rainfall_profile(profile)
    return build_custom_rainfall_series(
        start=start,
        values_mm_per_interval=checked["values_mm_per_interval"],
        interval_minutes=int(checked["interval_minutes"]),
        tail_minutes=tail_minutes,
    )


def build_solver_forcing_contract(
    profile: dict[str, Any],
    *,
    target_solver: str,
    start_time: str = "2024-04-16T00:00:00Z",
) -> dict[str, Any]:
    """Produce a vendor-neutral forcing package for SWMM, ANUGA or a commercial adapter.

    Commercial model field names differ by vendor, so this function does not
    claim to be a vendor-native project file. It provides the stable exchange
    contract that a vendor adapter can translate without changing the selected
    rainfall profile or spatial zones.
    """

    checked = build_rainfall_profile(profile)
    solver = str(target_solver).lower()
    if solver not in {"swmm", "anuga", "commercial"}:
        raise ValueError("target_solver_invalid")
    interval = int(checked["interval_minutes"])
    values = [float(value) for value in checked["values_mm_per_interval"]]
    if solver == "anuga":
        temporal_values = [value / (interval * 60.0) * 0.001 for value in values]
        temporal_unit = "m_per_second"
    else:
        temporal_values = [value * 60.0 / interval for value in values]
        temporal_unit = "mm_per_hour"
    spatial_zone_forcings = []
    for zone in checked["zones"]:
        zone_depths = spatial_zone_values_mm_per_interval(
            values,
            zone,
            default_peak_position_percent=float(checked["peak_position_percent"]),
        )
        if solver == "anuga":
            zone_temporal_values = [value / (interval * 60.0) * 0.001 for value in zone_depths]
        else:
            zone_temporal_values = [value * 60.0 / interval for value in zone_depths]
        spatial_zone_forcings.append({
            "zone_id": zone["zone_id"],
            "rainfall_factor": zone["rainfall_factor"],
            "temporal_pattern_id": zone.get("temporal_pattern_id") or "inherit",
            "total_depth_mm": float(sum(zone_depths)),
            "temporal_values": zone_temporal_values,
        })
    return {
        "schema": "gwm.abu_dhabi_rainfall_forcing_exchange.v1",
        "target_solver": solver,
        "profile_id": checked.get("profile_id"),
        "climate_zone": checked["climate_zone"],
        "start_time": start_time,
        "duration_minutes": checked["duration_minutes"],
        "interval_minutes": interval,
        "temporal_values": temporal_values,
        "temporal_unit": temporal_unit,
        "total_depth_mm": checked["total_depth_mm"],
        "spatial_mode": checked["spatial_mode"],
        "spatial_zones": checked["zones"],
        "spatial_zone_forcings": spatial_zone_forcings,
        "default_zone": checked["default_zone"],
        "source_type": checked["source_type"],
        "source_reference": checked["source_reference"],
        "adapter_status": "ready_for_solver_translation" if solver in {"swmm", "anuga"} else "vendor_adapter_required",
        "claim_boundary": "Forcing exchange contract only; vendor-native commercial model project settings, licensing and acceptance remain to be confirmed.",
    }


def build_solver_forcing_package(
    profile: dict[str, Any],
    *,
    target_solver: str,
    start_time: str = "2024-04-16T00:00:00Z",
) -> bytes:
    """Build a deterministic, vendor-neutral rainfall forcing ZIP package."""

    checked = build_rainfall_profile(profile)
    contract = build_solver_forcing_contract(
        checked,
        target_solver=target_solver,
        start_time=start_time,
    )
    try:
        start = datetime.fromisoformat(str(start_time).replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError("start_time_invalid") from error
    interval = int(checked["interval_minutes"])
    rows = ["elapsed_minutes,timestamp,forcing_value,forcing_unit,depth_mm_per_interval"]
    for index, (forcing_value, depth) in enumerate(
        zip(contract["temporal_values"], checked["values_mm_per_interval"])
    ):
        elapsed = index * interval
        stamp = start + timedelta(minutes=elapsed)
        rows.append(
            f"{elapsed},{stamp.isoformat().replace('+00:00', 'Z')},{float(forcing_value):.12g},"
            f"{contract['temporal_unit']},{float(depth):.12g}"
        )
    forcing_csv = "\n".join(rows) + "\n"
    zone_rows = ["zone_id,elapsed_minutes,timestamp,forcing_value,forcing_unit,depth_mm_per_interval,temporal_pattern_id,rainfall_factor"]
    for zone in contract["spatial_zone_forcings"]:
        if contract["temporal_unit"] == "m_per_second":
            zone_depths = [float(value) * interval * 60.0 / 0.001 for value in zone["temporal_values"]]
        else:
            zone_depths = [float(value) * interval / 60.0 for value in zone["temporal_values"]]
        for index, (forcing_value, depth) in enumerate(zip(zone["temporal_values"], zone_depths)):
            elapsed = index * interval
            stamp = start + timedelta(minutes=elapsed)
            zone_rows.append(
                f"{zone['zone_id']},{elapsed},{stamp.isoformat().replace('+00:00', 'Z')},"
                f"{float(forcing_value):.12g},{contract['temporal_unit']},{float(depth):.12g},"
                f"{zone['temporal_pattern_id']},{float(zone['rainfall_factor']):.12g}"
            )
    zone_forcing_csv = "\n".join(zone_rows) + "\n"
    spatial_geojson = {
        "type": "FeatureCollection",
        "name": "rainfall_spatial_zones",
        "features": [
            {
                "type": "Feature",
                "id": zone["zone_id"],
                "geometry": zone["geometry"],
                "properties": {
                    key: value for key, value in zone.items() if key != "geometry"
                },
            }
            for zone in checked["zones"]
        ],
    }
    readme = (
        "Abu Dhabi rainfall forcing exchange package\n"
        f"Schema: {contract['schema']}\n"
        f"Target solver: {contract['target_solver']}\n"
        f"Adapter status: {contract['adapter_status']}\n\n"
        "This package is an auditable interchange artifact. It is not a vendor-native "
        "Bentley OpenFlows or Autodesk InfoWorks ICM project file. Vendor version, "
        "licensing, import mapping and batch execution must be confirmed separately.\n"
    )

    buffer = io.BytesIO()
    with ZipFile(buffer, "w") as archive:
        def write_text(name: str, value: str) -> None:
            entry = ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            entry.compress_type = ZIP_DEFLATED
            entry.external_attr = 0o644 << 16
            archive.writestr(entry, value.encode("utf-8"))

        write_text("manifest.json", json.dumps(contract, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
        write_text("profile.json", json.dumps(checked, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
        write_text("rainfall_timeseries.csv", forcing_csv)
        write_text("rainfall_zone_timeseries.csv", zone_forcing_csv)
        write_text("spatial_zones.geojson", json.dumps(spatial_geojson, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
        write_text("README.txt", readme)
    return buffer.getvalue()


__all__ = [
    "CLIMATE_ZONE_CATALOG",
    "PATTERN_CATALOG",
    "RAINFALL_PROFILE_SCHEMA",
    "build_custom_rainfall_series",
    "build_rainfall_profile",
    "build_solver_forcing_contract",
    "build_solver_forcing_package",
    "import_rainfall_profile_csv",
    "list_saved_rainfall_profiles",
    "list_rainfall_profiles",
    "load_rainfall_profile",
    "rainfall_profile_series",
    "rainfall_profile_root_for_current_user",
    "rainfall_profile_csv",
    "save_rainfall_profile",
    "spatial_rainfall_preview_geojson",
    "spatial_zone_values_mm_per_interval",
    "validate_spatial_rainfall_zones",
]
