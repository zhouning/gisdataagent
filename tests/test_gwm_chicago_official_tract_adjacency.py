from __future__ import annotations

import importlib.util
import json
from pathlib import Path

from data_agent.uwm.geospatial_kernel.longitudinal_panel_sources import (
    validate_longitudinal_panel_source_contract,
)


SCRIPT_PATH = (
    Path(__file__).resolve().parents[1]
    / "scripts/build_gwm_chicago_official_tract_adjacency.py"
)
SCRIPT_SPEC = importlib.util.spec_from_file_location(
    "build_gwm_chicago_official_tract_adjacency", SCRIPT_PATH
)
assert SCRIPT_SPEC is not None and SCRIPT_SPEC.loader is not None
SCRIPT_MODULE = importlib.util.module_from_spec(SCRIPT_SPEC)
SCRIPT_SPEC.loader.exec_module(SCRIPT_MODULE)
DEFAULT_OUTPUT = SCRIPT_MODULE.DEFAULT_OUTPUT
build_official_tract_adjacency = SCRIPT_MODULE.build_official_tract_adjacency


def test_official_tiger2020_cook_topology_is_reproducible() -> None:
    result = build_official_tract_adjacency()

    assert result["geometry_validation"]["source_feature_count"] == 3265
    assert result["geometry_validation"]["cook_county_feature_count"] == 1332
    assert result["geometry_validation"]["coordinate_reference_system"] == (
        "EPSG:4269"
    )
    assert result["graph_summary"] == {
        "node_count": 1332,
        "queen_edge_count": 4410,
        "rook_edge_count": 3416,
        "queen_isolated_node_count": 0,
        "rook_isolated_node_count": 0,
        "queen_connected_component_count": 1,
        "rook_connected_component_count": 1,
        "queen_degree": {"minimum": 2, "maximum": 45, "mean": 6.621622},
        "rook_degree": {"minimum": 2, "maximum": 44, "mean": 5.129129},
    }
    assert result["topology_quality_diagnostics"]["passed"] is True
    assert result["target_cohort"]["event_count"] == 17
    assert result["target_cohort"]["distinct_tract_count"] == 17
    assert result["target_cohort"]["missing_target_tracts"] == []
    assert result["target_cohort"]["tracts_with_zero_rook_neighbors"] == []
    assert result["readiness"]["network_to_unit_time_ready"] is True
    assert result["readiness"]["causal_estimation_ready"] is False


def test_committed_official_network_opens_only_the_network_gate() -> None:
    adjacency = json.loads(DEFAULT_OUTPUT.read_text(encoding="utf-8"))
    contract_path = DEFAULT_OUTPUT.parent.parent / "source_candidate_contract.json"
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    validation = validate_longitudinal_panel_source_contract(contract)

    assert adjacency["readiness"][
        "official_cook_internal_interference_network_usable"
    ] is True
    assert validation["valid"] is True
    assert validation["role_readiness"]["interference_network"] == {
        "source_ids": ["tiger2020_chicago_city_tract_adjacency"],
        "metadata_ready": True,
        "sample_ready": True,
    }
    assert contract["crosswalk_evidence"]["network_to_unit_time"]["passed"] is True
    assert contract["crosswalk_evidence"]["outcome_to_unit"]["passed"] is False
    assert validation["panel_materialization_ready"] is False
    assert validation["causal_estimation_admitted"] is False
