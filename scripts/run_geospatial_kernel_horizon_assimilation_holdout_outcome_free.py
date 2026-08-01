#!/usr/bin/env python3
"""Fetch issue-only observations and seal chronological horizon rollouts."""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np

from data_agent.uwm.geospatial_kernel_v2 import (
    ActionBoundaryFlux,
    BranchingManningNetworkTransportOperator,
    BranchingNetworkTransportConfig,
    ForcingFlux,
    ReachForcingSupport,
    StockState,
)
from data_agent.uwm.geospatial_kernel_v2.horizon_assimilation_policy import (
    HORIZON_ASSIMILATION_MODES,
    HORIZON_ASSIMILATION_SUPPORTED_HORIZONS_HOURS,
    HorizonAssimilationPolicy,
)
from data_agent.uwm.geospatial_kernel_v2.horizon_assimilation_rollout import (
    execute_horizon_assimilation_issue,
)

if __package__:
    from scripts import (
        acquire_geospatial_kernel_horizon_assimilation_holdout_static_inputs as static,
    )
    from scripts import (
        freeze_geospatial_kernel_horizon_assimilation_holdout_protocol as freeze,
    )
    from scripts import (
        plan_geospatial_kernel_horizon_assimilation_holdout_inputs as frozen_plan,
    )
    from scripts.acquire_geotransport_center_hill_v2_d3_inputs import _opener
    from scripts.acquire_geotransport_v2_blind_validation_outcomes import (
        _fetch_usgs,
    )
    from scripts.evaluate_geospatial_kernel_issue_state_assimilation import (
        _mainstem_ids,
    )
    from scripts.run_geotransport_center_hill_v2_d5_full_subnetwork_outcome_free import (
        _geometry,
        _network,
        _read_npy,
    )
else:
    import acquire_geospatial_kernel_horizon_assimilation_holdout_static_inputs as static
    import freeze_geospatial_kernel_horizon_assimilation_holdout_protocol as freeze
    import plan_geospatial_kernel_horizon_assimilation_holdout_inputs as frozen_plan
    from acquire_geotransport_center_hill_v2_d3_inputs import _opener
    from acquire_geotransport_v2_blind_validation_outcomes import _fetch_usgs
    from evaluate_geospatial_kernel_issue_state_assimilation import _mainstem_ids
    from run_geotransport_center_hill_v2_d5_full_subnetwork_outcome_free import (
        _geometry,
        _network,
        _read_npy,
    )

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PROTOCOL = freeze.DEFAULT_OUTPUT
DEFAULT_FROZEN_PLAN = frozen_plan.DEFAULT_OUTPUT
DEFAULT_STATIC_REPORT = static.DEFAULT_REPORT
DEFAULT_OUTPUT = REPO_ROOT / (
    "data/geotransport_v0_1/"
    "geospatial_kernel_horizon_assimilation_holdout/outcome_free_rollout"
)
DEFAULT_REPORT = REPO_ROOT / (
    "benchmarks/geotransport_v0_1/"
    "geospatial_kernel_horizon_assimilation_holdout_rollout_report.json"
)
SCHEMA = "gwm.geotransport.horizon_assimilation_holdout_rollout.v1"
ISSUE_SCHEMA = "gwm.geotransport.horizon_assimilation_holdout_joint_issue.v1"
CFS_TO_M3S = 0.028316846592
NOMINAL_CONFORMANCE_ABSOLUTE_TOLERANCE_M3S = 1e-12


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--protocol", type=Path, default=DEFAULT_PROTOCOL)
    parser.add_argument("--frozen-plan", type=Path, default=DEFAULT_FROZEN_PLAN)
    parser.add_argument("--static-report", type=Path, default=DEFAULT_STATIC_REPORT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--proxy", default="http://127.0.0.1:7897")
    parser.add_argument("--timeout-seconds", type=float, default=180.0)
    parser.add_argument("--retries", type=int, default=4)
    return parser.parse_args()


def prepare_execution(
    *,
    protocol_path: Path = DEFAULT_PROTOCOL,
    frozen_plan_path: Path = DEFAULT_FROZEN_PLAN,
    static_report_path: Path = DEFAULT_STATIC_REPORT,
) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    protocol_body, protocol = _load_json(protocol_path)
    plan_body, plan = _load_json(frozen_plan_path)
    static_body, static_report = _load_json(static_report_path)
    frozen_plan._validate_protocol(protocol)
    rebuilt_plan = frozen_plan.compile_holdout_input_plan(
        protocol_path=protocol_path,
        generated_at=frozen_plan._parse_time(plan.get("generated_at")),
    )
    if plan != rebuilt_plan:
        raise ValueError("horizon_holdout_rollout_frozen_plan_invalid")
    _validate_static_report(
        static_report,
        protocol_body=protocol_body,
        plan_body=plan_body,
    )
    policy = HorizonAssimilationPolicy.from_dict(protocol["candidate_lock"]["policy"])
    if protocol["candidate_lock"]["policy_sha256"] != hashlib.sha256(
        _canonical_json(policy.as_dict())
    ).hexdigest():
        raise ValueError("horizon_holdout_rollout_policy_identity_mismatch")

    contexts: dict[str, dict[str, Any]] = {}
    for system_id in freeze.SYSTEM_IDS:
        lock = protocol["systems"][system_id]
        inputs = static_report["systems"][system_id]
        topology_body = _read_verified(lock["topology_report"])
        topology = json.loads(topology_body)
        network_body = _read_verified(topology["artifacts"]["full_subnetwork"])
        network_payload = json.loads(network_body)
        network = _network(network_payload["network"])
        mainstem_ids, mainstem_artifact = _mainstem_ids(
            system_id=system_id,
            topology=topology,
            network_payload=network_payload,
            network=network,
        )
        arrays = {
            name: _read_npy(descriptor)
            for name, descriptor in inputs["decoded_arrays"].items()
        }
        feature_ids = tuple(int(value) for value in arrays["feature_ids"])
        initial_storage = np.asarray(arrays["initial_storage_m3"], dtype=float)
        q_lateral = np.asarray(arrays["q_lateral_m3s"], dtype=float)
        timestamps = tuple(str(value) for value in arrays["forcing_timestamps_utc"])
        if (
            feature_ids != network.feature_ids
            or initial_storage.shape != (len(feature_ids),)
            or q_lateral.shape != (freeze.HOUR_COUNT, len(feature_ids))
            or timestamps
            != tuple(
                _iso(freeze.START + timedelta(hours=index))
                for index in range(freeze.HOUR_COUNT)
            )
        ):
            raise ValueError(f"horizon_holdout_rollout_{system_id}_static_axis_invalid")
        route_link = topology["artifacts"]["route_link_subset"]
        route_link_body = _read_verified(route_link)
        geometry = _geometry(REPO_ROOT / route_link["path"], network, route_link_body)
        reference_floor = np.maximum(
            np.asarray(network.effective_lengths_m, dtype=float)
            * np.asarray(geometry.bottom_width_m, dtype=float)
            * 0.01,
            1.0,
        )
        reference_storage = np.where(
            initial_storage > 0.0,
            initial_storage,
            reference_floor,
        )
        terminal_fraction = float(lock["forcing_support"]["partial_terminal_reach_fraction"])
        forcing_support = ReachForcingSupport(
            feature_ids=feature_ids,
            coverage_fractions=tuple(
                terminal_fraction if value == network.outlet_feature_id else 1.0
                for value in feature_ids
            ),
            support_method=str(lock["forcing_support"]["partial_terminal_reach_method"]),
            provenance_id=f"horizon-holdout:{system_id}:forcing-support",
            evidence_level="derived",
            admitted_as_spatial_support=True,
        )
        contexts[system_id] = {
            "lock": lock,
            "network": network,
            "geometry": geometry,
            "feature_ids": feature_ids,
            "mainstem_ids": mainstem_ids,
            "mainstem_artifact": mainstem_artifact,
            "reference_storage": tuple(float(value) for value in reference_storage),
            "q_lateral": q_lateral,
            "actions": _parse_actions(_read_verified(inputs["action_values"])),
            "forcing_support": forcing_support,
            "operator": BranchingManningNetworkTransportOperator(
                network,
                BranchingNetworkTransportConfig(
                    timestep_seconds=freeze.TIMESTEP_SECONDS,
                    integration_substep_seconds=freeze.SUBSTEP_SECONDS,
                    operator_form_admitted=True,
                    allow_unadmitted_components_for_diagnostics=True,
                ),
            ),
            "state": StockState(
                values=tuple(float(value) for value in initial_storage),
                unit="m3",
                provenance_id=(
                    f"horizon-holdout:{system_id}:initial:"
                    f"{inputs['decoded_arrays']['initial_storage_m3']['sha256']}"
                ),
            ),
            "request_by_issue": {
                value["issue_time_utc"]: value
                for value in plan["systems"][system_id]["issue_observation_requests"]
            },
        }
    preparation = {
        "protocol_body": protocol_body,
        "plan_body": plan_body,
        "static_body": static_body,
        "protocol": protocol,
        "plan": plan,
        "static_report": static_report,
        "policy": policy,
    }
    return preparation, contexts


def execute_joint_issue(
    *,
    issue_index: int,
    issue_time: datetime,
    policy: HorizonAssimilationPolicy,
    contexts: Mapping[str, Mapping[str, Any]],
    observations: Mapping[str, Mapping[str, Any]],
) -> tuple[dict[str, Any], dict[str, StockState]]:
    systems: dict[str, Any] = {}
    next_states: dict[str, StockState] = {}
    for system_id in freeze.SYSTEM_IDS:
        context = contexts[system_id]
        observation = observations[system_id]
        value = observation.get("value_m3s")
        rollout = execute_horizon_assimilation_issue(
            system_id=system_id,
            policy=policy,
            network=context["network"],
            geometry=context["geometry"],
            modeled_stock=context["state"],
            reference_storage_m3=context["reference_storage"],
            mainstem_feature_ids=context["mainstem_ids"],
            reference_time=issue_time - timedelta(hours=1),
            issue_time=issue_time,
            issue_observed_outlet_m3s=value,
            observation_available_at=issue_time if value is not None else None,
            action_release_m3s_by_step=tuple(
                context["actions"][issue_time + timedelta(hours=offset)]
                for offset in range(12)
            ),
            q_lateral_m3s_by_step=tuple(
                tuple(float(value) for value in context["q_lateral"][issue_index + offset])
                for offset in range(12)
            ),
            forcing_support=context["forcing_support"],
            timestep_seconds=freeze.TIMESTEP_SECONDS,
            integration_substep_seconds=freeze.SUBSTEP_SECONDS,
        )
        next_state, baseline_predictions = _advance_nominal_interval(
            context=context,
            issue_index=issue_index,
            issue_time=issue_time,
        )
        nominal = rollout.mode_rollout("nominal")
        errors = {
            str(horizon): abs(
                nominal.prediction_for_horizon(horizon)
                - baseline_predictions[horizon]
            )
            for horizon in HORIZON_ASSIMILATION_SUPPORTED_HORIZONS_HOURS
        }
        if max(errors.values()) > NOMINAL_CONFORMANCE_ABSOLUTE_TOLERANCE_M3S:
            raise RuntimeError(
                f"horizon_holdout_rollout_{system_id}_nominal_conformance_failed"
            )
        systems[system_id] = {
            "observation": dict(observation),
            "rollout": rollout.as_dict(),
            "nominal_canonical_conformance": {
                "maximum_absolute_error_m3s": max(errors.values()),
                "absolute_tolerance_m3s": NOMINAL_CONFORMANCE_ABSOLUTE_TOLERANCE_M3S,
                "passed": True,
            },
        }
        next_states[system_id] = next_state
    return systems, next_states


def run_chronological_holdout(
    *,
    protocol_path: Path = DEFAULT_PROTOCOL,
    frozen_plan_path: Path = DEFAULT_FROZEN_PLAN,
    static_report_path: Path = DEFAULT_STATIC_REPORT,
    output_root: Path = DEFAULT_OUTPUT,
    proxy: str = "http://127.0.0.1:7897",
    timeout_seconds: float = 180.0,
    retries: int = 4,
) -> tuple[bytes, dict[str, Any]]:
    preparation, contexts = prepare_execution(
        protocol_path=protocol_path,
        frozen_plan_path=frozen_plan_path,
        static_report_path=static_report_path,
    )
    issue_times = tuple(
        frozen_plan._parse_time(value)
        for value in preparation["protocol"]["window"]["issue_times_utc"]
    )
    existing_seals = sorted((output_root / "issues").glob("*/joint_issue.json"))
    if existing_seals:
        raise ValueError("horizon_holdout_rollout_partial_recovery_not_permitted")
    opener = _opener(proxy)
    rows: list[dict[str, object]] = []
    issue_artifacts: list[dict[str, Any]] = []
    previous_seal_sha256: str | None = None
    remote_request_count = 0
    reused_request_count = 0

    for ordinal, (issue_index, issue_time) in enumerate(
        zip(freeze.ISSUE_INDICES, issue_times, strict=True)
    ):
        issue_key = _iso(issue_time)
        issue_dir = output_root / f"issues/{issue_index:03d}"
        observations: dict[str, dict[str, Any]] = {}
        raw_descriptors: dict[str, dict[str, Any]] = {}
        for system_id in freeze.SYSTEM_IDS:
            request = contexts[system_id]["request_by_issue"].get(issue_key)
            if request is None:
                raise ValueError("horizon_holdout_rollout_issue_request_missing")
            raw_path = issue_dir / f"{system_id}_issue_observation.json"
            if raw_path.exists():
                body = raw_path.read_bytes()
                retrieval = {
                    "url": request["url"],
                    "retrieval_mode": "verified_current_issue_retry_reuse",
                }
                reused_request_count += 1
            else:
                body, retrieval = _fetch_usgs(
                    request["url"],
                    opener=opener,
                    timeout_seconds=timeout_seconds,
                    retries=retries,
                    maximum_bytes=1_000_000,
                )
                issue_dir.mkdir(parents=True, exist_ok=True)
                raw_path.write_bytes(body)
                remote_request_count += 1
            observations[system_id] = _parse_exact_issue_observation(
                json.loads(body),
                site_id=str(request["site_id"]),
                issue_time=issue_time,
            )
            raw_descriptors[system_id] = {
                **retrieval,
                **_artifact(raw_path, body),
            }

        systems, next_states = execute_joint_issue(
            issue_index=issue_index,
            issue_time=issue_time,
            policy=preparation["policy"],
            contexts=contexts,
            observations=observations,
        )
        for system_id in freeze.SYSTEM_IDS:
            state_path = issue_dir / f"{system_id}_next_canonical_state.npy"
            _write_npy(state_path, np.asarray(next_states[system_id].values, dtype=np.float64))
            systems[system_id]["issue_observation_raw"] = raw_descriptors[system_id]
            systems[system_id]["next_canonical_state"] = _artifact(
                state_path,
                state_path.read_bytes(),
            )
        issue_payload = {
            "schema": ISSUE_SCHEMA,
            "status": "joint_issue_predictions_sealed_before_next_issue_request",
            "issue_ordinal": ordinal,
            "issue_index": issue_index,
            "issue_time_utc": issue_key,
            "lineage": {
                "protocol_sha256": hashlib.sha256(
                    preparation["protocol_body"]
                ).hexdigest(),
                "frozen_input_plan_sha256": hashlib.sha256(
                    preparation["plan_body"]
                ).hexdigest(),
                "static_input_report_sha256": hashlib.sha256(
                    preparation["static_body"]
                ).hexdigest(),
                "policy_sha256": preparation["protocol"]["candidate_lock"][
                    "policy_sha256"
                ],
                "previous_joint_issue_seal_sha256": previous_seal_sha256,
            },
            "systems": systems,
            "ordering_audit": {
                "both_system_issue_observations_loaded": True,
                "all_constituent_predictions_executed": True,
                "both_next_canonical_states_sealed": True,
                "next_issue_request_started": False,
                "bulk_prefetch_used": False,
            },
            "data_isolation": {
                "post_issue_observation_requested": False,
                "future_target_argument_accepted": False,
                "score_or_loss_argument_accepted": False,
                "full_outcome_series_requested": False,
                "actual_historical_publication_latency_verified": False,
            },
            "claim_boundary": {
                "issue_predictions_sealed": True,
                "holdout_scored": False,
                "candidate_promoted": False,
                "runtime_default_enabled": False,
            },
        }
        seal_body = _canonical_json(issue_payload)
        previous_seal_sha256 = hashlib.sha256(seal_body).hexdigest()
        sealed_issue = {
            **issue_payload,
            "joint_issue_seal": {
                "algorithm": "sha256_canonical_json_without_joint_issue_seal",
                "sha256": previous_seal_sha256,
            },
        }
        issue_path = issue_dir / "joint_issue.json"
        _write_json(issue_path, sealed_issue)
        issue_artifacts.append(
            {
                "issue_index": issue_index,
                "issue_time_utc": issue_key,
                "joint_issue_seal_sha256": previous_seal_sha256,
                **_artifact(issue_path, issue_path.read_bytes()),
            }
        )
        rows.extend(_prediction_rows(sealed_issue))
        for system_id in freeze.SYSTEM_IDS:
            contexts[system_id]["state"] = next_states[system_id]

    predictions_body = _encode_rows(rows)
    return predictions_body, {
        "schema": SCHEMA,
        "status": "all_chronological_issue_predictions_jointly_sealed",
        "generated_at": datetime.now(UTC).isoformat(),
        "frozen_artifacts": {
            "protocol": _artifact(protocol_path, preparation["protocol_body"]),
            "input_plan": _artifact(frozen_plan_path, preparation["plan_body"]),
            "static_input_report": _artifact(
                static_report_path,
                preparation["static_body"],
            ),
        },
        "execution": {
            "system_count": len(freeze.SYSTEM_IDS),
            "issue_count_per_system": len(issue_times),
            "joint_issue_seal_count": len(issue_artifacts),
            "mode_count": len(HORIZON_ASSIMILATION_MODES),
            "horizon_count": len(HORIZON_ASSIMILATION_SUPPORTED_HORIZONS_HOURS),
            "constituent_prediction_count": len(rows),
            "usgs_issue_request_count": remote_request_count + reused_request_count,
            "usgs_remote_request_count": remote_request_count,
            "usgs_current_issue_retry_reuse_count": reused_request_count,
            "static_request_count": 10,
            "frozen_total_request_count_completed": (
                10 + remote_request_count + reused_request_count
            ),
        },
        "issue_artifacts": issue_artifacts,
        "joint_chain": {
            "first_previous_seal_sha256": None,
            "final_joint_issue_seal_sha256": previous_seal_sha256,
            "chronological_chain_complete": len(issue_artifacts) == len(issue_times),
            "next_issue_requested_only_after_prior_joint_seal": True,
        },
        "prediction_artifact": {
            "path": _display(output_root / "predictions.csv"),
            "sha256": hashlib.sha256(predictions_body).hexdigest(),
            "size_bytes": len(predictions_body),
        },
        "data_isolation": {
            "full_outcome_url_compiled": False,
            "full_outcome_series_requested": False,
            "target_or_score_input_accepted": False,
            "scores_computed": False,
        },
        "claim_boundary": {
            "static_inputs_acquired": True,
            "issue_observations_acquired_in_causal_order": True,
            "outcome_free_predictions_executed": True,
            "holdout_outcomes_acquired_for_scoring": False,
            "holdout_scored": False,
            "geospatial_kernel_validated": False,
            "candidate_promoted": False,
            "runtime_default_enabled": False,
        },
    }


def _advance_nominal_interval(
    *,
    context: Mapping[str, Any],
    issue_index: int,
    issue_time: datetime,
) -> tuple[StockState, dict[int, float]]:
    state = context["state"]
    action_index = context["feature_ids"].index(
        context["network"].action_entry_feature_ids[0]
    )
    predictions: dict[int, float] = {}
    for offset in range(12):
        action_values = np.zeros(len(context["feature_ids"]), dtype=float)
        action_values[action_index] = context["actions"][
            issue_time + timedelta(hours=offset)
        ]
        result = context["operator"].step(
            state,
            context["geometry"],
            action=ActionBoundaryFlux(
                values=tuple(float(value) for value in action_values),
                unit="m3 s-1",
                provenance_id=f"horizon-holdout:canonical-action:{issue_index}:{offset}",
            ),
            forcing=ForcingFlux(
                values=tuple(
                    float(value)
                    for value in context["q_lateral"][issue_index + offset]
                ),
                unit="m3 s-1",
                provenance_id=f"horizon-holdout:canonical-forcing:{issue_index}:{offset}",
                modeled=True,
            ),
            forcing_support=context["forcing_support"],
        )
        if (
            abs(result.global_mass_balance_residual_m3)
            > result.numeric_mass_tolerance_m3
        ):
            raise RuntimeError("horizon_holdout_rollout_canonical_mass_failed")
        state = StockState(
            values=result.next_stock.values,
            unit="m3",
            provenance_id=f"horizon-holdout:canonical-state:{issue_index + offset + 1}",
        )
        horizon = offset + 1
        if horizon in HORIZON_ASSIMILATION_SUPPORTED_HORIZONS_HOURS:
            predictions[horizon] = result.outlet_mean_flow_m3s
    return state, predictions


def _parse_exact_issue_observation(
    payload: Mapping[str, Any],
    *,
    site_id: str,
    issue_time: datetime,
) -> dict[str, Any]:
    series = (payload.get("value") or {}).get("timeSeries") or []
    matching: list[Mapping[str, Any]] = []
    for row in series:
        site_codes = {
            value.get("value")
            for value in (row.get("sourceInfo") or {}).get("siteCode") or []
        }
        variable = row.get("variable") or {}
        variable_codes = {
            value.get("value") for value in variable.get("variableCode") or []
        }
        if site_id in site_codes and "00060" in variable_codes:
            if (variable.get("unit") or {}).get("unitCode") != "ft3/s":
                raise ValueError("horizon_holdout_rollout_usgs_unit_invalid")
            matching.append(row)
    if not matching:
        return {
            "value_m3s": None,
            "exact_issue_timestamp_found": False,
            "fallback_reason": "no_matching_usgs_series",
            "qualifiers": [],
            "historical_publication_at_issue_time_verified": False,
        }
    if len(matching) != 1:
        raise ValueError("horizon_holdout_rollout_usgs_single_series_required")
    row = matching[0]
    no_data = float((row.get("variable") or {}).get("noDataValue", -999999.0))
    exact: list[Mapping[str, Any]] = []
    for group in row.get("values") or []:
        for sample in group.get("value") or []:
            if _parse_time(sample.get("dateTime")) == issue_time:
                exact.append(sample)
    if not exact:
        return {
            "value_m3s": None,
            "exact_issue_timestamp_found": False,
            "fallback_reason": "exact_issue_timestamp_missing",
            "qualifiers": [],
            "historical_publication_at_issue_time_verified": False,
        }
    if len(exact) != 1:
        raise ValueError("horizon_holdout_rollout_usgs_duplicate_issue_timestamp")
    sample = exact[0]
    raw_value = float(sample["value"])
    qualifiers = tuple(str(value) for value in sample.get("qualifiers") or ())
    if raw_value == no_data:
        value_m3s = None
        fallback = "usgs_no_data_value"
    elif qualifiers != ("A",):
        value_m3s = None
        fallback = "issue_observation_not_approved"
    else:
        value_m3s = raw_value * CFS_TO_M3S
        fallback = None
    return {
        "value_m3s": value_m3s,
        "raw_value_ft3s": raw_value,
        "exact_issue_timestamp_found": True,
        "fallback_reason": fallback,
        "qualifiers": list(qualifiers),
        "historical_publication_at_issue_time_verified": False,
    }


def _prediction_rows(issue: Mapping[str, Any]) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for system_id in freeze.SYSTEM_IDS:
        system = issue["systems"][system_id]
        selected = system["rollout"]["selected_predictions"]
        for mode_rollout in system["rollout"]["mode_rollouts"]:
            mode = mode_rollout["mode"]
            for horizon in HORIZON_ASSIMILATION_SUPPORTED_HORIZONS_HOURS:
                selection = selected[str(horizon)]
                rows.append(
                    {
                        "issue_index": issue["issue_index"],
                        "issue_time_utc": issue["issue_time_utc"],
                        "system_id": system_id,
                        "mode": mode,
                        "horizon_hours": horizon,
                        "target_time_utc": _iso(
                            _parse_time(issue["issue_time_utc"])
                            + timedelta(hours=horizon)
                        ),
                        "predicted_outlet_m3s": mode_rollout[
                            "predictions_m3s_by_horizon_hours"
                        ][str(horizon)],
                        "selected_by_policy": selection["mode"] == mode,
                        "issue_observed_outlet_m3s": system["observation"].get(
                            "value_m3s"
                        ),
                        "observation_fallback_reason": system["observation"].get(
                            "fallback_reason"
                        ),
                    }
                )
    return rows


def _validate_static_report(
    report: Mapping[str, Any],
    *,
    protocol_body: bytes,
    plan_body: bytes,
) -> None:
    claims = report.get("claim_boundary") or {}
    isolation = report.get("data_isolation") or {}
    if (
        report.get("schema") != static.SCHEMA
        or report.get("status") != "static_inputs_acquired_issue_observations_deferred"
        or report.get("frozen_artifacts", {}).get("protocol", {}).get("sha256")
        != hashlib.sha256(protocol_body).hexdigest()
        or report.get("frozen_artifacts", {}).get("input_plan", {}).get("sha256")
        != hashlib.sha256(plan_body).hexdigest()
        or claims.get("static_inputs_acquired") is not True
        or claims.get("issue_observations_acquired") is not False
        or claims.get("outcome_free_predictions_executed") is not False
        or claims.get("candidate_promoted") is not False
        or isolation.get("usgs_url_requested") is not False
        or isolation.get("issue_observation_loaded") is not False
    ):
        raise ValueError("horizon_holdout_rollout_static_report_invalid")
    for system_id in freeze.SYSTEM_IDS:
        system = report["systems"][system_id]
        _read_verified(system["action_values"])
        for descriptor in system["decoded_arrays"].values():
            _read_verified(descriptor)


def _parse_actions(body: bytes) -> dict[datetime, float]:
    reader = csv.DictReader(io.StringIO(body.decode("utf-8")))
    if reader.fieldnames != [
        "support_start_utc",
        "support_end_utc",
        "action_release_m3s",
        "source_role",
    ]:
        raise ValueError("horizon_holdout_rollout_action_columns_invalid")
    actions: dict[datetime, float] = {}
    for row in reader:
        start = _parse_time(row["support_start_utc"])
        end = _parse_time(row["support_end_utc"])
        value = float(row["action_release_m3s"])
        if (
            end - start != timedelta(hours=1)
            or row["source_role"] != "boundary_action"
            or not np.isfinite(value)
            or value < 0.0
            or start in actions
        ):
            raise ValueError("horizon_holdout_rollout_action_value_invalid")
        actions[start] = value
    expected = {
        freeze.START + timedelta(hours=index) for index in range(freeze.HOUR_COUNT)
    }
    if set(actions) != expected:
        raise ValueError("horizon_holdout_rollout_action_time_axis_mismatch")
    return actions


def _read_verified(descriptor: Mapping[str, Any]) -> bytes:
    path = (REPO_ROOT / str(descriptor.get("path"))).resolve()
    try:
        path.relative_to(REPO_ROOT)
    except ValueError as exc:
        raise ValueError("horizon_holdout_rollout_artifact_outside_repository") from exc
    body = path.read_bytes()
    if (
        hashlib.sha256(body).hexdigest() != descriptor.get("sha256")
        or len(body) != descriptor.get("size_bytes")
    ):
        raise ValueError("horizon_holdout_rollout_artifact_identity_mismatch")
    return body


def _load_json(path: Path) -> tuple[bytes, dict[str, Any]]:
    body = path.read_bytes()
    payload = json.loads(body)
    if not isinstance(payload, dict):
        raise ValueError("horizon_holdout_rollout_json_document_required")
    return body, payload


def _parse_time(value: object) -> datetime:
    if not isinstance(value, str):
        raise ValueError("horizon_holdout_rollout_time_invalid")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("horizon_holdout_rollout_time_invalid") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("horizon_holdout_rollout_time_invalid")
    return parsed.astimezone(UTC)


def _canonical_json(payload: Mapping[str, Any]) -> bytes:
    return json.dumps(
        payload,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


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


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _write_npy(path: Path, values: np.ndarray[Any, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as stream:
        np.save(stream, values, allow_pickle=False)


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _encode_rows(rows: list[dict[str, object]]) -> bytes:
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
    writer.writeheader()
    writer.writerows(rows)
    return stream.getvalue().encode("utf-8")


def main() -> int:
    args = parse_args()
    if args.timeout_seconds <= 0.0 or args.retries <= 0:
        raise ValueError("horizon_holdout_rollout_positive_request_limits_required")
    if args.report.exists():
        raise ValueError("horizon_holdout_rollout_report_already_exists")
    predictions, report = run_chronological_holdout(
        protocol_path=args.protocol,
        frozen_plan_path=args.frozen_plan,
        static_report_path=args.static_report,
        output_root=args.output,
        proxy=args.proxy,
        timeout_seconds=args.timeout_seconds,
        retries=args.retries,
    )
    prediction_path = args.output / "predictions.csv"
    prediction_path.parent.mkdir(parents=True, exist_ok=True)
    prediction_path.write_bytes(predictions)
    _write_json(args.report, report)
    print(args.report)
    print(
        "joint_issue_seals="
        f"{report['execution']['joint_issue_seal_count']} "
        "usgs_issue_requests="
        f"{report['execution']['usgs_issue_request_count']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
