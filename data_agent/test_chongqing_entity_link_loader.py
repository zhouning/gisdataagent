"""Contract tests for the resumable Chongqing authority loader."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import NAMESPACE_URL, uuid5

import pytest
from pydantic import ValidationError

from data_agent.chongqing_entity_link_baseline import (
    build_chongqing_entity_link_baseline,
)
from data_agent.chongqing_entity_link_loader import (
    ChongqingEntityLinkLoadError,
    ChongqingEntityLinkLoadReceipt,
    load_chongqing_entity_link_baseline,
)

RECORDED_AT = datetime(2026, 8, 14, 12, tzinfo=UTC)


def _draft_sha256(draft) -> str:
    payload = json.dumps(
        draft.model_dump(mode="json"),
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


class _FakeTemporalAuthority:
    def __init__(self, log: list[str], *, non_idempotent: bool = False):
        self.log = log
        self.non_idempotent = non_idempotent
        self.records: dict[str, SimpleNamespace] = {}
        self.calls = 0
        self.batch_calls: list[int] = []

    def record(self, draft):
        self.log.append("entity")
        self.calls += 1
        if not self.non_idempotent and draft.idempotency_key in self.records:
            return self.records[draft.idempotency_key]
        identity_key = (
            f"temporal:{draft.idempotency_key}:{self.calls}"
            if self.non_idempotent
            else f"temporal:{draft.idempotency_key}"
        )
        result = SimpleNamespace(
            assertion_id=uuid5(NAMESPACE_URL, identity_key),
            assertion_sha256=_draft_sha256(draft),
            recorded_at=RECORDED_AT + timedelta(microseconds=len(self.records)),
        )
        if not self.non_idempotent:
            self.records[draft.idempotency_key] = result
        return result

    def record_batch(self, drafts):
        batch = tuple(drafts)
        self.batch_calls.append(len(batch))
        return tuple(self.record(draft) for draft in batch)


class _FakeLinkAuthority:
    def __init__(
        self,
        log: list[str],
        *,
        fail_link_at: int | None = None,
        non_idempotent_links: bool = False,
    ):
        self.log = log
        self.fail_link_at = fail_link_at
        self.non_idempotent_links = non_idempotent_links
        self.bindings: dict[str, SimpleNamespace] = {}
        self.link_types: dict[str, SimpleNamespace] = {}
        self.links: dict[str, SimpleNamespace] = {}
        self.binding_calls = 0
        self.type_calls = 0
        self.link_calls = 0
        self.binding_batch_calls: list[int] = []
        self.type_batch_calls: list[int] = []
        self.link_batch_calls: list[int] = []

    def bind_source(self, draft):
        self.log.append("binding")
        self.binding_calls += 1
        existing = self.bindings.get(draft.idempotency_key)
        if existing is not None:
            return existing
        result = SimpleNamespace(
            binding_id=uuid5(NAMESPACE_URL, f"binding:{draft.idempotency_key}"),
            binding_sha256=_draft_sha256(draft),
            recorded_at=RECORDED_AT
            + timedelta(seconds=1, microseconds=len(self.bindings)),
        )
        self.bindings[draft.idempotency_key] = result
        return result

    def bind_sources_batch(self, drafts):
        batch = tuple(drafts)
        self.binding_batch_calls.append(len(batch))
        return tuple(self.bind_source(draft) for draft in batch)

    def register_link_type(self, draft):
        self.log.append("link_type")
        self.type_calls += 1
        existing = self.link_types.get(draft.link_type_ref)
        if existing is not None:
            return existing
        result = SimpleNamespace(
            link_type_ref=draft.link_type_ref,
            type_sha256=_draft_sha256(draft),
            created_at=RECORDED_AT + timedelta(seconds=2),
        )
        self.link_types[draft.link_type_ref] = result
        return result

    def register_link_types_batch(self, drafts):
        batch = tuple(drafts)
        self.type_batch_calls.append(len(batch))
        return tuple(self.register_link_type(draft) for draft in batch)

    def record_link(self, draft):
        self.log.append("link")
        self.link_calls += 1
        if self.fail_link_at == self.link_calls:
            self.fail_link_at = None
            raise RuntimeError("injected link write failure")
        existing = self.links.get(draft.idempotency_key)
        if existing is not None and not self.non_idempotent_links:
            return existing
        identity_key = (
            f"link:{draft.idempotency_key}:{self.link_calls}"
            if self.non_idempotent_links
            else f"link:{draft.idempotency_key}"
        )
        result = SimpleNamespace(
            assertion_id=uuid5(NAMESPACE_URL, identity_key),
            assertion_sha256=_draft_sha256(draft),
            recorded_at=RECORDED_AT
            + timedelta(seconds=3, microseconds=len(self.links)),
        )
        if not self.non_idempotent_links:
            self.links[draft.idempotency_key] = result
        return result

    def record_links_batch(self, drafts):
        batch = tuple(drafts)
        self.link_batch_calls.append(len(batch))
        records_before = dict(self.links)
        calls_before = self.link_calls
        log_size_before = len(self.log)
        try:
            return tuple(self.record_link(draft) for draft in batch)
        except Exception:
            self.links = records_before
            self.link_calls = calls_before
            del self.log[log_size_before:]
            raise


def test_loader_writes_in_dependency_order_and_returns_sealed_receipt() -> None:
    baseline = build_chongqing_entity_link_baseline()
    log: list[str] = []
    temporal = _FakeTemporalAuthority(log)
    links = _FakeLinkAuthority(log)

    receipt = load_chongqing_entity_link_baseline(
        baseline=baseline,
        temporal_authority=temporal,
        link_authority=links,
    )

    assert receipt.schema_id == "gda.chongqing-entity-link-load-receipt.v2"
    assert receipt.constraint_feature_count == 16
    assert receipt.constraint_identity_count == 16
    assert receipt.entity_count == 455
    assert receipt.binding_count == 455
    assert receipt.link_type_count == 1
    assert receipt.link_assertion_count == 486
    assert receipt.customer_scope_observation_count == 472
    assert receipt.exact_intersection_observation_count == 492
    assert receipt.evidence_observation_count == 492
    assert receipt.excluded_precision_sliver_count == 1
    assert receipt.precision_policy == (
        "positive_intersection_area_gt_1e-15_source_crs_units"
    )
    assert receipt.authority_operation_count == 1_397
    assert receipt.authority_batch_count == 7
    assert receipt.idempotency_key_count == 1_396
    assert receipt.replayed_operation_count == 0
    assert receipt.replayed_batch_count == 0
    assert receipt.replay_verification == "not_requested"
    assert receipt.write_mode == "chunked_atomic_authority_batches"
    assert receipt.atomicity_status == "atomic_per_batch_resumable_across_batches"
    assert receipt.batch_size == 250
    assert len(receipt.receipt_sha256) == 64
    assert log[:455] == ["entity"] * 455
    assert log[455:910] == ["binding"] * 455
    assert log[910] == "link_type"
    assert log[911:] == ["link"] * 486

    with pytest.raises(ValidationError, match="frozen"):
        receipt.entity_count = 0
    forged = receipt.model_dump(mode="python")
    forged["authority_state_sha256"] = "0" * 64
    with pytest.raises(ValidationError, match="receipt SHA-256"):
        ChongqingEntityLinkLoadReceipt.model_validate(forged)


def test_loader_full_replay_returns_the_same_authority_state() -> None:
    baseline = build_chongqing_entity_link_baseline()
    log: list[str] = []
    temporal = _FakeTemporalAuthority(log)
    links = _FakeLinkAuthority(log)

    receipt = load_chongqing_entity_link_baseline(
        baseline=baseline,
        temporal_authority=temporal,
        link_authority=links,
        verify_replay=True,
    )

    assert receipt.replay_verification == "passed"
    assert receipt.replayed_operation_count == 1_397
    assert receipt.authority_batch_count == 7
    assert receipt.replayed_batch_count == 7
    assert temporal.calls == 910
    assert temporal.batch_calls == [250, 205, 250, 205]
    assert links.binding_calls == 910
    assert links.binding_batch_calls == [250, 205, 250, 205]
    assert links.type_calls == 2
    assert links.type_batch_calls == [1, 1]
    assert links.link_calls == 972
    assert links.link_batch_calls == [250, 236, 250, 236]
    assert len(temporal.records) == 455
    assert len(links.bindings) == 455
    assert len(links.link_types) == 1
    assert len(links.links) == 486


def test_loader_rejects_a_replay_that_returns_new_link_identities() -> None:
    baseline = build_chongqing_entity_link_baseline()
    log: list[str] = []

    with pytest.raises(ChongqingEntityLinkLoadError, match="different authority identities"):
        load_chongqing_entity_link_baseline(
            baseline=baseline,
            temporal_authority=_FakeTemporalAuthority(log),
            link_authority=_FakeLinkAuthority(log, non_idempotent_links=True),
            verify_replay=True,
        )


def test_interrupted_load_can_resume_without_duplicate_authority_state() -> None:
    baseline = build_chongqing_entity_link_baseline()
    log: list[str] = []
    temporal = _FakeTemporalAuthority(log)
    links = _FakeLinkAuthority(log, fail_link_at=4)

    with pytest.raises(ChongqingEntityLinkLoadError, match="safe to retry"):
        load_chongqing_entity_link_baseline(
            baseline=baseline,
            temporal_authority=temporal,
            link_authority=links,
        )
    assert len(links.links) == 0

    receipt = load_chongqing_entity_link_baseline(
        baseline=baseline,
        temporal_authority=temporal,
        link_authority=links,
    )

    assert receipt.link_assertion_count == 486
    assert len(temporal.records) == 455
    assert len(links.bindings) == 455
    assert len(links.link_types) == 1
    assert len(links.links) == 486


def test_loader_rejects_a_baseline_from_another_tenant_before_writing() -> None:
    baseline = build_chongqing_entity_link_baseline(tenant_id="cq-customer-a")
    log: list[str] = []

    with pytest.raises(ChongqingEntityLinkLoadError, match="does not belong"):
        load_chongqing_entity_link_baseline(
            tenant_id="cq-customer-b",
            baseline=baseline,
            temporal_authority=_FakeTemporalAuthority(log),
            link_authority=_FakeLinkAuthority(log),
        )
    assert log == []


def test_loader_rejects_inconsistent_baseline_counts_before_writing() -> None:
    baseline = build_chongqing_entity_link_baseline().model_copy(
        update={"link_identity_count": 485}
    )
    log: list[str] = []

    with pytest.raises(ChongqingEntityLinkLoadError, match="draft count is inconsistent"):
        load_chongqing_entity_link_baseline(
            baseline=baseline,
            temporal_authority=_FakeTemporalAuthority(log),
            link_authority=_FakeLinkAuthority(log),
        )
    assert log == []
