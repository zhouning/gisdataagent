"""Synchronous SWMM--ANUGA exchange runner.

This module is the executable bridge between the native SWMM dynamic API and
an ANUGA surface adapter.  It deliberately keeps the solver-specific pieces
small and explicit: SWMM advances one exchange window, ANUGA advances the same
window, and the next-window external node flows are computed from the signed
head difference.  Every window is emitted as a JSON-serialisable ledger so a
run can be inspected instead of being treated as a black box.

The runner is suitable for a pilot or a citywide run.  It does not put private
customer data in the repository; callers provide paths and mappings at run
time.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping, Protocol, Sequence

from .swmm_anuga_coupling import (
    HeadExchangeParameters,
    compute_head_difference_exchange_rate,
)

COUPLED_RUNNER_SCHEMA = "gwm.abu_dhabi_flood.swmm_anuga_coupled_run.v1"
COUPLED_WINDOW_SCHEMA = "gwm.abu_dhabi_flood.swmm_anuga_coupled_window.v1"


def _finite(value: float, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"coupled_runner_{name}_invalid")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"coupled_runner_{name}_invalid")
    return result


def _nonnegative(value: float, name: str) -> float:
    result = _finite(value, name)
    if result < 0.0:
        raise ValueError(f"coupled_runner_{name}_invalid")
    return result


@dataclass(frozen=True)
class CouplingInterfaceBinding:
    """One explicit SWMM node to ANUGA cell binding."""

    interface_id: str
    swmm_node_id: str
    anuga_cell_index: int
    inlet_elevation_m: float
    head_exchange_parameters: HeadExchangeParameters
    provenance: str
    swmm_node_index: int | None = None

    def __post_init__(self) -> None:
        for name in ("interface_id", "swmm_node_id", "provenance"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"coupled_runner_{name}_invalid")
        if (
            isinstance(self.anuga_cell_index, bool)
            or not isinstance(self.anuga_cell_index, int)
            or self.anuga_cell_index < 0
        ):
            raise ValueError("coupled_runner_anuga_cell_index_invalid")
        _finite(self.inlet_elevation_m, "inlet_elevation_m")
        if self.swmm_node_index is not None and (
            isinstance(self.swmm_node_index, bool)
            or not isinstance(self.swmm_node_index, int)
            or self.swmm_node_index < 0
        ):
            raise ValueError("coupled_runner_swmm_node_index_invalid")

    def as_dict(self) -> dict[str, object]:
        return {
            "interface_id": self.interface_id,
            "swmm_node_id": self.swmm_node_id,
            "swmm_node_index": self.swmm_node_index,
            "anuga_cell_index": self.anuga_cell_index,
            "inlet_elevation_m": float(self.inlet_elevation_m),
            "head_exchange_parameters": self.head_exchange_parameters.as_dict(),
            "provenance": self.provenance,
        }


@dataclass(frozen=True)
class SurfaceState:
    """State returned by a surface adapter after one exchange window."""

    stage_by_cell_m: tuple[float, ...]
    storage_start_m3: float
    storage_end_m3: float
    external_inflow_m3: float = 0.0
    external_outflow_m3: float = 0.0
    rainfall_inflow_m3: float = 0.0
    infiltration_loss_m3: float = 0.0
    boundary_outflow_m3: float = 0.0
    applied_source_volume_m3: float | None = None
    available_volume_by_cell_m3: tuple[float, ...] = ()

    def __post_init__(self) -> None:
        if not self.stage_by_cell_m:
            raise ValueError("coupled_runner_surface_stage_required")
        for value in self.stage_by_cell_m:
            _finite(value, "surface_stage")
        for name in (
            "storage_start_m3",
            "storage_end_m3",
            "external_inflow_m3",
            "external_outflow_m3",
            "rainfall_inflow_m3",
            "infiltration_loss_m3",
            "boundary_outflow_m3",
        ):
            _nonnegative(getattr(self, name), name)
        if self.applied_source_volume_m3 is not None:
            _finite(self.applied_source_volume_m3, "applied_source_volume_m3")
        for value in self.available_volume_by_cell_m3:
            _nonnegative(value, "available_volume_by_cell_m3")

    @property
    def storage_change_m3(self) -> float:
        return float(self.storage_end_m3 - self.storage_start_m3)

    def as_dict(self) -> dict[str, object]:
        return {
            "stage_cell_count": len(self.stage_by_cell_m),
            "storage_start_m3": float(self.storage_start_m3),
            "storage_end_m3": float(self.storage_end_m3),
            "storage_change_m3": self.storage_change_m3,
            "external_inflow_m3": float(self.external_inflow_m3),
            "external_outflow_m3": float(self.external_outflow_m3),
            "rainfall_inflow_m3": float(self.rainfall_inflow_m3),
            "infiltration_loss_m3": float(self.infiltration_loss_m3),
            "boundary_outflow_m3": float(self.boundary_outflow_m3),
            "applied_source_volume_m3": (
                None
                if self.applied_source_volume_m3 is None
                else float(self.applied_source_volume_m3)
            ),
            "available_volume_cell_count": len(self.available_volume_by_cell_m3),
        }


class SurfaceAdapter(Protocol):
    """Minimal surface solver contract consumed by the runner."""

    cell_count: int

    def snapshot(self) -> SurfaceState:
        """Return the current state without advancing time."""

    def advance(
        self,
        window_seconds: int,
        source_rate_by_cell_m3s: Sequence[float],
    ) -> SurfaceState:
        """Advance exactly one exchange window with a signed cell rate."""


class AnugaSurfaceAdapter:
    """ANUGA implementation of :class:`SurfaceAdapter`.

    ``triangle_to_cell`` maps every ANUGA triangle to a compact exchange-cell
    index.  The adapter converts a cell discharge rate (m³/s) into the
    per-triangle rate (m/s) expected by ``anuga.Rate_operator`` and returns
    centroid stages after each synchronized ``yieldstep``.
    """

    def __init__(
        self,
        domain: Any,
        source_operator: Any,
        triangle_to_cell: Sequence[int],
        cell_areas_m2: Sequence[float],
        *,
        yieldstep_seconds: int,
        finaltime_seconds: int,
    ) -> None:
        try:
            import numpy as np
        except ImportError as exc:  # pragma: no cover - only needed in ANUGA runtime
            raise RuntimeError("coupled_runner_numpy_required_for_anuga_adapter") from exc
        self._np = np
        self.domain = domain
        self.source_operator = source_operator
        self.triangle_to_cell = self._np.asarray(triangle_to_cell, dtype=self._np.int64).reshape(-1)
        self.cell_areas_m2 = self._np.asarray(cell_areas_m2, dtype=self._np.float64).reshape(-1)
        if self.cell_areas_m2.size == 0 or self._np.any(~self._np.isfinite(self.cell_areas_m2)) or self._np.any(self.cell_areas_m2 <= 0.0):
            raise ValueError("coupled_runner_anuga_cell_areas_invalid")
        if self.triangle_to_cell.size != int(domain.number_of_triangles):
            raise ValueError("coupled_runner_anuga_triangle_mapping_shape_invalid")
        if self._np.any(self.triangle_to_cell < 0) or self._np.any(self.triangle_to_cell >= self.cell_areas_m2.size):
            raise ValueError("coupled_runner_anuga_triangle_mapping_value_invalid")
        if isinstance(yieldstep_seconds, bool) or not isinstance(yieldstep_seconds, int) or yieldstep_seconds <= 0:
            raise ValueError("coupled_runner_anuga_yieldstep_invalid")
        if isinstance(finaltime_seconds, bool) or not isinstance(finaltime_seconds, int) or finaltime_seconds <= 0:
            raise ValueError("coupled_runner_anuga_finaltime_invalid")
        self.cell_count = int(self.cell_areas_m2.size)
        self._evolver = iter(
            domain.evolve(
                yieldstep=float(yieldstep_seconds),
                finaltime=float(finaltime_seconds),
                skip_initial_step=True,
            )
        )
        self._last_boundary_flux = float(domain.get_boundary_flux_integral())
        self._last_cumulative_source = float(getattr(source_operator, "cumulative_influx", 0.0))

    def _stage_by_cell(self):
        stage = self._np.asarray(self.domain.get_quantity("stage").centroid_values, dtype=self._np.float64)
        result = self._np.zeros(self.cell_count, dtype=self._np.float64)
        counts = self._np.zeros(self.cell_count, dtype=self._np.int64)
        self._np.add.at(result, self.triangle_to_cell, stage)
        self._np.add.at(counts, self.triangle_to_cell, 1)
        return result / self._np.maximum(counts, 1)

    def _available_volume_by_cell(self):
        stage = self._np.asarray(self.domain.get_quantity("stage").centroid_values, dtype=self._np.float64)
        elevation = self._np.asarray(self.domain.get_quantity("elevation").centroid_values, dtype=self._np.float64)
        depth = self._np.maximum(stage - elevation, 0.0)
        triangle_area = self._np.asarray(self.domain.areas, dtype=self._np.float64)
        result = self._np.zeros(self.cell_count, dtype=self._np.float64)
        self._np.add.at(result, self.triangle_to_cell, depth * triangle_area)
        return result

    def snapshot(self) -> SurfaceState:
        stage = tuple(float(value) for value in self._stage_by_cell())
        storage = float(self.domain.get_water_volume())
        return SurfaceState(
            stage_by_cell_m=stage,
            storage_start_m3=storage,
            storage_end_m3=storage,
            available_volume_by_cell_m3=tuple(float(value) for value in self._available_volume_by_cell()),
        )

    def advance(self, window_seconds: int, source_rate_by_cell_m3s: Sequence[float]) -> SurfaceState:
        if len(source_rate_by_cell_m3s) != self.cell_count:
            raise ValueError("coupled_runner_anuga_source_rate_shape_invalid")
        source = self._np.asarray(source_rate_by_cell_m3s, dtype=self._np.float64)
        if self._np.any(~self._np.isfinite(source)):
            raise ValueError("coupled_runner_anuga_source_rate_invalid")
        triangle_rate_mps = source[self.triangle_to_cell] / self.cell_areas_m2[self.triangle_to_cell]
        self.source_operator.set_rate(triangle_rate_mps)
        storage_start = float(self.domain.get_water_volume())
        try:
            next(self._evolver)
        except StopIteration as exc:
            raise RuntimeError("coupled_runner_anuga_evolver_finished") from exc
        elapsed = float(self.domain.get_time())
        expected = float(window_seconds)
        if elapsed <= 0.0:
            raise RuntimeError("coupled_runner_anuga_time_not_advanced")
        storage_end = float(self.domain.get_water_volume())
        boundary_flux = float(self.domain.get_boundary_flux_integral())
        boundary_delta = boundary_flux - self._last_boundary_flux
        self._last_boundary_flux = boundary_flux
        cumulative_source = float(getattr(self.source_operator, "cumulative_influx", self._last_cumulative_source))
        applied_source_volume = cumulative_source - self._last_cumulative_source
        self._last_cumulative_source = cumulative_source
        return SurfaceState(
            stage_by_cell_m=tuple(float(value) for value in self._stage_by_cell()),
            storage_start_m3=storage_start,
            storage_end_m3=storage_end,
            external_inflow_m3=max(0.0, boundary_delta),
            external_outflow_m3=0.0,
            rainfall_inflow_m3=0.0,
            infiltration_loss_m3=0.0,
            boundary_outflow_m3=max(0.0, -boundary_delta),
            applied_source_volume_m3=applied_source_volume,
            available_volume_by_cell_m3=tuple(float(value) for value in self._available_volume_by_cell()),
        )


class SwmmSession(Protocol):
    """Subset of :class:`SwmmDynamicSession` used by the runner."""

    def node_index(self, node_id: str) -> int: ...

    def node_state(self, index: int) -> Mapping[str, float]: ...

    def set_node_surface_exchange_flow(self, index: int, rate_m3s: float) -> None: ...

    def stride(self, seconds: int) -> float: ...

    def node_storage_m3(self) -> float: ...


@dataclass(frozen=True)
class CoupledWindowRecord:
    window_index: int
    start_seconds: float
    end_seconds: float
    swmm_node_storage_start_m3: float
    swmm_node_storage_end_m3: float
    surface_storage_start_m3: float
    surface_storage_end_m3: float
    rainfall_inflow_m3: float
    swmm_overflow_to_surface_m3: float
    head_exchange_swmm_to_surface_m3: float
    head_exchange_surface_to_swmm_m3: float
    total_swmm_to_anuga_m3: float
    total_anuga_to_swmm_m3: float
    external_outflow_m3: float
    infiltration_loss_m3: float
    coupled_mass_balance_residual_m3: float
    surface_mass_balance_residual_m3: float
    anuga_requested_signed_source_m3: float
    anuga_applied_signed_source_m3: float
    exchange_application_difference_m3: float
    interfaces: tuple[dict[str, object], ...]

    @property
    def quality_passed(self) -> bool:
        source_scale = max(
            abs(self.anuga_requested_signed_source_m3),
            abs(self.anuga_applied_signed_source_m3),
            1.0,
        )
        return (
            abs(self.coupled_mass_balance_residual_m3) <= 1.0e-3
            and abs(self.exchange_application_difference_m3) / source_scale <= 5.0e-3
        )

    def as_dict(self) -> dict[str, object]:
        return {
            "schema": COUPLED_WINDOW_SCHEMA,
            "window_index": self.window_index,
            "start_seconds": float(self.start_seconds),
            "end_seconds": float(self.end_seconds),
            "swmm_node_storage_start_m3": float(self.swmm_node_storage_start_m3),
            "swmm_node_storage_end_m3": float(self.swmm_node_storage_end_m3),
            "surface_storage_start_m3": float(self.surface_storage_start_m3),
            "surface_storage_end_m3": float(self.surface_storage_end_m3),
            "rainfall_inflow_m3": float(self.rainfall_inflow_m3),
            "swmm_overflow_to_surface_m3": float(self.swmm_overflow_to_surface_m3),
            "head_exchange_swmm_to_surface_m3": float(self.head_exchange_swmm_to_surface_m3),
            "head_exchange_surface_to_swmm_m3": float(self.head_exchange_surface_to_swmm_m3),
            "total_swmm_to_anuga_m3": float(self.total_swmm_to_anuga_m3),
            "total_anuga_to_swmm_m3": float(self.total_anuga_to_swmm_m3),
            "external_outflow_m3": float(self.external_outflow_m3),
            "infiltration_loss_m3": float(self.infiltration_loss_m3),
            "coupled_mass_balance_residual_m3": float(self.coupled_mass_balance_residual_m3),
            "surface_mass_balance_residual_m3": float(self.surface_mass_balance_residual_m3),
            "anuga_requested_signed_source_m3": float(self.anuga_requested_signed_source_m3),
            "anuga_applied_signed_source_m3": float(self.anuga_applied_signed_source_m3),
            "exchange_application_difference_m3": float(self.exchange_application_difference_m3),
            "exchange_application_relative_difference": (
                abs(self.exchange_application_difference_m3)
                / max(abs(self.anuga_requested_signed_source_m3), abs(self.anuga_applied_signed_source_m3), 1.0)
            ),
            "quality_passed": self.quality_passed,
            "interfaces": list(self.interfaces),
        }


@dataclass(frozen=True)
class CoupledRunResult:
    run_id: str
    window_seconds: int
    windows: tuple[CoupledWindowRecord, ...]
    interface_bindings: tuple[CouplingInterfaceBinding, ...]
    status: str
    failure: str | None = None

    @property
    def quality_passed(self) -> bool:
        return self.status == "completed" and all(window.quality_passed for window in self.windows)

    def as_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema": COUPLED_RUNNER_SCHEMA,
            "run_id": self.run_id,
            "window_seconds": self.window_seconds,
            "status": self.status,
            "quality_passed": self.quality_passed,
            "failure": self.failure,
            "interface_bindings": [item.as_dict() for item in self.interface_bindings],
            "windows": [item.as_dict() for item in self.windows],
        }
        payload["receipt_sha256"] = hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")
        ).hexdigest()
        return payload


def _resolve_bindings(
    swmm: SwmmSession,
    bindings: Iterable[CouplingInterfaceBinding],
    cell_count: int,
) -> tuple[CouplingInterfaceBinding, ...]:
    resolved: list[CouplingInterfaceBinding] = []
    seen_interfaces: set[str] = set()
    seen_nodes: set[int] = set()
    for binding in bindings:
        if binding.interface_id in seen_interfaces:
            raise ValueError("coupled_runner_duplicate_interface_id")
        index = binding.swmm_node_index
        if index is None:
            index = int(swmm.node_index(binding.swmm_node_id))
        if index in seen_nodes:
            raise ValueError("coupled_runner_duplicate_swmm_node_binding")
        if index < 0:
            raise ValueError("coupled_runner_swmm_node_index_invalid")
        if binding.anuga_cell_index >= cell_count:
            raise ValueError("coupled_runner_anuga_cell_index_out_of_range")
        resolved.append(
            CouplingInterfaceBinding(
                interface_id=binding.interface_id,
                swmm_node_id=binding.swmm_node_id,
                anuga_cell_index=binding.anuga_cell_index,
                inlet_elevation_m=binding.inlet_elevation_m,
                head_exchange_parameters=binding.head_exchange_parameters,
                provenance=binding.provenance,
                swmm_node_index=index,
            )
        )
        seen_interfaces.add(binding.interface_id)
        seen_nodes.add(index)
    if not resolved:
        raise ValueError("coupled_runner_interfaces_required")
    return tuple(resolved)


def _bounded_head_rate(
    binding: CouplingInterfaceBinding,
    swmm_state: Mapping[str, float],
    surface_state: SurfaceState,
    window_seconds: int,
) -> float:
    """Compute a signed rate and prevent a reverse exchange draining a dry cell."""

    raw_rate = compute_head_difference_exchange_rate(
        float(swmm_state.get("head_m", 0.0)),
        float(surface_state.stage_by_cell_m[binding.anuga_cell_index]),
        binding.head_exchange_parameters,
    )
    if raw_rate >= 0.0 or not surface_state.available_volume_by_cell_m3:
        return raw_rate
    available = float(surface_state.available_volume_by_cell_m3[binding.anuga_cell_index])
    return max(raw_rate, -available / float(window_seconds))


def run_synchronous_coupling(
    swmm: SwmmSession,
    surface: SurfaceAdapter,
    bindings: Iterable[CouplingInterfaceBinding],
    *,
    run_id: str,
    duration_seconds: int,
    window_seconds: int = 300,
    rainfall_rate_by_cell_m3s: Sequence[float] | None = None,
    fail_on_mass_balance: bool = False,
) -> CoupledRunResult:
    """Run explicit SWMM/ANUGA windows and return a quality receipt.

    The explicit scheme uses the current surface stage to compute the exchange
    written to SWMM before each SWMM stride.  The SWMM overflow and positive
    head exchange then become the source for the matching ANUGA window.  The
    resulting surface stage is used to compute the exchange for the next
    window.  This one-window explicit lag is intentional and recorded; it is
    stable, auditable, and can later be replaced with an iterative sub-window
    scheme without changing the receipt contract.
    """

    if not isinstance(run_id, str) or not run_id.strip():
        raise ValueError("coupled_runner_run_id_invalid")
    if isinstance(duration_seconds, bool) or not isinstance(duration_seconds, int) or duration_seconds <= 0:
        raise ValueError("coupled_runner_duration_seconds_invalid")
    if isinstance(window_seconds, bool) or not isinstance(window_seconds, int) or window_seconds <= 0:
        raise ValueError("coupled_runner_window_seconds_invalid")
    if duration_seconds % window_seconds:
        raise ValueError("coupled_runner_duration_must_align_window")
    cell_count = int(surface.cell_count)
    if cell_count <= 0:
        raise ValueError("coupled_runner_surface_cell_count_invalid")
    if rainfall_rate_by_cell_m3s is None:
        rainfall = [0.0] * cell_count
    else:
        rainfall = [float(value) for value in rainfall_rate_by_cell_m3s]
        if len(rainfall) != cell_count or any(not math.isfinite(value) or value < 0.0 for value in rainfall):
            raise ValueError("coupled_runner_rainfall_rate_shape_invalid")

    resolved = _resolve_bindings(swmm, bindings, cell_count)
    current_surface = surface.snapshot()
    if len(current_surface.stage_by_cell_m) < cell_count:
        raise ValueError("coupled_runner_surface_snapshot_shape_invalid")
    records: list[CoupledWindowRecord] = []
    pending_exchange: dict[int, float] = {}
    # Seed the first window with the exchange implied by the initial surface
    # stage.  Without this seed the first ANUGA source would be created from a
    # transfer that had not yet been removed from SWMM, producing a visible
    # first-window mass-balance jump.
    for binding in resolved:
        assert binding.swmm_node_index is not None
        initial_swmm_state = swmm.node_state(binding.swmm_node_index)
        initial_rate = _bounded_head_rate(binding, initial_swmm_state, current_surface, window_seconds)
        pending_exchange[binding.swmm_node_index] = -initial_rate

    try:
        for window_index in range(duration_seconds // window_seconds):
            start_seconds = float(window_index * window_seconds)
            end_seconds = float((window_index + 1) * window_seconds)
            swmm_storage_start = _nonnegative(swmm.node_storage_m3(), "swmm_node_storage_start_m3")

            # The exchange calculated from the previous surface state is
            # written before the matching SWMM stride.
            for binding in resolved:
                assert binding.swmm_node_index is not None
                swmm.set_node_surface_exchange_flow(
                    binding.swmm_node_index,
                    pending_exchange[binding.swmm_node_index],
                )
            elapsed = _finite(swmm.stride(window_seconds), "swmm_elapsed_seconds")
            if abs(elapsed - end_seconds) > 1.0e-3:
                raise RuntimeError("coupled_runner_swmm_elapsed_window_mismatch")

            swmm_states = {
                binding.interface_id: swmm.node_state(binding.swmm_node_index or 0)
                for binding in resolved
            }
            source_rate = list(rainfall)
            interface_rows: list[dict[str, object]] = []
            swmm_overflow_volume = 0.0
            head_to_surface_volume = 0.0
            surface_to_swmm_volume = 0.0
            for binding in resolved:
                state = swmm_states[binding.interface_id]
                overflow_rate = max(0.0, float(state.get("overflow_or_flooding_m3s", 0.0)))
                swmm_head = float(state.get("head_m", 0.0))
                previous_stage = float(current_surface.stage_by_cell_m[binding.anuga_cell_index])
                # Use the same rate that was applied to SWMM at the start of
                # this window.  Recomputing from the post-SWMM head would make
                # the two solver ledgers refer to different transfers.
                assert binding.swmm_node_index is not None
                head_rate = -pending_exchange[binding.swmm_node_index]
                positive_head_rate = max(0.0, head_rate)
                reverse_rate = max(0.0, -head_rate)
                # A negative head rate is a surface sink.  Passing the signed
                # value to ANUGA keeps the surface ledger closed while the
                # opposite positive lateral flow is scheduled for SWMM.
                source_rate[binding.anuga_cell_index] += overflow_rate + head_rate
                swmm_overflow_volume += overflow_rate * window_seconds
                head_to_surface_volume += positive_head_rate * window_seconds
                surface_to_swmm_volume += reverse_rate * window_seconds
                interface_rows.append(
                    {
                        "interface_id": binding.interface_id,
                        "swmm_node_id": binding.swmm_node_id,
                        "anuga_cell_index": binding.anuga_cell_index,
                        "swmm_head_m": swmm_head,
                        "surface_stage_m": previous_stage,
                        "overflow_rate_m3s": overflow_rate,
                        "head_exchange_rate_m3s": head_rate,
                        "swmm_to_anuga_volume_m3": (overflow_rate + positive_head_rate) * window_seconds,
                        "anuga_to_swmm_volume_m3": reverse_rate * window_seconds,
                        "provenance": binding.provenance,
                    }
                )

            surface_state = surface.advance(window_seconds, source_rate)
            if len(surface_state.stage_by_cell_m) < cell_count:
                raise ValueError("coupled_runner_surface_result_shape_invalid")
            swmm_storage_end = _nonnegative(swmm.node_storage_m3(), "swmm_node_storage_end_m3")

            # Compute the exchange to be applied at the next window.  A
            # positive signed rate means SWMM -> surface and is therefore a
            # negative lateral flow when written to SWMM; a negative signed
            # rate means surface -> SWMM and is a positive lateral flow.
            for binding in resolved:
                state = swmm_states[binding.interface_id]
                next_stage = float(surface_state.stage_by_cell_m[binding.anuga_cell_index])
                next_surface = SurfaceState(
                    stage_by_cell_m=surface_state.stage_by_cell_m,
                    storage_start_m3=surface_state.storage_start_m3,
                    storage_end_m3=surface_state.storage_end_m3,
                    available_volume_by_cell_m3=surface_state.available_volume_by_cell_m3,
                )
                next_head_rate = _bounded_head_rate(binding, state, next_surface, window_seconds)
                assert binding.swmm_node_index is not None
                pending_exchange[binding.swmm_node_index] = -next_head_rate

            # Check the complete surface ledger.  SWMM overflow and head
            # exchange are internal transfers; signed ANUGA source equals
            # SWMM->surface minus surface->SWMM.
            external_inflow = surface_state.rainfall_inflow_m3 + surface_state.external_inflow_m3
            external_outflow = (
                surface_state.external_outflow_m3
                + surface_state.boundary_outflow_m3
                + surface_state.infiltration_loss_m3
            )
            requested_signed_source_volume = (
                sum(rainfall) * window_seconds
                + swmm_overflow_volume
                + head_to_surface_volume
                - surface_to_swmm_volume
            )
            applied_signed_source_volume = (
                requested_signed_source_volume
                if surface_state.applied_source_volume_m3 is None
                else float(surface_state.applied_source_volume_m3)
            )
            surface_residual = (
                surface_state.storage_change_m3
                - applied_signed_source_volume
                + external_outflow
            )
            # The dynamic API exposes node storage, but not a complete
            # conduit-storage value at each exchange step.  The quality gate
            # therefore uses the full ANUGA ledger and records node storage as
            # an audit scope rather than silently claiming system closure.
            residual = surface_residual
            record = CoupledWindowRecord(
                window_index=window_index,
                start_seconds=start_seconds,
                end_seconds=end_seconds,
                swmm_node_storage_start_m3=swmm_storage_start,
                swmm_node_storage_end_m3=swmm_storage_end,
                surface_storage_start_m3=current_surface.storage_end_m3,
                surface_storage_end_m3=surface_state.storage_end_m3,
                rainfall_inflow_m3=surface_state.rainfall_inflow_m3,
                swmm_overflow_to_surface_m3=swmm_overflow_volume,
                head_exchange_swmm_to_surface_m3=head_to_surface_volume,
                head_exchange_surface_to_swmm_m3=surface_to_swmm_volume,
                total_swmm_to_anuga_m3=swmm_overflow_volume + head_to_surface_volume,
                total_anuga_to_swmm_m3=surface_to_swmm_volume,
                external_outflow_m3=external_outflow,
                infiltration_loss_m3=surface_state.infiltration_loss_m3,
                coupled_mass_balance_residual_m3=float(residual),
                surface_mass_balance_residual_m3=float(surface_residual),
                anuga_requested_signed_source_m3=float(requested_signed_source_volume),
                anuga_applied_signed_source_m3=applied_signed_source_volume,
                exchange_application_difference_m3=float(
                    applied_signed_source_volume - requested_signed_source_volume
                ),
                interfaces=tuple(interface_rows),
            )
            records.append(record)
            current_surface = surface_state
            if fail_on_mass_balance and not record.quality_passed:
                raise RuntimeError(f"coupled_runner_mass_balance_failed_window_{window_index}")
    except Exception as exc:
        return CoupledRunResult(
            run_id=run_id,
            window_seconds=window_seconds,
            windows=tuple(records),
            interface_bindings=resolved,
            status="failed",
            failure=f"{type(exc).__name__}:{exc}",
        )
    return CoupledRunResult(
        run_id=run_id,
        window_seconds=window_seconds,
        windows=tuple(records),
        interface_bindings=resolved,
        status="completed",
    )


def write_coupled_run_receipt(result: CoupledRunResult, path: Path) -> None:
    """Write a stable, self-hashed JSON receipt."""

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result.as_dict(), indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
