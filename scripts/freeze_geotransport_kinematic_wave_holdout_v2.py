#!/usr/bin/env python3
"""Freeze the v2 two-system holdout after the v1 CFL reporting erratum."""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

from data_agent.uwm.geospatial_kernel_v2 import load_nwm_zarr_schema, nwm_chunk_url

if __package__:
    from scripts.freeze_geotransport_kinematic_wave_holdout_v1 import (
        CFL_NUMBER,
        CORE_CODE_PATHS,
        DEFAULT_CENTER_SUPPORT,
        DEFAULT_CENTER_TOPOLOGY,
        DEFAULT_JPP_TOPOLOGY,
        DEFAULT_METADATA_ROOT,
        HOUR_COUNT,
        SYSTEM_IDS,
        TARGET_CELL_LENGTH_M,
        TIMESTEP_SECONDS,
        _artifact,
        _iso,
        compile_protocol as compile_v1_protocol,
    )
else:
    from freeze_geotransport_kinematic_wave_holdout_v1 import (
        CFL_NUMBER,
        CORE_CODE_PATHS,
        DEFAULT_CENTER_SUPPORT,
        DEFAULT_CENTER_TOPOLOGY,
        DEFAULT_JPP_TOPOLOGY,
        DEFAULT_METADATA_ROOT,
        HOUR_COUNT,
        SYSTEM_IDS,
        TARGET_CELL_LENGTH_M,
        TIMESTEP_SECONDS,
        _artifact,
        _iso,
        compile_protocol as compile_v1_protocol,
    )


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = REPO_ROOT / (
    "benchmarks/geotransport_v0_1/kinematic_wave_holdout_v2_protocol.json"
)
V1_PROTOCOL = REPO_ROOT / (
    "benchmarks/geotransport_v0_1/kinematic_wave_holdout_v1_protocol.json"
)
V1_FAILURE = REPO_ROOT / (
    "benchmarks/geotransport_v0_1/kinematic_wave_holdout_v1_execution_failure.json"
)
ERRATUM_ADR = REPO_ROOT / (
    "docs/architecture-decisions/"
    "adr-033-kinematic-wave-holdout-v1-cfl-reporting-erratum.md"
)
SCHEMA = "gwm.geotransport.kinematic_wave_holdout_protocol.v2"
INPUT_SCHEMA = "gwm.geotransport.kinematic_wave_holdout_inputs.v2"
ROLLOUT_SCHEMA = "gwm.geotransport.kinematic_wave_holdout_rollout.v2"
OUTCOME_SCHEMA = "gwm.geotransport.kinematic_wave_holdout_outcomes.v2"
SCORE_SCHEMA = "gwm.geotransport.kinematic_wave_holdout_score.v2"
INITIAL_STATE_AT = datetime(2022, 11, 10, 0, tzinfo=timezone.utc)
START = datetime(2022, 11, 10, 1, tzinfo=timezone.utc)
END = datetime(2022, 12, 8, 1, tzinfo=timezone.utc)
INITIAL_TIME_CHUNK = 570
ROLLOUT_TIME_CHUNK = 571
V2_CODE_PATHS = (
    "scripts/freeze_geotransport_kinematic_wave_holdout_v2.py",
    "scripts/acquire_geotransport_kinematic_wave_holdout_v2_inputs.py",
    "scripts/run_geotransport_kinematic_wave_holdout_v2_outcome_free.py",
    "scripts/acquire_geotransport_kinematic_wave_holdout_v2_outcomes.py",
    "scripts/score_geotransport_kinematic_wave_holdout_v2.py",
)
FORBIDDEN_PREEXISTING_PATHS = (
    "data/geotransport_v0_1/kinematic_wave_holdout_v2/inputs",
    "data/geotransport_v0_1/kinematic_wave_holdout_v2/predictions",
    "data/geotransport_v0_1/kinematic_wave_holdout_v2/outcomes",
    "benchmarks/geotransport_v0_1/kinematic_wave_holdout_v2_inputs_report.json",
    "benchmarks/geotransport_v0_1/kinematic_wave_holdout_v2_rollout_report.json",
    "benchmarks/geotransport_v0_1/kinematic_wave_holdout_v2_outcomes_report.json",
    "benchmarks/geotransport_v0_1/kinematic_wave_holdout_v2_score.json",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--metadata-root", type=Path, default=DEFAULT_METADATA_ROOT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def compile_protocol(
    *, metadata_root: Path = DEFAULT_METADATA_ROOT
) -> dict[str, Any]:
    for relative in FORBIDDEN_PREEXISTING_PATHS:
        if (REPO_ROOT / relative).exists():
            raise ValueError(f"kinematic_holdout_v2_preexisting_artifact:{relative}")
    if not V1_PROTOCOL.exists() or not V1_FAILURE.exists() or not ERRATUM_ADR.exists():
        raise ValueError("kinematic_holdout_v2_erratum_lineage_missing")
    schema = load_nwm_zarr_schema(metadata_root)
    if (
        schema.time_chunk_size != HOUR_COUNT
        or schema.time_origin
        + timedelta(hours=((INITIAL_TIME_CHUNK + 1) * HOUR_COUNT) - 1)
        != INITIAL_STATE_AT
        or schema.time_origin
        + timedelta(hours=ROLLOUT_TIME_CHUNK * HOUR_COUNT)
        != START
        or START + timedelta(hours=HOUR_COUNT) != END
    ):
        raise ValueError("kinematic_holdout_v2_nwm_time_contract_mismatch")

    payload = json.loads(
        json.dumps(
            compile_v1_protocol(
                metadata_root=metadata_root,
                center_topology_path=DEFAULT_CENTER_TOPOLOGY,
                jpp_topology_path=DEFAULT_JPP_TOPOLOGY,
                center_support_path=DEFAULT_CENTER_SUPPORT,
            )
        )
    )
    payload["schema"] = SCHEMA
    payload["frozen_at"] = datetime.now(timezone.utc).isoformat()
    payload["scientific_role"] = (
        "outcome-inaccessible two-system replication of the project-owned "
        "branching finite-volume kinematic-wave operator after the v1 "
        "binary64 CFL reporting erratum"
    )
    payload["window"] = {
        "initial_state_valid_at": _iso(INITIAL_STATE_AT),
        "start_inclusive": _iso(START),
        "end_exclusive": _iso(END),
        "hour_count": HOUR_COUNT,
        "time_step": "PT1H",
        "initial_state_time_chunk_index": INITIAL_TIME_CHUNK,
        "forcing_time_chunk_index": ROLLOUT_TIME_CHUNK,
    }
    for system_id in SYSTEM_IDS:
        _retime_system(payload["systems"][system_id])
    payload["operator_lock"]["timestep_seconds"] = TIMESTEP_SECONDS
    payload["operator_lock"]["target_cell_length_m"] = TARGET_CELL_LENGTH_M
    payload["operator_lock"]["cfl_number"] = CFL_NUMBER
    payload["operator_lock"]["cfl_reporting_comparison"] = (
        "configured_CFL_plus_two_binary64_ULPs"
    )
    payload["scoring_lock"]["per_system_execution_gates"] = [
        "every_step_mass_residual_within_numeric_tolerance",
        "every_step_CFL_at_or_below_0.8_plus_two_binary64_ULPs",
        "all_cell_volumes_nonnegative_finite",
        "zero_state_zero_input_identity",
    ]
    payload["protocol_lineage"] = {
        "base_v1_protocol": _artifact(V1_PROTOCOL),
        "v1_execution_failure": _artifact(V1_FAILURE),
        "pre_v2_erratum_decision": _artifact(ERRATUM_ADR),
        "v1_prediction_artifacts_written": False,
        "v1_outcomes_requested": False,
        "v2_dynamic_inputs_requested_before_freeze": False,
        "v2_outcomes_requested_before_freeze": False,
        "allowed_execution_change": (
            "CFL reporting threshold from one to two binary64 ULPs only"
        ),
        "operator_flux_state_or_timestep_changed": False,
        "window_changed_to_unseen_nwm_chunk": True,
    }
    payload["frozen_code"] = {
        path: _artifact(REPO_ROOT / path)
        for path in (*CORE_CODE_PATHS, *V2_CODE_PATHS)
    }
    payload["fixed_evidence"]["v1_protocol"] = _artifact(V1_PROTOCOL)
    payload["fixed_evidence"]["v1_execution_failure"] = _artifact(V1_FAILURE)
    payload["fixed_evidence"]["v1_cfl_erratum_adr"] = _artifact(ERRATUM_ADR)
    payload["data_isolation_at_freeze"] = {
        "initial_state_chunk_570_loaded_for_v2": False,
        "forcing_chunk_571_loaded_for_v2": False,
        "action_values_loaded_for_v2_window": False,
        "outcome_values_loaded_for_v2_window": False,
        "outcome_artifacts_present": False,
    }
    payload["claim_boundary_before_execution"] = {
        "branching_kinematic_operator_implemented": True,
        "v1_execution_gate_passed": False,
        "v2_protocol_frozen": True,
        "v2_dynamic_inputs_acquired": False,
        "v2_outcome_free_predictions_sealed": False,
        "v2_outcomes_acquired": False,
        "v2_scored": False,
        "operator_form_admitted": False,
        "geospatial_kernel_validated": False,
    }
    payload["forbidden_after_freeze"].extend(
        [
            "change_two_ULP_CFL_reporting_adjudication",
            "reuse_v1_dynamic_inputs_or_candidate_window_for_v2",
            "inspect_v2_outcomes_before_both_v2_predictions_are_sealed",
        ]
    )
    return payload


def _retime_system(system: dict[str, Any]) -> None:
    chunks = tuple(int(value) for value in system["feature_chunk_indices"])
    system["initial_state_objects"] = [
        nwm_chunk_url("streamflow", f"{INITIAL_TIME_CHUNK}.{chunk}")
        for chunk in chunks
    ]
    system["forcing_objects"] = [
        nwm_chunk_url("q_lateral", f"{ROLLOUT_TIME_CHUNK}.{chunk}")
        for chunk in chunks
    ]
    system["time_objects"] = [
        nwm_chunk_url("time", str(INITIAL_TIME_CHUNK)),
        nwm_chunk_url("time", str(ROLLOUT_TIME_CHUNK)),
    ]
    action = system["action"]
    query = urlencode(
        {
            "name": action["timeseries"],
            "office": action["office"],
            "begin": _iso(START),
            "end": _iso(END),
            "unit": action["unit"],
            "page-size": "50000",
        }
    )
    action["url"] = (
        "https://cwms-data.usace.army.mil/cwms-data/timeseries?" + query
    )
    outcome = system["outcome"]
    outcome["request_start"] = _iso(START - timedelta(hours=1))
    outcome["request_end"] = _iso(END + timedelta(hours=1))


def main() -> int:
    args = parse_args()
    if args.output.exists():
        raise ValueError("kinematic_holdout_v2_protocol_refuses_overwrite")
    payload = compile_protocol(metadata_root=args.metadata_root)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(args.output)
    print(hashlib.sha256(args.output.read_bytes()).hexdigest())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
