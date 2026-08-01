"""Causal, graph-localized ensemble analysis for river-network storage state."""

from __future__ import annotations

import heapq
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

import numpy as np

from .branching_network import DirectedReachNetwork
from .causal_observation_update import CausalDischargeObservation
from .contracts import ReachHydraulicGeometry, StockState

LOCALIZED_ENSEMBLE_STATE_ANALYSIS_SCHEMA = (
    "gwm.geospatial_kernel.localized_ensemble_state_analysis.v1"
)
LOCALIZATION_SEMANTICS = (
    "compact_support_wendland_c2_on_undirected_reach_center_path_distance"
)
ANALYSIS_METHOD = "deterministic_ensemble_kalman_filter_denkf"


def _aware(value: datetime) -> bool:
    return value.tzinfo is not None and value.utcoffset() is not None


@dataclass(frozen=True)
class LocalizedEnsembleStateEstimatorConfig:
    """Fail-closed controls for a diagnostic localized DEnKF analysis."""

    localization_radius_m: float
    maximum_observation_age_seconds: float
    minimum_ensemble_members: int = 5
    covariance_inflation: float = 1.0
    accepted_quality_statuses: tuple[str, ...] = ("approved",)
    require_authoritative_evidence: bool = True
    allow_unadmitted_components_for_diagnostics: bool = False
    mass_accounting_relative_tolerance: float = 1e-12

    def __post_init__(self) -> None:
        radius = float(self.localization_radius_m)
        maximum_age = float(self.maximum_observation_age_seconds)
        inflation = float(self.covariance_inflation)
        tolerance = float(self.mass_accounting_relative_tolerance)
        if not np.isfinite(radius) or radius <= 0.0:
            raise ValueError("ensemble_state_localization_radius_must_be_positive")
        if not np.isfinite(maximum_age) or maximum_age < 0.0:
            raise ValueError("ensemble_state_maximum_observation_age_invalid")
        if (
            not isinstance(self.minimum_ensemble_members, int)
            or isinstance(self.minimum_ensemble_members, bool)
            or self.minimum_ensemble_members < 3
        ):
            raise ValueError("ensemble_state_minimum_member_count_invalid")
        if not np.isfinite(inflation) or inflation < 1.0:
            raise ValueError("ensemble_state_covariance_inflation_invalid")
        if (
            not self.accepted_quality_statuses
            or len(self.accepted_quality_statuses)
            != len(set(self.accepted_quality_statuses))
            or "rejected" in self.accepted_quality_statuses
        ):
            raise ValueError("ensemble_state_quality_status_policy_invalid")
        if not isinstance(self.require_authoritative_evidence, bool) or not isinstance(
            self.allow_unadmitted_components_for_diagnostics, bool
        ):
            raise ValueError("ensemble_state_admission_flags_must_be_boolean")
        if not np.isfinite(tolerance) or tolerance <= 0.0:
            raise ValueError("ensemble_state_mass_tolerance_invalid")
        object.__setattr__(self, "localization_radius_m", radius)
        object.__setattr__(self, "maximum_observation_age_seconds", maximum_age)
        object.__setattr__(self, "covariance_inflation", inflation)
        object.__setattr__(self, "accepted_quality_statuses", tuple(self.accepted_quality_statuses))
        object.__setattr__(self, "mass_accounting_relative_tolerance", tolerance)


@dataclass(frozen=True)
class LocalizedEnsembleStateAnalysisResult:
    """A deterministic ensemble analysis with an explicit mass-adjustment ledger."""

    feature_ids: tuple[int, ...]
    observation_feature_ids: tuple[int, ...]
    analysis_time: datetime
    forecast_storage_ensemble_m3: tuple[tuple[float, ...], ...]
    analysis_storage_ensemble_m3: tuple[tuple[float, ...], ...]
    forecast_observation_ensemble_m3s: tuple[tuple[float, ...], ...]
    analysis_observation_ensemble_m3s: tuple[tuple[float, ...], ...]
    observed_discharge_m3s: tuple[float, ...]
    observation_error_std_m3s: tuple[float, ...]
    innovation_m3s: tuple[float, ...]
    graph_distance_m_by_observation: tuple[tuple[float, ...], ...]
    localization_taper_by_observation: tuple[tuple[float, ...], ...]
    localized_kalman_gain_by_observation: tuple[tuple[float, ...], ...]
    mean_analysis_increment_m3_by_feature: tuple[float, ...]
    external_analysis_increment_m3_by_member: tuple[float, ...]
    mass_accounting_residual_m3_by_member: tuple[float, ...]
    maximum_absolute_mass_accounting_residual_m3: float
    mass_accounting_passed: bool
    observation_covariance_condition_number: float
    provenance_id: str
    components_admitted: bool
    diagnostic_only: bool

    @property
    def ensemble_member_count(self) -> int:
        return len(self.forecast_storage_ensemble_m3)

    @property
    def forecast_mean_stock(self) -> StockState:
        values = np.asarray(self.forecast_storage_ensemble_m3, dtype=float).mean(axis=0)
        return StockState(
            tuple(float(value) for value in values),
            "m3",
            f"{self.provenance_id}:forecast-ensemble-mean",
        )

    @property
    def analysis_mean_stock(self) -> StockState:
        values = np.asarray(self.analysis_storage_ensemble_m3, dtype=float).mean(axis=0)
        return StockState(
            tuple(float(value) for value in values),
            "m3",
            f"{self.provenance_id}:analysis-ensemble-mean",
        )

    def as_dict(self) -> dict[str, object]:
        forecast_observations = np.asarray(
            self.forecast_observation_ensemble_m3s, dtype=float
        )
        analysis_observations = np.asarray(
            self.analysis_observation_ensemble_m3s, dtype=float
        )
        return {
            "schema": LOCALIZED_ENSEMBLE_STATE_ANALYSIS_SCHEMA,
            "analysis_method": ANALYSIS_METHOD,
            "localization_semantics": LOCALIZATION_SEMANTICS,
            "analysis_time": self.analysis_time.isoformat(),
            "feature_ids": list(self.feature_ids),
            "observation_feature_ids": list(self.observation_feature_ids),
            "ensemble_member_count": self.ensemble_member_count,
            "forecast_storage_ensemble_m3": [
                list(row) for row in self.forecast_storage_ensemble_m3
            ],
            "analysis_storage_ensemble_m3": [
                list(row) for row in self.analysis_storage_ensemble_m3
            ],
            "observations": {
                "observed_discharge_m3s": list(self.observed_discharge_m3s),
                "observation_error_std_m3s": list(
                    self.observation_error_std_m3s
                ),
                "forecast_ensemble_mean_m3s": [
                    float(value) for value in forecast_observations.mean(axis=0)
                ],
                "analysis_ensemble_mean_m3s": [
                    float(value) for value in analysis_observations.mean(axis=0)
                ],
                "innovation_m3s": list(self.innovation_m3s),
            },
            "graph_localization": {
                "distance_m_by_observation": [
                    list(row) for row in self.graph_distance_m_by_observation
                ],
                "taper_by_observation": [
                    list(row) for row in self.localization_taper_by_observation
                ],
                "localized_kalman_gain_by_observation": [
                    list(row) for row in self.localized_kalman_gain_by_observation
                ],
            },
            "mass_adjustment_ledger": {
                "mean_analysis_increment_m3_by_feature": list(
                    self.mean_analysis_increment_m3_by_feature
                ),
                "external_analysis_increment_m3_by_member": list(
                    self.external_analysis_increment_m3_by_member
                ),
                "accounting_residual_m3_by_member": list(
                    self.mass_accounting_residual_m3_by_member
                ),
                "maximum_absolute_accounting_residual_m3": (
                    self.maximum_absolute_mass_accounting_residual_m3
                ),
                "accounting_passed": self.mass_accounting_passed,
                "analysis_increment_is_transition_flux": False,
                "analysis_increment_role": (
                    "explicit_external_state_correction_not_hidden_water"
                ),
            },
            "numerics": {
                "observation_covariance_condition_number": (
                    self.observation_covariance_condition_number
                )
            },
            "provenance_id": self.provenance_id,
            "claim_boundary": {
                "components_admitted": self.components_admitted,
                "estimator_candidate_admitted": False,
                "diagnostic_only": self.diagnostic_only,
                "future_outcome_used": False,
                "forecast_skill_scored": False,
                "runtime_default_enabled": False,
                "geospatial_kernel_validated": False,
            },
        }


class LocalizedEnsembleStateEstimator:
    """Estimate full graph storage from a physical ensemble and causal gauges."""

    def __init__(self, config: LocalizedEnsembleStateEstimatorConfig) -> None:
        self.config = config

    def analyze(
        self,
        *,
        network: DirectedReachNetwork,
        geometry: ReachHydraulicGeometry,
        forecast_storage_ensemble_m3: Sequence[Sequence[float]],
        observations: tuple[CausalDischargeObservation, ...],
        observation_error_std_m3s: Sequence[float],
        analysis_time: datetime,
        provenance_id: str,
        forecast_geometry_ensemble: Sequence[ReachHydraulicGeometry] | None = None,
    ) -> LocalizedEnsembleStateAnalysisResult:
        """Run a DEnKF analysis; no future target, score, or loss is accepted."""

        forecast = np.asarray(forecast_storage_ensemble_m3, dtype=float)
        errors = np.asarray(observation_error_std_m3s, dtype=float)
        geometry_ensemble = tuple(forecast_geometry_ensemble or ())
        components_admitted = self._validate_inputs(
            network=network,
            geometry=geometry,
            forecast=forecast,
            observations=observations,
            errors=errors,
            geometry_ensemble=geometry_ensemble,
            analysis_time=analysis_time,
            provenance_id=provenance_id,
        )
        member_geometries = geometry_ensemble or (geometry,) * forecast.shape[0]
        forecast_observations = _observation_ensemble(
            network, member_geometries, forecast, observations
        )
        member_count = forecast.shape[0]
        state_mean = forecast.mean(axis=0)
        observation_mean = forecast_observations.mean(axis=0)
        state_anomalies = (forecast - state_mean).T * self.config.covariance_inflation
        observation_anomalies = (
            forecast_observations - observation_mean
        ).T * self.config.covariance_inflation
        scale = 1.0 / float(member_count - 1)
        cross_covariance = state_anomalies @ observation_anomalies.T * scale
        observation_covariance = (
            observation_anomalies @ observation_anomalies.T * scale
            + np.diag(errors**2)
        )

        distances = np.asarray(
            [
                _reach_center_distances_m(network, observation.feature_id)
                for observation in observations
            ],
            dtype=float,
        )
        taper = _wendland_c2(distances / self.config.localization_radius_m)
        localized_cross_covariance = cross_covariance * taper.T
        try:
            kalman_gain = np.linalg.solve(
                observation_covariance, localized_cross_covariance.T
            ).T
        except np.linalg.LinAlgError as exc:
            raise ValueError("ensemble_state_observation_covariance_singular") from exc

        observed = np.asarray(
            [observation.discharge_m3s for observation in observations], dtype=float
        )
        innovation = observed - observation_mean
        analysis_mean = state_mean + kalman_gain @ innovation
        analysis_anomalies = state_anomalies - 0.5 * (
            kalman_gain @ observation_anomalies
        )
        unconstrained_analysis = (analysis_mean[:, None] + analysis_anomalies).T
        analysis = np.maximum(unconstrained_analysis, 0.0)
        if not np.isfinite(analysis).all():
            raise RuntimeError("ensemble_state_analysis_nonfinite")

        analysis_observations = _observation_ensemble(
            network, member_geometries, analysis, observations
        )
        increments = analysis - forecast
        external_by_member = increments.sum(axis=1)
        forecast_total = forecast.sum(axis=1)
        analysis_total = analysis.sum(axis=1)
        residual = analysis_total - forecast_total - external_by_member
        tolerance = self.config.mass_accounting_relative_tolerance * np.maximum(
            np.maximum(forecast_total, analysis_total), 1.0
        )
        mass_passed = bool((np.abs(residual) <= tolerance).all())
        if not mass_passed:
            raise RuntimeError("ensemble_state_mass_accounting_failed")

        return LocalizedEnsembleStateAnalysisResult(
            feature_ids=network.feature_ids,
            observation_feature_ids=tuple(
                observation.feature_id for observation in observations
            ),
            analysis_time=analysis_time,
            forecast_storage_ensemble_m3=_matrix_tuple(forecast),
            analysis_storage_ensemble_m3=_matrix_tuple(analysis),
            forecast_observation_ensemble_m3s=_matrix_tuple(
                forecast_observations
            ),
            analysis_observation_ensemble_m3s=_matrix_tuple(analysis_observations),
            observed_discharge_m3s=tuple(float(value) for value in observed),
            observation_error_std_m3s=tuple(float(value) for value in errors),
            innovation_m3s=tuple(float(value) for value in innovation),
            graph_distance_m_by_observation=_matrix_tuple(distances),
            localization_taper_by_observation=_matrix_tuple(taper),
            localized_kalman_gain_by_observation=_matrix_tuple(kalman_gain.T),
            mean_analysis_increment_m3_by_feature=tuple(
                float(value) for value in increments.mean(axis=0)
            ),
            external_analysis_increment_m3_by_member=tuple(
                float(value) for value in external_by_member
            ),
            mass_accounting_residual_m3_by_member=tuple(
                float(value) for value in residual
            ),
            maximum_absolute_mass_accounting_residual_m3=float(
                np.max(np.abs(residual))
            ),
            mass_accounting_passed=mass_passed,
            observation_covariance_condition_number=float(
                np.linalg.cond(observation_covariance)
            ),
            provenance_id=provenance_id,
            components_admitted=components_admitted,
            diagnostic_only=True,
        )

    def _validate_inputs(
        self,
        *,
        network: DirectedReachNetwork,
        geometry: ReachHydraulicGeometry,
        forecast: np.ndarray,
        observations: tuple[CausalDischargeObservation, ...],
        errors: np.ndarray,
        geometry_ensemble: tuple[ReachHydraulicGeometry, ...],
        analysis_time: datetime,
        provenance_id: str,
    ) -> bool:
        if not _aware(analysis_time):
            raise ValueError("ensemble_state_analysis_time_must_be_aware")
        if not provenance_id.strip():
            raise ValueError("ensemble_state_provenance_required")
        if geometry.feature_ids != network.feature_ids:
            raise ValueError("ensemble_state_geometry_feature_alignment_invalid")
        if (
            forecast.ndim != 2
            or forecast.shape[0] < self.config.minimum_ensemble_members
            or forecast.shape[1] != len(network.feature_ids)
            or not np.isfinite(forecast).all()
            or bool((forecast < 0.0).any())
        ):
            raise ValueError("ensemble_state_forecast_ensemble_invalid")
        if geometry_ensemble and (
            len(geometry_ensemble) != forecast.shape[0]
            or any(
                value.feature_ids != network.feature_ids
                for value in geometry_ensemble
            )
        ):
            raise ValueError("ensemble_state_geometry_ensemble_invalid")
        if (
            not observations
            or len({value.feature_id for value in observations}) != len(observations)
            or any(value.feature_id not in network.feature_ids for value in observations)
        ):
            raise ValueError("ensemble_state_observations_invalid")
        if (
            errors.shape != (len(observations),)
            or not np.isfinite(errors).all()
            or bool((errors <= 0.0).any())
        ):
            raise ValueError("ensemble_state_observation_errors_invalid")

        observations_admitted = True
        for observation in observations:
            if observation.available_at > analysis_time:
                raise ValueError("ensemble_state_observation_not_yet_available")
            age = (analysis_time - observation.valid_at).total_seconds()
            if age < 0.0:
                raise ValueError("ensemble_state_future_valid_observation")
            if age > self.config.maximum_observation_age_seconds:
                raise ValueError("ensemble_state_observation_too_old")
            admitted = (
                observation.quality_status in self.config.accepted_quality_statuses
                and (
                    not self.config.require_authoritative_evidence
                    or observation.evidence_level == "authoritative"
                )
            )
            observations_admitted = observations_admitted and admitted
        components_admitted = (
            network.admitted
            and geometry.admitted_as_hydraulic_geometry
            and all(
                value.admitted_as_hydraulic_geometry
                for value in geometry_ensemble
            )
            and observations_admitted
        )
        if (
            not components_admitted
            and not self.config.allow_unadmitted_components_for_diagnostics
        ):
            raise ValueError(
                "ensemble_state_unadmitted_components_require_diagnostic_mode"
            )
        return components_admitted


def _observation_ensemble(
    network: DirectedReachNetwork,
    geometry_ensemble: Sequence[ReachHydraulicGeometry],
    storage_ensemble: np.ndarray,
    observations: Sequence[CausalDischargeObservation],
) -> np.ndarray:
    feature_index = {value: index for index, value in enumerate(network.feature_ids)}
    result = np.zeros((storage_ensemble.shape[0], len(observations)), dtype=float)
    for observation_index, observation in enumerate(observations):
        index = feature_index[observation.feature_id]
        result[:, observation_index] = [
            _manning_discharge(
                float(storage),
                length_m=network.effective_lengths_m[index],
                bottom_width_m=geometry.bottom_width_m[index],
                side_slope=geometry.side_slope_horizontal_per_vertical[index],
                bed_slope=geometry.bed_slope[index],
                manning_n=geometry.manning_n[index],
            )
            for storage, geometry in zip(
                storage_ensemble[:, index], geometry_ensemble, strict=True
            )
        ]
    return result


def _manning_discharge(
    storage_m3: float,
    *,
    length_m: float,
    bottom_width_m: float,
    side_slope: float,
    bed_slope: float,
    manning_n: float,
) -> float:
    if storage_m3 <= 0.0:
        return 0.0
    area = storage_m3 / length_m
    root = float(np.sqrt(bottom_width_m**2 + 4.0 * side_slope * area))
    depth = 2.0 * area / (bottom_width_m + root)
    wetted_perimeter = bottom_width_m + 2.0 * depth * np.sqrt(
        1.0 + side_slope**2
    )
    hydraulic_radius = area / wetted_perimeter
    return float(
        area
        * hydraulic_radius ** (2.0 / 3.0)
        * np.sqrt(bed_slope)
        / manning_n
    )


def _reach_center_distances_m(
    network: DirectedReachNetwork, observation_feature_id: int
) -> tuple[float, ...]:
    index = {feature_id: offset for offset, feature_id in enumerate(network.feature_ids)}
    adjacency: list[list[tuple[int, float]]] = [
        [] for _ in network.feature_ids
    ]
    for source_index, target_feature_id in enumerate(network.downstream_feature_ids):
        if target_feature_id is None:
            continue
        target_index = index[target_feature_id]
        distance = 0.5 * (
            network.effective_lengths_m[source_index]
            + network.effective_lengths_m[target_index]
        )
        adjacency[source_index].append((target_index, distance))
        adjacency[target_index].append((source_index, distance))

    distances = [float("inf")] * len(network.feature_ids)
    start = index[observation_feature_id]
    distances[start] = 0.0
    queue: list[tuple[float, int]] = [(0.0, start)]
    while queue:
        distance, node = heapq.heappop(queue)
        if distance > distances[node]:
            continue
        for target, edge_distance in adjacency[node]:
            candidate = distance + edge_distance
            if candidate < distances[target]:
                distances[target] = candidate
                heapq.heappush(queue, (candidate, target))
    if not np.isfinite(np.asarray(distances, dtype=float)).all():
        raise ValueError("ensemble_state_network_distance_disconnected")
    return tuple(float(value) for value in distances)


def _wendland_c2(normalized_distance: np.ndarray) -> np.ndarray:
    ratio = np.asarray(normalized_distance, dtype=float)
    result = np.zeros_like(ratio)
    inside = ratio < 1.0
    bounded = np.maximum(ratio[inside], 0.0)
    result[inside] = (1.0 - bounded) ** 4 * (1.0 + 4.0 * bounded)
    return result


def _matrix_tuple(values: np.ndarray) -> tuple[tuple[float, ...], ...]:
    return tuple(tuple(float(value) for value in row) for row in values)
