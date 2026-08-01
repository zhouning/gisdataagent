"""Compile public spatial-boundary evidence without inventing neighbor states."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
from typing import Any

from .public_confluence_fixture import REPO_ROOT


PUBLIC_SPATIAL_BOUNDARY_EVIDENCE_SCHEMA = (
    "gwm.geospatial_kernel.public_spatial_boundary_evidence.v1"
)
EXPECTED_ACQUISITION_SCHEMA = (
    "gwm.geotransport.stage27_spatial_boundary_acquisition.v1"
)
DEFAULT_SOURCE_ROOT = REPO_ROOT / (
    "data/geotransport_v0_1/stage27_center_hill_spatial_boundary_evidence"
)
ROOT_COMID = 18421703
ANCHOR_SITE_ID = "USGS-03424860"
ANCHOR_MAINSTEM_URI = "https://geoconnex.us/ref/mainstems/349840"
RELEVANT_PARAMETER_CODES = frozenset({"00060", "00065"})
NEAREST_OBSERVATION_TOLERANCE_SECONDS = 900.0
MAXIMUM_BRACKET_SECONDS = 1800.0
EARTH_RADIUS_M = 6_371_008.8


@dataclass(frozen=True)
class TemporalSeriesSupport:
    series_id: str
    parameter_code: str
    parameter_name: str
    unit: str
    computation_period: str
    computation: str
    statistic_id: str | None
    begin_utc: str
    end_utc: str

    @property
    def instantaneous(self) -> bool:
        return (
            self.computation_period == "Points"
            and self.computation == "Instantaneous"
            and self.statistic_id == "00011"
        )

    def as_dict(self) -> dict[str, object]:
        return {
            "series_id": self.series_id,
            "parameter_code": self.parameter_code,
            "parameter_name": self.parameter_name,
            "unit": self.unit,
            "computation_period": self.computation_period,
            "computation": self.computation,
            "statistic_id": self.statistic_id,
            "begin_utc": self.begin_utc,
            "end_utc": self.end_utc,
            "instantaneous": self.instantaneous,
        }


@dataclass(frozen=True)
class SpatialBoundaryCandidateEvidence:
    monitoring_location_id: str
    name: str
    coordinate_wgs84: tuple[float, float]
    comid: int
    reachcode: str
    measure_percent: float
    topology_directions: tuple[str, ...]
    navigation_search_bounds_km: tuple[tuple[str, float], ...]
    mainstem_uri: str | None
    distance_from_anchor_m: float
    site_type: str
    drainage_area_square_miles: float | None
    temporal_series: tuple[TemporalSeriesSupport, ...]
    field_observation_counts: tuple[tuple[str, int], ...]
    field_time_range: tuple[str, str] | None
    source_artifacts: tuple[dict[str, object], ...]

    @property
    def is_anchor(self) -> bool:
        return self.monitoring_location_id == ANCHOR_SITE_ID

    @property
    def same_mainstem_as_anchor(self) -> bool:
        return self.mainstem_uri == ANCHOR_MAINSTEM_URI

    @property
    def instantaneous_parameter_codes(self) -> tuple[str, ...]:
        return tuple(
            sorted(
                {
                    value.parameter_code
                    for value in self.temporal_series
                    if value.instantaneous
                }
            )
        )

    def as_dict(self) -> dict[str, object]:
        return {
            "monitoring_location_id": self.monitoring_location_id,
            "name": self.name,
            "coordinate_wgs84": list(self.coordinate_wgs84),
            "comid": self.comid,
            "reachcode": self.reachcode,
            "measure_percent": self.measure_percent,
            "topology_directions": list(self.topology_directions),
            "navigation_search_bounds_km": dict(
                self.navigation_search_bounds_km
            ),
            "mainstem_uri": self.mainstem_uri,
            "same_mainstem_as_anchor": self.same_mainstem_as_anchor,
            "distance": {
                "value_m": self.distance_from_anchor_m,
                "method": "wgs84_coordinate_great_circle",
                "nldi_route_distance_returned": False,
            },
            "site_type": self.site_type,
            "drainage_area_square_miles": self.drainage_area_square_miles,
            "temporal_series": [
                value.as_dict() for value in self.temporal_series
            ],
            "instantaneous_parameter_codes": list(
                self.instantaneous_parameter_codes
            ),
            "field_observation_counts": dict(
                self.field_observation_counts
            ),
            "field_time_range": (
                list(self.field_time_range)
                if self.field_time_range is not None
                else None
            ),
            "source_artifacts": list(self.source_artifacts),
        }


@dataclass(frozen=True)
class ScalarObservation:
    observation_id: str
    monitoring_location_id: str
    parameter_code: str
    time: str
    value: float
    unit: str
    approval_status: str
    observation_kind: str

    def as_dict(self) -> dict[str, object]:
        return {
            "observation_id": self.observation_id,
            "monitoring_location_id": self.monitoring_location_id,
            "parameter_code": self.parameter_code,
            "time": self.time,
            "value": self.value,
            "unit": self.unit,
            "approval_status": self.approval_status,
            "observation_kind": self.observation_kind,
        }


@dataclass(frozen=True)
class SynchronizedSpatialSnapshot:
    candidate: ScalarObservation
    anchor_before: ScalarObservation
    anchor_after: ScalarObservation
    candidate_comid: int
    candidate_topology_directions: tuple[str, ...]
    candidate_distance_from_anchor_m: float
    candidate_same_mainstem_as_anchor: bool
    nearest_time_difference_seconds: float
    bracket_width_seconds: float
    source_artifact: dict[str, object]

    def __post_init__(self) -> None:
        if (
            self.candidate.monitoring_location_id == ANCHOR_SITE_ID
            or self.anchor_before.monitoring_location_id != ANCHOR_SITE_ID
            or self.anchor_after.monitoring_location_id != ANCHOR_SITE_ID
            or not (
                self.candidate.parameter_code
                == self.anchor_before.parameter_code
                == self.anchor_after.parameter_code
            )
            or not (
                self.candidate.unit
                == self.anchor_before.unit
                == self.anchor_after.unit
            )
            or self.nearest_time_difference_seconds
            > NEAREST_OBSERVATION_TOLERANCE_SECONDS
            or self.bracket_width_seconds > MAXIMUM_BRACKET_SECONDS
        ):
            raise ValueError("synchronized_spatial_snapshot_invalid")

    @property
    def fully_approved(self) -> bool:
        return all(
            value.approval_status == "Approved"
            for value in (
                self.candidate,
                self.anchor_before,
                self.anchor_after,
            )
        )

    @property
    def anchor_bracket_mean(self) -> float:
        return (self.anchor_before.value + self.anchor_after.value) / 2.0

    @property
    def candidate_to_anchor_bracket_mean_ratio(self) -> float:
        return self.candidate.value / self.anchor_bracket_mean

    def as_dict(self) -> dict[str, object]:
        return {
            "candidate": self.candidate.as_dict(),
            "anchor_bracket": {
                "before": self.anchor_before.as_dict(),
                "after": self.anchor_after.as_dict(),
                "mean_value": self.anchor_bracket_mean,
            },
            "spatial_binding": {
                "candidate_comid": self.candidate_comid,
                "candidate_topology_directions": list(
                    self.candidate_topology_directions
                ),
                "candidate_distance_from_anchor_m": (
                    self.candidate_distance_from_anchor_m
                ),
                "candidate_same_mainstem_as_anchor": (
                    self.candidate_same_mainstem_as_anchor
                ),
            },
            "synchronization": {
                "method": "candidate_field_time_bracketed_by_anchor_continuous_values",
                "nearest_time_difference_seconds": (
                    self.nearest_time_difference_seconds
                ),
                "nearest_tolerance_seconds": (
                    NEAREST_OBSERVATION_TOLERANCE_SECONDS
                ),
                "bracket_width_seconds": self.bracket_width_seconds,
                "maximum_bracket_seconds": MAXIMUM_BRACKET_SECONDS,
                "linear_interpolation_performed": False,
                "passes": True,
            },
            "candidate_to_anchor_bracket_mean_ratio": (
                self.candidate_to_anchor_bracket_mean_ratio
            ),
            "fully_approved": self.fully_approved,
            "source_artifact": self.source_artifact,
        }


@dataclass(frozen=True)
class PublicSpatialBoundaryEvidenceLedger:
    candidates: tuple[SpatialBoundaryCandidateEvidence, ...]
    synchronized_snapshots: tuple[SynchronizedSpatialSnapshot, ...]
    source_artifacts: tuple[dict[str, object], ...]
    request_boundary: dict[str, object]
    licenses: tuple[dict[str, str], ...]
    provenance_id: str

    def __post_init__(self) -> None:
        ids = tuple(value.monitoring_location_id for value in self.candidates)
        if (
            len(self.candidates) != 11
            or len(set(ids)) != len(ids)
            or ids != tuple(sorted(ids))
            or ANCHOR_SITE_ID not in ids
            or len(self.synchronized_snapshots) != 2
            or any(
                value.candidate.monitoring_location_id != "USGS-03424010"
                for value in self.synchronized_snapshots
            )
        ):
            raise ValueError("public_spatial_boundary_evidence_ledger_invalid")

    def require_synchronized_spatial_snapshots(
        self,
    ) -> tuple[SynchronizedSpatialSnapshot, ...]:
        return self.synchronized_snapshots

    def require_continuous_boundary_hydrographs(self) -> None:
        raise ValueError(
            "public_spatial_boundary_continuous_hydrographs_unavailable"
        )

    def require_fully_approved_spatial_snapshots(self) -> None:
        raise ValueError(
            "public_spatial_boundary_candidate_measurements_provisional"
        )

    def require_observed_spatial_rollout(self) -> None:
        raise ValueError(
            "public_spatial_boundary_snapshots_are_not_spatial_rollout"
        )

    def substitute_anchor_history_for_neighbor(self) -> None:
        raise ValueError(
            "public_spatial_boundary_same_site_temporal_substitution_forbidden"
        )

    def as_dict(self) -> dict[str, object]:
        distinct = [value for value in self.candidates if not value.is_anchor]
        same_mainstem = [
            value for value in distinct if value.same_mainstem_as_anchor
        ]
        approved = [
            value for value in self.synchronized_snapshots if value.fully_approved
        ]
        return {
            "schema": PUBLIC_SPATIAL_BOUNDARY_EVIDENCE_SCHEMA,
            "root_comid": ROOT_COMID,
            "anchor_monitoring_location_id": ANCHOR_SITE_ID,
            "candidate_count": len(self.candidates),
            "spatially_distinct_candidate_count": len(distinct),
            "same_mainstem_spatial_candidate_count": len(same_mainstem),
            "candidates": [value.as_dict() for value in self.candidates],
            "synchronized_snapshot_count": len(
                self.synchronized_snapshots
            ),
            "fully_approved_snapshot_count": len(approved),
            "synchronized_snapshots": [
                value.as_dict() for value in self.synchronized_snapshots
            ],
            "request_boundary": self.request_boundary,
            "licenses": list(self.licenses),
            "source_artifacts": list(self.source_artifacts),
            "provenance_id": self.provenance_id,
            "evidence_admission": {
                "nldi_topology_and_comid_binding_verified": True,
                "spatially_distinct_synchronized_snapshots_admitted": True,
                "candidate_measurements_are_provisional": True,
                "continuous_boundary_hydrographs_admitted": False,
                "same_site_temporal_substitution_admitted": False,
                "observed_spatial_rollout_admitted": False,
                "runtime_operator_admitted": False,
            },
            "claim_boundary": {
                "two_observed_spatial_snapshot_pairs_found": True,
                "snapshot_pairs_are_continuous_boundary_conditions": False,
                "snapshot_pairs_define_travel_time": False,
                "snapshot_pairs_define_reach_wide_geometry": False,
                "reach_boundary_conditions_observed": False,
                "observed_spatial_rollout_completed": False,
                "operator_admitted": False,
            },
            "decision": {
                "spatial_snapshot_evidence_admitted": True,
                "continuous_boundary_hydrographs_admitted": False,
                "observed_spatial_rollout_completed": False,
                "runtime_operator_admitted": False,
            },
        }


def compile_public_spatial_boundary_evidence(
    source_root: Path = DEFAULT_SOURCE_ROOT,
    *,
    repo_root: Path = REPO_ROOT,
) -> PublicSpatialBoundaryEvidenceLedger:
    repository = Path(repo_root).resolve()
    manifest = _read_json(Path(source_root) / "acquisition_manifest.json")
    _validate_manifest(manifest)
    verified = _verify_artifacts(manifest, repository)
    by_source = {
        str(value["source_id"]): value for value in verified
    }
    candidate_values = {
        str(value["monitoring_location_id"]): value
        for value in manifest["candidates"]
    }
    anchor_coordinate = tuple(
        float(item)
        for item in candidate_values[ANCHOR_SITE_ID]["coordinate_wgs84"]
    )
    candidates = tuple(
        _compile_candidate(
            value,
            anchor_coordinate=anchor_coordinate,
            artifacts=by_source,
            repository=repository,
        )
        for value in sorted(
            manifest["candidates"],
            key=lambda item: str(item["monitoring_location_id"]),
        )
    )
    candidate_by_id = {
        value.monitoring_location_id: value for value in candidates
    }
    snapshots = tuple(
        _compile_snapshot(
            value,
            candidate=candidate_by_id[
                str(value["candidate_monitoring_location_id"])
            ],
            artifacts=by_source,
            repository=repository,
        )
        for value in manifest["match_windows"]
    )
    licenses = tuple(
        {
            "license": name,
            "license_url": url,
        }
        for name, url in sorted(
            {
                (str(value["license"]), str(value["license_url"]))
                for value in verified
            }
        )
    )
    digest = hashlib.sha256(
        "|".join(sorted(str(value["sha256"]) for value in verified)).encode(
            "ascii"
        )
    ).hexdigest()
    return PublicSpatialBoundaryEvidenceLedger(
        candidates,
        snapshots,
        tuple(verified),
        dict(manifest["request_boundary"]),
        licenses,
        f"usgs-spatial-boundary:{ROOT_COMID}:{digest}",
    )


def _compile_candidate(
    value: dict[str, Any],
    *,
    anchor_coordinate: tuple[float, float],
    artifacts: dict[str, dict[str, object]],
    repository: Path,
) -> SpatialBoundaryCandidateEvidence:
    site_id = str(value["monitoring_location_id"])
    number = site_id.removeprefix("USGS-")
    source_ids = (
        f"usgs_monitoring_location_{number}",
        f"usgs_time_series_metadata_{number}",
        f"usgs_field_measurements_{number}",
    )
    source_records = tuple(artifacts[source_id] for source_id in source_ids)
    site = _read_json(_resolve(source_records[0], repository))
    series_body = _read_json(_resolve(source_records[1], repository))
    field_body = _read_json(_resolve(source_records[2], repository))
    properties = site["properties"]
    coordinate = tuple(float(item) for item in site["geometry"]["coordinates"])
    nldi_coordinate = tuple(float(item) for item in value["coordinate_wgs84"])
    if (
        str(properties["id"]) != site_id
        or max(abs(a - b) for a, b in zip(coordinate, nldi_coordinate)) > 1e-5
    ):
        raise ValueError("public_spatial_boundary_site_binding_invalid")
    series = tuple(
        _compile_series(feature)
        for feature in series_body["features"]
        if str(feature["properties"].get("parameter_code"))
        in RELEVANT_PARAMETER_CODES
    )
    fields = [
        feature["properties"]
        for feature in field_body["features"]
        if str(feature["properties"].get("parameter_code"))
        in RELEVANT_PARAMETER_CODES
    ]
    counts = _counts(str(item["parameter_code"]) for item in fields)
    times = sorted(str(item["time"]) for item in fields)
    drainage = properties.get("drainage_area")
    return SpatialBoundaryCandidateEvidence(
        site_id,
        str(value["name"]),
        coordinate,
        int(value["comid"]),
        str(value["reachcode"]),
        float(value["measure_percent"]),
        tuple(str(item) for item in value["topology_directions"]),
        tuple(
            sorted(
                (str(name), float(bound))
                for name, bound in value[
                    "navigation_search_bounds_km"
                ].items()
            )
        ),
        str(value["mainstem_uri"]) if value["mainstem_uri"] else None,
        _great_circle_distance_m(anchor_coordinate, coordinate),
        str(properties["site_type"]),
        float(drainage) if drainage is not None else None,
        series,
        tuple(sorted(counts.items())),
        (times[0], times[-1]) if times else None,
        source_records,
    )


def _compile_series(feature: dict[str, Any]) -> TemporalSeriesSupport:
    value = feature["properties"]
    return TemporalSeriesSupport(
        str(feature["id"]),
        str(value["parameter_code"]),
        str(value["parameter_name"]),
        str(value["unit_of_measure"]),
        str(value["computation_period_identifier"]),
        str(value["computation_identifier"]),
        str(value["statistic_id"])
        if value.get("statistic_id") is not None
        else None,
        str(value["begin_utc"]),
        str(value["end_utc"]),
    )


def _compile_snapshot(
    match: dict[str, Any],
    *,
    candidate: SpatialBoundaryCandidateEvidence,
    artifacts: dict[str, dict[str, object]],
    repository: Path,
) -> SynchronizedSpatialSnapshot:
    number = candidate.monitoring_location_id.removeprefix("USGS-")
    fields_record = artifacts[f"usgs_field_measurements_{number}"]
    fields = _read_json(_resolve(fields_record, repository))
    feature = next(
        (
            item
            for item in fields["features"]
            if str(item["id"])
            == str(match["candidate_field_measurement_id"])
        ),
        None,
    )
    if feature is None:
        raise ValueError("public_spatial_boundary_candidate_field_missing")
    candidate_observation = _scalar_from_field(feature)
    continuous_record = artifacts[str(match["source_id"])]
    continuous = _read_json(_resolve(continuous_record, repository))
    anchor_observations = tuple(
        sorted(
            (_scalar_from_continuous(item) for item in continuous["features"]),
            key=lambda item: _parse_datetime(item.time),
        )
    )
    candidate_time = _parse_datetime(candidate_observation.time)
    before = [
        item
        for item in anchor_observations
        if _parse_datetime(item.time) <= candidate_time
    ]
    after = [
        item
        for item in anchor_observations
        if _parse_datetime(item.time) >= candidate_time
    ]
    if not before or not after:
        raise ValueError("public_spatial_boundary_anchor_bracket_missing")
    anchor_before = before[-1]
    anchor_after = after[0]
    before_time = _parse_datetime(anchor_before.time)
    after_time = _parse_datetime(anchor_after.time)
    nearest = min(
        abs((candidate_time - before_time).total_seconds()),
        abs((after_time - candidate_time).total_seconds()),
    )
    bracket = (after_time - before_time).total_seconds()
    return SynchronizedSpatialSnapshot(
        candidate_observation,
        anchor_before,
        anchor_after,
        candidate.comid,
        candidate.topology_directions,
        candidate.distance_from_anchor_m,
        candidate.same_mainstem_as_anchor,
        nearest,
        bracket,
        continuous_record,
    )


def _scalar_from_field(feature: dict[str, Any]) -> ScalarObservation:
    value = feature["properties"]
    return ScalarObservation(
        str(feature["id"]),
        str(value["monitoring_location_id"]),
        str(value["parameter_code"]),
        str(value["time"]),
        float(value["value"]),
        str(value["unit_of_measure"]),
        str(value["approval_status"]),
        "field_measurement",
    )


def _scalar_from_continuous(feature: dict[str, Any]) -> ScalarObservation:
    value = feature["properties"]
    return ScalarObservation(
        str(feature["id"]),
        str(value["monitoring_location_id"]),
        str(value["parameter_code"]),
        str(value["time"]),
        float(value["value"]),
        str(value["unit_of_measure"]),
        str(value["approval_status"]),
        "continuous_observation",
    )


def _validate_manifest(manifest: dict[str, Any]) -> None:
    boundary = manifest.get("request_boundary", {})
    if (
        manifest.get("schema") != EXPECTED_ACQUISITION_SCHEMA
        or manifest.get("mode") != "values"
        or manifest.get("candidate_count") != 11
        or manifest.get("match_window_count") != 2
        or manifest.get("artifact_count") != 38
        or manifest.get("actual_request_count") != 38
        or manifest.get("total_downloaded_bytes", math.inf)
        > boundary.get("maximum_total_download_bytes", -math.inf)
        or boundary.get("workspace_or_private_data_sent") is not False
    ):
        raise ValueError("public_spatial_boundary_manifest_invalid")


def _verify_artifacts(
    manifest: dict[str, Any], repository: Path
) -> list[dict[str, object]]:
    verified = []
    for record in manifest["artifacts"]:
        path = _resolve(record, repository)
        body = path.read_bytes()
        if (
            len(body) != int(record["size_bytes"])
            or hashlib.sha256(body).hexdigest() != record["sha256"]
            or record.get("license") != "USGS public-domain data"
        ):
            raise ValueError("public_spatial_boundary_artifact_invalid")
        verified.append(
            {
                "source_id": str(record["source_id"]),
                "path": str(record["path"]),
                "size_bytes": int(record["size_bytes"]),
                "sha256": str(record["sha256"]),
                "url": str(record["url"]),
                "role": str(record["role"]),
                "license": str(record["license"]),
                "license_url": str(record["license_url"]),
            }
        )
    return verified


def _resolve(record: dict[str, object], repository: Path) -> Path:
    path = (repository / str(record["path"])).resolve()
    if repository != path and repository not in path.parents:
        raise ValueError("public_spatial_boundary_artifact_outside_repository")
    return path


def _great_circle_distance_m(
    first: tuple[float, float], second: tuple[float, float]
) -> float:
    lon1, lat1 = (math.radians(value) for value in first)
    lon2, lat2 = (math.radians(value) for value in second)
    dlon = lon2 - lon1
    dlat = lat2 - lat1
    a = (
        math.sin(dlat / 2.0) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2.0) ** 2
    )
    return 2.0 * EARTH_RADIUS_M * math.asin(math.sqrt(a))


def _parse_datetime(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("public_spatial_boundary_datetime_naive")
    return parsed.astimezone(timezone.utc)


def _counts(values) -> dict[str, int]:
    result: dict[str, int] = {}
    for value in values:
        result[value] = result.get(value, 0) + 1
    return result


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))
