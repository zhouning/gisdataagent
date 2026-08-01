"""Outcome-blind internal state and edge-flux telemetry for physical routing."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import numpy as np

from .branching_kinematic_wave import (
    BRANCHING_KINEMATIC_WAVE_OPERATOR_SCHEMA,
    BranchingKinematicWaveStepResult,
)
from .branching_network import (
    BRANCHING_NETWORK_TRANSPORT_OPERATOR_SCHEMA,
    BranchingNetworkTransportResult,
    DirectedReachNetwork,
)
from .contracts import StockState
from .kinematic_wave import KinematicWaveState

INTERNAL_INNOVATION_TELEMETRY_SCHEMA = "gwm.geospatial_kernel.internal_innovation_telemetry.v1"
FEATURE_AXIS_SCHEMA = "gwm.geospatial_kernel.feature_axis.v1"
EDGE_AXIS_SCHEMA = "gwm.geospatial_kernel.edge_axis.v1"
REACH_STATE_SCHEMA = "gwm.geospatial_kernel.reach_state_timeseries.v1"
EDGE_FLUX_SCHEMA = "gwm.geospatial_kernel.edge_flux_timeseries.v1"
STEP_MASS_LEDGER_SCHEMA = "gwm.geospatial_kernel.step_mass_ledger.v1"

_SUPPORTED_OPERATOR_SCHEMAS = {
    BRANCHING_NETWORK_TRANSPORT_OPERATOR_SCHEMA,
    BRANCHING_KINEMATIC_WAVE_OPERATOR_SCHEMA,
}
_EVIDENCE_LEVELS = {"authoritative", "derived", "candidate"}
_ARTIFACT_FILES = {
    "feature_axis_artifact": "feature_axis.json",
    "edge_axis_artifact": "edge_axis.json",
    "reach_state_artifact": "reach_state.json",
    "edge_flux_artifact": "edge_flux.json",
    "step_mass_ledger_artifact": "step_mass_ledger.json",
}


def _aware(value: datetime) -> bool:
    return value.tzinfo is not None and value.utcoffset() is not None


def _canonical_json_bytes(value: object) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        )
        + "\n"
    ).encode("utf-8")


def _sha256_json(value: object) -> str:
    return hashlib.sha256(_canonical_json_bytes(value)).hexdigest()


@dataclass(frozen=True)
class InternalInnovationTelemetryConfig:
    system_id: str
    forecast_issue_time: datetime
    operator_schema: str
    provenance_id: str
    evidence_level: str
    admitted: bool

    def __post_init__(self) -> None:
        if not self.system_id.strip() or not self.provenance_id.strip():
            raise ValueError("internal_telemetry_identity_required")
        if not _aware(self.forecast_issue_time):
            raise ValueError("internal_telemetry_issue_time_must_be_aware")
        if self.operator_schema not in _SUPPORTED_OPERATOR_SCHEMAS:
            raise ValueError("internal_telemetry_operator_schema_unsupported")
        if self.evidence_level not in _EVIDENCE_LEVELS:
            raise ValueError("internal_telemetry_evidence_level_invalid")
        if not isinstance(self.admitted, bool):
            raise ValueError("internal_telemetry_admitted_must_be_boolean")
        if self.admitted and self.evidence_level == "candidate":
            raise ValueError("candidate_internal_telemetry_cannot_be_admitted")


@dataclass(frozen=True)
class InternalInnovationTelemetryBundle:
    system_id: str
    operator_schema: str
    network_fingerprint: str
    step_count: int
    artifacts: dict[str, dict[str, object]]
    alignment_assertions: dict[str, bool]
    source_steps_admitted: bool
    diagnostic_only: bool

    def __post_init__(self) -> None:
        if self.step_count <= 0:
            raise ValueError("internal_telemetry_bundle_requires_steps")
        if set(self.artifacts) != set(_ARTIFACT_FILES):
            raise ValueError("internal_telemetry_bundle_artifacts_incomplete")
        if not self.alignment_assertions or not all(self.alignment_assertions.values()):
            raise ValueError("internal_telemetry_bundle_alignment_failed")

    def as_dict(self) -> dict[str, object]:
        return {
            "schema": INTERNAL_INNOVATION_TELEMETRY_SCHEMA,
            "system_id": self.system_id,
            "operator_schema": self.operator_schema,
            "network_fingerprint": self.network_fingerprint,
            "step_count": self.step_count,
            "alignment_assertions": self.alignment_assertions,
            "source_steps_admitted": self.source_steps_admitted,
            "diagnostic_only": self.diagnostic_only,
            "claim_boundary": {
                "reach_states_are_modeled_not_observed": True,
                "edge_fluxes_are_physical_base_flux_not_observed_truth": True,
                "outcome_values_loaded": False,
                "innovation_fitted": False,
            },
        }


class InternalInnovationTelemetryRecorder:
    """Record existing physical step outputs without changing their operator."""

    def __init__(
        self,
        network: DirectedReachNetwork,
        config: InternalInnovationTelemetryConfig,
    ) -> None:
        if not isinstance(network, DirectedReachNetwork):
            raise TypeError("directed_reach_network_required")
        if not isinstance(config, InternalInnovationTelemetryConfig):
            raise TypeError("internal_telemetry_config_required")
        self.network = network
        self.config = config
        self._network_fingerprint = _sha256_json(network.as_dict())
        self._feature_rows = self._build_feature_axis()
        self._edge_rows = self._build_edge_axis()
        if not self._edge_rows:
            raise ValueError("internal_telemetry_requires_internal_edge")
        self._state_rows: list[dict[str, object]] = []
        self._flux_rows: list[dict[str, object]] = []
        self._ledger_rows: list[dict[str, object]] = []
        self._last_support_end: datetime | None = None
        self._last_final_values: tuple[float, ...] | None = None

    def record_step(
        self,
        initial_state: StockState | KinematicWaveState,
        result: BranchingNetworkTransportResult | BranchingKinematicWaveStepResult,
        *,
        support_start: datetime,
        support_end: datetime,
        inputs_available_at: datetime,
        input_provenance_ids: tuple[str, ...],
    ) -> None:
        self._validate_time_axis(
            support_start=support_start,
            support_end=support_end,
            inputs_available_at=inputs_available_at,
        )
        if (
            not input_provenance_ids
            or len(input_provenance_ids) != len(set(input_provenance_ids))
            or any(
                not isinstance(value, str) or not value.strip() for value in input_provenance_ids
            )
        ):
            raise ValueError("internal_telemetry_input_provenance_required")
        if self.config.operator_schema == BRANCHING_NETWORK_TRANSPORT_OPERATOR_SCHEMA:
            if not isinstance(initial_state, StockState) or not isinstance(
                result, BranchingNetworkTransportResult
            ):
                raise TypeError("internal_telemetry_manning_step_required")
            step = self._manning_step(initial_state, result)
        else:
            if not isinstance(initial_state, KinematicWaveState) or not isinstance(
                result, BranchingKinematicWaveStepResult
            ):
                raise TypeError("internal_telemetry_kinematic_step_required")
            step = self._kinematic_step(initial_state, result)

        if result.feature_ids != self.network.feature_ids:
            raise ValueError("internal_telemetry_result_feature_axis_mismatch")
        step_index = len(self._ledger_rows)
        initial_values = step["initial_values"]
        final_values = step["final_values"]
        if self._last_final_values is not None and tuple(initial_values) != self._last_final_values:
            raise ValueError("internal_telemetry_state_transition_discontinuity")
        temporal = {
            "step_index": step_index,
            "forecast_issue_time": self.config.forecast_issue_time.isoformat(),
            "inputs_available_at": inputs_available_at.isoformat(),
            "support_start_utc": support_start.isoformat(),
            "support_end_utc": support_end.isoformat(),
            "input_provenance_ids": list(input_provenance_ids),
            "initial_state_provenance_id": initial_state.provenance_id,
            "final_state_provenance_id": (
                result.next_stock.provenance_id
                if isinstance(result, BranchingNetworkTransportResult)
                else result.next_state.provenance_id
            ),
        }
        depths = result.reach_end_depth_m
        outflows = result.reach_mean_outflow_m3s
        for feature_index, feature_id in enumerate(self.network.feature_ids):
            self._state_rows.append(
                {
                    **temporal,
                    "feature_index": feature_index,
                    "feature_id": feature_id,
                    "initial_stock_m3": initial_values[feature_index],
                    "final_stock_m3": final_values[feature_index],
                    "final_depth_m": float(depths[feature_index]),
                    "state_role": "modeled_physical_internal_state",
                    "ground_truth": False,
                }
            )
        feature_index = {value: index for index, value in enumerate(self.network.feature_ids)}
        for edge in self._edge_rows:
            source_index = feature_index[int(edge["source_feature_id"])]
            self._flux_rows.append(
                {
                    **temporal,
                    "edge_index": edge["edge_index"],
                    "edge_key": edge["edge_key"],
                    "source_feature_id": edge["source_feature_id"],
                    "target_feature_id": edge["target_feature_id"],
                    "base_mean_flux_m3s": float(outflows[source_index]),
                    "flux_role": "modeled_physical_base_internal_transfer",
                    "ground_truth": False,
                }
            )
        ledger = {
            **temporal,
            **step["ledger"],
            "mass_balance_passed": abs(float(step["ledger"]["residual_m3"]))
            <= float(step["ledger"]["numeric_tolerance_m3"]),
            "source_step_admitted": bool(step["admitted"]),
            "diagnostic_only": bool(result.diagnostic_only),
        }
        if ledger["mass_balance_passed"] is not True:
            raise ValueError("internal_telemetry_source_mass_balance_failed")
        self._ledger_rows.append(ledger)
        self._last_support_end = support_end
        self._last_final_values = tuple(float(value) for value in final_values)

    def compile(self) -> InternalInnovationTelemetryBundle:
        step_count = len(self._ledger_rows)
        if step_count == 0:
            raise ValueError("internal_telemetry_requires_at_least_one_step")
        all_steps_admitted = all(row["source_step_admitted"] is True for row in self._ledger_rows)
        feature_axis = self._artifact_base(
            FEATURE_AXIS_SCHEMA,
            all_steps_admitted=all_steps_admitted,
        ) | {
            "axis_order": "network.feature_ids",
            "feature_count": len(self._feature_rows),
            "features": list(self._feature_rows),
        }
        edge_axis = self._artifact_base(
            EDGE_AXIS_SCHEMA,
            all_steps_admitted=all_steps_admitted,
        ) | {
            "axis_order": "network.feature_ids_filtered_to_internal_edges",
            "edge_count": len(self._edge_rows),
            "edges": list(self._edge_rows),
        }
        feature_axis_sha256 = _sha256_json(feature_axis)
        edge_axis_sha256 = _sha256_json(edge_axis)
        reach_state = self._artifact_base(
            REACH_STATE_SCHEMA,
            all_steps_admitted=all_steps_admitted,
        ) | {
            "feature_axis_sha256": feature_axis_sha256,
            "step_count": step_count,
            "row_count": len(self._state_rows),
            "stock_unit": "m3",
            "depth_unit": "m",
            "rows": list(self._state_rows),
            "claim_boundary": {
                "modeled": True,
                "ground_truth": False,
                "observation_values_loaded": False,
            },
        }
        edge_flux = self._artifact_base(
            EDGE_FLUX_SCHEMA,
            all_steps_admitted=all_steps_admitted,
        ) | {
            "edge_axis_sha256": edge_axis_sha256,
            "step_count": step_count,
            "row_count": len(self._flux_rows),
            "flux_unit": "m3 s-1",
            "rows": list(self._flux_rows),
            "claim_boundary": {
                "physical_base_flux": True,
                "observed_flux_truth": False,
                "innovation_values_included": False,
            },
        }
        mass_ledger = self._artifact_base(
            STEP_MASS_LEDGER_SCHEMA,
            all_steps_admitted=all_steps_admitted,
        ) | {
            "feature_axis_sha256": feature_axis_sha256,
            "step_count": step_count,
            "row_count": len(self._ledger_rows),
            "volume_unit": "m3",
            "rows": list(self._ledger_rows),
        }
        assertions = {
            "feature_axis_matches_reach_state": (
                len(self._state_rows) == step_count * len(self._feature_rows)
                and all(
                    row["feature_id"] == self.network.feature_ids[int(row["feature_index"])]
                    for row in self._state_rows
                )
            ),
            "edge_axis_matches_edge_flux": (
                len(self._flux_rows) == step_count * len(self._edge_rows)
                and all(
                    row["edge_key"] == self._edge_rows[int(row["edge_index"])]["edge_key"]
                    for row in self._flux_rows
                )
            ),
            "every_step_has_mass_ledger": len(self._ledger_rows) == step_count,
            "every_step_mass_ledger_conservative": all(
                row["mass_balance_passed"] is True for row in self._ledger_rows
            ),
            "state_transition_continuity_verified": all(
                self._state_rows[index]["final_stock_m3"]
                == self._state_rows[index + len(self._feature_rows)]["initial_stock_m3"]
                for index in range(max(0, (step_count - 1) * len(self._feature_rows)))
            ),
            "causal_availability_recorded": all(
                datetime.fromisoformat(str(row["inputs_available_at"]))
                <= self.config.forecast_issue_time
                <= datetime.fromisoformat(str(row["support_start_utc"]))
                for row in self._ledger_rows
            ),
        }
        artifacts = {
            "feature_axis_artifact": feature_axis,
            "edge_axis_artifact": edge_axis,
            "reach_state_artifact": reach_state,
            "edge_flux_artifact": edge_flux,
            "step_mass_ledger_artifact": mass_ledger,
        }
        return InternalInnovationTelemetryBundle(
            system_id=self.config.system_id,
            operator_schema=self.config.operator_schema,
            network_fingerprint=self._network_fingerprint,
            step_count=step_count,
            artifacts=artifacts,
            alignment_assertions=assertions,
            source_steps_admitted=all_steps_admitted,
            diagnostic_only=not (self.config.admitted and all_steps_admitted),
        )

    def _validate_time_axis(
        self,
        *,
        support_start: datetime,
        support_end: datetime,
        inputs_available_at: datetime,
    ) -> None:
        if not all(_aware(value) for value in (support_start, support_end, inputs_available_at)):
            raise ValueError("internal_telemetry_times_must_be_aware")
        if support_end <= support_start:
            raise ValueError("internal_telemetry_support_interval_invalid")
        if self.config.forecast_issue_time > support_start:
            raise ValueError("internal_telemetry_support_starts_before_issue")
        if inputs_available_at > self.config.forecast_issue_time:
            raise ValueError("internal_telemetry_inputs_unavailable_at_issue")
        if self._last_support_end is not None and support_start != self._last_support_end:
            raise ValueError("internal_telemetry_steps_must_be_contiguous")

    def _manning_step(
        self,
        initial_state: StockState,
        result: BranchingNetworkTransportResult,
    ) -> dict[str, object]:
        if result.observed_internal_boundary_replacement_used:
            raise ValueError("internal_telemetry_internal_boundary_edge_flux_unobservable")
        if initial_state.unit != "m3" or result.next_stock.unit != "m3":
            raise ValueError("internal_telemetry_stock_unit_mismatch")
        initial = tuple(float(value) for value in initial_state.values)
        final = tuple(float(value) for value in result.next_stock.values)
        self._validate_reach_values(initial, final, result)
        initial_total = float(sum(initial))
        self._validate_reported_storage(
            final_total=float(sum(final)),
            reported_final=result.final_network_storage_m3,
        )
        return {
            "initial_values": initial,
            "final_values": final,
            "admitted": result.nonlinear_transport_admitted,
            "ledger": {
                "initial_network_storage_m3": initial_total,
                "final_network_storage_m3": result.final_network_storage_m3,
                "action_input_volume_m3": result.action_input_volume_m3,
                "distributed_forcing_volume_m3": (result.distributed_forcing_volume_m3),
                "modeled_tributary_boundary_volume_m3": (
                    result.modeled_tributary_boundary_volume_m3
                ),
                "observed_internal_boundary_input_volume_m3": (
                    result.observed_internal_boundary_input_volume_m3
                ),
                "total_input_volume_m3": result.total_input_volume_m3,
                "outlet_volume_m3": result.outlet_volume_m3,
                "displaced_upstream_outflow_volume_m3": (
                    result.displaced_upstream_outflow_volume_m3
                ),
                "residual_m3": result.global_mass_balance_residual_m3,
                "numeric_tolerance_m3": result.numeric_mass_tolerance_m3,
                "accounting_equation": ("final+outlet+displaced-initial-total_input=residual"),
            },
        }

    def _kinematic_step(
        self,
        initial_state: KinematicWaveState,
        result: BranchingKinematicWaveStepResult,
    ) -> dict[str, object]:
        if (
            initial_state.cell_feature_ids != result.next_state.cell_feature_ids
            or initial_state.cell_index_within_reach != result.next_state.cell_index_within_reach
        ):
            raise ValueError("internal_telemetry_cell_axis_changed")
        initial = self._aggregate_cell_storage(initial_state)
        final = self._aggregate_cell_storage(result.next_state)
        self._validate_reach_values(initial, final, result)
        initial_total = float(sum(initial))
        final_total = float(sum(final))
        self._validate_reported_storage(
            final_total=initial_total,
            reported_final=result.initial_network_storage_m3,
        )
        self._validate_reported_storage(
            final_total=final_total,
            reported_final=result.final_network_storage_m3,
        )
        return {
            "initial_values": initial,
            "final_values": final,
            "admitted": result.branching_kinematic_wave_admitted,
            "ledger": {
                "initial_network_storage_m3": result.initial_network_storage_m3,
                "final_network_storage_m3": result.final_network_storage_m3,
                "action_input_volume_m3": result.action_input_volume_m3,
                "distributed_forcing_volume_m3": (result.distributed_forcing_volume_m3),
                "modeled_tributary_boundary_volume_m3": 0.0,
                "observed_internal_boundary_input_volume_m3": 0.0,
                "total_input_volume_m3": result.total_input_volume_m3,
                "outlet_volume_m3": result.outlet_volume_m3,
                "displaced_upstream_outflow_volume_m3": 0.0,
                "residual_m3": result.global_mass_balance_residual_m3,
                "numeric_tolerance_m3": result.numeric_mass_tolerance_m3,
                "accounting_equation": ("final+outlet-initial-total_input=residual"),
            },
        }

    def _aggregate_cell_storage(self, state: KinematicWaveState) -> tuple[float, ...]:
        feature_index = {value: index for index, value in enumerate(self.network.feature_ids)}
        values = np.zeros(len(self.network.feature_ids), dtype=float)
        for feature_id, volume in zip(
            state.cell_feature_ids,
            state.cell_volume_m3,
            strict=True,
        ):
            if feature_id not in feature_index:
                raise ValueError("internal_telemetry_cell_feature_outside_network")
            values[feature_index[feature_id]] += float(volume)
        if set(state.cell_feature_ids) != set(self.network.feature_ids):
            raise ValueError("internal_telemetry_cell_feature_axis_incomplete")
        return tuple(float(value) for value in values)

    def _validate_reach_values(
        self,
        initial: tuple[float, ...],
        final: tuple[float, ...],
        result: BranchingNetworkTransportResult | BranchingKinematicWaveStepResult,
    ) -> None:
        count = len(self.network.feature_ids)
        arrays = (
            np.asarray(initial, dtype=float),
            np.asarray(final, dtype=float),
            np.asarray(result.reach_mean_outflow_m3s, dtype=float),
            np.asarray(result.reach_end_depth_m, dtype=float),
        )
        if any(value.shape != (count,) for value in arrays):
            raise ValueError("internal_telemetry_reach_axis_mismatch")
        if any(not np.isfinite(value).all() for value in arrays):
            raise ValueError("internal_telemetry_reach_values_nonfinite")
        if any(bool((value < 0.0).any()) for value in arrays):
            raise ValueError("internal_telemetry_reach_values_negative")

    @staticmethod
    def _validate_reported_storage(*, final_total: float, reported_final: float) -> None:
        tolerance = np.finfo(float).eps * 100.0 * max(1.0, abs(final_total), abs(reported_final))
        if abs(final_total - reported_final) > tolerance:
            raise ValueError("internal_telemetry_reported_storage_mismatch")

    def _artifact_base(
        self,
        schema: str,
        *,
        all_steps_admitted: bool,
    ) -> dict[str, object]:
        return {
            "schema": schema,
            "system_id": self.config.system_id,
            "operator_schema": self.config.operator_schema,
            "network_id": self.network.network_id,
            "network_fingerprint": self._network_fingerprint,
            "forecast_issue_time": self.config.forecast_issue_time.isoformat(),
            "provenance_id": self.config.provenance_id,
            "evidence_level": self.config.evidence_level,
            "instrumentation_contract_admitted": self.config.admitted,
            "source_steps_admitted": all_steps_admitted,
            "diagnostic_only": not (self.config.admitted and all_steps_admitted),
        }

    def _build_feature_axis(self) -> list[dict[str, object]]:
        topological_rank = {
            feature: rank for rank, feature in enumerate(self.network.topological_feature_ids)
        }
        return [
            {
                "feature_index": index,
                "feature_id": feature,
                "topological_rank": topological_rank[feature],
                "effective_length_m": self.network.effective_lengths_m[index],
            }
            for index, feature in enumerate(self.network.feature_ids)
        ]

    def _build_edge_axis(self) -> list[dict[str, object]]:
        rows = []
        for source, target in zip(
            self.network.feature_ids,
            self.network.downstream_feature_ids,
            strict=True,
        ):
            if target is None:
                continue
            rows.append(
                {
                    "edge_index": len(rows),
                    "edge_key": f"reach:{source}->reach:{target}",
                    "source_feature_id": source,
                    "target_feature_id": target,
                    "direction_role": "authoritative_network_direction",
                    "edge_admitted": self.network.admitted,
                    "evidence_level": self.network.evidence_level,
                }
            )
        return rows


def write_hash_bound_internal_innovation_artifacts(
    bundle: InternalInnovationTelemetryBundle,
    output_directory: Path,
    *,
    repo_root: Path,
) -> dict[str, object]:
    """Write an immutable artifact set and return its rollout descriptor block."""

    if not isinstance(bundle, InternalInnovationTelemetryBundle):
        raise TypeError("internal_telemetry_bundle_required")
    root = Path(repo_root).resolve()
    output = Path(output_directory).resolve()
    try:
        output.relative_to(root)
    except ValueError as error:
        raise ValueError("internal_telemetry_output_outside_repository") from error
    output.mkdir(parents=True, exist_ok=True)
    descriptors: dict[str, object] = {}
    write_plan: list[tuple[str, Path, dict[str, object], bytes]] = []
    for artifact_name, filename in _ARTIFACT_FILES.items():
        payload = bundle.artifacts[artifact_name]
        body = _canonical_json_bytes(payload)
        path = output / filename
        if path.is_symlink():
            raise FileExistsError("internal_telemetry_artifact_conflict")
        if path.exists():
            if not path.is_file() or path.read_bytes() != body:
                raise FileExistsError("internal_telemetry_artifact_conflict")
        write_plan.append((artifact_name, path, payload, body))
    for artifact_name, path, payload, body in write_plan:
        if not path.exists():
            path.write_bytes(body)
        descriptors[artifact_name] = {
            "path": path.relative_to(root).as_posix(),
            "sha256": hashlib.sha256(body).hexdigest(),
            "size_bytes": len(body),
            "schema": payload["schema"],
        }
    descriptors["alignment_assertions"] = dict(bundle.alignment_assertions)
    descriptors["telemetry_bundle"] = bundle.as_dict()
    return descriptors
