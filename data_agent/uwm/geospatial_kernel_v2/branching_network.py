"""Branch-aware river-network contracts and conservative Manning transport."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

import numpy as np
from scipy.optimize import brentq

from .contracts import (
    ActionBoundaryFlux,
    ForcingFlux,
    ReachForcingSupport,
    ReachHydraulicGeometry,
    StockState,
)


DIRECTED_REACH_NETWORK_SCHEMA = "gwm.geospatial_kernel.directed_reach_network.v1"
TRIBUTARY_CONFLUENCE_SCHEMA = "gwm.geospatial_kernel.tributary_confluence.v1"
MODELED_TRIBUTARY_BOUNDARY_FLUX_SCHEMA = (
    "gwm.geospatial_kernel.modeled_tributary_boundary_flux.v1"
)
OBSERVED_INTERNAL_BOUNDARY_REPLACEMENT_SCHEMA = (
    "gwm.geospatial_kernel.observed_internal_boundary_replacement.v1"
)
BRANCHING_NETWORK_TRANSPORT_OPERATOR_SCHEMA = (
    "gwm.geospatial_kernel.branching_manning_network_storage.v1"
)

_EVIDENCE_LEVELS = {"authoritative", "derived", "candidate"}


def _positive_feature_ids(values: Iterable[int], name: str) -> tuple[int, ...]:
    result = tuple(values)
    if not result or any(
        not isinstance(value, int) or isinstance(value, bool) or value <= 0
        for value in result
    ):
        raise ValueError(f"{name}_must_be_positive_integers")
    if len(result) != len(set(result)):
        raise ValueError(f"{name}_must_be_unique")
    return result


def _finite_values(values: Iterable[float], name: str) -> tuple[float, ...]:
    result = tuple(float(value) for value in values)
    if not result or not np.isfinite(np.asarray(result, dtype=float)).all():
        raise ValueError(f"{name}_must_be_nonempty_and_finite")
    return result


@dataclass(frozen=True)
class DirectedReachNetwork:
    """A dendritic reach DAG with metric support and explicit action entries.

    Each reach has at most one downstream reach. Multiple upstream reaches may
    converge on one target. Exactly one reach leaves the modeled domain.
    """

    network_id: str
    feature_ids: tuple[int, ...]
    downstream_feature_ids: tuple[int | None, ...]
    full_lengths_m: tuple[float, ...]
    effective_lengths_m: tuple[float, ...]
    action_entry_feature_ids: tuple[int, ...]
    provenance_id: str
    evidence_level: str
    admitted: bool

    def __post_init__(self) -> None:
        if not self.network_id.strip() or not self.provenance_id.strip():
            raise ValueError("directed_reach_network_identity_required")
        features = _positive_feature_ids(
            self.feature_ids, "directed_reach_network_feature_ids"
        )
        object.__setattr__(self, "feature_ids", features)
        if len(self.downstream_feature_ids) != len(features):
            raise ValueError("directed_reach_network_downstream_count_mismatch")
        feature_set = set(features)
        for source, target in zip(
            features, self.downstream_feature_ids, strict=True
        ):
            if target is not None and target not in feature_set:
                raise ValueError("directed_reach_network_target_outside_domain")
            if target == source:
                raise ValueError("directed_reach_network_self_loop")
        outlets = tuple(
            feature
            for feature, target in zip(
                features, self.downstream_feature_ids, strict=True
            )
            if target is None
        )
        if len(outlets) != 1:
            raise ValueError("directed_reach_network_requires_one_outlet")
        full = _finite_values(
            self.full_lengths_m, "directed_reach_network_full_lengths"
        )
        effective = _finite_values(
            self.effective_lengths_m, "directed_reach_network_effective_lengths"
        )
        if len(full) != len(features) or len(effective) != len(features):
            raise ValueError("directed_reach_network_length_count_mismatch")
        if bool((np.asarray(full) <= 0.0).any()) or bool(
            (np.asarray(effective) <= 0.0).any()
        ):
            raise ValueError("directed_reach_network_lengths_must_be_positive")
        if bool((np.asarray(effective) > np.asarray(full) + 1e-6).any()):
            raise ValueError("directed_reach_network_effective_length_exceeds_full")
        object.__setattr__(self, "full_lengths_m", full)
        object.__setattr__(self, "effective_lengths_m", effective)
        actions = tuple(self.action_entry_feature_ids)
        if len(actions) != len(set(actions)) or any(
            feature not in feature_set for feature in actions
        ):
            raise ValueError("directed_reach_network_action_entry_invalid")
        object.__setattr__(self, "action_entry_feature_ids", actions)
        if self.evidence_level not in _EVIDENCE_LEVELS:
            raise ValueError("unsupported_directed_reach_network_evidence_level")
        if not isinstance(self.admitted, bool):
            raise ValueError("directed_reach_network_admission_must_be_boolean")
        if self.admitted and self.evidence_level == "candidate":
            raise ValueError("candidate_directed_reach_network_cannot_be_admitted")
        if len(self.topological_indices) != len(features):
            raise ValueError("directed_reach_network_cycle_detected")

    @property
    def outlet_feature_id(self) -> int:
        return next(
            feature
            for feature, target in zip(
                self.feature_ids, self.downstream_feature_ids, strict=True
            )
            if target is None
        )

    @property
    def topological_indices(self) -> tuple[int, ...]:
        index = {feature: offset for offset, feature in enumerate(self.feature_ids)}
        indegree = [0] * len(self.feature_ids)
        for target in self.downstream_feature_ids:
            if target is not None:
                indegree[index[target]] += 1
        ready = [offset for offset, value in enumerate(indegree) if value == 0]
        order: list[int] = []
        while ready:
            source_index = ready.pop(0)
            order.append(source_index)
            target = self.downstream_feature_ids[source_index]
            if target is None:
                continue
            target_index = index[target]
            indegree[target_index] -= 1
            if indegree[target_index] == 0:
                ready.append(target_index)
        return tuple(order)

    @property
    def topological_feature_ids(self) -> tuple[int, ...]:
        return tuple(self.feature_ids[index] for index in self.topological_indices)

    @property
    def source_feature_ids(self) -> tuple[int, ...]:
        targets = {value for value in self.downstream_feature_ids if value is not None}
        return tuple(feature for feature in self.feature_ids if feature not in targets)

    @property
    def confluence_feature_ids(self) -> tuple[int, ...]:
        counts = {feature: 0 for feature in self.feature_ids}
        for target in self.downstream_feature_ids:
            if target is not None:
                counts[target] += 1
        return tuple(feature for feature in self.feature_ids if counts[feature] > 1)

    @property
    def partial_feature_ids(self) -> tuple[int, ...]:
        return tuple(
            feature
            for feature, full, effective in zip(
                self.feature_ids,
                self.full_lengths_m,
                self.effective_lengths_m,
                strict=True,
            )
            if full - effective > 1e-6
        )

    def as_dict(self) -> dict[str, object]:
        return {
            "schema": DIRECTED_REACH_NETWORK_SCHEMA,
            "network_id": self.network_id,
            "feature_ids": list(self.feature_ids),
            "downstream_feature_ids": list(self.downstream_feature_ids),
            "full_lengths_m": list(self.full_lengths_m),
            "effective_lengths_m": list(self.effective_lengths_m),
            "action_entry_feature_ids": list(self.action_entry_feature_ids),
            "source_feature_ids": list(self.source_feature_ids),
            "outlet_feature_id": self.outlet_feature_id,
            "confluence_feature_ids": list(self.confluence_feature_ids),
            "partial_feature_ids": list(self.partial_feature_ids),
            "topological_feature_ids": list(self.topological_feature_ids),
            "provenance_id": self.provenance_id,
            "evidence_level": self.evidence_level,
            "admitted": self.admitted,
        }


@dataclass(frozen=True)
class TributaryConfluence:
    """GIS-compiled attachment of a tributary mouth to a receiving reach."""

    tributary_feature_id: int
    receiving_feature_id: int
    longitude: float
    latitude: float
    upstream_network_compiled: bool
    provenance_id: str
    evidence_level: str
    admitted: bool

    def __post_init__(self) -> None:
        for value in (self.tributary_feature_id, self.receiving_feature_id):
            if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
                raise ValueError("tributary_confluence_feature_ids_must_be_positive")
        if self.tributary_feature_id == self.receiving_feature_id:
            raise ValueError("tributary_confluence_self_attachment")
        if not np.isfinite(self.longitude) or not np.isfinite(self.latitude):
            raise ValueError("tributary_confluence_coordinate_must_be_finite")
        if not -180.0 <= self.longitude <= 180.0 or not -90.0 <= self.latitude <= 90.0:
            raise ValueError("tributary_confluence_coordinate_out_of_range")
        if not self.provenance_id.strip():
            raise ValueError("tributary_confluence_provenance_required")
        if self.evidence_level not in _EVIDENCE_LEVELS:
            raise ValueError("unsupported_tributary_confluence_evidence_level")
        if self.admitted and self.evidence_level == "candidate":
            raise ValueError("candidate_tributary_confluence_cannot_be_admitted")
        if not isinstance(self.upstream_network_compiled, bool) or not isinstance(
            self.admitted, bool
        ):
            raise ValueError("tributary_confluence_flags_must_be_boolean")

    def as_dict(self) -> dict[str, object]:
        return {
            "schema": TRIBUTARY_CONFLUENCE_SCHEMA,
            "tributary_feature_id": self.tributary_feature_id,
            "receiving_feature_id": self.receiving_feature_id,
            "coordinate": [self.longitude, self.latitude],
            "upstream_network_compiled": self.upstream_network_compiled,
            "provenance_id": self.provenance_id,
            "evidence_level": self.evidence_level,
            "admitted": self.admitted,
        }


@dataclass(frozen=True)
class ModeledTributaryBoundaryFlux:
    """NWM-like tributary-mouth inflow, explicitly not an observation."""

    feature_ids: tuple[int, ...]
    values: tuple[float, ...]
    unit: str
    provenance_id: str
    variable_role: str = "modeled_tributary_boundary_flux"
    modeled: bool = True
    ground_truth: bool = False
    possible_nudging: bool = True

    def __post_init__(self) -> None:
        features = _positive_feature_ids(
            self.feature_ids, "modeled_tributary_boundary_feature_ids"
        )
        values = _finite_values(
            self.values, "modeled_tributary_boundary_flux_values"
        )
        if len(features) != len(values):
            raise ValueError("modeled_tributary_boundary_flux_count_mismatch")
        if bool((np.asarray(values) < 0.0).any()):
            raise ValueError("modeled_tributary_boundary_flux_must_be_nonnegative")
        if not self.unit.strip() or not self.provenance_id.strip():
            raise ValueError("modeled_tributary_boundary_flux_identity_required")
        if self.variable_role != "modeled_tributary_boundary_flux":
            raise ValueError("modeled_tributary_boundary_flux_role_required")
        if self.modeled is not True or self.ground_truth is not False:
            raise ValueError("modeled_tributary_boundary_flux_ground_truth_forbidden")
        if self.possible_nudging is not True:
            raise ValueError("modeled_tributary_boundary_flux_nudging_label_required")
        object.__setattr__(self, "feature_ids", features)
        object.__setattr__(self, "values", values)

    def as_dict(self) -> dict[str, object]:
        return {
            "schema": MODELED_TRIBUTARY_BOUNDARY_FLUX_SCHEMA,
            "feature_ids": list(self.feature_ids),
            "values": list(self.values),
            "unit": self.unit,
            "provenance_id": self.provenance_id,
            "variable_role": self.variable_role,
            "modeled": self.modeled,
            "ground_truth": self.ground_truth,
            "possible_nudging": self.possible_nudging,
        }


@dataclass(frozen=True)
class ObservedInternalBoundaryReplacement:
    """Observed cross-section flow replacing compiled upstream transfer."""

    feature_ids: tuple[int, ...]
    values: tuple[float, ...]
    unit: str
    provenance_id: str
    evidence_level: str
    admitted: bool
    archive_revised: bool
    operational_vintage_verified: bool
    variable_role: str = "observed_internal_boundary_replacement"

    def __post_init__(self) -> None:
        features = _positive_feature_ids(
            self.feature_ids, "observed_internal_boundary_feature_ids"
        )
        values = _finite_values(
            self.values, "observed_internal_boundary_values"
        )
        if len(features) != len(values):
            raise ValueError("observed_internal_boundary_count_mismatch")
        if bool((np.asarray(values) < 0.0).any()):
            raise ValueError("observed_internal_boundary_must_be_nonnegative")
        if self.unit != "m3 s-1" or not self.provenance_id.strip():
            raise ValueError("observed_internal_boundary_identity_invalid")
        if self.evidence_level not in _EVIDENCE_LEVELS:
            raise ValueError("observed_internal_boundary_evidence_level_invalid")
        flags = (
            self.admitted,
            self.archive_revised,
            self.operational_vintage_verified,
        )
        if any(not isinstance(value, bool) for value in flags):
            raise ValueError("observed_internal_boundary_flags_must_be_boolean")
        if self.admitted and (
            self.evidence_level == "candidate"
            or not self.operational_vintage_verified
        ):
            raise ValueError("observed_internal_boundary_admission_invalid")
        if self.variable_role != "observed_internal_boundary_replacement":
            raise ValueError("observed_internal_boundary_role_required")
        object.__setattr__(self, "feature_ids", features)
        object.__setattr__(self, "values", values)

    def as_dict(self) -> dict[str, object]:
        return {
            "schema": OBSERVED_INTERNAL_BOUNDARY_REPLACEMENT_SCHEMA,
            "feature_ids": list(self.feature_ids),
            "values": list(self.values),
            "unit": self.unit,
            "provenance_id": self.provenance_id,
            "evidence_level": self.evidence_level,
            "admitted": self.admitted,
            "archive_revised": self.archive_revised,
            "operational_vintage_verified": self.operational_vintage_verified,
            "variable_role": self.variable_role,
            "replacement_semantics": (
                "observed input enters the boundary reach once while compiled "
                "upstream transfer exits as separately ledgered displaced volume"
            ),
        }


@dataclass(frozen=True)
class BranchingNetworkTransportConfig:
    timestep_seconds: float
    operator_form_admitted: bool = False
    allow_unadmitted_components_for_diagnostics: bool = False
    root_relative_tolerance: float = 1e-12
    root_absolute_tolerance_m3: float = 1e-10
    integration_substep_seconds: float = 300.0
    absolute_mass_tolerance_m3: float = 1e-6
    relative_mass_tolerance: float = 1e-9

    def __post_init__(self) -> None:
        if not isinstance(self.operator_form_admitted, bool) or not isinstance(
            self.allow_unadmitted_components_for_diagnostics, bool
        ):
            raise ValueError("branching_network_admission_flags_must_be_boolean")
        for value, error in (
            (self.timestep_seconds, "branching_network_timestep_must_be_positive"),
            (self.root_relative_tolerance, "branching_network_root_rtol_must_be_positive"),
            (self.root_absolute_tolerance_m3, "branching_network_root_atol_must_be_positive"),
            (self.integration_substep_seconds, "branching_network_substep_must_be_positive"),
            (
                self.relative_mass_tolerance,
                "branching_network_relative_mass_tolerance_must_be_positive",
            ),
        ):
            if not np.isfinite(value) or value <= 0.0:
                raise ValueError(error)
        if (
            not np.isfinite(self.absolute_mass_tolerance_m3)
            or self.absolute_mass_tolerance_m3 < 0.0
        ):
            raise ValueError("branching_network_mass_tolerance_must_be_nonnegative")


@dataclass(frozen=True)
class BranchingNetworkTransportResult:
    next_stock: StockState
    feature_ids: tuple[int, ...]
    reach_mean_outflow_m3s: tuple[float, ...]
    reach_end_depth_m: tuple[float, ...]
    action_input_volume_m3: float
    distributed_forcing_volume_m3: float
    modeled_tributary_boundary_volume_m3: float
    observed_internal_boundary_input_volume_m3: float
    displaced_upstream_outflow_volume_m3: float
    internal_boundary_net_analysis_volume_m3: float
    total_input_volume_m3: float
    outlet_volume_m3: float
    outlet_mean_flow_m3s: float
    final_network_storage_m3: float
    global_mass_balance_residual_m3: float
    numeric_mass_tolerance_m3: float
    network_admitted: bool
    geometry_admitted: bool
    confluences_admitted: bool
    forcing_support_admitted: bool
    operator_form_admitted: bool
    nonlinear_transport_admitted: bool
    modeled_tributary_boundary_used: bool
    observed_internal_boundary_replacement_used: bool
    internal_boundary_operational_vintage_verified: bool
    tributary_boundary_ground_truth: bool
    tributary_boundary_possible_nudging: bool
    independent_end_to_end_prediction: bool
    diagnostic_only: bool

    def as_dict(self) -> dict[str, object]:
        return {
            "schema": BRANCHING_NETWORK_TRANSPORT_OPERATOR_SCHEMA,
            "next_stock_m3": list(self.next_stock.values),
            "feature_ids": list(self.feature_ids),
            "reach_mean_outflow_m3s": list(self.reach_mean_outflow_m3s),
            "reach_end_depth_m": list(self.reach_end_depth_m),
            "action_input_volume_m3": self.action_input_volume_m3,
            "distributed_forcing_volume_m3": self.distributed_forcing_volume_m3,
            "modeled_tributary_boundary_volume_m3": (
                self.modeled_tributary_boundary_volume_m3
            ),
            "observed_internal_boundary_input_volume_m3": (
                self.observed_internal_boundary_input_volume_m3
            ),
            "displaced_upstream_outflow_volume_m3": (
                self.displaced_upstream_outflow_volume_m3
            ),
            "internal_boundary_net_analysis_volume_m3": (
                self.internal_boundary_net_analysis_volume_m3
            ),
            "total_input_volume_m3": self.total_input_volume_m3,
            "outlet_volume_m3": self.outlet_volume_m3,
            "outlet_mean_flow_m3s": self.outlet_mean_flow_m3s,
            "final_network_storage_m3": self.final_network_storage_m3,
            "global_mass_balance_residual_m3": self.global_mass_balance_residual_m3,
            "numeric_mass_tolerance_m3": self.numeric_mass_tolerance_m3,
            "network_admitted": self.network_admitted,
            "geometry_admitted": self.geometry_admitted,
            "confluences_admitted": self.confluences_admitted,
            "forcing_support_admitted": self.forcing_support_admitted,
            "operator_form_admitted": self.operator_form_admitted,
            "nonlinear_transport_admitted": self.nonlinear_transport_admitted,
            "modeled_tributary_boundary_used": self.modeled_tributary_boundary_used,
            "observed_internal_boundary_replacement_used": (
                self.observed_internal_boundary_replacement_used
            ),
            "internal_boundary_operational_vintage_verified": (
                self.internal_boundary_operational_vintage_verified
            ),
            "tributary_boundary_ground_truth": self.tributary_boundary_ground_truth,
            "tributary_boundary_possible_nudging": (
                self.tributary_boundary_possible_nudging
            ),
            "independent_end_to_end_prediction": (
                self.independent_end_to_end_prediction
            ),
            "diagnostic_only": self.diagnostic_only,
        }


class BranchingManningNetworkTransportOperator:
    """Advance a dendritic Manning storage network in topological order."""

    def __init__(
        self,
        network: DirectedReachNetwork,
        config: BranchingNetworkTransportConfig,
        *,
        external_confluences: tuple[TributaryConfluence, ...] = (),
    ) -> None:
        self.network = network
        self.config = config
        self.external_confluences = tuple(external_confluences)
        feature_set = set(network.feature_ids)
        tributary_ids: set[int] = set()
        for confluence in self.external_confluences:
            if confluence.receiving_feature_id not in feature_set:
                raise ValueError("tributary_confluence_receiver_outside_network")
            if confluence.upstream_network_compiled:
                raise ValueError("external_confluence_cannot_have_compiled_subnetwork")
            if confluence.tributary_feature_id in feature_set:
                raise ValueError("external_confluence_tributary_inside_network")
            if confluence.tributary_feature_id in tributary_ids:
                raise ValueError("duplicate_external_tributary_confluence")
            tributary_ids.add(confluence.tributary_feature_id)
        self._index = {
            feature: index for index, feature in enumerate(network.feature_ids)
        }
        upstream: list[list[int]] = [[] for _ in network.feature_ids]
        for source_index, target in enumerate(network.downstream_feature_ids):
            if target is not None:
                upstream[self._index[target]].append(source_index)
        self._upstream_indices = tuple(tuple(values) for values in upstream)
        self._external_target_indices = frozenset(
            self._index[value.receiving_feature_id]
            for value in self.external_confluences
        )
        self._action_target_indices = frozenset(
            self._index[value] for value in network.action_entry_feature_ids
        )

    def zero_state(self, *, provenance_id: str) -> StockState:
        return StockState(
            values=(0.0,) * len(self.network.feature_ids),
            unit="m3",
            provenance_id=provenance_id,
        )

    def step(
        self,
        stock: StockState,
        geometry: ReachHydraulicGeometry,
        *,
        action: ActionBoundaryFlux | None = None,
        forcing: ForcingFlux | None = None,
        forcing_support: ReachForcingSupport | None = None,
        tributary_boundary: ModeledTributaryBoundaryFlux | None = None,
        internal_boundary: ObservedInternalBoundaryReplacement | None = None,
    ) -> BranchingNetworkTransportResult:
        self._validate_inputs(
            stock=stock,
            geometry=geometry,
            action=action,
            forcing=forcing,
            forcing_support=forcing_support,
            tributary_boundary=tributary_boundary,
            internal_boundary=internal_boundary,
        )
        count = len(self.network.feature_ids)
        dt = float(self.config.timestep_seconds)
        initial = np.asarray(stock.values, dtype=float)
        action_rate = _values_or_zeros(action, count)
        raw_forcing_rate = _values_or_zeros(forcing, count)
        forcing_fractions = (
            np.asarray(forcing_support.coverage_fractions, dtype=float)
            if forcing_support is not None
            else np.ones(count, dtype=float)
        )
        forcing_rate = raw_forcing_rate * forcing_fractions
        boundary_rate = (
            np.asarray(tributary_boundary.values, dtype=float)
            if tributary_boundary is not None
            else np.zeros(count, dtype=float)
        )
        internal_boundary_rate = np.zeros(count, dtype=float)
        internal_boundary_indices: set[int] = set()
        if internal_boundary is not None:
            for feature_id, value in zip(
                internal_boundary.feature_ids,
                internal_boundary.values,
                strict=True,
            ):
                index = self._index[feature_id]
                internal_boundary_indices.add(index)
                internal_boundary_rate[index] = value
        external_rate = action_rate + forcing_rate + boundary_rate
        lengths = np.asarray(self.network.effective_lengths_m, dtype=float)
        bottom_width = np.asarray(geometry.bottom_width_m, dtype=float)
        side_slope = np.asarray(
            geometry.side_slope_horizontal_per_vertical, dtype=float
        )
        bed_slope = np.asarray(geometry.bed_slope, dtype=float)
        manning_n = np.asarray(geometry.manning_n, dtype=float)

        def discharge_at(index: int, storage_m3: float) -> float:
            if storage_m3 <= 0.0:
                return 0.0
            area = storage_m3 / lengths[index]
            depth = (
                -bottom_width[index]
                + np.sqrt(
                    bottom_width[index] ** 2
                    + 4.0 * side_slope[index] * area
                )
            ) / (2.0 * side_slope[index])
            wetted = bottom_width[index] + 2.0 * depth * np.sqrt(
                1.0 + side_slope[index] ** 2
            )
            radius = area / wetted
            return float(
                area
                * radius ** (2.0 / 3.0)
                * np.sqrt(bed_slope[index])
                / manning_n[index]
            )

        next_storage = initial.copy()
        transferred_volume = np.zeros(count, dtype=float)
        displaced_upstream_volume = 0.0
        elapsed = 0.0
        while elapsed < dt:
            substep = min(self.config.integration_substep_seconds, dt - elapsed)
            previous_storage = next_storage
            advanced_storage = np.empty(count, dtype=float)
            current_discharge = np.zeros(count, dtype=float)
            for index in self.network.topological_indices:
                upstream_rate = sum(
                    current_discharge[source]
                    for source in self._upstream_indices[index]
                )
                if index in internal_boundary_indices:
                    displaced_upstream_volume += substep * upstream_rate
                    upstream_rate = float(internal_boundary_rate[index])
                available = float(
                    previous_storage[index]
                    + substep * (external_rate[index] + upstream_rate)
                )
                if available < 0.0 or not np.isfinite(available):
                    raise RuntimeError("branching_network_nonfinite_available_volume")
                if available == 0.0:
                    storage_value = 0.0
                    discharge_value = 0.0
                else:
                    storage_value = float(
                        brentq(
                            lambda value: (
                                value
                                + substep * discharge_at(index, value)
                                - available
                            ),
                            0.0,
                            available,
                            xtol=self.config.root_absolute_tolerance_m3,
                            rtol=self.config.root_relative_tolerance,
                        )
                    )
                    discharge_value = discharge_at(index, storage_value)
                advanced_storage[index] = storage_value
                current_discharge[index] = discharge_value
                transferred_volume[index] += substep * discharge_value
            next_storage = advanced_storage
            elapsed += substep

        outlet_index = self._index[self.network.outlet_feature_id]
        action_volume = float(action_rate.sum() * dt)
        forcing_volume = float(forcing_rate.sum() * dt)
        boundary_volume = float(boundary_rate.sum() * dt)
        internal_boundary_volume = float(internal_boundary_rate.sum() * dt)
        input_volume = (
            action_volume
            + forcing_volume
            + boundary_volume
            + internal_boundary_volume
        )
        outlet_volume = float(transferred_volume[outlet_index])
        final_storage = float(next_storage.sum())
        residual = float(
            final_storage
            + outlet_volume
            + displaced_upstream_volume
            - initial.sum()
            - input_volume
        )
        numeric_scale = max(
            1.0,
            float(initial.sum()),
            input_volume,
            final_storage,
            outlet_volume,
            displaced_upstream_volume,
        )
        tolerance = (
            self.config.absolute_mass_tolerance_m3
            + self.config.relative_mass_tolerance * numeric_scale
        )
        if abs(residual) > tolerance:
            raise RuntimeError("branching_network_global_mass_balance_exceeded")

        area = next_storage / lengths
        depth = (
            -bottom_width + np.sqrt(bottom_width**2 + 4.0 * side_slope * area)
        ) / (2.0 * side_slope)
        partial_indices = {
            self._index[value] for value in self.network.partial_feature_ids
        }
        support_required = any(
            raw_forcing_rate[index] != 0.0 for index in partial_indices
        )
        support_admitted = (
            not support_required
            or bool(
                forcing_support is not None
                and forcing_support.admitted_as_spatial_support
            )
        )
        confluences_admitted = all(
            value.admitted for value in self.external_confluences
        )
        admitted = (
            self.network.admitted
            and geometry.admitted_as_hydraulic_geometry
            and confluences_admitted
            and support_admitted
            and self.config.operator_form_admitted
            and bool(internal_boundary is None or internal_boundary.admitted)
        )
        provenance = (
            f"branching_manning_network_storage|{self.network.provenance_id}|"
            f"{stock.provenance_id}|{geometry.provenance_id}"
        )
        boundary_used = bool((boundary_rate > 0.0).any())
        return BranchingNetworkTransportResult(
            next_stock=StockState(
                tuple(float(value) for value in next_storage),
                "m3",
                provenance,
            ),
            feature_ids=self.network.feature_ids,
            reach_mean_outflow_m3s=tuple(
                float(value / dt) for value in transferred_volume
            ),
            reach_end_depth_m=tuple(float(value) for value in depth),
            action_input_volume_m3=action_volume,
            distributed_forcing_volume_m3=forcing_volume,
            modeled_tributary_boundary_volume_m3=boundary_volume,
            observed_internal_boundary_input_volume_m3=internal_boundary_volume,
            displaced_upstream_outflow_volume_m3=float(
                displaced_upstream_volume
            ),
            internal_boundary_net_analysis_volume_m3=float(
                internal_boundary_volume - displaced_upstream_volume
            ),
            total_input_volume_m3=input_volume,
            outlet_volume_m3=outlet_volume,
            outlet_mean_flow_m3s=outlet_volume / dt,
            final_network_storage_m3=final_storage,
            global_mass_balance_residual_m3=residual,
            numeric_mass_tolerance_m3=float(tolerance),
            network_admitted=self.network.admitted,
            geometry_admitted=geometry.admitted_as_hydraulic_geometry,
            confluences_admitted=confluences_admitted,
            forcing_support_admitted=support_admitted,
            operator_form_admitted=self.config.operator_form_admitted,
            nonlinear_transport_admitted=admitted,
            modeled_tributary_boundary_used=boundary_used,
            observed_internal_boundary_replacement_used=(
                internal_boundary is not None
            ),
            internal_boundary_operational_vintage_verified=bool(
                internal_boundary is not None
                and internal_boundary.operational_vintage_verified
            ),
            tributary_boundary_ground_truth=False,
            tributary_boundary_possible_nudging=boundary_used,
            independent_end_to_end_prediction=bool(
                not boundary_used and internal_boundary is None
            ),
            diagnostic_only=not admitted,
        )

    def _validate_inputs(
        self,
        *,
        stock: StockState,
        geometry: ReachHydraulicGeometry,
        action: ActionBoundaryFlux | None,
        forcing: ForcingFlux | None,
        forcing_support: ReachForcingSupport | None,
        tributary_boundary: ModeledTributaryBoundaryFlux | None,
        internal_boundary: ObservedInternalBoundaryReplacement | None,
    ) -> None:
        count = len(self.network.feature_ids)
        if not isinstance(stock, StockState):
            raise TypeError("stock_state_required")
        if not isinstance(geometry, ReachHydraulicGeometry):
            raise TypeError("reach_hydraulic_geometry_required")
        if action is not None and not isinstance(action, ActionBoundaryFlux):
            raise TypeError("action_boundary_flux_required")
        if forcing is not None and not isinstance(forcing, ForcingFlux):
            raise TypeError("forcing_flux_required")
        if forcing_support is not None and not isinstance(
            forcing_support, ReachForcingSupport
        ):
            raise TypeError("reach_forcing_support_required")
        if tributary_boundary is not None and not isinstance(
            tributary_boundary, ModeledTributaryBoundaryFlux
        ):
            raise TypeError("modeled_tributary_boundary_flux_required")
        if internal_boundary is not None and not isinstance(
            internal_boundary, ObservedInternalBoundaryReplacement
        ):
            raise TypeError("observed_internal_boundary_replacement_required")
        if stock.unit != "m3" or len(stock.values) != count:
            raise ValueError("branching_network_stock_axis_or_unit_mismatch")
        if geometry.feature_ids != self.network.feature_ids:
            raise ValueError("branching_network_geometry_feature_axis_mismatch")
        for name, field in (("action", action), ("forcing", forcing)):
            if field is None:
                continue
            if field.unit != "m3 s-1" or len(field.values) != count:
                raise ValueError(f"branching_network_{name}_axis_or_unit_mismatch")
            if bool((np.asarray(field.values, dtype=float) < 0.0).any()):
                raise ValueError(f"branching_network_{name}_must_be_nonnegative")
        if action is not None:
            nonzero = set(np.flatnonzero(np.asarray(action.values) > 0.0))
            if not nonzero.issubset(self._action_target_indices):
                raise ValueError("branching_network_action_outside_admitted_entry")
        if forcing_support is not None:
            if forcing_support.feature_ids != self.network.feature_ids:
                raise ValueError("branching_network_forcing_support_axis_mismatch")
            partial = set(self.network.partial_feature_ids)
            for feature_id, fraction in zip(
                forcing_support.feature_ids,
                forcing_support.coverage_fractions,
                strict=True,
            ):
                if feature_id not in partial and abs(fraction - 1.0) > 1e-12:
                    raise ValueError(
                        "branching_network_full_reach_support_must_equal_one"
                    )
        if tributary_boundary is not None:
            if tributary_boundary.feature_ids != self.network.feature_ids:
                raise ValueError("branching_network_boundary_feature_axis_mismatch")
            if tributary_boundary.unit != "m3 s-1":
                raise ValueError("branching_network_boundary_unit_mismatch")
            nonzero = set(np.flatnonzero(np.asarray(tributary_boundary.values) > 0.0))
            if not nonzero.issubset(self._external_target_indices):
                raise ValueError("branching_network_boundary_outside_confluence")
        if internal_boundary is not None:
            feature_set = set(self.network.feature_ids)
            if not set(internal_boundary.feature_ids).issubset(feature_set):
                raise ValueError("internal_boundary_feature_outside_network")
            boundary_indices = {
                self._index[feature_id]
                for feature_id in internal_boundary.feature_ids
            }
            if any(not self._upstream_indices[index] for index in boundary_indices):
                raise ValueError("internal_boundary_requires_compiled_upstream")
            if boundary_indices & self._action_target_indices:
                raise ValueError("internal_boundary_cannot_replace_action_entry")
            if boundary_indices & self._external_target_indices:
                raise ValueError("internal_boundary_cannot_overlap_external_boundary")
        partial_indices = {
            self._index[value] for value in self.network.partial_feature_ids
        }
        forcing_required = bool(
            forcing is not None
            and any(forcing.values[index] != 0.0 for index in partial_indices)
        )
        if forcing_required and forcing_support is None:
            raise ValueError(
                "branching_network_partial_forcing_requires_spatial_support"
            )
        support_admitted = (
            not forcing_required
            or bool(
                forcing_support is not None
                and forcing_support.admitted_as_spatial_support
            )
        )
        admitted = (
            self.network.admitted
            and geometry.admitted_as_hydraulic_geometry
            and all(value.admitted for value in self.external_confluences)
            and support_admitted
            and self.config.operator_form_admitted
            and bool(internal_boundary is None or internal_boundary.admitted)
        )
        if not admitted and not self.config.allow_unadmitted_components_for_diagnostics:
            raise ValueError(
                "unadmitted_branching_network_components_require_explicit_diagnostic_mode"
            )


def _values_or_zeros(
    field: ActionBoundaryFlux | ForcingFlux | None, count: int
) -> np.ndarray:
    if field is None:
        return np.zeros(count, dtype=float)
    return np.asarray(field.values, dtype=float)
