"""Causal, bounded forecast closure for conservative reach-network transport."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
import hashlib
import json
from typing import Protocol

import numpy as np
from scipy.optimize import brentq

from .branching_network import (
    BranchingManningNetworkTransportOperator,
    BranchingNetworkTransportResult,
    DirectedReachNetwork,
    ModeledTributaryBoundaryFlux,
    ObservedInternalBoundaryReplacement,
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
from .graph_state_estimation import GraphStateUpdateParameters


FORECAST_CLOSURE_PARAMETERS_SCHEMA = (
    "gwm.geospatial_kernel.forecast_closure_parameters.v1"
)
FORECAST_CLOSURE_SCHEMA = "gwm.geospatial_kernel.forecast_closure.v1"
FORECAST_CLOSED_BRANCHING_TRANSPORT_SCHEMA = (
    "gwm.geospatial_kernel.forecast_closed_branching_transport.v1"
)

_EVIDENCE_LEVELS = {"authoritative", "derived", "candidate"}


def _aware(value: datetime) -> bool:
    return value.tzinfo is not None and value.utcoffset() is not None


def _network_fingerprint(network: DirectedReachNetwork) -> str:
    body = json.dumps(
        network.as_dict(),
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(body).hexdigest()


def _finite_tuple(values: tuple[float, ...], name: str) -> tuple[float, ...]:
    result = tuple(float(value) for value in values)
    if not result or not np.isfinite(np.asarray(result, dtype=float)).all():
        raise ValueError(f"{name}_must_be_nonempty_and_finite")
    return result


@dataclass(frozen=True)
class StateDependentManningClosureParameters:
    """Frozen parameters for a bounded state-dependent roughness residual."""

    feature_ids: tuple[int, ...]
    reference_storage_m3: tuple[float, ...]
    log_roughness_intercept: tuple[float, ...]
    log_roughness_storage_slope: tuple[float, ...]
    training_system_ids: tuple[str, ...]
    training_data_start: datetime
    training_data_end: datetime
    provenance_id: str
    evidence_level: str
    admitted: bool
    outcome_calibrated: bool

    def __post_init__(self) -> None:
        if not self.feature_ids or any(
            not isinstance(value, int) or isinstance(value, bool) or value <= 0
            for value in self.feature_ids
        ):
            raise ValueError("forecast_closure_feature_ids_must_be_positive_integers")
        if len(self.feature_ids) != len(set(self.feature_ids)):
            raise ValueError("forecast_closure_feature_ids_must_be_unique")
        reference = _finite_tuple(
            self.reference_storage_m3,
            "forecast_closure_reference_storage",
        )
        intercept = _finite_tuple(
            self.log_roughness_intercept,
            "forecast_closure_log_roughness_intercept",
        )
        slope = _finite_tuple(
            self.log_roughness_storage_slope,
            "forecast_closure_log_roughness_storage_slope",
        )
        count = len(self.feature_ids)
        if any(len(values) != count for values in (reference, intercept, slope)):
            raise ValueError("forecast_closure_parameter_axis_mismatch")
        if bool((np.asarray(reference) <= 0.0).any()):
            raise ValueError("forecast_closure_reference_storage_must_be_positive")
        object.__setattr__(self, "reference_storage_m3", reference)
        object.__setattr__(self, "log_roughness_intercept", intercept)
        object.__setattr__(self, "log_roughness_storage_slope", slope)
        if (
            not self.training_system_ids
            or len(self.training_system_ids) != len(set(self.training_system_ids))
            or any(not value.strip() for value in self.training_system_ids)
        ):
            raise ValueError("forecast_closure_training_system_ids_required")
        if not _aware(self.training_data_start) or not _aware(self.training_data_end):
            raise ValueError("forecast_closure_training_times_must_be_timezone_aware")
        if self.training_data_end < self.training_data_start:
            raise ValueError("forecast_closure_training_window_reversed")
        if not self.provenance_id.strip():
            raise ValueError("forecast_closure_parameter_provenance_required")
        if self.evidence_level not in _EVIDENCE_LEVELS:
            raise ValueError("unsupported_forecast_closure_parameter_evidence_level")
        if not isinstance(self.admitted, bool) or not isinstance(
            self.outcome_calibrated, bool
        ):
            raise ValueError("forecast_closure_parameter_flags_must_be_boolean")
        if self.admitted and self.evidence_level == "candidate":
            raise ValueError("candidate_forecast_closure_parameters_cannot_be_admitted")

    def as_dict(self) -> dict[str, object]:
        return {
            "schema": FORECAST_CLOSURE_PARAMETERS_SCHEMA,
            "feature_ids": list(self.feature_ids),
            "reference_storage_m3": list(self.reference_storage_m3),
            "log_roughness_intercept": list(self.log_roughness_intercept),
            "log_roughness_storage_slope": list(
                self.log_roughness_storage_slope
            ),
            "training_system_ids": list(self.training_system_ids),
            "training_data_start": self.training_data_start.isoformat(),
            "training_data_end": self.training_data_end.isoformat(),
            "provenance_id": self.provenance_id,
            "evidence_level": self.evidence_level,
            "admitted": self.admitted,
            "outcome_calibrated": self.outcome_calibrated,
        }


@dataclass(frozen=True)
class ForecastClosureConfig:
    observation_update: CausalObservationUpdateConfig
    minimum_roughness_multiplier: float = 0.5
    maximum_roughness_multiplier: float = 2.0
    allow_unadmitted_components_for_diagnostics: bool = False
    root_relative_tolerance: float = 1e-12
    root_absolute_tolerance_m3: float = 1e-10
    maximum_bracket_expansions: int = 128

    def __post_init__(self) -> None:
        if not isinstance(self.observation_update, CausalObservationUpdateConfig):
            raise TypeError("causal_observation_update_config_required")
        lower = float(self.minimum_roughness_multiplier)
        upper = float(self.maximum_roughness_multiplier)
        if (
            not np.isfinite(lower)
            or not np.isfinite(upper)
            or lower <= 0.0
            or lower > 1.0
            or upper < 1.0
            or lower > upper
        ):
            raise ValueError("forecast_closure_roughness_multiplier_bounds_invalid")
        object.__setattr__(self, "minimum_roughness_multiplier", lower)
        object.__setattr__(self, "maximum_roughness_multiplier", upper)
        if not isinstance(self.allow_unadmitted_components_for_diagnostics, bool):
            raise ValueError("forecast_closure_diagnostic_flag_must_be_boolean")
        if (
            not np.isfinite(self.root_relative_tolerance)
            or self.root_relative_tolerance <= 0.0
        ):
            raise ValueError("forecast_closure_root_rtol_must_be_positive")
        if (
            not np.isfinite(self.root_absolute_tolerance_m3)
            or self.root_absolute_tolerance_m3 <= 0.0
        ):
            raise ValueError("forecast_closure_root_atol_must_be_positive")
        if (
            not isinstance(self.maximum_bracket_expansions, int)
            or isinstance(self.maximum_bracket_expansions, bool)
            or self.maximum_bracket_expansions <= 0
        ):
            raise ValueError(
                "forecast_closure_maximum_bracket_expansions_must_be_positive_integer"
            )


@dataclass(frozen=True)
class NetworkObservationUpdate:
    observation: CausalDischargeObservation
    observation_age_seconds: float
    forecast_discharge_m3s: float
    analysis_discharge_m3s: float
    forecast_storage_m3: float
    observation_equivalent_storage_m3: float
    analysis_storage_m3: float
    analysis_increment_m3: float
    graph_analysis_increment_m3: float
    graph_updated_feature_count: int
    admitted: bool

    def as_dict(self) -> dict[str, object]:
        return {
            "observation": self.observation.as_dict(),
            "observation_age_seconds": self.observation_age_seconds,
            "forecast_discharge_m3s": self.forecast_discharge_m3s,
            "analysis_discharge_m3s": self.analysis_discharge_m3s,
            "forecast_storage_m3": self.forecast_storage_m3,
            "observation_equivalent_storage_m3": (
                self.observation_equivalent_storage_m3
            ),
            "analysis_storage_m3": self.analysis_storage_m3,
            "analysis_increment_m3": self.analysis_increment_m3,
            "graph_analysis_increment_m3": self.graph_analysis_increment_m3,
            "graph_updated_feature_count": self.graph_updated_feature_count,
            "admitted": self.admitted,
        }


@dataclass(frozen=True)
class ForecastClosureResult:
    analysis_stock: StockState
    effective_geometry: ReachHydraulicGeometry
    issue_time: datetime
    feature_ids: tuple[int, ...]
    network_fingerprint: str
    observation_updates: tuple[NetworkObservationUpdate, ...]
    analysis_increment_m3: tuple[float, ...]
    graph_analysis_increment_m3: tuple[float, ...]
    raw_log_roughness_residual: tuple[float, ...]
    applied_log_roughness_residual: tuple[float, ...]
    applied_roughness_multiplier: tuple[float, ...]
    residual_clipped: tuple[bool, ...]
    parameters: StateDependentManningClosureParameters
    graph_state_update_parameters: GraphStateUpdateParameters | None
    network_admitted: bool
    base_geometry_admitted: bool
    parameters_admitted: bool
    graph_parameters_admitted: bool
    observations_admitted: bool
    training_data_precedes_issue_time: bool
    closure_admitted: bool
    diagnostic_only: bool

    @property
    def total_analysis_increment_m3(self) -> float:
        return float(sum(self.analysis_increment_m3))

    def as_dict(self) -> dict[str, object]:
        return {
            "schema": FORECAST_CLOSURE_SCHEMA,
            "issue_time": self.issue_time.isoformat(),
            "feature_ids": list(self.feature_ids),
            "network_fingerprint": self.network_fingerprint,
            "analysis_stock_m3": list(self.analysis_stock.values),
            "analysis_increment_m3": list(self.analysis_increment_m3),
            "graph_analysis_increment_m3": list(
                self.graph_analysis_increment_m3
            ),
            "total_analysis_increment_m3": self.total_analysis_increment_m3,
            "analysis_increment_mass_role": (
                "external_analysis_increment_not_transition_flux"
            ),
            "observation_updates": [
                value.as_dict() for value in self.observation_updates
            ],
            "raw_log_roughness_residual": list(
                self.raw_log_roughness_residual
            ),
            "applied_log_roughness_residual": list(
                self.applied_log_roughness_residual
            ),
            "applied_roughness_multiplier": list(
                self.applied_roughness_multiplier
            ),
            "residual_clipped": list(self.residual_clipped),
            "residual_mass_role": (
                "bounded_constitutive_rate_law_only_no_external_source_sink"
            ),
            "parameters": self.parameters.as_dict(),
            "graph_state_update_parameters": (
                None
                if self.graph_state_update_parameters is None
                else self.graph_state_update_parameters.as_dict()
            ),
            "admission": {
                "network_admitted": self.network_admitted,
                "base_geometry_admitted": self.base_geometry_admitted,
                "parameters_admitted": self.parameters_admitted,
                "graph_parameters_admitted": self.graph_parameters_admitted,
                "observations_admitted": self.observations_admitted,
                "training_data_precedes_issue_time": (
                    self.training_data_precedes_issue_time
                ),
                "closure_admitted": self.closure_admitted,
                "diagnostic_only": self.diagnostic_only,
            },
        }


class ForecastClosure(Protocol):
    """Prepare an analysis state and constitutive law without changing topology."""

    def prepare(
        self,
        network: DirectedReachNetwork,
        stock: StockState,
        geometry: ReachHydraulicGeometry,
        *,
        issue_time: datetime,
        observations: tuple[CausalDischargeObservation, ...] = (),
    ) -> ForecastClosureResult: ...


class CausalStateDependentManningForecastClosure:
    """Reference closure with causal analysis updates and bounded roughness."""

    def __init__(
        self,
        parameters: StateDependentManningClosureParameters,
        config: ForecastClosureConfig,
        graph_state_update_parameters: GraphStateUpdateParameters | None = None,
    ) -> None:
        self.parameters = parameters
        self.config = config
        self.graph_state_update_parameters = graph_state_update_parameters

    def prepare(
        self,
        network: DirectedReachNetwork,
        stock: StockState,
        geometry: ReachHydraulicGeometry,
        *,
        issue_time: datetime,
        observations: tuple[CausalDischargeObservation, ...] = (),
    ) -> ForecastClosureResult:
        self._validate_inputs(network, stock, geometry, issue_time, observations)
        feature_index = {
            feature_id: index for index, feature_id in enumerate(network.feature_ids)
        }
        analysis_values = list(stock.values)
        increments = np.zeros(len(network.feature_ids), dtype=float)
        graph_increments = np.zeros(len(network.feature_ids), dtype=float)
        updates: list[NetworkObservationUpdate] = []
        observations_admitted = True
        for observation in observations:
            index = feature_index[observation.feature_id]
            admitted = self._observation_admitted(observation)
            observations_admitted = observations_admitted and admitted
            length = network.effective_lengths_m[index]
            geometry_values = (
                geometry.bottom_width_m[index],
                geometry.side_slope_horizontal_per_vertical[index],
                geometry.bed_slope[index],
                geometry.manning_n[index],
            )
            forecast_storage = float(analysis_values[index])
            forecast_discharge = _manning_discharge(
                forecast_storage,
                length,
                *geometry_values,
            )
            target_storage = self._storage_for_discharge(
                observation.discharge_m3s,
                length=length,
                geometry_values=geometry_values,
                forecast_storage_m3=forecast_storage,
            )
            analysis_storage = float(
                forecast_storage
                + self.config.observation_update.analysis_gain
                * (target_storage - forecast_storage)
            )
            increment = analysis_storage - forecast_storage
            analysis_values[index] = analysis_storage
            increments[index] += increment
            updates.append(
                NetworkObservationUpdate(
                    observation=observation,
                    observation_age_seconds=float(
                        (issue_time - observation.valid_at).total_seconds()
                    ),
                    forecast_discharge_m3s=forecast_discharge,
                    analysis_discharge_m3s=_manning_discharge(
                        analysis_storage,
                        length,
                        *geometry_values,
                    ),
                    forecast_storage_m3=forecast_storage,
                    observation_equivalent_storage_m3=target_storage,
                    analysis_storage_m3=analysis_storage,
                    analysis_increment_m3=increment,
                    graph_analysis_increment_m3=0.0,
                    graph_updated_feature_count=0,
                    admitted=admitted,
                )
            )

        if self.graph_state_update_parameters is not None:
            graph = self.graph_state_update_parameters
            graph_row = {
                feature_id: row
                for feature_id, row in zip(
                    graph.observation_feature_ids,
                    graph.log_storage_gain_rows,
                    strict=True,
                )
            }
            graph_reference = np.asarray(graph.reference_storage_m3, dtype=float)
            gain = self.config.observation_update.analysis_gain
            for update_index, update in enumerate(updates):
                gain_row = graph_row.get(update.observation.feature_id)
                if gain_row is None:
                    continue
                gauge_index = feature_index[update.observation.feature_id]
                reference_at_gauge = graph_reference[gauge_index]
                innovation = float(
                    np.log1p(
                        update.observation_equivalent_storage_m3
                        / reference_at_gauge
                    )
                    - np.log1p(update.forecast_storage_m3 / reference_at_gauge)
                )
                graph_total = 0.0
                updated_count = 0
                for index, spatial_gain in enumerate(gain_row):
                    if spatial_gain <= 0.0:
                        continue
                    prior_value = float(analysis_values[index])
                    normalized = float(
                        np.log1p(prior_value / graph_reference[index])
                    )
                    analysis_normalized = max(
                        0.0,
                        normalized + float(spatial_gain) * gain * innovation,
                    )
                    analysis_value = float(
                        graph_reference[index] * np.expm1(analysis_normalized)
                    )
                    if not np.isfinite(analysis_value) or analysis_value < 0.0:
                        raise RuntimeError("graph_state_update_nonfinite_analysis")
                    increment = analysis_value - prior_value
                    analysis_values[index] = analysis_value
                    increments[index] += increment
                    graph_increments[index] += increment
                    graph_total += increment
                    updated_count += 1
                updates[update_index] = replace(
                    update,
                    graph_analysis_increment_m3=graph_total,
                    graph_updated_feature_count=updated_count,
                )

        storage = np.asarray(analysis_values, dtype=float)
        reference = np.asarray(self.parameters.reference_storage_m3, dtype=float)
        centered_state = np.log1p(storage / reference) - np.log(2.0)
        with np.errstate(over="ignore", invalid="ignore"):
            raw_log_residual = (
                np.asarray(self.parameters.log_roughness_intercept, dtype=float)
                + np.asarray(
                    self.parameters.log_roughness_storage_slope,
                    dtype=float,
                )
                * centered_state
            )
        if not np.isfinite(raw_log_residual).all():
            raise RuntimeError("forecast_closure_nonfinite_constitutive_residual")
        lower_log = float(np.log(self.config.minimum_roughness_multiplier))
        upper_log = float(np.log(self.config.maximum_roughness_multiplier))
        applied_log_residual = np.clip(raw_log_residual, lower_log, upper_log)
        multipliers = np.exp(applied_log_residual)
        clipped = np.abs(raw_log_residual - applied_log_residual) > 1e-12

        graph_training_precedes_issue = (
            self.graph_state_update_parameters is None
            or self.graph_state_update_parameters.training_data_end < issue_time
        )
        training_precedes_issue = (
            self.parameters.training_data_end < issue_time
            and graph_training_precedes_issue
        )
        parameters_admitted = (
            self.parameters.admitted
            and self.parameters.evidence_level != "candidate"
            and training_precedes_issue
        )
        graph_parameters_admitted = (
            self.graph_state_update_parameters is None
            or (
                self.graph_state_update_parameters.admitted
                and self.graph_state_update_parameters.evidence_level != "candidate"
                and graph_training_precedes_issue
            )
        )
        closure_admitted = (
            network.admitted
            and geometry.admitted_as_hydraulic_geometry
            and parameters_admitted
            and graph_parameters_admitted
            and observations_admitted
        )
        provenance = (
            "forecast_closure|"
            f"stock={_provenance_digest(stock.provenance_id)}|"
            f"geometry={_provenance_digest(geometry.provenance_id)}|"
            f"parameters={_provenance_digest(self.parameters.provenance_id)}|"
            "graph="
            f"{_provenance_digest(self.graph_state_update_parameters.provenance_id) if self.graph_state_update_parameters is not None else 'none'}|"
            f"issue={issue_time.isoformat()}"
        )
        effective_geometry = ReachHydraulicGeometry(
            feature_ids=geometry.feature_ids,
            bottom_width_m=geometry.bottom_width_m,
            side_slope_horizontal_per_vertical=(
                geometry.side_slope_horizontal_per_vertical
            ),
            bed_slope=geometry.bed_slope,
            manning_n=tuple(
                float(value)
                for value in (
                    np.asarray(geometry.manning_n, dtype=float) * multipliers
                )
            ),
            provenance_id=provenance,
            evidence_level=("derived" if closure_admitted else "candidate"),
            admitted_as_hydraulic_geometry=closure_admitted,
        )
        return ForecastClosureResult(
            analysis_stock=StockState(
                tuple(float(value) for value in analysis_values),
                "m3",
                provenance,
            ),
            effective_geometry=effective_geometry,
            issue_time=issue_time,
            feature_ids=network.feature_ids,
            network_fingerprint=_network_fingerprint(network),
            observation_updates=tuple(updates),
            analysis_increment_m3=tuple(float(value) for value in increments),
            graph_analysis_increment_m3=tuple(
                float(value) for value in graph_increments
            ),
            raw_log_roughness_residual=tuple(
                float(value) for value in raw_log_residual
            ),
            applied_log_roughness_residual=tuple(
                float(value) for value in applied_log_residual
            ),
            applied_roughness_multiplier=tuple(
                float(value) for value in multipliers
            ),
            residual_clipped=tuple(bool(value) for value in clipped),
            parameters=self.parameters,
            graph_state_update_parameters=self.graph_state_update_parameters,
            network_admitted=network.admitted,
            base_geometry_admitted=geometry.admitted_as_hydraulic_geometry,
            parameters_admitted=parameters_admitted,
            graph_parameters_admitted=graph_parameters_admitted,
            observations_admitted=observations_admitted,
            training_data_precedes_issue_time=training_precedes_issue,
            closure_admitted=closure_admitted,
            diagnostic_only=not closure_admitted,
        )

    def _validate_inputs(
        self,
        network: DirectedReachNetwork,
        stock: StockState,
        geometry: ReachHydraulicGeometry,
        issue_time: datetime,
        observations: tuple[CausalDischargeObservation, ...],
    ) -> None:
        if not isinstance(network, DirectedReachNetwork):
            raise TypeError("directed_reach_network_required")
        if not isinstance(stock, StockState):
            raise TypeError("stock_state_required")
        if not isinstance(geometry, ReachHydraulicGeometry):
            raise TypeError("reach_hydraulic_geometry_required")
        if not _aware(issue_time):
            raise ValueError("forecast_closure_issue_time_must_be_timezone_aware")
        if stock.unit != "m3" or len(stock.values) != len(network.feature_ids):
            raise ValueError("forecast_closure_stock_axis_or_unit_mismatch")
        if geometry.feature_ids != network.feature_ids:
            raise ValueError("forecast_closure_geometry_feature_axis_mismatch")
        if self.parameters.feature_ids != network.feature_ids:
            raise ValueError("forecast_closure_parameter_feature_axis_mismatch")
        if self.parameters.training_data_end >= issue_time:
            raise ValueError("forecast_closure_training_data_not_before_issue_time")
        graph = self.graph_state_update_parameters
        if graph is not None:
            if graph.feature_ids != network.feature_ids:
                raise ValueError("graph_state_update_feature_axis_mismatch")
            if graph.training_data_end >= issue_time:
                raise ValueError("graph_state_update_training_data_not_before_issue_time")
            self._validate_graph_support(network, graph)
        if not isinstance(observations, tuple) or any(
            not isinstance(value, CausalDischargeObservation)
            for value in observations
        ):
            raise TypeError("causal_discharge_observation_tuple_required")
        observed_features = tuple(value.feature_id for value in observations)
        if len(observed_features) != len(set(observed_features)):
            raise ValueError("forecast_closure_one_observation_per_feature_required")
        feature_set = set(network.feature_ids)
        for observation in observations:
            if observation.feature_id not in feature_set:
                raise ValueError("forecast_closure_observation_feature_outside_network")
            if observation.valid_at > issue_time:
                raise ValueError("future_observation_valid_time_forbidden")
            if observation.available_at > issue_time:
                raise ValueError("observation_not_yet_available_at_analysis_time")
            age = float((issue_time - observation.valid_at).total_seconds())
            if age > self.config.observation_update.maximum_observation_age_seconds:
                raise ValueError("causal_observation_exceeds_maximum_age")
            if (
                not self._observation_admitted(observation)
                and not self.config.allow_unadmitted_components_for_diagnostics
            ):
                raise ValueError(
                    "unadmitted_forecast_closure_observation_requires_diagnostic_mode"
                )
        base_admitted = (
            network.admitted
            and geometry.admitted_as_hydraulic_geometry
            and self.parameters.admitted
            and self.parameters.evidence_level != "candidate"
            and (
                graph is None
                or (graph.admitted and graph.evidence_level != "candidate")
            )
        )
        if (
            not base_admitted
            and not self.config.allow_unadmitted_components_for_diagnostics
        ):
            raise ValueError(
                "unadmitted_forecast_closure_components_require_diagnostic_mode"
            )

    @staticmethod
    def _validate_graph_support(
        network: DirectedReachNetwork,
        graph: GraphStateUpdateParameters,
    ) -> None:
        downstream = dict(
            zip(
                network.feature_ids,
                network.downstream_feature_ids,
                strict=True,
            )
        )
        for observation_feature_id, gain_row in zip(
            graph.observation_feature_ids,
            graph.log_storage_gain_rows,
            strict=True,
        ):
            for source_feature_id, gain in zip(
                network.feature_ids,
                gain_row,
                strict=True,
            ):
                if gain <= 0.0:
                    continue
                current: int | None = source_feature_id
                visited: set[int] = set()
                while current is not None and current != observation_feature_id:
                    if current in visited:
                        raise RuntimeError("graph_state_update_network_cycle_detected")
                    visited.add(current)
                    current = downstream[current]
                if current != observation_feature_id:
                    raise ValueError(
                        "graph_state_update_support_outside_observation_upstream_dag"
                    )

    def _observation_admitted(
        self,
        observation: CausalDischargeObservation,
    ) -> bool:
        update = self.config.observation_update
        return (
            observation.quality_status in update.accepted_quality_statuses
            and (
                not update.require_authoritative_evidence
                or observation.evidence_level == "authoritative"
            )
        )

    def _storage_for_discharge(
        self,
        discharge_m3s: float,
        *,
        length: float,
        geometry_values: tuple[float, float, float, float],
        forecast_storage_m3: float,
    ) -> float:
        if discharge_m3s == 0.0:
            return 0.0
        upper = max(forecast_storage_m3, length * geometry_values[0] * 0.01, 1.0)
        for _ in range(self.config.maximum_bracket_expansions):
            if _manning_discharge(upper, length, *geometry_values) >= discharge_m3s:
                break
            upper *= 2.0
            if not np.isfinite(upper):
                raise RuntimeError("forecast_closure_storage_bracket_nonfinite")
        else:
            raise RuntimeError("forecast_closure_storage_bracket_not_found")
        return float(
            brentq(
                lambda value: (
                    _manning_discharge(value, length, *geometry_values)
                    - discharge_m3s
                ),
                0.0,
                upper,
                xtol=self.config.root_absolute_tolerance_m3,
                rtol=self.config.root_relative_tolerance,
            )
        )


@dataclass(frozen=True)
class ForecastClosedBranchingTransportResult:
    closure: ForecastClosureResult
    transport: BranchingNetworkTransportResult
    prior_storage_m3: float
    analysis_increment_m3: float
    transition_input_volume_m3: float
    transition_displaced_upstream_volume_m3: float
    final_storage_m3: float
    outlet_volume_m3: float
    forecast_cycle_mass_balance_residual_m3: float
    forecast_cycle_mass_tolerance_m3: float
    forecast_admitted: bool
    diagnostic_only: bool

    @property
    def outlet_mean_flow_m3s(self) -> float:
        return self.transport.outlet_mean_flow_m3s

    def as_dict(self) -> dict[str, object]:
        return {
            "schema": FORECAST_CLOSED_BRANCHING_TRANSPORT_SCHEMA,
            "closure": self.closure.as_dict(),
            "transport": self.transport.as_dict(),
            "forecast_cycle_mass_ledger": {
                "prior_storage_m3": self.prior_storage_m3,
                "analysis_increment_m3": self.analysis_increment_m3,
                "analysis_increment_is_transition_flux": False,
                "transition_input_volume_m3": self.transition_input_volume_m3,
                "transition_displaced_upstream_volume_m3": (
                    self.transition_displaced_upstream_volume_m3
                ),
                "final_storage_m3": self.final_storage_m3,
                "outlet_volume_m3": self.outlet_volume_m3,
                "residual_m3": self.forecast_cycle_mass_balance_residual_m3,
                "tolerance_m3": self.forecast_cycle_mass_tolerance_m3,
            },
            "forecast_admitted": self.forecast_admitted,
            "diagnostic_only": self.diagnostic_only,
        }


class ForecastClosedBranchingTransportOperator:
    """Compose a forecast closure with the unchanged conservative DAG solver."""

    def __init__(
        self,
        transport: BranchingManningNetworkTransportOperator,
        closure: ForecastClosure,
    ) -> None:
        self.transport = transport
        self.closure = closure

    def step(
        self,
        stock: StockState,
        geometry: ReachHydraulicGeometry,
        *,
        issue_time: datetime,
        observations: tuple[CausalDischargeObservation, ...] = (),
        action: ActionBoundaryFlux | None = None,
        forcing: ForcingFlux | None = None,
        forcing_support: ReachForcingSupport | None = None,
        tributary_boundary: ModeledTributaryBoundaryFlux | None = None,
        internal_boundary: ObservedInternalBoundaryReplacement | None = None,
    ) -> ForecastClosedBranchingTransportResult:
        network = self.transport.network
        before = _network_fingerprint(network)
        closure_result = self.closure.prepare(
            network,
            stock,
            geometry,
            issue_time=issue_time,
            observations=observations,
        )
        if closure_result.network_fingerprint != before:
            raise RuntimeError("forecast_closure_topology_fingerprint_mismatch")
        result = self.transport.step(
            closure_result.analysis_stock,
            closure_result.effective_geometry,
            action=action,
            forcing=forcing,
            forcing_support=forcing_support,
            tributary_boundary=tributary_boundary,
            internal_boundary=internal_boundary,
        )
        if _network_fingerprint(network) != before:
            raise RuntimeError("forecast_closure_mutated_authoritative_topology")
        prior_storage = float(sum(stock.values))
        analysis_increment = closure_result.total_analysis_increment_m3
        final_storage = result.final_network_storage_m3
        outlet_volume = result.outlet_volume_m3
        transition_input = result.total_input_volume_m3
        transition_displaced = result.displaced_upstream_outflow_volume_m3
        residual = float(
            final_storage
            + outlet_volume
            + transition_displaced
            - prior_storage
            - analysis_increment
            - transition_input
        )
        scale = max(1.0, abs(analysis_increment), prior_storage, final_storage)
        tolerance = result.numeric_mass_tolerance_m3 + 1e-12 * scale
        if abs(residual) > tolerance:
            raise RuntimeError("forecast_closure_cycle_mass_balance_exceeded")
        admitted = closure_result.closure_admitted and result.nonlinear_transport_admitted
        return ForecastClosedBranchingTransportResult(
            closure=closure_result,
            transport=result,
            prior_storage_m3=prior_storage,
            analysis_increment_m3=analysis_increment,
            transition_input_volume_m3=transition_input,
            transition_displaced_upstream_volume_m3=transition_displaced,
            final_storage_m3=final_storage,
            outlet_volume_m3=outlet_volume,
            forecast_cycle_mass_balance_residual_m3=residual,
            forecast_cycle_mass_tolerance_m3=float(tolerance),
            forecast_admitted=admitted,
            diagnostic_only=not admitted,
        )


def _manning_discharge(
    storage_m3: float,
    length_m: float,
    bottom_width_m: float,
    side_slope_horizontal_per_vertical: float,
    bed_slope: float,
    manning_n: float,
) -> float:
    if storage_m3 <= 0.0:
        return 0.0
    area = storage_m3 / length_m
    depth = (
        -bottom_width_m
        + np.sqrt(
            bottom_width_m**2
            + 4.0 * side_slope_horizontal_per_vertical * area
        )
    ) / (2.0 * side_slope_horizontal_per_vertical)
    wetted_perimeter = bottom_width_m + 2.0 * depth * np.sqrt(
        1.0 + side_slope_horizontal_per_vertical**2
    )
    hydraulic_radius = area / wetted_perimeter
    return float(
        area * hydraulic_radius ** (2.0 / 3.0) * np.sqrt(bed_slope) / manning_n
    )


def _provenance_digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()
