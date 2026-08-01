#!/usr/bin/env python3
"""Freeze the Center Hill history-aware internal-boundary diagnostic."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

if __package__:
    from scripts.freeze_geotransport_center_hill_lead_time_development_protocol import (
        CORE_HORIZONS,
        DIAGNOSTIC_HORIZONS,
        HORIZONS,
    )
    from scripts.run_geotransport_center_hill_v2_d5_full_subnetwork_outcome_free import (
        REPO_ROOT,
    )
else:
    from freeze_geotransport_center_hill_lead_time_development_protocol import (
        CORE_HORIZONS,
        DIAGNOSTIC_HORIZONS,
        HORIZONS,
    )
    from run_geotransport_center_hill_v2_d5_full_subnetwork_outcome_free import (
        REPO_ROOT,
    )


DEFAULT_LEAD_PROTOCOL = REPO_ROOT / (
    "benchmarks/geotransport_v0_1/"
    "center_hill_lead_time_development_protocol.json"
)
DEFAULT_LEAD_REPORT = REPO_ROOT / (
    "benchmarks/geotransport_v0_1/"
    "center_hill_lead_time_development_report.json"
)
DEFAULT_REFERENCE_REPORT = REPO_ROOT / (
    "benchmarks/geotransport_v0_1/"
    "smith_fork_internal_boundary_reference_report.json"
)
DEFAULT_OUTPUT = REPO_ROOT / (
    "benchmarks/geotransport_v0_1/"
    "center_hill_internal_boundary_development_protocol.json"
)
SCHEMA = "gwm.geotransport.center_hill_internal_boundary_development_protocol.v1"
REFERENCE_SCHEMA = "gwm.geotransport.smith_fork_internal_boundary_reference.v1"
LEAD_PROTOCOL_SCHEMA = "gwm.geotransport.center_hill_lead_time_development_protocol.v1"
LEAD_REPORT_SCHEMA = "gwm.geotransport.center_hill_lead_time_development.v1"
SCENARIOS = (
    "observed_internal_boundary",
    "modeled_cut_control",
    "zero_internal_boundary",
)
CORE_CODE_PATHS = (
    "data_agent/uwm/geospatial_kernel_v2/branching_network.py",
    "data_agent/uwm/geospatial_kernel_v2/forecast_closure.py",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lead-protocol", type=Path, default=DEFAULT_LEAD_PROTOCOL)
    parser.add_argument("--lead-report", type=Path, default=DEFAULT_LEAD_REPORT)
    parser.add_argument(
        "--reference-report", type=Path, default=DEFAULT_REFERENCE_REPORT
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def compile_protocol(
    *,
    lead_protocol_path: Path = DEFAULT_LEAD_PROTOCOL,
    lead_report_path: Path = DEFAULT_LEAD_REPORT,
    reference_report_path: Path = DEFAULT_REFERENCE_REPORT,
) -> dict[str, Any]:
    lead_protocol_body, lead_protocol = _load(lead_protocol_path)
    lead_report_body, lead_report = _load(lead_report_path)
    reference_body, reference = _load(reference_report_path)
    _validate_parents(lead_protocol, lead_report, reference)
    linear = reference["linear_reference"]
    return {
        "schema": SCHEMA,
        "status": "frozen_before_internal_boundary_development_execution",
        "frozen_at": datetime.now(timezone.utc).isoformat(),
        "scientific_role": (
            "post-outcome public-development diagnostic of a history-aware "
            "internal observed-boundary observer; not validation"
        ),
        "parent_evidence": {
            "lead_time_protocol": _artifact(lead_protocol_path, lead_protocol_body),
            "lead_time_report": _artifact(lead_report_path, lead_report_body),
            "internal_boundary_reference": _artifact(
                reference_report_path, reference_body
            ),
        },
        "core_code": {
            path: _artifact(REPO_ROOT / path, (REPO_ROOT / path).read_bytes())
            for path in CORE_CODE_PATHS
        },
        "outcome_access_at_freeze": {
            "window_outcomes_previously_accessed": True,
            "candidate_parameters_fitted_from_outlet_targets": False,
            "boundary_geometry_selected_from_outlet_targets": False,
            "horizons_selected_from_current_candidate_errors": False,
            "prospective_or_validation_claim_permitted": False,
        },
        "window_and_horizons": {
            "window": lead_protocol["window"],
            "diagnostic_horizons_hours": list(DIAGNOSTIC_HORIZONS),
            "core_horizons_hours": list(CORE_HORIZONS),
            "all_horizons_hours": list(HORIZONS),
            "reuse_exact_parent_issue_axis": True,
        },
        "gis_compilation_lock": {
            "site_id": reference["site"]["site_id"],
            "boundary_feature_id": reference["site"]["feature_id"],
            "downstream_feature_id": reference["site"]["downstream_feature_id"],
            "full_route_link_length_m": linear["route_link_full_length_m"],
            "central_downstream_fraction": linear["projected_downstream_fraction"],
            "central_downstream_partial_length_m": linear[
                "route_link_downstream_partial_length_m"
            ],
            "downstream_fraction_uncertainty_bracket": linear[
                "uncertainty_bracket_downstream_fraction"
            ],
            "gauge_initial_storage_scaling": "central_downstream_fraction",
            "gauge_q_lateral_support_scaling": (
                "central downstream length fraction; candidate approximation"
            ),
            "snap_distance_m": linear["point_to_line_snap_distance_m"],
            "linear_reference_admitted": False,
            "diagnostic_only": True,
        },
        "operator_lock": {
            "operator": "ObservedInternalBoundaryReplacement",
            "replacement_rule": (
                "observed flow enters the cut boundary reach once; modeled direct "
                "upstream transfer exits as displaced_upstream_outflow_volume_m3"
            ),
            "mass_identity": (
                "initial + action + supported forcing + observed boundary = final "
                "+ outlet + displaced upstream outflow"
            ),
            "internal_boundary_is_generic_forcing": False,
            "partial_network_topology_mutation_after_compile": False,
            "boundary_admitted": False,
        },
        "scenario_lock": {
            "scenarios": list(SCENARIOS),
            "observed_internal_boundary": (
                "outlet local state update plus latest issue-time-available Smith "
                "Fork discharge held as boundary flow across each forecast branch"
            ),
            "modeled_cut_control": (
                "same cut geometry, initial state, outlet update, action, and forcing; "
                "retain compiled modeled upstream transfer"
            ),
            "zero_internal_boundary": (
                "same cut geometry but replace modeled upstream transfer with zero"
            ),
            "missing_smith_fork_observation": (
                "fall back to modeled upstream transfer; no imputation"
            ),
            "post_issue_observation_assimilation": "forbidden",
            "boundary_flow_forecast": (
                "latest issue-time-available Smith Fork observation persisted to all "
                "future intervals in the branch"
            ),
            "cycling_state": (
                "each scenario advances only its registered first-hour result"
            ),
        },
        "information_track": {
            "name": "retrospective_oracle_action_forcing_archive_observation_replay",
            "future_realized_action_used": True,
            "future_retrospective_q_lateral_used": True,
            "future_outlet_target_used_by_model": False,
            "future_smith_fork_observation_used_within_branch": False,
            "observation_operational_vintage_verified": False,
            "operational_forecast_claim_permitted": False,
        },
        "baseline_and_gate_lock": {
            "parent_local_multi_gauge": (
                "reuse hash-verified predictions from the frozen lead-time report"
            ),
            "causal_latency_matched_persistence": "reuse parent baseline values",
            "zero_latency_archive_persistence": "reuse parent diagnostic values",
            "common_complete_case_mask_per_horizon": True,
            "primary_metric": "rmse_m3s",
            "secondary_metrics": ["mae_m3s", "bias_m3s", "nse"],
            "per_core_horizon_gate": (
                "observed-boundary RMSE below modeled-cut, zero-boundary, parent "
                "local multi-gauge, and causal persistence"
            ),
            "development_gate": (
                "all four core horizons plus all scenario mass ledgers; no compensation"
            ),
            "one_hour_can_change_development_gate": False,
        },
        "forbidden_after_freeze": [
            "change_boundary_feature_or_partial_length",
            "select partial-length bracket member from target errors",
            "change_horizons_issue_axis_orcommon mask",
            "fit_boundary scaling or persistence decay from outlet targets",
            "use future Smith Fork observations inside a branch rollout",
            "omit failed horizons",
            "claim the candidate linear reference or observation vintage is admitted",
        ],
        "claim_boundary_before_execution": {
            "internal_boundary_contract_implemented": True,
            "internal_boundary_reference_admitted": False,
            "history_aware_boundary_diagnostic_executed": False,
            "lagged_graph_kernel_fitted": False,
            "forecast_closure_validated": False,
            "geospatial_kernel_validated": False,
        },
    }


def _validate_parents(
    lead_protocol: Mapping[str, Any],
    lead_report: Mapping[str, Any],
    reference: Mapping[str, Any],
) -> None:
    if (
        lead_protocol.get("schema") != LEAD_PROTOCOL_SCHEMA
        or lead_protocol.get("status")
        != "frozen_before_lead_time_development_execution"
        or lead_report.get("schema") != LEAD_REPORT_SCHEMA
        or lead_report.get("status")
        != "public_development_lead_time_diagnostic_complete"
        or (lead_report.get("claim_boundary") or {}).get(
            "geospatial_kernel_validated"
        )
        is not False
        or reference.get("schema") != REFERENCE_SCHEMA
        or reference.get("status")
        != "candidate_internal_boundary_reference_compiled"
        or (reference.get("claim_boundary") or {}).get(
            "linear_reference_admitted"
        )
        is not False
        or (reference.get("quality_gates") or {}).get(
            "point_to_line_snap_distance_below_30m"
        )
        is not False
    ):
        raise ValueError("internal_boundary_protocol_parent_evidence_invalid")


def _load(path: Path) -> tuple[bytes, dict[str, Any]]:
    body = path.read_bytes()
    return body, json.loads(body)


def _artifact(path: Path, body: bytes) -> dict[str, Any]:
    return {
        "path": _display(path),
        "sha256": hashlib.sha256(body).hexdigest(),
        "size_bytes": len(body),
    }


def _display(path: Path) -> str:
    resolved = path.resolve()
    try:
        return resolved.relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return resolved.as_posix()


def _json_body(payload: Mapping[str, Any]) -> bytes:
    return (
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")


def main() -> int:
    args = parse_args()
    if args.output.exists():
        raise ValueError("internal_boundary_protocol_refuses_overwrite")
    protocol = compile_protocol(
        lead_protocol_path=args.lead_protocol,
        lead_report_path=args.lead_report,
        reference_report_path=args.reference_report,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(_json_body(protocol))
    print(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
