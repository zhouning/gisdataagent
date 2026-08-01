#!/usr/bin/env python3
"""Compile Stage 41 source-only component-discharge event gates."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from data_agent.uwm.geospatial_kernel_v2 import (  # noqa: E402
    public_component_discharge_event_evidence as evidence,
)
from scripts import (  # noqa: E402
    freeze_geotransport_stage41_component_discharge_event_protocol as freeze,
)

DEFAULT_DATA_ROOT = REPO_ROOT / evidence.STAGE41_ROOT
DEFAULT_LEDGER_OUTPUT = DEFAULT_DATA_ROOT / (
    "component_discharge_event_evidence_ledger.json"
)
DEFAULT_OUTPUT = REPO_ROOT / (
    "benchmarks/geotransport_v0_1/"
    "stage41_component_discharge_event_gates.json"
)
SCHEMA = "gwm.geotransport.stage41_component_discharge_event_gates.v1"
STATUS = evidence.STATUS
FROZEN_HASHES = {
    "data_agent/uwm/geospatial_kernel_v2/component_discharge_event_selection.py": (
        "f3f72959befaf70384994f9a47265ac6cd87e1fa63824fbf9879c7bf37784d04"
    ),
    (
        "data_agent/uwm/geospatial_kernel_v2/"
        "public_component_discharge_event_evidence.py"
    ): "a5566c33790f1d8b3f0e6b1865eb2aca0a250732766550c38947fa3916f1bd2a",
    (
        "scripts/freeze_geotransport_stage41_"
        "component_discharge_event_protocol.py"
    ): "84335dd7fdbcb6caa69fb319b5c2525cb126d1891d28810571dcd5bb1aa3908a",
    (
        "scripts/compile_geotransport_stage41_"
        "component_discharge_events.py"
    ): "7e4b26113692a3eebb8f0353a7ca96c08ec182d1cccfad21ef64a8b468734190",
    (
        "data_agent/test_geospatial_kernel_"
        "component_discharge_event_selection.py"
    ): "6433586c74d99c0133e94aff3174c35c956c7957f16ead27ac8b72156289252a",
    (
        "data_agent/test_freeze_geotransport_stage41_"
        "component_discharge_event_protocol.py"
    ): "cbcc48383366d9708b894ca311c9735aa9ea90e5c12f9b4bdbc3259a542c8292",
    (
        "data_agent/test_geospatial_kernel_public_"
        "component_discharge_event_evidence.py"
    ): "147d204ce48c8f35e71a326a0e505e48a9e8572a903ddf8c42042e415986dbe2",
    evidence.PROTOCOL_PATH: evidence.EXPECTED_PROTOCOL_SHA256,
    evidence.CANDIDATE_LEDGER_PATH: evidence.EXPECTED_CANDIDATE_LEDGER_SHA256,
    evidence.MANIFEST_PATH: evidence.EXPECTED_MANIFEST_SHA256,
    freeze.STAGE40_LEDGER_PATH: freeze.FROZEN_HASHES[
        freeze.STAGE40_LEDGER_PATH
    ],
    freeze.STAGE40_GATES_PATH: freeze.FROZEN_HASHES[
        freeze.STAGE40_GATES_PATH
    ],
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--ledger-output", type=Path, default=DEFAULT_LEDGER_OUTPUT
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    ledger = evidence.compile_public_component_discharge_event_evidence()
    ledger_artifact = _write_artifact(args.ledger_output, ledger.as_dict())
    report = compile_report(ledger=ledger, ledger_artifact=ledger_artifact)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(_json_bytes(report))
    print(args.output)
    print(f"status={report['status']}")
    print(f"gates={sum(report['gates'].values())}/{len(report['gates'])}")
    return 0 if report["all_gates_passed"] else 1


def compile_report(
    *,
    ledger: evidence.PublicComponentDischargeEventEvidenceLedger | None = None,
    ledger_artifact: dict[str, object] | None = None,
) -> dict[str, Any]:
    if ledger is None:
        ledger = evidence.compile_public_component_discharge_event_evidence()
    ledger_report = ledger.as_dict()
    if ledger_artifact is None:
        ledger_artifact = _memory_artifact(
            DEFAULT_LEDGER_OUTPUT, ledger_report
        )
    frozen = _frozen_hash_report(FROZEN_HASHES)
    selection = ledger.selection
    events = selection.selected_events
    decision = ledger_report["decision"]
    protocol = _read_json(REPO_ROOT / evidence.PROTOCOL_PATH)
    refusals = _refusal_control(ledger)
    gates = {
        "all_twelve_stage40_and_stage41_artifacts_match": all(
            value["matches"] for value in frozen.values()
        ),
        "stage41_protocol_is_exactly_bound": (
            ledger.protocol_artifact["sha256"]
            == evidence.EXPECTED_PROTOCOL_SHA256
        ),
        "stage41_candidate_ledger_is_exactly_bound": (
            ledger.candidate_ledger_artifact["sha256"]
            == evidence.EXPECTED_CANDIDATE_LEDGER_SHA256
        ),
        "stage41_event_manifest_is_exactly_bound": (
            ledger.event_selection_manifest_artifact["sha256"]
            == evidence.EXPECTED_MANIFEST_SHA256
        ),
        "stage40_ledger_and_gates_are_preserved": (
            ledger.stage40_ledger_artifact["sha256"]
            == freeze.FROZEN_HASHES[freeze.STAGE40_LEDGER_PATH]
            and ledger.stage40_gates_artifact["sha256"]
            == freeze.FROZEN_HASHES[freeze.STAGE40_GATES_PATH]
        ),
        "all_twenty_stage40_source_artifacts_are_preserved": (
            len(ledger.source_artifacts) == 20
            and len(
                {str(value["sha256"]) for value in ledger.source_artifacts}
            )
            == 20
        ),
        "all_43825_hours_support_exact_four_component_sums": (
            selection.total_value_count == 43_825
            and selection.synchronized_total_derivation_admissible is True
        ),
        "derived_total_is_source_only_and_not_fully_persisted": (
            decision["full_derived_total_series_persisted"] is False
            and protocol["frozen_total_derivation"]["derived_total_role"]
            == "source_only_event_selector"
        ),
        "candidate_window_uses_exact_73_hour_support": all(
            value["inclusive_total_value_count"] == 73 for value in events
        ),
        "all_twenty_exclusion_intervals_are_applied": (
            selection.excluded_interval_count == 20
        ),
        "thirty_day_window_overlap_exclusion_is_frozen": (
            protocol["predeclared_event_selection"][
                "prior_outcome_exclusion_radius_days"
            ]
            == 30
            and protocol["predeclared_event_selection"][
                "candidate_window_must_not_overlap_exclusion_interval"
            ]
            is True
        ),
        "eligible_candidate_count_is_exact": (
            len(selection.candidates) == 2_547
        ),
        "candidate_stratum_counts_are_exact": (
            selection.candidate_counts_by_stratum
            == (
                ("high_increase", 51),
                ("high_decrease", 77),
                ("low_increase", 1_262),
                ("low_decrease", 1_157),
            )
        ),
        "four_events_are_selected_in_frozen_stratum_order": (
            tuple(value["selection_stratum"] for value in events)
            == evidence.selection_operator.STRATUM_ORDER
        ),
        "four_exact_event_ids_are_preserved": (
            tuple(str(value["event_id"]) for value in events)
            == evidence.EXPECTED_EVENT_IDS
        ),
        "selected_events_are_at_least_180_days_apart": (
            _events_are_separated(events)
        ),
        "all_selected_steps_exceed_50_m3s": all(
            float(value["absolute_total_step_m3s"]) >= 50.0
            for value in events
        ),
        "all_selected_ranges_exceed_100_m3s": all(
            float(value["total_window_range_m3s"]) >= 100.0
            for value in events
        ),
        "all_selected_events_pass_excitation_identifiability": all(
            value["release_excitation_identifiability"][
                "blind_response_test_admissible"
            ]
            is True
            for value in events
        ),
        "component_specific_candidate_counts_are_exact": (
            selection.component_gate_candidate_counts
            == (
                ("orifice", 0),
                ("sluice", 0),
                ("spillway", 0),
                ("turbine", 2_542),
            )
        ),
        "all_selected_steps_are_turbine_only": all(
            value["active_step_components"] == ["turbine"]
            and value["dominant_step_component"] == "turbine"
            for value in events
        ),
        "non_turbine_component_contrast_is_rejected": (
            decision["non_turbine_component_contrast_admitted"] is False
        ),
        "quality_codes_are_not_approval_semantics": (
            decision["quality_code_approval_semantics_admitted"] is False
        ),
        "source_only_total_discharge_events_are_admitted": (
            decision["source_only_total_discharge_events_admitted"] is True
            and decision["source_only_total_discharge_event_count"] == 4
        ),
        "target_functional_is_frozen_before_new_values": (
            decision["target_functional_frozen"] is True
            and protocol["blinding_protocol"][
                "target_functional_frozen_before_new_target_values"
            ]
            is True
        ),
        "no_new_network_requests_were_made": (
            decision["new_network_request_count"] == 0
        ),
        "no_downstream_or_tributary_values_were_acquired": (
            decision["downstream_or_tributary_values_acquired"] is False
        ),
        "observed_downstream_response_remains_unadmitted": (
            decision["observed_downstream_response_admitted"] is False
        ),
        "gate_commands_remain_rejected": (
            decision["gate_commands_admitted"] is False
        ),
        "human_actions_remain_rejected": (
            decision["human_actions_admitted"] is False
        ),
        "causal_interventions_remain_rejected": (
            decision["causal_interventions_admitted"] is False
        ),
        "physical_response_time_remains_rejected": (
            decision["physical_response_time_admitted"] is False
        ),
        "runtime_operators_remain_rejected": (
            decision["runtime_operators_admitted"] is False
        ),
        "fresh_approval_is_required_for_target_acquisition": (
            decision["fresh_approval_required_for_target_acquisition"] is True
        ),
        "eight_typed_refusal_controls_fail_closed": all(refusals.values()),
        "public_provenance_is_content_addressed": (
            ledger.provenance_id.startswith(
                "center-hill-component-discharge-events:"
            )
            and len(ledger.provenance_id.rsplit(":", 1)[1]) == 64
        ),
        "stage41_ledger_is_content_addressed": (
            len(str(ledger_artifact["sha256"])) == 64
            and int(ledger_artifact["size_bytes"]) > 0
        ),
    }
    return {
        "schema": SCHEMA,
        "compiled_at": datetime.now(UTC).isoformat(),
        "status": STATUS,
        "frozen_artifacts": frozen,
        "stage41_ledger_artifact": ledger_artifact,
        "source_summary": {
            "inherited_source_artifact_count": len(ledger.source_artifacts),
            "new_network_request_count": 0,
            "total_hour_count": selection.total_value_count,
        },
        "candidate_summary": {
            "eligible_candidate_count": len(selection.candidates),
            "candidate_counts_by_stratum": dict(
                selection.candidate_counts_by_stratum
            ),
            "component_gate_candidate_counts": dict(
                selection.component_gate_candidate_counts
            ),
        },
        "selected_events": list(events),
        "refusal_controls": refusals,
        "gates": gates,
        "all_gates_passed": all(gates.values()),
        "decision": decision,
    }


def _events_are_separated(events: tuple[dict[str, object], ...]) -> bool:
    from datetime import datetime as parse_datetime

    times = [
        parse_datetime.fromisoformat(
            str(value["step_time_utc"]).replace("Z", "+00:00")
        )
        for value in events
    ]
    return all(
        abs(left - right).days >= 180
        for index, left in enumerate(times)
        for right in times[index + 1 :]
    )


def _refusal_control(
    ledger: evidence.PublicComponentDischargeEventEvidenceLedger,
) -> dict[str, bool]:
    calls = {
        "quality_approval": ledger.require_quality_approval_semantics,
        "non_turbine_contrast": ledger.require_non_turbine_component_contrast,
        "gate_command": ledger.require_gate_command,
        "human_action": ledger.require_human_action,
        "downstream_response": ledger.require_observed_downstream_response,
        "causal_intervention": ledger.require_causal_intervention,
        "physical_response_time": ledger.require_physical_response_time,
        "runtime_operator": ledger.promote_to_runtime_operator,
    }
    result = {}
    for key, call in calls.items():
        try:
            call()
        except ValueError:
            result[key] = True
        else:
            result[key] = False
    return result


def _frozen_hash_report(
    expected: dict[str, str],
) -> dict[str, dict[str, object]]:
    return {
        path: {
            "expected_sha256": digest,
            "actual_sha256": _sha256(REPO_ROOT / path),
            "matches": _sha256(REPO_ROOT / path) == digest,
        }
        for path, digest in expected.items()
    }


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_artifact(path: Path, value: dict[str, object]) -> dict[str, object]:
    body = _json_bytes(value)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(body)
    return _artifact(path, body)


def _memory_artifact(path: Path, value: dict[str, object]) -> dict[str, object]:
    return _artifact(path, _json_bytes(value))


def _artifact(path: Path, body: bytes) -> dict[str, object]:
    return {
        "path": str(path.resolve().relative_to(REPO_ROOT)),
        "sha256": hashlib.sha256(body).hexdigest(),
        "size_bytes": len(body),
    }


def _json_bytes(value: dict[str, object]) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode("utf-8")


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_bytes())
    if not isinstance(value, dict):
        raise ValueError("stage41_gate_json_object_required")
    return value


if __name__ == "__main__":
    raise SystemExit(main())
