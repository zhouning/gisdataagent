"""Contract tests for complete Chongqing data-package reconciliation."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from datetime import UTC, datetime, timedelta
from uuid import NAMESPACE_URL, uuid5

import pytest
from pydantic import ValidationError

from data_agent.chongqing_data_package_reconciliation import (
    ChongqingDataPackageReconciliationError,
    ChongqingDataPackageReconciliationPlan,
    ChongqingDataPackageReconciliationReceipt,
    apply_chongqing_data_package_reconciliation_plan,
    build_chongqing_data_package_reconciliation_plan,
)
from data_agent.chongqing_entity_link_baseline import (
    ChongqingEntityLinkBaseline,
    build_chongqing_entity_link_baseline,
)
from data_agent.entity_link_authority import (
    EntitySourceBinding,
    EntitySourceBindingDraft,
    InstanceLinkAssertion,
    InstanceLinkAssertionDraft,
    InstanceLinkLifecycle,
    InstanceLinkMutationKind,
)
from data_agent.temporal_entity_authority import (
    TemporalEntityAssertion,
    TemporalEntityAssertionDraft,
    TemporalLifecycleState,
    TemporalMutationKind,
)

RECORDED_AT = datetime(2026, 8, 14, 20, tzinfo=UTC)


def _sha256(value) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _entity_assertion(
    draft: TemporalEntityAssertionDraft,
    *,
    lifecycle_state: TemporalLifecycleState | None = None,
    mutation_kind: TemporalMutationKind | None = None,
    valid_from: datetime | None = None,
    token: str | None = None,
) -> TemporalEntityAssertion:
    values = draft.model_dump(mode="python")
    values.update(
        {
            "lifecycle_state": lifecycle_state or draft.lifecycle_state,
            "mutation_kind": mutation_kind or draft.mutation_kind,
            "valid_from": valid_from or draft.valid_from,
            "supersedes_assertion_id": None,
            "idempotency_key": f"test.entity.{token or draft.idempotency_key[-64:]}",
        }
    )
    document = TemporalEntityAssertionDraft(**values)
    return TemporalEntityAssertion(
        **document.model_dump(mode="python"),
        assertion_id=uuid5(NAMESPACE_URL, f"entity:{document.idempotency_key}"),
        assertion_sha256=_sha256(document.model_dump(mode="json")),
        recorded_at=RECORDED_AT,
    )


def _source_binding(draft: EntitySourceBindingDraft) -> EntitySourceBinding:
    return EntitySourceBinding(
        **draft.model_dump(mode="python"),
        binding_id=uuid5(NAMESPACE_URL, f"source:{draft.idempotency_key}"),
        binding_sha256=_sha256(draft.model_dump(mode="json")),
        recorded_at=RECORDED_AT,
    )


def _link_assertion(
    draft: InstanceLinkAssertionDraft,
    *,
    lifecycle_state: InstanceLinkLifecycle | None = None,
    mutation_kind: InstanceLinkMutationKind | None = None,
    valid_from: datetime | None = None,
    token: str | None = None,
) -> InstanceLinkAssertion:
    values = draft.model_dump(mode="python")
    values.update(
        {
            "lifecycle_state": lifecycle_state or draft.lifecycle_state,
            "mutation_kind": mutation_kind or draft.mutation_kind,
            "valid_from": valid_from or draft.valid_from,
            "supersedes_assertion_id": None,
            "idempotency_key": f"test.link.{token or draft.idempotency_key[-64:]}",
        }
    )
    document = InstanceLinkAssertionDraft(**values)
    return InstanceLinkAssertion(
        **document.model_dump(mode="python"),
        assertion_id=uuid5(NAMESPACE_URL, f"link:{document.idempotency_key}"),
        assertion_sha256=_sha256(document.model_dump(mode="json")),
        recorded_at=RECORDED_AT,
    )


class _FakeTemporalAuthority:
    def __init__(self, events: list[tuple[str, ...]]) -> None:
        self.events = events
        self.results: dict[str, TemporalEntityAssertion] = {}

    def record_batch(self, drafts):
        results = []
        for draft in tuple(drafts):
            self.events.append(
                (
                    "entity",
                    draft.entity_ref,
                    draft.mutation_kind.value,
                    draft.lifecycle_state.value,
                )
            )
            existing = self.results.get(draft.idempotency_key)
            if existing is None:
                existing = TemporalEntityAssertion(
                    **draft.model_dump(mode="python"),
                    assertion_id=uuid5(
                        NAMESPACE_URL,
                        f"written-entity:{draft.idempotency_key}",
                    ),
                    assertion_sha256=_sha256(draft.model_dump(mode="json")),
                    recorded_at=RECORDED_AT
                    + timedelta(microseconds=len(self.results)),
                )
                self.results[draft.idempotency_key] = existing
            results.append(existing)
        return tuple(results)


class _FakeLinkAuthority:
    def __init__(self, events: list[tuple[str, ...]]) -> None:
        self.events = events
        self.binding_results: dict[str, EntitySourceBinding] = {}
        self.link_results: dict[str, InstanceLinkAssertion] = {}

    def bind_sources_batch(self, drafts):
        results = []
        for draft in tuple(drafts):
            self.events.append(
                ("source", draft.source_identity_ref, draft.source_version_ref)
            )
            existing = self.binding_results.get(draft.idempotency_key)
            if existing is None:
                existing = EntitySourceBinding(
                    **draft.model_dump(mode="python"),
                    binding_id=uuid5(
                        NAMESPACE_URL,
                        f"written-source:{draft.idempotency_key}",
                    ),
                    binding_sha256=_sha256(draft.model_dump(mode="json")),
                    recorded_at=RECORDED_AT
                    + timedelta(microseconds=len(self.binding_results)),
                )
                self.binding_results[draft.idempotency_key] = existing
            results.append(existing)
        return tuple(results)

    def record_links_batch(self, drafts):
        results = []
        for draft in tuple(drafts):
            self.events.append(
                (
                    "link",
                    draft.link_ref,
                    draft.mutation_kind.value,
                    draft.lifecycle_state.value,
                )
            )
            existing = self.link_results.get(draft.idempotency_key)
            if existing is None:
                existing = InstanceLinkAssertion(
                    **draft.model_dump(mode="python"),
                    assertion_id=uuid5(
                        NAMESPACE_URL,
                        f"written-link:{draft.idempotency_key}",
                    ),
                    assertion_sha256=_sha256(draft.model_dump(mode="json")),
                    recorded_at=RECORDED_AT
                    + timedelta(microseconds=len(self.link_results)),
                )
                self.link_results[draft.idempotency_key] = existing
            results.append(existing)
        return tuple(results)


def _authority_state(baseline: ChongqingEntityLinkBaseline):
    entities = {
        draft.entity_ref: _entity_assertion(draft)
        for draft in baseline.temporal_entity_drafts
    }
    sources = {
        draft.source_identity_ref: _source_binding(draft)
        for draft in baseline.source_binding_drafts
    }
    links = {
        draft.link_ref: _link_assertion(draft)
        for draft in baseline.link_assertion_drafts
    }
    return entities, sources, links


def _changed_package():
    previous = build_chongqing_entity_link_baseline()
    effective_at = previous.link_assertion_drafts[0].valid_from + timedelta(days=1)
    link_counts = Counter(
        draft.source_entity_ref for draft in previous.link_assertion_drafts
    )
    retired_entity_ref = next(
        entity_ref for entity_ref, count in link_counts.items() if count == 1
    )
    retired_link = next(
        draft
        for draft in previous.link_assertion_drafts
        if draft.source_entity_ref == retired_entity_ref
    )
    retained_links = [
        draft
        for draft in previous.link_assertion_drafts
        if draft.link_ref != retired_link.link_ref
    ]
    correction_link = next(
        draft
        for draft in retained_links
        if draft.source_entity_ref != retired_entity_ref
    )
    restoration_link = next(
        draft
        for draft in retained_links
        if draft.link_ref != correction_link.link_ref
        and draft.source_entity_ref != correction_link.source_entity_ref
    )
    corrected_entity_ref = correction_link.source_entity_ref
    activated_entity_ref = restoration_link.source_entity_ref

    entity_by_ref = {
        draft.entity_ref: draft for draft in previous.temporal_entity_drafts
    }
    source_by_entity = {
        draft.entity_ref: draft for draft in previous.source_binding_drafts
    }
    corrected_entity = entity_by_ref[corrected_entity_ref]
    corrected_source = source_by_entity[corrected_entity_ref]
    source_version_v2 = (
        f"gda://{previous.tenant_id}/resource_version/customer-parcels-v2"
    )
    desired_corrected_entity = corrected_entity.model_copy(
        update={
            "attributes": {
                **corrected_entity.attributes,
                "package_recompute_revision": 2,
            },
            "source_version_refs": (source_version_v2,),
        }
    )
    desired_corrected_source = corrected_source.model_copy(
        update={
            "source_version_ref": source_version_v2,
            "evidence": {
                **corrected_source.evidence,
                "package_recompute_revision": 2,
            },
        }
    )

    new_entity_ref = f"gda://{previous.tenant_id}/entity/package-added-parcel"
    new_source_ref = (
        f"gda://{previous.tenant_id}/source_identity/package-added-parcel"
    )
    new_entity = corrected_entity.model_copy(
        update={
            "entity_ref": new_entity_ref,
            "attributes": {
                **corrected_entity.attributes,
                "parcel_id": "package-added-parcel",
                "package_recompute_revision": 2,
            },
            "source_version_refs": (source_version_v2,),
            "idempotency_key": "cq.package-added-parcel.initial",
        }
    )
    new_source = corrected_source.model_copy(
        update={
            "source_identity_ref": new_source_ref,
            "source_object_id": "package-added-parcel",
            "entity_ref": new_entity_ref,
            "source_version_ref": source_version_v2,
            "evidence": {
                **corrected_source.evidence,
                "package_recompute_revision": 2,
            },
            "idempotency_key": "cq.source.package-added-parcel.v1",
        }
    )
    corrected_link = correction_link.model_copy(
        update={
            "evidence": {
                **correction_link.evidence,
                "package_recompute_revision": 2,
            },
            "source_version_refs": tuple(
                sorted({*correction_link.source_version_refs, source_version_v2})
            ),
        }
    )
    new_link_ref = f"gda://{previous.tenant_id}/entity_link/package-added-link"
    new_link = correction_link.model_copy(
        update={
            "link_ref": new_link_ref,
            "source_entity_ref": new_entity_ref,
            "attributes": {
                **correction_link.attributes,
                "package_added": True,
            },
            "source_version_refs": tuple(
                sorted({*correction_link.source_version_refs, source_version_v2})
            ),
            "idempotency_key": "cq.link.package-added-link.initial",
        }
    )

    desired_entities = tuple(
        desired_corrected_entity
        if draft.entity_ref == corrected_entity_ref
        else draft
        for draft in previous.temporal_entity_drafts
        if draft.entity_ref != retired_entity_ref
    ) + (new_entity,)
    retired_source_ref = source_by_entity[retired_entity_ref].source_identity_ref
    desired_sources = tuple(
        desired_corrected_source
        if draft.source_identity_ref == corrected_source.source_identity_ref
        else draft
        for draft in previous.source_binding_drafts
        if draft.source_identity_ref != retired_source_ref
    ) + (new_source,)
    desired_links = tuple(
        corrected_link if draft.link_ref == correction_link.link_ref else draft
        for draft in retained_links
    ) + (new_link,)
    desired = previous.model_copy(
        update={
            "customer_bundle_version": "package-reconciliation-v2",
            "temporal_entity_drafts": desired_entities,
            "source_binding_drafts": desired_sources,
            "link_identity_count": len(desired_links),
            "link_assertion_drafts": desired_links,
        }
    )

    entities, sources, links = _authority_state(previous)
    entities[new_entity_ref] = None
    entities[activated_entity_ref] = _entity_assertion(
        entity_by_ref[activated_entity_ref],
        lifecycle_state=TemporalLifecycleState.SUSPENDED,
        mutation_kind=TemporalMutationKind.TRANSITION,
        valid_from=effective_at - timedelta(hours=1),
        token="suspended-before-package-reconciliation",
    )
    sources[new_source_ref] = None
    links[new_link_ref] = None
    links[restoration_link.link_ref] = _link_assertion(
        restoration_link,
        lifecycle_state=InstanceLinkLifecycle.RETRACTED,
        mutation_kind=InstanceLinkMutationKind.TRANSITION,
        valid_from=effective_at - timedelta(hours=1),
        token="retracted-before-package-reconciliation",
    )
    refs = {
        "retired_entity": retired_entity_ref,
        "retired_source": retired_source_ref,
        "retired_link": retired_link.link_ref,
        "corrected_entity": corrected_entity_ref,
        "activated_entity": activated_entity_ref,
        "new_entity": new_entity_ref,
        "new_source": new_source_ref,
        "new_link": new_link_ref,
        "corrected_link": correction_link.link_ref,
        "restored_link": restoration_link.link_ref,
    }
    return previous, desired, effective_at, entities, sources, links, refs


def test_plan_classifies_complete_package_delta_and_seals_inputs() -> None:
    previous, desired, effective_at, entities, sources, links, refs = (
        _changed_package()
    )

    plan = build_chongqing_data_package_reconciliation_plan(
        previous_baseline=previous,
        desired_baseline=desired,
        entity_assertions=entities,
        source_bindings=sources,
        link_assertions=links,
        effective_at=effective_at,
    )

    assert plan.operation_count == 10
    assert [draft.entity_ref for draft in plan.entity_correction_drafts] == [
        refs["corrected_entity"]
    ]
    assert [draft.entity_ref for draft in plan.entity_addition_drafts] == [
        refs["new_entity"]
    ]
    assert [draft.entity_ref for draft in plan.entity_activation_drafts] == [
        refs["activated_entity"]
    ]
    assert [draft.entity_ref for draft in plan.entity_retirement_drafts] == [
        refs["retired_entity"]
    ]
    assert len(plan.source_binding_drafts) == 2
    assert plan.retained_retired_source_identity_refs == (refs["retired_source"],)
    assert len(plan.link_plan.correction_drafts) == 1
    assert len(plan.link_plan.retraction_drafts) == 1
    assert len(plan.link_plan.restoration_drafts) == 1
    assert len(plan.link_plan.addition_drafts) == 1
    assert plan.link_plan.retraction_drafts[0].link_ref == refs["retired_link"]
    assert all(
        len(value) == 64
        for value in (
            plan.plan_sha256,
            plan.previous_baseline_sha256,
            plan.desired_baseline_sha256,
            plan.entity_authority_input_sha256,
            plan.source_authority_input_sha256,
            plan.link_plan.authority_input_state_sha256,
        )
    )


def test_apply_orders_all_phases_and_complete_replay_is_idempotent() -> None:
    previous, desired, effective_at, entities, sources, links, refs = (
        _changed_package()
    )
    plan = build_chongqing_data_package_reconciliation_plan(
        previous_baseline=previous,
        desired_baseline=desired,
        entity_assertions=entities,
        source_bindings=sources,
        link_assertions=links,
        effective_at=effective_at,
    )
    events: list[tuple[str, ...]] = []
    temporal_authority = _FakeTemporalAuthority(events)
    link_authority = _FakeLinkAuthority(events)

    receipt = apply_chongqing_data_package_reconciliation_plan(
        plan,
        temporal_authority=temporal_authority,
        link_authority=link_authority,
        batch_size=1,
        verify_replay=True,
    )

    assert receipt.operation_count == 10
    assert receipt.batch_count == 10
    assert receipt.replay_verification == "passed"
    assert receipt.entity_correction_count == 1
    assert receipt.entity_addition_count == 1
    assert receipt.entity_activation_count == 1
    assert receipt.source_binding_count == 2
    assert receipt.entity_retirement_count == 1
    assert receipt.link_correction_count == 1
    assert receipt.link_retraction_count == 1
    assert receipt.link_restoration_count == 1
    assert receipt.link_addition_count == 1
    assert receipt.previous_baseline_sha256 == plan.previous_baseline_sha256
    assert receipt.desired_baseline_sha256 == plan.desired_baseline_sha256
    first_pass = events[:10]
    assert events[10:] == first_pass
    assert first_pass[0][0:2] == ("link", refs["retired_link"])
    assert first_pass[1][0:2] == ("entity", refs["corrected_entity"])
    assert first_pass[2][0:2] == ("entity", refs["new_entity"])
    assert first_pass[3][0:2] == ("entity", refs["activated_entity"])
    assert [event[0] for event in first_pass[4:6]] == ["source", "source"]
    assert first_pass[6][0:2] == ("link", refs["corrected_link"])
    assert first_pass[7][0:2] == ("link", refs["restored_link"])
    assert first_pass[8][0:2] == ("link", refs["new_link"])
    assert first_pass[9][0:2] == ("entity", refs["retired_entity"])
    assert len(temporal_authority.results) == 4
    assert len(link_authority.binding_results) == 2
    assert len(link_authority.link_results) == 4

    forged_receipt = receipt.model_dump(mode="python")
    forged_receipt["batch_count"] += 1
    with pytest.raises(ValidationError, match="batch count"):
        ChongqingDataPackageReconciliationReceipt.model_validate(forged_receipt)


def test_unchanged_package_produces_a_sealed_zero_write_receipt() -> None:
    baseline = build_chongqing_entity_link_baseline()
    entities, sources, links = _authority_state(baseline)
    effective_at = baseline.link_assertion_drafts[0].valid_from + timedelta(days=1)
    plan = build_chongqing_data_package_reconciliation_plan(
        previous_baseline=baseline,
        desired_baseline=baseline,
        entity_assertions=entities,
        source_bindings=sources,
        link_assertions=links,
        effective_at=effective_at,
    )
    events: list[tuple[str, ...]] = []

    receipt = apply_chongqing_data_package_reconciliation_plan(
        plan,
        temporal_authority=_FakeTemporalAuthority(events),
        link_authority=_FakeLinkAuthority(events),
        verify_replay=True,
    )

    assert plan.operation_count == 0
    assert receipt.operation_count == 0
    assert receipt.batch_count == 0
    assert receipt.recorded_from is None
    assert receipt.recorded_through is None
    assert events == []


def test_draft_entity_is_activated_with_a_lifecycle_transition() -> None:
    baseline = build_chongqing_entity_link_baseline()
    entities, sources, links = _authority_state(baseline)
    entity = baseline.temporal_entity_drafts[0]
    entities[entity.entity_ref] = _entity_assertion(
        entity,
        lifecycle_state=TemporalLifecycleState.DRAFT,
        token="draft-before-package-reconciliation",
    )

    plan = build_chongqing_data_package_reconciliation_plan(
        previous_baseline=baseline,
        desired_baseline=baseline,
        entity_assertions=entities,
        source_bindings=sources,
        link_assertions=links,
        effective_at=entity.valid_from + timedelta(days=1),
    )

    assert len(plan.entity_activation_drafts) == 1
    activation = plan.entity_activation_drafts[0]
    assert activation.entity_ref == entity.entity_ref
    assert activation.mutation_kind is TemporalMutationKind.TRANSITION
    assert activation.lifecycle_state is TemporalLifecycleState.ACTIVE


def test_plan_and_receipt_seals_reject_tampering_before_writes() -> None:
    previous, desired, effective_at, entities, sources, links, _ = (
        _changed_package()
    )
    plan = build_chongqing_data_package_reconciliation_plan(
        previous_baseline=previous,
        desired_baseline=desired,
        entity_assertions=entities,
        source_bindings=sources,
        link_assertions=links,
        effective_at=effective_at,
    )
    forged = plan.model_copy(update={"operation_count": plan.operation_count - 1})
    events: list[tuple[str, ...]] = []

    with pytest.raises(
        ChongqingDataPackageReconciliationError,
        match="plan seal is invalid",
    ):
        apply_chongqing_data_package_reconciliation_plan(
            forged,
            temporal_authority=_FakeTemporalAuthority(events),
            link_authority=_FakeLinkAuthority(events),
        )
    assert events == []

    document = plan.model_dump(mode="python")
    document["desired_customer_bundle_version"] = "forged-version"
    with pytest.raises(ValidationError, match="plan SHA-256"):
        ChongqingDataPackageReconciliationPlan.model_validate(document)


def test_source_semantic_changes_and_terminal_reappearance_fail_closed() -> None:
    baseline = build_chongqing_entity_link_baseline()
    effective_at = baseline.link_assertion_drafts[0].valid_from + timedelta(days=1)
    entities, sources, links = _authority_state(baseline)
    source = baseline.source_binding_drafts[0]
    changed_source = source.model_copy(
        update={"entity_ref": baseline.temporal_entity_drafts[1].entity_ref}
    )
    desired = baseline.model_copy(
        update={
            "customer_bundle_version": "changed-source-semantics",
            "source_binding_drafts": (
                changed_source,
                *baseline.source_binding_drafts[1:],
            ),
        }
    )
    with pytest.raises(
        ChongqingDataPackageReconciliationError,
        match="source identity semantics changed",
    ):
        build_chongqing_data_package_reconciliation_plan(
            previous_baseline=baseline,
            desired_baseline=desired,
            entity_assertions=entities,
            source_bindings=sources,
            link_assertions=links,
            effective_at=effective_at,
        )

    entity = baseline.temporal_entity_drafts[0]
    entities[entity.entity_ref] = _entity_assertion(
        entity,
        lifecycle_state=TemporalLifecycleState.RETIRED,
        mutation_kind=TemporalMutationKind.TRANSITION,
        valid_from=effective_at - timedelta(hours=1),
        token="already-retired",
    )
    with pytest.raises(
        ChongqingDataPackageReconciliationError,
        match="terminal entity cannot reappear",
    ):
        build_chongqing_data_package_reconciliation_plan(
            previous_baseline=baseline,
            desired_baseline=baseline,
            entity_assertions=entities,
            source_bindings=sources,
            link_assertions=links,
            effective_at=effective_at,
        )


def test_source_natural_key_and_stable_entity_type_require_lineage() -> None:
    baseline = build_chongqing_entity_link_baseline()
    effective_at = baseline.link_assertion_drafts[0].valid_from + timedelta(days=1)
    entities, sources, links = _authority_state(baseline)
    source = baseline.source_binding_drafts[0]
    moved_source_ref = (
        f"gda://{baseline.tenant_id}/source_identity/moved-natural-key"
    )
    moved_source = source.model_copy(
        update={
            "source_identity_ref": moved_source_ref,
            "idempotency_key": "cq.source.moved-natural-key.v1",
        }
    )
    desired_sources = (moved_source, *baseline.source_binding_drafts[1:])
    desired = baseline.model_copy(
        update={
            "customer_bundle_version": "moved-natural-key",
            "source_binding_drafts": desired_sources,
        }
    )
    source_state = {**sources, moved_source_ref: None}
    with pytest.raises(
        ChongqingDataPackageReconciliationError,
        match="natural key moved",
    ):
        build_chongqing_data_package_reconciliation_plan(
            previous_baseline=baseline,
            desired_baseline=desired,
            entity_assertions=entities,
            source_bindings=source_state,
            link_assertions=links,
            effective_at=effective_at,
        )

    entity = baseline.temporal_entity_drafts[0]
    changed_entity = entity.model_copy(
        update={"object_type": "natural_resource.changed_land_parcel"}
    )
    desired = baseline.model_copy(
        update={
            "customer_bundle_version": "changed-entity-type",
            "temporal_entity_drafts": (
                changed_entity,
                *baseline.temporal_entity_drafts[1:],
            ),
        }
    )
    with pytest.raises(
        ChongqingDataPackageReconciliationError,
        match="stable entity type or owner changed",
    ):
        build_chongqing_data_package_reconciliation_plan(
            previous_baseline=baseline,
            desired_baseline=desired,
            entity_assertions=entities,
            source_bindings=sources,
            link_assertions=links,
            effective_at=effective_at,
        )
