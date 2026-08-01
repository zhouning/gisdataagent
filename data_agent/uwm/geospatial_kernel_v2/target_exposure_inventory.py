"""Target-value exposure inventory for outcome-blind event selection."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

SCHEMA = "gwm.geospatial.target_exposure_inventory.v1"
TARGET_SITE_ID = "USGS-03424860"
PARAMETER_CODE = "00060"


@dataclass(frozen=True)
class TargetExposureRecord:
    source_id: str
    phase: str
    artifact_path: str
    begin_utc: str
    end_utc: str
    evidence_kind: str

    def __post_init__(self) -> None:
        if (
            not self.source_id
            or not self.phase
            or not self.artifact_path
            or self.evidence_kind
            not in {"acquisition_manifest", "outcome_report", "sealed_protocol"}
            or _parse_time(self.begin_utc) >= _parse_time(self.end_utc)
        ):
            raise ValueError("target_exposure_record_invalid")

    def as_dict(self) -> dict[str, str]:
        return {
            "source_id": self.source_id,
            "phase": self.phase,
            "artifact_path": self.artifact_path,
            "begin_utc": self.begin_utc,
            "end_utc": self.end_utc,
            "evidence_kind": self.evidence_kind,
            "target_site_id": TARGET_SITE_ID,
            "parameter_code": PARAMETER_CODE,
        }


@dataclass(frozen=True)
class TargetExposureInventory:
    records: tuple[TargetExposureRecord, ...]
    source_artifacts: tuple[dict[str, object], ...]

    def __post_init__(self) -> None:
        ordered = tuple(
            sorted(
                self.records,
                key=lambda value: (
                    _parse_time(value.begin_utc),
                    _parse_time(value.end_utc),
                    value.source_id,
                ),
            )
        )
        artifact_paths = tuple(str(value.get("path")) for value in self.source_artifacts)
        if (
            not self.records
            or self.records != ordered
            or not self.source_artifacts
            or len(artifact_paths) != len(set(artifact_paths))
            or any(len(str(value.get("sha256", ""))) != 64 for value in self.source_artifacts)
            or any(record.artifact_path not in artifact_paths for record in self.records)
        ):
            raise ValueError("target_exposure_inventory_invalid")

    @property
    def merged_intervals(self) -> tuple[dict[str, object], ...]:
        merged: list[tuple[datetime, datetime]] = []
        for record in self.records:
            begin = _parse_time(record.begin_utc)
            end = _parse_time(record.end_utc)
            if merged and begin <= merged[-1][1]:
                merged[-1] = (merged[-1][0], max(merged[-1][1], end))
            else:
                merged.append((begin, end))
        result = []
        for index, (begin, end) in enumerate(merged, start=1):
            covered = tuple(
                record.source_id
                for record in self.records
                if _parse_time(record.begin_utc) <= end and _parse_time(record.end_utc) >= begin
            )
            result.append(
                {
                    "interval_id": f"target_exposure_{index:02d}",
                    "begin_utc": _iso(begin),
                    "end_utc": _iso(end),
                    "source_record_count": len(covered),
                    "source_ids": list(covered),
                }
            )
        return tuple(result)

    @property
    def excluded_windows_utc(self) -> tuple[tuple[str, str], ...]:
        return tuple(
            (str(value["begin_utc"]), str(value["end_utc"])) for value in self.merged_intervals
        )

    def overlaps(self, begin_utc: str, end_utc: str) -> bool:
        begin = _parse_time(begin_utc)
        end = _parse_time(end_utc)
        if begin > end:
            raise ValueError("target_exposure_query_window_invalid")
        return any(
            begin <= _parse_time(str(value["end_utc"]))
            and end >= _parse_time(str(value["begin_utc"]))
            for value in self.merged_intervals
        )

    def as_dict(self) -> dict[str, Any]:
        phases = sorted({record.phase for record in self.records})
        return {
            "schema": SCHEMA,
            "role": "complete_known_target_value_exposure_boundary",
            "target": {
                "site_id": TARGET_SITE_ID,
                "parameter_code": PARAMETER_CODE,
                "quantity": "continuous_discharge",
            },
            "source_artifact_count": len(self.source_artifacts),
            "source_artifacts": list(self.source_artifacts),
            "exposure_record_count": len(self.records),
            "exposure_phase_count": len(phases),
            "exposure_phases": phases,
            "exposure_records": [record.as_dict() for record in self.records],
            "merged_interval_count": len(self.merged_intervals),
            "merged_intervals": list(self.merged_intervals),
            "boundary": {
                "request_boundaries_are_used_not_trimmed_analysis_support": True,
                "overlapping_and_contiguous_intervals_are_merged": True,
                "metadata_only_requests_are_excluded": True,
                "other_sites_and_parameters_are_excluded": True,
                "target_values_loaded_by_inventory_compiler": False,
                "network_request_count": 0,
            },
        }


def compile_target_exposure_inventory(
    records: tuple[TargetExposureRecord, ...],
    source_artifacts: tuple[dict[str, object], ...],
) -> TargetExposureInventory:
    ordered = tuple(
        sorted(
            records,
            key=lambda value: (
                _parse_time(value.begin_utc),
                _parse_time(value.end_utc),
                value.source_id,
            ),
        )
    )
    return TargetExposureInventory(ordered, source_artifacts)


def _parse_time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("target_exposure_timezone_required")
    return parsed.astimezone(UTC)


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")
