from __future__ import annotations

from datetime import datetime, timezone

import numpy as np

from scripts.acquire_geotransport_v2_blind_validation_outcomes import _outcome_csv
from scripts.compile_geotransport_center_hill_v2_d5_full_subnetwork import (
    compile_upstream_domain,
)
from scripts.compile_geotransport_j_percy_priest_v1_full_subnetwork import (
    derive_direct_branch_mouths,
)
from scripts.freeze_geotransport_v2_blind_validation_protocol import (
    _terminal_length_fraction,
)


def test_direct_branch_discovery_excludes_control_and_mainstem() -> None:
    links = np.asarray([1, 2, 3, 10, 11, 20, 30], dtype=np.int64)
    targets = np.asarray([2, 3, 0, 2, 10, 3, 2], dtype=np.int64)

    mouths, receiving = derive_direct_branch_mouths(
        source_links=links,
        source_to=targets,
        active_mainstem_ids=(2, 3),
        excluded_control_ids=(1, 30),
    )

    assert mouths == (10, 20)
    assert receiving == {10: 2, 20: 3}


def test_full_domain_keeps_control_outside_natural_branch_closure() -> None:
    features, downstream, memberships = compile_upstream_domain(
        source_links=(1, 2, 3, 10, 11, 20, 21),
        source_to=(2, 3, 0, 2, 10, 3, 20),
        branch_mouth_ids=(10, 20),
        active_mainstem_ids=(2, 3),
        expected_receiving_by_mouth={10: 2, 20: 3},
        forbidden_feature_ids=(1,),
        outlet_feature_id=3,
    )

    assert 1 not in features
    assert memberships == {10: (10, 11), 20: (20, 21)}
    assert dict(zip(features, downstream, strict=True))[3] is None
    positions = {feature: index for index, feature in enumerate(features)}
    for source, target in zip(features, downstream, strict=True):
        if target is not None:
            assert positions[source] < positions[target]


def test_partial_terminal_forcing_support_is_outcome_free_length_fraction() -> None:
    network = {
        "outlet_feature_id": 3,
        "feature_ids": [1, 2, 3],
        "full_lengths_m": [10.0, 20.0, 100.0],
        "effective_lengths_m": [10.0, 20.0, 25.0],
    }

    assert _terminal_length_fraction(network) == 0.25


def test_blind_outcome_csv_keeps_prior_role_separate_from_targets() -> None:
    first = datetime(2022, 3, 31, 1, tzinfo=timezone.utc)
    second = datetime(2022, 3, 31, 2, tzinfo=timezone.utc)

    body = _outcome_csv((first, second), {first: 1.5, second: None})

    lines = body.decode("utf-8").splitlines()
    assert lines[1].endswith(",independent_observation,persistence_prior")
    assert lines[2].endswith(",independent_observation,target")
    assert ",," in lines[2]
