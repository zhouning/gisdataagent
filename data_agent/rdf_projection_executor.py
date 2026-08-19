"""Plan-bound RDF graph projection execution for registered Fuseki targets."""

from __future__ import annotations

import gzip
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, ClassVar
from urllib.parse import urlencode, urlsplit, urlunsplit

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from rdflib import BNode, Graph, Literal, URIRef
from rdflib.namespace import RDF

from .cross_store_projection_consistency import (
    ProjectionConsistencyError,
    ProjectionEngine,
    ProjectionRepairPlan,
    ProjectionTargetObservation,
)
from .ontology.package_reader import OntologyPackageReader
from .platform_contracts import NonEmptyText, Sha256, TenantId, canonical_json_fingerprint


class RDFProjectionExecutionError(ProjectionConsistencyError):
    """A plan-bound RDF action could not be safely completed."""


class RDFProjectionConfigurationError(RDFProjectionExecutionError):
    """The registered RDF target, package, or HTTP channel is unusable."""


class RDFProjectionValidationError(RDFProjectionExecutionError):
    """The plan, immutable package, or observed RDF graph is invalid."""


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class RDFProjectionTarget(_FrozenModel):
    """Explicit Graph Store target bound to one immutable ontology package."""

    schema_id: ClassVar[str] = "gda.rdf-projection-target.v2"
    tenant_id: TenantId
    projection_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{2,127}$")
    target_ref: NonEmptyText
    graph_store_endpoint: NonEmptyText
    sparql_update_endpoint: NonEmptyText
    package_dir: NonEmptyText
    ontology_key: str = Field(pattern=r"^[a-z][a-z0-9-]{2,127}$")
    semantic_version: str = Field(pattern=r"^[0-9]+\.[0-9]+\.[0-9]+$")
    package_id: NonEmptyText
    package_content_sha256: Sha256
    rdf_artifact_sha256: Sha256
    expected_triple_count: int = Field(ge=1)

    @model_validator(mode="after")
    def _canonical_target(self) -> RDFProjectionTarget:
        if self.ontology_key != "natural-resource-one-map" or self.semantic_version != "2.3.0":
            raise ValueError(
                "RDF projection targets are restricted to natural-resource-one-map 2.3.0"
            )
        target = urlsplit(self.target_ref)
        if target.scheme != "rdf" or not target.netloc or not target.path.strip("/"):
            raise ValueError("target_ref must be rdf://host/dataset/graph")
        if target.username or target.password or target.query or target.fragment:
            raise ValueError("target_ref must not contain credentials, query, or fragment")
        endpoint = urlsplit(self.graph_store_endpoint)
        if endpoint.scheme not in {"http", "https"} or not endpoint.netloc:
            raise ValueError("graph_store_endpoint must be an absolute HTTP URL")
        if endpoint.username or endpoint.password or endpoint.fragment:
            raise ValueError("graph_store_endpoint must not contain credentials or fragments")
        update_endpoint = urlsplit(self.sparql_update_endpoint)
        if update_endpoint.scheme not in {"http", "https"} or not update_endpoint.netloc:
            raise ValueError("sparql_update_endpoint must be an absolute HTTP URL")
        if (
            update_endpoint.username
            or update_endpoint.password
            or update_endpoint.query
            or update_endpoint.fragment
        ):
            raise ValueError(
                "sparql_update_endpoint must not contain credentials, query, or fragment"
            )
        if (update_endpoint.scheme, update_endpoint.netloc) != (
            endpoint.scheme,
            endpoint.netloc,
        ):
            raise ValueError(
                "Graph Store and SPARQL Update endpoints must share one registered origin"
            )
        return self

    @property
    def identity(self) -> tuple[str, str, str]:
        return self.tenant_id, self.projection_id, self.target_ref


class RDFProjectionTargetRegistry:
    """Explicit immutable-by-convention RDF target and package allowlist."""

    def __init__(self, targets: tuple[RDFProjectionTarget, ...] = ()) -> None:
        self._targets: dict[tuple[str, str, str], RDFProjectionTarget] = {}
        for target in targets:
            self.register(target)

    def register(self, target: RDFProjectionTarget) -> None:
        if target.identity in self._targets:
            raise RDFProjectionConfigurationError("duplicate RDF target registration")
        self._targets[target.identity] = target

    def resolve(
        self, *, tenant_id: str, projection_id: str, target_ref: str
    ) -> RDFProjectionTarget:
        target = self._targets.get((tenant_id, projection_id, target_ref))
        if target is None:
            raise RDFProjectionValidationError("RDF target is not explicitly registered")
        return target


def rdf_graph_fingerprint(graph: Graph) -> str:
    """Return an order-independent fingerprint for a blank-node-free RDF graph."""

    triple_hashes: list[bytes] = []
    for subject, predicate, object_ in graph:
        if any(isinstance(term, BNode) for term in (subject, predicate, object_)):
            raise RDFProjectionValidationError(
                "blank nodes are not allowed in governed RDF projections"
            )
        statement = f"{subject.n3()} {predicate.n3()} {object_.n3()} .\n".encode()
        triple_hashes.append(hashlib.sha256(statement).digest())
    triple_hashes.sort()
    aggregate = hashlib.sha256(b"".join(triple_hashes)).hexdigest()
    return canonical_json_fingerprint(
        {
            "schema": "gda.rdf-target-content.v1",
            "triple_count": len(graph),
            "triple_hashes_sha256": aggregate,
        }
    )


class RDFProjectionRepairReceipt(_FrozenModel):
    """Fuseki commit evidence suitable for checkpoint construction."""

    schema_id: ClassVar[str] = "gda.rdf-projection-repair-receipt.v1"
    status: str = Field(pattern=r"^(completed|replayed|checkpointed|deleted)$")
    tenant_id: TenantId
    projection_id: str
    target_ref: NonEmptyText
    action: str = Field(pattern=r"^(checkpoint|rebuild|delete)$")
    plan_sha256: Sha256
    idempotency_key: Sha256
    provider_commit_ref: dict[str, Any]
    target_exists: bool
    target_content_sha256: Sha256 | None = None
    target_row_count: int = Field(ge=0)
    observed_at: datetime

    @field_validator("observed_at")
    @classmethod
    def _utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("receipt timestamp must be timezone-aware")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def _state(self) -> RDFProjectionRepairReceipt:
        if self.target_exists != (self.target_content_sha256 is not None):
            raise ValueError("receipt target content must match target existence")
        if not self.target_exists and self.target_row_count != 0:
            raise ValueError("deleted receipt must have zero triples")
        if self.provider_commit_ref.get("plan_sha256") != self.plan_sha256:
            raise ValueError("provider commit ref must bind plan_sha256")
        if self.provider_commit_ref.get("idempotency_key") != self.idempotency_key:
            raise ValueError("provider commit ref must bind idempotency key")
        return self


def rdf_projection_receipt_fingerprint(
    *,
    tenant_id: str,
    projection_id: str,
    target_ref: str,
    action: str,
    plan_sha256: str,
    idempotency_key: str,
    provider_commit_ref: dict[str, Any],
    target_exists: bool,
    target_content_sha256: str | None,
    target_row_count: int,
) -> str:
    """Fingerprint one provider-native Fuseki receipt graph."""

    commit_ref = dict(provider_commit_ref)
    commit_ref.pop("receipt_sha256", None)
    return canonical_json_fingerprint(
        {
            "schema": "gda.rdf-fuseki-provider-receipt.v1",
            "tenant_id": tenant_id,
            "projection_id": projection_id,
            "target_ref": target_ref,
            "action": action,
            "plan_sha256": plan_sha256,
            "idempotency_key": idempotency_key,
            "provider_commit_ref": commit_ref,
            "target_exists": target_exists,
            "target_content_sha256": target_content_sha256,
            "target_row_count": target_row_count,
        }
    )


_RECEIPT_CLASS = URIRef("urn:gda:rdf-projection-receipt:Receipt")
_RECEIPT_PREDICATE_BASE = "urn:gda:rdf-projection-receipt:field:"


def _receipt_predicate(name: str) -> URIRef:
    return URIRef(f"{_RECEIPT_PREDICATE_BASE}{name}")


class RDFProjectionRepairExecutor:
    """Execute sealed plans against registered Fuseki Graph Store endpoints."""

    MAX_GRAPH_BYTES = 200_000_000

    def __init__(
        self,
        registry: RDFProjectionTargetRegistry,
        *,
        username: str | None = None,
        password: str | None = None,
        timeout_seconds: float = 120.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        if timeout_seconds <= 0 or timeout_seconds > 600:
            raise RDFProjectionConfigurationError(
                "RDF projection timeout must be between 0 and 600 seconds"
            )
        self.registry = registry
        self.username = username
        self.password = password
        self.timeout_seconds = timeout_seconds
        self.transport = transport
        self._package_cache: dict[tuple[str, str, str], tuple[bytes, str, int]] = {}

    def _client(self) -> httpx.Client:
        auth = (self.username, self.password or "") if self.username else None
        return httpx.Client(
            timeout=self.timeout_seconds,
            auth=auth,
            transport=self.transport,
        )

    @staticmethod
    def _parse_graph(content: bytes, content_type: str) -> Graph:
        if len(content) > RDFProjectionRepairExecutor.MAX_GRAPH_BYTES:
            raise RDFProjectionValidationError("RDF graph exceeds the response byte budget")
        media_type = content_type.partition(";")[0].strip().lower()
        rdf_format = {
            "application/n-triples": "nt",
            "application/n-triples;charset=utf-8": "nt",
            "text/turtle": "turtle",
            "application/turtle": "turtle",
            "application/rdf+xml": "xml",
        }.get(media_type, "turtle")
        try:
            graph = Graph()
            graph.parse(data=content, format=rdf_format)
            return graph
        except Exception as exc:
            raise RDFProjectionValidationError(
                "registered RDF target returned an invalid graph"
            ) from exc

    def _load_package(self, target: RDFProjectionTarget) -> tuple[bytes, str, int]:
        cached = self._package_cache.get(target.identity)
        if cached is not None:
            return cached
        try:
            reader = OntologyPackageReader(
                Path(target.package_dir),
                verify=True,
                ontology_key=target.ontology_key,
            )
            manifest = reader.manifest
            rdf_artifact = manifest.artifacts["rdf"]
            triple_count = int(manifest.stats["rdf_triple_count"])
            if (
                manifest.semantic_version != target.semantic_version
                or manifest.package_id != target.package_id
                or manifest.content_sha256 != target.package_content_sha256
                or rdf_artifact.sha256 != target.rdf_artifact_sha256
                or triple_count != target.expected_triple_count
            ):
                raise RDFProjectionConfigurationError(
                    "registered RDF package identity does not match its verified manifest"
                )
            with gzip.open(reader.artifact_path("rdf"), "rb") as stream:
                turtle = stream.read(self.MAX_GRAPH_BYTES + 1)
            if len(turtle) > self.MAX_GRAPH_BYTES:
                raise RDFProjectionConfigurationError(
                    "registered RDF package exceeds the byte budget"
                )
            graph = self._parse_graph(turtle, "text/turtle")
            if len(graph) != triple_count:
                raise RDFProjectionConfigurationError(
                    "registered RDF package triple count differs from its manifest"
                )
            result = (turtle, rdf_graph_fingerprint(graph), triple_count)
        except RDFProjectionExecutionError:
            raise
        except (KeyError, OSError, TypeError, ValueError) as exc:
            raise RDFProjectionConfigurationError(
                "registered RDF package cannot be verified"
            ) from exc
        self._package_cache[target.identity] = result
        return result

    @staticmethod
    def _receipt_graph_uri(plan: ProjectionRepairPlan) -> str:
        return f"urn:gda:rdf-projection-receipt:{plan.plan_idempotency_key}"

    @staticmethod
    def _stage_graph_uri(plan: ProjectionRepairPlan) -> str:
        return f"urn:gda:rdf-projection-stage:{plan.plan_idempotency_key}"

    @staticmethod
    def _graph_endpoint(target: RDFProjectionTarget, graph_uri: str) -> str:
        parsed = urlsplit(target.graph_store_endpoint)
        return urlunsplit(
            (
                parsed.scheme,
                parsed.netloc,
                parsed.path,
                urlencode({"graph": graph_uri}),
                "",
            )
        )

    @staticmethod
    def _receipt_graph(receipt: RDFProjectionRepairReceipt) -> Graph:
        graph = Graph()
        subject = URIRef(str(receipt.provider_commit_ref["receipt_graph"]))
        fields: dict[str, Any] = {
            "tenant_id": receipt.tenant_id,
            "projection_id": receipt.projection_id,
            "target_ref": receipt.target_ref,
            "action": receipt.action,
            "status": receipt.status,
            "plan_sha256": receipt.plan_sha256,
            "idempotency_key": receipt.idempotency_key,
            "provider_commit_ref": json.dumps(
                receipt.provider_commit_ref,
                ensure_ascii=True,
                sort_keys=True,
                separators=(",", ":"),
            ),
            "target_exists": receipt.target_exists,
            "target_row_count": receipt.target_row_count,
            "observed_at": receipt.observed_at.isoformat().replace("+00:00", "Z"),
            "receipt_sha256": receipt.provider_commit_ref["receipt_sha256"],
        }
        if receipt.target_content_sha256 is not None:
            fields["target_content_sha256"] = receipt.target_content_sha256
        graph.add((subject, RDF.type, _RECEIPT_CLASS))
        for name, value in fields.items():
            graph.add((subject, _receipt_predicate(name), Literal(value)))
        return graph

    @staticmethod
    def _one_value(graph: Graph, subject: URIRef, name: str) -> Any:
        values = tuple(graph.objects(subject, _receipt_predicate(name)))
        if len(values) != 1:
            raise RDFProjectionValidationError(
                "stored Fuseki provider receipt has invalid field cardinality"
            )
        return values[0]

    def _receipt_from_graph(
        self,
        graph: Graph,
        plan: ProjectionRepairPlan,
    ) -> RDFProjectionRepairReceipt:
        subjects = tuple(set(graph.subjects(RDF.type, _RECEIPT_CLASS)))
        if len(subjects) != 1 or not isinstance(subjects[0], URIRef):
            raise RDFProjectionValidationError(
                "stored Fuseki provider receipt graph is invalid"
            )
        subject = subjects[0]
        expected_graph_uri = self._receipt_graph_uri(plan)
        if str(subject) != expected_graph_uri:
            raise RDFProjectionValidationError(
                "stored Fuseki provider receipt graph is not plan-bound"
            )
        try:
            commit_ref = json.loads(
                str(self._one_value(graph, subject, "provider_commit_ref"))
            )
            target_exists_value = str(
                self._one_value(graph, subject, "target_exists")
            ).lower()
            if target_exists_value not in {"true", "false"}:
                raise ValueError("invalid target existence")
            target_exists = target_exists_value == "true"
            content_values = tuple(
                graph.objects(subject, _receipt_predicate("target_content_sha256"))
            )
            if len(content_values) > 1:
                raise ValueError("invalid target content cardinality")
            target_content_sha256 = (
                str(content_values[0]) if content_values else None
            )
            receipt_sha256 = str(
                self._one_value(graph, subject, "receipt_sha256")
            )
            receipt = RDFProjectionRepairReceipt(
                status=str(self._one_value(graph, subject, "status")),
                tenant_id=str(self._one_value(graph, subject, "tenant_id")),
                projection_id=str(
                    self._one_value(graph, subject, "projection_id")
                ),
                target_ref=str(self._one_value(graph, subject, "target_ref")),
                action=str(self._one_value(graph, subject, "action")),
                plan_sha256=str(
                    self._one_value(graph, subject, "plan_sha256")
                ),
                idempotency_key=str(
                    self._one_value(graph, subject, "idempotency_key")
                ),
                provider_commit_ref=commit_ref,
                target_exists=target_exists,
                target_content_sha256=target_content_sha256,
                target_row_count=int(
                    str(self._one_value(graph, subject, "target_row_count"))
                ),
                observed_at=datetime.fromisoformat(
                    str(self._one_value(graph, subject, "observed_at")).replace(
                        "Z", "+00:00"
                    )
                ),
            )
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise RDFProjectionValidationError(
                "stored Fuseki provider receipt payload is invalid"
            ) from exc
        expected_sha256 = rdf_projection_receipt_fingerprint(
            tenant_id=receipt.tenant_id,
            projection_id=receipt.projection_id,
            target_ref=receipt.target_ref,
            action=receipt.action,
            plan_sha256=receipt.plan_sha256,
            idempotency_key=receipt.idempotency_key,
            provider_commit_ref=receipt.provider_commit_ref,
            target_exists=receipt.target_exists,
            target_content_sha256=receipt.target_content_sha256,
            target_row_count=receipt.target_row_count,
        )
        if (
            receipt.tenant_id != plan.tenant_id
            or receipt.projection_id != plan.projection_id
            or receipt.target_ref != plan.target_ref
            or receipt.action != plan.action
            or receipt.plan_sha256 != plan.plan_sha256
            or receipt.idempotency_key != plan.plan_idempotency_key
            or receipt.provider_commit_ref.get("provider") != "rdf_fuseki"
            or receipt.provider_commit_ref.get("receipt_graph")
            != expected_graph_uri
            or receipt.provider_commit_ref.get("receipt_sha256")
            != expected_sha256
            or receipt_sha256 != expected_sha256
        ):
            raise RDFProjectionValidationError(
                "stored Fuseki provider receipt is not bound to the sealed plan"
            )
        return receipt

    @staticmethod
    def _assert_receipt_matches_target(
        receipt: RDFProjectionRepairReceipt,
        observation: ProjectionTargetObservation,
        plan: ProjectionRepairPlan,
    ) -> None:
        desired = plan.desired_state
        if (
            receipt.target_exists != desired.target_exists
            or receipt.target_content_sha256 != desired.expected_target_content_sha256
            or receipt.target_row_count != desired.expected_row_count
            or observation.target_exists != receipt.target_exists
            or observation.observed_content_sha256 != receipt.target_content_sha256
            or observation.observed_row_count != receipt.target_row_count
        ):
            raise RDFProjectionValidationError(
                "stored Fuseki provider receipt does not match the current RDF target"
            )

    def recover_receipt(
        self,
        plan: ProjectionRepairPlan,
    ) -> RDFProjectionRepairReceipt | None:
        """Recover provider-native evidence without replaying a Fuseki mutation."""

        target = self.registry.resolve(
            tenant_id=plan.tenant_id,
            projection_id=plan.projection_id,
            target_ref=plan.target_ref,
        )
        self._assert_plan(plan, target)
        endpoint = self._graph_endpoint(target, self._receipt_graph_uri(plan))
        try:
            with self._client() as client:
                response = client.get(
                    endpoint,
                    headers={"Accept": "application/n-triples"},
                )
        except httpx.HTTPError as exc:
            raise RDFProjectionConfigurationError(
                "Fuseki provider receipt recovery failed"
            ) from exc
        if response.status_code == 404:
            return None
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise RDFProjectionConfigurationError(
                "Fuseki provider receipt recovery was rejected"
            ) from exc
        graph = self._parse_graph(
            response.content,
            response.headers.get("content-type", "application/n-triples"),
        )
        receipt = self._receipt_from_graph(graph, plan)
        observation = self.observe(target)
        self._assert_receipt_matches_target(receipt, observation, plan)
        return receipt

    def observe(self, target: RDFProjectionTarget) -> ProjectionTargetObservation:
        try:
            with self._client() as client:
                response = client.get(
                    target.graph_store_endpoint,
                    headers={"Accept": "application/n-triples"},
                )
        except httpx.HTTPError as exc:
            raise RDFProjectionConfigurationError("RDF Graph Store observation failed") from exc
        if response.status_code == 404:
            return self._missing_observation(target)
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise RDFProjectionConfigurationError(
                "RDF Graph Store observation was rejected"
            ) from exc
        graph = self._parse_graph(
            response.content,
            response.headers.get("content-type", "application/n-triples"),
        )
        if not graph:
            return self._missing_observation(target)
        return ProjectionTargetObservation(
            tenant_id=target.tenant_id,
            projection_id=target.projection_id,
            target_engine=ProjectionEngine.RDF,
            target_ref=target.target_ref,
            target_exists=True,
            observed_content_sha256=rdf_graph_fingerprint(graph),
            observed_row_count=len(graph),
            observed_by="workload:rdf-projection-executor",
            observed_at=datetime.now(UTC),
        )

    @staticmethod
    def _missing_observation(target: RDFProjectionTarget) -> ProjectionTargetObservation:
        return ProjectionTargetObservation(
            tenant_id=target.tenant_id,
            projection_id=target.projection_id,
            target_engine=ProjectionEngine.RDF,
            target_ref=target.target_ref,
            target_exists=False,
            observed_content_sha256=None,
            observed_row_count=0,
            observed_by="workload:rdf-projection-executor",
            observed_at=datetime.now(UTC),
        )

    @staticmethod
    def _assert_plan(plan: ProjectionRepairPlan, target: RDFProjectionTarget) -> None:
        if plan.target_engine is not ProjectionEngine.RDF:
            raise RDFProjectionValidationError("RDF executor only accepts RDF plans")
        if (
            plan.tenant_id != target.tenant_id
            or plan.projection_id != target.projection_id
            or plan.target_ref != target.target_ref
        ):
            raise RDFProjectionValidationError(
                "repair plan target identity does not match registered RDF target"
            )
        if plan.action == "fail_closed":
            raise RDFProjectionValidationError("fail-closed repair plans cannot be executed")

    @staticmethod
    def _assert_observation(
        plan: ProjectionRepairPlan,
        current: ProjectionTargetObservation,
    ) -> None:
        expected = plan.observation
        if (
            current.target_exists != expected.target_exists
            or current.observed_content_sha256 != expected.observed_content_sha256
            or current.observed_row_count != expected.observed_row_count
        ):
            raise RDFProjectionValidationError(
                "RDF target changed after the repair plan was sealed"
            )

    def execute(
        self,
        plan: ProjectionRepairPlan,
        *,
        observed_at: datetime | None = None,
    ) -> RDFProjectionRepairReceipt:
        target = self.registry.resolve(
            tenant_id=plan.tenant_id,
            projection_id=plan.projection_id,
            target_ref=plan.target_ref,
        )
        self._assert_plan(plan, target)
        now = observed_at or datetime.now(UTC)
        if now.tzinfo is None or now.utcoffset() is None:
            raise RDFProjectionValidationError("observed_at must be timezone-aware")
        now = now.astimezone(UTC)
        stored_receipt = self.recover_receipt(plan)
        if stored_receipt is not None:
            return stored_receipt.model_copy(update={"status": "replayed"})
        current = self.observe(target)
        desired = plan.desired_state
        already_desired = (
            current.target_exists == desired.target_exists
            and current.observed_content_sha256 == desired.expected_target_content_sha256
            and current.observed_row_count == desired.expected_row_count
        )
        if already_desired:
            status = "checkpointed" if plan.action == "checkpoint" else "replayed"
        else:
            self._assert_observation(plan, current)
            if plan.action == "checkpoint":
                raise RDFProjectionValidationError(
                    "checkpoint target does not match desired RDF state"
                )
            if plan.action == "delete":
                status = "deleted"
            else:
                turtle, fingerprint, triple_count = self._load_package(target)
                if (
                    plan.desired_state.source_content_sha256 != target.package_content_sha256
                    or plan.desired_state.expected_target_content_sha256 != fingerprint
                    or plan.desired_state.expected_row_count != triple_count
                ):
                    raise RDFProjectionValidationError(
                        "registered RDF package does not match desired target state"
                    )
                status = "completed"
        receipt_graph = self._receipt_graph_uri(plan)
        commit_ref = {
            "provider": "rdf_fuseki",
            "provider_commit": receipt_graph,
            "provider_atomicity": "single_fuseki_update_request",
            "receipt_graph": receipt_graph,
            "package_id": target.package_id,
            "package_content_sha256": target.package_content_sha256,
            "plan_sha256": plan.plan_sha256,
            "idempotency_key": plan.plan_idempotency_key,
        }
        receipt_sha256 = rdf_projection_receipt_fingerprint(
            tenant_id=plan.tenant_id,
            projection_id=plan.projection_id,
            target_ref=plan.target_ref,
            action=plan.action,
            plan_sha256=plan.plan_sha256,
            idempotency_key=plan.plan_idempotency_key,
            provider_commit_ref=commit_ref,
            target_exists=desired.target_exists,
            target_content_sha256=desired.expected_target_content_sha256,
            target_row_count=desired.expected_row_count,
        )
        commit_ref["receipt_sha256"] = receipt_sha256
        receipt = RDFProjectionRepairReceipt(
            status=status,
            tenant_id=plan.tenant_id,
            projection_id=plan.projection_id,
            target_ref=plan.target_ref,
            action=plan.action,
            plan_sha256=plan.plan_sha256,
            idempotency_key=plan.plan_idempotency_key,
            provider_commit_ref=commit_ref,
            target_exists=desired.target_exists,
            target_content_sha256=desired.expected_target_content_sha256,
            target_row_count=desired.expected_row_count,
            observed_at=now,
        )
        stage_uri: str | None = None
        if not already_desired and plan.action == "rebuild":
            stage_uri = self._stage_graph_uri(plan)
            self._put_graph(target, stage_uri, turtle)
        self._commit_receipt(
            target,
            receipt,
            stage_uri=stage_uri,
            delete_target=not already_desired and plan.action == "delete",
        )
        post = self.observe(target)
        self._assert_receipt_matches_target(receipt, post, plan)
        return receipt

    def _put_graph(
        self,
        target: RDFProjectionTarget,
        graph_uri: str,
        turtle: bytes,
    ) -> None:
        try:
            with self._client() as client:
                response = client.put(
                    self._graph_endpoint(target, graph_uri),
                    content=turtle,
                    headers={
                        "Content-Type": "text/turtle; charset=utf-8",
                        "X-GDA-Ontology-Package": target.package_id,
                        "X-GDA-Content-SHA256": target.package_content_sha256,
                    },
                )
                response.raise_for_status()
        except httpx.HTTPError as exc:
            raise RDFProjectionExecutionError("RDF staging graph upload failed") from exc

    def _commit_receipt(
        self,
        target: RDFProjectionTarget,
        receipt: RDFProjectionRepairReceipt,
        *,
        stage_uri: str | None,
        delete_target: bool,
    ) -> None:
        operations: list[str] = []
        if stage_uri is not None:
            operations.extend(
                (
                    f"COPY SILENT GRAPH <{stage_uri}> TO DEFAULT",
                    f"DROP SILENT GRAPH <{stage_uri}>",
                )
            )
        elif delete_target:
            operations.append("DROP SILENT DEFAULT")
        receipt_graph = str(receipt.provider_commit_ref["receipt_graph"])
        triples = self._receipt_graph(receipt).serialize(format="nt")
        if isinstance(triples, bytes):
            triples = triples.decode("utf-8")
        operations.append(
            f"INSERT DATA {{ GRAPH <{receipt_graph}> {{\n{triples.strip()}\n}} }}"
        )
        update = " ;\n".join(operations)
        try:
            with self._client() as client:
                response = client.post(
                    target.sparql_update_endpoint,
                    content=update.encode("utf-8"),
                    headers={
                        "Content-Type": "application/sparql-update; charset=utf-8",
                        "X-GDA-Plan-SHA256": receipt.plan_sha256,
                        "Idempotency-Key": receipt.idempotency_key,
                    },
                )
                response.raise_for_status()
        except httpx.HTTPError as exc:
            raise RDFProjectionExecutionError(
                "Fuseki target and provider receipt commit failed"
            ) from exc


__all__ = [
    "RDFProjectionConfigurationError",
    "RDFProjectionExecutionError",
    "RDFProjectionRepairExecutor",
    "RDFProjectionRepairReceipt",
    "RDFProjectionTarget",
    "RDFProjectionTargetRegistry",
    "RDFProjectionValidationError",
    "rdf_projection_receipt_fingerprint",
    "rdf_graph_fingerprint",
]
