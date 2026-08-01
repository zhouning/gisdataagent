"""Physical ensemble forecast-analysis-forecast cycle on a river network."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta

import numpy as np

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
from .ensemble_graph_state_estimation import (
    LocalizedEnsembleStateAnalysisResult,
    LocalizedEnsembleStateEstimator,
)

PHYSICAL_ENSEMBLE_MANNING_FORECAST_CYCLE_SCHEMA = (
    "gwm.geospatial_kernel.physical_ensemble_manning_forecast_cycle.v1"
)
REQUIRED_UNCERTAINTY_SOURCES = (
    "initial_storage",
    "manning_roughness",
    "modeled_forcing",
)
GRAPH_PARTITION_ENSEMBLE_SEMANTICS = (
    "normalized_length_weighted_graph_laplacian_low_frequency_sign_partitions"
)


def _aware(value: datetime) -> bool:
    return value.tzinfo is not None and value.utcoffset() is not None


@dataclass(frozen=True)
class PhysicalEnsembleMemberSpec:
    """Explicit physical multipliers for one deterministic ensemble member."""

    member_id: str
    initial_storage_multiplier_by_feature: tuple[float, ...]
    manning_n_multiplier_by_feature: tuple[float, ...]
    action_multiplier_by_feature: tuple[float, ...]
    forcing_multiplier_by_feature: tuple[float, ...]
    nominal: bool = False

    def __post_init__(self) -> None:
        if not self.member_id.strip() or not isinstance(self.nominal, bool):
            raise ValueError("physical_ensemble_member_identity_invalid")
        fields = {
            "initial_storage": np.asarray(
                self.initial_storage_multiplier_by_feature, dtype=float
            ),
            "manning_n": np.asarray(
                self.manning_n_multiplier_by_feature, dtype=float
            ),
            "action": np.asarray(self.action_multiplier_by_feature, dtype=float),
            "forcing": np.asarray(self.forcing_multiplier_by_feature, dtype=float),
        }
        if any(value.ndim != 1 or value.size == 0 for value in fields.values()):
            raise ValueError("physical_ensemble_member_multipliers_required")
        if any(not np.isfinite(value).all() for value in fields.values()):
            raise ValueError("physical_ensemble_member_multipliers_nonfinite")
        if bool((fields["initial_storage"] <= 0.0).any()) or bool(
            (fields["manning_n"] <= 0.0).any()
        ):
            raise ValueError("physical_ensemble_state_multipliers_must_be_positive")
        if bool((fields["action"] < 0.0).any()) or bool(
            (fields["forcing"] < 0.0).any()
        ):
            raise ValueError("physical_ensemble_flux_multipliers_must_be_nonnegative")
        for name, value in fields.items():
            attribute = {
                "initial_storage": "initial_storage_multiplier_by_feature",
                "manning_n": "manning_n_multiplier_by_feature",
                "action": "action_multiplier_by_feature",
                "forcing": "forcing_multiplier_by_feature",
            }[name]
            object.__setattr__(
                self, attribute, tuple(float(item) for item in value)
            )

    def as_dict(self) -> dict[str, object]:
        return {
            "member_id": self.member_id,
            "nominal": self.nominal,
            "initial_storage_multiplier_by_feature": list(
                self.initial_storage_multiplier_by_feature
            ),
            "manning_n_multiplier_by_feature": list(
                self.manning_n_multiplier_by_feature
            ),
            "action_multiplier_by_feature": list(
                self.action_multiplier_by_feature
            ),
            "forcing_multiplier_by_feature": list(
                self.forcing_multiplier_by_feature
            ),
        }


def build_symmetric_physical_ensemble_design(
    *,
    feature_ids: Sequence[int],
    initial_storage_fraction: float,
    manning_n_fraction: float,
    forcing_fraction: float,
) -> tuple[PhysicalEnsembleMemberSpec, ...]:
    """Build a seven-member one-factor-at-a-time design with no hidden priors."""

    features = tuple(feature_ids)
    if (
        not features
        or len(features) != len(set(features))
        or any(
            not isinstance(value, int) or isinstance(value, bool) or value <= 0
            for value in features
        )
    ):
        raise ValueError("physical_ensemble_design_feature_ids_invalid")
    fractions = {
        "initial_storage": float(initial_storage_fraction),
        "manning_n": float(manning_n_fraction),
        "forcing": float(forcing_fraction),
    }
    if any(
        not np.isfinite(value) or value <= 0.0 or value >= 1.0
        for value in fractions.values()
    ):
        raise ValueError("physical_ensemble_design_fraction_outside_open_unit_interval")
    count = len(features)
    ones = (1.0,) * count

    def member(
        member_id: str,
        *,
        initial: float = 1.0,
        roughness: float = 1.0,
        forcing: float = 1.0,
        nominal: bool = False,
    ) -> PhysicalEnsembleMemberSpec:
        return PhysicalEnsembleMemberSpec(
            member_id=member_id,
            initial_storage_multiplier_by_feature=(initial,) * count,
            manning_n_multiplier_by_feature=(roughness,) * count,
            action_multiplier_by_feature=ones,
            forcing_multiplier_by_feature=(forcing,) * count,
            nominal=nominal,
        )

    return (
        member("nominal", nominal=True),
        member("initial_storage_low", initial=1.0 - fractions["initial_storage"]),
        member("initial_storage_high", initial=1.0 + fractions["initial_storage"]),
        member("manning_n_low", roughness=1.0 - fractions["manning_n"]),
        member("manning_n_high", roughness=1.0 + fractions["manning_n"]),
        member("modeled_forcing_low", forcing=1.0 - fractions["forcing"]),
        member("modeled_forcing_high", forcing=1.0 + fractions["forcing"]),
    )


def build_graph_partition_physical_ensemble_design(
    *,
    network: DirectedReachNetwork,
    initial_storage_fraction: float | Sequence[float],
    manning_n_fraction: float | Sequence[float],
    forcing_fraction: float | Sequence[float],
    graph_partition_mode_count: int,
) -> tuple[PhysicalEnsembleMemberSpec, ...]:
    """Add low-frequency graph partitions without changing marginal variance."""

    fractions = {
        "initial_storage": _feature_fraction_array(
            initial_storage_fraction,
            feature_count=len(network.feature_ids),
        ),
        "manning_n": _feature_fraction_array(
            manning_n_fraction,
            feature_count=len(network.feature_ids),
        ),
        "forcing": _feature_fraction_array(
            forcing_fraction,
            feature_count=len(network.feature_ids),
        ),
    }
    if (
        not isinstance(graph_partition_mode_count, int)
        or isinstance(graph_partition_mode_count, bool)
        or graph_partition_mode_count <= 0
        or graph_partition_mode_count >= len(network.feature_ids)
    ):
        raise ValueError("graph_partition_ensemble_mode_count_invalid")

    patterns = (
        np.ones(len(network.feature_ids), dtype=float),
        *_graph_partition_sign_patterns(network, graph_partition_mode_count),
    )
    ones = np.ones(len(network.feature_ids), dtype=float)
    members = [
        PhysicalEnsembleMemberSpec(
            member_id="nominal",
            initial_storage_multiplier_by_feature=tuple(ones),
            manning_n_multiplier_by_feature=tuple(ones),
            action_multiplier_by_feature=tuple(ones),
            forcing_multiplier_by_feature=tuple(ones),
            nominal=True,
        )
    ]
    source_specs = (
        (
            "initial_storage",
            fractions["initial_storage"],
            "initial_storage_multiplier_by_feature",
        ),
        (
            "manning_n",
            fractions["manning_n"],
            "manning_n_multiplier_by_feature",
        ),
        (
            "modeled_forcing",
            fractions["forcing"],
            "forcing_multiplier_by_feature",
        ),
    )
    for source_name, fraction_by_feature, attribute_name in source_specs:
        for pattern_index, pattern in enumerate(patterns):
            if pattern_index == 0:
                pair_names = (
                    f"{source_name}_low",
                    f"{source_name}_high",
                )
            else:
                pair_names = (
                    f"{source_name}_graph_partition_{pattern_index:02d}_minus",
                    f"{source_name}_graph_partition_{pattern_index:02d}_plus",
                )
            for member_id, direction in zip(pair_names, (-1.0, 1.0), strict=True):
                fields = {
                    "initial_storage_multiplier_by_feature": tuple(ones),
                    "manning_n_multiplier_by_feature": tuple(ones),
                    "action_multiplier_by_feature": tuple(ones),
                    "forcing_multiplier_by_feature": tuple(ones),
                }
                fields[attribute_name] = tuple(
                    ones + direction * fraction_by_feature * pattern
                )
                members.append(
                    PhysicalEnsembleMemberSpec(
                        member_id=member_id,
                        **fields,
                    )
                )
    return tuple(members)


def _feature_fraction_array(
    value: float | Sequence[float], *, feature_count: int
) -> np.ndarray:
    if np.isscalar(value):
        fractions = np.full(feature_count, float(value), dtype=float)
    else:
        fractions = np.asarray(value, dtype=float)
    if fractions.shape != (feature_count,):
        raise ValueError("graph_partition_ensemble_fraction_axis_mismatch")
    if (
        not np.isfinite(fractions).all()
        or bool((fractions < 0.0).any())
        or bool((fractions >= 1.0).any())
    ):
        raise ValueError(
            "graph_partition_ensemble_fraction_outside_half_open_unit_interval"
        )
    if not bool((fractions > 0.0).any()):
        raise ValueError("graph_partition_ensemble_fraction_has_no_variation")
    return fractions


def _graph_partition_sign_patterns(
    network: DirectedReachNetwork,
    mode_count: int,
) -> tuple[np.ndarray, ...]:
    count = len(network.feature_ids)
    feature_index = {
        feature_id: index for index, feature_id in enumerate(network.feature_ids)
    }
    adjacency = np.zeros((count, count), dtype=float)
    lengths = np.asarray(network.effective_lengths_m, dtype=float)
    for source_index, downstream_feature_id in enumerate(
        network.downstream_feature_ids
    ):
        if downstream_feature_id is None:
            continue
        target_index = feature_index[downstream_feature_id]
        center_distance = 0.5 * (lengths[source_index] + lengths[target_index])
        weight = 1.0 / center_distance
        adjacency[source_index, target_index] = weight
        adjacency[target_index, source_index] = weight
    degree = adjacency.sum(axis=1)
    if bool((degree <= 0.0).any()):
        raise ValueError("graph_partition_ensemble_network_disconnected")
    inverse_sqrt_degree = 1.0 / np.sqrt(degree)
    laplacian = np.eye(count) - (
        inverse_sqrt_degree[:, None]
        * adjacency
        * inverse_sqrt_degree[None, :]
    )
    eigenvalues, eigenvectors = np.linalg.eigh(laplacian)
    zero_tolerance = 1e-10
    if int(np.count_nonzero(eigenvalues <= zero_tolerance)) != 1:
        raise ValueError("graph_partition_ensemble_network_disconnected")

    canonical_index = feature_index[min(network.feature_ids)]
    patterns: list[np.ndarray] = []
    identities: set[tuple[int, ...]] = set()
    for eigen_index in np.flatnonzero(eigenvalues > zero_tolerance):
        pattern = np.where(eigenvectors[:, eigen_index] >= 0.0, 1, -1)
        if pattern[canonical_index] < 0:
            pattern = -pattern
        identity = tuple(int(value) for value in pattern)
        if len(set(identity)) == 1 or identity in identities:
            continue
        identities.add(identity)
        patterns.append(pattern.astype(float))
        if len(patterns) == mode_count:
            return tuple(patterns)
    raise ValueError("graph_partition_ensemble_unique_modes_unavailable")


@dataclass(frozen=True)
class PhysicalEnsembleManningForecastCycleResult:
    member_specs: tuple[PhysicalEnsembleMemberSpec, ...]
    feature_ids: tuple[int, ...]
    reference_time: datetime
    analysis_time: datetime
    forecast_valid_times: tuple[datetime, ...]
    uncertainty_sources_varied: tuple[tuple[str, bool], ...]
    state_analysis: LocalizedEnsembleStateAnalysisResult
    outlet_flow_ensemble_m3s_by_horizon: tuple[tuple[float, ...], ...]
    outlet_flow_mean_m3s_by_horizon: tuple[float, ...]
    outlet_flow_p05_m3s_by_horizon: tuple[float, ...]
    outlet_flow_median_m3s_by_horizon: tuple[float, ...]
    outlet_flow_p95_m3s_by_horizon: tuple[float, ...]
    physical_mass_balance_check_count_by_member: tuple[int, ...]
    physical_mass_balance_pass_count_by_member: tuple[int, ...]
    maximum_absolute_physical_mass_residual_m3_by_member: tuple[float, ...]
    all_physical_mass_balances_passed: bool
    provenance_id: str

    @property
    def member_ids(self) -> tuple[str, ...]:
        return tuple(value.member_id for value in self.member_specs)

    def as_dict(self) -> dict[str, object]:
        mass_ledgers = [
            {
                "member_id": member_id,
                "check_count": checks,
                "pass_count": passes,
                "maximum_absolute_residual_m3": residual,
            }
            for member_id, checks, passes, residual in zip(
                self.member_ids,
                self.physical_mass_balance_check_count_by_member,
                self.physical_mass_balance_pass_count_by_member,
                self.maximum_absolute_physical_mass_residual_m3_by_member,
                strict=True,
            )
        ]
        return {
            "schema": PHYSICAL_ENSEMBLE_MANNING_FORECAST_CYCLE_SCHEMA,
            "reference_time": self.reference_time.isoformat(),
            "analysis_time": self.analysis_time.isoformat(),
            "forecast_valid_times": [
                value.isoformat() for value in self.forecast_valid_times
            ],
            "feature_ids": list(self.feature_ids),
            "member_specs": [value.as_dict() for value in self.member_specs],
            "uncertainty_sources_varied": dict(self.uncertainty_sources_varied),
            "state_analysis": self.state_analysis.as_dict(),
            "forecast": {
                "outlet_flow_ensemble_m3s_by_horizon": [
                    list(row) for row in self.outlet_flow_ensemble_m3s_by_horizon
                ],
                "outlet_flow_mean_m3s_by_horizon": list(
                    self.outlet_flow_mean_m3s_by_horizon
                ),
                "outlet_flow_p05_m3s_by_horizon": list(
                    self.outlet_flow_p05_m3s_by_horizon
                ),
                "outlet_flow_median_m3s_by_horizon": list(
                    self.outlet_flow_median_m3s_by_horizon
                ),
                "outlet_flow_p95_m3s_by_horizon": list(
                    self.outlet_flow_p95_m3s_by_horizon
                ),
            },
            "mass_ledgers": {
                "analysis_adjustment": self.state_analysis.as_dict()[
                    "mass_adjustment_ledger"
                ],
                "physical_transition_by_member": mass_ledgers,
                "all_physical_mass_balances_passed": (
                    self.all_physical_mass_balances_passed
                ),
            },
            "provenance_id": self.provenance_id,
            "data_isolation": {
                "future_target_argument_accepted": False,
                "score_or_loss_argument_accepted": False,
                "future_target_used": False,
                "scores_computed": False,
            },
            "claim_boundary": {
                "physical_ensemble_cycle_implemented": True,
                "physical_and_analysis_invariants_only": True,
                "forecast_skill_evidence_produced": False,
                "candidate_admitted": False,
                "diagnostic_only": True,
                "runtime_default_enabled": False,
                "geospatial_kernel_validated": False,
                "superiority_claim_supported": False,
            },
        }


class PhysicalEnsembleManningForecastCycle:
    """Propagate physical members, analyze causally, then forecast each member."""

    def __init__(
        self,
        *,
        transport_config: BranchingNetworkTransportConfig,
        state_estimator: LocalizedEnsembleStateEstimator,
    ) -> None:
        if not transport_config.allow_unadmitted_components_for_diagnostics:
            raise ValueError("physical_ensemble_cycle_requires_diagnostic_transport")
        if not state_estimator.config.allow_unadmitted_components_for_diagnostics:
            raise ValueError("physical_ensemble_cycle_requires_diagnostic_estimator")
        self.transport_config = transport_config
        self.state_estimator = state_estimator

    def execute(
        self,
        *,
        network: DirectedReachNetwork,
        base_geometry: ReachHydraulicGeometry,
        initial_stock: StockState,
        member_specs: tuple[PhysicalEnsembleMemberSpec, ...],
        historical_action_m3s_by_step: Sequence[Sequence[float]],
        historical_forcing_m3s_by_step: Sequence[Sequence[float]],
        forecast_action_m3s_by_step: Sequence[Sequence[float]],
        forecast_forcing_m3s_by_step: Sequence[Sequence[float]],
        forcing_support: ReachForcingSupport,
        observations: tuple[CausalDischargeObservation, ...],
        observation_error_std_m3s: Sequence[float],
        reference_time: datetime,
        analysis_time: datetime,
        provenance_id: str,
    ) -> PhysicalEnsembleManningForecastCycleResult:
        """Execute an outcome-free physical ensemble analysis and forecast cycle."""

        historical_action = np.asarray(historical_action_m3s_by_step, dtype=float)
        historical_forcing = np.asarray(historical_forcing_m3s_by_step, dtype=float)
        forecast_action = np.asarray(forecast_action_m3s_by_step, dtype=float)
        forecast_forcing = np.asarray(forecast_forcing_m3s_by_step, dtype=float)
        source_flags = self._validate_inputs(
            network=network,
            base_geometry=base_geometry,
            initial_stock=initial_stock,
            member_specs=member_specs,
            historical_action=historical_action,
            historical_forcing=historical_forcing,
            forecast_action=forecast_action,
            forecast_forcing=forecast_forcing,
            forcing_support=forcing_support,
            reference_time=reference_time,
            analysis_time=analysis_time,
            provenance_id=provenance_id,
        )

        member_geometries = tuple(
            _member_geometry(base_geometry, member, provenance_id)
            for member in member_specs
        )
        issue_stocks: list[StockState] = []
        checks_by_member: list[int] = []
        passes_by_member: list[int] = []
        maximum_residual_by_member: list[float] = []
        operators: list[BranchingManningNetworkTransportOperator] = []
        for member, geometry in zip(member_specs, member_geometries, strict=True):
            operator = BranchingManningNetworkTransportOperator(
                network, self.transport_config
            )
            operators.append(operator)
            stock = StockState(
                values=tuple(
                    float(value * multiplier)
                    for value, multiplier in zip(
                        initial_stock.values,
                        member.initial_storage_multiplier_by_feature,
                        strict=True,
                    )
                ),
                unit="m3",
                provenance_id=f"{provenance_id}:{member.member_id}:initial-stock",
            )
            checks = 0
            passes = 0
            maximum_residual = 0.0
            for step_index in range(historical_action.shape[0]):
                transition = _step_member(
                    operator=operator,
                    stock=stock,
                    geometry=geometry,
                    member=member,
                    action_values=historical_action[step_index],
                    forcing_values=historical_forcing[step_index],
                    forcing_support=forcing_support,
                    provenance_id=f"{provenance_id}:history:{step_index}",
                )
                stock = transition.next_stock
                checks += 1
                passed = abs(transition.global_mass_balance_residual_m3) <= (
                    transition.numeric_mass_tolerance_m3
                )
                passes += int(passed)
                maximum_residual = max(
                    maximum_residual,
                    abs(transition.global_mass_balance_residual_m3),
                )
            issue_stocks.append(stock)
            checks_by_member.append(checks)
            passes_by_member.append(passes)
            maximum_residual_by_member.append(maximum_residual)

        state_analysis = self.state_estimator.analyze(
            network=network,
            geometry=base_geometry,
            forecast_storage_ensemble_m3=tuple(
                value.values for value in issue_stocks
            ),
            observations=observations,
            observation_error_std_m3s=observation_error_std_m3s,
            analysis_time=analysis_time,
            provenance_id=f"{provenance_id}:state-analysis",
            forecast_geometry_ensemble=member_geometries,
        )

        outlet_by_member: list[list[float]] = []
        for member_index, (member, geometry, operator) in enumerate(
            zip(member_specs, member_geometries, operators, strict=True)
        ):
            stock = StockState(
                values=state_analysis.analysis_storage_ensemble_m3[member_index],
                unit="m3",
                provenance_id=f"{provenance_id}:{member.member_id}:analysis-stock",
            )
            member_outlet: list[float] = []
            for step_index in range(forecast_action.shape[0]):
                transition = _step_member(
                    operator=operator,
                    stock=stock,
                    geometry=geometry,
                    member=member,
                    action_values=forecast_action[step_index],
                    forcing_values=forecast_forcing[step_index],
                    forcing_support=forcing_support,
                    provenance_id=f"{provenance_id}:forecast:{step_index}",
                )
                stock = transition.next_stock
                member_outlet.append(transition.outlet_mean_flow_m3s)
                checks_by_member[member_index] += 1
                passed = abs(transition.global_mass_balance_residual_m3) <= (
                    transition.numeric_mass_tolerance_m3
                )
                passes_by_member[member_index] += int(passed)
                maximum_residual_by_member[member_index] = max(
                    maximum_residual_by_member[member_index],
                    abs(transition.global_mass_balance_residual_m3),
                )
            outlet_by_member.append(member_outlet)

        outlet = np.asarray(outlet_by_member, dtype=float).T
        all_mass_passed = all(
            checks == passes
            for checks, passes in zip(checks_by_member, passes_by_member, strict=True)
        )
        if not all_mass_passed:
            raise RuntimeError("physical_ensemble_cycle_mass_balance_failed")
        timestep = float(self.transport_config.timestep_seconds)
        valid_times = tuple(
            analysis_time + timedelta(seconds=timestep * (index + 1))
            for index in range(forecast_action.shape[0])
        )
        return PhysicalEnsembleManningForecastCycleResult(
            member_specs=member_specs,
            feature_ids=network.feature_ids,
            reference_time=reference_time,
            analysis_time=analysis_time,
            forecast_valid_times=valid_times,
            uncertainty_sources_varied=tuple(source_flags.items()),
            state_analysis=state_analysis,
            outlet_flow_ensemble_m3s_by_horizon=_matrix_tuple(outlet),
            outlet_flow_mean_m3s_by_horizon=tuple(
                float(value) for value in outlet.mean(axis=1)
            ),
            outlet_flow_p05_m3s_by_horizon=tuple(
                float(value) for value in np.quantile(outlet, 0.05, axis=1)
            ),
            outlet_flow_median_m3s_by_horizon=tuple(
                float(value) for value in np.quantile(outlet, 0.5, axis=1)
            ),
            outlet_flow_p95_m3s_by_horizon=tuple(
                float(value) for value in np.quantile(outlet, 0.95, axis=1)
            ),
            physical_mass_balance_check_count_by_member=tuple(checks_by_member),
            physical_mass_balance_pass_count_by_member=tuple(passes_by_member),
            maximum_absolute_physical_mass_residual_m3_by_member=tuple(
                maximum_residual_by_member
            ),
            all_physical_mass_balances_passed=True,
            provenance_id=provenance_id,
        )

    def _validate_inputs(
        self,
        *,
        network: DirectedReachNetwork,
        base_geometry: ReachHydraulicGeometry,
        initial_stock: StockState,
        member_specs: tuple[PhysicalEnsembleMemberSpec, ...],
        historical_action: np.ndarray,
        historical_forcing: np.ndarray,
        forecast_action: np.ndarray,
        forecast_forcing: np.ndarray,
        forcing_support: ReachForcingSupport,
        reference_time: datetime,
        analysis_time: datetime,
        provenance_id: str,
    ) -> dict[str, bool]:
        count = len(network.feature_ids)
        if not _aware(reference_time) or not _aware(analysis_time):
            raise ValueError("physical_ensemble_cycle_times_must_be_aware")
        if analysis_time <= reference_time or not provenance_id.strip():
            raise ValueError("physical_ensemble_cycle_time_or_provenance_invalid")
        if base_geometry.feature_ids != network.feature_ids:
            raise ValueError("physical_ensemble_cycle_geometry_axis_invalid")
        if initial_stock.unit != "m3" or len(initial_stock.values) != count:
            raise ValueError("physical_ensemble_cycle_initial_stock_invalid")
        if forcing_support.feature_ids != network.feature_ids:
            raise ValueError("physical_ensemble_cycle_forcing_support_axis_invalid")
        if (
            len(member_specs) < self.state_estimator.config.minimum_ensemble_members
            or len({value.member_id for value in member_specs}) != len(member_specs)
            or sum(value.nominal for value in member_specs) != 1
        ):
            raise ValueError("physical_ensemble_cycle_member_set_invalid")
        for member in member_specs:
            fields = (
                member.initial_storage_multiplier_by_feature,
                member.manning_n_multiplier_by_feature,
                member.action_multiplier_by_feature,
                member.forcing_multiplier_by_feature,
            )
            if any(len(value) != count for value in fields):
                raise ValueError("physical_ensemble_cycle_member_axis_invalid")
            all_nominal = all(
                all(item == 1.0 for item in values) for values in fields
            )
            if member.nominal != all_nominal:
                raise ValueError("physical_ensemble_cycle_nominal_member_invalid")
        matrices = {
            "historical_action": historical_action,
            "historical_forcing": historical_forcing,
            "forecast_action": forecast_action,
            "forecast_forcing": forecast_forcing,
        }
        if any(
            values.ndim != 2
            or values.shape[0] == 0
            or values.shape[1] != count
            or not np.isfinite(values).all()
            or bool((values < 0.0).any())
            for values in matrices.values()
        ):
            raise ValueError("physical_ensemble_cycle_flux_matrix_invalid")
        if historical_action.shape[0] != historical_forcing.shape[0] or (
            forecast_action.shape[0] != forecast_forcing.shape[0]
        ):
            raise ValueError("physical_ensemble_cycle_flux_step_count_mismatch")
        expected_seconds = (
            historical_action.shape[0] * self.transport_config.timestep_seconds
        )
        if abs((analysis_time - reference_time).total_seconds() - expected_seconds) > 1e-6:
            raise ValueError("physical_ensemble_cycle_history_time_axis_invalid")
        action_indices = {
            network.feature_ids.index(value)
            for value in network.action_entry_feature_ids
        }
        if any(
            bool((values[:, index] > 0.0).any())
            for index in range(count)
            if index not in action_indices
            for values in (historical_action, forecast_action)
        ):
            raise ValueError("physical_ensemble_cycle_action_outside_entry")

        flags = {
            "initial_storage": any(
                any(value != 1.0 for value in member.initial_storage_multiplier_by_feature)
                for member in member_specs
            ),
            "manning_roughness": any(
                any(value != 1.0 for value in member.manning_n_multiplier_by_feature)
                for member in member_specs
            ),
            "modeled_forcing": any(
                any(value != 1.0 for value in member.forcing_multiplier_by_feature)
                for member in member_specs
            ),
            "boundary_action": any(
                any(value != 1.0 for value in member.action_multiplier_by_feature)
                for member in member_specs
            ),
        }
        if any(not flags[source] for source in REQUIRED_UNCERTAINTY_SOURCES):
            raise ValueError("physical_ensemble_cycle_required_uncertainty_missing")
        return flags


def _member_geometry(
    base: ReachHydraulicGeometry,
    member: PhysicalEnsembleMemberSpec,
    provenance_id: str,
) -> ReachHydraulicGeometry:
    multiplier = np.asarray(member.manning_n_multiplier_by_feature, dtype=float)
    if bool((multiplier == 1.0).all()):
        return base
    return ReachHydraulicGeometry(
        feature_ids=base.feature_ids,
        bottom_width_m=base.bottom_width_m,
        side_slope_horizontal_per_vertical=(
            base.side_slope_horizontal_per_vertical
        ),
        bed_slope=base.bed_slope,
        manning_n=tuple(
            float(value * factor)
            for value, factor in zip(base.manning_n, multiplier, strict=True)
        ),
        provenance_id=f"{provenance_id}:{member.member_id}:candidate-roughness",
        evidence_level="candidate",
        admitted_as_hydraulic_geometry=False,
    )


def _step_member(
    *,
    operator: BranchingManningNetworkTransportOperator,
    stock: StockState,
    geometry: ReachHydraulicGeometry,
    member: PhysicalEnsembleMemberSpec,
    action_values: np.ndarray,
    forcing_values: np.ndarray,
    forcing_support: ReachForcingSupport,
    provenance_id: str,
):
    action = ActionBoundaryFlux(
        values=tuple(
            float(value * multiplier)
            for value, multiplier in zip(
                action_values,
                member.action_multiplier_by_feature,
                strict=True,
            )
        ),
        unit="m3 s-1",
        provenance_id=f"{provenance_id}:{member.member_id}:action",
    )
    forcing = ForcingFlux(
        values=tuple(
            float(value * multiplier)
            for value, multiplier in zip(
                forcing_values,
                member.forcing_multiplier_by_feature,
                strict=True,
            )
        ),
        unit="m3 s-1",
        provenance_id=f"{provenance_id}:{member.member_id}:forcing",
        modeled=True,
    )
    return operator.step(
        stock,
        geometry,
        action=action,
        forcing=forcing,
        forcing_support=forcing_support,
    )


def _matrix_tuple(values: np.ndarray) -> tuple[tuple[float, ...], ...]:
    return tuple(tuple(float(value) for value in row) for row in values)
