from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from data_agent.uwm.geospatial_kernel_v2 import (
    cwms_component_discharge_catalog as catalog,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
RAW_PATH = REPO_ROOT / (
    "data/geotransport_v0_1/"
    "stage38_center_hill_cwms_component_discharge_catalog/"
    "raw/center_hill_timeseries_catalog.json"
)


def _raw() -> dict[str, object]:
    value = json.loads(RAW_PATH.read_bytes())
    assert isinstance(value, dict)
    return value


def _evidence() -> catalog.CWMSComponentDischargeCatalogEvidence:
    return catalog.compile_cwms_component_discharge_catalog(_raw())


def test_stage38_selects_exact_four_hourly_manual_revision_series():
    evidence = _evidence()

    assert tuple(value.component for value in evidence.components) == (
        "orifice",
        "sluice",
        "spillway",
        "turbine",
    )
    assert tuple(value.series_id for value in evidence.components) == tuple(
        catalog.EXPECTED_SERIES_IDS[key] for key in catalog.EXPECTED_COMPONENTS
    )
    assert all(value.manually_revised for value in evidence.components)


def test_stage38_preserves_catalog_units_interval_and_display_aliases():
    components = _evidence().components

    assert {value.office for value in components} == {"LRN"}
    assert {value.units for value in components} == {"cms"}
    assert {value.interval for value in components} == {"1Hour"}
    assert {value.interval_offset for value in components} == {0}
    assert {value.time_zone for value in components} == {"US/Central"}
    assert tuple(value.display_alias for value in components) == (
        "Orifice Flow",
        "Sluice Gate Flow",
        "Spillway Flow",
        "Turbine Flow",
    )


def test_stage38_catalog_extents_are_metadata_not_continuity_claims():
    components = _evidence().components

    assert tuple(value.earliest_time_utc for value in components) == (
        "2008-08-04T06:00:00Z",
        "2004-09-30T19:00:00Z",
        "1987-05-20T05:00:00Z",
        "1987-05-20T05:00:00Z",
    )
    assert {value.latest_time_utc for value in components} == {"2026-07-28T05:00:00Z"}
    assert _evidence().as_dict()["claim_boundary"]["coverage_continuity_admitted"] is False


def test_stage38_ignores_daily_forecasts_with_similar_component_names():
    raw = _raw()
    forecast_names = tuple(
        str(value.get("name", ""))
        for value in raw["entries"]
        if isinstance(value, dict) and str(value.get("name", "")).endswith(".celrn-cwms-forecast")
    )
    component_forecast_count = sum(
        any(f".Flow-{component.title()}." in name for component in catalog.EXPECTED_COMPONENTS)
        for name in forecast_names
    )

    assert component_forecast_count == 4
    assert len(_evidence().components) == 4
    assert all(value.series_id.endswith(".man-rev") for value in _evidence().components)


def test_stage38_fails_closed_when_required_display_alias_is_removed():
    raw = copy.deepcopy(_raw())
    orifice = next(
        value for value in raw["entries"] if value["name"] == catalog.EXPECTED_SERIES_IDS["orifice"]
    )
    orifice["aliases"] = [value for value in orifice["aliases"] if value["value"] != "Orifice Flow"]

    with pytest.raises(ValueError, match="identity_invalid"):
        catalog.compile_cwms_component_discharge_catalog(raw)


def test_stage38_fails_closed_on_duplicate_exact_series_identity():
    raw = copy.deepcopy(_raw())
    turbine = next(
        value for value in raw["entries"] if value["name"] == catalog.EXPECTED_SERIES_IDS["turbine"]
    )
    raw["entries"].append(turbine)
    raw["total"] = 38

    with pytest.raises(ValueError, match="series_not_unique"):
        catalog.compile_cwms_component_discharge_catalog(raw)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    (
        ("total", 36, "catalog_invalid"),
        ("page-size", 499, "catalog_invalid"),
        ("values", [], "values_not_permitted"),
    ),
)
def test_stage38_fails_closed_on_catalog_boundary_changes(field: str, value: object, message: str):
    raw = copy.deepcopy(_raw())
    raw[field] = value

    with pytest.raises(ValueError, match=message):
        catalog.compile_cwms_component_discharge_catalog(raw)


def test_stage38_typed_refusals_block_values_actions_and_runtime_promotion():
    evidence = _evidence()
    calls = (
        (evidence.require_historical_values, "historical_values"),
        (evidence.require_continuous_coverage, "continuous_coverage"),
        (evidence.require_gate_command, "gate_command"),
        (evidence.require_human_action, "human_action"),
        (evidence.require_causal_intervention, "causal_intervention"),
        (evidence.promote_to_runtime_operator, "runtime_operator_unadmitted"),
    )
    for call, message in calls:
        with pytest.raises(ValueError, match=message):
            call()
