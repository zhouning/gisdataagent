from __future__ import annotations

import pytest

from data_agent.uwm.abu_dhabi_flood.makani_probe import EXPECTED_SOURCE_BINDING
from data_agent.uwm.abu_dhabi_flood.registered_makani_acquisition import (
    LAYER_SPECS,
    RegisteredMakaniLayerSpec,
    _select_sql,
    validate_registered_source,
)


def _source() -> dict:
    return {
        "id": EXPECTED_SOURCE_BINDING["source_id"],
        "source_name": EXPECTED_SOURCE_BINDING["source_name"],
        "source_type": "database",
        "endpoint_url": "source://registered-example/makani",
        "enabled": True,
        "query_config": {
            "allowed_schemas": ["layer"],
            "discovery_mode": "metadata_only",
        },
        "discovery_fingerprint": EXPECTED_SOURCE_BINDING["discovery_fingerprint"],
        "profile_fingerprint": EXPECTED_SOURCE_BINDING["profile_fingerprint"],
    }


def test_registered_source_validation_fails_closed_on_scope_drift() -> None:
    assert validate_registered_source(_source()) == EXPECTED_SOURCE_BINDING
    drifted = _source()
    drifted["query_config"]["allowed_schemas"] = ["layer", "public"]
    with pytest.raises(ValueError, match="binding_drift"):
        validate_registered_source(drifted)


def test_layer_specs_are_minimized_and_exclude_personal_fields() -> None:
    forbidden = {
        "addressnumber",
        "asset_image",
        "comments",
        "created_user",
        "last_edited_user",
        "roadname_ar",
        "roadname_en",
    }
    assert len(LAYER_SPECS) == 13
    for spec in LAYER_SPECS:
        assert spec.fields[0] == "fid"
        assert spec.fields[-1] == "geom"
        assert not forbidden.intersection(spec.fields)
        sql = _select_sql(spec)
        assert f'"layer"."{spec.table_name}"' in sql
        assert "ST_Intersects" in sql
        assert not any(field in sql for field in forbidden)


def test_layer_spec_rejects_sensitive_or_unbounded_contract() -> None:
    with pytest.raises(ValueError, match="sensitive_field"):
        RegisteredMakaniLayerSpec(
            "st_pipeline",
            "pipeline",
            ("fid", "created_user", "geom"),
        )
    with pytest.raises(ValueError, match="require_fid_and_geom"):
        RegisteredMakaniLayerSpec("st_pipeline", "pipeline", ("unitid", "geom"))
