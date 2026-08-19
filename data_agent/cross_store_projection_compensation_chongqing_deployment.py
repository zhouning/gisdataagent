"""Seal Chongqing customer-data deployment evidence for compensation runs.

The compensation chain already pins its own recovery snapshot and rule
contracts.  This module adds a separately verifiable catalog of the supplied
Chongqing customer bundle, its ontology mapping baseline, and its relationship
to a sealed dispatch/plan/materialization chain.  It is preparation evidence
only: it never reads Provider credentials, materializes payloads, invokes an
adapter, or writes any authority record.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any, ClassVar, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from .chongqing_customer_data_quality import (
    ChongqingCustomerDataQualityError,
    build_chongqing_customer_data_quality_report,
)
from .chongqing_entity_link_baseline import CUSTOMER_BUNDLE_DIR
from .cross_store_projection_compensation_dispatch import (
    FederatedProjectionCompensationDispatchIntent,
)
from .cross_store_projection_compensation_provider_materialization import (
    FederatedProjectionCompensationProviderMaterializationSet,
)
from .cross_store_projection_compensation_provider_plan import (
    FederatedProjectionCompensationProviderPlanSet,
)
from .cross_store_projection_consistency import ProjectionEngine
from .natural_resource_ontology_demo import DemoBundleError, NaturalResourceOntologyDemo
from .platform_contracts import (
    NonEmptyText,
    ResourceURNText,
    Sha256,
    TenantId,
    canonical_json_fingerprint,
)


class ChongqingFederatedCompensationDeploymentError(ValueError):
    """The Chongqing deployment evidence cannot be safely sealed."""


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


def _fingerprint(schema: str, values: dict[str, Any], hash_field: str) -> str:
    payload = dict(values)
    payload.pop(hash_field, None)
    return canonical_json_fingerprint({"schema": schema, "data": _json_ready(payload)})


def _json_ready(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, Mapping):
        return {str(key): _json_ready(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_json_ready(item) for item in value]
    return value


class ChongqingCustomerBundleArtifact(_FrozenModel):
    """One hash-only artifact from the supplied Chongqing demo bundle."""

    schema_id: ClassVar[str] = "gda.chongqing-customer-bundle-artifact.v1"
    artifact_name: NonEmptyText
    byte_size: int = Field(ge=1)
    content_sha256: Sha256
    artifact_sha256: Sha256

    @model_validator(mode="after")
    def _sealed(self) -> ChongqingCustomerBundleArtifact:
        if Path(self.artifact_name).name != self.artifact_name:
            raise ValueError("customer bundle artifact name must not contain a path")
        expected = _fingerprint(
            self.schema_id,
            self.model_dump(mode="json", exclude={"artifact_sha256"}),
            "artifact_sha256",
        )
        if self.artifact_sha256 != expected:
            raise ValueError("customer bundle artifact fingerprint is invalid")
        return self


class ChongqingCustomerSourceRecord(_FrozenModel):
    """A source-system record summary without exposing customer source paths."""

    schema_id: ClassVar[str] = "gda.chongqing-customer-source-record.v1"
    source_role: NonEmptyText
    source_content_sha256: Sha256
    record_count: int = Field(ge=0)
    source_record_sha256: Sha256

    @model_validator(mode="after")
    def _sealed(self) -> ChongqingCustomerSourceRecord:
        if "/" in self.source_role or "\\" in self.source_role:
            raise ValueError("customer source role must not expose a source path")
        expected = _fingerprint(
            self.schema_id,
            self.model_dump(mode="json", exclude={"source_record_sha256"}),
            "source_record_sha256",
        )
        if self.source_record_sha256 != expected:
            raise ValueError("customer source record fingerprint is invalid")
        return self


class ChongqingCustomerFieldMapping(_FrozenModel):
    """One source-field to natural-resource ontology mapping declaration."""

    schema_id: ClassVar[str] = "gda.chongqing-customer-field-mapping.v1"
    source_field: NonEmptyText
    ontology_term: NonEmptyText
    relation: NonEmptyText
    mapping_sha256: Sha256

    @model_validator(mode="after")
    def _sealed(self) -> ChongqingCustomerFieldMapping:
        if any("/" in value or "\\" in value for value in (self.source_field, self.ontology_term)):
            raise ValueError("customer field mapping must not expose a local path")
        expected = _fingerprint(
            self.schema_id,
            self.model_dump(mode="json", exclude={"mapping_sha256"}),
            "mapping_sha256",
        )
        if self.mapping_sha256 != expected:
            raise ValueError("customer field mapping fingerprint is invalid")
        return self


class ChongqingFederatedCompensationSourceCatalog(_FrozenModel):
    """Pinned customer-bundle, ontology, source and field-mapping evidence."""

    schema_id: ClassVar[str] = "gda.chongqing-federated-compensation-source-catalog.v1"
    customer_bundle_id: Literal["natural-resource-ontology-customer-demo-v1"]
    customer_bundle_version: Literal["1.0.0"]
    ontology_package_id: Literal["natural-resource-one-map:2.3.0:587915868b1221af"]
    ontology_content_sha256: Literal[
        "587915868b1221af2315508ede7bf7babced063cba8b261de2f10afa23841019"
    ]
    customer_data_quality_report_sha256: Sha256
    artifacts: tuple[ChongqingCustomerBundleArtifact, ...] = Field(min_length=1)
    sources: tuple[ChongqingCustomerSourceRecord, ...] = Field(min_length=1)
    field_mappings: tuple[ChongqingCustomerFieldMapping, ...] = Field(min_length=1)
    field_mapping_set_sha256: Sha256
    review_state: Literal["technical_baseline_unreviewed"] = "technical_baseline_unreviewed"
    intended_use: Literal["assisted_precheck_not_for_production_decision"] = (
        "assisted_precheck_not_for_production_decision"
    )
    source_catalog_sha256: Sha256

    @model_validator(mode="after")
    def _sealed(self) -> ChongqingFederatedCompensationSourceCatalog:
        artifact_names = tuple(item.artifact_name for item in self.artifacts)
        source_roles = tuple(item.source_role for item in self.sources)
        mapping_identities = tuple(
            (item.source_field, item.ontology_term, item.relation) for item in self.field_mappings
        )
        if artifact_names != tuple(sorted(set(artifact_names))):
            raise ValueError("customer bundle artifacts must be unique and sorted")
        if source_roles != tuple(sorted(set(source_roles))):
            raise ValueError("customer source roles must be unique and sorted")
        if mapping_identities != tuple(sorted(set(mapping_identities))):
            raise ValueError("customer field mappings must be unique and sorted")
        expected_mapping_set = canonical_json_fingerprint(
            {
                "schema": "gda.chongqing-customer-field-mapping-set.v1",
                "mappings": [item.model_dump(mode="json") for item in self.field_mappings],
            }
        )
        if self.field_mapping_set_sha256 != expected_mapping_set:
            raise ValueError("customer field mapping set fingerprint is invalid")
        expected = _fingerprint(
            self.schema_id,
            self.model_dump(mode="json", exclude={"source_catalog_sha256"}),
            "source_catalog_sha256",
        )
        if self.source_catalog_sha256 != expected:
            raise ValueError("Chongqing source catalog fingerprint is invalid")
        return self


class ChongqingFederatedCompensationDeploymentItem(_FrozenModel):
    """One no-payload Provider position in the customer deployment package."""

    schema_id: ClassVar[str] = "gda.chongqing-federated-compensation-deployment-item.v1"
    position: int = Field(ge=0, le=31)
    source_plan_sha256: Sha256
    source_resource_version_ref: NonEmptyText
    source_content_sha256: Sha256
    projection_id: NonEmptyText
    target_engine: ProjectionEngine
    target_ref: NonEmptyText
    plan_binding_sha256: Sha256
    materialization_binding_sha256: Sha256
    provider_plan_sha256: Sha256
    provider_idempotency_key: Sha256
    materialization_ref: ResourceURNText
    item_sha256: Sha256

    @model_validator(mode="after")
    def _sealed(self) -> ChongqingFederatedCompensationDeploymentItem:
        expected = _fingerprint(
            self.schema_id,
            self.model_dump(mode="json", exclude={"item_sha256"}),
            "item_sha256",
        )
        if self.item_sha256 != expected:
            raise ValueError("Chongqing deployment item fingerprint is invalid")
        return self


class ChongqingFederatedCompensationDeploymentBinding(_FrozenModel):
    """Read-only deployment package bound to one sealed compensation run."""

    schema_id: ClassVar[str] = "gda.chongqing-federated-compensation-deployment-binding.v1"
    tenant_id: TenantId
    run_id: NonEmptyText
    dispatch_intent_sha256: Sha256
    recovery_source_snapshot_sha256: Sha256
    plan_set_sha256: Sha256
    materialization_set_sha256: Sha256
    source_catalog_sha256: Sha256
    field_mapping_set_sha256: Sha256
    customer_data_quality_report_sha256: Sha256
    approved_rule_ids: tuple[NonEmptyText, ...] = Field(min_length=1, max_length=8)
    approved_rule_contract_sha256s: tuple[Sha256, ...] = Field(
        min_length=1,
        max_length=8,
    )
    items: tuple[ChongqingFederatedCompensationDeploymentItem, ...] = Field(
        min_length=1,
        max_length=32,
    )
    deployment_state: Literal["customer_catalog_bound_pending_provider_execution"] = (
        "customer_catalog_bound_pending_provider_execution"
    )
    provider_dispatch_performed: Literal[False] = False
    checkpoint_authority_write_performed: Literal[False] = False
    compensation_completion_recorded: Literal[False] = False
    review_state: Literal["technical_baseline_unreviewed"] = "technical_baseline_unreviewed"
    intended_use: Literal["assisted_precheck_not_for_production_decision"] = (
        "assisted_precheck_not_for_production_decision"
    )
    deployment_binding_sha256: Sha256

    @model_validator(mode="after")
    def _sealed(self) -> ChongqingFederatedCompensationDeploymentBinding:
        positions = tuple(item.position for item in self.items)
        source_plans = tuple(item.source_plan_sha256 for item in self.items)
        idempotency_keys = tuple(item.provider_idempotency_key for item in self.items)
        if positions != tuple(range(len(self.items))):
            raise ValueError("Chongqing deployment positions must be contiguous and ordered")
        if len(set(source_plans)) != len(source_plans):
            raise ValueError("Chongqing deployment source plans must be unique")
        if len(set(idempotency_keys)) != len(idempotency_keys):
            raise ValueError("Chongqing deployment idempotency keys must be unique")
        if self.approved_rule_ids != tuple(sorted(set(self.approved_rule_ids))):
            raise ValueError("Chongqing deployment rule IDs must be unique and sorted")
        if self.approved_rule_contract_sha256s != tuple(
            sorted(set(self.approved_rule_contract_sha256s))
        ):
            raise ValueError("Chongqing deployment rule hashes must be unique and sorted")
        expected = _fingerprint(
            self.schema_id,
            self.model_dump(mode="json", exclude={"deployment_binding_sha256"}),
            "deployment_binding_sha256",
        )
        if self.deployment_binding_sha256 != expected:
            raise ValueError("Chongqing deployment binding fingerprint is invalid")
        return self


def _catalog_artifact(item: dict[str, Any]) -> ChongqingCustomerBundleArtifact:
    values = {
        "artifact_name": str(item.get("name") or ""),
        "byte_size": item.get("size"),
        "content_sha256": item.get("sha256"),
    }
    return ChongqingCustomerBundleArtifact(
        **values,
        artifact_sha256=_fingerprint(
            ChongqingCustomerBundleArtifact.schema_id,
            values,
            "artifact_sha256",
        ),
    )


def _catalog_source(item: dict[str, Any]) -> ChongqingCustomerSourceRecord:
    values = {
        "source_role": str(item.get("role") or ""),
        "source_content_sha256": item.get("sha256"),
        "record_count": item.get("record_count"),
    }
    return ChongqingCustomerSourceRecord(
        **values,
        source_record_sha256=_fingerprint(
            ChongqingCustomerSourceRecord.schema_id,
            values,
            "source_record_sha256",
        ),
    )


def _catalog_mapping(item: dict[str, Any]) -> ChongqingCustomerFieldMapping:
    values = {
        "source_field": str(item.get("source") or ""),
        "ontology_term": str(item.get("target") or ""),
        "relation": str(item.get("relation") or ""),
    }
    return ChongqingCustomerFieldMapping(
        **values,
        mapping_sha256=_fingerprint(
            ChongqingCustomerFieldMapping.schema_id,
            values,
            "mapping_sha256",
        ),
    )


def build_chongqing_federated_compensation_source_catalog(
    *,
    bundle_dir: str | Path | None = None,
) -> ChongqingFederatedCompensationSourceCatalog:
    """Read and seal the supplied Chongqing demo bundle without provider access."""

    try:
        demo = NaturalResourceOntologyDemo(bundle_dir=bundle_dir)
    except DemoBundleError as exc:
        raise ChongqingFederatedCompensationDeploymentError(
            "Chongqing customer bundle cannot be verified"
        ) from exc
    bundle = demo.demo.get("bundle")
    ontology = demo.demo.get("ontology")
    raw_sources = demo.demo.get("sources")
    raw_mappings = demo.demo.get("field_mappings")
    raw_artifacts = demo.manifest.get("files")
    if (
        not all(isinstance(value, list) for value in (raw_sources, raw_mappings, raw_artifacts))
        or not isinstance(bundle, dict)
        or not isinstance(ontology, dict)
    ):
        raise ChongqingFederatedCompensationDeploymentError(
            "Chongqing customer bundle catalog is incomplete"
        )
    if any(
        not isinstance(item, dict)
        for values in (raw_artifacts, raw_sources, raw_mappings)
        for item in values
    ):
        raise ChongqingFederatedCompensationDeploymentError(
            "Chongqing customer bundle catalog contains a non-object item"
        )
    try:
        artifacts = tuple(
            sorted(
                (_catalog_artifact(item) for item in raw_artifacts),
                key=lambda item: item.artifact_name,
            )
        )
        sources = tuple(
            sorted(
                (_catalog_source(item) for item in raw_sources),
                key=lambda item: item.source_role,
            )
        )
        field_mappings = tuple(
            sorted(
                (_catalog_mapping(item) for item in raw_mappings),
                key=lambda item: (item.source_field, item.ontology_term, item.relation),
            )
        )
    except (TypeError, ValueError, ValidationError) as exc:
        raise ChongqingFederatedCompensationDeploymentError(
            "Chongqing customer bundle contains an invalid catalog item"
        ) from exc
    quality_bundle_dir = bundle_dir if bundle_dir is not None else CUSTOMER_BUNDLE_DIR
    try:
        quality_report = build_chongqing_customer_data_quality_report(
            bundle_dir=quality_bundle_dir,
        )
    except ChongqingCustomerDataQualityError as exc:
        raise ChongqingFederatedCompensationDeploymentError(
            "Chongqing customer bundle lacks a sealed aggregate quality report"
        ) from exc
    mapping_set_sha256 = canonical_json_fingerprint(
        {
            "schema": "gda.chongqing-customer-field-mapping-set.v1",
            "mappings": [item.model_dump(mode="json") for item in field_mappings],
        }
    )
    values = {
        "customer_bundle_id": bundle.get("id"),
        "customer_bundle_version": bundle.get("version"),
        "ontology_package_id": ontology.get("package_id"),
        "ontology_content_sha256": ontology.get("sha256"),
        "customer_data_quality_report_sha256": quality_report.report_sha256,
        "artifacts": artifacts,
        "sources": sources,
        "field_mappings": field_mappings,
        "field_mapping_set_sha256": mapping_set_sha256,
        "review_state": "technical_baseline_unreviewed",
        "intended_use": "assisted_precheck_not_for_production_decision",
    }
    try:
        return ChongqingFederatedCompensationSourceCatalog(
            **values,
            source_catalog_sha256=_fingerprint(
                ChongqingFederatedCompensationSourceCatalog.schema_id,
                values,
                "source_catalog_sha256",
            ),
        )
    except (TypeError, ValueError, ValidationError) as exc:
        raise ChongqingFederatedCompensationDeploymentError(
            "Chongqing customer bundle differs from the pinned deployment baseline"
        ) from exc


def _validated_chain(
    intent: FederatedProjectionCompensationDispatchIntent,
    plan_set: FederatedProjectionCompensationProviderPlanSet,
    materialization: FederatedProjectionCompensationProviderMaterializationSet,
    source_catalog: ChongqingFederatedCompensationSourceCatalog,
) -> tuple[
    FederatedProjectionCompensationDispatchIntent,
    FederatedProjectionCompensationProviderPlanSet,
    FederatedProjectionCompensationProviderMaterializationSet,
    ChongqingFederatedCompensationSourceCatalog,
]:
    try:
        return (
            FederatedProjectionCompensationDispatchIntent.model_validate(
                intent.model_dump(mode="python")
            ),
            FederatedProjectionCompensationProviderPlanSet.model_validate(
                plan_set.model_dump(mode="python")
            ),
            FederatedProjectionCompensationProviderMaterializationSet.model_validate(
                materialization.model_dump(mode="python")
            ),
            ChongqingFederatedCompensationSourceCatalog.model_validate(
                source_catalog.model_dump(mode="python")
            ),
        )
    except (AttributeError, TypeError, ValueError, ValidationError) as exc:
        raise ChongqingFederatedCompensationDeploymentError(
            "Chongqing deployment input violates a sealed contract"
        ) from exc


def build_chongqing_federated_compensation_deployment_binding(
    intent: FederatedProjectionCompensationDispatchIntent,
    plan_set: FederatedProjectionCompensationProviderPlanSet,
    materialization: FederatedProjectionCompensationProviderMaterializationSet,
    source_catalog: ChongqingFederatedCompensationSourceCatalog,
) -> ChongqingFederatedCompensationDeploymentBinding:
    """Bind a sealed run to the pinned Chongqing customer catalog without execution."""

    intent, plan_set, materialization, source_catalog = _validated_chain(
        intent,
        plan_set,
        materialization,
        source_catalog,
    )
    if (
        plan_set.tenant_id != intent.tenant_id
        or plan_set.run_id != intent.run_id
        or plan_set.dispatch_intent_sha256 != intent.dispatch_intent_sha256
        or materialization.tenant_id != intent.tenant_id
        or materialization.run_id != intent.run_id
        or materialization.plan_set_sha256 != plan_set.plan_set_sha256
        or plan_set.provider_dispatch_performed
        or materialization.provider_dispatch_performed
        or plan_set.execution_allowed
        or materialization.execution_allowed
    ):
        raise ChongqingFederatedCompensationDeploymentError(
            "Chongqing deployment chain differs from the sealed dispatch intent"
        )
    plan_by_position = {item.position: item for item in plan_set.plan_bindings}
    source_by_position = {item.position: item for item in intent.plan_bindings}
    if (
        len(plan_by_position) != len(plan_set.plan_bindings)
        or len(source_by_position) != len(intent.plan_bindings)
        or len(materialization.bindings) != len(plan_set.plan_bindings)
        or set(plan_by_position) != set(source_by_position)
    ):
        raise ChongqingFederatedCompensationDeploymentError(
            "Chongqing deployment positions are incomplete"
        )
    items: list[ChongqingFederatedCompensationDeploymentItem] = []
    for materialized in materialization.bindings:
        plan = plan_by_position.get(materialized.position)
        source = source_by_position.get(materialized.position)
        if (
            plan is None
            or source is None
            or (
                plan.source_plan_sha256 != source.plan_sha256
                or plan.target_engine.value != source.target_engine
                or plan.target_ref != source.target_ref
                or materialized.plan_binding_sha256 != plan.plan_binding_sha256
                or materialized.target_engine is not plan.target_engine
                or materialized.target_ref != plan.target_ref
                or materialized.provider_idempotency_key != plan.provider_idempotency_key
            )
        ):
            raise ChongqingFederatedCompensationDeploymentError(
                "Chongqing deployment plan and materialization position differs"
            )
        values = {
            "position": materialized.position,
            "source_plan_sha256": plan.source_plan_sha256,
            "source_resource_version_ref": plan.source_resource_version_ref,
            "source_content_sha256": plan.source_content_sha256,
            "projection_id": materialized.projection_id,
            "target_engine": plan.target_engine,
            "target_ref": plan.target_ref,
            "plan_binding_sha256": plan.plan_binding_sha256,
            "materialization_binding_sha256": materialized.materialization_binding_sha256,
            "provider_plan_sha256": materialized.provider_plan_sha256,
            "provider_idempotency_key": materialized.provider_idempotency_key,
            "materialization_ref": materialized.materialization_ref,
        }
        items.append(
            ChongqingFederatedCompensationDeploymentItem(
                **values,
                item_sha256=_fingerprint(
                    ChongqingFederatedCompensationDeploymentItem.schema_id,
                    values,
                    "item_sha256",
                ),
            )
        )
    values = {
        "tenant_id": intent.tenant_id,
        "run_id": intent.run_id,
        "dispatch_intent_sha256": intent.dispatch_intent_sha256,
        "recovery_source_snapshot_sha256": intent.source_snapshot_sha256,
        "plan_set_sha256": plan_set.plan_set_sha256,
        "materialization_set_sha256": materialization.materialization_set_sha256,
        "source_catalog_sha256": source_catalog.source_catalog_sha256,
        "field_mapping_set_sha256": source_catalog.field_mapping_set_sha256,
        "customer_data_quality_report_sha256": (source_catalog.customer_data_quality_report_sha256),
        "approved_rule_ids": intent.approved_rule_ids,
        "approved_rule_contract_sha256s": intent.approved_rule_contract_sha256s,
        "items": tuple(items),
        "deployment_state": "customer_catalog_bound_pending_provider_execution",
        "provider_dispatch_performed": False,
        "checkpoint_authority_write_performed": False,
        "compensation_completion_recorded": False,
        "review_state": "technical_baseline_unreviewed",
        "intended_use": "assisted_precheck_not_for_production_decision",
    }
    return ChongqingFederatedCompensationDeploymentBinding(
        **values,
        deployment_binding_sha256=_fingerprint(
            ChongqingFederatedCompensationDeploymentBinding.schema_id,
            values,
            "deployment_binding_sha256",
        ),
    )


__all__ = [
    "ChongqingCustomerBundleArtifact",
    "ChongqingCustomerFieldMapping",
    "ChongqingCustomerSourceRecord",
    "ChongqingFederatedCompensationDeploymentBinding",
    "ChongqingFederatedCompensationDeploymentError",
    "ChongqingFederatedCompensationDeploymentItem",
    "ChongqingFederatedCompensationSourceCatalog",
    "build_chongqing_federated_compensation_deployment_binding",
    "build_chongqing_federated_compensation_source_catalog",
]
