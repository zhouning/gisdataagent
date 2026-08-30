"""REST boundary tests for the first governed master-data slice."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, date, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from data_agent.api import platform_gateway_routes as routes
from data_agent.master_data_authority import (
    MASTER_DATA_ACTIVATION_ACTION,
    MasterDataConfigurationError,
    MasterDataDomain,
    MasterEntityActivation,
    MasterEntityVersion,
    MasterMatchResult,
    MasterMatchStatus,
    MasterResourceProjection,
    MasterResourceProjectionPage,
    MasterSourceRecord,
)
from data_agent.platform_contracts import ApprovalCase, ResourceVersion

TENANT = "tenant-a"
NOW = datetime(2026, 8, 4, 12, tzinfo=UTC)
ENTITY_ID = "administrative-unit-500112"
ENTITY_REF = f"gda://{TENANT}/master_entity/{ENTITY_ID}"
VERSION_REF = f"{ENTITY_REF}.v1"
SOURCE_KEY = "11111111111111111111111111111111"
SOURCE_REF = f"gda://{TENANT}/master_source_record/{SOURCE_KEY}"


def _request(*, body=None, path=None, query=None):
    request = MagicMock()

    async def read_json():
        return body or {}

    request.json.side_effect = read_json
    request.path_params = path or {}
    request.headers = {"x-request-id": "master-request-1"}
    request.query_params = query or {}
    return request


def _user(
    role="platform_operator",
    *,
    subject_type="human",
    identifier="operator-1",
):
    return SimpleNamespace(
        identifier=identifier,
        metadata={
            "role": role,
            "tenant_id": TENANT,
            "subject_type": subject_type,
        },
    )


def _source(**changes) -> MasterSourceRecord:
    values = {
        "tenant_id": TENANT,
        "source_record_ref": SOURCE_REF,
        "domain": MasterDataDomain.ADMINISTRATIVE_UNIT,
        "source_system_ref": f"gda://{TENANT}/source/national-admin-codes",
        "source_record_id": "500112",
        "source_revision": "2026-01-01",
        "business_key": "500112",
        "display_name": "璧山区",
        "parent_business_key": "500100",
        "attributes": {"level": "county"},
        "observed_by": "workload:master-harvester",
        "observed_at": NOW,
        "record_fingerprint": "a" * 64,
    }
    values.update(changes)
    return MasterSourceRecord(**values)


def _version(**changes) -> MasterEntityVersion:
    values = {
        "tenant_id": TENANT,
        "entity_ref": ENTITY_REF,
        "entity_version_ref": VERSION_REF,
        "version": 1,
        "domain": MasterDataDomain.ADMINISTRATIVE_UNIT,
        "business_key": "500112",
        "canonical_name": "璧山区",
        "attributes": {"level": "county"},
        "source_record_refs": (SOURCE_REF,),
        "match_candidate_refs": (),
        "valid_from": date(2026, 1, 1),
        "owner_subject": "team:natural-resource-governance",
        "created_by": "human:operator-1",
        "creation_reason": "stage governed administrative unit",
        "created_at": NOW,
        "entity_fingerprint": "b" * 64,
    }
    values.update(changes)
    return MasterEntityVersion(**values)


def _activation() -> MasterEntityActivation:
    return MasterEntityActivation(
        tenant_id=TENANT,
        entity_ref=ENTITY_REF,
        domain=MasterDataDomain.ADMINISTRATIVE_UNIT,
        business_key="500112",
        active_version_ref=VERSION_REF,
        active_fingerprint="b" * 64,
        approval_case_ref=f"gda://{TENANT}/approval_case/master-v1",
        activation_version=1,
        activated_by="human:admin-1",
        activation_reason="activate approved golden record",
        activated_at=NOW,
    )


def _resource_projection() -> MasterResourceProjection:
    return MasterResourceProjection(
        tenant_id=TENANT,
        entity_ref=ENTITY_REF,
        entity_version_ref=VERSION_REF,
        entity_fingerprint="b" * 64,
        activation_version=1,
        resource_version=ResourceVersion(
            tenant_id=TENANT,
            resource_urn=ENTITY_REF,
            resource_version_id="00000000-0000-5000-8000-000000000001",
            version_key="v1",
            content_sha256="b" * 64,
            authority_version_ref={
                "authority_system": "gda_control.master_data",
                "entity_version_ref": VERSION_REF,
                "entity_fingerprint": "b" * 64,
            },
            created_by="human:operator-1",
            created_at=NOW,
        ),
        approval_case_ref=f"gda://{TENANT}/approval_case/master-v1",
        projected_at=NOW,
    )


def test_observe_source_injects_tenant_actor_time_and_stable_identity() -> None:
    authority = MagicMock()
    authority.observe.side_effect = lambda draft: _source(
        source_record_ref=draft.source_record_ref,
        observed_by=draft.observed_by,
        observed_at=draft.observed_at,
    )
    body = {
        "domain": "administrative_unit",
        "source_system_ref": f"gda://{TENANT}/source/national-admin-codes",
        "source_record_id": "500112",
        "source_revision": "2026-01-01",
        "business_key": "500112",
        "display_name": "璧山区",
        "parent_business_key": "500100",
        "attributes": {"level": "county"},
    }
    workload = _user(subject_type="workload", identifier="master-harvester")

    with (
        patch.object(routes, "_get_user_from_request", return_value=workload),
        patch.object(routes, "_master_data_authority", return_value=authority),
        patch.object(routes, "_utc_now", return_value=NOW),
    ):
        response = asyncio.run(
            routes.observe_master_source_record(_request(body=body))
        )

    assert response.status_code == 200
    draft = authority.observe.call_args.args[0]
    assert draft.tenant_id == TENANT
    assert draft.observed_by == "workload:master-harvester"
    assert draft.observed_at == NOW
    assert draft.source_record_ref.startswith(
        f"gda://{TENANT}/master_source_record/"
    )
    assert json.loads(response.body)["data"]["business_key"] == "500112"


def test_match_endpoint_requires_machine_identity_and_injects_proposer() -> None:
    human = _user()
    with patch.object(routes, "_get_user_from_request", return_value=human):
        denied = asyncio.run(
            routes.propose_master_source_matches(
                _request(body={}, path={"source_record_key": SOURCE_KEY})
            )
        )
    assert denied.status_code == 403
    assert json.loads(denied.body)["error"]["code"] == (
        "master_match_machine_identity_required"
    )

    authority = MagicMock()
    authority.match.return_value = MasterMatchResult(
        tenant_id=TENANT,
        source_record=_source(),
        status=MasterMatchStatus.UNMATCHED,
        candidates=(),
    )
    agent = _user(subject_type="agent", identifier="master-matcher")
    with (
        patch.object(routes, "_get_user_from_request", return_value=agent),
        patch.object(routes, "_master_data_authority", return_value=authority),
        patch.object(routes, "_utc_now", return_value=NOW),
    ):
        response = asyncio.run(
            routes.propose_master_source_matches(
                _request(
                    body={"limit": 3},
                    path={"source_record_key": SOURCE_KEY},
                )
            )
        )
    assert response.status_code == 200
    assert authority.match.call_args.args == (TENANT, SOURCE_REF)
    assert authority.match.call_args.kwargs == {
        "proposed_by": "agent:master-matcher",
        "proposed_at": NOW,
        "limit": 3,
    }


def test_stage_and_approval_bind_server_owned_entity_version() -> None:
    authority = MagicMock()
    authority.stage.return_value = _version()
    authority.get.return_value = _version()
    source_refs = [SOURCE_REF]
    stage_body = {
        "version": 1,
        "domain": "administrative_unit",
        "business_key": "500112",
        "canonical_name": "璧山区",
        "attributes": {"level": "county"},
        "source_record_refs": source_refs,
        "match_candidate_refs": [],
        "valid_from": "2026-01-01",
        "owner_subject": "team:natural-resource-governance",
        "creation_reason": "stage governed administrative unit",
    }
    user = _user()
    with (
        patch.object(routes, "_get_user_from_request", return_value=user),
        patch.object(routes, "_master_data_authority", return_value=authority),
        patch.object(routes, "_utc_now", return_value=NOW),
    ):
        staged = asyncio.run(
            routes.stage_master_entity_version(
                _request(body=stage_body, path={"entity_id": ENTITY_ID})
            )
        )
    assert staged.status_code == 200
    draft = authority.stage.call_args.args[0]
    assert draft.entity_ref == ENTITY_REF
    assert draft.entity_version_ref == VERSION_REF
    assert draft.created_by == "human:operator-1"

    approval_authority = MagicMock()
    approval_authority.create.side_effect = lambda approval, **_: SimpleNamespace(
        approval_case=approval,
        created=True,
    )
    with (
        patch.object(routes, "_get_user_from_request", return_value=user),
        patch.object(routes, "_master_data_authority", return_value=authority),
        patch.object(
            routes,
            "_approval_case_authority",
            return_value=approval_authority,
        ),
        patch.object(routes, "_utc_now", return_value=NOW),
    ):
        response = asyncio.run(
            routes.create_master_activation_approval_case(
                _request(
                    body={
                        "case_id": "master-v1",
                        "request_reason": "review first golden record",
                    },
                    path={"entity_id": ENTITY_ID, "version": "1"},
                )
            )
        )
    assert response.status_code == 201
    approval: ApprovalCase = approval_authority.create.call_args.args[0]
    assert approval.action == MASTER_DATA_ACTIVATION_ACTION
    assert approval.target_resource_urn == VERSION_REF
    assert approval.target_fingerprint == "b" * 64
    assert approval.request_context["source_record_refs"] == source_refs


def test_activation_is_admin_only_and_maps_authority_unavailable() -> None:
    operator = _user()
    request = _request(
        body={
            "approval_case_id": "master-v1",
            "expected_activation_version": 0,
            "reason": "activate approved golden record",
        },
        path={"entity_id": ENTITY_ID, "version": "1"},
    )
    with patch.object(routes, "_get_user_from_request", return_value=operator):
        denied = asyncio.run(routes.activate_master_entity_version(request))
    assert denied.status_code == 403

    admin = _user(role="admin", identifier="admin-1")
    authority = MagicMock()
    authority.get.return_value = _version()
    authority.activate.return_value = _activation()
    with (
        patch.object(routes, "_get_user_from_request", return_value=admin),
        patch.object(routes, "_master_data_authority", return_value=authority),
    ):
        accepted = asyncio.run(
            routes.activate_master_entity_version(
                _request(
                    body={
                        "approval_case_id": "master-v1",
                        "expected_activation_version": 0,
                        "reason": "activate approved golden record",
                    },
                    path={"entity_id": ENTITY_ID, "version": "1"},
                )
            )
        )
    assert accepted.status_code == 200
    assert authority.activate.call_args.kwargs["entity_fingerprint"] == "b" * 64
    assert authority.activate.call_args.kwargs["actor_subject"] == "human:admin-1"

    authority.get.side_effect = MasterDataConfigurationError("database unavailable")
    with (
        patch.object(routes, "_get_user_from_request", return_value=admin),
        patch.object(routes, "_master_data_authority", return_value=authority),
    ):
        unavailable = asyncio.run(
            routes.activate_master_entity_version(
                _request(
                    body={
                        "approval_case_id": "master-v1",
                        "expected_activation_version": 0,
                        "reason": "activate approved golden record",
                    },
                    path={"entity_id": ENTITY_ID, "version": "1"},
                )
            )
        )
    assert unavailable.status_code == 503


def test_resource_projection_endpoint_uses_server_owned_identity_and_paging() -> None:
    authority = MagicMock()
    authority.resource_projections.return_value = MasterResourceProjectionPage(
        items=(_resource_projection(),),
        offset=2,
        limit=1,
        has_more=True,
    )
    with (
        patch.object(routes, "_get_user_from_request", return_value=_user()),
        patch.object(routes, "_master_data_authority", return_value=authority),
    ):
        response = asyncio.run(
            routes.list_master_resource_projections(
                _request(
                    path={"entity_id": ENTITY_ID},
                    query={"limit": "1", "offset": "2"},
                )
            )
        )

    assert response.status_code == 200
    assert authority.resource_projections.call_args.args == (TENANT, ENTITY_REF)
    assert authority.resource_projections.call_args.kwargs == {"limit": 1, "offset": 2}
    payload = json.loads(response.body)["data"]
    assert payload["count"] == 1
    assert payload["has_more"] is True
    assert payload["items"][0]["resource_version"]["version_key"] == "v1"

    with patch.object(routes, "_get_user_from_request", return_value=_user()):
        rejected = asyncio.run(
            routes.list_master_resource_projections(
                _request(
                    path={"entity_id": ENTITY_ID},
                    query={"limit": "101"},
                )
            )
        )
    assert rejected.status_code == 400
