from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from data_agent.cross_store_projection_compensation_chongqing_deployment import (
    build_chongqing_federated_compensation_deployment_binding,
    build_chongqing_federated_compensation_source_catalog,
)
from data_agent.cross_store_projection_compensation_chongqing_source_lineage import (
    ChongqingFederatedCompensationSourceLineageError,
    ChongqingFederatedCompensationSourceLineageSet,
    build_chongqing_federated_compensation_source_lineage_set,
)
from data_agent.test_cross_store_projection_compensation_provider_receipt_set import (
    _receipt_set_inputs,
)


def _lineage_inputs():
    intent, plan_set, materialization, _ = _receipt_set_inputs()
    source_catalog = build_chongqing_federated_compensation_source_catalog()
    deployment_binding = build_chongqing_federated_compensation_deployment_binding(
        intent,
        plan_set,
        materialization,
        source_catalog,
    )
    source_roles_by_position = {
        item.position: (source_catalog.sources[item.position].source_role,)
        for item in deployment_binding.items
    }
    return source_catalog, deployment_binding, source_roles_by_position


def test_source_lineage_binds_each_deployment_position_to_a_customer_source() -> None:
    source_catalog, deployment_binding, source_roles_by_position = _lineage_inputs()

    lineage_set = build_chongqing_federated_compensation_source_lineage_set(
        source_catalog,
        deployment_binding,
        source_roles_by_position,
    )

    assert tuple(item.position for item in lineage_set.items) == (0, 1, 2)
    assert tuple(
        item.customer_sources[0].source_role for item in lineage_set.items
    ) == tuple(source_roles_by_position[position][0] for position in range(3))
    assert lineage_set.deployment_binding_sha256 == (
        deployment_binding.deployment_binding_sha256
    )
    assert lineage_set.source_catalog_sha256 == source_catalog.source_catalog_sha256
    assert lineage_set.provider_dispatch_performed is False
    assert lineage_set.checkpoint_authority_write_performed is False
    assert lineage_set.compensation_completion_recorded is False
    document = json.dumps(lineage_set.model_dump(mode="json"), sort_keys=True)
    assert "relative_path" not in document
    assert "POLYGON" not in document
    assert "provider_commit_ref" not in document


@pytest.mark.parametrize(
    ("source_roles_by_position", "message"),
    [
        ({0: ("和平村规划地类",), 1: ("斑竹村规划地类",)}, "cover every deployment"),
        (
            {
                0: ("和平村规划地类",),
                1: ("斑竹村规划地类",),
                2: ("not-a-customer-source",),
            },
            "absent from the Chongqing catalog",
        ),
        (
            {
                0: ("和平村规划地类", "和平村规划地类"),
                1: ("斑竹村规划地类",),
                2: ("建设用地管制区",),
            },
            "unique and sorted",
        ),
    ],
)
def test_source_lineage_rejects_incomplete_unknown_or_duplicate_selections(
    source_roles_by_position: dict[int, tuple[str, ...]],
    message: str,
) -> None:
    source_catalog, deployment_binding, _ = _lineage_inputs()

    with pytest.raises(ChongqingFederatedCompensationSourceLineageError, match=message):
        build_chongqing_federated_compensation_source_lineage_set(
            source_catalog,
            deployment_binding,
            source_roles_by_position,
        )


def test_source_lineage_fingerprint_drift_fails_closed() -> None:
    source_catalog, deployment_binding, source_roles_by_position = _lineage_inputs()
    lineage_set = build_chongqing_federated_compensation_source_lineage_set(
        source_catalog,
        deployment_binding,
        source_roles_by_position,
    )
    drifted = lineage_set.model_copy(update={"source_catalog_sha256": "f" * 64})

    with pytest.raises(ValidationError, match="source lineage set fingerprint"):
        ChongqingFederatedCompensationSourceLineageSet.model_validate(
            drifted.model_dump(mode="python")
        )
