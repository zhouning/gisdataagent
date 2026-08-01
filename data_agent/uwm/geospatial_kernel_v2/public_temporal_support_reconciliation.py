"""Stage 33 public path and temporal-support reconciliation evidence."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
from pathlib import Path
from typing import Any

from data_agent.uwm.geospatial_kernel_v2 import (
    geospatial_temporal_support as temporal,
)
from data_agent.uwm.geospatial_kernel_v2 import (
    public_lag_support_evidence as stage32,
)


REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_SOURCE_ROOT = REPO_ROOT / (
    "data/geotransport_v0_1/stage33_center_hill_temporal_support_path"
)
STAGE27_LEDGER_PATH = REPO_ROOT / (
    "data/geotransport_v0_1/stage27_center_hill_spatial_boundary_evidence/"
    "spatial_boundary_evidence_ledger.json"
)
STAGE28_LEDGER_PATH = REPO_ROOT / (
    "data/geotransport_v0_1/"
    "stage28_center_hill_operational_boundary_evidence/"
    "operational_boundary_evidence_ledger.json"
)
STAGE32_LEDGER_PATH = REPO_ROOT / (
    "data/geotransport_v0_1/stage32_center_hill_lag_support_events/"
    "lag_support_evidence_ledger.json"
)
STAGE32_GATES_PATH = REPO_ROOT / (
    "benchmarks/geotransport_v0_1/stage32_lag_support_gates.json"
)
HYDRODYNAMIC_REPORT_PATH = REPO_ROOT / (
    "benchmarks/geotransport_v0_1/hydrodynamic_scale_envelope_report.json"
)
ADVECTIVE_REPORT_PATH = REPO_ROOT / (
    "benchmarks/geotransport_v0_1/center_hill_travel_time_prior_report.json"
)
SCHEMA = "gwm.geotransport.public_temporal_support_reconciliation.v1"
ACQUISITION_SCHEMA = (
    "gwm.geotransport.stage33_temporal_support_path_acquisition.v1"
)
RELATION_ID = "center-hill-tailwater-to-stonewall"
PATH_ID = "center-hill-tailwater-to-stonewall-path"
SOURCE_COMID = 18421761
TARGET_COMID = 18421703
SOURCE_ZONE_RADIUS_M = 250.0
TARGET_SNAP_TOLERANCE_M = 100.0
PATH_LENGTH_EQUIVALENCE_TOLERANCE_M = 250.0


@dataclass(frozen=True)
class PublicTemporalPathBinding:
    relation_id: str
    path_id: str
    source_comid: int
    target_comid: int
    feature_ids: tuple[int, ...]
    full_geometry_length_m: float
    linear_referenced_length_m: float
    source_snap_distance_m: float
    target_snap_distance_m: float
    maximum_connection_gap_m: float
    physics_path_extra_upstream_length_m: float
    physics_path_suffix_matches: bool
    source_artifact: dict[str, object]

    def __post_init__(self) -> None:
        if (
            self.relation_id != RELATION_ID
            or self.path_id != PATH_ID
            or self.source_comid != SOURCE_COMID
            or self.target_comid != TARGET_COMID
            or not self.feature_ids
            or self.feature_ids[0] != SOURCE_COMID
            or self.feature_ids[-1] != TARGET_COMID
            or len(set(self.feature_ids)) != len(self.feature_ids)
            or not all(
                math.isfinite(value) and value >= 0.0
                for value in (
                    self.full_geometry_length_m,
                    self.linear_referenced_length_m,
                    self.source_snap_distance_m,
                    self.target_snap_distance_m,
                    self.maximum_connection_gap_m,
                    self.physics_path_extra_upstream_length_m,
                )
            )
        ):
            raise ValueError("public_temporal_path_binding_invalid")

    @property
    def spatial_path_admitted(self) -> bool:
        return (
            self.source_snap_distance_m <= SOURCE_ZONE_RADIUS_M
            and self.target_snap_distance_m <= TARGET_SNAP_TOLERANCE_M
            and self.maximum_connection_gap_m <= TARGET_SNAP_TOLERANCE_M
            and self.physics_path_suffix_matches
            and self.physics_path_extra_upstream_length_m
            <= PATH_LENGTH_EQUIVALENCE_TOLERANCE_M
        )

    def require_spatial_path(self) -> tuple[int, ...]:
        if not self.spatial_path_admitted:
            raise ValueError("public_temporal_spatial_path_unadmitted")
        return self.feature_ids

    def as_dict(self) -> dict[str, object]:
        return {
            "relation_id": self.relation_id,
            "path_id": self.path_id,
            "source_comid": self.source_comid,
            "target_comid": self.target_comid,
            "feature_ids": list(self.feature_ids),
            "feature_count": len(self.feature_ids),
            "full_geometry_length_m": self.full_geometry_length_m,
            "linear_referenced_length_m": (
                self.linear_referenced_length_m
            ),
            "source_snap_distance_m": self.source_snap_distance_m,
            "source_zone_radius_m": SOURCE_ZONE_RADIUS_M,
            "target_snap_distance_m": self.target_snap_distance_m,
            "target_snap_tolerance_m": TARGET_SNAP_TOLERANCE_M,
            "maximum_connection_gap_m": self.maximum_connection_gap_m,
            "physics_path_extra_upstream_length_m": (
                self.physics_path_extra_upstream_length_m
            ),
            "path_length_equivalence_tolerance_m": (
                PATH_LENGTH_EQUIVALENCE_TOLERANCE_M
            ),
            "physics_path_suffix_matches": (
                self.physics_path_suffix_matches
            ),
            "spatial_path_admitted": self.spatial_path_admitted,
            "source_artifact": self.source_artifact,
        }


@dataclass(frozen=True)
class PublicTemporalSupportReconciliationLedger:
    operator_artifact: dict[str, object]
    acquisition_plan_artifact: dict[str, object]
    acquisition_manifest_artifact: dict[str, object]
    path_binding: PublicTemporalPathBinding
    stage32_event_support_sets: tuple[tuple[int, ...], ...]
    stage32_detectable_relation_count: int
    reconciliation: temporal.GeospatialTemporalSupportReconciliation
    source_artifacts: tuple[dict[str, object], ...]
    provenance_id: str

    def __post_init__(self) -> None:
        if (
            len(self.stage32_event_support_sets) != 4
            or self.stage32_detectable_relation_count != 3
            or len(self.source_artifacts) != 9
            or self.reconciliation.path_id != self.path_binding.path_id
            or self.reconciliation.relation_id
            != self.path_binding.relation_id
        ):
            raise ValueError(
                "public_temporal_support_reconciliation_ledger_invalid"
            )

    def require_spatial_path(self) -> tuple[int, ...]:
        return self.path_binding.require_spatial_path()

    def require_physics_consistent_support(self) -> tuple[int, ...]:
        return self.reconciliation.require_physics_consistent_support()

    def promote_to_runtime_transition(self) -> None:
        self.reconciliation.promote_to_runtime_transition()

    def as_dict(self) -> dict[str, object]:
        compatibilities = self.reconciliation.compatibilities
        return {
            "schema": SCHEMA,
            "operator_artifact": self.operator_artifact,
            "acquisition_plan_artifact": self.acquisition_plan_artifact,
            "acquisition_manifest_artifact": (
                self.acquisition_manifest_artifact
            ),
            "path_binding": self.path_binding.as_dict(),
            "stage32_event_support_sets_hours": [
                list(value) for value in self.stage32_event_support_sets
            ],
            "stage32_detectable_relation_count": (
                self.stage32_detectable_relation_count
            ),
            "reconciliation": self.reconciliation.as_dict(),
            "source_artifacts": list(self.source_artifacts),
            "provenance_id": self.provenance_id,
            "diagnostic_summary": {
                "empirical_union_hours": list(
                    self.reconciliation.empirical.supported_hours
                ),
                "physics_support_ids": [
                    value.physics.support_id for value in compatibilities
                ],
                "physics_support_intervals_hours": [
                    [
                        value.physics.lower_hours,
                        value.physics.upper_hours,
                    ]
                    for value in compatibilities
                ],
                "numerical_overlap_by_support": [
                    value.numerical_overlap for value in compatibilities
                ],
                "minimum_separation_hours": [
                    value.minimum_separation_hours
                    for value in compatibilities
                ],
            },
            "claim_boundary": {
                "nldi_source_to_target_path_admitted": (
                    self.path_binding.spatial_path_admitted
                ),
                "stage32_empirical_union_is_common_support": False,
                "numerical_overlap_equals_physical_validation": False,
                "gravity_wave_time_admitted_as_response_lag": False,
                "manning_centroid_time_admitted_as_response_lag": False,
                "advective_residence_time_admitted_as_response_lag": False,
                "runtime_transition_admitted": False,
            },
            "decision": {
                "spatial_path_admitted": (
                    self.path_binding.spatial_path_admitted
                ),
                "physics_support_candidates_admitted": True,
                "any_numerical_temporal_overlap": any(
                    value.numerical_overlap for value in compatibilities
                ),
                "physics_consistency_admitted": (
                    self.reconciliation.physics_consistency_admitted
                ),
                "runtime_transition_admitted": False,
            },
        }


def compile_public_temporal_support_reconciliation(
    source_root: Path = DEFAULT_SOURCE_ROOT,
    *,
    repo_root: Path = REPO_ROOT,
) -> PublicTemporalSupportReconciliationLedger:
    root = Path(repo_root).resolve()
    source = Path(source_root).resolve()
    manifest_path = source / "acquisition_manifest.json"
    manifest = _read_json(manifest_path)
    plan_body = _read_verified(
        manifest["frozen_acquisition_plan"], root
    )
    plan = json.loads(plan_body)
    _validate_acquisition(manifest, plan, root)
    path_record = manifest["artifacts"][0]
    path_payload = json.loads(_read_verified(path_record, root))
    path_features = _source_target_features(path_payload)

    stage27 = _read_json(STAGE27_LEDGER_PATH)
    stage28 = _read_json(STAGE28_LEDGER_PATH)
    stage32_file = _read_json(STAGE32_LEDGER_PATH)
    stage32_compiled = stage32.compile_public_lag_support_evidence(
        repo_root=root
    )
    if stage32_compiled.as_dict() != stage32_file:
        raise ValueError("public_temporal_stage32_ledger_not_reproducible")
    stage32_gates = _read_json(STAGE32_GATES_PATH)
    hydrodynamic = _read_json(HYDRODYNAMIC_REPORT_PATH)
    advective = _read_json(ADVECTIVE_REPORT_PATH)

    source_value = stage28["location_binding"]["cwms_coordinate"]
    source_coordinate = (
        float(source_value["longitude"]),
        float(source_value["latitude"]),
    )
    target_candidate = next(
        value
        for value in stage27["candidates"]
        if value["monitoring_location_id"] == "USGS-03424860"
    )
    target_coordinate = tuple(
        float(value) for value in target_candidate["coordinate_wgs84"]
    )
    _validate_prior_evidence(
        plan,
        stage32_gates,
        hydrodynamic,
        advective,
        source_coordinate,
        target_coordinate,
    )
    path_binding = _compile_path_binding(
        path_features,
        source_coordinate=source_coordinate,
        target_coordinate=target_coordinate,
        hydrodynamic=hydrodynamic,
        advective=advective,
        source_artifact=dict(path_record),
    )

    support_sets = tuple(
        value.lag_support.supported_lags_hours
        for value in stage32_compiled.events
    )
    empirical_union = tuple(
        sorted({hour for values in support_sets for hour in values})
    )
    empirical = temporal.DiscreteTemporalSupport(
        RELATION_ID,
        "empirical_downstream_response_lag",
        empirical_union,
        stage32_compiled.provenance_id,
        True,
    )
    physics = _compile_physics_support(hydrodynamic, advective)
    compatibilities = tuple(
        temporal.compile_temporal_support_compatibility(
            empirical,
            value,
            same_spatial_path=path_binding.spatial_path_admitted,
        )
        for value in physics
    )
    reconciliation = temporal.GeospatialTemporalSupportReconciliation(
        RELATION_ID,
        PATH_ID,
        empirical,
        compatibilities,
        stage32_compiled.common_empirical_support_admitted,
    )
    sources = (
        _artifact(source / "acquisition_plan.json", root),
        _artifact(manifest_path, root),
        dict(path_record),
        _artifact(STAGE27_LEDGER_PATH, root),
        _artifact(STAGE28_LEDGER_PATH, root),
        _artifact(STAGE32_LEDGER_PATH, root),
        _artifact(STAGE32_GATES_PATH, root),
        _artifact(HYDRODYNAMIC_REPORT_PATH, root),
        _artifact(ADVECTIVE_REPORT_PATH, root),
    )
    digest = hashlib.sha256(
        "|".join(str(value["sha256"]) for value in sources).encode("ascii")
    ).hexdigest()
    return PublicTemporalSupportReconciliationLedger(
        dict(plan["frozen_operator_artifact"]),
        dict(manifest["frozen_acquisition_plan"]),
        _artifact(manifest_path, root),
        path_binding,
        support_sets,
        sum(value.graph_relation is not None for value in stage32_compiled.events),
        reconciliation,
        sources,
        f"nldi-public-temporal-reconciliation:center-hill:{digest}",
    )


def _compile_path_binding(
    features: list[dict[str, Any]],
    *,
    source_coordinate: tuple[float, float],
    target_coordinate: tuple[float, float],
    hydrodynamic: dict[str, Any],
    advective: dict[str, Any],
    source_artifact: dict[str, object],
) -> PublicTemporalPathBinding:
    lines, gaps = _orient_lines(
        [value["geometry"]["coordinates"] for value in features],
        source_coordinate,
    )
    lengths = tuple(_line_length_m(value) for value in lines)
    source_snap, source_measure = _project_point_to_line(
        source_coordinate, lines[0]
    )
    target_snap, target_measure = _project_point_to_line(
        target_coordinate, lines[-1]
    )
    effective_length = (
        sum(lengths)
        - source_measure
        - (lengths[-1] - target_measure)
    )
    ids = tuple(
        int(value["properties"]["nhdplus_comid"])
        for value in features
    )
    hydro = next(
        value
        for value in hydrodynamic["systems"]
        if value["system_id"] == "center_hill"
    )
    advective_ids = tuple(
        int(value)
        for value in advective["linear_referenced_path"]["feature_ids"]
    )
    hydro_ids = tuple(int(value) for value in hydro["path_feature_ids"])
    suffix_matches = (
        hydro_ids[-len(ids) :] == ids
        and advective_ids[-len(ids) :] == ids
    )
    physics_length = float(
        advective["linear_referenced_path"]["total_effective_length_m"]
    )
    return PublicTemporalPathBinding(
        RELATION_ID,
        PATH_ID,
        SOURCE_COMID,
        TARGET_COMID,
        ids,
        float(sum(lengths)),
        float(effective_length),
        source_snap,
        target_snap,
        max(gaps, default=0.0),
        abs(physics_length - effective_length),
        suffix_matches,
        source_artifact,
    )


def _compile_physics_support(
    hydrodynamic: dict[str, Any],
    advective: dict[str, Any],
) -> tuple[temporal.ContinuousTemporalSupport, ...]:
    hydro = next(
        value
        for value in hydrodynamic["systems"]
        if value["system_id"] == "center_hill"
    )
    envelopes = hydro["envelopes"]
    gravity = envelopes["gravity_wave_travel_time_hours_q05_q50_q95"]
    manning = envelopes[
        "manning_centroid_travel_time_hours_q05_q50_q95"
    ]
    advective_seconds = advective["advective_travel_time_summary"]
    return (
        temporal.ContinuousTemporalSupport(
            "public-state-gravity-wave-envelope",
            PATH_ID,
            "gravity_wave_time",
            float(gravity[0]),
            float(gravity[1]),
            float(gravity[2]),
            str(hydro["path_scale_values"]["sha256"]),
            True,
            False,
            False,
        ),
        temporal.ContinuousTemporalSupport(
            "public-state-manning-centroid-envelope",
            PATH_ID,
            "manning_kinematic_centroid_time",
            float(manning[0]),
            float(manning[1]),
            float(manning[2]),
            str(hydro["path_scale_values"]["sha256"]),
            True,
            False,
            False,
        ),
        temporal.ContinuousTemporalSupport(
            "nwm-v3-advective-residence-envelope",
            PATH_ID,
            "advective_residence_time",
            float(advective_seconds["q05_seconds"]) / 3600.0,
            float(advective_seconds["q50_seconds"]) / 3600.0,
            float(advective_seconds["q95_seconds"]) / 3600.0,
            str(
                advective["advective_travel_time_prior"]["provenance_id"]
            ),
            True,
            False,
            False,
        ),
    )


def _validate_acquisition(
    manifest: dict[str, Any],
    plan: dict[str, Any],
    root: Path,
) -> None:
    after = manifest.get("claim_boundary_after_acquisition") or {}
    if (
        manifest.get("schema") != ACQUISITION_SCHEMA
        or manifest.get("status") != "source_to_target_path_acquired"
        or manifest.get("artifact_count") != 1
        or manifest.get("actual_request_count") != 1
        or manifest.get("path_feature_count") != 24
        or manifest.get("source_is_first_path_feature") is not True
        or manifest.get("target_reached") is not True
        or manifest.get("features_after_target_excluded") != 13
        or after.get("operator_frozen_before_path_values") is not True
        or after.get("temporal_support_reconciliation_compiled") is not False
        or plan != manifest.get("frozen_acquisition_plan_content")
        or plan.get("request_boundary", {}).get(
            "release_or_downstream_outcome_values_requested"
        )
        is not False
    ):
        raise ValueError("public_temporal_acquisition_manifest_invalid")
    _read_verified(plan["frozen_operator_artifact"], root)
    record = manifest["artifacts"][0]
    if (
        record.get("hash_verified") is not True
        or record.get("tls_hostname_verification_retained") is not True
    ):
        raise ValueError("public_temporal_path_provenance_invalid")


def _validate_prior_evidence(
    plan: dict[str, Any],
    stage32_gates: dict[str, Any],
    hydrodynamic: dict[str, Any],
    advective: dict[str, Any],
    source_coordinate: tuple[float, float],
    target_coordinate: tuple[float, float],
) -> None:
    relation = plan.get("relation") or {}
    if (
        _haversine_m(
            tuple(relation.get("source", {}).get("coordinate_wgs84") or ()),
            source_coordinate,
        )
        > 1.0
        or _haversine_m(
            tuple(relation.get("target", {}).get("coordinate_wgs84") or ()),
            target_coordinate,
        )
        > 1.0
        or stage32_gates.get("all_gates_passed") is not True
        or stage32_gates.get("decision", {}).get(
            "common_empirical_support_admitted"
        )
        is not False
        or hydrodynamic.get("schema")
        != "gwm.geotransport.hydrodynamic_scale_envelope.v1"
        or advective.get("schema")
        != "gwm.geotransport.center_hill_travel_time_prior.v1"
        or advective.get("advective_travel_time_prior", {}).get(
            "admitted_as_flood_wave_lag"
        )
        is not False
    ):
        raise ValueError("public_temporal_prior_evidence_invalid")


def _source_target_features(
    payload: dict[str, Any],
) -> list[dict[str, Any]]:
    features = payload.get("features") or []
    ids = [
        int(value["properties"]["nhdplus_comid"])
        for value in features
    ]
    if not ids or ids[0] != SOURCE_COMID or ids.count(TARGET_COMID) != 1:
        raise ValueError("public_temporal_source_target_path_invalid")
    return list(features[: ids.index(TARGET_COMID) + 1])


def _orient_lines(
    raw_lines: list[list[list[float]]],
    source_point: tuple[float, float],
) -> tuple[list[list[list[float]]], list[float]]:
    if not raw_lines or any(len(value) < 2 for value in raw_lines):
        raise ValueError("public_temporal_path_lines_required")
    first = raw_lines[0]
    if _haversine_m(source_point, tuple(first[-1])) < _haversine_m(
        source_point, tuple(first[0])
    ):
        first = list(reversed(first))
    lines = [first]
    gaps = []
    for raw in raw_lines[1:]:
        forward_gap = _haversine_m(tuple(lines[-1][-1]), tuple(raw[0]))
        reverse_gap = _haversine_m(tuple(lines[-1][-1]), tuple(raw[-1]))
        line = raw if forward_gap <= reverse_gap else list(reversed(raw))
        gap = min(forward_gap, reverse_gap)
        lines.append(line)
        gaps.append(gap)
    return lines, gaps


def _project_point_to_line(
    point: tuple[float, float], line: list[list[float]]
) -> tuple[float, float]:
    lon_scale = 111_195.08 * math.cos(math.radians(point[1]))
    lat_scale = 111_195.08
    px, py = point[0] * lon_scale, point[1] * lat_scale
    best_distance = math.inf
    best_measure = 0.0
    measure = 0.0
    for first, second in zip(line, line[1:]):
        ax, ay = first[0] * lon_scale, first[1] * lat_scale
        bx, by = second[0] * lon_scale, second[1] * lat_scale
        dx, dy = bx - ax, by - ay
        length_squared = dx * dx + dy * dy
        ratio = 0.0 if length_squared == 0.0 else (
            ((px - ax) * dx + (py - ay) * dy) / length_squared
        )
        ratio = min(1.0, max(0.0, ratio))
        distance = math.hypot(
            px - (ax + ratio * dx),
            py - (ay + ratio * dy),
        )
        segment_length = _haversine_m(tuple(first), tuple(second))
        if distance < best_distance:
            best_distance = distance
            best_measure = measure + ratio * segment_length
        measure += segment_length
    return float(best_distance), float(best_measure)


def _line_length_m(line: list[list[float]]) -> float:
    return float(
        sum(
            _haversine_m(tuple(first), tuple(second))
            for first, second in zip(line, line[1:])
        )
    )


def _haversine_m(
    first: tuple[float, float], second: tuple[float, float]
) -> float:
    lon1, lat1 = map(math.radians, first)
    lon2, lat2 = map(math.radians, second)
    delta_lon = lon2 - lon1
    delta_lat = lat2 - lat1
    value = (
        math.sin(delta_lat / 2.0) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin(delta_lon / 2.0) ** 2
    )
    return 6_371_008.8 * 2.0 * math.asin(min(1.0, math.sqrt(value)))


def _read_verified(descriptor: dict[str, Any], root: Path) -> bytes:
    path = _resolve(descriptor, root)
    body = path.read_bytes()
    if (
        hashlib.sha256(body).hexdigest() != descriptor.get("sha256")
        or len(body) != descriptor.get("size_bytes")
    ):
        raise ValueError("public_temporal_artifact_mismatch")
    return body


def _resolve(descriptor: dict[str, Any], root: Path) -> Path:
    path = (root / str(descriptor["path"])).resolve()
    if root != path and root not in path.parents:
        raise ValueError("public_temporal_artifact_outside_repository")
    return path


def _artifact(path: Path, root: Path) -> dict[str, object]:
    resolved = path.resolve()
    if root != resolved and root not in resolved.parents:
        raise ValueError("public_temporal_artifact_outside_repository")
    body = resolved.read_bytes()
    return {
        "path": resolved.relative_to(root).as_posix(),
        "sha256": hashlib.sha256(body).hexdigest(),
        "size_bytes": len(body),
    }


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_bytes())
    if not isinstance(value, dict):
        raise ValueError("public_temporal_json_object_required")
    return value
