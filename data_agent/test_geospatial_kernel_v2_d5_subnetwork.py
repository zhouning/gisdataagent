from __future__ import annotations

import pytest

from scripts.compile_geotransport_center_hill_v2_d5_full_subnetwork import (
    compile_upstream_domain,
)


def _compile(**overrides):
    values = {
        "source_links": (1, 2, 3, 4, 10, 11, 20, 21, 22),
        "source_to": (2, 3, 4, 0, 11, 2, 21, 22, 3),
        "branch_mouth_ids": (11, 22),
        "active_mainstem_ids": (1, 2, 3, 4),
        "expected_receiving_by_mouth": {11: 2, 22: 3},
        "forbidden_feature_ids": (99,),
        "outlet_feature_id": 4,
    }
    values.update(overrides)
    return compile_upstream_domain(**values)


def test_compile_upstream_domain_internalizes_complete_branches() -> None:
    feature_ids, downstream_ids, memberships = _compile()

    assert set(feature_ids) == {1, 2, 3, 4, 10, 11, 20, 21, 22}
    assert feature_ids[-1] == 4
    assert dict(zip(feature_ids, downstream_ids, strict=True))[4] is None
    assert memberships == {11: (10, 11), 22: (20, 21, 22)}
    positions = {feature: index for index, feature in enumerate(feature_ids)}
    for source, target in zip(feature_ids, downstream_ids, strict=True):
        if target is not None:
            assert positions[source] < positions[target]


def test_compile_upstream_domain_rejects_wrong_mouth_attachment() -> None:
    with pytest.raises(ValueError, match="mouth_downstream_target_mismatch"):
        _compile(expected_receiving_by_mouth={11: 3, 22: 3})


def test_compile_upstream_domain_rejects_forbidden_upstream_ancestor() -> None:
    with pytest.raises(ValueError, match="forbidden_ancestor_present"):
        _compile(
            source_links=(1, 2, 3, 4, 10, 11, 20, 21, 22, 99),
            source_to=(2, 3, 4, 0, 11, 2, 21, 22, 3, 10),
        )


def test_compile_upstream_domain_rejects_overlapping_direct_mouth_basins() -> None:
    with pytest.raises(ValueError, match="incremental_branches_overlap"):
        _compile(
            branch_mouth_ids=(11, 10, 22),
            expected_receiving_by_mouth={11: 2, 10: 11, 22: 3},
        )


def test_compile_upstream_domain_rejects_cycle() -> None:
    with pytest.raises(ValueError, match="subnetwork_cycle_detected"):
        _compile(
            source_to=(2, 1, 4, 0, 11, 2, 21, 22, 3),
        )
