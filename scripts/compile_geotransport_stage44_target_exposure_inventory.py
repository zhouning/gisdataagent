#!/usr/bin/env python3
"""Compile the no-network Stage 44 target-exposure inventory."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from data_agent.uwm.geospatial_kernel_v2 import (  # noqa: E402
    target_exposure_inventory as inventory_operator,
)

STAGE44_ROOT = "data/geotransport_v0_1/stage44_center_hill_component_lag_replication"
DEFAULT_OUTPUT = REPO_ROOT / STAGE44_ROOT / "target_exposure_inventory.json"
STATUS = "stage44_complete_known_target_exposure_inventory_compiled_offline"

SOURCE_SPECS = (
    (
        "smoke",
        "data/geotransport_v0_1/acquisition_manifest.json",
        "acquisition_manifest",
        1,
    ),
    (
        "development",
        "data/geotransport_v0_1/center_hill_672h/acquisition_manifest.json",
        "acquisition_manifest",
        1,
    ),
    (
        "temporal_holdout_companion",
        "data/geotransport_v0_1/center_hill_evaluation/companion/acquisition_manifest.json",
        "acquisition_manifest",
        1,
    ),
    (
        "center_hill_v2_d3",
        "data/geotransport_v0_1/center_hill_v2_d3_inputs/outcome/acquisition_manifest.json",
        "acquisition_manifest",
        1,
    ),
    (
        "two_system_blind_validation",
        "benchmarks/geotransport_v0_1/geotransport_v2_blind_validation_outcomes_report.json",
        "outcome_report",
        1,
    ),
    (
        "kinematic_holdout_v1",
        "benchmarks/geotransport_v0_1/kinematic_wave_holdout_v1_protocol.json",
        "sealed_protocol",
        1,
    ),
    (
        "kinematic_holdout_v2",
        "benchmarks/geotransport_v0_1/kinematic_wave_holdout_v2_outcomes_report.json",
        "outcome_report",
        1,
    ),
    (
        "stage27_spatial_boundary",
        "data/geotransport_v0_1/"
        "stage27_center_hill_spatial_boundary_evidence/"
        "acquisition_manifest.json",
        "acquisition_manifest",
        2,
    ),
    (
        "stage28_operational_boundary",
        "data/geotransport_v0_1/"
        "stage28_center_hill_operational_boundary_evidence/"
        "acquisition_manifest.json",
        "acquisition_manifest",
        2,
    ),
    (
        "stage29_blind_transfer",
        "data/geotransport_v0_1/"
        "stage29_center_hill_blind_transfer_events/"
        "observation_acquisition_manifest.json",
        "acquisition_manifest",
        3,
    ),
    (
        "stage30_regime_validation",
        "data/geotransport_v0_1/"
        "stage30_center_hill_regime_validation_events/"
        "observation_acquisition_manifest.json",
        "acquisition_manifest",
        4,
    ),
    (
        "stage31_identifiable_response",
        "data/geotransport_v0_1/"
        "stage31_center_hill_identifiable_response_events/"
        "observation_acquisition_manifest.json",
        "acquisition_manifest",
        4,
    ),
    (
        "stage32_lag_support",
        "data/geotransport_v0_1/"
        "stage32_center_hill_lag_support_events/"
        "observation_acquisition_manifest.json",
        "acquisition_manifest",
        4,
    ),
    (
        "stage36_hydraulic_boundary",
        "data/geotransport_v0_1/"
        "stage36_center_hill_hydraulic_boundary_events/"
        "observation_acquisition_manifest.json",
        "acquisition_manifest",
        4,
    ),
    (
        "stage42_component_event_targets",
        "data/geotransport_v0_1/"
        "stage42_center_hill_component_event_target_protocol/"
        "target_acquisition_manifest.json",
        "acquisition_manifest",
        4,
    ),
)

FROZEN_HASHES = {
    "data/geotransport_v0_1/acquisition_manifest.json": (
        "08d322ee9ee580e2d5f74cfe1dd8d7a85f5052f340a9d25c4cffcc860047e8c0"
    ),
    "data/geotransport_v0_1/center_hill_672h/acquisition_manifest.json": (
        "9c0611755e0099ed2caf02660b108b94529579e8f809c4e8f7f0dafb38222b87"
    ),
    (
        "data/geotransport_v0_1/center_hill_evaluation/companion/acquisition_manifest.json"
    ): "5989e1bfc87a788e9ba7daf6760e5e147aa459792e5b81eb17418f7d0ed1bf27",
    (
        "data/geotransport_v0_1/center_hill_v2_d3_inputs/outcome/acquisition_manifest.json"
    ): "00b9f3d8da9f3920b7b15782ad54a6e564fed0ab00ae0db7f639829c33e1a580",
    (
        "benchmarks/geotransport_v0_1/geotransport_v2_blind_validation_outcomes_report.json"
    ): "9f299c3610501f9d223f658c538a1db612f1d2ff3e02bc565abf0c55f20731d6",
    "benchmarks/geotransport_v0_1/kinematic_wave_holdout_v1_protocol.json": (
        "cd8b5d7eb2c52472a145b2ccecbd7fbf469aa05888fa5121f2e6c31e243bde8b"
    ),
    (
        "benchmarks/geotransport_v0_1/kinematic_wave_holdout_v2_outcomes_report.json"
    ): "2e61b7440746a33eb5a9ab51bb8248325e31206a7c153baa470fbbe625cfbd38",
    (
        "data/geotransport_v0_1/stage27_center_hill_spatial_boundary_evidence/"
        "acquisition_manifest.json"
    ): "475e2c596667dcd4c2c7f6d8b88b212e0fa35e1c4619f2ec7bd1a86a5fd44d9e",
    (
        "data/geotransport_v0_1/stage28_center_hill_operational_boundary_evidence/"
        "acquisition_manifest.json"
    ): "1af45b76c416fed176307a6f3acdfabde006c1514a57cddc71f7008b6ea36af6",
    (
        "data/geotransport_v0_1/stage29_center_hill_blind_transfer_events/"
        "observation_acquisition_manifest.json"
    ): "6e4597cc00612c4846e2f3cfdc1affbe5c9e75572fd81c2260d833c01d9864a8",
    (
        "data/geotransport_v0_1/stage30_center_hill_regime_validation_events/"
        "observation_acquisition_manifest.json"
    ): "c44eb3d49e455e86f729ac1b3968481123ef37fe288de82f9da3c4416a349849",
    (
        "data/geotransport_v0_1/stage31_center_hill_identifiable_response_events/"
        "observation_acquisition_manifest.json"
    ): "8f84fe838c5a7cf641195a8bbc941a2a1396360c510043e9ffedb22547122b97",
    (
        "data/geotransport_v0_1/stage32_center_hill_lag_support_events/"
        "observation_acquisition_manifest.json"
    ): "8960a952be727defda098de02b3005b7a335c7ef1b8ec40f4c082dbe1294b648",
    (
        "data/geotransport_v0_1/stage36_center_hill_hydraulic_boundary_events/"
        "observation_acquisition_manifest.json"
    ): "88c88416741287984ab5091e3d6e4a6d95384dad14a545832e76c50bf784a269",
    (
        "data/geotransport_v0_1/stage42_center_hill_component_event_target_protocol/"
        "target_acquisition_manifest.json"
    ): "55201c79b843a4d961efc2388d4e6bae54a4f505e50a8c429f634be048f20df7",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def compile_inventory() -> inventory_operator.TargetExposureInventory:
    records: list[inventory_operator.TargetExposureRecord] = []
    artifacts = []
    for phase, relative_path, evidence_kind, expected_count in SOURCE_SPECS:
        artifact = _frozen_artifact(relative_path)
        artifacts.append(artifact)
        payload = _read_json(REPO_ROOT / relative_path)
        intervals = _extract_target_intervals(payload)
        if len(intervals) != expected_count:
            raise ValueError(
                f"stage44_target_interval_count_drift:{phase}:{len(intervals)}:{expected_count}"
            )
        for index, (source_id, begin_utc, end_utc) in enumerate(intervals, start=1):
            records.append(
                inventory_operator.TargetExposureRecord(
                    source_id=source_id or f"{phase}_{index:02d}",
                    phase=phase,
                    artifact_path=relative_path,
                    begin_utc=begin_utc,
                    end_utc=end_utc,
                    evidence_kind=evidence_kind,
                )
            )
    return inventory_operator.compile_target_exposure_inventory(tuple(records), tuple(artifacts))


def compile_report() -> dict[str, Any]:
    inventory = compile_inventory()
    return {
        **inventory.as_dict(),
        "status": STATUS,
        "audit": {
            "all_source_artifacts_hash_frozen": True,
            "source_artifact_paths_are_explicit": True,
            "known_stage27_short_probes_included": True,
            "known_stage28_three_day_windows_included": True,
            "known_stage29_through_stage32_event_windows_included": True,
            "known_stage36_event_windows_included": True,
            "known_stage42_event_windows_included": True,
            "broad_development_and_holdout_windows_included": True,
            "inventory_compiled_before_stage44_event_selection": True,
        },
        "claim_boundary": {
            "complete_known_target_exposure_boundary_admitted": True,
            "absence_of_unknown_external_exposure_proven": False,
            "stage44_replication_events_admitted": False,
            "new_target_values_acquired": False,
            "stage43_pattern_replicated": False,
            "causal_or_physical_relation_admitted": False,
            "runtime_operator_admitted": False,
        },
    }


def _extract_target_intervals(
    payload: dict[str, Any],
) -> tuple[tuple[str | None, str, str], ...]:
    by_window: dict[tuple[str, str], str | None] = {}
    for value in _walk_objects(payload):
        source_id = _source_id(value)
        for key in ("url", "source_url", "final_url"):
            raw_url = value.get(key)
            if not isinstance(raw_url, str):
                continue
            bounds = _target_url_bounds(raw_url)
            if bounds is not None:
                current = by_window.get(bounds)
                if current is None or (source_id is not None and current.startswith("http")):
                    by_window[bounds] = source_id or raw_url
        if (
            str(value.get("site_id")) in {"03424860", "USGS-03424860"}
            and str(value.get("parameter_code")) == "00060"
            and isinstance(value.get("request_start"), str)
            and isinstance(value.get("request_end"), str)
        ):
            bounds = (
                _normalized_time(str(value["request_start"])),
                _normalized_time(str(value["request_end"])),
            )
            by_window[bounds] = source_id
    return tuple((source_id, begin, end) for (begin, end), source_id in sorted(by_window.items()))


def _target_url_bounds(url: str) -> tuple[str, str] | None:
    query = parse_qs(urlparse(unquote(url)).query)
    site = (query.get("monitoring_location_id") or query.get("sites") or [""])[0]
    parameter = (query.get("parameter_code") or query.get("parameterCd") or [""])[0]
    if site not in {"03424860", "USGS-03424860"} or parameter != "00060":
        return None
    if "datetime" in query:
        raw_begin, raw_end = query["datetime"][0].split("/", maxsplit=1)
    elif "startDT" in query and "endDT" in query:
        raw_begin = query["startDT"][0]
        raw_end = query["endDT"][0]
    else:
        return None
    return _normalized_time(raw_begin), _normalized_time(raw_end)


def _source_id(value: dict[str, Any]) -> str | None:
    for key in ("source_id", "event_id", "system_id"):
        raw = value.get(key)
        if isinstance(raw, str) and raw:
            return raw
    return None


def _walk_objects(value: Any):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _walk_objects(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_objects(child)


def _normalized_time(value: str) -> str:
    return inventory_operator._iso(inventory_operator._parse_time(value))  # noqa: SLF001


def _frozen_artifact(relative_path: str) -> dict[str, object]:
    path = REPO_ROOT / relative_path
    body = path.read_bytes()
    sha256 = hashlib.sha256(body).hexdigest()
    if sha256 != FROZEN_HASHES[relative_path]:
        raise ValueError(f"stage44_frozen_exposure_artifact_drift:{relative_path}")
    return {"path": relative_path, "sha256": sha256, "size_bytes": len(body)}


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_bytes())
    if not isinstance(value, dict):
        raise ValueError("stage44_json_object_required")
    return value


def _json_bytes(value: dict[str, Any]) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode("utf-8")


def main() -> int:
    args = parse_args()
    report = compile_report()
    body = _json_bytes(report)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(body)
    print(args.output)
    print(f"status={report['status']}")
    print(f"records={report['exposure_record_count']}")
    print(f"merged_intervals={report['merged_interval_count']}")
    print("network_requests=0")
    print(f"sha256={hashlib.sha256(body).hexdigest()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
