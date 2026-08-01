#!/usr/bin/env python3
"""Compile Stage 44 source-only component-lag replication events."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts import (  # noqa: E402
    compile_geotransport_stage41_component_discharge_events as stage41,
)
from scripts import (  # noqa: E402
    compile_geotransport_stage44_target_exposure_inventory as exposure,
)
from scripts import (  # noqa: E402
    freeze_geotransport_stage44_component_lag_replication_protocol as freeze,
)

DEFAULT_OUTPUT = REPO_ROOT / freeze.STAGE44_ROOT
PROTOCOL_NAME = "replication_protocol.json"
CANDIDATE_LEDGER_NAME = "replication_candidate_ledger.json"
MANIFEST_NAME = "replication_event_manifest.json"
CANDIDATE_SCHEMA = "gwm.geotransport.stage44_replication_candidates.v1"
MANIFEST_SCHEMA = "gwm.geotransport.stage44_replication_event_manifest.v1"
STATUS = "stage44_component_lag_replication_cohort_frozen_source_only"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def compile_selection():
    inventory = exposure.compile_inventory()
    anchor = inventory.excluded_windows_utc[0][0]
    return stage41.selection_operator.compile_component_discharge_event_selection(
        stage41._payloads(),  # noqa: SLF001
        excluded_event_times_utc=(anchor,),
        excluded_windows_utc=inventory.excluded_windows_utc,
        exclusion_radius_days=freeze.EXCLUSION_RADIUS_DAYS,
    )


def compile_artifacts(
    output: Path = DEFAULT_OUTPUT,
) -> tuple[dict[str, Any], dict[str, Any]]:
    output = Path(output).resolve()
    _require_inside_repo(output)
    protocol_path = output / PROTOCOL_NAME
    protocol = _read_json(protocol_path)
    if protocol != freeze.build_protocol():
        raise ValueError("stage44_protocol_must_be_exactly_frozen")
    protocol_artifact = _artifact(protocol_path)
    inventory_path = REPO_ROOT / freeze.TARGET_EXPOSURE_INVENTORY_PATH
    inventory_report = _read_json(inventory_path)
    if inventory_report != exposure.compile_report():
        raise ValueError("stage44_target_exposure_inventory_not_reproducible")
    inventory_artifact = _artifact(inventory_path)
    selection = compile_selection()
    summary = selection.as_dict()
    if (
        len(selection.candidates) != freeze.EXPECTED_ELIGIBLE_CANDIDATE_COUNT
        or dict(selection.candidate_counts_by_stratum) != freeze.EXPECTED_STRATUM_COUNTS
        or dict(selection.component_gate_candidate_counts) != freeze.EXPECTED_COMPONENT_COUNTS
        or tuple(str(value["event_id"]) for value in selection.selected_events)
        != freeze.EXPECTED_EVENT_IDS
    ):
        raise ValueError("stage44_source_only_selection_not_reproducible")
    candidate_ledger = {
        **selection.as_dict(include_candidates=True),
        "schema": CANDIDATE_SCHEMA,
        "role": "confirmatory_replication_source_cohort_selection",
        "protocol_artifact": protocol_artifact,
        "target_exposure_inventory_artifact": inventory_artifact,
        "target_exposure_boundary": protocol["target_exposure_boundary"],
        "strict_replication_hypothesis": protocol["strict_replication_hypothesis"],
        "network_request_count": 0,
        "target_values_loaded": False,
    }
    candidate_path = output / CANDIDATE_LEDGER_NAME
    _write_json(candidate_path, candidate_ledger)
    candidate_artifact = _artifact(candidate_path)
    manifest = {
        "schema": MANIFEST_SCHEMA,
        "status": STATUS,
        "protocol_artifact": protocol_artifact,
        "target_exposure_inventory_artifact": inventory_artifact,
        "candidate_ledger_artifact": candidate_artifact,
        "eligible_candidate_count": len(selection.candidates),
        "candidate_counts_by_stratum": dict(selection.candidate_counts_by_stratum),
        "component_gate_candidate_counts": dict(selection.component_gate_candidate_counts),
        "selected_event_count": len(selection.selected_events),
        "selected_events": list(selection.selected_events),
        "strict_replication_hypothesis": protocol["strict_replication_hypothesis"],
        "later_target_protocol_boundary": protocol["later_target_protocol_boundary"],
        "data_boundary": {
            "network_request_count": 0,
            "new_source_values_acquired": False,
            "new_target_values_acquired": False,
            "target_request_plan_created": False,
        },
        "claim_boundary": {
            "complete_known_target_exposure_boundary_applied": True,
            "source_only_replication_cohort_frozen": True,
            "stage44_replication_test_executed": False,
            "stage43_pattern_replicated": False,
            "universal_lag_admitted": False,
            "stage30_historical_falsification_overturned": False,
            "non_turbine_component_contrast_admitted": False,
            "causal_or_physical_relation_admitted": False,
            "runtime_operator_admitted": False,
        },
        "selection_summary": summary,
    }
    manifest_path = output / MANIFEST_NAME
    _write_json(manifest_path, manifest)
    return candidate_ledger, manifest


def _require_inside_repo(path: Path) -> None:
    try:
        path.relative_to(REPO_ROOT)
    except ValueError as exc:
        raise ValueError("stage44_output_outside_repo") from exc


def _artifact(path: Path) -> dict[str, object]:
    resolved = path.resolve()
    _require_inside_repo(resolved)
    body = resolved.read_bytes()
    return {
        "path": str(resolved.relative_to(REPO_ROOT)),
        "sha256": hashlib.sha256(body).hexdigest(),
        "size_bytes": len(body),
    }


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_bytes())
    if not isinstance(value, dict):
        raise ValueError("stage44_json_object_required")
    return value


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(_json_bytes(value))


def _json_bytes(value: dict[str, Any]) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode("utf-8")


def main() -> int:
    args = parse_args()
    _, manifest = compile_artifacts(args.output)
    print(args.output / MANIFEST_NAME)
    print(f"status={manifest['status']}")
    print(f"eligible_candidates={manifest['eligible_candidate_count']}")
    print(f"selected_events={manifest['selected_event_count']}")
    print("network_requests=0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
