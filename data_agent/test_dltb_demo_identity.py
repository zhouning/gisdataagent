from __future__ import annotations

import geopandas as gpd
import pytest
from shapely.geometry import box

from data_agent.dltb_demo_identity import (
    _vector_profile,
    dataset_descriptor,
    require_matching_identity,
    require_upstream_dataset_id,
)


def test_bishan_descriptor_is_not_ninxia_authority_data():
    descriptor = dataset_descriptor("bishan")

    assert descriptor["dataset_id"] == "bishan"
    assert "璧山区" in descriptor["dataset_name"]
    assert "not Ningxia authority data" in descriptor["sample_scope"]


def test_registered_dataset_identity_mismatch_fails_closed():
    identity = {
        "dataset_id": "bishan",
        "verification_status": "mismatch",
        "mismatches": [
            {
                "role": "dltb",
                "check": "sha256",
                "expected": "expected",
                "actual": "planning-sample",
            }
        ],
    }

    with pytest.raises(ValueError, match="bishan source identity mismatch"):
        require_matching_identity(identity)


def test_phase2_rejects_a_different_phase1_dataset_id():
    upstream = {"dataset_identity": {"dataset_id": "chongqing_planning_sample"}}

    with pytest.raises(ValueError, match="phase 2 requested 'bishan'"):
        require_upstream_dataset_id(upstream, "bishan", required=True)


def test_phase2_rejects_legacy_report_without_dataset_identity():
    with pytest.raises(ValueError, match="rerun phase 1"):
        require_upstream_dataset_id({"schema": "legacy"}, "bishan", required=True)


def test_governed_geoparquet_identity_uses_geopandas_adapter(tmp_path):
    source = tmp_path / "DLTB.parquet"
    gpd.GeoDataFrame(
        {"BSM": ["1", "2"]},
        geometry=[box(0, 0, 1, 1), box(1, 0, 2, 1)],
        crs="EPSG:3857",
    ).to_parquet(source, index=False)

    profile = _vector_profile(source, ("DLTB",))

    assert profile["adapter"] == "geopandas_geoparquet"
    assert profile["feature_count"] == 2
    assert profile["crs"] == "EPSG:3857"
