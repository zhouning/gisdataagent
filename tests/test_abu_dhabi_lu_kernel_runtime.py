from __future__ import annotations

import numpy as np

from benchmarks.abu_dhabi_land_use_v1.run_geospatial_kernel import (
    ABU_DHABI_LU_GK_RUNTIME_ADAPTER,
    AbuDhabiLUKernelAdapter,
    AbuDhabiLUKernelContext,
    allocate_action,
    probability_cube,
)
from data_agent.uwm.dam_geospatial_kernel import DAM_GK_RUNTIME_ADAPTER
from data_agent.uwm.geospatial_kernel import (
    GeospatialKernelRuntime,
    KernelAction,
    KernelState,
    build_kernel_capability_report,
    summarize_kernel_steps,
)
from data_agent.uwm.geospatial_kernel_v2.runtime_adapter import (
    BRANCHING_HYDRAULIC_RUNTIME_ADAPTER,
)


class _Inputs:
    def __init__(self) -> None:
        self.valid = np.ones((2, 3), dtype=bool)

    def features(self, state: np.ndarray, *, driver_year: int) -> np.ndarray:
        del driver_year
        return np.stack([state.astype(np.float32), np.ones_like(state)])


class _Model:
    classes_ = np.arange(1, 7)

    def predict_proba(self, features: np.ndarray) -> np.ndarray:
        probability = np.full((len(features), 6), 0.02, dtype=np.float32)
        probability[:, 1] = 0.90
        return probability / probability.sum(axis=1, keepdims=True)


def test_abu_dhabi_lu_adapter_matches_direct_transition_and_allocation() -> None:
    inputs = _Inputs()
    model = _Model()
    current = np.array([[1, 2, 3], [4, 5, 6]], dtype=np.uint8)
    hard = np.zeros_like(current, dtype=bool)
    target_counts = {1: 0, 2: 2, 3: 1, 4: 1, 5: 1, 6: 1}
    action_payload = {
        "action_id": "test-allocation",
        "start_year": 2022,
        "target_year": 2023,
        "feasible_target_counts": target_counts,
    }
    expected_probability = probability_cube(model, inputs, current, driver_year=2022)
    expected, expected_allocation = allocate_action(
        current,
        expected_probability,
        valid=inputs.valid,
        hard=hard,
        target_counts=target_counts,
    )
    state = KernelState(
        domain=ABU_DHABI_LU_GK_RUNTIME_ADAPTER.domain,
        time_id="2022",
        state_ref="test-state",
        payload=current,
    )
    action = KernelAction(
        action_id="test-allocation",
        domain=ABU_DHABI_LU_GK_RUNTIME_ADAPTER.domain,
        source_time="2022",
        target_time="2023",
        payload=action_payload,
    )

    result = GeospatialKernelRuntime(AbuDhabiLUKernelAdapter()).step(
        state=state,
        action=action,
        context=AbuDhabiLUKernelContext(
            model=model,
            inputs=inputs,
            driver_year=2022,
            hard_exclusion=hard,
            parameter_ref="test-model",
        ),
    )

    assert np.array_equal(result.candidate.payload, expected_probability)
    assert np.array_equal(result.next_state.payload, expected)
    assert result.projection.diagnostics["moved_pixels"] == expected_allocation["moved_pixels"]
    assert result.projection.diagnostics["hard_exclusion_changed_pixels"] == 0
    summary = summarize_kernel_steps(
        adapter=ABU_DHABI_LU_GK_RUNTIME_ADAPTER,
        expected_step_count=1,
        steps=[result],
    )
    assert summary["all_expected_steps_completed"] is True
    assert summary["all_steps_admitted"] is False
    assert summary["status_counts"]["projected"] == 1


def test_real_lu_dam_and_hydraulic_adapters_share_only_the_runtime_contract() -> None:
    report = build_kernel_capability_report(
        [
            ABU_DHABI_LU_GK_RUNTIME_ADAPTER,
            DAM_GK_RUNTIME_ADAPTER,
            BRANCHING_HYDRAULIC_RUNTIME_ADAPTER,
        ]
    )

    assert report["adapter_count"] == 3
    assert report["domains"] == [
        "conservative_hydraulic_reach_network",
        "dam_hydraulic_network",
        "land_use_raster",
    ]
    assert report["claim_boundary"]["shared_execution_semantics"] is True
    assert report["claim_boundary"]["shared_learning_algorithm"] is False
    assert report["claim_boundary"]["shared_parameters"] is False
    assert report["claim_boundary"]["cross_domain_skill_transfer_proven"] is False
