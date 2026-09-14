"""Contract tests for the Abu Dhabi semantic admin and virtual-lake read models."""

import json
from unittest.mock import MagicMock
from types import SimpleNamespace

import pytest
from starlette.requests import Request

from data_agent.api import abu_dhabi_semantic_admin_routes as routes


async def _receive():
    return {"type": "http.request", "body": b"", "more_body": False}


def _request(
    *,
    query: str = "",
    path_params: dict | None = None,
    method: str = "GET",
    body: bytes = b"",
    path: str = "/",
) -> Request:
    async def receive():
        return {"type": "http.request", "body": body, "more_body": False}

    return Request(
        {
            "type": "http",
            "method": method,
            "path": path,
            "headers": [],
            "query_string": query.encode(),
            "path_params": path_params or {},
        },
        receive=receive,
    )


@pytest.mark.asyncio
async def test_admin_read_model_exposes_reviewed_baseline_without_database(monkeypatch):
    user = SimpleNamespace(identifier="analyst", metadata={"role": "analyst"})
    monkeypatch.setattr(routes, "_get_user_from_request", lambda request: user)
    monkeypatch.setattr(routes, "_set_user_context", lambda value: ("analyst", "analyst"))
    monkeypatch.setattr(routes, "_engine", lambda: None)

    response = await routes.semantic_admin_entries(
        _request(query="scope=liveability", path_params={"entry_type": "assets"})
    )
    payload = json.loads(response.body)

    assert response.status_code == 200
    # The baseline is artifact-backed and intentionally evolves with the
    # published semantic version; assert the route exposes the full current
    # reviewed set instead of freezing a historical asset count.
    assert payload["total"] == len(routes._baseline_entries("liveability", "assets"))
    assert payload["total"] > 0
    assert payload["baseline_is_immutable"] is True
    assert all(item["source"] == "artifact" for item in payload["items"])
    assert all("credential" not in json.dumps(item).casefold() for item in payload["items"])


@pytest.mark.asyncio
async def test_virtual_lake_metadata_falls_back_to_technical_catalog_evidence(monkeypatch):
    user = SimpleNamespace(identifier="analyst", metadata={"role": "analyst"})
    monkeypatch.setattr(routes, "_get_user_from_request", lambda request: user)
    monkeypatch.setattr(routes, "_set_user_context", lambda value: ("analyst", "analyst"))
    monkeypatch.setattr(routes, "_engine", lambda: None)

    response = await routes.virtual_lake_metadata(_request())
    payload = json.loads(response.body)

    assert response.status_code == 200
    assert [item["source_id"] for item in payload["items"]] == [12, 13]
    # The technical catalog is the source of truth for resource discovery.
    expected_counts = [
        len(routes._artifact_metadata(scope)[1])
        for scope in ("liveability", "makani")
    ]
    assert [item["resource_count"] for item in payload["items"]] == expected_counts
    assert all(item["source_rows_persisted"] is False for item in payload["items"])
    assert all(item["metadata_origin"] == "artifact_technical_catalog_evidence" for item in payload["items"])
    assert all("auth_config" not in json.dumps(item) for item in payload["items"])
    liveability = payload["items"][0]
    first_column = liveability["resources"][0]["columns"][0]
    assert first_column["name"]
    assert first_column["type"] != "unknown"


@pytest.mark.asyncio
async def test_metric_contract_overview_is_artifact_backed_and_reports_unconnected_observations(monkeypatch):
    user = SimpleNamespace(identifier="analyst", metadata={"role": "analyst"})
    monkeypatch.setattr(routes, "_get_user_from_request", lambda request: user)
    monkeypatch.setattr(routes, "_set_user_context", lambda value: ("analyst", "analyst"))
    monkeypatch.setattr(routes, "_engine", lambda: None)

    response = await routes.semantic_metric_contracts_overview(
        _request(query="scope=liveability")
    )
    payload = json.loads(response.body)

    assert response.status_code == 200
    assert payload["artifact_status"] == "available"
    assert payload["contracts"]["total"] == len(routes._artifact("liveability").get("metric_contracts") or [])
    assert payload["observation"]["status"] == "not_connected"
    assert payload["observation"]["observation_count"] is None
    assert payload["claim_boundary"]["source_rows_persisted"] is False
    assert "/Users/" not in json.dumps(payload)


@pytest.mark.asyncio
async def test_metric_observation_overview_fails_closed_when_store_is_unavailable(monkeypatch):
    class BrokenEngine:
        def connect(self):
            raise RuntimeError("database unavailable")

    monkeypatch.setattr(routes, "_engine", lambda: BrokenEngine())
    payload = routes._metric_observation_status("liveability")
    assert payload["status"] == "unavailable"
    assert payload["observation_count"] is None
    assert payload["latest_observed_at"] is None


@pytest.mark.asyncio
async def test_admin_mutation_requires_editor_role(monkeypatch):
    user = SimpleNamespace(identifier="viewer", metadata={"role": "viewer"})
    monkeypatch.setattr(routes, "_get_user_from_request", lambda request: user)
    monkeypatch.setattr(routes, "_set_user_context", lambda value: ("viewer", "viewer"))

    response = await routes.semantic_admin_create(
        _request(query="scope=liveability", path_params={"entry_type": "assets"})
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_generic_registered_source_scope_is_supported(monkeypatch):
    user = SimpleNamespace(identifier="analyst", metadata={"role": "analyst"})
    monkeypatch.setattr(routes, "_get_user_from_request", lambda request: user)
    monkeypatch.setattr(routes, "_set_user_context", lambda value: ("analyst", "analyst"))
    monkeypatch.setattr(routes, "_engine", lambda: None)

    response = await routes.semantic_admin_entries(
        _request(query="scope=source_42", path_params={"entry_type": "assets"})
    )
    payload = json.loads(response.body)
    assert response.status_code == 200
    assert payload["scope"] == "source_42"
    assert payload["total"] == 0


@pytest.mark.asyncio
async def test_metric_contract_hyphen_alias_normalizes_to_canonical_entry_type(monkeypatch):
    user = SimpleNamespace(identifier="analyst", metadata={"role": "analyst"})
    monkeypatch.setattr(routes, "_get_user_from_request", lambda request: user)
    monkeypatch.setattr(routes, "_set_user_context", lambda value: ("analyst", "analyst"))
    monkeypatch.setattr(routes, "_engine", lambda: None)

    response = await routes.semantic_admin_entries(
        _request(query="scope=liveability", path_params={"entry_type": "metric-contracts"})
    )
    payload = json.loads(response.body)

    assert response.status_code == 200
    assert payload["entry_type"] == "metric_contracts"
    assert payload["total"] == len(routes._baseline_entries("liveability", "metric_contracts"))


@pytest.mark.asyncio
async def test_metric_contract_alias_does_not_bypass_scope_validation(monkeypatch):
    user = SimpleNamespace(identifier="analyst", metadata={"role": "analyst"})
    monkeypatch.setattr(routes, "_get_user_from_request", lambda request: user)
    monkeypatch.setattr(routes, "_set_user_context", lambda value: ("analyst", "analyst"))

    response = await routes.semantic_admin_entries(
        _request(query="scope=not a scope", path_params={"entry_type": "metric-contracts"})
    )

    assert response.status_code == 400
    assert json.loads(response.body)["error"] == "unsupported scope or entry_type"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("path", "expected_entry_type"),
    [
        ("/api/semantic/governance/assets", "assets"),
        ("/api/semantic/governance/fields", "fields"),
        ("/api/semantic/governance/relationships", "relationships"),
        ("/api/semantic/governance/metric_contracts", "metric_contracts"),
        ("/api/semantic/governance/metric-contracts", "metric_contracts"),
    ],
)
async def test_literal_governance_routes_resolve_entry_type_from_request_path(
    monkeypatch, path, expected_entry_type
):
    user = SimpleNamespace(identifier="analyst", metadata={"role": "analyst"})
    monkeypatch.setattr(routes, "_get_user_from_request", lambda request: user)
    monkeypatch.setattr(routes, "_set_user_context", lambda value: ("analyst", "analyst"))
    monkeypatch.setattr(routes, "_engine", lambda: None)

    response = await routes.semantic_admin_entries(
        _request(query="scope=liveability", path=path)
    )
    payload = json.loads(response.body)

    assert response.status_code == 200
    assert payload["entry_type"] == expected_entry_type
    assert payload["total"] == len(routes._baseline_entries("liveability", expected_entry_type))


@pytest.mark.asyncio
async def test_review_queue_is_paged_redacted_and_projects_nonapproved_drafts(monkeypatch):
    user = SimpleNamespace(identifier="analyst", metadata={"role": "analyst"})
    monkeypatch.setattr(routes, "_get_user_from_request", lambda request: user)
    monkeypatch.setattr(routes, "_set_user_context", lambda value: ("analyst", "analyst"))
    monkeypatch.setattr(
        routes,
        "_review_queue",
        lambda scope: {
            "coverage": {"field_task_count": 2, "review_required_field_count": 1},
            "source": {"dictionary_evidence": "/Users/example/private/dictionary.json"},
            "field_tasks": [
                {
                    "task_id": "FIELD_1",
                    "kind": "field_semantic_review",
                    "physical_table": "public.facilities",
                    "physical_field": "capacity",
                    "current": {"labels": {"zh": "容量", "en": "capacity"}},
                    "suggested": {"data_type": "INTEGER"},
                    "dictionary_evidence": {
                        "support_status": "dictionary_exact_supported",
                        "dictionary_description": "学校容量",
                        "path": "/Users/example/private/capacity.md",
                    },
                    "review_status": "review_required",
                    "required_decisions": ["确认单位和可加性"],
                },
                {
                    "task_id": "FIELD_2",
                    "kind": "field_semantic_review",
                    "physical_table": "public.facilities",
                    "physical_field": "name",
                    "current": {"labels": {"zh": "名称"}, "business_role": "dimension"},
                    "review_status": "reviewed",
                },
            ],
        },
    )
    monkeypatch.setattr(
        routes,
        "_artifact",
        lambda scope: {
            "semantic_assets": [
                {"asset_id": "facility.asset", "physical_tables": ["public.facilities"]}
            ],
            "table_bindings": [],
        },
    )

    response = await routes.semantic_review_queue(
        _request(query="scope=makani&kind=field&status=review_required&limit=1")
    )
    payload = json.loads(response.body)

    assert response.status_code == 200
    assert payload["total"] == 1
    assert payload["has_more"] is False
    assert payload["claim_boundary"]["unreviewed_items_are_executable"] is False
    assert payload["source"]["dictionary_evidence"] == "external_artifact/dictionary.json"
    item = payload["items"][0]
    assert item["dictionary_evidence"]["path"] == "external_artifact/capacity.md"
    assert item["draft"]["entry_type"] == "fields"
    assert item["draft"]["payload"]["asset_id"] == "facility.asset"
    assert item["draft"]["payload"]["review_status"] == "candidate_review"
    assert item["draft"]["not_approved"] is True
    assert "/Users/" not in json.dumps(payload)


@pytest.mark.asyncio
async def test_review_queue_rejects_unknown_kind(monkeypatch):
    user = SimpleNamespace(identifier="analyst", metadata={"role": "analyst"})
    monkeypatch.setattr(routes, "_get_user_from_request", lambda request: user)
    monkeypatch.setattr(routes, "_set_user_context", lambda value: ("analyst", "analyst"))

    response = await routes.semantic_review_queue(
        _request(query="scope=makani&kind=metric")
    )

    assert response.status_code == 400


@pytest.mark.asyncio
async def test_review_queue_merges_persisted_semantic_decision_without_changing_candidate(monkeypatch):
    user = SimpleNamespace(identifier="reviewer", metadata={"role": "standard_reviewer"})
    monkeypatch.setattr(routes, "_get_user_from_request", lambda request: user)
    monkeypatch.setattr(routes, "_set_user_context", lambda value: ("reviewer", "standard_reviewer"))
    monkeypatch.setattr(
        routes,
        "_review_queue",
        lambda scope: {
            "coverage": {"field_task_count": 1, "review_required_field_count": 1},
            "field_tasks": [{
                "task_id": "FIELD_1",
                "physical_table": "public.facilities",
                "physical_field": "capacity",
                "review_status": "review_required",
                "binding_status": "technical_metadata_only",
            }],
        },
    )
    monkeypatch.setattr(
        routes,
        "_semantic_reviews",
        lambda scope, kind: ({
            "FIELD_1": {
                "decision": "approved_for_draft",
                "review_notes": "字段含义已确认",
                "reviewed_by": "reviewer",
            }
        }, True),
    )
    monkeypatch.setattr(routes, "_artifact", lambda scope: {"semantic_assets": [], "table_bindings": []})

    response = await routes.semantic_review_queue(
        _request(query="scope=makani&kind=field&status=reviewed")
    )
    payload = json.loads(response.body)
    assert response.status_code == 200
    assert payload["total"] == 1
    assert payload["items"][0]["review_status"] == "reviewed"
    assert payload["items"][0]["candidate_review_status"] == "review_required"
    assert payload["items"][0]["review"]["decision"] == "approved_for_draft"
    assert payload["claim_boundary"]["is_business_semantic_authority"] is False


@pytest.mark.asyncio
async def test_benchmark_review_queue_is_paged_redacted_and_not_gold(monkeypatch):
    user = SimpleNamespace(identifier="analyst", metadata={"role": "analyst"})
    monkeypatch.setattr(routes, "_get_user_from_request", lambda request: user)
    monkeypatch.setattr(routes, "_set_user_context", lambda value: ("analyst", "analyst"))
    monkeypatch.setattr(
        routes,
        "_benchmark_review_queue",
        lambda scope: {
            "coverage": {"question_slot_count": 2, "language_variant_count": 6},
            "source": {"dictionary_evidence": "/Users/example/private/dictionary.json"},
            "tasks": [
                {
                    "task_id": "BENCH_1",
                    "kind": "business_benchmark_question_slot",
                    "physical_table": "public.facilities",
                    "physical_field": "capacity",
                    "business_asset_id": "facility.asset",
                    "operation": "aggregate_summary",
                    "field_role": "measure",
                    "labels": {"zh": "容量", "en": "capacity"},
                    "question_templates": {"zh": "统计容量"},
                    "languages": ["zh"],
                    "review_status": "pending_business_gold_review",
                    "promotion_requirements": ["确认单位和可加性"],
                    "dictionary_evidence": {
                        "support_status": "dictionary_exact_supported",
                        "path": "/Users/example/private/capacity.md",
                    },
                    "gold_sql": "SELECT secret",
                },
                {
                    "task_id": "BENCH_2",
                    "physical_table": "public.facilities",
                    "physical_field": "name",
                    "review_status": "reviewed",
                },
            ],
        },
    )

    response = await routes.semantic_benchmark_review_queue(
        _request(query="scope=makani&status=pending_business_gold_review&limit=1")
    )
    payload = json.loads(response.body)

    assert response.status_code == 200
    assert payload["total"] == 1
    assert payload["claim_boundary"]["is_scored_benchmark"] is False
    assert payload["claim_boundary"]["is_gold_set"] is False
    assert payload["claim_boundary"]["gold_sql_present"] is False
    assert payload["source"]["dictionary_evidence"] == "external_artifact/dictionary.json"
    item = payload["items"][0]
    assert item["task_id"] == "BENCH_1"
    assert item["dictionary_evidence"]["path"] == "external_artifact/capacity.md"
    assert "gold_sql" not in item
    assert "/Users/" not in json.dumps(payload)


@pytest.mark.asyncio
async def test_benchmark_review_queue_rejects_unknown_status(monkeypatch):
    user = SimpleNamespace(identifier="analyst", metadata={"role": "analyst"})
    monkeypatch.setattr(routes, "_get_user_from_request", lambda request: user)
    monkeypatch.setattr(routes, "_set_user_context", lambda value: ("analyst", "analyst"))

    response = await routes.semantic_benchmark_review_queue(
        _request(query="scope=makani&status=approved")
    )

    assert response.status_code == 400


@pytest.mark.asyncio
async def test_benchmark_review_queue_merges_persisted_decision_without_promoting_gold(monkeypatch):
    user = SimpleNamespace(identifier="reviewer", metadata={"role": "standard_reviewer"})
    monkeypatch.setattr(routes, "_get_user_from_request", lambda request: user)
    monkeypatch.setattr(routes, "_set_user_context", lambda value: ("reviewer", "standard_reviewer"))
    monkeypatch.setattr(
        routes,
        "_benchmark_review_queue",
        lambda scope: {
            "coverage": {"question_slot_count": 1, "language_variant_count": 3},
            "tasks": [{
                "task_id": "BENCH_1",
                "physical_table": "public.facilities",
                "physical_field": "capacity",
                "review_status": "pending_business_gold_review",
            }],
        },
    )
    monkeypatch.setattr(
        routes,
        "_benchmark_reviews",
        lambda scope: ({"BENCH_1": {
            "decision": "approved_for_gold",
            "review_notes": "单位已由业务专家确认",
            "question_templates": {"zh": "统计容量"},
            "evidence": {"is_gold": False},
            "reviewed_by": "reviewer",
        }}, True),
    )

    response = await routes.semantic_benchmark_review_queue(
        _request(query="scope=makani&status=reviewed")
    )
    payload = json.loads(response.body)
    assert response.status_code == 200
    assert payload["total"] == 1
    assert payload["coverage"]["persisted_review_count"] == 1
    assert payload["items"][0]["review"]["decision"] == "approved_for_gold"
    assert payload["items"][0]["review_status"] == "reviewed"
    assert payload["claim_boundary"]["approved_review_is_not_gold"] is True
    assert payload["claim_boundary"]["gold_sql_present"] is False


@pytest.mark.asyncio
async def test_benchmark_review_persists_decision_and_rejects_gold_payload(monkeypatch):
    user = SimpleNamespace(identifier="reviewer", metadata={"role": "standard_reviewer"})
    monkeypatch.setattr(routes, "_get_user_from_request", lambda request: user)
    monkeypatch.setattr(routes, "_set_user_context", lambda value: ("reviewer", "standard_reviewer"))
    monkeypatch.setattr(
        routes,
        "_benchmark_review_queue",
        lambda scope: {"source": {}, "tasks": [{"task_id": "BENCH_1", "kind": "business_benchmark_question_slot"}]},
    )
    engine = MagicMock()
    conn = engine.begin.return_value.__enter__.return_value
    conn.execute.return_value.mappings.return_value.one.return_value = {
        "task_id": "BENCH_1",
        "decision": "approved_for_gold",
        "review_notes": "confirmed",
        "question_templates": {"zh": "统计容量"},
        "evidence": {"is_gold": False},
        "reviewed_by": "reviewer",
        "reviewed_at": None,
        "updated_at": None,
    }
    monkeypatch.setattr(routes, "_engine", lambda: engine)
    response = await routes.semantic_benchmark_review(
        _request(
            query="scope=makani",
            path_params={"task_id": "BENCH_1"},
            method="POST",
            body=json.dumps({
                "decision": "approved_for_gold",
                "review_notes": "confirmed",
                "question_templates": {"zh": "统计容量"},
            }).encode(),
        )
    )
    payload = json.loads(response.body)
    assert response.status_code == 200
    assert payload["review"]["is_gold"] is False
    assert payload["review"]["runtime_effect"].startswith("none_until")
    assert conn.execute.called

    forbidden = await routes.semantic_benchmark_review(
        _request(
            query="scope=makani",
            path_params={"task_id": "BENCH_1"},
            method="POST",
            body=json.dumps({"decision": "approved_for_gold", "gold_sql": "SELECT 1"}).encode(),
        )
    )
    assert forbidden.status_code == 400


@pytest.mark.asyncio
async def test_semantic_review_persists_decision_without_runtime_authority(monkeypatch):
    user = SimpleNamespace(identifier="reviewer", metadata={"role": "standard_reviewer"})
    monkeypatch.setattr(routes, "_get_user_from_request", lambda request: user)
    monkeypatch.setattr(routes, "_set_user_context", lambda value: ("reviewer", "standard_reviewer"))
    monkeypatch.setattr(
        routes,
        "_review_queue",
        lambda scope: {
            "source": {"dictionary_evidence": "/Users/example/dictionary.json"},
            "field_tasks": [{
                "task_id": "FIELD_1",
                "kind": "field_semantic_review",
                "physical_table": "public.facilities",
                "physical_field": "capacity",
                "review_status": "review_required",
                "dictionary_evidence": {"path": "/Users/example/capacity.md"},
            }],
        },
    )
    engine = MagicMock()
    conn = engine.begin.return_value.__enter__.return_value
    conn.execute.return_value.mappings.return_value.one.return_value = {
        "task_id": "FIELD_1",
        "queue_kind": "field",
        "decision": "approved_for_draft",
        "review_notes": "字段含义已确认",
        "evidence": {"is_runtime_authority": False},
        "reviewed_by": "reviewer",
        "reviewed_at": None,
        "updated_at": None,
    }
    monkeypatch.setattr(routes, "_engine", lambda: engine)
    response = await routes.semantic_review(
        _request(
            query="scope=makani",
            path_params={"kind": "field", "task_id": "FIELD_1"},
            method="POST",
            body=json.dumps({"decision": "approved_for_draft", "review_notes": "字段含义已确认"}).encode(),
        )
    )
    payload = json.loads(response.body)
    assert response.status_code == 200
    assert payload["review"]["decision"] == "approved_for_draft"
    assert payload["review"]["runtime_effect"].startswith("none_until")
    assert "/Users/" not in json.dumps(payload)
    assert conn.execute.called

    forbidden = await routes.semantic_review(
        _request(
            query="scope=makani",
            path_params={"kind": "field", "task_id": "FIELD_1"},
            method="POST",
            body=json.dumps({"decision": "approved_for_draft", "execution_authorized": True}).encode(),
        )
    )
    assert forbidden.status_code == 400


def test_admin_routes_include_crud_version_and_virtual_lake_endpoints():
    paths = {(route.path, tuple(sorted(route.methods))) for route in routes.get_abu_dhabi_semantic_admin_routes()}
    assert (
        "/api/abu-dhabi/nl2semantic2sql/semantic-admin/assets",
        ("GET", "HEAD"),
    ) in paths
    assert (
        "/api/abu-dhabi/nl2semantic2sql/semantic-admin/versions/{version_id}/{action}",
        ("POST",),
    ) in paths
    assert (
        "/api/abu-dhabi/nl2semantic2sql/virtual-lake-metadata",
        ("GET", "HEAD"),
    ) in paths
    assert (
        "/api/semantic/governance/assets",
        ("GET", "HEAD"),
    ) in paths
    assert (
        "/api/semantic/governance/metric-contracts/overview",
        ("GET", "HEAD"),
    ) in paths
    assert (
        "/api/semantic/governance/metric-contracts",
        ("GET", "HEAD"),
    ) in paths
    assert (
        "/api/semantic/governance/review-queue",
        ("GET", "HEAD"),
    ) in paths
    assert (
        "/api/semantic/governance/benchmark-review-queue",
        ("GET", "HEAD"),
    ) in paths
    assert (
        "/api/semantic/governance/benchmark-review-queue/{task_id}/review",
        ("POST",),
    ) in paths
    assert (
        "/api/semantic/governance/review-queue/{kind}/{task_id}/review",
        ("POST",),
    ) in paths


def test_publish_payload_validation_is_fail_closed():
    with pytest.raises(ValueError, match="physical_tables"):
        routes._validate_payload("assets", {"asset_id": "missing_table"})
    with pytest.raises(ValueError, match="tables"):
        routes._validate_payload("metric_contracts", {"contract_id": "contract"})
