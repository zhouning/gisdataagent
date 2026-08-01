from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from data_agent.uwm.geospatial_kernel_v2 import (
    component_discharge_value_support as support,
)
from scripts import plan_geotransport_stage39_component_discharge_values as planner

REPO_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = REPO_ROOT / planner.freeze.STAGE39_ROOT


def _payloads():
    result = {component: [] for component in support.catalog.EXPECTED_COMPONENTS}
    for source in planner.compile_plan()["sources"]:
        result[source["component"]].append(
            json.loads((SOURCE_ROOT / source["output_name"]).read_bytes())
        )
    return {key: tuple(value) for key, value in result.items()}


def _compiled():
    return support.compile_synchronized_component_discharge_support(_payloads())


def test_stage40_all_four_components_have_complete_hourly_grid():
    compiled = _compiled()

    assert [value.component for value in compiled.components] == [
        "orifice",
        "sluice",
        "spillway",
        "turbine",
    ]
    assert all(value.complete_hourly_grid for value in compiled.components)
    assert [value.unique_timestamp_count for value in compiled.components] == [43_825] * 4
    assert [value.missing_timestamp_count for value in compiled.components] == [0] * 4


def test_stage40_annual_boundary_duplicates_are_identical_and_deduplicated():
    components = _compiled().components

    assert [value.raw_row_count for value in components] == [43_829] * 4
    assert [value.duplicate_boundary_row_count for value in components] == [4] * 4


def test_stage40_all_component_values_are_real_and_nonnegative():
    components = _compiled().components

    assert [value.null_value_count for value in components] == [0] * 4
    assert [value.real_value_count for value in components] == [43_825] * 4
    assert [value.negative_value_count for value in components] == [0] * 4
    assert all(value.complete_real_nonnegative_support for value in components)


def test_stage40_quality_codes_are_inventoried_without_approval_semantics():
    reports = [value.as_dict() for value in _compiled().components]

    assert all("0" in value["quality_code_counts"] for value in reports)
    assert all("-2147478653" in value["quality_code_counts"] for value in reports)
    assert all(value["quality_codes_interpreted_as_approval"] is False for value in reports)


def test_stage40_all_hours_are_eligible_for_synchronized_support():
    compiled = _compiled()

    assert compiled.missing_component_hour_count == 0
    assert compiled.null_component_hour_count == 0
    assert compiled.negative_component_hour_count == 0
    assert compiled.eligible_synchronized_hour_count == 43_825
    assert compiled.synchronized_support_complete is True


def test_stage40_duplicate_boundary_mismatch_fails_closed():
    payloads = _payloads()
    mutated = {key: list(value) for key, value in payloads.items()}
    second = copy.deepcopy(mutated["orifice"][1])
    second["values"][0][1] = float(second["values"][0][1]) + 1.0
    mutated["orifice"][1] = second

    with pytest.raises(ValueError, match="duplicate_boundary_mismatch"):
        support.compile_synchronized_component_discharge_support(
            {key: tuple(value) for key, value in mutated.items()}
        )


def test_stage40_missing_payload_group_fails_closed():
    payloads = _payloads()
    del payloads["sluice"]

    with pytest.raises(ValueError, match="payload_group_required"):
        support.compile_synchronized_component_discharge_support(payloads)


def test_stage40_typed_refusals_block_unsupported_promotions():
    compiled = _compiled()
    calls = (
        (compiled.require_quality_approval_semantics, "approval_semantics"),
        (compiled.require_total_discharge_values, "total_values_not_compiled"),
        (compiled.require_event_selection, "event_selection"),
        (compiled.require_gate_command, "gate_command"),
        (compiled.require_human_action, "human_action"),
        (compiled.require_causal_intervention, "causal_intervention"),
        (compiled.require_physical_response_time, "physical_response_time"),
        (compiled.promote_to_runtime_operator, "runtime_operator"),
    )
    for call, message in calls:
        with pytest.raises(ValueError, match=message):
            call()
