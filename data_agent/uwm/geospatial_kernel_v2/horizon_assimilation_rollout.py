"""Outcome-free horizon-routed state assimilation and conservative rollout."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import numpy as np

from .branching_network import (
    BranchingManningNetworkTransportOperator,
    BranchingNetworkTransportConfig,
    DirectedReachNetwork,
)
from .causal_observation_update import (
    CausalDischargeObservation,
    CausalObservationUpdateConfig,
)
from .contracts import (
    ActionBoundaryFlux,
    ForcingFlux,
    ReachForcingSupport,
    ReachHydraulicGeometry,
    StockState,
)
from .forecast_closure import (
    CausalStateDependentManningForecastClosure,
    ForecastClosureConfig,
    StateDependentManningClosureParameters,
)
from .graph_state_estimation import (
    DETERMINISTIC_DISTANCE_LOCALIZED_GAIN_SEMANTICS,
    DETERMINISTIC_MAINSTEM_GAIN_SEMANTICS,
    GraphStateUpdateParameters,
)
from .horizon_assimilation_policy import (
    HORIZON_ASSIMILATION_MODES,
    HORIZON_ASSIMILATION_SUPPORTED_HORIZONS_HOURS,
    HorizonAssimilationPolicy,
)

HORIZON_ASSIMILATION_ROLLOUT_SCHEMA = (
    "gwm.geospatial_kernel.horizon_assimilation_rollout.v1"
)
MAINSTEM_RATIO_MODE = "mainstem_ratio_observation_update"
LINEAR_DISTANCE_MODE = "linear_distance_localized_mainstem_update"
QUADRATIC_DISTANCE_MODE = "quadratic_distance_localized_mainstem_update"
GRAPH_UPDATE_MODES = {
    MAINSTEM_RATIO_MODE,
    LINEAR_DISTANCE_MODE,
    QUADRATIC_DISTANCE_MODE,
}
SUPPORTED_ASSIMILATION_MODES = HORIZON_ASSIMILATION_MODES + (MAINSTEM_RATIO_MODE,)


def _aware(value: datetime) -> bool:
    return value.tzinfo is not None and value.utcoffset() is not None


@dataclass(frozen=True)
class AssimilationModeRollout:
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
    closure_admitted: bool
    diagnostic_only: bool

    def prediction_for_horizon(self, horizon_hours: int) -> float:
        try:
            index = HORIZON_ASSIMILATION_SUPPORTED_HORIZONS_HOURS.index(
                horizon_hours
            )
        except ValueError as exc:
            raise ValueError("horizon_assimilation_rollout_horizon_unsupported") from exc
        return self.predictions_m3s[index]

    def as_dict(self) -> dict[str, object]:
        return {
            "mode": self.mode,
            "predictions_m3s_by_horizon_hours": {
                str(horizon): self.predictions_m3s[index]
                for index, horizon in enumerate(
                    HORIZON_ASSIMILATION_SUPPORTED_HORIZONS_HOURS
                )
            },
            "observation_assimilated": self.observation_assimilated,
            "observation_fallback_reason": self.observation_fallback_reason,
            "prior_storage_m3": self.prior_storage_m3,
            "analysis_storage_m3": self.analysis_storage_m3,
            "analysis_increment_m3": self.analysis_increment_m3,
            "graph_analysis_increment_m3": self.graph_analysis_increment_m3,
            "graph_updated_feature_count": self.graph_updated_feature_count,
            "branch_analysis_increment_max_abs_m3": (
                self.branch_analysis_increment_max_abs_m3
            ),
            "analysis_ledger_passed": self.analysis_ledger_passed,
            "physical_mass_balance_check_count": (
                self.physical_mass_balance_check_count
            ),
            "physical_mass_balance_pass_count": self.physical_mass_balance_pass_count,
            "closure_admitted": self.closure_admitted,
            "diagnostic_only": self.diagnostic_only,
        }


@dataclass(frozen=True)
class HorizonAssimilationRolloutResult:
    system_id: str
    issue_time: datetime
    issue_observed_outlet_m3s: float | None
    policy: HorizonAssimilationPolicy
    mode_rollouts: tuple[AssimilationModeRollout, ...]
    graph_gain_profiles: dict[str, dict[str, object]]

    def __post_init__(self) -> None:
        if (
            not self.system_id.strip()
            or not _aware(self.issue_time)
            or tuple(value.mode for value in self.mode_rollouts)
            != HORIZON_ASSIMILATION_MODES
        ):
            raise ValueError("horizon_assimilation_rollout_result_invalid")

    def mode_rollout(self, mode: str) -> AssimilationModeRollout:
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
            value.physical_mass_balance_pass_count
            == value.physical_mass_balance_check_count
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
                "predicted_outlet_m3s": self.selected_prediction_for_horizon(
                    horizon
                ),
            }
            for horizon in HORIZON_ASSIMILATION_SUPPORTED_HORIZONS_HOURS
        }
        return {
            "schema": HORIZON_ASSIMILATION_ROLLOUT_SCHEMA,
            "system_id": self.system_id,
            "issue_time_utc": self.issue_time.isoformat(),
            "issue_observed_outlet_m3s": self.issue_observed_outlet_m3s,
            "policy": self.policy.as_dict(),
            "selected_predictions": selected,
            "mode_rollouts": [value.as_dict() for value in self.mode_rollouts],
            "graph_gain_profiles": self.graph_gain_profiles,
            "execution_gates": {
                "all_analysis_ledgers_passed": self.all_analysis_ledgers_passed,
                "all_physical_mass_balances_passed": (
                    self.all_physical_mass_balances_passed
                ),
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
            },
        }


def execute_horizon_assimilation_issue(
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
) -> HorizonAssimilationRolloutResult:
    """Execute every frozen constituent while exposing only routed predictions."""

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
    mode_results: list[AssimilationModeRollout] = []
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
        state = closure.analysis_stock
        predictions: dict[int, float] = {}
        mass_checks: list[bool] = []
        for offset in range(max(HORIZON_ASSIMILATION_SUPPORTED_HORIZONS_HOURS)):
            action_values = np.zeros(len(network.feature_ids), dtype=float)
            action_values[action_index] = action_release_m3s_by_step[offset]
            step = operator.step(
                state,
                closure.effective_geometry,
                action=ActionBoundaryFlux(
                    values=tuple(float(value) for value in action_values),
                    unit="m3 s-1",
                    provenance_id=(
                        f"{system_id}:horizon-assimilation:{mode}:action:{offset}"
                    ),
                ),
                forcing=ForcingFlux(
                    values=q_lateral_m3s_by_step[offset],
                    unit="m3 s-1",
                    provenance_id=(
                        f"{system_id}:horizon-assimilation:{mode}:forcing:{offset}"
                    ),
                    modeled=True,
                ),
                forcing_support=forcing_support,
            )
            state = step.next_stock
            mass_checks.append(
                abs(step.global_mass_balance_residual_m3)
                <= step.numeric_mass_tolerance_m3
            )
            horizon = offset + 1
            if horizon in HORIZON_ASSIMILATION_SUPPORTED_HORIZONS_HOURS:
                predictions[horizon] = step.outlet_mean_flow_m3s
        result = AssimilationModeRollout(
            mode=mode,
            predictions_m3s=tuple(
                predictions[value]
                for value in HORIZON_ASSIMILATION_SUPPORTED_HORIZONS_HOURS
            ),
            observation_assimilated=bool(mode_observation),
            observation_fallback_reason=(
                fallback_reason if mode != "nominal" else None
            ),
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
            closure_admitted=closure.closure_admitted,
            diagnostic_only=closure.diagnostic_only,
        )
        if (
            not result.analysis_ledger_passed
            or result.physical_mass_balance_pass_count
            != result.physical_mass_balance_check_count
            or (mode in GRAPH_UPDATE_MODES and branch_max != 0.0)
            or (mode in GRAPH_UPDATE_MODES and not result.diagnostic_only)
            or (mode not in GRAPH_UPDATE_MODES and not result.closure_admitted)
        ):
            raise RuntimeError("horizon_assimilation_rollout_execution_gate_failed")
        mode_results.append(result)
    return HorizonAssimilationRolloutResult(
        system_id=system_id,
        issue_time=issue_time,
        issue_observed_outlet_m3s=issue_observed_outlet_m3s,
        policy=policy,
        mode_rollouts=tuple(mode_results),
        graph_gain_profiles=profiles,
    )


def build_state_assimilation_closures(
    *,
    system_id: str,
    network: DirectedReachNetwork,
    reference_storage_m3: tuple[float, ...],
    mainstem_feature_ids: tuple[int, ...],
    reference_time: datetime,
    modes: tuple[str, ...],
) -> tuple[
    dict[str, CausalStateDependentManningForecastClosure],
    dict[str, dict[str, object]],
]:
    if (
        not system_id.strip()
        or not _aware(reference_time)
        or not modes
        or len(modes) != len(set(modes))
        or any(mode not in SUPPORTED_ASSIMILATION_MODES for mode in modes)
    ):
        raise ValueError("horizon_assimilation_closure_inputs_invalid")
    reference = np.asarray(reference_storage_m3, dtype=float)
    if (
        reference.shape != (len(network.feature_ids),)
        or not np.isfinite(reference).all()
        or bool((reference <= 0.0).any())
    ):
        raise ValueError("horizon_assimilation_reference_storage_invalid")
    parameters = StateDependentManningClosureParameters(
        feature_ids=network.feature_ids,
        reference_storage_m3=tuple(float(value) for value in reference),
        log_roughness_intercept=(0.0,) * len(network.feature_ids),
        log_roughness_storage_slope=(0.0,) * len(network.feature_ids),
        training_system_ids=(f"{system_id}:nwm-v3-initial-modeled-state",),
        training_data_start=reference_time,
        training_data_end=reference_time,
        provenance_id=f"{system_id}:identity-manning-closure:no-outcome-fit",
        evidence_level="derived",
        admitted=True,
        outcome_calibrated=False,
    )
    config = ForecastClosureConfig(
        observation_update=CausalObservationUpdateConfig(
            analysis_gain=1.0,
            maximum_observation_age_seconds=0.0,
        ),
        minimum_roughness_multiplier=1.0,
        maximum_roughness_multiplier=1.0,
        allow_unadmitted_components_for_diagnostics=True,
    )
    closures = {
        "nominal": CausalStateDependentManningForecastClosure(parameters, config),
        "outlet_only_observation_update": CausalStateDependentManningForecastClosure(
            parameters,
            config,
        ),
    }
    gain_rows, reports = graph_gain_profiles(
        network=network,
        mainstem_feature_ids=mainstem_feature_ids,
        modes=modes,
    )
    for mode, gain_row in gain_rows.items():
        graph_parameters = GraphStateUpdateParameters(
            feature_ids=network.feature_ids,
            observation_feature_ids=(network.outlet_feature_id,),
            reference_storage_m3=tuple(float(value) for value in reference),
            log_storage_gain_rows=(gain_row,),
            training_system_ids=(f"{system_id}:authoritative-mainstem-construction",),
            training_data_start=reference_time,
            training_data_end=reference_time,
            provenance_id=f"{system_id}:{mode}:no-outcome-fit",
            evidence_level="candidate",
            admitted=False,
            modeled_state_based=True,
            possible_nudging=True,
            outcome_calibrated=False,
            gain_semantics=(
                DETERMINISTIC_MAINSTEM_GAIN_SEMANTICS
                if mode == MAINSTEM_RATIO_MODE
                else DETERMINISTIC_DISTANCE_LOCALIZED_GAIN_SEMANTICS
            ),
        )
        closures[mode] = CausalStateDependentManningForecastClosure(
            parameters,
            config,
            graph_state_update_parameters=graph_parameters,
        )
    return {mode: closures[mode] for mode in modes}, reports


def graph_gain_profiles(
    *,
    network: DirectedReachNetwork,
    mainstem_feature_ids: tuple[int, ...],
    modes: tuple[str, ...],
) -> tuple[dict[str, tuple[float, ...]], dict[str, dict[str, object]]]:
    _validate_mainstem(network, mainstem_feature_ids)
    graph_modes = tuple(mode for mode in modes if mode in GRAPH_UPDATE_MODES)
    if not graph_modes:
        return {}, {}
    feature_index = {
        feature_id: index for index, feature_id in enumerate(network.feature_ids)
    }
    lengths = np.asarray(
        [
            network.effective_lengths_m[feature_index[value]]
            for value in mainstem_feature_ids
        ],
        dtype=float,
    )
    downstream_distance = np.asarray(
        [
            float(lengths[index + 1 :].sum())
            for index in range(len(mainstem_feature_ids))
        ],
        dtype=float,
    )
    maximum_distance = float(downstream_distance[0])
    if not np.isfinite(maximum_distance) or maximum_distance <= 0.0:
        raise ValueError("horizon_assimilation_mainstem_distance_required")
    linear = np.clip(1.0 - downstream_distance / maximum_distance, 0.0, 1.0)
    linear[-1] = 0.0
    profile_values = {
        MAINSTEM_RATIO_MODE: np.where(
            np.arange(len(mainstem_feature_ids))
            == len(mainstem_feature_ids) - 1,
            0.0,
            1.0,
        ),
        LINEAR_DISTANCE_MODE: linear,
        QUADRATIC_DISTANCE_MODE: linear**2,
    }
    rows: dict[str, tuple[float, ...]] = {}
    reports: dict[str, dict[str, object]] = {}
    for mode in graph_modes:
        gains = profile_values[mode]
        by_feature = dict(zip(mainstem_feature_ids, gains, strict=True))
        row = tuple(float(by_feature.get(value, 0.0)) for value in network.feature_ids)
        positive = [value for value in row if value > 0.0]
        if not positive:
            raise ValueError("horizon_assimilation_positive_graph_gain_required")
        rows[mode] = row
        reports[mode] = {
            "family": mode,
            "outcome_fitted": False,
            "distance_basis": "authoritative_mainstem_effective_length",
            "distance_origin": "outlet_support_end",
            "maximum_upstream_distance_m": maximum_distance,
            "positive_gain_feature_count": len(positive),
            "minimum_positive_gain": min(positive),
            "maximum_gain": max(positive),
            "mainstem_feature_gains": {
                str(feature_id): float(gain)
                for feature_id, gain in zip(
                    mainstem_feature_ids,
                    gains,
                    strict=True,
                )
            },
        }
    return rows, reports


def _validate_issue_inputs(
    *,
    system_id: str,
    network: DirectedReachNetwork,
    modeled_stock: StockState,
    reference_storage_m3: tuple[float, ...],
    mainstem_feature_ids: tuple[int, ...],
    reference_time: datetime,
    issue_time: datetime,
    issue_observed_outlet_m3s: float | None,
    observation_available_at: datetime | None,
    action_release_m3s_by_step: tuple[float, ...],
    q_lateral_m3s_by_step: tuple[tuple[float, ...], ...],
) -> None:
    horizon = max(HORIZON_ASSIMILATION_SUPPORTED_HORIZONS_HOURS)
    action = np.asarray(action_release_m3s_by_step, dtype=float)
    forcing = np.asarray(q_lateral_m3s_by_step, dtype=float)
    reference = np.asarray(reference_storage_m3, dtype=float)
    observation_invalid = (
        issue_observed_outlet_m3s is not None
        and not np.isfinite(float(issue_observed_outlet_m3s))
    )
    availability_invalid = (
        issue_observed_outlet_m3s is None
        and observation_available_at is not None
    ) or (
        issue_observed_outlet_m3s is not None
        and (
            observation_available_at is None
            or not _aware(observation_available_at)
            or observation_available_at != issue_time
        )
    )
    if (
        not system_id.strip()
        or not _aware(reference_time)
        or not _aware(issue_time)
        or reference_time > issue_time
        or len(modeled_stock.values) != len(network.feature_ids)
        or reference.shape != (len(network.feature_ids),)
        or not np.isfinite(reference).all()
        or bool((reference <= 0.0).any())
        or action.shape != (horizon,)
        or not np.isfinite(action).all()
        or bool((action < 0.0).any())
        or forcing.shape != (horizon, len(network.feature_ids))
        or not np.isfinite(forcing).all()
        or observation_invalid
        or availability_invalid
    ):
        raise ValueError("horizon_assimilation_issue_inputs_invalid")
    _validate_mainstem(network, mainstem_feature_ids)


def _validate_mainstem(
    network: DirectedReachNetwork,
    mainstem_feature_ids: tuple[int, ...],
) -> None:
    if (
        len(mainstem_feature_ids) < 2
        or len(mainstem_feature_ids) != len(set(mainstem_feature_ids))
        or mainstem_feature_ids[0] != network.action_entry_feature_ids[0]
        or mainstem_feature_ids[-1] != network.outlet_feature_id
        or not set(mainstem_feature_ids).issubset(network.feature_ids)
    ):
        raise ValueError("horizon_assimilation_mainstem_invalid")
    downstream = dict(
        zip(network.feature_ids, network.downstream_feature_ids, strict=True)
    )
    if any(
        downstream[left] != right
        for left, right in zip(
            mainstem_feature_ids,
            mainstem_feature_ids[1:],
            strict=False,
        )
    ):
        raise ValueError("horizon_assimilation_mainstem_not_contiguous")


def _observation_fallback_reason(value: float | None) -> str | None:
    if value is None:
        return "missing_issue_observation"
    if value < 0.0:
        return "negative_discharge_outside_forward_manning_domain"
    return None
