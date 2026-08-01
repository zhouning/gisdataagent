"""Bind public USGS channel measurements to downstream dynamic-wave states."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import hashlib
import json
import math
from pathlib import Path
from typing import Any

from .dynamic_wave_flux import (
    STANDARD_GRAVITY_MPS2,
    DynamicWaveCellState,
    TrapezoidalChannelSection,
    dynamic_wave_characteristic_speeds_mps,
)
from .public_confluence_fixture import REPO_ROOT


PUBLIC_REACH_HYDRAULIC_MEASUREMENTS_SCHEMA = (
    "gwm.geospatial_kernel.public_reach_hydraulic_measurements.v1"
)
EXPECTED_ACQUISITION_SCHEMA = (
    "gwm.geotransport.stage23_usgs_channel_measurement_acquisition.v1"
)
DEFAULT_SOURCE_ROOT = REPO_ROOT / (
    "data/geotransport_v0_1/stage23_usgs_channel_measurements_03424860"
)
MONITORING_LOCATION_ID = "USGS-03424860"
REACH_ID = "18421703"
GAUGE_COORDINATE_WGS84 = (-85.90444444444445, 36.18611111111111)
GAUGE_DISTANCE_FROM_JUNCTION_M = 925.4563554985091
FOOT_TO_M = 0.3048
SQUARE_FOOT_TO_M2 = 0.09290304
CUBIC_FOOT_PER_SECOND_TO_M3S = 0.028316846592
FLOW_CLOSURE_TOLERANCE = 0.02


@dataclass(frozen=True)
class ObservedReachHydraulicState:
    measurement_id: str
    field_visit_id: str
    measurement_number: str
    time: str
    coordinate_wgs84: tuple[float, float]
    channel_name: str
    flow_m3s: float
    top_width_m: float
    flow_area_m2: float
    reported_mean_velocity_mps: float
    gage_height_m: float
    gage_height_approval_status: str
    measurement_type: str
    channel_measurement_type: str
    channel_location_direction: str
    channel_location_distance_m: float | None
    channel_material: str
    channel_stability: str
    channel_evenness: str
    source_last_modified: str

    def __post_init__(self) -> None:
        scalars = (
            self.flow_m3s,
            self.top_width_m,
            self.flow_area_m2,
            self.reported_mean_velocity_mps,
            self.gage_height_m,
        )
        if (
            not self.measurement_id
            or not self.field_visit_id
            or any(not math.isfinite(value) or value <= 0.0 for value in scalars)
            or (
                self.channel_location_distance_m is not None
                and (
                    not math.isfinite(self.channel_location_distance_m)
                    or self.channel_location_distance_m < 0.0
                )
            )
            or self.flow_closure_relative_error > FLOW_CLOSURE_TOLERANCE
        ):
            raise ValueError("observed_reach_hydraulic_state_invalid")

    @property
    def equivalent_section(self) -> TrapezoidalChannelSection:
        return TrapezoidalChannelSection(self.top_width_m, 0.0)

    @property
    def dynamic_wave_state(self) -> DynamicWaveCellState:
        return DynamicWaveCellState(self.flow_area_m2, self.flow_m3s)

    @property
    def equivalent_mean_depth_m(self) -> float:
        return self.flow_area_m2 / self.top_width_m

    @property
    def kernel_mean_velocity_mps(self) -> float:
        return self.dynamic_wave_state.mean_velocity_mps

    @property
    def flow_closure_relative_error(self) -> float:
        reconstructed = self.flow_area_m2 * self.reported_mean_velocity_mps
        return abs(self.flow_m3s - reconstructed) / max(
            self.flow_m3s, reconstructed
        )

    @property
    def froude_number(self) -> float:
        return self.kernel_mean_velocity_mps / math.sqrt(
            STANDARD_GRAVITY_MPS2 * self.equivalent_mean_depth_m
        )

    @property
    def characteristic_speeds_mps(self) -> tuple[float, float]:
        return dynamic_wave_characteristic_speeds_mps(
            self.dynamic_wave_state, self.equivalent_section
        )

    def as_dict(self) -> dict[str, object]:
        return {
            "measurement_id": self.measurement_id,
            "field_visit_id": self.field_visit_id,
            "measurement_number": self.measurement_number,
            "time": self.time,
            "coordinate_wgs84": list(self.coordinate_wgs84),
            "channel_name": self.channel_name,
            "observed_si": {
                "flow_m3s": self.flow_m3s,
                "top_width_m": self.top_width_m,
                "flow_area_m2": self.flow_area_m2,
                "reported_mean_velocity_mps": (
                    self.reported_mean_velocity_mps
                ),
                "gage_height_m": self.gage_height_m,
            },
            "dynamic_wave_binding": {
                "state": {
                    "area_m2": self.dynamic_wave_state.area_m2,
                    "discharge_m3s": self.dynamic_wave_state.discharge_m3s,
                    "mean_velocity_mps": self.kernel_mean_velocity_mps,
                },
                "equivalent_rectangular_section": {
                    "bottom_width_m": self.equivalent_section.bottom_width_m,
                    "side_slope_horizontal_per_vertical": 0.0,
                    "equivalent_mean_depth_m": self.equivalent_mean_depth_m,
                },
                "minimum_maximum_characteristic_speed_mps": list(
                    self.characteristic_speeds_mps
                ),
                "froude_number": self.froude_number,
                "subcritical_at_observed_state": self.froude_number < 1.0,
                "state_conditioned_equivalent_section": True,
                "fixed_permanent_geometry": False,
            },
            "flow_closure": {
                "identity": "Q_approximately_equals_A_times_mean_velocity",
                "relative_error": self.flow_closure_relative_error,
                "tolerance": FLOW_CLOSURE_TOLERANCE,
                "passes": self.flow_closure_relative_error
                <= FLOW_CLOSURE_TOLERANCE,
            },
            "field_context": {
                "gage_height_approval_status": (
                    self.gage_height_approval_status
                ),
                "gage_height_is_bed_referenced_depth": False,
                "measurement_type": self.measurement_type,
                "channel_measurement_type": self.channel_measurement_type,
                "channel_location_direction": self.channel_location_direction,
                "channel_location_distance_m": (
                    self.channel_location_distance_m
                ),
                "channel_material": self.channel_material,
                "channel_stability": self.channel_stability,
                "channel_evenness": self.channel_evenness,
                "source_last_modified": self.source_last_modified,
            },
        }


@dataclass(frozen=True)
class PublicReachHydraulicMeasurements:
    monitoring_location_id: str
    reach_id: str
    gauge_coordinate_wgs84: tuple[float, float]
    gauge_distance_from_junction_m: float
    measurements: tuple[ObservedReachHydraulicState, ...]
    source_artifacts: tuple[dict[str, object], ...]
    provenance_id: str

    def __post_init__(self) -> None:
        if (
            self.monitoring_location_id != MONITORING_LOCATION_ID
            or self.reach_id != REACH_ID
            or len(self.measurements) != 110
            or len({value.measurement_id for value in self.measurements}) != 110
            or tuple(sorted(value.time for value in self.measurements))
            != tuple(value.time for value in self.measurements)
        ):
            raise ValueError("public_reach_hydraulic_measurements_invalid")

    def require_fixed_reach_geometry(self) -> None:
        raise ValueError(
            "public_reach_measurements_state_conditioned_not_fixed_geometry"
        )

    def require_confluence_patch_bathymetry(self) -> None:
        raise ValueError(
            "public_reach_measurement_not_confluence_patch_bathymetry"
        )

    def as_dict(self) -> dict[str, object]:
        fields = {
            "flow_m3s": [value.flow_m3s for value in self.measurements],
            "top_width_m": [value.top_width_m for value in self.measurements],
            "flow_area_m2": [value.flow_area_m2 for value in self.measurements],
            "equivalent_mean_depth_m": [
                value.equivalent_mean_depth_m for value in self.measurements
            ],
            "kernel_mean_velocity_mps": [
                value.kernel_mean_velocity_mps for value in self.measurements
            ],
            "gage_height_m": [
                value.gage_height_m for value in self.measurements
            ],
            "froude_number": [
                value.froude_number for value in self.measurements
            ],
        }
        return {
            "schema": PUBLIC_REACH_HYDRAULIC_MEASUREMENTS_SCHEMA,
            "monitoring_location_id": self.monitoring_location_id,
            "reach_id": self.reach_id,
            "gauge_coordinate_wgs84": list(self.gauge_coordinate_wgs84),
            "gauge_distance_from_junction_m": (
                self.gauge_distance_from_junction_m
            ),
            "measurement_count": len(self.measurements),
            "time_range": [
                self.measurements[0].time,
                self.measurements[-1].time,
            ],
            "observed_ranges_and_quantiles": {
                name: _distribution(values) for name, values in fields.items()
            },
            "method_counts": _counts(
                value.measurement_type for value in self.measurements
            ),
            "channel_measurement_type_counts": _counts(
                value.channel_measurement_type for value in self.measurements
            ),
            "material_counts": _counts(
                value.channel_material for value in self.measurements
            ),
            "gage_height_approval_counts": _counts(
                value.gage_height_approval_status
                for value in self.measurements
            ),
            "maximum_flow_closure_relative_error": max(
                value.flow_closure_relative_error
                for value in self.measurements
            ),
            "subcritical_observation_count": sum(
                value.froude_number < 1.0 for value in self.measurements
            ),
            "measurements": [
                value.as_dict() for value in self.measurements
            ],
            "source_artifacts": list(self.source_artifacts),
            "provenance_id": self.provenance_id,
            "kernel_binding": {
                "dynamic_wave_cell_state_bound_per_measurement": True,
                "equivalent_rectangular_section_bound_per_measurement": True,
                "observed_subcritical_state_coverage": True,
                "fixed_reach_geometry_admitted": False,
                "confluence_patch_bathymetry_admitted": False,
            },
            "claim_boundary": {
                "public_downstream_reach_hydraulic_states_compiled": True,
                "measurement_location_is_junction_patch": False,
                "gage_height_treated_as_bed_referenced_depth": False,
                "equivalent_section_treated_as_permanent_geometry": False,
                "confluence_bathymetry_completed": False,
                "operator_admitted": False,
            },
        }


def compile_public_reach_hydraulic_measurements(
    source_root: Path = DEFAULT_SOURCE_ROOT,
    *,
    repo_root: Path = REPO_ROOT,
) -> PublicReachHydraulicMeasurements:
    repository = Path(repo_root).resolve()
    manifest = _read_json(Path(source_root) / "acquisition_manifest.json")
    _validate_manifest(manifest)
    verified = _verify_artifacts(manifest, repository)
    by_source = {
        str(value["source_id"]): value for value in manifest["artifacts"]
    }
    channels = _read_json(
        _resolve(by_source["usgs_channel_measurements_03424860"], repository)
    )
    fields = _read_json(
        _resolve(by_source["usgs_field_measurements_03424860"], repository)
    )
    field_by_visit: dict[str, list[dict[str, Any]]] = {}
    for feature in fields["features"]:
        value = feature["properties"]
        field_by_visit.setdefault(str(value["field_visit_id"]), []).append(
            value
        )
    measurements = tuple(
        sorted(
            (
                _compile_measurement(feature, field_by_visit)
                for feature in channels["features"]
            ),
            key=lambda value: (value.time, value.measurement_id),
        )
    )
    digest = hashlib.sha256(
        "|".join(
            sorted(str(value["sha256"]) for value in verified)
        ).encode("ascii")
    ).hexdigest()
    return PublicReachHydraulicMeasurements(
        MONITORING_LOCATION_ID,
        REACH_ID,
        GAUGE_COORDINATE_WGS84,
        GAUGE_DISTANCE_FROM_JUNCTION_M,
        measurements,
        tuple(verified),
        f"usgs-channel-measurements:{MONITORING_LOCATION_ID}:{digest}",
    )


def _compile_measurement(
    feature: dict[str, Any],
    field_by_visit: dict[str, list[dict[str, Any]]],
) -> ObservedReachHydraulicState:
    value = feature["properties"]
    expected_units = {
        "channel_flow_unit": "ft^3/s",
        "channel_width_unit": "ft",
        "channel_area_unit": "ft^2",
        "channel_velocity_unit": "ft/s",
    }
    if any(value.get(field) != unit for field, unit in expected_units.items()):
        raise ValueError("public_reach_hydraulic_measurement_units_invalid")
    visit_id = str(value["field_visit_id"])
    channel_time = _parse_datetime(str(value["time"]))
    stages = [
        item
        for item in field_by_visit.get(visit_id, [])
        if item.get("reading_type") == "MeanGageHeight"
        and item.get("parameter_code") == "00065"
        and item.get("unit_of_measure") == "ft"
        and item.get("value") not in (None, "")
    ]
    if not stages:
        raise ValueError("public_reach_gage_height_join_missing")
    stage = min(
        stages,
        key=lambda item: abs(
            (_parse_datetime(str(item["time"])) - channel_time).total_seconds()
        ),
    )
    geometry = feature.get("geometry", {})
    if geometry.get("type") != "Point":
        raise ValueError("public_reach_measurement_geometry_invalid")
    coordinate = tuple(float(item) for item in geometry["coordinates"])
    if len(coordinate) != 2 or math.hypot(
        coordinate[0] - GAUGE_COORDINATE_WGS84[0],
        coordinate[1] - GAUGE_COORDINATE_WGS84[1],
    ) > 1e-10:
        raise ValueError("public_reach_measurement_location_mismatch")
    distance = value.get("channel_location_distance")
    if distance not in (None, "") and value.get(
        "channel_location_distance_unit"
    ) != "ft":
        raise ValueError("public_reach_measurement_distance_unit_invalid")
    return ObservedReachHydraulicState(
        str(value["id"]),
        visit_id,
        str(value["measurement_number"]),
        str(value["time"]),
        (coordinate[0], coordinate[1]),
        str(value.get("channel_name") or ""),
        float(value["channel_flow"]) * CUBIC_FOOT_PER_SECOND_TO_M3S,
        float(value["channel_width"]) * FOOT_TO_M,
        float(value["channel_area"]) * SQUARE_FOOT_TO_M2,
        float(value["channel_velocity"]) * FOOT_TO_M,
        float(stage["value"]) * FOOT_TO_M,
        str(stage["approval_status"]),
        str(value.get("measurement_type") or "Unknown"),
        str(value.get("channel_measurement_type") or "Unknown"),
        str(value.get("channel_location_direction") or "Unknown"),
        None if distance in (None, "") else float(distance) * FOOT_TO_M,
        str(value.get("channel_material") or "Unknown"),
        str(value.get("channel_stability") or "Unknown"),
        str(value.get("channel_evenness") or "Unknown"),
        str(value["last_modified"]),
    )


def _validate_manifest(manifest: dict[str, Any]) -> None:
    claims = manifest.get("claim_boundary", {})
    boundary = manifest.get("request_boundary", {})
    if (
        manifest.get("schema") != EXPECTED_ACQUISITION_SCHEMA
        or manifest.get("mode") != "values"
        or manifest.get("artifact_count") != 3
        or manifest.get("total_downloaded_bytes", 1_500_001) > 1_500_000
        or boundary.get("workspace_or_private_data_sent") is not False
        or claims.get("measurement_location_is_junction_patch") is not False
        or claims.get("single_measurement_defines_permanent_cross_section")
        is not False
        or claims.get("gage_height_is_bed_referenced_depth") is not False
    ):
        raise ValueError("public_reach_hydraulic_manifest_invalid")


def _verify_artifacts(
    manifest: dict[str, Any], repo_root: Path
) -> tuple[dict[str, object], ...]:
    results = []
    for value in manifest["artifacts"]:
        path = _resolve(value, repo_root)
        body = path.read_bytes()
        digest = hashlib.sha256(body).hexdigest()
        if len(body) != int(value["size_bytes"]) or digest != value["sha256"]:
            raise ValueError("public_reach_hydraulic_artifact_identity_mismatch")
        results.append(
            {
                "source_id": value["source_id"],
                "path": value["path"],
                "size_bytes": len(body),
                "sha256": digest,
                "role": value["role"],
                "identity_matches": True,
            }
        )
    return tuple(results)


def _resolve(value: dict[str, Any], repo_root: Path) -> Path:
    path = (repo_root / str(value["path"])).resolve()
    if path != repo_root and repo_root not in path.parents:
        raise ValueError("public_reach_hydraulic_path_outside_repository")
    return path


def _parse_datetime(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _distribution(values: list[float]) -> dict[str, float]:
    ordered = sorted(values)
    return {
        "minimum": ordered[0],
        "p05": _quantile(ordered, 0.05),
        "median": _quantile(ordered, 0.5),
        "p95": _quantile(ordered, 0.95),
        "maximum": ordered[-1],
    }


def _quantile(ordered: list[float], probability: float) -> float:
    position = (len(ordered) - 1) * probability
    lower = int(math.floor(position))
    upper = int(math.ceil(position))
    if lower == upper:
        return ordered[lower]
    fraction = position - lower
    return ordered[lower] + fraction * (ordered[upper] - ordered[lower])


def _counts(values) -> dict[str, int]:
    result: dict[str, int] = {}
    for value in values:
        result[value] = result.get(value, 0) + 1
    return dict(sorted(result.items()))


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))
