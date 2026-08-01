from __future__ import annotations

import json

import pytest

from scripts import (
    acquire_geotransport_stage33_temporal_support_path as acquire,
)


def test_stage33_plan_freezes_operator_relation_and_reconciliation_gate():
    plan = acquire.compile_plan()

    assert len(plan["frozen_operator_artifact"]["sha256"]) == 64
    assert plan["relation"]["source"]["comid"] == 18421761
    assert plan["relation"]["target"]["comid"] == 18421703
    assert plan["predeclared_reconciliation"] == {
        "empirical_quantity": "empirical_downstream_response_lag",
        "physics_quantities": [
            "gravity_wave_time",
            "manning_kinematic_centroid_time",
            "advective_residence_time",
        ],
        "same_spatial_path_required": True,
        "all_event_common_empirical_support_required": True,
        "physics_quantity_admission_required": True,
        "numerical_overlap_required": True,
        "runtime_promotion_allowed": False,
    }


def test_stage33_plan_is_one_public_spatial_request_without_outcomes():
    plan = acquire.compile_plan(values_mode=True)

    assert len(plan["sources"]) == 1
    assert plan["sources"][0]["source"] == "usgs_nldi"
    assert plan["request_boundary"]["maximum_request_count"] == 1
    assert plan["request_boundary"][
        "release_or_downstream_outcome_values_requested"
    ] is False
    assert plan["request_boundary"]["workspace_or_private_data_sent"] is False


def test_stage33_path_validation_extracts_source_to_target_prefix():
    path = acquire.REPO_ROOT / (
        "data/geotransport_v0_1/topology/raw/"
        "center_hill-downstream-flowlines.json"
    )
    payload = json.loads(path.read_bytes())
    features = payload["features"]
    source_index = next(
        index
        for index, value in enumerate(features)
        if int(value["properties"]["nhdplus_comid"])
        == acquire.SOURCE_COMID
    )
    source_payload = {
        "type": "FeatureCollection",
        "features": features[source_index:],
    }

    selected = acquire._validate_path_payload(source_payload)
    ids = [
        int(value["properties"]["nhdplus_comid"])
        for value in selected
    ]

    assert ids[0] == 18421761
    assert ids[-1] == 18421703
    assert len(ids) == 24


def test_stage33_path_validation_rejects_missing_target():
    payload = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {
                    "type": "LineString",
                    "coordinates": [[-85.82, 36.09], [-85.83, 36.10]],
                },
                "properties": {"nhdplus_comid": 18421761},
            }
        ],
    }

    with pytest.raises(ValueError, match="target_not_unique"):
        acquire._validate_path_payload(payload)


def test_stage33_rejects_unapproved_host():
    with pytest.raises(ValueError, match="url_outside_allowlist"):
        acquire._validate_url("https://example.com/private")


def test_stage33_requires_exact_frozen_plan(tmp_path):
    path = tmp_path / "acquisition_plan.json"
    with pytest.raises(ValueError, match="plan_must_be_frozen"):
        acquire._load_exact_plan(path, acquire.compile_plan())
    path.write_text(json.dumps({"schema": "wrong"}), encoding="utf-8")
    with pytest.raises(ValueError, match="frozen_plan_mismatch"):
        acquire._load_exact_plan(path, acquire.compile_plan())
