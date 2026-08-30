"""HTTP contract tests for standard-aware virtual-source field mapping."""
from __future__ import annotations

from unittest.mock import patch

import pandas as pd
from starlette.applications import Starlette
from starlette.testclient import TestClient

from data_agent.api.virtual_routes import get_virtual_source_routes


class _User:
    identifier = "alice"
    metadata = {"role": "analyst"}


def _client() -> TestClient:
    return TestClient(Starlette(routes=get_virtual_source_routes()))


def _auth_patches():
    return (
        patch("data_agent.api.virtual_routes._get_user_from_request", return_value=_User()),
        patch("data_agent.api.virtual_routes._set_user_context", return_value=("alice", "analyst")),
    )


def test_standard_inference_profiles_sample_and_returns_versioned_contract():
    frame = pd.DataFrame({"DLBM": ["0101", "0201"], "TBMJ": [1.5, 2.5]})
    response_payload = {
        "schema": "gis-data-agent.standard-mapping-proposal.v1",
        "standard_version_id": "v1",
        "source_profile_hash": "abc",
        "mapping": {"DLBM": "dlbm"},
        "proposals": [],
    }
    auth, context = _auth_patches()
    with auth, context, \
         patch("data_agent.virtual_sources.get_virtual_source", return_value={"id": 7}), \
         patch("data_agent.virtual_sources.query_virtual_source", return_value=frame), \
         patch(
             "data_agent.standards_platform.application.service.propose_for_released_standard",
             return_value=response_payload,
         ) as propose:
        response = _client().post(
            "/api/virtual-sources/7/infer-mapping",
            json={
                "standard_version_id": "v1",
                "target_table": "parcel_current",
            },
        )

    assert response.status_code == 200
    assert response.json()["schema"] == "gis-data-agent.standard-mapping-proposal.v1"
    fields = propose.call_args.kwargs["source_fields"]
    assert [(field.name, field.dtype) for field in fields] == [
        ("DLBM", str(frame["DLBM"].dtype)),
        ("TBMJ", str(frame["TBMJ"].dtype)),
    ]
    assert fields[0].samples == ("0101", "0201")
    assert propose.call_args.kwargs["target_table"] == "parcel_current"


def test_standard_inference_rejects_non_released_version():
    frame = pd.DataFrame({"DLBM": ["0101"]})
    auth, context = _auth_patches()
    with auth, context, \
         patch("data_agent.virtual_sources.get_virtual_source", return_value={"id": 7}), \
         patch("data_agent.virtual_sources.query_virtual_source", return_value=frame), \
         patch(
             "data_agent.standards_platform.application.service.propose_for_released_standard",
             side_effect=ValueError("standard version must be released"),
         ):
        response = _client().post(
            "/api/virtual-sources/7/infer-mapping",
            json={"standard_version_id": "draft-version"},
        )

    assert response.status_code == 409
    assert response.json()["error"] == "standard version must be released"


def test_confirm_standard_mapping_returns_auditable_contract():
    confirmed = {
        "contract_id": "contract-1",
        "status": "confirmed",
        "mapping_count": 1,
        "execution_scope": "rename_only",
    }
    body = {
        "standard_version_id": "v1",
        "source_profile_hash": "abc",
        "schema_mapping": {"DLBM": "dlbm"},
        "field_bindings": [{
            "source_field": "DLBM",
            "target_data_element_id": "e1",
            "confidence": 1.0,
            "match_method": "lexical_type",
            "evidence": {"lexical_score": 1.0},
        }],
        "source_fields": ["DLBM", "UNUSED"],
        "review_decisions": [
            {
                "source_field": "DLBM",
                "decision": "approved",
                "reason": "recommendation_accepted",
            },
            {
                "source_field": "UNUSED",
                "decision": "rejected",
                "reason": "not_applicable",
            },
        ],
        "target_table": "parcel_current",
    }
    auth, context = _auth_patches()
    with auth, context, patch(
        "data_agent.standards_platform.application.service.confirm_virtual_source_mapping",
        return_value=confirmed,
    ) as confirm:
        response = _client().put(
            "/api/virtual-sources/7/schema-mapping", json=body,
        )

    assert response.status_code == 200
    assert response.json() == confirmed
    assert confirm.call_args.kwargs["owner_username"] == "alice"
    assert confirm.call_args.kwargs["field_bindings"] == body["field_bindings"]
    assert confirm.call_args.kwargs["review_decisions"] == body["review_decisions"]
    assert confirm.call_args.kwargs["target_table"] == "parcel_current"


def test_legacy_mapping_update_surfaces_repository_error():
    auth, context = _auth_patches()
    with auth, context, patch(
        "data_agent.virtual_sources.update_virtual_source",
        return_value={"status": "error", "message": "Source not found or not owned by you"},
    ):
        response = _client().put(
            "/api/virtual-sources/99/schema-mapping",
            json={"schema_mapping": {"old": "new"}},
        )

    assert response.status_code == 404


def test_inference_without_standard_keeps_canonical_fallback_contract():
    frame = pd.DataFrame({"pop": [1]})
    auth, context = _auth_patches()
    with auth, context, \
         patch("data_agent.virtual_sources.get_virtual_source", return_value={"id": 7}), \
         patch("data_agent.virtual_sources.query_virtual_source", return_value=frame), \
         patch(
             "data_agent.virtual_sources.infer_schema_mapping",
             return_value={"pop": "population"},
         ):
        response = _client().post("/api/virtual-sources/7/infer-mapping")

    assert response.status_code == 200
    assert response.json()["mapping"] == {"pop": "population"}
    assert response.json()["execution_policy"]["mode"] == "legacy_canonical_fallback"


def test_chongqing_acceptance_endpoint_returns_only_product_summary():
    auth, context = _auth_patches()
    with auth, context:
        response = _client().get(
            "/api/virtual-sources/standard-mapping-acceptance",
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["technical_status"] == "passed"
    assert payload["promotion_ready"] is False
    assert len(payload["cases"]) == 3
    encoded = str(payload)
    assert "relative_path" not in encoded
    assert "sha256" not in encoded


def test_quality_preflight_is_sampled_read_only_and_release_blocked():
    frame = pd.DataFrame({"DLBM": ["0101", "0201"], "TBMJ": [1.5, 2.5]})
    contract = {
        "contract_id": "contract-1",
        "mapping_hash": "a" * 64,
        "source_snapshot_hash": "b" * 64,
        "field_bindings": [
            {
                "source_field": "DLBM",
                "target_field": "dlbm",
                "target_data_element_id": "e1",
                "datatype": "VARCHAR",
                "representation_class": "code",
                "obligation": "mandatory",
            },
            {
                "source_field": "TBMJ",
                "target_field": "tbmj",
                "target_data_element_id": "e2",
                "datatype": "DECIMAL",
                "representation_class": "decimal",
                "obligation": "mandatory",
            },
        ],
    }
    auth, context = _auth_patches()
    with auth, context, \
         patch("data_agent.virtual_sources.get_virtual_source", return_value={"id": 7}), \
         patch(
             "data_agent.standards_platform.application.service.load_confirmed_virtual_source_mapping",
             return_value=contract,
         ), \
         patch(
             "data_agent.virtual_sources.query_virtual_source",
             return_value=frame,
         ) as query:
        response = _client().post(
            "/api/virtual-sources/7/quality-preflight",
            json={"sample_limit": 200},
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["verdict"] == "passed"
    assert payload["scope"]["full_dataset_validated"] is False
    assert payload["scope"]["authoritative_quality_assessment"] is False
    assert payload["release_candidate"]["data_product_version_created"] is False
    query.assert_awaited_once_with(
        {"id": 7}, limit=200, register_result=False,
    )


def test_quality_preflight_requires_confirmed_mapping_contract():
    auth, context = _auth_patches()
    with auth, context, \
         patch("data_agent.virtual_sources.get_virtual_source", return_value={"id": 7}), \
         patch(
             "data_agent.standards_platform.application.service.load_confirmed_virtual_source_mapping",
             side_effect=LookupError(
                 "confirmed standard mapping contract not found",
             ),
         ):
        response = _client().post(
            "/api/virtual-sources/7/quality-preflight",
            json={"sample_limit": 200},
        )

    assert response.status_code == 409
    assert response.json()["error"] == (
        "confirmed standard mapping contract not found"
    )


def test_quality_preflight_rejects_unbounded_sample_limit():
    auth, context = _auth_patches()
    with auth, context:
        response = _client().post(
            "/api/virtual-sources/7/quality-preflight",
            json={"sample_limit": 1001},
        )

    assert response.status_code == 400
