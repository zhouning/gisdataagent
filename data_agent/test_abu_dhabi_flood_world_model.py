from __future__ import annotations

import pytest

from data_agent.uwm.abu_dhabi_flood import (
    AbuDhabiFloodWorldModel,
    DrainageLink,
    FloodAction,
    FloodModelConfig,
    FloodNetwork,
    RainfallForcing,
    SurfacePatch,
)


def _model() -> AbuDhabiFloodWorldModel:
    network = FloodNetwork(
        network_id="abu-dhabi-synthetic-catchments",
        patches=(
            SurfacePatch("catchment-a", 10_000.0, 0.85, 0.0, 2.0, "fixture:patch-a"),
            SurfacePatch("catchment-b", 8_000.0, 0.75, 0.0, 1.0, "fixture:patch-b"),
        ),
        links=(
            DrainageLink(
                "pipe-a-to-b",
                "catchment-a",
                "catchment-b",
                0.05,
                600.0,
                "fixture:pipe-a-to-b",
            ),
            DrainageLink(
                "outfall-b",
                "catchment-b",
                None,
                0.03,
                900.0,
                "fixture:outfall-b",
            ),
        ),
        crs="EPSG:32640",
        provenance_id="fixture:abu-dhabi-flood-network",
    )
    return AbuDhabiFloodWorldModel(network, FloodModelConfig(300.0))


def _rainfall(timestamp_s: float, intensity_a: float = 60.0) -> RainfallForcing:
    return RainfallForcing(
        (intensity_a, intensity_a),
        duration_seconds=300.0,
        timestamp_s=timestamp_s,
        provenance_id="fixture:rainfall",
    )


def test_rainfall_transition_closes_mass_ledger_and_keeps_depth_nonnegative():
    model = _model()
    initial = model.initial_state()
    trace = model.step(initial, _rainfall(0.0))

    assert trace.rainfall_input_m3 > 0.0
    assert trace.peak_depth_m > 0.0
    assert all(depth >= 0.0 for depth in trace.surface_depth_m)
    assert trace.mass_balance_residual_m3 == pytest.approx(0.0, abs=1e-10)
    assert trace.state_after.total_storage_m3 == pytest.approx(
        trace.rainfall_input_m3,
        abs=1e-10,
    )


def test_pipe_action_and_pump_action_change_counterfactual_state():
    model = _model()
    initial = model.initial_state()
    rain = tuple(_rainfall(index * 300.0, 120.0) for index in range(4))
    baseline = FloodAction("baseline", (1.0, 1.0), (0.0, 0.0), "fixture:baseline")
    intervention = FloodAction(
        "emergency-pumping-and-gate",
        (2.0, 2.0),
        (2.0, 1.0),
        "fixture:intervention",
    )
    results = model.counterfactual(
        initial,
        rain,
        {"baseline": (baseline,) * len(rain), "intervention": (intervention,) * len(rain)},
    )

    assert (
        results["intervention"].peak_depth_by_patch_m[0]
        < results["baseline"].peak_depth_by_patch_m[0]
    )
    assert (
        results["intervention"].final_state.total_storage_m3
        < results["baseline"].final_state.total_storage_m3
    )
    assert results["intervention"].maximum_abs_mass_balance_residual_m3 <= 1e-10


def test_link_travel_time_delays_arrival_until_a_later_step():
    model = _model()
    state = model.initial_state(surface_depth_m=(0.2, 0.0))
    first = model.step(state, _rainfall(0.0, 0.0))
    second = model.step(first.state_after, _rainfall(300.0, 0.0))

    assert first.link_inflow_m3[0] > 0.0
    assert first.link_release_m3[0] == pytest.approx(0.0, abs=1e-12)
    assert second.link_release_m3[0] > 0.0
    assert second.state_after.surface_volume_m3[1] > 0.0


def test_candidate_network_cannot_be_marked_admitted():
    with pytest.raises(ValueError, match="candidate_network_cannot_be_admitted"):
        FloodNetwork(
            network_id="invalid",
            patches=(SurfacePatch("a", 1.0, 1.0, 0.0, 0.0, "fixture:a"),),
            links=(DrainageLink("out", "a", None, 1.0, 1.0, "fixture:out"),),
            crs="EPSG:32640",
            provenance_id="fixture:invalid",
            admitted=True,
        )
