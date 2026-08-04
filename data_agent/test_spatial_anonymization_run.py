from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest

from data_agent.platform_authorization import parse_policy_decision_artifact
from data_agent.spatial_anonymization_run import (
    SPATIAL_ANONYMIZATION_SEMANTIC_TYPE,
    SpatialAnonymizationRequest,
    SpatialAnonymizationRunSpec,
    build_spatial_anonymization_resources,
    build_spatial_anonymization_submission,
    parse_spatial_anonymization_version,
    spatial_anonymization_dataops_client_request_id,
    spatial_anonymization_lock_keys,
    spatial_anonymization_request_fingerprint,
    spatial_anonymization_request_identity,
    spatial_anonymization_version_id,
)

TENANT = "tenant-a"
DEFINITION_ID = UUID("40000000-0000-4000-8000-000000000010")
PLAN_ID = UUID("40000000-0000-4000-8000-000000000020")
ADMITTED_AT = datetime(2026, 8, 3, 8, 0, tzinfo=UTC)


def _request(**overrides):
    values = {
        "tenant_id": TENANT,
        "client_request_id": "spatial-mask-20260803-001",
        "requester_subject": "human:data-governance-operator",
        "source_asset_ref": "agent_data_assets:17",
        "source_schema": "geo",
        "source_table": "restricted_parcels",
        "output_schema": "public",
        "output_table": "restricted_parcels_l3",
        "data_type": "polygon",
        "level": "L3",
        "k_anonymity": 5,
        "keep_attrs": ("tbmj", "dlmc"),
        "agg_strategy": "area_weighted",
        "dp_epsilon": 1.0,
        "dp_numeric_fields": ("tbmj",),
    }
    values.update(overrides)
    return SpatialAnonymizationRequest(**values)


def _spec(**overrides):
    values = {
        "request": _request(),
        "definition_version_id": DEFINITION_ID,
        "execution_plan_artifact_id": PLAN_ID,
        "workload_subject_id": "spatial-anonymization-worker",
        "workload_roles": ("platform_operator",),
        "purpose": "produce a governed anonymized spatial output",
        "policy_version_ref": "gda://tenant-a/policy/spatial-anonymization:v1",
        "policy_evaluator_subject": "workload:policy-evaluator",
        "config_fingerprint": "a" * 64,
    }
    values.update(overrides)
    return SpatialAnonymizationRunSpec(**values)


def test_request_identity_is_stable_while_payload_drift_is_visible():
    first = _request()
    changed = _request(k_anonymity=10)

    assert spatial_anonymization_request_identity(first) == (
        spatial_anonymization_request_identity(changed)
    )
    assert spatial_anonymization_lock_keys(first) == spatial_anonymization_lock_keys(
        changed
    )
    assert spatial_anonymization_dataops_client_request_id(first) == (
        spatial_anonymization_dataops_client_request_id(changed)
    )
    assert spatial_anonymization_request_fingerprint(first) != (
        spatial_anonymization_request_fingerprint(changed)
    )
    assert spatial_anonymization_version_id(first) != spatial_anonymization_version_id(
        changed
    )


def test_request_resource_version_round_trips_complete_operation():
    request = _request()
    resource, version = build_spatial_anonymization_resources(
        request,
        created_at=ADMITTED_AT,
    )

    assert resource.resource_kind == "anonymization"
    assert resource.technical_refs[0]["asset_ref"] == "agent_data_assets:17"
    assert version.content_sha256 == spatial_anonymization_request_fingerprint(request)
    assert parse_spatial_anonymization_version(version) == request

    tampered = version.model_copy(update={"content_sha256": "b" * 64})
    with pytest.raises(ValueError, match="metadata does not match"):
        parse_spatial_anonymization_version(tampered)


def test_submission_binds_request_invocation_policy_and_dispatch_scope():
    submission = build_spatial_anonymization_submission(
        _spec(),
        admitted_at=ADMITTED_AT,
    )
    run = submission.run
    bindings = {item.binding_name: item for item in run.input_bindings}
    decision = parse_policy_decision_artifact(
        submission.manual_submission.policy_artifact
    )

    assert tuple(bindings) == ("anonymization_request", "invocation")
    assert bindings["anonymization_request"].semantic_type == (
        SPATIAL_ANONYMIZATION_SEMANTIC_TYPE
    )
    assert run.orchestration_class.value == "dataops"
    assert run.subject_context.subject_id == "spatial-anonymization-worker"
    assert run.subject_context.delegated_by == "human:data-governance-operator"
    assert decision.resource_version_ids == tuple(
        sorted(
            {
                DEFINITION_ID,
                submission.request_version.resource_version_id,
                submission.manual_submission.invocation_version.resource_version_id,
            },
            key=str,
        )
    )
    assert submission.manual_spec.logical_start == ADMITTED_AT
    assert submission.manual_spec.logical_end == ADMITTED_AT + timedelta(microseconds=1)


@pytest.mark.parametrize(
    "overrides",
    (
        {"output_schema": "private"},
        {"output_table": "restricted_parcels", "output_schema": "geo"},
        {"dp_epsilon": 1.0, "dp_numeric_fields": ()},
        {"dp_epsilon": None, "dp_numeric_fields": ("tbmj",)},
        {"data_type": "point", "category_column": None, "top_k_categories": None},
    ),
)
def test_request_rejects_ambiguous_or_incomplete_execution_contract(overrides):
    with pytest.raises(ValueError):
        _request(**overrides)


def test_point_request_rejects_polygon_only_parameters():
    with pytest.raises(ValueError, match="polygon aggregation fields"):
        _request(
            data_type="point",
            category_column="category",
            top_k_categories=5,
        )
