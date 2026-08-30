import asyncio
import gzip
import hashlib
import json
import re
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from pydantic import ValidationError
from rdflib import BNode, Graph, Literal, URIRef

from data_agent.api import platform_gateway_routes as routes
from data_agent.capability_registry import RDF_PROJECTION_REPAIR_EXECUTE
from data_agent.cross_store_projection_authority import (
    ProjectionCheckpointAuthorityConfigurationError,
)
from data_agent.cross_store_projection_consistency import (
    InMemoryProjectionCheckpointLedger,
    ProjectionDesiredState,
    ProjectionEngine,
    ProjectionTargetObservation,
    build_projection_repair_plan,
)
from data_agent.mcp_tool_registry import _mcp_execute_rdf_projection_repair
from data_agent.ontology.contracts import ArtifactRecord, PackageManifest
from data_agent.rdf_projection_executor import (
    RDFProjectionRepairExecutor,
    RDFProjectionTarget,
    RDFProjectionTargetRegistry,
    RDFProjectionValidationError,
    rdf_graph_fingerprint,
)
from data_agent.rdf_projection_service import (
    RDFProjectionRepairRequest,
    RDFProjectionServiceConfigurationError,
    RDFProjectionServiceConflictError,
    execute_rdf_projection_repair,
    load_rdf_projection_registry,
)
from data_agent.user_context import current_tenant_id, current_user_id, current_user_role

_TENANT = "cq-rdf-test"
_TARGET_REF = "rdf://fuseki.test/ontology/default"
_PACKAGE_SHA = "a" * 64


def _write_package(root: Path) -> tuple[RDFProjectionTarget, Graph]:
    turtle = b"""@prefix ex: <https://example.test/> .
ex:parcel-1 ex:landUse \"farmland\" .
ex:parcel-2 ex:landUse \"forest\" .
"""
    compressed = gzip.compress(turtle, mtime=0)
    (root / "ontology.ttl.gz").write_bytes(compressed)
    graph = Graph()
    graph.parse(data=turtle, format="turtle")
    artifact_sha = hashlib.sha256(compressed).hexdigest()
    manifest = PackageManifest(
        package_id="natural-resource-one-map:2.3.0:test",
        ontology_key="natural-resource-one-map",
        ontology_version_id="00000000-0000-0000-0000-000000000001",
        semantic_version="2.3.0",
        title="test natural resource ontology",
        description="test",
        generated_at=datetime(2026, 8, 15, tzinfo=UTC),
        source_fingerprint="b" * 64,
        content_sha256=_PACKAGE_SHA,
        stats={"rdf_triple_count": len(graph)},
        domain_stats=[],
        artifacts={
            "rdf": ArtifactRecord(
                path="ontology.ttl.gz",
                media_type="application/gzip",
                sha256=artifact_sha,
                bytes=len(compressed),
            )
        },
        vocabularies=[],
        validation_summary={},
    )
    (root / "manifest.json").write_text(manifest.model_dump_json(), encoding="utf-8")
    return (
        RDFProjectionTarget(
            tenant_id=_TENANT,
            projection_id="cq.natural_resource_ontology",
            target_ref=_TARGET_REF,
            graph_store_endpoint="http://fuseki.test/ontology/data?default",
            sparql_update_endpoint="http://fuseki.test/ontology/update",
            package_dir=str(root),
            ontology_key="natural-resource-one-map",
            semantic_version="2.3.0",
            package_id=manifest.package_id,
            package_content_sha256=manifest.content_sha256,
            rdf_artifact_sha256=artifact_sha,
            expected_triple_count=len(graph),
        ),
        graph,
    )


def _desired(
    target: RDFProjectionTarget,
    graph: Graph,
    source_sha256: str = _PACKAGE_SHA,
) -> ProjectionDesiredState:
    return ProjectionDesiredState(
        tenant_id=target.tenant_id,
        projection_id=target.projection_id,
        source_resource_version_ref=("gda://cq-rdf-test/ontology/natural-resource-one-map/2.3.0"),
        source_content_sha256=source_sha256,
        target_engine=ProjectionEngine.RDF,
        target_ref=target.target_ref,
        target_exists=True,
        expected_target_content_sha256=rdf_graph_fingerprint(graph),
        expected_row_count=len(graph),
    )


def _missing(target: RDFProjectionTarget) -> ProjectionTargetObservation:
    return ProjectionTargetObservation(
        tenant_id=target.tenant_id,
        projection_id=target.projection_id,
        target_engine=ProjectionEngine.RDF,
        target_ref=target.target_ref,
        target_exists=False,
        observed_content_sha256=None,
        observed_row_count=0,
        observed_by="workload:rdf-test",
        observed_at=datetime(2026, 8, 15, tzinfo=UTC),
    )


def _provider_state() -> dict[str, object]:
    return {"graph": None, "named": {}, "update_calls": 0}


def _transport(state: dict[str, object]) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        query = parse_qs(urlsplit(str(request.url)).query)
        graph_uri = query.get("graph", [None])[0]
        named = state["named"]
        assert isinstance(named, dict)
        if request.method == "GET":
            content = state["graph"] if graph_uri is None else named.get(graph_uri)
            if content is None:
                return httpx.Response(404, request=request)
            return httpx.Response(
                200,
                content=content,
                headers={"Content-Type": "text/turtle"},
                request=request,
            )
        if request.method == "PUT":
            if graph_uri is None:
                state["graph"] = request.content
            else:
                named[graph_uri] = request.content
            return httpx.Response(204, request=request)
        if request.method == "DELETE":
            if graph_uri is None:
                state["graph"] = None
            else:
                named.pop(graph_uri, None)
            return httpx.Response(204, request=request)
        if request.method == "POST" and request.url.path.endswith("/update"):
            update = request.content.decode("utf-8")
            stage_match = re.search(
                r"COPY SILENT GRAPH <([^>]+)> TO DEFAULT",
                update,
            )
            receipt_match = re.search(
                r"INSERT DATA \{ GRAPH <([^>]+)> \{\n(.*?)\n\} \}",
                update,
                re.DOTALL,
            )
            if receipt_match is None:
                return httpx.Response(400, request=request)
            next_graph = state["graph"]
            if stage_match is not None:
                stage_uri = stage_match.group(1)
                if stage_uri not in named:
                    return httpx.Response(409, request=request)
                next_graph = named[stage_uri]
            elif "DROP SILENT DEFAULT" in update:
                next_graph = None
            state["graph"] = next_graph
            receipt_uri, receipt_triples = receipt_match.groups()
            named[receipt_uri] = receipt_triples.encode("utf-8")
            if stage_match is not None:
                named.pop(stage_match.group(1), None)
            state["update_calls"] = int(state["update_calls"]) + 1
            return httpx.Response(204, request=request)
        return httpx.Response(405, request=request)

    return httpx.MockTransport(handler)


class _FailOnceRecordAuthority:
    def __init__(self) -> None:
        self.ledger = InMemoryProjectionCheckpointLedger()
        self.failed = False

    def current(self, **identity):
        return self.ledger.current(**identity)

    def history(self, **identity):
        return self.ledger.history(**identity)

    def record(self, checkpoint, *, previous_checkpoint_sha256=None):
        if not self.failed:
            self.failed = True
            raise ProjectionCheckpointAuthorityConfigurationError(
                "simulated checkpoint authority outage"
            )
        return self.ledger.record(
            checkpoint,
            previous_checkpoint_sha256=previous_checkpoint_sha256,
        )


def _http_request(*, body: dict, headers: dict | None = None):
    request = MagicMock()

    async def read_json():
        return body

    request.json.side_effect = read_json
    request.headers = headers or {"x-request-id": "rdf-projection-request-1"}
    request.path_params = {}
    request.query_params = {}
    return request


def _user(*, tenant_id: str = _TENANT):
    return SimpleNamespace(
        identifier="operator-1",
        metadata={"role": "platform_operator", "tenant_id": tenant_id},
    )


def test_rdf_fingerprint_is_order_independent_and_rejects_blank_nodes():
    first = Graph()
    first.add((URIRef("https://e/s"), URIRef("https://e/p"), Literal("v")))
    first.add((URIRef("https://e/s2"), URIRef("https://e/p"), Literal("v2")))
    second = Graph()
    for triple in reversed(tuple(first)):
        second.add(triple)
    assert rdf_graph_fingerprint(first) == rdf_graph_fingerprint(second)
    first.add((BNode("x"), URIRef("https://e/p"), Literal("v")))
    with pytest.raises(RDFProjectionValidationError, match="Blank nodes|blank nodes"):
        rdf_graph_fingerprint(first)


def test_rdf_target_and_registry_reject_unregistered_or_credentialed_targets(tmp_path):
    target, _ = _write_package(tmp_path)
    registry = RDFProjectionTargetRegistry((target,))
    assert (
        registry.resolve(
            tenant_id=target.tenant_id,
            projection_id=target.projection_id,
            target_ref=target.target_ref,
        )
        == target
    )
    with pytest.raises(RDFProjectionValidationError, match="not explicitly registered"):
        registry.resolve(
            tenant_id=target.tenant_id,
            projection_id=target.projection_id,
            target_ref="rdf://fuseki.test/ontology/other",
        )
    with pytest.raises(ValueError, match="credentials"):
        target.model_copy(
            update={"graph_store_endpoint": "http://user:secret@fuseki.test/data"}
        ).model_validate(
            {
                **target.model_dump(mode="json"),
                "graph_store_endpoint": "http://user:secret@fuseki.test/data",
            }
        )
    with pytest.raises(ValueError, match="share one registered origin"):
        RDFProjectionTarget.model_validate(
            {
                **target.model_dump(mode="json"),
                "sparql_update_endpoint": "http://attacker.test/ontology/update",
            }
        )
    with pytest.raises(ValueError, match="natural-resource-one-map 2.3.0"):
        RDFProjectionTarget.model_validate(
            {
                **target.model_dump(mode="json"),
                "semantic_version": "2.4.0",
            }
        )


def test_rdf_executor_rebuild_replay_drift_and_delete(tmp_path):
    target, graph = _write_package(tmp_path)
    state = _provider_state()
    executor = RDFProjectionRepairExecutor(
        RDFProjectionTargetRegistry((target,)),
        transport=_transport(state),
    )
    desired = _desired(target, graph)
    rebuild = build_projection_repair_plan(desired, _missing(target), None)
    first = executor.execute(rebuild)
    replay = executor.execute(rebuild)
    assert first.status == "completed"
    assert replay.status == "replayed"
    assert replay.target_content_sha256 == desired.expected_target_content_sha256
    assert state["update_calls"] == 1

    state["graph"] = b"@prefix ex: <https://example.test/> . ex:x ex:p ex:y ."
    with pytest.raises(
        RDFProjectionValidationError,
        match="does not match the current RDF target",
    ):
        executor.execute(rebuild)
    state["graph"] = gzip.decompress((tmp_path / "ontology.ttl.gz").read_bytes())

    current = executor.observe(target)
    deleted = ProjectionDesiredState(
        tenant_id=target.tenant_id,
        projection_id=target.projection_id,
        source_resource_version_ref="gda://cq-rdf-test/ontology/deleted",
        source_content_sha256="c" * 64,
        target_engine=ProjectionEngine.RDF,
        target_ref=target.target_ref,
        target_exists=False,
        expected_target_content_sha256=None,
        expected_row_count=0,
    )
    delete_plan = build_projection_repair_plan(deleted, current, None)
    assert delete_plan.action == "delete"
    receipt = executor.execute(delete_plan)
    assert receipt.status == "deleted"
    assert state["graph"] is None


def test_rdf_service_checkpoints_and_reobserves_replay(tmp_path):
    target, graph = _write_package(tmp_path)
    state = _provider_state()
    executor = RDFProjectionRepairExecutor(
        RDFProjectionTargetRegistry((target,)),
        transport=_transport(state),
    )
    authority = InMemoryProjectionCheckpointLedger()
    plan = build_projection_repair_plan(_desired(target, graph), _missing(target), None)
    request = RDFProjectionRepairRequest(
        plan=plan,
        checkpointed_by="workload:rdf-projection-test",
    )
    first = execute_rdf_projection_repair(
        request,
        executor=executor,
        authority=authority,
    )
    replay = execute_rdf_projection_repair(
        request,
        executor=executor,
        authority=authority,
    )
    assert first.status == "completed"
    assert first.checkpoint_created
    assert first.checkpoint.target_commit_ref["provider"] == "rdf_fuseki"
    assert replay.status == "replayed"
    assert not replay.checkpoint_created

    state["graph"] = b"@prefix ex: <https://example.test/> . ex:x ex:p ex:y ."
    with pytest.raises(RDFProjectionServiceConflictError, match="drifted"):
        execute_rdf_projection_repair(
            request,
            executor=executor,
            authority=authority,
        )


def test_rdf_service_retry_after_authority_outage_recovers_fuseki_receipt_without_replay(
    tmp_path,
):
    target, graph = _write_package(tmp_path)
    state = _provider_state()
    executor = RDFProjectionRepairExecutor(
        RDFProjectionTargetRegistry((target,)),
        transport=_transport(state),
    )
    authority = _FailOnceRecordAuthority()
    plan = build_projection_repair_plan(_desired(target, graph), _missing(target), None)
    request = RDFProjectionRepairRequest(
        plan=plan,
        checkpointed_by="workload:rdf-projection-test",
    )

    with pytest.raises(RDFProjectionServiceConfigurationError, match="outage"):
        execute_rdf_projection_repair(
            request,
            executor=executor,
            authority=authority,
        )

    result = execute_rdf_projection_repair(
        request,
        executor=executor,
        authority=authority,
    )

    assert result.status == "completed"
    assert result.checkpoint_created is True
    assert result.receipt.provider_commit_ref["provider_atomicity"] == (
        "single_fuseki_update_request"
    )
    assert state["update_calls"] == 1


def test_rdf_service_contract_has_no_endpoint_credentials_or_payload(tmp_path):
    target, graph = _write_package(tmp_path)
    plan = build_projection_repair_plan(_desired(target, graph), _missing(target), None)
    request = RDFProjectionRepairRequest(
        plan=plan,
        checkpointed_by="agent:rdf-test",
    )
    with pytest.raises(ValidationError):
        RDFProjectionRepairRequest.model_validate(
            {
                **request.model_dump(mode="json"),
                "graph_store_endpoint": "http://attacker.test/data",
            }
        )
    registry = load_rdf_projection_registry(json.dumps([target.model_dump(mode="json")]))
    assert (
        registry.resolve(
            tenant_id=target.tenant_id,
            projection_id=target.projection_id,
            target_ref=target.target_ref,
        )
        == target
    )

    spec = RDF_PROJECTION_REPAIR_EXECUTE
    assert spec.input.semantic_type == "gda.rdf-projection-repair-request.v1"
    assert set(spec.input.json_schema["required"]) == {"checkpointed_by", "plan"}
    assert spec.output.semantic_type == "gda.rdf-projection-repair-result.v1"
    openapi = spec.openapi_projection()["paths"]["/api/platform/v1/projections/rdf/repairs"]["post"]
    mcp = spec.mcp_projection()
    assert openapi["requestBody"]["content"]["application/json"]["schema"] == (mcp["inputSchema"])
    schema_text = json.dumps(spec.input.json_schema, sort_keys=True)
    for forbidden in (
        "graph_store_endpoint",
        "sparql_update_endpoint",
        "username",
        "password",
        "rdf_payload",
        "package_dir",
    ):
        assert forbidden not in schema_text


def test_rdf_rest_and_mcp_bind_checkpoint_actor(tmp_path):
    target, graph = _write_package(tmp_path)
    plan = build_projection_repair_plan(_desired(target, graph), _missing(target), None)
    spoofed = RDFProjectionRepairRequest(
        plan=plan,
        checkpointed_by="human:spoofed",
    )
    with patch.object(routes, "_get_user_from_request", return_value=_user()):
        response = asyncio.run(
            routes.execute_rdf_projection_repair_plan(
                _http_request(body=spoofed.model_dump(mode="json"))
            )
        )
    assert response.status_code == 403
    assert json.loads(response.body)["error"]["code"] == "checkpoint_actor_mismatch"

    submission = RDFProjectionRepairRequest(
        plan=plan,
        checkpointed_by="human:operator-1",
    )
    state = _provider_state()
    result = execute_rdf_projection_repair(
        submission,
        executor=RDFProjectionRepairExecutor(
            RDFProjectionTargetRegistry((target,)),
            transport=_transport(state),
        ),
        authority=InMemoryProjectionCheckpointLedger(),
    )
    request = _http_request(
        body=submission.model_dump(mode="json"),
        headers={
            "x-request-id": "rdf-projection-request-1",
            "X-GDA-Capability-Fingerprint": RDF_PROJECTION_REPAIR_EXECUTE.fingerprint,
            "idempotency-key": plan.plan_idempotency_key,
        },
    )
    with (
        patch.object(routes, "_get_user_from_request", return_value=_user()),
        patch.object(routes, "execute_rdf_projection_repair", return_value=result),
    ):
        response = asyncio.run(routes.execute_rdf_projection_repair_plan(request))
    assert response.status_code == 200
    payload = json.loads(response.body)["data"]
    assert payload["checkpoint"]["updated_by"] == "human:operator-1"
    assert payload["technical_baseline_status"] == "technical_baseline_unreviewed"
    assert payload["decision_status"] == "assisted_precheck_not_for_production_decision"

    tenant_token = current_tenant_id.set(plan.tenant_id)
    user_token = current_user_id.set("projection-agent")
    role_token = current_user_role.set("platform_operator")
    try:
        mismatch = json.loads(
            _mcp_execute_rdf_projection_repair(
                plan.model_dump(mode="json"),
                "agent:spoofed",
            )
        )
        assert mismatch["code"] == "checkpoint_actor_mismatch"
        with patch(
            "data_agent.rdf_projection_service.execute_rdf_projection_repair",
            return_value=result,
        ):
            payload = json.loads(
                _mcp_execute_rdf_projection_repair(
                    plan.model_dump(mode="json"),
                    "agent:projection-agent",
                )
            )
        assert payload["checkpoint"]["updated_by"] == "human:operator-1"
        assert payload["technical_baseline_status"] == "technical_baseline_unreviewed"
    finally:
        current_user_role.reset(role_token)
        current_user_id.reset(user_token)
        current_tenant_id.reset(tenant_token)
