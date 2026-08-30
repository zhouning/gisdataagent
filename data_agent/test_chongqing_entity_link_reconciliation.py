"""Contract tests for append-only Chongqing exact-Link reconciliation."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from uuid import NAMESPACE_URL, uuid5

import pytest
from pydantic import ValidationError

from data_agent.chongqing_entity_link_baseline import (
    ChongqingEntityLinkBaseline,
    build_chongqing_entity_link_baseline,
)
from data_agent.chongqing_entity_link_reconciliation import (
    ChongqingLinkReconciliationError,
    ChongqingLinkReconciliationPlan,
    apply_chongqing_link_reconciliation_plan,
    build_chongqing_link_reconciliation_plan,
)
from data_agent.entity_link_authority import (
    InstanceLinkAssertion,
    InstanceLinkAssertionDraft,
    InstanceLinkLifecycle,
    InstanceLinkMutationKind,
)

RECORDED_AT = datetime(2026, 8, 14, 18, tzinfo=UTC)


def _sha256(value) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _assertion(
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
            "idempotency_key": f"test.{token or draft.idempotency_key[-40:]}",
        }
    )
    document = InstanceLinkAssertionDraft(**values)
    return InstanceLinkAssertion(
        **document.model_dump(mode="python"),
        assertion_id=uuid5(NAMESPACE_URL, f"assertion:{document.idempotency_key}"),
        assertion_sha256=_sha256(document.model_dump(mode="json")),
        recorded_at=RECORDED_AT,
    )


def _baseline_with_links(
    baseline: ChongqingEntityLinkBaseline,
    links: tuple[InstanceLinkAssertionDraft, ...],
    *,
    version: str,
) -> ChongqingEntityLinkBaseline:
    return baseline.model_copy(
        update={
            "customer_bundle_version": version,
            "link_identity_count": len(links),
            "link_assertion_drafts": links,
        }
    )


class _FakeLinkAuthority:
    def __init__(self) -> None:
        self.results: dict[str, InstanceLinkAssertion] = {}
        self.batch_calls: list[tuple[InstanceLinkAssertionDraft, ...]] = []

    def record_links_batch(self, drafts):
        batch = tuple(drafts)
        self.batch_calls.append(batch)
        results = []
        for draft in batch:
            existing = self.results.get(draft.idempotency_key)
            if existing is None:
                existing = InstanceLinkAssertion(
                    **draft.model_dump(mode="python"),
                    assertion_id=uuid5(
                        NAMESPACE_URL,
                        f"reconciled:{draft.idempotency_key}",
                    ),
                    assertion_sha256=_sha256(draft.model_dump(mode="json")),
                    recorded_at=RECORDED_AT
                    + timedelta(microseconds=len(self.results)),
                )
                self.results[draft.idempotency_key] = existing
            results.append(existing)
        return tuple(results)


def test_plan_classifies_correction_retraction_restoration_and_addition() -> None:
    baseline = build_chongqing_entity_link_baseline()
    links = baseline.link_assertion_drafts
    previous = _baseline_with_links(
        baseline,
        tuple(link for index, link in enumerate(links) if index not in {2, 3}),
        version="1.0.0-previous",
    )
    corrected_first = links[0].model_copy(
        update={
            "evidence": {
                **links[0].evidence,
                "recompute_revision": "feature-overlay-v3",
            }
        }
    )
    desired = _baseline_with_links(
        baseline,
        (corrected_first, *links[2:]),
        version="1.0.1-desired",
    )
    effective_at = links[0].valid_from + timedelta(days=1)
    authority_assertions = {
        link.link_ref: _assertion(link) for link in previous.link_assertion_drafts
    }
    authority_assertions[links[2].link_ref] = None
    authority_assertions[links[3].link_ref] = _assertion(
        links[3],
        lifecycle_state=InstanceLinkLifecycle.RETRACTED,
        mutation_kind=InstanceLinkMutationKind.TRANSITION,
        valid_from=effective_at - timedelta(hours=1),
        token="previously-retracted",
    )

    plan = build_chongqing_link_reconciliation_plan(
        previous_baseline=previous,
        desired_baseline=desired,
        authority_assertions=authority_assertions,
        effective_at=effective_at,
    )

    assert plan.schema_id == "gda.chongqing-link-reconciliation-plan.v1"
    assert plan.operation_count == 4
    assert len(plan.correction_drafts) == 1
    assert len(plan.retraction_drafts) == 1
    assert len(plan.restoration_drafts) == 1
    assert len(plan.addition_drafts) == 1
    assert len(plan.unchanged_link_refs) == 482
    correction = plan.correction_drafts[0]
    assert correction.link_ref == links[0].link_ref
    assert correction.supersedes_assertion_id == authority_assertions[
        links[0].link_ref
    ].assertion_id
    assert correction.valid_from == links[0].valid_from
    assert correction.evidence["recompute_revision"] == "feature-overlay-v3"
    assert plan.retraction_drafts[0].link_ref == links[1].link_ref
    assert plan.retraction_drafts[0].valid_from == effective_at
    assert plan.restoration_drafts[0].link_ref == links[3].link_ref
    assert plan.addition_drafts[0].link_ref == links[2].link_ref
    assert len(plan.plan_sha256) == 64

    forged = plan.model_dump(mode="python")
    forged["operation_count"] = 3
    with pytest.raises(ValidationError):
        ChongqingLinkReconciliationPlan.model_validate(forged)


def test_apply_plan_orders_phases_and_full_replay_is_idempotent() -> None:
    baseline = build_chongqing_entity_link_baseline()
    links = baseline.link_assertion_drafts
    previous = _baseline_with_links(
        baseline,
        tuple(link for index, link in enumerate(links) if index not in {2, 3}),
        version="1.0.0-previous",
    )
    desired = _baseline_with_links(
        baseline,
        (
            links[0].model_copy(
                update={"attributes": {**links[0].attributes, "audit_revision": 2}}
            ),
            *links[2:],
        ),
        version="1.0.1-desired",
    )
    effective_at = links[0].valid_from + timedelta(days=1)
    authority_assertions = {
        link.link_ref: _assertion(link) for link in previous.link_assertion_drafts
    }
    authority_assertions[links[2].link_ref] = None
    authority_assertions[links[3].link_ref] = _assertion(
        links[3],
        lifecycle_state=InstanceLinkLifecycle.RETRACTED,
        mutation_kind=InstanceLinkMutationKind.TRANSITION,
        valid_from=effective_at - timedelta(hours=1),
        token="restore-source",
    )
    plan = build_chongqing_link_reconciliation_plan(
        previous_baseline=previous,
        desired_baseline=desired,
        authority_assertions=authority_assertions,
        effective_at=effective_at,
    )
    authority = _FakeLinkAuthority()

    receipt = apply_chongqing_link_reconciliation_plan(
        plan,
        link_authority=authority,
        batch_size=1,
        verify_replay=True,
    )

    assert receipt.replay_verification == "passed"
    assert receipt.operation_count == 4
    assert receipt.batch_count == 4
    assert receipt.unchanged_count == 482
    assert receipt.correction_count == 1
    assert receipt.retraction_count == 1
    assert receipt.restoration_count == 1
    assert receipt.addition_count == 1
    assert len(authority.results) == 4
    assert len(authority.batch_calls) == 8
    first_pass = [batch[0] for batch in authority.batch_calls[:4]]
    assert [draft.lifecycle_state for draft in first_pass] == [
        InstanceLinkLifecycle.RETRACTED,
        InstanceLinkLifecycle.ACTIVE,
        InstanceLinkLifecycle.ACTIVE,
        InstanceLinkLifecycle.ACTIVE,
    ]
    assert [draft.mutation_kind for draft in first_pass] == [
        InstanceLinkMutationKind.TRANSITION,
        InstanceLinkMutationKind.CORRECTION,
        InstanceLinkMutationKind.TRANSITION,
        InstanceLinkMutationKind.INITIAL,
    ]
    assert len(receipt.receipt_sha256) == 64


def test_unchanged_baseline_produces_a_sealed_zero_write_receipt() -> None:
    baseline = build_chongqing_entity_link_baseline()
    effective_at = baseline.link_assertion_drafts[0].valid_from + timedelta(days=1)
    authority_assertions = {
        draft.link_ref: _assertion(draft)
        for draft in baseline.link_assertion_drafts
    }
    plan = build_chongqing_link_reconciliation_plan(
        previous_baseline=baseline,
        desired_baseline=baseline,
        authority_assertions=authority_assertions,
        effective_at=effective_at,
    )
    authority = _FakeLinkAuthority()

    receipt = apply_chongqing_link_reconciliation_plan(
        plan,
        link_authority=authority,
        verify_replay=True,
    )

    assert plan.operation_count == 0
    assert len(plan.unchanged_link_refs) == 486
    assert receipt.operation_count == 0
    assert receipt.batch_count == 0
    assert receipt.recorded_from is None
    assert receipt.recorded_through is None
    assert authority.batch_calls == []


def test_entity_identity_change_fails_before_a_plan_is_created() -> None:
    baseline = build_chongqing_entity_link_baseline()
    changed_entities = baseline.temporal_entity_drafts[:-1]
    desired = baseline.model_copy(update={"temporal_entity_drafts": changed_entities})
    effective_at = baseline.link_assertion_drafts[0].valid_from + timedelta(days=1)
    authority_assertions = {
        draft.link_ref: _assertion(draft)
        for draft in baseline.link_assertion_drafts
    }

    with pytest.raises(
        ChongqingLinkReconciliationError,
        match="entity identity changes require entity migration",
    ):
        build_chongqing_link_reconciliation_plan(
            previous_baseline=baseline,
            desired_baseline=desired,
            authority_assertions=authority_assertions,
            effective_at=effective_at,
        )


def test_missing_authority_union_and_invalid_effective_time_fail_closed() -> None:
    baseline = build_chongqing_entity_link_baseline()
    assertions = {
        draft.link_ref: _assertion(draft)
        for draft in baseline.link_assertion_drafts[:-1]
    }
    with pytest.raises(
        ChongqingLinkReconciliationError,
        match="cover the union",
    ):
        build_chongqing_link_reconciliation_plan(
            previous_baseline=baseline,
            desired_baseline=baseline,
            authority_assertions=assertions,
            effective_at=baseline.link_assertion_drafts[0].valid_from
            + timedelta(days=1),
        )

    complete = {
        draft.link_ref: _assertion(draft)
        for draft in baseline.link_assertion_drafts
    }
    with pytest.raises(
        ChongqingLinkReconciliationError,
        match="effective_at must be later",
    ):
        build_chongqing_link_reconciliation_plan(
            previous_baseline=baseline,
            desired_baseline=baseline,
            authority_assertions=complete,
            effective_at=baseline.link_assertion_drafts[0].valid_from,
        )
