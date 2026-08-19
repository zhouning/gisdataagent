from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from data_agent.cross_store_projection_compensation_chongqing_deployment import (
    build_chongqing_federated_compensation_deployment_binding,
    build_chongqing_federated_compensation_source_catalog,
)
from data_agent.cross_store_projection_compensation_chongqing_source_lineage import (
    build_chongqing_federated_compensation_source_lineage_set,
)
from data_agent.cross_store_projection_compensation_chongqing_source_selection_profile import (
    ChongqingFederatedCompensationSourceSelectionProfile,
    ChongqingFederatedCompensationSourceSelectionProfileError,
    build_chongqing_federated_compensation_profiled_source_lineage_binding,
    build_chongqing_federated_compensation_source_selection_profile,
)
from data_agent.test_cross_store_projection_compensation_provider_receipt_set import (
    _receipt_set_inputs,
)


def _profiled_lineage_inputs():
    intent, plan_set, materialization, _ = _receipt_set_inputs()
    source_catalog = build_chongqing_federated_compensation_source_catalog()
    deployment_binding = build_chongqing_federated_compensation_deployment_binding(
        intent,
        plan_set,
        materialization,
        source_catalog,
    )
    profile = build_chongqing_federated_compensation_source_selection_profile(
        source_catalog,
        "heping_review",
    )
    source_roles_by_position = {
        0: profile.required_source_roles[:3],
        1: profile.required_source_roles[3:5],
        2: profile.required_source_roles[5:],
    }
    source_lineage_set = build_chongqing_federated_compensation_source_lineage_set(
        source_catalog,
        deployment_binding,
        source_roles_by_position,
    )
    return source_catalog, deployment_binding, profile, source_lineage_set


def test_customer_scenario_profile_restricts_and_completely_covers_source_lineage() -> None:
    source_catalog, deployment_binding, profile, source_lineage_set = (
        _profiled_lineage_inputs()
    )

    binding = build_chongqing_federated_compensation_profiled_source_lineage_binding(
        source_catalog,
        deployment_binding,
        profile,
        source_lineage_set,
    )

    assert profile.profile_id == "chongqing-heping-review-source-selection-baseline-v1"
    assert binding.selected_source_roles == profile.required_source_roles
    assert binding.source_selection_profile_sha256 == profile.profile_sha256
    assert binding.provider_dispatch_performed is False
    document = json.dumps(binding.model_dump(mode="json"), sort_keys=True)
    assert "relative_path" not in document
    assert "POLYGON" not in document
    assert "provider_commit_ref" not in document


def test_profiled_lineage_rejects_missing_or_cross_scenario_source_roles() -> None:
    source_catalog, deployment_binding, profile, _ = _profiled_lineage_inputs()
    incomplete_lineage = build_chongqing_federated_compensation_source_lineage_set(
        source_catalog,
        deployment_binding,
        {
            0: profile.required_source_roles[:3],
            1: profile.required_source_roles[3:5],
            2: ("斑竹村规划地类",),
        },
    )

    with pytest.raises(
        ChongqingFederatedCompensationSourceSelectionProfileError,
        match="exactly cover",
    ):
        build_chongqing_federated_compensation_profiled_source_lineage_binding(
            source_catalog,
            deployment_binding,
            profile,
            incomplete_lineage,
        )


def test_profile_fingerprint_drift_fails_closed() -> None:
    source_catalog, _, profile, _ = _profiled_lineage_inputs()
    drifted = profile.model_copy(update={"source_catalog_sha256": "f" * 64})

    with pytest.raises(ValidationError, match="profile fingerprint"):
        ChongqingFederatedCompensationSourceSelectionProfile.model_validate(
            drifted.model_dump(mode="python")
        )

    banzhu = build_chongqing_federated_compensation_source_selection_profile(
        source_catalog,
        "banzhu_adjustment",
    )
    assert banzhu.required_source_roles == tuple(sorted(banzhu.required_source_roles))
