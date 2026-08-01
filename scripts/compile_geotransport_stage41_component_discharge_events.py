#!/usr/bin/env python3
"""Compile the offline Stage 41 source-only component-discharge events."""

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

from data_agent.uwm.geospatial_kernel_v2 import (  # noqa: E402
    component_discharge_event_selection as selection_operator,
)
from data_agent.uwm.geospatial_kernel_v2 import (  # noqa: E402
    public_component_discharge_value_support as stage40_evidence,
)
from scripts import (  # noqa: E402
    freeze_geotransport_stage41_component_discharge_event_protocol as freeze,
)
from scripts import (  # noqa: E402
    plan_geotransport_stage39_component_discharge_values as planner,
)

DEFAULT_OUTPUT = REPO_ROOT / freeze.STAGE41_ROOT
PROTOCOL_NAME = "protocol.json"
CANDIDATE_LEDGER_NAME = "component_total_event_candidate_ledger.json"
MANIFEST_NAME = "event_selection_manifest.json"
CANDIDATE_SCHEMA = "gwm.geotransport.stage41_component_event_candidates.v1"
MANIFEST_SCHEMA = "gwm.geotransport.stage41_component_event_selection.v1"
STATUS = "stage41_component_total_discharge_events_frozen_source_only"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def compile_selection() -> selection_operator.ComponentDischargeEventSelection:
    return selection_operator.compile_component_discharge_event_selection(
        _payloads(),
        excluded_event_times_utc=(
            freeze.PRIOR_OUTCOME_EVENT_TIMES_UTC
            + freeze.TARGET_EXPOSED_EVENT_TIMES_UTC
        ),
        excluded_windows_utc=freeze.PRIOR_OUTCOME_WINDOWS_UTC,
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
        raise ValueError("stage41_protocol_must_be_exactly_frozen")
    protocol_artifact = _artifact(protocol_path)
    compiled = compile_selection()
    summary = compiled.as_dict()
    diagnostic = protocol["source_only_development_diagnostic"]
    if (
        summary["eligible_candidate_count"]
        != diagnostic["eligible_total_candidate_counts_by_radius"]["30"]
        or summary["component_gate_candidate_counts"]
        != {"orifice": 0, "sluice": 0, "spillway": 0, "turbine": 2_542}
    ):
        raise ValueError("stage41_source_diagnostic_not_reproducible")
    candidate_ledger = {
        **compiled.as_dict(include_candidates=True),
        "schema": CANDIDATE_SCHEMA,
        "protocol_artifact": protocol_artifact,
        "selection_protocol": protocol["predeclared_event_selection"],
        "source_gate": protocol["frozen_source_gate"],
        "network_request_count": 0,
        "downstream_or_tributary_values_loaded": False,
    }
    candidate_path = output / CANDIDATE_LEDGER_NAME
    _write_json(candidate_path, candidate_ledger)
    candidate_artifact = _artifact(candidate_path)
    stage40 = stage40_evidence.compile_public_component_discharge_value_support()
    stage40_artifacts = {
        "ledger": _artifact(REPO_ROOT / freeze.STAGE40_LEDGER_PATH),
        "gates": _artifact(REPO_ROOT / freeze.STAGE40_GATES_PATH),
    }
    manifest = {
        "schema": MANIFEST_SCHEMA,
        "status": STATUS,
        "protocol_artifact": protocol_artifact,
        "candidate_ledger_artifact": candidate_artifact,
        "stage40_artifacts": stage40_artifacts,
        "inherited_source_artifacts": list(stage40.source_artifacts),
        "inherited_source_artifact_count": len(stage40.source_artifacts),
        "total_derivation": summary["total_derivation"],
        "excluded_interval_count": summary["excluded_interval_count"],
        "eligible_candidate_count": summary["eligible_candidate_count"],
        "candidate_counts_by_stratum": summary["candidate_counts_by_stratum"],
        "component_gate_candidate_counts": summary[
            "component_gate_candidate_counts"
        ],
        "selected_event_count": summary["selected_event_count"],
        "selected_events": summary["selected_events"],
        "target_functional": protocol["predeclared_target_functional"],
        "data_boundary": {
            "network_request_count": 0,
            "new_source_values_acquired": False,
            "new_downstream_or_tributary_values_acquired": False,
            "private_or_workspace_data_requested": False,
        },
        "claim_boundary": summary["claim_boundary"],
    }
    manifest_path = output / MANIFEST_NAME
    _write_json(manifest_path, manifest)
    return candidate_ledger, manifest


def _payloads() -> dict[str, tuple[dict[str, object], ...]]:
    source_root = REPO_ROOT / planner.freeze.STAGE39_ROOT
    result: dict[str, list[dict[str, object]]] = {
        component: []
        for component in selection_operator.catalog.EXPECTED_COMPONENTS
    }
    for source in planner.compile_plan()["sources"]:
        component = str(source["component"])
        result[component].append(
            _read_json(source_root / str(source["output_name"]))
        )
    return {component: tuple(payloads) for component, payloads in result.items()}


def _require_inside_repo(path: Path) -> None:
    try:
        path.relative_to(REPO_ROOT)
    except ValueError as exc:
        raise ValueError("stage41_output_outside_repo") from exc


def _artifact(path: Path) -> dict[str, object]:
    resolved = path.resolve()
    _require_inside_repo(resolved)
    body = resolved.read_bytes()
    return {
        "path": str(resolved.relative_to(REPO_ROOT)),
        "sha256": hashlib.sha256(body).hexdigest(),
        "size_bytes": len(body),
    }


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(_json_bytes(value))


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_bytes())
    if not isinstance(value, dict):
        raise ValueError("stage41_json_object_required")
    return value


def _json_bytes(value: dict[str, Any]) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode("utf-8")


def main() -> int:
    args = parse_args()
    _, manifest = compile_artifacts(args.output)
    path = args.output / MANIFEST_NAME
    print(path)
    print(f"status={manifest['status']}")
    print(f"eligible_candidates={manifest['eligible_candidate_count']}")
    print(f"selected_events={manifest['selected_event_count']}")
    print("network_requests=0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
