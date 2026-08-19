"""Resumable authority loader for the version-locked Chongqing baseline."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .chongqing_entity_link_baseline import (
    CUSTOMER_BUNDLE_DIR,
    DEFAULT_TENANT,
    ONTOLOGY_PACKAGE_DIR,
    ChongqingEntityLinkBaseline,
    build_chongqing_entity_link_baseline,
)
from .entity_link_authority import EntityLinkAuthority
from .platform_contracts import Sha256, TenantId
from .temporal_entity_authority import TemporalEntityAuthority


class ChongqingEntityLinkLoadError(RuntimeError):
    """The baseline could not be completely written or replay-verified."""


class _FrozenContract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class _ChongqingEntityLinkLoadReceiptBody(_FrozenContract):
    schema_id: Literal["gda.chongqing-entity-link-load-receipt.v2"] = (
        "gda.chongqing-entity-link-load-receipt.v2"
    )
    tenant_id: TenantId
    customer_bundle_id: str
    customer_bundle_version: str
    ontology_package_id: str
    ontology_package_sha256: Sha256
    ontology_review_status: Literal["technical_baseline_unreviewed"]
    usage_status: Literal["assisted_precheck_not_for_production_decision"]
    decision_scope: str
    write_mode: Literal["chunked_atomic_authority_batches"] = (
        "chunked_atomic_authority_batches"
    )
    atomicity_status: Literal["atomic_per_batch_resumable_across_batches"] = (
        "atomic_per_batch_resumable_across_batches"
    )
    idempotency_status: Literal[
        "authority_idempotency_keys_and_type_fingerprint"
    ] = "authority_idempotency_keys_and_type_fingerprint"
    replay_verification: Literal["not_requested", "passed"]
    baseline_valid_from: datetime
    authority_recorded_from: datetime
    authority_recorded_through: datetime
    parcel_record_count: int = Field(ge=0)
    parcel_identity_count: int = Field(ge=0)
    constraint_feature_count: int = Field(ge=0)
    constraint_identity_count: int = Field(ge=0)
    constraint_scope_count: int = Field(ge=0)
    entity_count: int = Field(ge=0)
    binding_count: int = Field(ge=0)
    link_type_count: int = Field(ge=0)
    link_assertion_count: int = Field(ge=0)
    evidence_observation_count: int = Field(ge=0)
    customer_scope_observation_count: int = Field(ge=0)
    exact_intersection_observation_count: int = Field(ge=0)
    excluded_precision_sliver_count: int = Field(ge=0)
    precision_policy: Literal[
        "positive_intersection_area_gt_1e-15_source_crs_units"
    ]
    batch_size: int = Field(ge=1, le=500)
    authority_operation_count: int = Field(ge=0)
    authority_batch_count: int = Field(ge=0)
    idempotency_key_count: int = Field(ge=0)
    replayed_operation_count: int = Field(ge=0)
    replayed_batch_count: int = Field(ge=0)
    entity_assertion_state_sha256: Sha256
    source_binding_state_sha256: Sha256
    link_type_state_sha256: Sha256
    link_assertion_state_sha256: Sha256
    authority_state_sha256: Sha256

    @field_validator(
        "baseline_valid_from",
        "authority_recorded_from",
        "authority_recorded_through",
    )
    @classmethod
    def _aware_utc(cls, value: datetime, info) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError(f"{info.field_name} must be timezone-aware")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def _consistent_counts(self) -> _ChongqingEntityLinkLoadReceiptBody:
        if self.constraint_identity_count != self.constraint_feature_count:
            raise ValueError("constraint feature identity count is inconsistent")
        if self.evidence_observation_count != self.exact_intersection_observation_count:
            raise ValueError("exact intersection evidence count is inconsistent")
        expected_operations = (
            self.entity_count
            + self.binding_count
            + self.link_type_count
            + self.link_assertion_count
        )
        if self.authority_operation_count != expected_operations:
            raise ValueError("authority operation count is inconsistent")
        expected_idempotency_keys = (
            self.entity_count + self.binding_count + self.link_assertion_count
        )
        if self.idempotency_key_count != expected_idempotency_keys:
            raise ValueError("idempotency key count is inconsistent")
        expected_batches = sum(
            (count + self.batch_size - 1) // self.batch_size
            for count in (
                self.entity_count,
                self.binding_count,
                self.link_type_count,
                self.link_assertion_count,
            )
            if count
        )
        if self.authority_batch_count != expected_batches:
            raise ValueError("authority batch count is inconsistent")
        expected_replays = (
            expected_operations if self.replay_verification == "passed" else 0
        )
        if self.replayed_operation_count != expected_replays:
            raise ValueError("replayed operation count is inconsistent")
        expected_replayed_batches = (
            expected_batches if self.replay_verification == "passed" else 0
        )
        if self.replayed_batch_count != expected_replayed_batches:
            raise ValueError("replayed batch count is inconsistent")
        if self.authority_recorded_through < self.authority_recorded_from:
            raise ValueError("authority recording time window is inconsistent")
        return self


class ChongqingEntityLinkLoadReceipt(_ChongqingEntityLinkLoadReceiptBody):
    """Immutable, self-verifying receipt for one complete baseline load."""

    receipt_sha256: Sha256

    @model_validator(mode="after")
    def _valid_receipt_hash(self) -> ChongqingEntityLinkLoadReceipt:
        expected = _document_sha256(
            self.model_dump(mode="json", exclude={"receipt_sha256"})
        )
        if self.receipt_sha256 != expected:
            raise ValueError("load receipt SHA-256 is invalid")
        return self


@dataclass(frozen=True)
class _AuthorityLoadState:
    temporal_assertions: tuple[Any, ...]
    source_bindings: tuple[Any, ...]
    link_type: Any
    link_assertions: tuple[Any, ...]
    entity_assertion_state_sha256: str
    source_binding_state_sha256: str
    link_type_state_sha256: str
    link_assertion_state_sha256: str
    authority_state_sha256: str
    recorded_from: datetime
    recorded_through: datetime
    batch_count: int


def _document_sha256(document: Any) -> str:
    payload = json.dumps(
        document,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _result_state_sha256(
    results: Sequence[Any],
    *,
    identity_attribute: str,
    content_attribute: str,
) -> str:
    return _document_sha256(
        [
            {
                "identity": str(getattr(result, identity_attribute)),
                "content_sha256": str(getattr(result, content_attribute)),
            }
            for result in results
        ]
    )


def _load_batches(
    *,
    stage: str,
    drafts: Sequence[Any],
    identity_attribute: str,
    operation: Callable[[Sequence[Any]], Sequence[Any]],
    batch_size: int,
) -> tuple[tuple[Any, ...], int]:
    results: list[Any] = []
    total = len(drafts)
    batch_count = 0
    for offset in range(0, total, batch_size):
        batch = tuple(drafts[offset : offset + batch_size])
        first_identity = getattr(batch[0], identity_attribute, "unknown")
        last_identity = getattr(batch[-1], identity_attribute, "unknown")
        batch_count += 1
        try:
            batch_results = tuple(operation(batch))
        except Exception as exc:
            raise ChongqingEntityLinkLoadError(
                f"{stage} failed for batch {batch_count} covering items "
                f"{offset + 1}..{offset + len(batch)}/{total} "
                f"({first_identity}..{last_identity}); earlier batches remain committed "
                "and the load is safe to retry"
            ) from exc
        if len(batch_results) != len(batch):
            raise ChongqingEntityLinkLoadError(
                f"{stage} batch {batch_count} returned {len(batch_results)} results "
                f"for {len(batch)} inputs"
            )
        results.extend(batch_results)
    return tuple(results), batch_count


def _validate_baseline(baseline: ChongqingEntityLinkBaseline) -> None:
    expected_entities = baseline.parcel_identity_count + baseline.constraint_identity_count
    exact_observation_count = sum(
        int(draft.attributes.get("observation_count") or 0)
        for draft in baseline.link_assertion_drafts
    )
    customer_observation_keys = {
        (
            int(observation["parcel_feature_index"]),
            int(observation["hit_index"]),
        )
        for draft in baseline.link_assertion_drafts
        for observation in draft.evidence.get("observations") or []
    }
    checks = {
        "constraint identity count": (
            baseline.constraint_identity_count,
            baseline.constraint_feature_count,
        ),
        "temporal entity draft count": (
            len(baseline.temporal_entity_drafts),
            expected_entities,
        ),
        "source binding draft count": (
            len(baseline.source_binding_drafts),
            expected_entities,
        ),
        "link assertion draft count": (
            len(baseline.link_assertion_drafts),
            baseline.link_identity_count,
        ),
        "link evidence observation count": (
            len(customer_observation_keys),
            baseline.link_evidence_observation_count,
        ),
        "exact intersection observation count": (
            exact_observation_count,
            baseline.exact_intersection_observation_count,
        ),
    }
    for name, (actual, expected) in checks.items():
        if actual != expected:
            raise ChongqingEntityLinkLoadError(
                f"baseline {name} is inconsistent: expected {expected}, got {actual}"
            )

    tenant_values = {
        *(draft.tenant_id for draft in baseline.temporal_entity_drafts),
        *(draft.tenant_id for draft in baseline.source_binding_drafts),
        baseline.link_type_draft.tenant_id,
        *(draft.tenant_id for draft in baseline.link_assertion_drafts),
    }
    if tenant_values != {baseline.tenant_id}:
        raise ChongqingEntityLinkLoadError("baseline drafts cross tenant boundaries")

    unique_contracts = (
        (
            "temporal entity idempotency keys",
            [draft.idempotency_key for draft in baseline.temporal_entity_drafts],
        ),
        (
            "source binding idempotency keys",
            [draft.idempotency_key for draft in baseline.source_binding_drafts],
        ),
        (
            "link assertion idempotency keys",
            [draft.idempotency_key for draft in baseline.link_assertion_drafts],
        ),
        (
            "temporal entity references",
            [draft.entity_ref for draft in baseline.temporal_entity_drafts],
        ),
        (
            "source identity references",
            [draft.source_identity_ref for draft in baseline.source_binding_drafts],
        ),
        (
            "link references",
            [draft.link_ref for draft in baseline.link_assertion_drafts],
        ),
    )
    for name, values in unique_contracts:
        if len(values) != len(set(values)):
            raise ChongqingEntityLinkLoadError(f"baseline {name} are not unique")


def _write_baseline(
    baseline: ChongqingEntityLinkBaseline,
    *,
    temporal_authority: Any,
    link_authority: Any,
    batch_size: int,
) -> _AuthorityLoadState:
    temporal_assertions, temporal_batch_count = _load_batches(
        stage="temporal entity load",
        drafts=baseline.temporal_entity_drafts,
        identity_attribute="entity_ref",
        operation=temporal_authority.record_batch,
        batch_size=batch_size,
    )
    source_bindings, binding_batch_count = _load_batches(
        stage="source binding load",
        drafts=baseline.source_binding_drafts,
        identity_attribute="source_identity_ref",
        operation=link_authority.bind_sources_batch,
        batch_size=batch_size,
    )
    link_types, link_type_batch_count = _load_batches(
        stage="link type load",
        drafts=(baseline.link_type_draft,),
        identity_attribute="link_type_ref",
        operation=link_authority.register_link_types_batch,
        batch_size=batch_size,
    )
    link_type = link_types[0]
    link_assertions, link_batch_count = _load_batches(
        stage="link assertion load",
        drafts=baseline.link_assertion_drafts,
        identity_attribute="link_ref",
        operation=link_authority.record_links_batch,
        batch_size=batch_size,
    )

    try:
        entity_state = _result_state_sha256(
            temporal_assertions,
            identity_attribute="assertion_id",
            content_attribute="assertion_sha256",
        )
        binding_state = _result_state_sha256(
            source_bindings,
            identity_attribute="binding_id",
            content_attribute="binding_sha256",
        )
        link_type_state = _document_sha256(
            {
                "identity": str(link_type.link_type_ref),
                "content_sha256": str(link_type.type_sha256),
            }
        )
        link_state = _result_state_sha256(
            link_assertions,
            identity_attribute="assertion_id",
            content_attribute="assertion_sha256",
        )
        recorded_times = [
            *(result.recorded_at for result in temporal_assertions),
            *(result.recorded_at for result in source_bindings),
            link_type.created_at,
            *(result.recorded_at for result in link_assertions),
        ]
    except (AttributeError, TypeError, ValueError) as exc:
        raise ChongqingEntityLinkLoadError(
            "an authority returned an invalid load result"
        ) from exc

    authority_state = _document_sha256(
        {
            "entity_assertions": entity_state,
            "source_bindings": binding_state,
            "link_type": link_type_state,
            "link_assertions": link_state,
        }
    )
    return _AuthorityLoadState(
        temporal_assertions=temporal_assertions,
        source_bindings=source_bindings,
        link_type=link_type,
        link_assertions=link_assertions,
        entity_assertion_state_sha256=entity_state,
        source_binding_state_sha256=binding_state,
        link_type_state_sha256=link_type_state,
        link_assertion_state_sha256=link_state,
        authority_state_sha256=authority_state,
        recorded_from=min(recorded_times),
        recorded_through=max(recorded_times),
        batch_count=(
            temporal_batch_count
            + binding_batch_count
            + link_type_batch_count
            + link_batch_count
        ),
    )


def _build_receipt(
    baseline: ChongqingEntityLinkBaseline,
    state: _AuthorityLoadState,
    *,
    replay_verified: bool,
    batch_size: int,
) -> ChongqingEntityLinkLoadReceipt:
    operation_count = (
        len(state.temporal_assertions)
        + len(state.source_bindings)
        + 1
        + len(state.link_assertions)
    )
    body = _ChongqingEntityLinkLoadReceiptBody(
        tenant_id=baseline.tenant_id,
        customer_bundle_id=baseline.customer_bundle_id,
        customer_bundle_version=baseline.customer_bundle_version,
        ontology_package_id=baseline.ontology_package_id,
        ontology_package_sha256=baseline.ontology_package_sha256,
        ontology_review_status=baseline.ontology_review_status,
        usage_status=baseline.usage_status,
        decision_scope=baseline.decision_scope,
        replay_verification="passed" if replay_verified else "not_requested",
        baseline_valid_from=baseline.temporal_entity_drafts[0].valid_from,
        authority_recorded_from=state.recorded_from,
        authority_recorded_through=state.recorded_through,
        parcel_record_count=baseline.parcel_record_count,
        parcel_identity_count=baseline.parcel_identity_count,
        constraint_feature_count=baseline.constraint_feature_count,
        constraint_identity_count=baseline.constraint_identity_count,
        constraint_scope_count=baseline.constraint_scope_count,
        entity_count=len(state.temporal_assertions),
        binding_count=len(state.source_bindings),
        link_type_count=1,
        link_assertion_count=len(state.link_assertions),
        evidence_observation_count=baseline.exact_intersection_observation_count,
        customer_scope_observation_count=baseline.link_evidence_observation_count,
        exact_intersection_observation_count=(
            baseline.exact_intersection_observation_count
        ),
        excluded_precision_sliver_count=baseline.excluded_precision_sliver_count,
        precision_policy=baseline.precision_policy,
        batch_size=batch_size,
        authority_operation_count=operation_count,
        authority_batch_count=state.batch_count,
        idempotency_key_count=(
            len(state.temporal_assertions)
            + len(state.source_bindings)
            + len(state.link_assertions)
        ),
        replayed_operation_count=operation_count if replay_verified else 0,
        replayed_batch_count=state.batch_count if replay_verified else 0,
        entity_assertion_state_sha256=state.entity_assertion_state_sha256,
        source_binding_state_sha256=state.source_binding_state_sha256,
        link_type_state_sha256=state.link_type_state_sha256,
        link_assertion_state_sha256=state.link_assertion_state_sha256,
        authority_state_sha256=state.authority_state_sha256,
    )
    body_values = body.model_dump(mode="python")
    receipt_sha256 = _document_sha256(body.model_dump(mode="json"))
    return ChongqingEntityLinkLoadReceipt(
        **body_values,
        receipt_sha256=receipt_sha256,
    )


def load_chongqing_entity_link_baseline(
    *,
    tenant_id: str | None = None,
    bundle_dir: str | Path = CUSTOMER_BUNDLE_DIR,
    ontology_package_dir: str | Path = ONTOLOGY_PACKAGE_DIR,
    baseline: ChongqingEntityLinkBaseline | None = None,
    engine: Any = None,
    temporal_authority: Any = None,
    link_authority: Any = None,
    verify_replay: bool = False,
    batch_size: int = 250,
) -> ChongqingEntityLinkLoadReceipt:
    """Write the complete baseline through authorities and optionally replay it.

    Each bounded batch owns a PostgreSQL transaction. If a later batch fails,
    retrying the loader resumes safely through the existing idempotency keys and
    the link type fingerprint. A receipt is returned only after every batch succeeds.
    """
    if batch_size < 1 or batch_size > 500:
        raise ChongqingEntityLinkLoadError("batch_size must be 1..500")
    resolved_tenant = tenant_id or (
        baseline.tenant_id if baseline is not None else DEFAULT_TENANT
    )
    if baseline is None:
        baseline = build_chongqing_entity_link_baseline(
            tenant_id=resolved_tenant,
            bundle_dir=bundle_dir,
            ontology_package_dir=ontology_package_dir,
        )
    elif baseline.tenant_id != resolved_tenant:
        raise ChongqingEntityLinkLoadError(
            "the supplied baseline does not belong to tenant_id"
        )
    _validate_baseline(baseline)

    temporal_writer = temporal_authority or TemporalEntityAuthority(engine=engine)
    link_writer = link_authority or EntityLinkAuthority(engine=engine)
    initial = _write_baseline(
        baseline,
        temporal_authority=temporal_writer,
        link_authority=link_writer,
        batch_size=batch_size,
    )
    if verify_replay:
        replay = _write_baseline(
            baseline,
            temporal_authority=temporal_writer,
            link_authority=link_writer,
            batch_size=batch_size,
        )
        if (
            replay.authority_state_sha256 != initial.authority_state_sha256
            or replay.recorded_from != initial.recorded_from
            or replay.recorded_through != initial.recorded_through
        ):
            raise ChongqingEntityLinkLoadError(
                "full replay returned different authority identities, content fingerprints, "
                "or recording times"
            )
    return _build_receipt(
        baseline,
        initial,
        replay_verified=verify_replay,
        batch_size=batch_size,
    )
