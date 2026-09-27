from __future__ import annotations

from dataclasses import dataclass

import pytest

from data_agent.uwm.abu_dhabi_flood import (
    CouplingInterfaceBinding,
    HeadExchangeParameters,
    SurfaceState,
    run_synchronous_coupling,
)


@dataclass
class FakeSwmm:
    storage: float = 100.0
    head: float = 2.0
    overflow: float = 0.0

    def __post_init__(self) -> None:
        self.pending: dict[int, float] = {}
        self.elapsed = 0
        self.stride_calls = 0

    def node_index(self, node_id: str) -> int:
        if node_id != "N1":
            raise ValueError("unknown")
        return 0

    def node_state(self, index: int):
        assert index == 0
        return {
            "head_m": self.head,
            "overflow_or_flooding_m3s": self.overflow,
            "volume_m3": self.storage,
        }

    def set_node_surface_exchange_flow(self, index: int, rate_m3s: float) -> None:
        self.pending[index] = rate_m3s

    def stride(self, seconds: int) -> float:
        self.storage += self.pending.get(0, 0.0) * seconds
        self.elapsed += seconds
        self.stride_calls += 1
        return float(self.elapsed)

    def node_storage_m3(self) -> float:
        return self.storage


class FakeSurface:
    cell_count = 1

    def __init__(self, initial_stage: float = 1.0, initial_storage: float = 0.0) -> None:
        self.stage = initial_stage
        self.storage = initial_storage
        self.advance_calls = 0

    def snapshot(self) -> SurfaceState:
        return SurfaceState(
            stage_by_cell_m=(self.stage,),
            storage_start_m3=self.storage,
            storage_end_m3=self.storage,
            available_volume_by_cell_m3=(self.storage,),
        )

    def advance(self, window_seconds: int, source_rate_by_cell_m3s):
        source = float(source_rate_by_cell_m3s[0])
        start = self.storage
        self.storage += source * window_seconds
        self.stage += source * window_seconds / 100.0
        self.advance_calls += 1
        return SurfaceState(
            stage_by_cell_m=(self.stage,),
            storage_start_m3=start,
            storage_end_m3=self.storage,
            external_inflow_m3=0.0,
            rainfall_inflow_m3=0.0,
            applied_source_volume_m3=source * window_seconds,
            available_volume_by_cell_m3=(max(0.0, self.storage),),
        )


def _binding() -> CouplingInterfaceBinding:
    return CouplingInterfaceBinding(
        interface_id="I1",
        swmm_node_id="N1",
        anuga_cell_index=0,
        inlet_elevation_m=0.0,
        head_exchange_parameters=HeadExchangeParameters(
            opening_area_m2=0.01,
            discharge_coefficient=0.61,
            maximum_exchange_rate_m3s=0.1,
        ),
        provenance="fixture:customer-pilot-interface",
    )


def test_synchronous_runner_advances_matching_windows_and_closes_native_overflow_transfer():
    swmm = FakeSwmm(overflow=0.1)
    surface = FakeSurface()
    result = run_synchronous_coupling(
        swmm,
        surface,
        (_binding(),),
        run_id="fixture-coupled-run",
        duration_seconds=600,
        window_seconds=300,
        swmm_substep_seconds=30,
        fail_on_mass_balance=True,
    )

    assert result.status == "completed"
    assert result.quality_passed is True
    assert len(result.windows) == 2
    assert swmm.stride_calls == 20
    assert surface.advance_calls == 2
    assert result.windows[0].swmm_overflow_to_surface_m3 == pytest.approx(30.0)
    assert result.windows[0].head_exchange_swmm_to_surface_m3 == 0.0
    assert result.windows[0].coupled_mass_balance_residual_m3 == pytest.approx(0.0)
    assert result.as_dict()["receipt_sha256"]


def test_runner_rejects_non_aligned_swmm_substep():
    with pytest.raises(ValueError, match="swmm_substep_must_align_window"):
        run_synchronous_coupling(
            FakeSwmm(),
            FakeSurface(),
            (_binding(),),
            run_id="fixture-coupled-run",
            duration_seconds=300,
            window_seconds=300,
            swmm_substep_seconds=70,
        )


def test_dry_surface_below_inlet_does_not_exchange_from_absolute_datum_difference():
    swmm = FakeSwmm(head=2.0, overflow=0.0)
    surface = FakeSurface(initial_stage=1.0, initial_storage=0.0)
    result = run_synchronous_coupling(
        swmm,
        surface,
        (_binding(),),
        run_id="fixture-dry-no-exchange",
        duration_seconds=300,
        window_seconds=300,
        fail_on_mass_balance=True,
    )

    assert result.status == "completed"
    assert result.windows[0].total_swmm_to_anuga_m3 == 0.0
    assert result.windows[0].total_anuga_to_swmm_m3 == 0.0


def test_surface_capture_requires_inlet_inundation_and_is_volume_capped():
    swmm = FakeSwmm(head=0.5, overflow=0.0)
    surface = FakeSurface(initial_stage=3.0, initial_storage=10.0)
    result = run_synchronous_coupling(
        swmm,
        surface,
        (_binding(),),
        run_id="fixture-surface-capture",
        duration_seconds=300,
        window_seconds=300,
        fail_on_mass_balance=True,
    )

    assert result.status == "completed"
    assert result.windows[0].total_anuga_to_swmm_m3 == pytest.approx(10.0)
    assert result.windows[0].anuga_applied_signed_source_m3 == pytest.approx(-10.0)
    assert swmm.storage == pytest.approx(110.0)
    assert surface.storage == pytest.approx(0.0)


def test_runner_rejects_non_aligned_duration():
    with pytest.raises(ValueError, match="duration_must_align_window"):
        run_synchronous_coupling(
            FakeSwmm(),
            FakeSurface(),
            (_binding(),),
            run_id="fixture-coupled-run",
            duration_seconds=301,
            window_seconds=300,
        )


def test_runner_fails_closed_on_surface_cell_mapping_out_of_range():
    invalid = CouplingInterfaceBinding(
        interface_id="I1",
        swmm_node_id="N1",
        anuga_cell_index=2,
        inlet_elevation_m=0.0,
        head_exchange_parameters=HeadExchangeParameters(opening_area_m2=0.01),
        provenance="fixture:invalid",
    )
    with pytest.raises(ValueError, match="anuga_cell_index_out_of_range"):
        run_synchronous_coupling(
            FakeSwmm(),
            FakeSurface(),
            (invalid,),
            run_id="fixture-coupled-run",
            duration_seconds=300,
            window_seconds=300,
        )
