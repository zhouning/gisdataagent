"""Hard-constrained conservative transport over an admitted GeoComplex."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .contracts import (
    ActionBoundaryFlux,
    EdgeFlux,
    ForcingFlux,
    GeoComplex,
    SourceSinkFlux,
    StockState,
)


CONSERVATIVE_FLUX_OPERATOR_SCHEMA = (
    "gwm.geospatial_kernel.conservative_flux_operator.v1"
)


@dataclass(frozen=True)
class ConservativeFluxConfig:
    stock_unit: str
    flux_unit: str
    timestep_seconds: float
    absolute_tolerance: float = 1e-9

    def __post_init__(self) -> None:
        if not self.stock_unit.strip() or not self.flux_unit.strip():
            raise ValueError("operator_units_required")
        if not np.isfinite(self.timestep_seconds) or self.timestep_seconds <= 0.0:
            raise ValueError("timestep_seconds_must_be_finite_positive")
        if not np.isfinite(self.absolute_tolerance) or self.absolute_tolerance < 0.0:
            raise ValueError("absolute_tolerance_must_be_finite_nonnegative")


@dataclass(frozen=True)
class ConservativeFluxResult:
    next_stock: StockState
    flux_unit: str
    applied_edge_flux: tuple[float, ...]
    applied_action_flux: tuple[float, ...]
    applied_forcing_flux: tuple[float, ...]
    applied_source_sink_flux: tuple[float, ...]
    unmet_external_withdrawal: tuple[float, ...]
    capacity_limited_edges: tuple[bool, ...]
    stock_limited_edges: tuple[bool, ...]
    node_balance_residual: tuple[float, ...]
    global_mass_balance_residual: float

    def as_dict(self) -> dict[str, object]:
        return {
            "schema": CONSERVATIVE_FLUX_OPERATOR_SCHEMA,
            "next_stock": list(self.next_stock.values),
            "stock_unit": self.next_stock.unit,
            "applied_edge_flux": list(self.applied_edge_flux),
            "flux_unit": self.flux_unit,
            "applied_action_flux": list(self.applied_action_flux),
            "applied_forcing_flux": list(self.applied_forcing_flux),
            "applied_source_sink_flux": list(self.applied_source_sink_flux),
            "unmet_external_withdrawal": list(self.unmet_external_withdrawal),
            "capacity_limited_edges": list(self.capacity_limited_edges),
            "stock_limited_edges": list(self.stock_limited_edges),
            "node_balance_residual": list(self.node_balance_residual),
            "global_mass_balance_residual": self.global_mass_balance_residual,
        }


class ConservativeFluxOperator:
    """Apply external and internal fluxes without creating or losing stock.

    Proposed edge flux is projected onto hard capacity, evidence, and available
    stock constraints. Positive/negative external flux is accounted for by
    semantic channel before internal transport. Incoming edge volume cannot be
    re-exported within the same time step.
    """

    def __init__(self, complex_: GeoComplex, config: ConservativeFluxConfig):
        self.complex = complex_
        self.config = config

    def step(
        self,
        stock: StockState,
        proposed_edge_flux: EdgeFlux,
        *,
        action: ActionBoundaryFlux | None = None,
        forcing: ForcingFlux | None = None,
        source_sink: SourceSinkFlux | None = None,
    ) -> ConservativeFluxResult:
        self._validate_inputs(
            stock=stock,
            proposed_edge_flux=proposed_edge_flux,
            action=action,
            forcing=forcing,
            source_sink=source_sink,
        )
        node_count = self.complex.B.node_count
        dt = self.config.timestep_seconds
        initial = np.asarray(stock.values, dtype=float)
        requested_external = {
            "action": _values_or_zeros(action, node_count),
            "forcing": _values_or_zeros(forcing, node_count),
            "source_sink": _values_or_zeros(source_sink, node_count),
        }
        applied_external, post_external, unmet = _project_external_fluxes(
            stock=initial,
            channel_rates=requested_external,
            timestep_seconds=dt,
        )

        proposed = np.asarray(proposed_edge_flux.values, dtype=float)
        admitted = np.asarray(self.complex.E.edge_admitted, dtype=bool)
        tolerance = self.config.absolute_tolerance
        if bool((proposed[~admitted] > tolerance).any()):
            raise ValueError("nonzero_flux_on_unadmitted_edge")

        capacity = np.asarray(self.complex.M.edge_capacity_per_second, dtype=float)
        capacity_projected = np.minimum(proposed, capacity)
        capacity_projected[~admitted] = 0.0
        capacity_limited = proposed - capacity_projected > tolerance
        requested_volume = capacity_projected * dt

        source_indices = np.asarray(self.complex.B.source_indices, dtype=int)
        source_scale = np.ones(node_count, dtype=float)
        outgoing = np.zeros(node_count, dtype=float)
        np.add.at(outgoing, source_indices, requested_volume)
        limited_nodes = outgoing > post_external + tolerance
        source_scale[limited_nodes] = np.divide(
            post_external[limited_nodes],
            outgoing[limited_nodes],
            out=np.zeros_like(post_external[limited_nodes]),
            where=outgoing[limited_nodes] > 0.0,
        )
        applied_volume = requested_volume * source_scale[source_indices]
        applied_edge_rate = applied_volume / dt
        stock_limited = capacity_projected - applied_edge_rate > tolerance

        incidence = self.complex.B.incidence_matrix()
        internal_delta = incidence @ applied_volume
        external_delta = sum(applied_external.values()) * dt
        next_values = initial + external_delta + internal_delta
        next_values[np.abs(next_values) <= tolerance] = 0.0
        if bool((next_values < -tolerance).any()):
            raise RuntimeError("conservative_projection_produced_negative_stock")
        next_values = np.maximum(next_values, 0.0)

        node_residual = next_values - initial - external_delta - internal_delta
        global_residual = float(
            next_values.sum() - initial.sum() - external_delta.sum()
        )
        numeric_tolerance = tolerance + np.finfo(float).eps * 100.0 * max(
            1.0,
            float(np.abs(initial).sum()),
            float(np.abs(external_delta).sum()),
        )
        if abs(global_residual) > numeric_tolerance:
            raise RuntimeError("global_mass_balance_tolerance_exceeded")

        provenance = (
            f"{self.config.flux_unit}|conservative_flux_step|"
            f"{stock.provenance_id}|{proposed_edge_flux.provenance_id}"
        )
        return ConservativeFluxResult(
            next_stock=StockState(
                values=tuple(float(value) for value in next_values),
                unit=stock.unit,
                provenance_id=provenance,
            ),
            flux_unit=self.config.flux_unit,
            applied_edge_flux=tuple(float(value) for value in applied_edge_rate),
            applied_action_flux=tuple(float(value) for value in applied_external["action"]),
            applied_forcing_flux=tuple(float(value) for value in applied_external["forcing"]),
            applied_source_sink_flux=tuple(
                float(value) for value in applied_external["source_sink"]
            ),
            unmet_external_withdrawal=tuple(float(value) for value in unmet),
            capacity_limited_edges=tuple(bool(value) for value in capacity_limited),
            stock_limited_edges=tuple(bool(value) for value in stock_limited),
            node_balance_residual=tuple(float(value) for value in node_residual),
            global_mass_balance_residual=global_residual,
        )

    def _validate_inputs(
        self,
        *,
        stock: StockState,
        proposed_edge_flux: EdgeFlux,
        action: ActionBoundaryFlux | None,
        forcing: ForcingFlux | None,
        source_sink: SourceSinkFlux | None,
    ) -> None:
        if not isinstance(stock, StockState):
            raise TypeError("stock_state_required")
        if not isinstance(proposed_edge_flux, EdgeFlux):
            raise TypeError("edge_flux_required")
        if action is not None and not isinstance(action, ActionBoundaryFlux):
            raise TypeError("action_boundary_flux_required")
        if forcing is not None and not isinstance(forcing, ForcingFlux):
            raise TypeError("forcing_flux_required")
        if source_sink is not None and not isinstance(source_sink, SourceSinkFlux):
            raise TypeError("source_sink_flux_required")
        if stock.unit != self.config.stock_unit:
            raise ValueError("stock_unit_mismatch")
        if proposed_edge_flux.unit != self.config.flux_unit:
            raise ValueError("edge_flux_unit_mismatch")
        node_count = self.complex.B.node_count
        edge_count = self.complex.B.edge_count
        if len(stock.values) != node_count:
            raise ValueError("stock_node_count_mismatch")
        if len(proposed_edge_flux.values) != edge_count:
            raise ValueError("edge_flux_count_mismatch")
        for name, field in (
            ("action", action),
            ("forcing", forcing),
            ("source_sink", source_sink),
        ):
            if field is None:
                continue
            if field.unit != self.config.flux_unit:
                raise ValueError(f"{name}_flux_unit_mismatch")
            if len(field.values) != node_count:
                raise ValueError(f"{name}_node_count_mismatch")


def _values_or_zeros(
    field: ActionBoundaryFlux | ForcingFlux | SourceSinkFlux | None,
    count: int,
) -> np.ndarray:
    if field is None:
        return np.zeros(count, dtype=float)
    return np.asarray(field.values, dtype=float)


def _project_external_fluxes(
    *,
    stock: np.ndarray,
    channel_rates: dict[str, np.ndarray],
    timestep_seconds: float,
) -> tuple[dict[str, np.ndarray], np.ndarray, np.ndarray]:
    positive_volume = sum(
        np.maximum(rate, 0.0) for rate in channel_rates.values()
    ) * timestep_seconds
    available = stock + positive_volume
    requested_withdrawal_rate = sum(
        np.maximum(-rate, 0.0) for rate in channel_rates.values()
    )
    requested_withdrawal_volume = requested_withdrawal_rate * timestep_seconds
    withdrawal_scale = np.ones_like(stock)
    limited = requested_withdrawal_volume > available
    withdrawal_scale[limited] = np.divide(
        available[limited],
        requested_withdrawal_volume[limited],
        out=np.zeros_like(available[limited]),
        where=requested_withdrawal_volume[limited] > 0.0,
    )

    applied: dict[str, np.ndarray] = {}
    for name, rate in channel_rates.items():
        applied[name] = np.maximum(rate, 0.0) + np.minimum(rate, 0.0) * withdrawal_scale
    actual_external_volume = sum(applied.values()) * timestep_seconds
    post_external = stock + actual_external_volume
    unmet = requested_withdrawal_rate - sum(
        np.maximum(-rate, 0.0) for rate in applied.values()
    )
    return applied, post_external, unmet
