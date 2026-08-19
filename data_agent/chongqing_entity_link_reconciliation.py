"""Append-only reconciliation of two Chongqing exact-Link baselines.

This slice deliberately reconciles relations only. Endpoint identities and Link
type semantics must remain stable; those changes belong to entity migration and
are rejected before any authority write occurs.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .chongqing_entity_link_baseline import ChongqingEntityLinkBaseline
from .entity_link_authority import (
    EntityLinkAuthority,
    EntityLinkNotFoundError,
    InstanceLinkAssertion,
    InstanceLinkAssertionDraft,
    InstanceLinkLifecycle,
    InstanceLinkMutationKind,
    InstanceLinkQuery,
    InstanceLinkQueryMode,
)
from .platform_contracts import Sha256, TenantId


class ChongqingLinkReconciliationError(RuntimeError):
    """The Link delta is unsafe, inconsistent, or could not be applied."""


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
    action: str,
    *,
    link_ref: str,
    authority_assertion_sha256: str | None,
    desired_sha256: str | None,
    effective_at: datetime,
) -> str:
    digest = _document_sha256(
        {
            "action": action,
            "link_ref": link_ref,
            "authority_assertion_sha256": authority_assertion_sha256,
            "desired_sha256": desired_sha256,
            "effective_at": effective_at.isoformat(),
        }
    )
    return f"cq.link.reconcile.{action}.{digest[:32]}"


def _desired_state(document: InstanceLinkAssertionDraft | InstanceLinkAssertion) -> dict[str, Any]:
    return {
        "link_ref": document.link_ref,
        "link_type_ref": document.link_type_ref,
        "source_entity_ref": document.source_entity_ref,
        "target_entity_ref": document.target_entity_ref,
        "lifecycle_state": document.lifecycle_state.value,
        "attributes": document.attributes,
        "valid_to": (
            document.valid_to.isoformat() if document.valid_to is not None else None
        ),
        "source_version_refs": list(document.source_version_refs),
        "confidence_basis_points": document.confidence_basis_points,
        "evidence": document.evidence,
        "owner_subject": document.owner_subject,
    }


def _desired_state_sha256(
    document: InstanceLinkAssertionDraft | InstanceLinkAssertion,
) -> str:
    return _document_sha256(_desired_state(document))


def _link_drafts(
    baseline: ChongqingEntityLinkBaseline,
) -> dict[str, InstanceLinkAssertionDraft]:
    drafts = {draft.link_ref: draft for draft in baseline.link_assertion_drafts}
    if len(drafts) != len(baseline.link_assertion_drafts):
        raise ChongqingLinkReconciliationError(
            "a Chongqing baseline contains duplicate Link references"
        )
    if len(drafts) != baseline.link_identity_count:
        raise ChongqingLinkReconciliationError(
            "a Chongqing baseline Link count is inconsistent"
        )
    return drafts


def _entity_types(baseline: ChongqingEntityLinkBaseline) -> dict[str, str]:
    values = {
        draft.entity_ref: draft.object_type for draft in baseline.temporal_entity_drafts
    }
    if len(values) != len(baseline.temporal_entity_drafts):
        raise ChongqingLinkReconciliationError(
            "a Chongqing baseline contains duplicate entity references"
        )
    return values


def _validate_baseline_pair(
    previous: ChongqingEntityLinkBaseline,
    desired: ChongqingEntityLinkBaseline,
    *,
    effective_at: datetime,
    allow_entity_identity_changes: bool = False,
) -> tuple[
    dict[str, InstanceLinkAssertionDraft],
    dict[str, InstanceLinkAssertionDraft],
]:
    if previous.tenant_id != desired.tenant_id:
        raise ChongqingLinkReconciliationError("baseline tenants do not match")
    fixed_fields = (
        "ontology_package_id",
        "ontology_package_sha256",
        "ontology_review_status",
        "usage_status",
        "decision_scope",
        "precision_policy",
    )
    if any(getattr(previous, name) != getattr(desired, name) for name in fixed_fields):
        raise ChongqingLinkReconciliationError(
            "baseline ontology, review, usage, or precision contract changed"
        )
    if previous.link_type_draft != desired.link_type_draft:
        raise ChongqingLinkReconciliationError(
            "Link type changes require a separately versioned migration"
        )
    previous_entity_types = _entity_types(previous)
    desired_entity_types = _entity_types(desired)
    if (
        not allow_entity_identity_changes
        and previous_entity_types != desired_entity_types
    ):
        raise ChongqingLinkReconciliationError(
            "entity identity changes require entity migration before Link reconciliation"
        )
    if any(
        previous_entity_types[entity_ref] != desired_entity_types[entity_ref]
        for entity_ref in previous_entity_types.keys() & desired_entity_types.keys()
    ):
        raise ChongqingLinkReconciliationError(
            "a stable entity reference changes object type"
        )
    previous_links = _link_drafts(previous)
    desired_links = _link_drafts(desired)
    for link_ref in previous_links.keys() & desired_links.keys():
        before = previous_links[link_ref]
        after = desired_links[link_ref]
        if (
            before.link_type_ref,
            before.source_entity_ref,
            before.target_entity_ref,
            before.owner_subject,
        ) != (
            after.link_type_ref,
            after.source_entity_ref,
            after.target_entity_ref,
            after.owner_subject,
        ):
            raise ChongqingLinkReconciliationError(
                "a stable Link reference changes identity or owner"
            )
    latest_initial = max(
        (
            draft.valid_from
            for draft in (*previous_links.values(), *desired_links.values())
        ),
        default=effective_at,
    )
    if effective_at <= latest_initial:
        raise ChongqingLinkReconciliationError(
            "effective_at must be later than all baseline initial events"
        )
    return previous_links, desired_links


class _ChongqingLinkReconciliationPlanBody(_FrozenContract):
    schema_id: Literal["gda.chongqing-link-reconciliation-plan.v1"] = (
        "gda.chongqing-link-reconciliation-plan.v1"
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
    authority_input_state_sha256: Sha256
    unchanged_link_refs: tuple[str, ...]
    correction_drafts: tuple[InstanceLinkAssertionDraft, ...]
    retraction_drafts: tuple[InstanceLinkAssertionDraft, ...]
    restoration_drafts: tuple[InstanceLinkAssertionDraft, ...]
    addition_drafts: tuple[InstanceLinkAssertionDraft, ...]
    operation_count: int = Field(ge=0)

    @field_validator("effective_at")
    @classmethod
    def _effective_time(cls, value: datetime) -> datetime:
        return _aware_utc(value, "effective_at")

    @model_validator(mode="after")
    def _consistent_plan(self) -> _ChongqingLinkReconciliationPlanBody:
        phases = (
            self.correction_drafts,
            self.retraction_drafts,
            self.restoration_drafts,
            self.addition_drafts,
        )
        expected = sum(len(items) for items in phases)
        if self.operation_count != expected:
            raise ValueError("reconciliation operation count is inconsistent")
        phase_refs = [draft.link_ref for items in phases for draft in items]
        all_refs = [*self.unchanged_link_refs, *phase_refs]
        if len(all_refs) != len(set(all_refs)):
            raise ValueError("a Link appears in multiple reconciliation outcomes")
        if self.unchanged_link_refs != tuple(sorted(self.unchanged_link_refs)):
            raise ValueError("unchanged Link references must be sorted")
        if any(
            tuple(draft.link_ref for draft in items)
            != tuple(sorted(draft.link_ref for draft in items))
            for items in phases
        ):
            raise ValueError("reconciliation phase drafts must be sorted")
        expected_mutations = (
            InstanceLinkMutationKind.CORRECTION,
            InstanceLinkMutationKind.TRANSITION,
            InstanceLinkMutationKind.TRANSITION,
            InstanceLinkMutationKind.INITIAL,
        )
        if any(
            any(draft.mutation_kind is not mutation for draft in items)
            for items, mutation in zip(phases, expected_mutations, strict=True)
        ):
            raise ValueError("reconciliation phase mutation kind is inconsistent")
        if any(
            draft.lifecycle_state is not InstanceLinkLifecycle.RETRACTED
            for draft in self.retraction_drafts
        ):
            raise ValueError("retraction phase contains an active Link")
        if any(
            draft.lifecycle_state is not InstanceLinkLifecycle.ACTIVE
            for items in (
                self.correction_drafts,
                self.restoration_drafts,
                self.addition_drafts,
            )
            for draft in items
        ):
            raise ValueError("an active reconciliation phase contains a retracted Link")
        return self


class ChongqingLinkReconciliationPlan(_ChongqingLinkReconciliationPlanBody):
    plan_sha256: Sha256

    @model_validator(mode="after")
    def _valid_plan_hash(self) -> ChongqingLinkReconciliationPlan:
        expected = _document_sha256(
            self.model_dump(mode="json", exclude={"plan_sha256"})
        )
        if self.plan_sha256 != expected:
            raise ValueError("reconciliation plan SHA-256 is invalid")
        return self


def _correction_draft(
    current: InstanceLinkAssertion,
    desired: InstanceLinkAssertionDraft,
    *,
    effective_at: datetime,
) -> InstanceLinkAssertionDraft:
    desired_sha256 = _desired_state_sha256(desired)
    return desired.model_copy(
        update={
            "valid_from": current.valid_from,
            "valid_to": current.valid_to,
            "lifecycle_state": current.lifecycle_state,
            "mutation_kind": InstanceLinkMutationKind.CORRECTION,
            "supersedes_assertion_id": current.assertion_id,
            "idempotency_key": _idempotency_key(
                "correct",
                link_ref=desired.link_ref,
                authority_assertion_sha256=current.assertion_sha256,
                desired_sha256=desired_sha256,
                effective_at=effective_at,
            ),
            "reason": "correct exact Link evidence from recomputed Chongqing baseline",
        }
    )


def _retraction_draft(
    current: InstanceLinkAssertion,
    *,
    previous_baseline_sha256: str,
    desired_baseline_sha256: str,
    effective_at: datetime,
) -> InstanceLinkAssertionDraft:
    evidence = {
        "evidence_kind": "chongqing_baseline_link_retraction",
        "previous_baseline_sha256": previous_baseline_sha256,
        "desired_baseline_sha256": desired_baseline_sha256,
        "previous_assertion_sha256": current.assertion_sha256,
        "previous_evidence_sha256": _document_sha256(current.evidence),
        "decision_scope": "辅助预审，不替代法定审批或行政决定",
    }
    return InstanceLinkAssertionDraft(
        tenant_id=current.tenant_id,
        link_ref=current.link_ref,
        link_type_ref=current.link_type_ref,
        source_entity_ref=current.source_entity_ref,
        target_entity_ref=current.target_entity_ref,
        lifecycle_state=InstanceLinkLifecycle.RETRACTED,
        attributes=current.attributes,
        valid_from=effective_at,
        valid_to=None,
        source_version_refs=current.source_version_refs,
        mutation_kind=InstanceLinkMutationKind.TRANSITION,
        confidence_basis_points=current.confidence_basis_points,
        evidence=evidence,
        idempotency_key=_idempotency_key(
            "retract",
            link_ref=current.link_ref,
            authority_assertion_sha256=current.assertion_sha256,
            desired_sha256=None,
            effective_at=effective_at,
        ),
        owner_subject=current.owner_subject,
        recorded_by=current.recorded_by,
        reason="retract exact Link absent from recomputed Chongqing baseline",
    )


def _active_transition_draft(
    current: InstanceLinkAssertion,
    desired: InstanceLinkAssertionDraft,
    *,
    effective_at: datetime,
) -> InstanceLinkAssertionDraft:
    return desired.model_copy(
        update={
            "valid_from": effective_at,
            "valid_to": None,
            "lifecycle_state": InstanceLinkLifecycle.ACTIVE,
            "mutation_kind": InstanceLinkMutationKind.TRANSITION,
            "supersedes_assertion_id": None,
            "idempotency_key": _idempotency_key(
                "restore",
                link_ref=desired.link_ref,
                authority_assertion_sha256=current.assertion_sha256,
                desired_sha256=_desired_state_sha256(desired),
                effective_at=effective_at,
            ),
            "reason": "restore exact Link present in recomputed Chongqing baseline",
        }
    )


def _addition_draft(
    desired: InstanceLinkAssertionDraft,
    *,
    effective_at: datetime,
) -> InstanceLinkAssertionDraft:
    return desired.model_copy(
        update={
            "valid_from": effective_at,
            "valid_to": None,
            "lifecycle_state": InstanceLinkLifecycle.ACTIVE,
            "mutation_kind": InstanceLinkMutationKind.INITIAL,
            "supersedes_assertion_id": None,
            "idempotency_key": _idempotency_key(
                "add",
                link_ref=desired.link_ref,
                authority_assertion_sha256=None,
                desired_sha256=_desired_state_sha256(desired),
                effective_at=effective_at,
            ),
            "reason": "add exact Link from recomputed Chongqing baseline",
        }
    )


def build_chongqing_link_reconciliation_plan(
    *,
    previous_baseline: ChongqingEntityLinkBaseline,
    desired_baseline: ChongqingEntityLinkBaseline,
    authority_assertions: Mapping[str, InstanceLinkAssertion | None],
    effective_at: datetime,
    allow_entity_identity_changes: bool = False,
) -> ChongqingLinkReconciliationPlan:
    """Build a sealed append-only Link delta without writing authority state."""
    effective_at = _aware_utc(effective_at, "effective_at")
    previous_links, desired_links = _validate_baseline_pair(
        previous_baseline,
        desired_baseline,
        effective_at=effective_at,
        allow_entity_identity_changes=allow_entity_identity_changes,
    )
    expected_refs = set(previous_links) | set(desired_links)
    if set(authority_assertions) != expected_refs:
        raise ChongqingLinkReconciliationError(
            "authority assertions must cover the union of baseline Link references"
        )

    for link_ref, current in authority_assertions.items():
        if current is None:
            continue
        if current.tenant_id != previous_baseline.tenant_id or current.link_ref != link_ref:
            raise ChongqingLinkReconciliationError(
                "authority assertion crosses tenant or Link identity"
            )
        expected_identity = previous_links.get(link_ref) or desired_links.get(link_ref)
        assert expected_identity is not None
        if (
            current.link_type_ref,
            current.source_entity_ref,
            current.target_entity_ref,
            current.owner_subject,
        ) != (
            expected_identity.link_type_ref,
            expected_identity.source_entity_ref,
            expected_identity.target_entity_ref,
            expected_identity.owner_subject,
        ):
            raise ChongqingLinkReconciliationError(
                "authority assertion does not match the baseline Link identity"
            )

    previous_sha256 = _model_sha256(previous_baseline)
    desired_sha256 = _model_sha256(desired_baseline)
    authority_state_sha256 = _document_sha256(
        {
            link_ref: (
                None
                if assertion is None
                else {
                    "assertion_id": str(assertion.assertion_id),
                    "assertion_sha256": assertion.assertion_sha256,
                    "lifecycle_state": assertion.lifecycle_state.value,
                    "desired_state_sha256": _desired_state_sha256(assertion),
                }
            )
            for link_ref, assertion in sorted(authority_assertions.items())
        }
    )

    unchanged: list[str] = []
    corrections: list[InstanceLinkAssertionDraft] = []
    retractions: list[InstanceLinkAssertionDraft] = []
    restorations: list[InstanceLinkAssertionDraft] = []
    additions: list[InstanceLinkAssertionDraft] = []
    for link_ref in sorted(expected_refs):
        before = previous_links.get(link_ref)
        desired = desired_links.get(link_ref)
        current = authority_assertions[link_ref]
        if desired is None:
            if current is None:
                raise ChongqingLinkReconciliationError(
                    "a previous baseline Link is absent from authority"
                )
            if current.lifecycle_state is InstanceLinkLifecycle.RETRACTED:
                unchanged.append(link_ref)
            else:
                retractions.append(
                    _retraction_draft(
                        current,
                        previous_baseline_sha256=previous_sha256,
                        desired_baseline_sha256=desired_sha256,
                        effective_at=effective_at,
                    )
                )
            continue

        if current is None:
            if before is not None:
                raise ChongqingLinkReconciliationError(
                    "a retained baseline Link is absent from authority"
                )
            additions.append(_addition_draft(desired, effective_at=effective_at))
            continue

        if current.lifecycle_state is InstanceLinkLifecycle.RETRACTED:
            restorations.append(
                _active_transition_draft(
                    current,
                    desired,
                    effective_at=effective_at,
                )
            )
        elif _desired_state_sha256(current) == _desired_state_sha256(desired):
            unchanged.append(link_ref)
        else:
            corrections.append(
                _correction_draft(
                    current,
                    desired,
                    effective_at=effective_at,
                )
            )

    body = _ChongqingLinkReconciliationPlanBody(
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
        authority_input_state_sha256=authority_state_sha256,
        unchanged_link_refs=tuple(unchanged),
        correction_drafts=tuple(corrections),
        retraction_drafts=tuple(retractions),
        restoration_drafts=tuple(restorations),
        addition_drafts=tuple(additions),
        operation_count=(
            len(corrections) + len(retractions) + len(restorations) + len(additions)
        ),
    )
    return ChongqingLinkReconciliationPlan(
        **body.model_dump(mode="python"),
        plan_sha256=_document_sha256(body.model_dump(mode="json")),
    )


@dataclass(frozen=True)
class _WriteState:
    assertions: tuple[InstanceLinkAssertion, ...]
    batch_count: int
    assertion_state_sha256: str
    recorded_from: datetime | None
    recorded_through: datetime | None


def _write_plan(
    plan: ChongqingLinkReconciliationPlan,
    *,
    link_authority: Any,
    batch_size: int,
) -> _WriteState:
    results: list[InstanceLinkAssertion] = []
    batch_count = 0
    phases: tuple[tuple[str, Sequence[InstanceLinkAssertionDraft]], ...] = (
        ("retractions", plan.retraction_drafts),
        ("corrections", plan.correction_drafts),
        ("restorations", plan.restoration_drafts),
        ("additions", plan.addition_drafts),
    )
    for phase_name, drafts in phases:
        for offset in range(0, len(drafts), batch_size):
            batch = tuple(drafts[offset : offset + batch_size])
            batch_count += 1
            try:
                written = tuple(link_authority.record_links_batch(batch))
            except Exception as exc:
                raise ChongqingLinkReconciliationError(
                    f"{phase_name} batch {batch_count} failed; earlier batches remain "
                    "committed and the sealed plan is safe to replay"
                ) from exc
            if len(written) != len(batch):
                raise ChongqingLinkReconciliationError(
                    f"{phase_name} batch returned {len(written)} results for "
                    f"{len(batch)} drafts"
                )
            results.extend(written)
    try:
        state_sha256 = _document_sha256(
            [
                {
                    "assertion_id": str(result.assertion_id),
                    "assertion_sha256": result.assertion_sha256,
                }
                for result in results
            ]
        )
        recorded_times = [result.recorded_at for result in results]
    except (AttributeError, TypeError, ValueError) as exc:
        raise ChongqingLinkReconciliationError(
            "Link authority returned an invalid reconciliation result"
        ) from exc
    return _WriteState(
        assertions=tuple(results),
        batch_count=batch_count,
        assertion_state_sha256=state_sha256,
        recorded_from=min(recorded_times) if recorded_times else None,
        recorded_through=max(recorded_times) if recorded_times else None,
    )


class _ChongqingLinkReconciliationReceiptBody(_FrozenContract):
    schema_id: Literal["gda.chongqing-link-reconciliation-receipt.v1"] = (
        "gda.chongqing-link-reconciliation-receipt.v1"
    )
    tenant_id: TenantId
    plan_sha256: Sha256
    effective_at: datetime
    ontology_review_status: Literal["technical_baseline_unreviewed"]
    usage_status: Literal["assisted_precheck_not_for_production_decision"]
    decision_scope: str
    replay_verification: Literal["not_requested", "passed"]
    batch_size: int = Field(ge=1, le=500)
    operation_count: int = Field(ge=0)
    batch_count: int = Field(ge=0)
    unchanged_count: int = Field(ge=0)
    correction_count: int = Field(ge=0)
    retraction_count: int = Field(ge=0)
    restoration_count: int = Field(ge=0)
    addition_count: int = Field(ge=0)
    recorded_from: datetime | None
    recorded_through: datetime | None
    assertion_state_sha256: Sha256

    @field_validator("effective_at", "recorded_from", "recorded_through")
    @classmethod
    def _times(cls, value: datetime | None, info) -> datetime | None:
        return None if value is None else _aware_utc(value, info.field_name)

    @model_validator(mode="after")
    def _consistent_receipt(self) -> _ChongqingLinkReconciliationReceiptBody:
        expected_operations = (
            self.correction_count
            + self.retraction_count
            + self.restoration_count
            + self.addition_count
        )
        if self.operation_count != expected_operations:
            raise ValueError("reconciliation receipt operation count is inconsistent")
        expected_batches = sum(
            (count + self.batch_size - 1) // self.batch_size
            for count in (
                self.retraction_count,
                self.correction_count,
                self.restoration_count,
                self.addition_count,
            )
            if count
        )
        if self.batch_count != expected_batches:
            raise ValueError("reconciliation receipt batch count is inconsistent")
        if (self.recorded_from is None) != (self.operation_count == 0):
            raise ValueError("reconciliation receipt recording window is inconsistent")
        if (self.recorded_through is None) != (self.operation_count == 0):
            raise ValueError("reconciliation receipt recording window is inconsistent")
        if (
            self.recorded_from is not None
            and self.recorded_through is not None
            and self.recorded_through < self.recorded_from
        ):
            raise ValueError("reconciliation recording window is inverted")
        return self


class ChongqingLinkReconciliationReceipt(_ChongqingLinkReconciliationReceiptBody):
    receipt_sha256: Sha256

    @model_validator(mode="after")
    def _valid_receipt_hash(self) -> ChongqingLinkReconciliationReceipt:
        expected = _document_sha256(
            self.model_dump(mode="json", exclude={"receipt_sha256"})
        )
        if self.receipt_sha256 != expected:
            raise ValueError("reconciliation receipt SHA-256 is invalid")
        return self


def apply_chongqing_link_reconciliation_plan(
    plan: ChongqingLinkReconciliationPlan,
    *,
    engine: Any = None,
    link_authority: Any = None,
    batch_size: int = 250,
    verify_replay: bool = False,
) -> ChongqingLinkReconciliationReceipt:
    """Apply one sealed relation-only plan through bounded authority batches."""
    if batch_size < 1 or batch_size > 500:
        raise ChongqingLinkReconciliationError("batch_size must be 1..500")
    writer = link_authority or EntityLinkAuthority(engine=engine)
    first = _write_plan(plan, link_authority=writer, batch_size=batch_size)
    if verify_replay:
        replay = _write_plan(plan, link_authority=writer, batch_size=batch_size)
        if (
            replay.assertion_state_sha256 != first.assertion_state_sha256
            or replay.recorded_from != first.recorded_from
            or replay.recorded_through != first.recorded_through
        ):
            raise ChongqingLinkReconciliationError(
                "replayed plan returned different authority identities, content, or times"
            )
    body = _ChongqingLinkReconciliationReceiptBody(
        tenant_id=plan.tenant_id,
        plan_sha256=plan.plan_sha256,
        effective_at=plan.effective_at,
        ontology_review_status=plan.ontology_review_status,
        usage_status=plan.usage_status,
        decision_scope=plan.decision_scope,
        replay_verification="passed" if verify_replay else "not_requested",
        batch_size=batch_size,
        operation_count=plan.operation_count,
        batch_count=first.batch_count,
        unchanged_count=len(plan.unchanged_link_refs),
        correction_count=len(plan.correction_drafts),
        retraction_count=len(plan.retraction_drafts),
        restoration_count=len(plan.restoration_drafts),
        addition_count=len(plan.addition_drafts),
        recorded_from=first.recorded_from,
        recorded_through=first.recorded_through,
        assertion_state_sha256=first.assertion_state_sha256,
    )
    return ChongqingLinkReconciliationReceipt(
        **body.model_dump(mode="python"),
        receipt_sha256=_document_sha256(body.model_dump(mode="json")),
    )


def reconcile_chongqing_entity_links(
    *,
    previous_baseline: ChongqingEntityLinkBaseline,
    desired_baseline: ChongqingEntityLinkBaseline,
    effective_at: datetime,
    engine: Any = None,
    link_authority: Any = None,
    evaluated_at: datetime | None = None,
    batch_size: int = 250,
    verify_replay: bool = False,
) -> tuple[ChongqingLinkReconciliationPlan, ChongqingLinkReconciliationReceipt]:
    """Resolve authority state, seal the delta, and apply it append-only."""
    writer = link_authority or EntityLinkAuthority(engine=engine)
    previous_links, desired_links = _validate_baseline_pair(
        previous_baseline,
        desired_baseline,
        effective_at=_aware_utc(effective_at, "effective_at"),
    )
    evaluated_at = _aware_utc(evaluated_at or datetime.now(UTC), "evaluated_at")
    authority_assertions: dict[str, InstanceLinkAssertion | None] = {}
    for link_ref in sorted(set(previous_links) | set(desired_links)):
        try:
            snapshot = writer.resolve(
                InstanceLinkQuery(
                    tenant_id=previous_baseline.tenant_id,
                    link_ref=link_ref,
                    mode=InstanceLinkQueryMode.VALID_AT,
                    valid_at=effective_at,
                ),
                evaluated_at=evaluated_at,
            )
        except EntityLinkNotFoundError:
            authority_assertions[link_ref] = None
        else:
            authority_assertions[link_ref] = snapshot.assertion
    plan = build_chongqing_link_reconciliation_plan(
        previous_baseline=previous_baseline,
        desired_baseline=desired_baseline,
        authority_assertions=authority_assertions,
        effective_at=effective_at,
    )
    receipt = apply_chongqing_link_reconciliation_plan(
        plan,
        link_authority=writer,
        batch_size=batch_size,
        verify_replay=verify_replay,
    )
    return plan, receipt
