#!/usr/bin/env python3
"""Execute one preflighted prospective Manning episode without outcomes."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from datetime import datetime
from pathlib import Path
from typing import Any

from data_agent.uwm.geospatial_kernel_v2.branching_network import (
    BRANCHING_NETWORK_TRANSPORT_OPERATOR_SCHEMA,
    BranchingManningNetworkTransportOperator,
    BranchingNetworkTransportConfig,
    DirectedReachNetwork,
)
from data_agent.uwm.geospatial_kernel_v2.contracts import (
    ActionBoundaryFlux,
    ForcingFlux,
    ReachForcingSupport,
    ReachHydraulicGeometry,
    StockState,
)
from data_agent.uwm.geospatial_kernel_v2.instrumented_physical_rollout import (
    InstrumentedManningStepInput,
    run_instrumented_manning_rollout,
)
from data_agent.uwm.geospatial_kernel_v2.internal_innovation_instrumentation import (
    InternalInnovationTelemetryConfig,
    write_hash_bound_internal_innovation_artifacts,
)

if __package__:
    from scripts.assess_geospatial_kernel_internal_innovation_episode_preflight import (
        PROTOCOL_PATH,
        REPO_ROOT,
        REQUIRED_INPUT_ARTIFACTS,
        assess_manifest,
    )
else:
    from assess_geospatial_kernel_internal_innovation_episode_preflight import (
        PROTOCOL_PATH,
        REPO_ROOT,
        REQUIRED_INPUT_ARTIFACTS,
        assess_manifest,
    )

EXECUTION_SCHEMA = "gwm.geospatial_kernel.prospective_manning_episode_execution.v2"
PREDICTION_SCHEMA = "gwm.geospatial_kernel.prospective_physical_prediction.v1"
PREDICTION_FILENAME = "physical_prediction.json"
REPORT_FILENAME = "execution_report.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output-directory", type=Path, required=True)
    return parser.parse_args()


def execute_manning_episode(
    *,
    manifest_path: Path,
    output_directory: Path,
    repo_root: Path = REPO_ROOT,
    protocol_path: Path = PROTOCOL_PATH,
) -> dict[str, Any]:
    """Compile, execute, and seal one 24-hour outcome-free physical episode."""

    root = Path(repo_root).resolve()
    manifest_file = _inside_root(root, manifest_path)
    output = _new_output_directory(root, output_directory)
    preflight = assess_manifest(
        manifest_file,
        repo_root=root,
        protocol_path=protocol_path,
    )
    if preflight.get("episode_execution_ready") is not True:
        raise ValueError("internal_innovation_episode_preflight_not_ready")
    manifest = _read_strict_json_object(manifest_file)
    if manifest.get("operator_schema") != BRANCHING_NETWORK_TRANSPORT_OPERATOR_SCHEMA:
        raise ValueError("internal_innovation_episode_manning_operator_required")
    descriptors = _mapping(manifest.get("artifacts"))
    payloads = {
        name: _load_bound_json(root, descriptors.get(name), expected_schema=schema)
        for name, schema in REQUIRED_INPUT_ARTIFACTS.items()
    }
    compiled = _compile_episode(manifest, descriptors, payloads)
    result = run_instrumented_manning_rollout(
        compiled["operator"],
        compiled["geometry"],
        compiled["initial_state"],
        compiled["steps"],
        telemetry_config=compiled["telemetry_config"],
    )
    if (
        result.telemetry.source_steps_admitted is not True
        or result.telemetry.diagnostic_only is True
        or any(row["diagnostic_only"] is True for row in result.prediction_rows)
    ):
        raise RuntimeError("internal_innovation_episode_physical_rollout_not_admitted")
    output.mkdir(parents=True)
    internal_artifacts = write_hash_bound_internal_innovation_artifacts(
        result.telemetry,
        output,
        repo_root=root,
    )
    prediction = _prediction_payload(manifest, result.prediction_rows)
    prediction_artifact = _write_json_exclusive(
        root,
        output / PREDICTION_FILENAME,
        prediction,
    )
    mass_passed = all(
        abs(float(row["global_mass_balance_residual_m3"]))
        <= float(row["numeric_mass_tolerance_m3"])
        for row in result.prediction_rows
    )
    report = {
        "schema": EXECUTION_SCHEMA,
        "status": "outcome_free_physical_prediction_and_internal_telemetry_sealed",
        "episode_id": manifest["episode_id"],
        "system_id": manifest["system_id"],
        "forecast_issue_time": manifest["forecast_issue_time"],
        "support": dict(manifest["support"]),
        "manifest_artifact": dict(preflight["manifest_artifact"]),
        "protocol": dict(preflight["protocol"]),
        "execution_addendum": dict(preflight["execution_addendum"]),
        "input_artifacts": {
            name: {
                **dict(descriptors[name]),
                "identity_recomputed_before_execution": True,
            }
            for name in REQUIRED_INPUT_ARTIFACTS
        },
        "registered_execution": {
            "operator": "BranchingManningNetworkTransportOperator",
            "operator_schema": BRANCHING_NETWORK_TRANSPORT_OPERATOR_SCHEMA,
            "timestep_seconds": 3600.0,
            "integration_substep_seconds": 300.0,
            "network_fingerprint": result.telemetry.network_fingerprint,
        },
        "prediction_artifact": prediction_artifact,
        "internal_innovation_artifacts": internal_artifacts,
        "invariants": {
            "step_count": result.telemetry.step_count,
            "actual_conservation_passed": mass_passed,
            "state_transition_continuity_verified": result.telemetry.alignment_assertions[
                "state_transition_continuity_verified"
            ],
            "all_source_steps_admitted": result.telemetry.source_steps_admitted,
        },
        "data_isolation": {
            "outcome_argument_accepted": False,
            "outcome_values_loaded": False,
            "outcome_artifacts_opened": False,
            "score_report_loaded": False,
            "candidate_fit_executed": False,
            "network_requests_performed": False,
        },
        "claim_boundary": {
            "prospective_input_manifest_preflight_passed": True,
            "physical_prediction_sealed": True,
            "internal_telemetry_sealed": True,
            "outcomes_acquired": False,
            "innovation_fitted": False,
            "candidate_promoted": False,
            "runtime_enabled": False,
            "geospatial_kernel_validated": False,
        },
    }
    _write_json_exclusive(root, output / REPORT_FILENAME, report)
    return report


def _compile_episode(
    manifest: dict[str, Any],
    descriptors: dict[str, Any],
    payloads: dict[str, dict[str, Any]],
) -> dict[str, object]:
    feature = payloads["feature_axis"]
    feature_rows = _required_list(feature.get("features"), "feature_axis")
    feature_ids = tuple(_required_positive_int(row.get("feature_id")) for row in feature_rows)
    geometry_payload = payloads["hydraulic_geometry"]
    full_lengths = _positive_float_vector(
        geometry_payload.get("full_lengths_m"),
        count=len(feature_ids),
        name="full_lengths_m",
    )
    effective_lengths = _positive_float_vector(
        geometry_payload.get("effective_lengths_m"),
        count=len(feature_ids),
        name="effective_lengths_m",
    )
    if any(
        effective > full + 1e-6
        for full, effective in zip(full_lengths, effective_lengths, strict=True)
    ):
        raise ValueError("internal_innovation_episode_effective_length_exceeds_full")
    downstream = _downstream_axis(feature_ids, payloads["edge_axis"])
    action_payload = payloads["reservoir_action_schedule"]
    action_entry_values = action_payload.get("action_entry_feature_ids")
    if not isinstance(action_entry_values, list) or not action_entry_values:
        raise ValueError("internal_innovation_episode_action_entry_axis_invalid")
    action_entries = tuple(
        _required_positive_int(value)
        for value in action_entry_values
    )
    if len(action_entries) != len(set(action_entries)) or not set(action_entries).issubset(
        feature_ids
    ):
        raise ValueError("internal_innovation_episode_action_entry_axis_invalid")
    network = DirectedReachNetwork(
        network_id=f"{manifest['system_id']}:{manifest['episode_id']}",
        feature_ids=feature_ids,
        downstream_feature_ids=downstream,
        full_lengths_m=full_lengths,
        effective_lengths_m=effective_lengths,
        action_entry_feature_ids=action_entries,
        provenance_id=_required_string(descriptors["edge_axis"].get("provenance_id")),
        evidence_level="derived",
        admitted=True,
    )
    geometry = ReachHydraulicGeometry(
        feature_ids=feature_ids,
        bottom_width_m=_positive_float_vector(
            geometry_payload.get("bottom_width_m"),
            count=len(feature_ids),
            name="bottom_width_m",
        ),
        side_slope_horizontal_per_vertical=_positive_float_vector(
            geometry_payload.get("side_slope_horizontal_per_vertical"),
            count=len(feature_ids),
            name="side_slope_horizontal_per_vertical",
        ),
        bed_slope=_positive_float_vector(
            geometry_payload.get("bed_slope"),
            count=len(feature_ids),
            name="bed_slope",
        ),
        manning_n=_positive_float_vector(
            geometry_payload.get("manning_n"),
            count=len(feature_ids),
            name="manning_n",
        ),
        provenance_id=_required_string(
            descriptors["hydraulic_geometry"].get("provenance_id")
        ),
        evidence_level="derived",
        admitted_as_hydraulic_geometry=True,
    )
    initial_payload = payloads["initial_state"]
    initial_state = StockState(
        values=_nonnegative_float_vector(
            initial_payload.get("stock_m3"),
            count=len(feature_ids),
            name="stock_m3",
        ),
        unit="m3",
        provenance_id=_required_string(descriptors["initial_state"].get("provenance_id")),
    )
    operator = BranchingManningNetworkTransportOperator(
        network,
        BranchingNetworkTransportConfig(
            timestep_seconds=3600.0,
            integration_substep_seconds=300.0,
            operator_form_admitted=True,
        ),
    )
    forcing_support = _forcing_support(
        feature_ids=feature_ids,
        full_lengths=full_lengths,
        effective_lengths=effective_lengths,
        forcing_payload=payloads["distributed_forcing_forecast"],
    )
    availability = max(
        _aware_datetime(descriptor.get("available_at"))
        for descriptor in descriptors.values()
        if isinstance(descriptor, dict)
    )
    action_rows = _required_list(action_payload.get("rows"), "action_rows")
    forcing_payload = payloads["distributed_forcing_forecast"]
    forcing_rows = _required_list(forcing_payload.get("rows"), "forcing_rows")
    steps = []
    action_entry_indices = {feature_ids.index(value) for value in action_entries}
    for index, (action_row, forcing_row) in enumerate(
        zip(action_rows, forcing_rows, strict=True)
    ):
        action_values = _nonnegative_float_vector(
            action_row.get("action_m3s"),
            count=len(feature_ids),
            name="action_m3s",
        )
        if any(
            value != 0.0
            for feature_index, value in enumerate(action_values)
            if feature_index not in action_entry_indices
        ):
            raise ValueError("internal_innovation_episode_action_outside_registered_entry")
        forcing_values = _nonnegative_float_vector(
            forcing_row.get("forcing_m3s"),
            count=len(feature_ids),
            name="forcing_m3s",
        )
        steps.append(
            InstrumentedManningStepInput(
                support_start=_aware_datetime(action_row.get("support_start_utc")),
                support_end=_aware_datetime(action_row.get("support_end_utc")),
                inputs_available_at=availability,
                action=ActionBoundaryFlux(
                    action_values,
                    "m3 s-1",
                    f"{descriptors['reservoir_action_schedule']['provenance_id']}:step:{index}",
                ),
                forcing=ForcingFlux(
                    forcing_values,
                    "m3 s-1",
                    f"{descriptors['distributed_forcing_forecast']['provenance_id']}:step:{index}",
                    modeled=True,
                ),
                forcing_support=forcing_support,
            )
        )
    issue_time = _aware_datetime(manifest.get("forecast_issue_time"))
    return {
        "operator": operator,
        "geometry": geometry,
        "initial_state": initial_state,
        "steps": tuple(steps),
        "telemetry_config": InternalInnovationTelemetryConfig(
            system_id=_required_string(manifest.get("system_id")),
            forecast_issue_time=issue_time,
            operator_schema=BRANCHING_NETWORK_TRANSPORT_OPERATOR_SCHEMA,
            provenance_id=f"{manifest['episode_id']}:internal-telemetry",
            evidence_level="derived",
            admitted=True,
        ),
    }


def _downstream_axis(
    feature_ids: tuple[int, ...], edge_payload: dict[str, Any]
) -> tuple[int | None, ...]:
    downstream: dict[int, int] = {}
    for row in _required_list(edge_payload.get("edges"), "edge_axis"):
        source = _required_positive_int(row.get("source_feature_id"))
        target = _required_positive_int(row.get("target_feature_id"))
        if source in downstream:
            raise ValueError("internal_innovation_episode_multiple_downstream_edges")
        downstream[source] = target
    return tuple(downstream.get(feature_id) for feature_id in feature_ids)


def _forcing_support(
    *,
    feature_ids: tuple[int, ...],
    full_lengths: tuple[float, ...],
    effective_lengths: tuple[float, ...],
    forcing_payload: dict[str, Any],
) -> ReachForcingSupport | None:
    if all(
        abs(full - effective) <= 1e-6
        for full, effective in zip(full_lengths, effective_lengths, strict=True)
    ):
        return None
    coverage = _nonnegative_float_vector(
        forcing_payload.get("coverage_fractions"),
        count=len(feature_ids),
        name="coverage_fractions",
    )
    if any(value > 1.0 for value in coverage):
        raise ValueError("internal_innovation_episode_forcing_coverage_invalid")
    return ReachForcingSupport(
        feature_ids=feature_ids,
        coverage_fractions=coverage,
        support_method=_required_string(forcing_payload.get("support_method")),
        provenance_id=_required_string(
            forcing_payload.get("spatial_support_provenance_id")
        ),
        evidence_level=_required_string(
            forcing_payload.get("spatial_support_evidence_level")
        ),
        admitted_as_spatial_support=(
            forcing_payload.get("admitted_as_spatial_support") is True
        ),
    )


def _prediction_payload(
    manifest: dict[str, Any], prediction_rows: tuple[dict[str, object], ...]
) -> dict[str, object]:
    return {
        "schema": PREDICTION_SCHEMA,
        "episode_id": manifest["episode_id"],
        "system_id": manifest["system_id"],
        "operator_schema": BRANCHING_NETWORK_TRANSPORT_OPERATOR_SCHEMA,
        "forecast_issue_time": manifest["forecast_issue_time"],
        "support": dict(manifest["support"]),
        "step_count": len(prediction_rows),
        "rows": list(prediction_rows),
        "claim_boundary": {
            "outcome_values_loaded": False,
            "physical_prediction_only": True,
            "innovation_applied": False,
        },
    }


def _load_bound_json(
    root: Path, descriptor_value: object, *, expected_schema: str
) -> dict[str, Any]:
    descriptor = _mapping(descriptor_value)
    path = _inside_root(root, Path(_required_string(descriptor.get("path"))))
    body = path.read_bytes()
    if (
        hashlib.sha256(body).hexdigest() != descriptor.get("sha256")
        or len(body) != descriptor.get("size_bytes")
    ):
        raise ValueError("internal_innovation_episode_input_identity_mismatch")
    payload = _read_strict_json_object(path)
    if payload.get("schema") != expected_schema:
        raise ValueError("internal_innovation_episode_input_schema_mismatch")
    return payload


def _write_json_exclusive(
    root: Path, path: Path, payload: dict[str, object]
) -> dict[str, object]:
    target = _inside_root(root, path)
    body = _canonical_json_bytes(payload)
    try:
        with target.open("xb") as stream:
            stream.write(body)
    except FileExistsError as error:
        raise FileExistsError("internal_innovation_episode_output_conflict") from error
    return {
        "path": target.relative_to(root).as_posix(),
        "sha256": hashlib.sha256(body).hexdigest(),
        "size_bytes": len(body),
        "schema": payload["schema"],
    }


def _new_output_directory(root: Path, value: Path) -> Path:
    output = _inside_root(root, value)
    if output == root or output.exists():
        raise FileExistsError("internal_innovation_episode_output_conflict")
    return output


def _inside_root(root: Path, path: Path) -> Path:
    resolved = path.resolve() if path.is_absolute() else (root / path).resolve()
    try:
        resolved.relative_to(root)
    except ValueError as error:
        raise ValueError("internal_innovation_episode_artifact_outside_repository") from error
    return resolved


def _read_strict_json_object(path: Path) -> dict[str, Any]:
    def reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("internal_innovation_episode_json_duplicate_key")
            result[key] = value
        return result

    def reject_nonfinite(value: str) -> None:
        raise ValueError(f"internal_innovation_episode_json_nonfinite:{value}")

    try:
        payload = json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=reject_duplicate_keys,
            parse_constant=reject_nonfinite,
        )
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError("internal_innovation_episode_json_invalid") from error
    if not isinstance(payload, dict):
        raise ValueError("internal_innovation_episode_json_root_not_object")
    return payload


def _canonical_json_bytes(value: object) -> bytes:
    return (
        json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        )
        + "\n"
    ).encode("utf-8")


def _required_list(value: object, name: str) -> list[dict[str, Any]]:
    if not isinstance(value, list) or not value or not all(
        isinstance(item, dict) for item in value
    ):
        raise ValueError(f"internal_innovation_episode_{name}_invalid")
    return value


def _required_positive_int(value: object) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise ValueError("internal_innovation_episode_positive_integer_required")
    return value


def _float_vector(
    value: object, *, count: int, name: str, nonnegative: bool
) -> tuple[float, ...]:
    if not isinstance(value, list) or len(value) != count:
        raise ValueError(f"internal_innovation_episode_{name}_invalid")
    result = tuple(float(item) for item in value)
    if not all(math.isfinite(item) for item in result) or any(
        item < 0.0 if nonnegative else item <= 0.0 for item in result
    ):
        raise ValueError(f"internal_innovation_episode_{name}_invalid")
    return result


def _positive_float_vector(value: object, *, count: int, name: str) -> tuple[float, ...]:
    return _float_vector(value, count=count, name=name, nonnegative=False)


def _nonnegative_float_vector(
    value: object, *, count: int, name: str
) -> tuple[float, ...]:
    return _float_vector(value, count=count, name=name, nonnegative=True)


def _aware_datetime(value: object) -> datetime:
    if not isinstance(value, str):
        raise ValueError("internal_innovation_episode_aware_datetime_required")
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError("internal_innovation_episode_aware_datetime_required") from error
    if result.tzinfo is None or result.utcoffset() is None:
        raise ValueError("internal_innovation_episode_aware_datetime_required")
    return result


def _required_string(value: object) -> str:
    if not isinstance(value, str) or not value.strip() or "\x00" in value:
        raise ValueError("internal_innovation_episode_string_required")
    return value


def _mapping(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def main() -> int:
    args = parse_args()
    report = execute_manning_episode(
        manifest_path=args.manifest,
        output_directory=args.output_directory,
    )
    print(Path(args.output_directory) / REPORT_FILENAME)
    print(f"status={report['status']}")
    print("outcome_values_loaded=False")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
