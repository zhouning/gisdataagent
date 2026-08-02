"""Post-freeze shared-runtime conformance for the frozen horizon rollout."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

import numpy as np

from data_agent.uwm.geospatial_kernel import (
    GEOSPATIAL_KERNEL_RUNTIME_SCHEMA,
    GeospatialKernelRuntime,
    KernelAction,
    summarize_kernel_steps,
)

from .branching_network import (
    BranchingManningNetworkTransportOperator,
    BranchingNetworkTransportConfig,
    DirectedReachNetwork,
)
from .causal_observation_update import CausalDischargeObservation
from .contracts import (
    ActionBoundaryFlux,
    ForcingFlux,
    ReachForcingSupport,
    ReachHydraulicGeometry,
    StockState,
)
from .horizon_assimilation_policy import (
    HORIZON_ASSIMILATION_MODES,
    HORIZON_ASSIMILATION_SUPPORTED_HORIZONS_HOURS,
    HorizonAssimilationPolicy,
)
from .horizon_assimilation_rollout import (
    GRAPH_UPDATE_MODES,
    _aware,
    _observation_fallback_reason,
    _validate_issue_inputs,
    build_state_assimilation_closures,
)
from .runtime_adapter import (
    BRANCHING_HYDRAULIC_RUNTIME_ADAPTER,
    BranchingHydraulicFluxAction,
    BranchingHydraulicRuntimeAdapter,
    branching_hydraulic_runtime_state,
)

RUNTIME_HORIZON_ASSIMILATION_ROLLOUT_SCHEMA = (
    "gwm.geospatial_kernel.horizon_assimilation_runtime_rollout.v1"
)


@dataclass(frozen=True)
class RuntimeAssimilationModeRollout:
    mode: str
    predictions_m3s: tuple[float, ...]
    observation_assimilated: bool
    observation_fallback_reason: str | None
    prior_storage_m3: float
    analysis_storage_m3: float
    analysis_increment_m3: float
    graph_analysis_increment_m3: float
    graph_updated_feature_count: int
    branch_analysis_increment_max_abs_m3: float
    analysis_ledger_passed: bool
    physical_mass_balance_check_count: int
    physical_mass_balance_pass_count: int
    kernel_runtime_adapter_id: str
    kernel_runtime_step_count: int
    kernel_runtime_completed_step_count: int
    kernel_runtime_admitted_step_count: int
    kernel_runtime_projected_step_count: int
    kernel_runtime_execution_summary: dict[str, object]
    closure_admitted: bool
    diagnostic_only: bool

    def prediction_for_horizon(self, horizon_hours: int) -> float:
        try:
            index = HORIZON_ASSIMILATION_SUPPORTED_HORIZONS_HOURS.index(horizon_hours)
        except ValueError as exc:
            raise ValueError("horizon_assimilation_rollout_horizon_unsupported") from exc
        return self.predictions_m3s[index]

    def as_dict(self) -> dict[str, object]:
        return {
            "mode": self.mode,
            "predictions_m3s_by_horizon_hours": {
                str(horizon): self.predictions_m3s[index]
                for index, horizon in enumerate(HORIZON_ASSIMILATION_SUPPORTED_HORIZONS_HOURS)
            },
            "observation_assimilated": self.observation_assimilated,
            "observation_fallback_reason": self.observation_fallback_reason,
            "prior_storage_m3": self.prior_storage_m3,
            "analysis_storage_m3": self.analysis_storage_m3,
            "analysis_increment_m3": self.analysis_increment_m3,
            "graph_analysis_increment_m3": self.graph_analysis_increment_m3,
            "graph_updated_feature_count": self.graph_updated_feature_count,
            "branch_analysis_increment_max_abs_m3": (self.branch_analysis_increment_max_abs_m3),
            "analysis_ledger_passed": self.analysis_ledger_passed,
            "physical_mass_balance_check_count": (self.physical_mass_balance_check_count),
            "physical_mass_balance_pass_count": self.physical_mass_balance_pass_count,
            "kernel_runtime": {
                "schema": GEOSPATIAL_KERNEL_RUNTIME_SCHEMA,
                "adapter_id": self.kernel_runtime_adapter_id,
                "step_count": self.kernel_runtime_step_count,
                "completed_step_count": self.kernel_runtime_completed_step_count,
                "admitted_step_count": self.kernel_runtime_admitted_step_count,
                "projected_step_count": self.kernel_runtime_projected_step_count,
                "execution_summary": self.kernel_runtime_execution_summary,
            },
            "closure_admitted": self.closure_admitted,
            "diagnostic_only": self.diagnostic_only,
        }


@dataclass(frozen=True)
class RuntimeHorizonAssimilationRolloutResult:
    system_id: str
    issue_time: datetime
    issue_observed_outlet_m3s: float | None
    policy: HorizonAssimilationPolicy
    mode_rollouts: tuple[RuntimeAssimilationModeRollout, ...]
    graph_gain_profiles: dict[str, dict[str, object]]

    def __post_init__(self) -> None:
        if (
            not self.system_id.strip()
            or not _aware(self.issue_time)
            or tuple(value.mode for value in self.mode_rollouts) != HORIZON_ASSIMILATION_MODES
        ):
            raise ValueError("horizon_assimilation_rollout_result_invalid")

    def mode_rollout(self, mode: str) -> RuntimeAssimilationModeRollout:
        try:
            return next(value for value in self.mode_rollouts if value.mode == mode)
        except StopIteration as exc:
            raise ValueError("horizon_assimilation_rollout_mode_unsupported") from exc

    def selected_prediction_for_horizon(self, horizon_hours: int) -> float:
        mode = self.policy.mode_for_horizon(horizon_hours)
        return self.mode_rollout(mode).prediction_for_horizon(horizon_hours)

    @property
    def all_analysis_ledgers_passed(self) -> bool:
        return all(value.analysis_ledger_passed for value in self.mode_rollouts)

    @property
    def all_physical_mass_balances_passed(self) -> bool:
        return all(
            value.physical_mass_balance_pass_count == value.physical_mass_balance_check_count
            for value in self.mode_rollouts
        )

    @property
    def all_kernel_runtime_steps_completed(self) -> bool:
        return all(
            value.kernel_runtime_step_count == value.kernel_runtime_completed_step_count
            and value.kernel_runtime_completed_step_count
            == value.kernel_runtime_admitted_step_count + value.kernel_runtime_projected_step_count
            for value in self.mode_rollouts
        )

    @property
    def localized_updates_preserved_all_branch_states(self) -> bool:
        return all(
            value.branch_analysis_increment_max_abs_m3 == 0.0
            for value in self.mode_rollouts
            if value.mode in GRAPH_UPDATE_MODES
        )

    def as_dict(self) -> dict[str, object]:
        selected = {
            str(horizon): {
                "mode": self.policy.mode_for_horizon(horizon),
                "predicted_outlet_m3s": self.selected_prediction_for_horizon(horizon),
            }
            for horizon in HORIZON_ASSIMILATION_SUPPORTED_HORIZONS_HOURS
        }
        return {
            "schema": RUNTIME_HORIZON_ASSIMILATION_ROLLOUT_SCHEMA,
            "system_id": self.system_id,
            "issue_time_utc": self.issue_time.isoformat(),
            "issue_observed_outlet_m3s": self.issue_observed_outlet_m3s,
            "policy": self.policy.as_dict(),
            "selected_predictions": selected,
            "mode_rollouts": [value.as_dict() for value in self.mode_rollouts],
            "graph_gain_profiles": self.graph_gain_profiles,
            "execution_gates": {
                "all_analysis_ledgers_passed": self.all_analysis_ledgers_passed,
                "all_physical_mass_balances_passed": (self.all_physical_mass_balances_passed),
                "all_kernel_runtime_steps_completed": (self.all_kernel_runtime_steps_completed),
                "localized_updates_preserved_all_branch_states": (
                    self.localized_updates_preserved_all_branch_states
                ),
            },
            "data_isolation": {
                "future_target_argument_accepted": False,
                "score_or_loss_argument_accepted": False,
                "future_target_used": False,
                "scores_computed": False,
            },
            "claim_boundary": {
                "candidate_admitted": False,
                "runtime_default_enabled": False,
                "geospatial_kernel_validated": False,
                "shared_runtime_contract_executed": True,
                "post_freeze_runtime_conformance_only": True,
                "frozen_holdout_candidate_modified": False,
            },
        }


def execute_runtime_horizon_assimilation_issue(
    *,
    system_id: str,
    policy: HorizonAssimilationPolicy,
    network: DirectedReachNetwork,
    geometry: ReachHydraulicGeometry,
    modeled_stock: StockState,
    reference_storage_m3: tuple[float, ...],
    mainstem_feature_ids: tuple[int, ...],
    reference_time: datetime,
    issue_time: datetime,
    issue_observed_outlet_m3s: float | None,
    observation_available_at: datetime | None,
    action_release_m3s_by_step: tuple[float, ...],
    q_lateral_m3s_by_step: tuple[tuple[float, ...], ...],
    forcing_support: ReachForcingSupport,
    timestep_seconds: int = 3600,
    integration_substep_seconds: int = 300,
) -> RuntimeHorizonAssimilationRolloutResult:
    """Replay frozen constituents through the runtime without claiming refreeze."""

    _validate_issue_inputs(
        system_id=system_id,
        network=network,
        modeled_stock=modeled_stock,
        reference_storage_m3=reference_storage_m3,
        mainstem_feature_ids=mainstem_feature_ids,
        reference_time=reference_time,
        issue_time=issue_time,
        issue_observed_outlet_m3s=issue_observed_outlet_m3s,
        observation_available_at=observation_available_at,
        action_release_m3s_by_step=action_release_m3s_by_step,
        q_lateral_m3s_by_step=q_lateral_m3s_by_step,
    )
    closures, profiles = build_state_assimilation_closures(
        system_id=system_id,
        network=network,
        reference_storage_m3=reference_storage_m3,
        mainstem_feature_ids=mainstem_feature_ids,
        reference_time=reference_time,
        modes=HORIZON_ASSIMILATION_MODES,
    )
    operator = BranchingManningNetworkTransportOperator(
        network,
        BranchingNetworkTransportConfig(
            timestep_seconds=timestep_seconds,
            integration_substep_seconds=integration_substep_seconds,
            operator_form_admitted=True,
            allow_unadmitted_components_for_diagnostics=True,
        ),
    )
    fallback_reason = _observation_fallback_reason(issue_observed_outlet_m3s)
    observation: tuple[CausalDischargeObservation, ...] = ()
    if fallback_reason is None:
        observation = (
            CausalDischargeObservation(
                feature_id=network.outlet_feature_id,
                discharge_m3s=float(issue_observed_outlet_m3s),
                valid_at=issue_time,
                available_at=observation_available_at,  # type: ignore[arg-type]
                quality_status="approved",
                provenance_id=f"{system_id}:issue-observation:{issue_time.isoformat()}",
                evidence_level="authoritative",
            ),
        )
    mainstem_set = set(mainstem_feature_ids)
    branch_indices = tuple(
        index
        for index, feature_id in enumerate(network.feature_ids)
        if feature_id not in mainstem_set
    )
    action_index = network.feature_ids.index(network.action_entry_feature_ids[0])
    mode_results: list[RuntimeAssimilationModeRollout] = []
    for mode in HORIZON_ASSIMILATION_MODES:
        mode_observation = observation if mode != "nominal" else ()
        closure = closures[mode].prepare(
            network,
            modeled_stock,
            geometry,
            issue_time=issue_time,
            observations=mode_observation,
        )
        prior_total = float(sum(modeled_stock.values))
        analysis_total = float(sum(closure.analysis_stock.values))
        increment = closure.total_analysis_increment_m3
        ledger_residual = analysis_total - prior_total - increment
        ledger_tolerance = 1e-10 * max(
            1.0,
            abs(prior_total),
            abs(analysis_total),
            abs(increment),
        )
        ledger_passed = abs(ledger_residual) <= ledger_tolerance
        branch_max = max(
            (abs(closure.analysis_increment_m3[index]) for index in branch_indices),
            default=0.0,
        )
        update = closure.observation_updates[0] if closure.observation_updates else None
        runtime = GeospatialKernelRuntime(
            BranchingHydraulicRuntimeAdapter(
                operator,
                parameter_ref=(
                    f"{system_id}:horizon-assimilation:{mode}:frozen-branching-transport-config"
                ),
            )
        )
        runtime_state = branching_hydraulic_runtime_state(
            stock=closure.analysis_stock,
            geometry=closure.effective_geometry,
            time_id=issue_time.isoformat(),
            state_ref=f"{system_id}:{mode}:analysis:{issue_time.isoformat()}",
        )
        predictions: dict[int, float] = {}
        mass_checks: list[bool] = []
        runtime_step_results = []
        for offset in range(max(HORIZON_ASSIMILATION_SUPPORTED_HORIZONS_HOURS)):
            action_values = np.zeros(len(network.feature_ids), dtype=float)
            action_values[action_index] = action_release_m3s_by_step[offset]
            source_time = issue_time + timedelta(seconds=offset * timestep_seconds)
            target_time = source_time + timedelta(seconds=timestep_seconds)
            action = KernelAction(
                action_id=f"{system_id}:{mode}:hydraulic-step:{offset}",
                domain=BRANCHING_HYDRAULIC_RUNTIME_ADAPTER.domain,
                source_time=source_time.isoformat(),
                target_time=target_time.isoformat(),
                payload=BranchingHydraulicFluxAction(
                    action=ActionBoundaryFlux(
                        values=tuple(float(value) for value in action_values),
                        unit="m3 s-1",
                        provenance_id=(f"{system_id}:horizon-assimilation:{mode}:action:{offset}"),
                    ),
                    forcing=ForcingFlux(
                        values=q_lateral_m3s_by_step[offset],
                        unit="m3 s-1",
                        provenance_id=(f"{system_id}:horizon-assimilation:{mode}:forcing:{offset}"),
                        modeled=True,
                    ),
                    forcing_support=forcing_support,
                ),
            )
            runtime_step = runtime.step(
                state=runtime_state,
                action=action,
                context=None,
            )
            runtime_step_results.append(runtime_step)
            result = runtime_step.candidate.payload
            runtime_state = runtime_step.next_state
            mass_checks.append(
                abs(result.global_mass_balance_residual_m3) <= result.numeric_mass_tolerance_m3
            )
            horizon = offset + 1
            if horizon in HORIZON_ASSIMILATION_SUPPORTED_HORIZONS_HOURS:
                predictions[horizon] = result.outlet_mean_flow_m3s
        runtime_summary = summarize_kernel_steps(
            adapter=BRANCHING_HYDRAULIC_RUNTIME_ADAPTER,
            expected_step_count=max(HORIZON_ASSIMILATION_SUPPORTED_HORIZONS_HOURS),
            steps=runtime_step_results,
        )
        status_counts = runtime_summary["status_counts"]
        result = RuntimeAssimilationModeRollout(
            mode=mode,
            predictions_m3s=tuple(
                predictions[value] for value in HORIZON_ASSIMILATION_SUPPORTED_HORIZONS_HOURS
            ),
            observation_assimilated=bool(mode_observation),
            observation_fallback_reason=(fallback_reason if mode != "nominal" else None),
            prior_storage_m3=prior_total,
            analysis_storage_m3=analysis_total,
            analysis_increment_m3=increment,
            graph_analysis_increment_m3=(
                0.0 if update is None else update.graph_analysis_increment_m3
            ),
            graph_updated_feature_count=(
                0 if update is None else update.graph_updated_feature_count
            ),
            branch_analysis_increment_max_abs_m3=branch_max,
            analysis_ledger_passed=ledger_passed,
            physical_mass_balance_check_count=len(mass_checks),
            physical_mass_balance_pass_count=sum(mass_checks),
            kernel_runtime_adapter_id=BRANCHING_HYDRAULIC_RUNTIME_ADAPTER.adapter_id,
            kernel_runtime_step_count=int(runtime_summary["expected_step_count"]),
            kernel_runtime_completed_step_count=int(runtime_summary["completed_step_count"]),
            kernel_runtime_admitted_step_count=int(status_counts["admitted"]),
            kernel_runtime_projected_step_count=int(status_counts["projected"]),
            kernel_runtime_execution_summary=runtime_summary,
            closure_admitted=closure.closure_admitted,
            diagnostic_only=closure.diagnostic_only,
        )
        if (
            not result.analysis_ledger_passed
            or result.physical_mass_balance_pass_count != result.physical_mass_balance_check_count
            or result.kernel_runtime_completed_step_count != result.kernel_runtime_step_count
            or result.kernel_runtime_admitted_step_count
            + result.kernel_runtime_projected_step_count
            != result.kernel_runtime_completed_step_count
            or runtime_summary["all_expected_steps_completed"] is not True
            or (mode in GRAPH_UPDATE_MODES and branch_max != 0.0)
            or (mode in GRAPH_UPDATE_MODES and not result.diagnostic_only)
            or (mode not in GRAPH_UPDATE_MODES and not result.closure_admitted)
        ):
            raise RuntimeError("horizon_assimilation_rollout_execution_gate_failed")
        mode_results.append(result)
    return RuntimeHorizonAssimilationRolloutResult(
        system_id=system_id,
        issue_time=issue_time,
        issue_observed_outlet_m3s=issue_observed_outlet_m3s,
        policy=policy,
        mode_rollouts=tuple(mode_results),
        graph_gain_profiles=profiles,
    )
