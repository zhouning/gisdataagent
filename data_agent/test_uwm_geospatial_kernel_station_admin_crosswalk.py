import copy
import json
from pathlib import Path

import pytest

from data_agent.uwm.geospatial_kernel.station_admin_crosswalk import (
    STATION_ADMIN_CROSSWALK_GATES,
    STATION_ADMIN_CROSSWALK_SCHEMA,
    build_station_admin_crosswalk,
    compute_station_admin_crosswalk_sha256,
    station_admin_assignment_map,
    validate_station_admin_crosswalk,
)

ROOT = Path(__file__).resolve().parents[1]
DATA_ROOT = ROOT / "data/uwm_public_proxy/chongqing_central"


def test_unique_point_polygon_assignments_build_complete_crosswalk():
    artifact = build_station_admin_crosswalk(
        crosswalk_id="fixture-crosswalk",
        created_at="2026-08-04T19:00:00Z",
        locations_payload=_locations(("station-a", 0.5, 0.5), ("station-b", 1.5, 0.5)),
        admin_feature_collection=_admins(
            ("county-a", "township-a", _square(0.0, 0.0, 1.0, 1.0)),
            ("county-b", "township-b", _square(1.0, 0.0, 2.0, 1.0)),
        ),
        source_refs=["fixture://locations", "fixture://admins"],
    )

    assert artifact["schema"] == STATION_ADMIN_CROSSWALK_SCHEMA
    assert tuple(artifact["gate_results"]) == STATION_ADMIN_CROSSWALK_GATES
    assert all(artifact["gate_results"].values())
    assert artifact["crosswalk_complete"] is True
    assert artifact["audit"]["assignment_status_counts"] == {
        "matched": 2,
        "unmatched": 0,
        "ambiguous": 0,
        "invalid_coordinates": 0,
    }
    assert station_admin_assignment_map(artifact) == {
        "station-a": "重庆市|county-a|township-a",
        "station-b": "重庆市|county-b|township-b",
    }
    assert validate_station_admin_crosswalk(artifact) == {"valid": True, "errors": []}


def test_unmatched_and_boundary_ambiguous_stations_fail_closed():
    artifact = build_station_admin_crosswalk(
        crosswalk_id="fail-closed-fixture",
        created_at="2026-08-04T19:00:00Z",
        locations_payload=_locations(
            ("boundary-station", 1.0, 0.5),
            ("outside-station", 3.0, 3.0),
        ),
        admin_feature_collection=_admins(
            ("county-a", "township-a", _square(0.0, 0.0, 1.0, 1.0)),
            ("county-b", "township-b", _square(1.0, 0.0, 2.0, 1.0)),
        ),
        source_refs=["fixture://locations", "fixture://admins"],
    )

    assert artifact["crosswalk_complete"] is False
    assert artifact["gate_results"]["all_stations_matched_exactly_once"] is False
    assert artifact["audit"]["ambiguous_station_ids"] == ["boundary-station"]
    assert artifact["audit"]["unmatched_station_ids"] == ["outside-station"]
    with pytest.raises(ValueError, match="station_admin_crosswalk_incomplete"):
        station_admin_assignment_map(artifact)
    assert station_admin_assignment_map(artifact, require_complete=False) == {}


def test_crosswalk_digest_detects_assignment_mutation():
    artifact = build_station_admin_crosswalk(
        crosswalk_id="digest-fixture",
        created_at="2026-08-04T19:00:00Z",
        locations_payload=_locations(("station-a", 0.5, 0.5)),
        admin_feature_collection=_admins(
            ("county-a", "township-a", _square(0.0, 0.0, 1.0, 1.0)),
        ),
        source_refs=["fixture://locations", "fixture://admins"],
    )
    mutated = copy.deepcopy(artifact)
    mutated["assignments"][0]["assignment"]["township"] = "mutated"

    validation = validate_station_admin_crosswalk(mutated)

    assert validation["valid"] is False
    assert "station_admin_crosswalk_assignments_invalid" in validation["errors"]
    assert "station_admin_crosswalk_sha256_mismatch" in validation["errors"]


def test_incomplete_crosswalk_cannot_escalate_by_rewriting_gates_and_digest():
    artifact = build_station_admin_crosswalk(
        crosswalk_id="escalation-fixture",
        created_at="2026-08-04T19:00:00Z",
        locations_payload=_locations(("outside-station", 3.0, 3.0)),
        admin_feature_collection=_admins(
            ("county-a", "township-a", _square(0.0, 0.0, 1.0, 1.0)),
        ),
        source_refs=["fixture://locations", "fixture://admins"],
    )
    forged = copy.deepcopy(artifact)
    forged["gate_results"] = {gate: True for gate in STATION_ADMIN_CROSSWALK_GATES}
    forged["remaining_gates"] = []
    forged["crosswalk_complete"] = True
    forged["crosswalk_sha256"] = compute_station_admin_crosswalk_sha256(forged)

    validation = validate_station_admin_crosswalk(forged)

    assert validation["valid"] is False
    assert "station_admin_crosswalk_gate_assignment_audit_mismatch" in validation["errors"]
    with pytest.raises(ValueError, match="invalid_station_admin_crosswalk"):
        station_admin_assignment_map(forged)


@pytest.mark.skipif(
    not (DATA_ROOT / "admin_units/chongqing_township_admin_units.geojson").is_file(),
    reason="requires the restricted local Chongqing township geometry source",
)
def test_current_chongqing_catalog_has_unique_township_assignment_for_all_stations():
    artifact = build_station_admin_crosswalk(
        crosswalk_id="chongqing-catalog-test",
        created_at="2026-08-04T19:00:00Z",
        locations_payload=_read_json(
            DATA_ROOT / "openaq_station_observations/openaq_locations_raw.json"
        ),
        admin_feature_collection=_read_json(
            DATA_ROOT / "admin_units/chongqing_township_admin_units.geojson"
        ),
        source_refs=["local://openaq", "local://admin-units"],
    )

    assert artifact["crosswalk_complete"] is True
    assert artifact["audit"]["station_count"] == 15
    assert artifact["audit"]["assignment_status_counts"]["matched"] == 15
    assert artifact["audit"]["unmatched_station_ids"] == []
    assert artifact["audit"]["ambiguous_station_ids"] == []


def _locations(*rows):
    return {
        "results": [
            {
                "id": station_id,
                "name": station_id,
                "coordinates": {"longitude": longitude, "latitude": latitude},
            }
            for station_id, longitude, latitude in rows
        ]
    }


def _admins(*rows):
    return {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {
                    "province": "重庆市",
                    "city": "重庆市",
                    "county": county,
                    "township": township,
                },
                "geometry": {"type": "Polygon", "coordinates": [coordinates]},
            }
            for county, township, coordinates in rows
        ],
    }


def _square(min_x, min_y, max_x, max_y):
    return [
        [min_x, min_y],
        [max_x, min_y],
        [max_x, max_y],
        [min_x, max_y],
        [min_x, min_y],
    ]


def _read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))
