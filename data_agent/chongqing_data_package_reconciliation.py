"""Phased append-only reconciliation for a complete Chongqing data package."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .chongqing_entity_link_baseline import ChongqingEntityLinkBaseline
from .chongqing_entity_link_reconciliation import (
    ChongqingLinkReconciliationPlan,
    build_chongqing_link_reconciliation_plan,
)
from .entity_link_authority import (
    EntityLinkAuthority,
    EntityLinkNotFoundError,
    EntitySourceBinding,
    EntitySourceBindingDraft,
    InstanceLinkAssertion,
    InstanceLinkQuery,
    InstanceLinkQueryMode,
)
from .platform_contracts import Sha256, TenantId
from .temporal_entity_authority import (
    TemporalEntityAssertion,
    TemporalEntityAssertionDraft,
    TemporalEntityAuthority,
    TemporalEntityNotFoundError,
    TemporalEntityQuery,
    TemporalLifecycleState,
    TemporalMutationKind,
    TemporalQueryMode,
)


class ChongqingDataPackageReconciliationError(RuntimeError):
    """A complete-package delta is inconsistent or could not be applied."""


class ChongqingDataPackageReconciliationCancelledError(
    ChongqingDataPackageReconciliationError
):
    """Cooperative cancellation observed between atomic authority batches."""


ReconciliationProgressCallback = Callable[[str, int, int], None]
ReconciliationCancelCheck = Callable[[], None]


class _FrozenContract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


def _document_sha256(document: Any) -> str:
    payload = json.dumps(
        document,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _model_sha256(model: BaseModel) -> str:
    return _document_sha256(model.model_dump(mode="json"))


def _aware_utc(value: datetime, name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")
    return value.astimezone(UTC)


def _idempotency_key(
    kind: str,
    identity_ref: str,
    *,
    current_sha256: str | None,
    desired_sha256: str | None,
    effective_at: datetime,
) -> str:
    digest = _document_sha256(
        {
            "kind": kind,
            "identity_ref": identity_ref,
            "current_sha256": current_sha256,
            "desired_sha256": desired_sha256,
            "effective_at": effective_at.isoformat(),
        }
    )
    return f"cq.package.reconcile.{kind}.{digest[:32]}"


def _entity_drafts(
    baseline: ChongqingEntityLinkBaseline,
) -> dict[str, TemporalEntityAssertionDraft]:
    values = {draft.entity_ref: draft for draft in baseline.temporal_entity_drafts}
    if len(values) != len(baseline.temporal_entity_drafts):
        raise ChongqingDataPackageReconciliationError(
            "a baseline contains duplicate entity references"
        )
    return values


def _source_drafts(
    baseline: ChongqingEntityLinkBaseline,
) -> dict[str, EntitySourceBindingDraft]:
    values = {
        draft.source_identity_ref: draft for draft in baseline.source_binding_drafts
    }
    if len(values) != len(baseline.source_binding_drafts):
        raise ChongqingDataPackageReconciliationError(
            "a baseline contains duplicate source identity references"
        )
    return values


def _entity_state(
    document: TemporalEntityAssertionDraft | TemporalEntityAssertion,
) -> dict[str, Any]:
    return {
        "entity_ref": document.entity_ref,
        "object_type": document.object_type,
        "lifecycle_state": document.lifecycle_state.value,
        "attributes": document.attributes,
        "valid_to": (
            document.valid_to.isoformat() if document.valid_to is not None else None
        ),
        "source_version_refs": list(document.source_version_refs),
        "owner_subject": document.owner_subject,
    }


def _entity_state_sha256(
    document: TemporalEntityAssertionDraft | TemporalEntityAssertion,
) -> str:
    return _document_sha256(_entity_state(document))


def _source_identity(document: EntitySourceBindingDraft | EntitySourceBinding) -> tuple[Any, ...]:
    return (
        document.source_identity_ref,
        document.source_system_ref,
        document.source_object_type,
        document.source_object_id,
        document.entity_ref,
        document.entity_object_type,
        document.ontology_class_uri,
        document.owner_subject,
    )


def _source_natural_key(
    document: EntitySourceBindingDraft | EntitySourceBinding,
) -> tuple[str, str, str]:
    return (
        document.source_system_ref,
        document.source_object_type,
        document.source_object_id,
    )


def _source_natural_identities(
    sources: Mapping[str, EntitySourceBindingDraft],
) -> dict[tuple[str, str, str], str]:
    values: dict[tuple[str, str, str], str] = {}
    for source_ref, draft in sources.items():
        natural_key = _source_natural_key(draft)
        existing = values.get(natural_key)
        if existing is not None and existing != source_ref:
            raise ChongqingDataPackageReconciliationError(
                "a baseline maps one source natural key to multiple identities"
            )
        values[natural_key] = source_ref
    return values


def _source_state(
    document: EntitySourceBindingDraft | EntitySourceBinding,
) -> dict[str, Any]:
    return {
        "source_identity": list(_source_identity(document)),
        "source_version_ref": document.source_version_ref,
        "valid_to": (
            document.valid_to.isoformat() if document.valid_to is not None else None
        ),
        "resolution_method": document.resolution_method.value,
        "confidence_basis_points": document.confidence_basis_points,
        "evidence": document.evidence,
    }


def _source_state_sha256(
    document: EntitySourceBindingDraft | EntitySourceBinding,
) -> str:
    return _document_sha256(_source_state(document))


def _entity_correction(
    current: TemporalEntityAssertion,
    desired: TemporalEntityAssertionDraft,
    *,
    effective_at: datetime,
) -> TemporalEntityAssertionDraft:
    desired_sha256 = _entity_state_sha256(desired)
    return desired.model_copy(
        update={
            "valid_from": current.valid_from,
            "valid_to": current.valid_to,
            "lifecycle_state": current.lifecycle_state,
            "mutation_kind": TemporalMutationKind.CORRECTION,
            "supersedes_assertion_id": current.assertion_id,
            "idempotency_key": _idempotency_key(
                "entity-correct",
                desired.entity_ref,
                current_sha256=current.assertion_sha256,
                desired_sha256=desired_sha256,
                effective_at=effective_at,
            ),
            "reason": "correct entity state from recomputed Chongqing package",
        }
    )


def _entity_addition(
    desired: TemporalEntityAssertionDraft,
    *,
    effective_at: datetime,
) -> TemporalEntityAssertionDraft:
    return desired.model_copy(
        update={
            "valid_from": effective_at,
            "valid_to": None,
            "lifecycle_state": TemporalLifecycleState.ACTIVE,
            "mutation_kind": TemporalMutationKind.INITIAL,
            "supersedes_assertion_id": None,
            "idempotency_key": _idempotency_key(
                "entity-add",
                desired.entity_ref,
                current_sha256=None,
                desired_sha256=_entity_state_sha256(desired),
                effective_at=effective_at,
            ),
            "reason": "add entity from recomputed Chongqing package",
        }
    )


def _entity_activation(
    current: TemporalEntityAssertion,
    desired: TemporalEntityAssertionDraft,
    *,
    effective_at: datetime,
) -> TemporalEntityAssertionDraft:
    return desired.model_copy(
        update={
            "valid_from": effective_at,
            "valid_to": None,
            "lifecycle_state": TemporalLifecycleState.ACTIVE,
            "mutation_kind": TemporalMutationKind.TRANSITION,
            "supersedes_assertion_id": None,
            "idempotency_key": _idempotency_key(
                "entity-activate",
                desired.entity_ref,
                current_sha256=current.assertion_sha256,
                desired_sha256=_entity_state_sha256(desired),
                effective_at=effective_at,
            ),
            "reason": "activate non-active entity present in recomputed Chongqing package",
        }
    )


def _entity_retirement(
    current: TemporalEntityAssertion,
    *,
    effective_at: datetime,
) -> TemporalEntityAssertionDraft:
    evidence = {
        **current.attributes,
        "reconciliation_retirement": {
            "previous_assertion_sha256": current.assertion_sha256,
            "reason": "entity_absent_from_recomputed_chongqing_package",
        },
    }
    return TemporalEntityAssertionDraft(
        tenant_id=current.tenant_id,
        entity_ref=current.entity_ref,
        object_type=current.object_type,
        lifecycle_state=TemporalLifecycleState.RETIRED,
        attributes=evidence,
        valid_from=effective_at,
        valid_to=None,
        source_version_refs=current.source_version_refs,
        mutation_kind=TemporalMutationKind.TRANSITION,
        idempotency_key=_idempotency_key(
            "entity-retire",
            current.entity_ref,
            current_sha256=current.assertion_sha256,
            desired_sha256=None,
            effective_at=effective_at,
        ),
        owner_subject=current.owner_subject,
        recorded_by=current.recorded_by,
        reason="retire entity absent from recomputed Chongqing package",
    )


def _source_update(
    desired: EntitySourceBindingDraft,
    *,
    current: EntitySourceBinding | None,
    effective_at: datetime,
) -> EntitySourceBindingDraft:
    action = "source-add" if current is None else "source-update"
    return desired.model_copy(
        update={
            "valid_from": effective_at,
            "valid_to": None,
            "idempotency_key": _idempotency_key(
                action,
                desired.source_identity_ref,
                current_sha256=(current.binding_sha256 if current is not None else None),
                desired_sha256=_source_state_sha256(desired),
                effective_at=effective_at,
            ),
            "reason": "append source-version evidence from recomputed Chongqing package",
        }
    )


class _ChongqingDataPackageReconciliationPlanBody(_FrozenContract):
    schema_id: Literal["gda.chongqing-data-package-reconciliation-plan.v1"] = (
        "gda.chongqing-data-package-reconciliation-plan.v1"
    )
    tenant_id: TenantId
    previous_customer_bundle_version: str
    desired_customer_bundle_version: str
    ontology_package_id: str
    ontology_package_sha256: Sha256
    ontology_review_status: Literal["technical_baseline_unreviewed"]
    usage_status: Literal["assisted_precheck_not_for_production_decision"]
    decision_scope: str
    effective_at: datetime
    previous_baseline_sha256: Sha256
    desired_baseline_sha256: Sha256
    entity_authority_input_sha256: Sha256
    source_authority_input_sha256: Sha256
    unchanged_entity_refs: tuple[str, ...]
    unchanged_source_identity_refs: tuple[str, ...]
    retained_retired_source_identity_refs: tuple[str, ...]
    entity_correction_drafts: tuple[TemporalEntityAssertionDraft, ...]
    entity_addition_drafts: tuple[TemporalEntityAssertionDraft, ...]
    entity_activation_drafts: tuple[TemporalEntityAssertionDraft, ...]
    source_binding_drafts: tuple[EntitySourceBindingDraft, ...]
    entity_retirement_drafts: tuple[TemporalEntityAssertionDraft, ...]
    link_plan: ChongqingLinkReconciliationPlan
    operation_count: int = Field(ge=0)

    @field_validator("effective_at")
    @classmethod
    def _effective_time(cls, value: datetime) -> datetime:
        return _aware_utc(value, "effective_at")

    @model_validator(mode="after")
    def _consistent_plan(self) -> _ChongqingDataPackageReconciliationPlanBody:
        entity_phases = (
            self.entity_correction_drafts,
            self.entity_addition_drafts,
            self.entity_activation_drafts,
            self.entity_retirement_drafts,
        )
        expected = (
            sum(len(items) for items in entity_phases)
            + len(self.source_binding_drafts)
            + self.link_plan.operation_count
        )
        if self.operation_count != expected:
            raise ValueError("package reconciliation operation count is inconsistent")
        if self.link_plan.tenant_id != self.tenant_id:
            raise ValueError("package and Link reconciliation tenants differ")
        if (
            self.link_plan.previous_baseline_sha256 != self.previous_baseline_sha256
            or self.link_plan.desired_baseline_sha256 != self.desired_baseline_sha256
            or self.link_plan.effective_at != self.effective_at
        ):
            raise ValueError("package and Link reconciliation versions differ")
        sorted_groups: tuple[tuple[str, ...], ...] = (
            self.unchanged_entity_refs,
            self.unchanged_source_identity_refs,
            self.retained_retired_source_identity_refs,
            *(tuple(draft.entity_ref for draft in items) for items in entity_phases),
            tuple(
                draft.source_identity_ref for draft in self.source_binding_drafts
            ),
        )
        if any(values != tuple(sorted(values)) for values in sorted_groups):
            raise ValueError("package reconciliation outcomes must be sorted")
        entity_outcomes = [
            *self.unchanged_entity_refs,
            *(draft.entity_ref for items in entity_phases for draft in items),
        ]
        if len(entity_outcomes) != len(set(entity_outcomes)):
            raise ValueError("an entity appears in multiple reconciliation outcomes")
        source_outcomes = [
            *self.unchanged_source_identity_refs,
            *self.retained_retired_source_identity_refs,
            *(draft.source_identity_ref for draft in self.source_binding_drafts),
        ]
        if len(source_outcomes) != len(set(source_outcomes)):
            raise ValueError("a source identity appears in multiple outcomes")
        return self


class ChongqingDataPackageReconciliationPlan(
    _ChongqingDataPackageReconciliationPlanBody
):
    plan_sha256: Sha256

    @model_validator(mode="after")
    def _valid_plan_hash(self) -> ChongqingDataPackageReconciliationPlan:
        expected = _document_sha256(
            self.model_dump(mode="json", exclude={"plan_sha256"})
        )
        if self.plan_sha256 != expected:
            raise ValueError("package reconciliation plan SHA-256 is invalid")
        return self


def build_chongqing_data_package_reconciliation_plan(
    *,
    previous_baseline: ChongqingEntityLinkBaseline,
    desired_baseline: ChongqingEntityLinkBaseline,
    entity_assertions: Mapping[str, TemporalEntityAssertion | None],
    source_bindings: Mapping[str, EntitySourceBinding | None],
    link_assertions: Mapping[str, InstanceLinkAssertion | None],
    effective_at: datetime,
) -> ChongqingDataPackageReconciliationPlan:
    """Compile all entity, source-version, and Link deltas without writing."""
    effective_at = _aware_utc(effective_at, "effective_at")
    if previous_baseline.tenant_id != desired_baseline.tenant_id:
        raise ChongqingDataPackageReconciliationError("baseline tenants do not match")
    fixed_fields = (
        "ontology_package_id",
        "ontology_package_sha256",
        "ontology_review_status",
        "usage_status",
        "decision_scope",
        "precision_policy",
    )
    if any(
        getattr(previous_baseline, name) != getattr(desired_baseline, name)
        for name in fixed_fields
    ):
        raise ChongqingDataPackageReconciliationError(
            "baseline ontology, review, usage, or precision contract changed"
        )
    if previous_baseline.link_type_draft != desired_baseline.link_type_draft:
        raise ChongqingDataPackageReconciliationError(
            "Link type changes require a separately versioned migration"
        )

    previous_entities = _entity_drafts(previous_baseline)
    desired_entities = _entity_drafts(desired_baseline)
    previous_sources = _source_drafts(previous_baseline)
    desired_sources = _source_drafts(desired_baseline)
    entity_refs = set(previous_entities) | set(desired_entities)
    source_refs = set(previous_sources) | set(desired_sources)
    if set(entity_assertions) != entity_refs:
        raise ChongqingDataPackageReconciliationError(
            "entity assertions must cover the union of baseline entities"
        )
    if set(source_bindings) != source_refs:
        raise ChongqingDataPackageReconciliationError(
            "source bindings must cover the union of baseline source identities"
        )
    for entities, sources in (
        (previous_entities, previous_sources),
        (desired_entities, desired_sources),
    ):
        if any(
            draft.entity_ref not in entities for draft in sources.values()
        ):
            raise ChongqingDataPackageReconciliationError(
                "a source identity targets an entity absent from its baseline"
            )
    for draft in desired_baseline.link_assertion_drafts:
        if (
            draft.source_entity_ref not in desired_entities
            or draft.target_entity_ref not in desired_entities
        ):
            raise ChongqingDataPackageReconciliationError(
                "a desired Link endpoint is absent from desired entities"
            )
    for draft in previous_baseline.link_assertion_drafts:
        if (
            draft.source_entity_ref not in previous_entities
            or draft.target_entity_ref not in previous_entities
        ):
            raise ChongqingDataPackageReconciliationError(
                "a previous Link endpoint is absent from previous entities"
            )

    previous_natural_sources = _source_natural_identities(previous_sources)
    desired_natural_sources = _source_natural_identities(desired_sources)
    for natural_key in previous_natural_sources.keys() & desired_natural_sources.keys():
        if previous_natural_sources[natural_key] != desired_natural_sources[natural_key]:
            raise ChongqingDataPackageReconciliationError(
                "a source natural key moved to another identity; lineage migration is required"
            )

    unchanged_entities: list[str] = []
    corrections: list[TemporalEntityAssertionDraft] = []
    additions: list[TemporalEntityAssertionDraft] = []
    activations: list[TemporalEntityAssertionDraft] = []
    retirements: list[TemporalEntityAssertionDraft] = []
    for entity_ref in sorted(entity_refs):
        before = previous_entities.get(entity_ref)
        desired = desired_entities.get(entity_ref)
        current = entity_assertions[entity_ref]
        identity = before or desired
        assert identity is not None
        if before is not None and desired is not None and (
            before.object_type != desired.object_type
            or before.owner_subject != desired.owner_subject
        ):
            raise ChongqingDataPackageReconciliationError(
                "stable entity type or owner changed; lineage migration is required"
            )
        if current is not None:
            if current.tenant_id != previous_baseline.tenant_id:
                raise ChongqingDataPackageReconciliationError(
                    "an entity authority assertion crosses tenant boundaries"
                )
            if current.entity_ref != entity_ref:
                raise ChongqingDataPackageReconciliationError(
                    "an entity authority assertion has the wrong identity"
                )
            if (
                current.object_type != identity.object_type
                or current.owner_subject != identity.owner_subject
            ):
                raise ChongqingDataPackageReconciliationError(
                    "stable entity type or owner differs from authority"
                )
        if desired is None:
            if current is None:
                raise ChongqingDataPackageReconciliationError(
                    "a previous entity is absent from authority"
                )
            if current.lifecycle_state in {
                TemporalLifecycleState.RETIRED,
                TemporalLifecycleState.DELETED,
            }:
                unchanged_entities.append(entity_ref)
            else:
                retirements.append(
                    _entity_retirement(current, effective_at=effective_at)
                )
            continue
        if current is None:
            if before is not None:
                raise ChongqingDataPackageReconciliationError(
                    "a retained entity is absent from authority"
                )
            additions.append(_entity_addition(desired, effective_at=effective_at))
            continue
        if current.lifecycle_state in {
            TemporalLifecycleState.RETIRED,
            TemporalLifecycleState.DELETED,
        }:
            raise ChongqingDataPackageReconciliationError(
                "a terminal entity cannot reappear without lineage migration"
            )
        if current.lifecycle_state in {
            TemporalLifecycleState.DRAFT,
            TemporalLifecycleState.SUSPENDED,
        }:
            activations.append(
                _entity_activation(current, desired, effective_at=effective_at)
            )
        elif _entity_state_sha256(current) == _entity_state_sha256(desired):
            unchanged_entities.append(entity_ref)
        else:
            corrections.append(
                _entity_correction(current, desired, effective_at=effective_at)
            )

    unchanged_sources: list[str] = []
    retired_sources: list[str] = []
    binding_updates: list[EntitySourceBindingDraft] = []
    for source_ref in sorted(source_refs):
        before = previous_sources.get(source_ref)
        desired = desired_sources.get(source_ref)
        current = source_bindings[source_ref]
        identity = before or desired
        assert identity is not None
        if before is not None and desired is not None:
            if _source_identity(before) != _source_identity(desired):
                raise ChongqingDataPackageReconciliationError(
                    "source identity semantics changed; lineage migration is required"
                )
        if current is not None:
            if current.tenant_id != previous_baseline.tenant_id:
                raise ChongqingDataPackageReconciliationError(
                    "a source binding crosses tenant boundaries"
                )
            if _source_identity(current) != _source_identity(identity):
                raise ChongqingDataPackageReconciliationError(
                    "source authority identity differs from the baseline"
                )
        if desired is None:
            if current is None:
                raise ChongqingDataPackageReconciliationError(
                    "a previous source identity is absent from authority"
                )
            retired_sources.append(source_ref)
        elif current is None:
            if before is not None:
                raise ChongqingDataPackageReconciliationError(
                    "a retained source identity is absent from authority"
                )
            binding_updates.append(
                _source_update(desired, current=None, effective_at=effective_at)
            )
        elif _source_state_sha256(current) == _source_state_sha256(desired):
            unchanged_sources.append(source_ref)
        else:
            binding_updates.append(
                _source_update(desired, current=current, effective_at=effective_at)
            )

    link_plan = build_chongqing_link_reconciliation_plan(
        previous_baseline=previous_baseline,
        desired_baseline=desired_baseline,
        authority_assertions=link_assertions,
        effective_at=effective_at,
        allow_entity_identity_changes=True,
    )
    previous_sha256 = _model_sha256(previous_baseline)
    desired_sha256 = _model_sha256(desired_baseline)
    if (
        link_plan.previous_baseline_sha256 != previous_sha256
        or link_plan.desired_baseline_sha256 != desired_sha256
    ):
        raise ChongqingDataPackageReconciliationError(
            "Link plan baseline fingerprint is inconsistent"
        )
    entity_input_sha256 = _document_sha256(
        {
            ref: (
                None
                if assertion is None
                else {
                    "assertion_id": str(assertion.assertion_id),
                    "assertion_sha256": assertion.assertion_sha256,
                    "state_sha256": _entity_state_sha256(assertion),
                }
            )
            for ref, assertion in sorted(entity_assertions.items())
        }
    )
    source_input_sha256 = _document_sha256(
        {
            ref: (
                None
                if binding is None
                else {
                    "binding_id": str(binding.binding_id),
                    "binding_sha256": binding.binding_sha256,
                    "state_sha256": _source_state_sha256(binding),
                }
            )
            for ref, binding in sorted(source_bindings.items())
        }
    )
    body = _ChongqingDataPackageReconciliationPlanBody(
        tenant_id=previous_baseline.tenant_id,
        previous_customer_bundle_version=previous_baseline.customer_bundle_version,
        desired_customer_bundle_version=desired_baseline.customer_bundle_version,
        ontology_package_id=previous_baseline.ontology_package_id,
        ontology_package_sha256=previous_baseline.ontology_package_sha256,
        ontology_review_status=previous_baseline.ontology_review_status,
        usage_status=previous_baseline.usage_status,
        decision_scope=previous_baseline.decision_scope,
        effective_at=effective_at,
        previous_baseline_sha256=previous_sha256,
        desired_baseline_sha256=desired_sha256,
        entity_authority_input_sha256=entity_input_sha256,
        source_authority_input_sha256=source_input_sha256,
        unchanged_entity_refs=tuple(unchanged_entities),
        unchanged_source_identity_refs=tuple(unchanged_sources),
        retained_retired_source_identity_refs=tuple(retired_sources),
        entity_correction_drafts=tuple(corrections),
        entity_addition_drafts=tuple(additions),
        entity_activation_drafts=tuple(activations),
        source_binding_drafts=tuple(binding_updates),
        entity_retirement_drafts=tuple(retirements),
        link_plan=link_plan,
        operation_count=(
            len(corrections)
            + len(additions)
            + len(activations)
            + len(binding_updates)
            + len(retirements)
            + link_plan.operation_count
        ),
    )
    return ChongqingDataPackageReconciliationPlan(
        **body.model_dump(mode="python"),
        plan_sha256=_document_sha256(body.model_dump(mode="json")),
    )


@dataclass(frozen=True)
class _PackageWriteState:
    entity_results: tuple[Any, ...]
    binding_results: tuple[Any, ...]
    link_results: tuple[Any, ...]
    batch_count: int
    entity_state_sha256: str
    binding_state_sha256: str
    link_state_sha256: str
    authority_state_sha256: str
    recorded_from: datetime | None
    recorded_through: datetime | None


_WritePhase = tuple[
    str,
    Sequence[Any],
    Callable[[Sequence[Any]], Sequence[Any]],
    list[Any],
]


def _write_batches(
    *,
    phase_name: str,
    drafts: Sequence[Any],
    operation: Callable[[Sequence[Any]], Sequence[Any]],
    batch_size: int,
    progress_label: str,
    progress_offset: int,
    progress_total: int,
    progress_callback: ReconciliationProgressCallback | None,
    cancel_check: ReconciliationCancelCheck | None,
) -> tuple[tuple[Any, ...], int]:
    results: list[Any] = []
    batch_count = 0
    for offset in range(0, len(drafts), batch_size):
        if cancel_check is not None:
            cancel_check()
        batch = tuple(drafts[offset : offset + batch_size])
        batch_count += 1
        try:
            written = tuple(operation(batch))
        except ChongqingDataPackageReconciliationCancelledError:
            raise
        except Exception as exc:
            raise ChongqingDataPackageReconciliationError(
                f"{phase_name} batch {batch_count} failed; earlier phases remain "
                "committed and the sealed plan is safe to replay"
            ) from exc
        if len(written) != len(batch):
            raise ChongqingDataPackageReconciliationError(
                f"{phase_name} returned {len(written)} results for {len(batch)} drafts"
            )
        results.extend(written)
        if cancel_check is not None:
            cancel_check()
        if progress_callback is not None:
            progress_callback(
                f"{progress_label}:{phase_name.replace(' ', '_')}",
                progress_offset + batch_count,
                progress_total,
            )
    return tuple(results), batch_count


def chongqing_data_package_reconciliation_batch_count(
    plan: ChongqingDataPackageReconciliationPlan,
    batch_size: int,
) -> int:
    """Return the exact number of atomic authority batches in one plan pass."""
    if batch_size < 1 or batch_size > 500:
        raise ChongqingDataPackageReconciliationError("batch_size must be 1..500")
    phase_counts = (
        len(plan.link_plan.retraction_drafts),
        len(plan.entity_correction_drafts),
        len(plan.entity_addition_drafts),
        len(plan.entity_activation_drafts),
        len(plan.source_binding_drafts),
        len(plan.link_plan.correction_drafts),
        len(plan.link_plan.restoration_drafts),
        len(plan.link_plan.addition_drafts),
        len(plan.entity_retirement_drafts),
    )
    return sum(
        (count + batch_size - 1) // batch_size for count in phase_counts if count
    )


def _result_state(
    results: Sequence[Any],
    *,
    identity_attribute: str,
    sha_attribute: str,
) -> str:
    return _document_sha256(
        [
            {
                "identity": str(getattr(result, identity_attribute)),
                "content_sha256": str(getattr(result, sha_attribute)),
            }
            for result in results
        ]
    )


def _write_package_plan(
    plan: ChongqingDataPackageReconciliationPlan,
    *,
    temporal_authority: Any,
    link_authority: Any,
    batch_size: int,
    progress_label: str,
    progress_offset: int,
    progress_total: int,
    progress_callback: ReconciliationProgressCallback | None,
    cancel_check: ReconciliationCancelCheck | None,
) -> _PackageWriteState:
    entity_results: list[Any] = []
    binding_results: list[Any] = []
    link_results: list[Any] = []
    batch_count = 0

    phases: tuple[_WritePhase, ...] = (
        (
            "link retractions",
            plan.link_plan.retraction_drafts,
            link_authority.record_links_batch,
            link_results,
        ),
        (
            "entity corrections",
            plan.entity_correction_drafts,
            temporal_authority.record_batch,
            entity_results,
        ),
        (
            "entity additions",
            plan.entity_addition_drafts,
            temporal_authority.record_batch,
            entity_results,
        ),
        (
            "entity activations",
            plan.entity_activation_drafts,
            temporal_authority.record_batch,
            entity_results,
        ),
        (
            "source binding updates",
            plan.source_binding_drafts,
            link_authority.bind_sources_batch,
            binding_results,
        ),
        (
            "link corrections",
            plan.link_plan.correction_drafts,
            link_authority.record_links_batch,
            link_results,
        ),
        (
            "link restorations",
            plan.link_plan.restoration_drafts,
            link_authority.record_links_batch,
            link_results,
        ),
        (
            "link additions",
            plan.link_plan.addition_drafts,
            link_authority.record_links_batch,
            link_results,
        ),
        (
            "entity retirements",
            plan.entity_retirement_drafts,
            temporal_authority.record_batch,
            entity_results,
        ),
    )
    for phase_name, drafts, operation, destination in phases:
        results, batches = _write_batches(
            phase_name=phase_name,
            drafts=drafts,
            operation=operation,
            batch_size=batch_size,
            progress_label=progress_label,
            progress_offset=progress_offset + batch_count,
            progress_total=progress_total,
            progress_callback=progress_callback,
            cancel_check=cancel_check,
        )
        destination.extend(results)
        batch_count += batches
    try:
        entity_state = _result_state(
            entity_results,
            identity_attribute="assertion_id",
            sha_attribute="assertion_sha256",
        )
        binding_state = _result_state(
            binding_results,
            identity_attribute="binding_id",
            sha_attribute="binding_sha256",
        )
        link_state = _result_state(
            link_results,
            identity_attribute="assertion_id",
            sha_attribute="assertion_sha256",
        )
        recorded_times = [
            *(result.recorded_at for result in entity_results),
            *(result.recorded_at for result in binding_results),
            *(result.recorded_at for result in link_results),
        ]
    except (AttributeError, TypeError, ValueError) as exc:
        raise ChongqingDataPackageReconciliationError(
            "an authority returned an invalid package reconciliation result"
        ) from exc
    authority_state = _document_sha256(
        {
            "entities": entity_state,
            "source_bindings": binding_state,
            "links": link_state,
        }
    )
    return _PackageWriteState(
        entity_results=tuple(entity_results),
        binding_results=tuple(binding_results),
        link_results=tuple(link_results),
        batch_count=batch_count,
        entity_state_sha256=entity_state,
        binding_state_sha256=binding_state,
        link_state_sha256=link_state,
        authority_state_sha256=authority_state,
        recorded_from=min(recorded_times) if recorded_times else None,
        recorded_through=max(recorded_times) if recorded_times else None,
    )


class _ChongqingDataPackageReconciliationReceiptBody(_FrozenContract):
    schema_id: Literal["gda.chongqing-data-package-reconciliation-receipt.v1"] = (
        "gda.chongqing-data-package-reconciliation-receipt.v1"
    )
    tenant_id: TenantId
    plan_sha256: Sha256
    effective_at: datetime
    previous_baseline_sha256: Sha256
    desired_baseline_sha256: Sha256
    entity_authority_input_sha256: Sha256
    source_authority_input_sha256: Sha256
    link_authority_input_sha256: Sha256
    ontology_review_status: Literal["technical_baseline_unreviewed"]
    usage_status: Literal["assisted_precheck_not_for_production_decision"]
    decision_scope: str
    replay_verification: Literal["not_requested", "passed"]
    write_mode: Literal["phased_chunked_atomic_authority_batches"] = (
        "phased_chunked_atomic_authority_batches"
    )
    atomicity_status: Literal["atomic_per_batch_resumable_across_phases"] = (
        "atomic_per_batch_resumable_across_phases"
    )
    batch_size: int = Field(ge=1, le=500)
    operation_count: int = Field(ge=0)
    batch_count: int = Field(ge=0)
    unchanged_entity_count: int = Field(ge=0)
    unchanged_source_count: int = Field(ge=0)
    retained_retired_source_count: int = Field(ge=0)
    entity_correction_count: int = Field(ge=0)
    entity_addition_count: int = Field(ge=0)
    entity_activation_count: int = Field(ge=0)
    source_binding_count: int = Field(ge=0)
    entity_retirement_count: int = Field(ge=0)
    link_operation_count: int = Field(ge=0)
    link_correction_count: int = Field(ge=0)
    link_retraction_count: int = Field(ge=0)
    link_restoration_count: int = Field(ge=0)
    link_addition_count: int = Field(ge=0)
    recorded_from: datetime | None
    recorded_through: datetime | None
    entity_state_sha256: Sha256
    source_binding_state_sha256: Sha256
    link_state_sha256: Sha256
    authority_state_sha256: Sha256

    @field_validator("effective_at", "recorded_from", "recorded_through")
    @classmethod
    def _times(cls, value: datetime | None, info) -> datetime | None:
        return None if value is None else _aware_utc(value, info.field_name)

    @model_validator(mode="after")
    def _consistent_receipt(self) -> _ChongqingDataPackageReconciliationReceiptBody:
        expected = (
            self.entity_correction_count
            + self.entity_addition_count
            + self.entity_activation_count
            + self.source_binding_count
            + self.entity_retirement_count
            + self.link_operation_count
        )
        if self.operation_count != expected:
            raise ValueError("package receipt operation count is inconsistent")
        expected_link_operations = (
            self.link_correction_count
            + self.link_retraction_count
            + self.link_restoration_count
            + self.link_addition_count
        )
        if self.link_operation_count != expected_link_operations:
            raise ValueError("package receipt Link operation count is inconsistent")
        phase_counts = (
            self.link_retraction_count,
            self.entity_correction_count,
            self.entity_addition_count,
            self.entity_activation_count,
            self.source_binding_count,
            self.link_correction_count,
            self.link_restoration_count,
            self.link_addition_count,
            self.entity_retirement_count,
        )
        expected_batches = sum(
            (count + self.batch_size - 1) // self.batch_size
            for count in phase_counts
            if count
        )
        if self.batch_count != expected_batches:
            raise ValueError("package receipt batch count is inconsistent")
        if (self.recorded_from is None) != (self.operation_count == 0):
            raise ValueError("package receipt recording window is inconsistent")
        if (self.recorded_through is None) != (self.operation_count == 0):
            raise ValueError("package receipt recording window is inconsistent")
        return self


class ChongqingDataPackageReconciliationReceipt(
    _ChongqingDataPackageReconciliationReceiptBody
):
    receipt_sha256: Sha256

    @model_validator(mode="after")
    def _valid_receipt_hash(self) -> ChongqingDataPackageReconciliationReceipt:
        expected = _document_sha256(
            self.model_dump(mode="json", exclude={"receipt_sha256"})
        )
        if self.receipt_sha256 != expected:
            raise ValueError("package reconciliation receipt SHA-256 is invalid")
        return self


def apply_chongqing_data_package_reconciliation_plan(
    plan: ChongqingDataPackageReconciliationPlan,
    *,
    engine: Any = None,
    temporal_authority: Any = None,
    link_authority: Any = None,
    batch_size: int = 250,
    verify_replay: bool = False,
    progress_callback: ReconciliationProgressCallback | None = None,
    cancel_check: ReconciliationCancelCheck | None = None,
) -> ChongqingDataPackageReconciliationReceipt:
    """Apply one sealed full-package plan through ordered authority phases."""
    if batch_size < 1 or batch_size > 500:
        raise ChongqingDataPackageReconciliationError("batch_size must be 1..500")
    try:
        plan = ChongqingDataPackageReconciliationPlan.model_validate(
            plan.model_dump(mode="python")
        )
    except (AttributeError, TypeError, ValueError) as exc:
        raise ChongqingDataPackageReconciliationError(
            "package reconciliation plan seal is invalid"
        ) from exc
    temporal_writer = temporal_authority or TemporalEntityAuthority(engine=engine)
    link_writer = link_authority or EntityLinkAuthority(engine=engine)
    batches_per_pass = chongqing_data_package_reconciliation_batch_count(
        plan,
        batch_size,
    )
    total_batches = batches_per_pass * (2 if verify_replay else 1)
    if cancel_check is not None:
        cancel_check()
    if progress_callback is not None and total_batches == 0:
        progress_callback("apply:no_changes", 0, 0)
    first = _write_package_plan(
        plan,
        temporal_authority=temporal_writer,
        link_authority=link_writer,
        batch_size=batch_size,
        progress_label="apply",
        progress_offset=0,
        progress_total=total_batches,
        progress_callback=progress_callback,
        cancel_check=cancel_check,
    )
    if verify_replay:
        replay = _write_package_plan(
            plan,
            temporal_authority=temporal_writer,
            link_authority=link_writer,
            batch_size=batch_size,
            progress_label="verify_replay",
            progress_offset=batches_per_pass,
            progress_total=total_batches,
            progress_callback=progress_callback,
            cancel_check=cancel_check,
        )
        if (
            replay.authority_state_sha256 != first.authority_state_sha256
            or replay.recorded_from != first.recorded_from
            or replay.recorded_through != first.recorded_through
        ):
            raise ChongqingDataPackageReconciliationError(
                "replayed package plan returned different authority state or times"
            )
    body = _ChongqingDataPackageReconciliationReceiptBody(
        tenant_id=plan.tenant_id,
        plan_sha256=plan.plan_sha256,
        effective_at=plan.effective_at,
        previous_baseline_sha256=plan.previous_baseline_sha256,
        desired_baseline_sha256=plan.desired_baseline_sha256,
        entity_authority_input_sha256=plan.entity_authority_input_sha256,
        source_authority_input_sha256=plan.source_authority_input_sha256,
        link_authority_input_sha256=plan.link_plan.authority_input_state_sha256,
        ontology_review_status=plan.ontology_review_status,
        usage_status=plan.usage_status,
        decision_scope=plan.decision_scope,
        replay_verification="passed" if verify_replay else "not_requested",
        batch_size=batch_size,
        operation_count=plan.operation_count,
        batch_count=first.batch_count,
        unchanged_entity_count=len(plan.unchanged_entity_refs),
        unchanged_source_count=len(plan.unchanged_source_identity_refs),
        retained_retired_source_count=len(
            plan.retained_retired_source_identity_refs
        ),
        entity_correction_count=len(plan.entity_correction_drafts),
        entity_addition_count=len(plan.entity_addition_drafts),
        entity_activation_count=len(plan.entity_activation_drafts),
        source_binding_count=len(plan.source_binding_drafts),
        entity_retirement_count=len(plan.entity_retirement_drafts),
        link_operation_count=plan.link_plan.operation_count,
        link_correction_count=len(plan.link_plan.correction_drafts),
        link_retraction_count=len(plan.link_plan.retraction_drafts),
        link_restoration_count=len(plan.link_plan.restoration_drafts),
        link_addition_count=len(plan.link_plan.addition_drafts),
        recorded_from=first.recorded_from,
        recorded_through=first.recorded_through,
        entity_state_sha256=first.entity_state_sha256,
        source_binding_state_sha256=first.binding_state_sha256,
        link_state_sha256=first.link_state_sha256,
        authority_state_sha256=first.authority_state_sha256,
    )
    return ChongqingDataPackageReconciliationReceipt(
        **body.model_dump(mode="python"),
        receipt_sha256=_document_sha256(body.model_dump(mode="json")),
    )


def plan_chongqing_data_package_reconciliation(
    *,
    previous_baseline: ChongqingEntityLinkBaseline,
    desired_baseline: ChongqingEntityLinkBaseline,
    effective_at: datetime,
    engine: Any = None,
    temporal_authority: Any = None,
    link_authority: Any = None,
    evaluated_at: datetime | None = None,
) -> ChongqingDataPackageReconciliationPlan:
    """Resolve authority state and seal all package deltas without writing."""
    effective_at = _aware_utc(effective_at, "effective_at")
    evaluated_at = _aware_utc(evaluated_at or datetime.now(UTC), "evaluated_at")
    temporal_writer = temporal_authority or TemporalEntityAuthority(engine=engine)
    link_writer = link_authority or EntityLinkAuthority(engine=engine)
    previous_entities = _entity_drafts(previous_baseline)
    desired_entities = _entity_drafts(desired_baseline)
    previous_sources = _source_drafts(previous_baseline)
    desired_sources = _source_drafts(desired_baseline)
    previous_links = {
        draft.link_ref: draft for draft in previous_baseline.link_assertion_drafts
    }
    desired_links = {
        draft.link_ref: draft for draft in desired_baseline.link_assertion_drafts
    }

    entity_assertions: dict[str, TemporalEntityAssertion | None] = {}
    for entity_ref in sorted(set(previous_entities) | set(desired_entities)):
        try:
            snapshot = temporal_writer.resolve(
                TemporalEntityQuery(
                    tenant_id=previous_baseline.tenant_id,
                    entity_ref=entity_ref,
                    mode=TemporalQueryMode.VALID_AT,
                    valid_at=effective_at,
                ),
                evaluated_at=evaluated_at,
            )
        except TemporalEntityNotFoundError:
            entity_assertions[entity_ref] = None
        else:
            entity_assertions[entity_ref] = snapshot.assertion

    source_bindings: dict[str, EntitySourceBinding | None] = {}
    for source_ref in sorted(set(previous_sources) | set(desired_sources)):
        try:
            binding = link_writer.resolve_source_binding(
                previous_baseline.tenant_id,
                source_ref,
                valid_at=effective_at,
                evaluated_at=evaluated_at,
            )
        except EntityLinkNotFoundError:
            source_bindings[source_ref] = None
        else:
            source_bindings[source_ref] = binding

    link_assertions: dict[str, InstanceLinkAssertion | None] = {}
    for link_ref in sorted(set(previous_links) | set(desired_links)):
        try:
            snapshot = link_writer.resolve(
                InstanceLinkQuery(
                    tenant_id=previous_baseline.tenant_id,
                    link_ref=link_ref,
                    mode=InstanceLinkQueryMode.VALID_AT,
                    valid_at=effective_at,
                ),
                evaluated_at=evaluated_at,
            )
        except EntityLinkNotFoundError:
            link_assertions[link_ref] = None
        else:
            link_assertions[link_ref] = snapshot.assertion

    return build_chongqing_data_package_reconciliation_plan(
        previous_baseline=previous_baseline,
        desired_baseline=desired_baseline,
        entity_assertions=entity_assertions,
        source_bindings=source_bindings,
        link_assertions=link_assertions,
        effective_at=effective_at,
    )


def reconcile_chongqing_data_package(
    *,
    previous_baseline: ChongqingEntityLinkBaseline,
    desired_baseline: ChongqingEntityLinkBaseline,
    effective_at: datetime,
    engine: Any = None,
    temporal_authority: Any = None,
    link_authority: Any = None,
    evaluated_at: datetime | None = None,
    batch_size: int = 250,
    verify_replay: bool = False,
) -> tuple[
    ChongqingDataPackageReconciliationPlan,
    ChongqingDataPackageReconciliationReceipt,
]:
    """Resolve authority state, seal all package deltas, and apply them."""
    temporal_writer = temporal_authority or TemporalEntityAuthority(engine=engine)
    link_writer = link_authority or EntityLinkAuthority(engine=engine)
    plan = plan_chongqing_data_package_reconciliation(
        previous_baseline=previous_baseline,
        desired_baseline=desired_baseline,
        effective_at=effective_at,
        temporal_authority=temporal_writer,
        link_authority=link_writer,
        evaluated_at=evaluated_at,
    )
    receipt = apply_chongqing_data_package_reconciliation_plan(
        plan,
        temporal_authority=temporal_writer,
        link_authority=link_writer,
        batch_size=batch_size,
        verify_replay=verify_replay,
    )
    return plan, receipt
