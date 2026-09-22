from __future__ import annotations

import json

import pytest

from data_agent.abu_dhabi_customer_hotspots_service import customer_hotspots_bootstrap_payload


def _feature(hotspot_id: int) -> dict:
    return {
        "type": "Feature",
        "id": hotspot_id,
        "geometry": {"type": "Point", "coordinates": [54.0 + hotspot_id / 10_000, 24.0]},
        "properties": {
            "hotspot_id": hotspot_id,
            "priority": "Very Important" if hotspot_id <= 151 else "Important",
            "center": "Island / City",
            "description": f"Hotspot {hotspot_id}",
            "source_version": "test",
            "source_sha256": "a" * 64,
            "evidence_class": "customer_static_hotspot_prior",
            "event_linkage": "unavailable",
        },
    }


def test_customer_hotspot_payload_requires_complete_official_id_set(tmp_path):
    path = tmp_path / "hotspots.geojson"
    path.write_text(
        json.dumps(
            {
                "type": "FeatureCollection",
                "metadata": {"source_sha256": "a" * 64},
                "features": [_feature(hotspot_id) for hotspot_id in range(1, 507)],
            }
        ),
        encoding="utf-8",
    )

    payload = customer_hotspots_bootstrap_payload(path)

    assert payload["metadata"]["feature_count"] == 506
    assert payload["metadata"]["unique_id_count"] == 506
    assert payload["metadata"]["priority_counts"] == {"Important": 355, "Very Important": 151}
    assert len(payload["geojson"]["features"]) == 506
    assert {feature["geometry"]["type"] for feature in payload["geojson"]["features"]} == {"Point"}


def test_customer_hotspot_payload_rejects_non_point_auxiliary_geometry(tmp_path):
    features = [_feature(hotspot_id) for hotspot_id in range(1, 507)]
    features[-1]["geometry"] = {"type": "Polygon", "coordinates": []}
    path = tmp_path / "hotspots.geojson"
    path.write_text(
        json.dumps({"type": "FeatureCollection", "metadata": {"source_sha256": "a" * 64}, "features": features}),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="Point geometry only"):
        customer_hotspots_bootstrap_payload(path)
