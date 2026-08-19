"""Conflict-safe migration into the existing bitemporal entity authorities.

This module does not own entity identity or history. It seals migration inputs,
requires human decisions for ambiguous identity or lineage changes, and compiles
only admitted work into the existing temporal, source-binding, and lineage
authorities.
"""

from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Callable
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, ClassVar, Protocol

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .entity_lineage_authority import (
    EntityLineageReceipt,
    EntityLineageRequest,
)
from .entity_link_authority import (
    EntityResolutionMethod,
    EntitySourceBinding,
    EntitySourceBindingDraft,
)
from .platform_contracts import (
    ResourceURNText,
    Sha256,
    ShortName,
    TenantId,
    canonical_json_fingerprint,
    parse_resource_urn,
)
from .temporal_entity_authority import (
    TemporalEntityAssertion,
    TemporalEntityAssertionDraft,
    TemporalMutationKind,
)

_ACTOR_RE = re.compile(r"^(human|workload|agent):[^\s]{1,128}$")
_AUTOMATIC_RESOLUTION_METHODS = frozenset(
    {
        EntityResolutionMethod.AUTHORITATIVE_IDENTIFIER,
        EntityResolutionMethod.AUTHORITATIVE_COMPOSITE_KEY,
    }
)


class _FrozenContract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class EntityMigrationPlanningStatus(StrEnum):
    READY = "ready"
    NEEDS_RESOLUTION = "needs_resolution"
    NOT_ADMITTED = "not_admitted"


class EntityMigrationConflictKind(StrEnum):
    AMBIGUOUS_SOURCE_IDENTITY = "ambiguous_source_identity"
    REVIEW_REQUIRED = "review_required"
    ENTITY_STATE_CONFLICT = "entity_state_conflict"
    LINEAGE_DECISION_REQUIRED = "lineage_decision_required"


class EntityMigrationExecutionStatus(StrEnum):
    COMPLETED = "completed"
    RECONCILING = "reconciling"


class EntityMigrationStage(StrEnum):
    ENTITY_ASSERTIONS = "entity_assertions"
    SOURCE_BINDINGS = "source_bindings"
    LINEAGE_EVENTS = "lineage_events"


class EntityMigrationStageStatus(StrEnum):
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class EntityMigrationError(RuntimeError):
    """Base error for entity-domain migration orchestration."""


class EntityMigrationAdmissionError(EntityMigrationError):
    """A migration plan is incomplete or no longer admitted."""


class EntityMigrationResolutionError(EntityMigrationError):
    """A human resolution does not bind the unresolved plan."""


def _aware_utc(value: datetime, field_name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value.astimezone(UTC)


def _jsonable(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, dict):
        return {key: _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    if isinstance(value, StrEnum):
        return value.value
    if isinstance(value, datetime):
        return _aware_utc(value, "datetime").isoformat().replace("+00:00", "Z")
    return value


def _fingerprint(schema: str, values: dict[str, Any], hash_field: str) -> Sha256:
    payload = dict(values)
    payload.pop(hash_field, None)
    return canonical_json_fingerprint({"schema": schema, "data": _jsonable(payload)})


def _tenant_ref(value: str, tenant_id: str, kind: str, field_name: str) -> None:
    parsed = parse_resource_urn(value)
    if parsed["tenant_id"] != tenant_id or parsed["resource_kind"] != kind:
        raise ValueError(f"{field_name} must use tenant {tenant_id!r} and kind {kind!r}")


def _typed_actor(value: str, field_name: str) -> str:
    value = value.strip()
    if _ACTOR_RE.fullmatch(value) is None:
        raise ValueError(f"{field_name} must use a typed subject")
    return value


def _entity_state_fingerprint(assertion: TemporalEntityAssertionDraft) -> Sha256:
    state = assertion.model_dump(
        mode="json",
        exclude={
            "source_version_refs",
            "idempotency_key",
            "recorded_by",
            "reason",
        },
    )
    return canonical_json_fingerprint(state)


class EntityDomainMigrationBudget(_FrozenContract):
    max_candidates: int = Field(default=5_000, ge=1, le=20_000)
    max_source_identities: int = Field(default=5_000, ge=1, le=20_000)
    max_lineage_events: int = Field(default=100, ge=0, le=1_000)
    batch_size: int = Field(default=250, ge=1, le=500)


class EntityMigrationCandidate(_FrozenContract):
    schema_id: ClassVar[str] = "gda.entity-migration-candidate.v1"
    tenant_id: TenantId
    candidate_id: ShortName
    source_identity_ref: ResourceURNText
    entity_ref: ResourceURNText
    entity_assertion: TemporalEntityAssertionDraft | None = None
    source_binding: EntitySourceBindingDraft
    evidence_refs: tuple[ResourceURNText, ...] = Field(min_length=1, max_length=100)
    candidate_sha256: Sha256

    @field_validator("evidence_refs")
    @classmethod
    def _canonical_evidence(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if tuple(sorted(set(values))) != values:
            raise ValueError("migration evidence_refs must be sorted and unique")
        return values

    @model_validator(mode="after")
    def _sealed_and_aligned(self) -> EntityMigrationCandidate:
        _tenant_ref(
            self.source_identity_ref,
            self.tenant_id,
            "source_identity",
            "source_identity_ref",
        )
        _tenant_ref(self.entity_ref, self.tenant_id, "entity", "entity_ref")
        binding = self.source_binding
        if (
            binding.tenant_id != self.tenant_id
            or binding.source_identity_ref != self.source_identity_ref
            or binding.entity_ref != self.entity_ref
        ):
            raise ValueError("migration candidate and source binding identity differ")
        if binding.source_version_ref not in self.evidence_refs:
            raise ValueError("source binding version must be migration evidence")
        for evidence_ref in self.evidence_refs:
            if parse_resource_urn(evidence_ref)["tenant_id"] != self.tenant_id:
                raise ValueError("migration evidence must use candidate tenant")
        if self.entity_assertion is not None:
            assertion = self.entity_assertion
            if (
                assertion.tenant_id != self.tenant_id
                or assertion.entity_ref != self.entity_ref
                or assertion.object_type != binding.entity_object_type
                or assertion.valid_from != binding.valid_from
                or assertion.valid_to != binding.valid_to
                or binding.source_version_ref not in assertion.source_version_refs
            ):
                raise ValueError("migration entity assertion and source binding state differ")
        expected = _fingerprint(
            self.schema_id,
            self.model_dump(mode="json", exclude={"candidate_sha256"}),
            "candidate_sha256",
        )
        if self.candidate_sha256 != expected:
            raise ValueError("migration candidate fingerprint is invalid")
        return self


def build_entity_migration_candidate(
    *,
    tenant_id: str,
    candidate_id: str,
    source_identity_ref: str,
    entity_ref: str,
    source_binding: EntitySourceBindingDraft,
    evidence_refs: tuple[str, ...],
    entity_assertion: TemporalEntityAssertionDraft | None = None,
) -> EntityMigrationCandidate:
    values: dict[str, Any] = {
        "tenant_id": tenant_id,
        "candidate_id": candidate_id,
        "source_identity_ref": source_identity_ref,
        "entity_ref": entity_ref,
        "entity_assertion": entity_assertion,
        "source_binding": source_binding,
        "evidence_refs": evidence_refs,
    }
    return EntityMigrationCandidate(
        **values,
        candidate_sha256=_fingerprint(
            EntityMigrationCandidate.schema_id,
            values,
            "candidate_sha256",
        ),
    )


class EntityDomainMigrationRequest(_FrozenContract):
    schema_id: ClassVar[str] = "gda.entity-domain-migration-request.v1"
    tenant_id: TenantId
    migration_id: ShortName
    source_domain_ref: ResourceURNText
    source_snapshot_refs: tuple[ResourceURNText, ...] = Field(
        min_length=1,
        max_length=100,
    )
    mapping_contract_ref: ResourceURNText
    mapping_contract_sha256: Sha256
    effective_at: datetime
    candidates: tuple[EntityMigrationCandidate, ...] = Field(
        min_length=1,
        max_length=20_000,
    )
    lineage_requests: tuple[EntityLineageRequest, ...] = Field(
        default=(),
        max_length=1_000,
    )
    budget: EntityDomainMigrationBudget = Field(default_factory=EntityDomainMigrationBudget)
    requested_by: str
    request_sha256: Sha256

    @field_validator("source_snapshot_refs")
    @classmethod
    def _canonical_snapshots(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if tuple(sorted(set(values))) != values:
            raise ValueError("source_snapshot_refs must be sorted and unique")
        return values

    @field_validator("effective_at")
    @classmethod
    def _valid_effective_at(cls, value: datetime) -> datetime:
        return _aware_utc(value, "effective_at")

    @field_validator("requested_by")
    @classmethod
    def _valid_requester(cls, value: str) -> str:
        return _typed_actor(value, "requested_by")

    @model_validator(mode="after")
    def _sealed_scope(self) -> EntityDomainMigrationRequest:
        _tenant_ref(
            self.source_domain_ref,
            self.tenant_id,
            "resource",
            "source_domain_ref",
        )
        for value in self.source_snapshot_refs:
            _tenant_ref(
                value,
                self.tenant_id,
                "resource_version",
                "source_snapshot_refs",
            )
        _tenant_ref(
            self.mapping_contract_ref,
            self.tenant_id,
            "resource_version",
            "mapping_contract_ref",
        )
        if len(self.candidates) > self.budget.max_candidates:
            raise ValueError("migration candidate budget exceeded")
        identities = {item.source_identity_ref for item in self.candidates}
        if len(identities) > self.budget.max_source_identities:
            raise ValueError("migration source identity budget exceeded")
        if len(self.lineage_requests) > self.budget.max_lineage_events:
            raise ValueError("migration lineage event budget exceeded")
        candidate_ids = tuple(item.candidate_id for item in self.candidates)
        if len(candidate_ids) != len(set(candidate_ids)):
            raise ValueError("migration candidate IDs must be unique")
        pins = set(self.source_snapshot_refs)
        allowed_evidence_refs = pins | {self.mapping_contract_ref}
        for candidate in self.candidates:
            if candidate.tenant_id != self.tenant_id:
                raise ValueError("migration candidate tenant differs")
            if not set(candidate.evidence_refs).issubset(allowed_evidence_refs):
                raise ValueError("migration candidate uses unpinned evidence")
            if candidate.source_binding.source_version_ref not in pins:
                raise ValueError("migration candidate uses an unpinned source snapshot")
            if candidate.entity_assertion is not None and not set(
                candidate.entity_assertion.source_version_refs
            ).issubset(pins):
                raise ValueError("migration assertion uses an unpinned source snapshot")
        event_refs = tuple(item.event_ref for item in self.lineage_requests)
        if len(event_refs) != len(set(event_refs)):
            raise ValueError("migration lineage event refs must be unique")
        for lineage in self.lineage_requests:
            if lineage.tenant_id != self.tenant_id:
                raise ValueError("migration lineage tenant differs")
            if lineage.effective_at != self.effective_at:
                raise ValueError("migration lineage effective_at differs")
            if not set(lineage.source_version_refs).issubset(pins):
                raise ValueError("migration lineage uses an unpinned source snapshot")
        expected = _fingerprint(
            self.schema_id,
            self.model_dump(mode="json", exclude={"request_sha256"}),
            "request_sha256",
        )
        if self.request_sha256 != expected:
            raise ValueError("entity migration request fingerprint is invalid")
        return self


def build_entity_domain_migration_request(
    *,
    tenant_id: str,
    migration_id: str,
    source_domain_ref: str,
    source_snapshot_refs: tuple[str, ...],
    mapping_contract_ref: str,
    mapping_contract_sha256: str,
    effective_at: datetime,
    candidates: tuple[EntityMigrationCandidate, ...],
    requested_by: str,
    lineage_requests: tuple[EntityLineageRequest, ...] = (),
    budget: EntityDomainMigrationBudget | None = None,
) -> EntityDomainMigrationRequest:
    values: dict[str, Any] = {
        "tenant_id": tenant_id,
        "migration_id": migration_id,
        "source_domain_ref": source_domain_ref,
        "source_snapshot_refs": source_snapshot_refs,
        "mapping_contract_ref": mapping_contract_ref,
        "mapping_contract_sha256": mapping_contract_sha256,
        "effective_at": effective_at,
        "candidates": candidates,
        "lineage_requests": lineage_requests,
        "budget": budget or EntityDomainMigrationBudget(),
        "requested_by": requested_by,
    }
    return EntityDomainMigrationRequest(
        **values,
        request_sha256=_fingerprint(
            EntityDomainMigrationRequest.schema_id,
            values,
            "request_sha256",
        ),
    )


class EntityMigrationConflict(_FrozenContract):
    conflict_id: ShortName
    kind: EntityMigrationConflictKind
    subject_ref: ResourceURNText
    option_ids: tuple[ShortName, ...] = Field(min_length=2, max_length=101)
    evidence_sha256: Sha256

    @model_validator(mode="after")
    def _unique_options(self) -> EntityMigrationConflict:
        if len(self.option_ids) != len(set(self.option_ids)):
            raise ValueError("entity migration conflict options must be unique")
        if "defer" not in self.option_ids:
            raise ValueError("entity migration conflict must retain a defer option")
        return self


class EntityMigrationResolution(_FrozenContract):
    request_sha256: Sha256
    prior_plan_sha256: Sha256
    conflict_id: ShortName
    selected_option_id: ShortName
    confirmed_by: str
    confirmed_at: datetime

    @field_validator("confirmed_by")
    @classmethod
    def _human_confirmer(cls, value: str) -> str:
        value = _typed_actor(value, "confirmed_by")
        if not value.startswith("human:"):
            raise ValueError("entity conflict resolution requires a human confirmer")
        return value

    @field_validator("confirmed_at")
    @classmethod
    def _valid_confirmation_time(cls, value: datetime) -> datetime:
        return _aware_utc(value, "confirmed_at")


class EntityDomainMigrationPlan(_FrozenContract):
    schema_id: ClassVar[str] = "gda.entity-domain-migration-plan.v1"
    request: EntityDomainMigrationRequest
    revision: int = Field(ge=0, le=128)
    status: EntityMigrationPlanningStatus
    conflicts: tuple[EntityMigrationConflict, ...]
    resolutions: tuple[EntityMigrationResolution, ...]
    selected_candidate_ids: tuple[ShortName, ...]
    entity_assertions: tuple[TemporalEntityAssertionDraft, ...]
    source_bindings: tuple[EntitySourceBindingDraft, ...]
    lineage_requests: tuple[EntityLineageRequest, ...]
    reason_codes: tuple[ShortName, ...] = Field(min_length=1, max_length=32)
    execution_allowed: bool
    supersedes_plan_sha256: Sha256 | None = None
    created_at: datetime
    plan_sha256: Sha256

    @field_validator("created_at")
    @classmethod
    def _valid_created_at(cls, value: datetime) -> datetime:
        return _aware_utc(value, "created_at")

    @model_validator(mode="after")
    def _sealed_plan(self) -> EntityDomainMigrationPlan:
        if self.status is EntityMigrationPlanningStatus.NOT_ADMITTED:
            raise ValueError("not-admitted migration cannot expose an execution plan")
        if self.execution_allowed != (self.status is EntityMigrationPlanningStatus.READY):
            raise ValueError("only a ready entity migration plan may execute")
        if self.status is EntityMigrationPlanningStatus.READY:
            if self.conflicts:
                raise ValueError("ready entity migration plan has unresolved conflicts")
            if not self.source_bindings:
                raise ValueError("ready entity migration plan has no source bindings")
        elif not self.conflicts:
            raise ValueError("resolution status requires unresolved conflicts")
        if not self.execution_allowed and (
            self.selected_candidate_ids
            or self.entity_assertions
            or self.source_bindings
            or self.lineage_requests
        ):
            raise ValueError("unresolved migration plan cannot expose authority writes")
        identities = tuple(item.source_identity_ref for item in self.source_bindings)
        if len(identities) != len(set(identities)):
            raise ValueError("ready migration source bindings must be unique")
        expected = _fingerprint(
            self.schema_id,
            self.model_dump(mode="json", exclude={"plan_sha256"}),
            "plan_sha256",
        )
        if self.plan_sha256 != expected:
            raise ValueError("entity migration plan fingerprint is invalid")
        return self


class EntityDomainMigrationPlanningOutcome(_FrozenContract):
    status: EntityMigrationPlanningStatus
    plan: EntityDomainMigrationPlan | None = None
    reason_codes: tuple[ShortName, ...] = Field(min_length=1, max_length=32)

    @model_validator(mode="after")
    def _consistent_outcome(self) -> EntityDomainMigrationPlanningOutcome:
        if self.status is EntityMigrationPlanningStatus.NOT_ADMITTED:
            if self.plan is not None:
                raise ValueError("not-admitted migration outcome cannot expose a plan")
        elif self.plan is None or self.plan.status is not self.status:
            raise ValueError("migration outcome must expose the matching plan")
        return self


class EntityDomainMigrationPlanner:
    """Compile migration candidates without silently resolving identity conflicts."""

    def __init__(self, *, now: Callable[[], datetime] | None = None) -> None:
        self._now = now or (lambda: datetime.now(UTC))

    def plan(
        self,
        request: EntityDomainMigrationRequest,
    ) -> EntityDomainMigrationPlanningOutcome:
        return self._compile(
            request,
            resolutions=(),
            revision=0,
            supersedes_plan_sha256=None,
        )

    def replan(
        self,
        request: EntityDomainMigrationRequest,
        prior: EntityDomainMigrationPlan,
        resolutions: tuple[EntityMigrationResolution, ...],
    ) -> EntityDomainMigrationPlanningOutcome:
        self._validate_resolutions(request, prior, resolutions)
        return self._compile(
            request,
            resolutions=(*prior.resolutions, *resolutions),
            revision=prior.revision + 1,
            supersedes_plan_sha256=prior.plan_sha256,
        )

    def _compile(
        self,
        request: EntityDomainMigrationRequest,
        *,
        resolutions: tuple[EntityMigrationResolution, ...],
        revision: int,
        supersedes_plan_sha256: str | None,
    ) -> EntityDomainMigrationPlanningOutcome:
        resolution_by_id = {item.conflict_id: item for item in resolutions}
        grouped: dict[str, list[EntityMigrationCandidate]] = defaultdict(list)
        for candidate in request.candidates:
            grouped[candidate.source_identity_ref].append(candidate)

        selected: list[EntityMigrationCandidate] = []
        unresolved: list[EntityMigrationConflict] = []
        for source_identity_ref, candidates in sorted(grouped.items()):
            options = sorted(candidates, key=lambda item: item.candidate_id)
            automatic = len(options) == 1 and self._automatic_candidate(options[0])
            if automatic:
                selected.append(options[0])
                continue
            kind = (
                EntityMigrationConflictKind.AMBIGUOUS_SOURCE_IDENTITY
                if len(options) > 1
                else EntityMigrationConflictKind.REVIEW_REQUIRED
            )
            conflict = self._conflict(
                kind=kind,
                subject_ref=source_identity_ref,
                option_ids=tuple(item.candidate_id for item in options) + ("defer",),
                evidence=[item.candidate_sha256 for item in options],
            )
            resolution = resolution_by_id.get(conflict.conflict_id)
            if resolution is None:
                unresolved.append(conflict)
                continue
            if resolution.selected_option_id == "defer":
                return self._not_admitted("entity_conflict_deferred")
            selected.append(
                next(item for item in options if item.candidate_id == resolution.selected_option_id)
            )

        state_assertions: list[TemporalEntityAssertionDraft] = []
        by_entity: dict[str, list[EntityMigrationCandidate]] = defaultdict(list)
        for candidate in selected:
            if candidate.entity_assertion is not None:
                by_entity[candidate.entity_ref].append(candidate)
        for entity_ref, candidates in sorted(by_entity.items()):
            state_groups: dict[str, list[EntityMigrationCandidate]] = defaultdict(list)
            for candidate in candidates:
                assert candidate.entity_assertion is not None
                state_groups[_entity_state_fingerprint(candidate.entity_assertion)].append(
                    candidate
                )
            if len(state_groups) == 1:
                state_assertions.append(self._corroborated_assertion(candidates))
                continue
            options = tuple(sorted(item.candidate_id for item in candidates))
            conflict = self._conflict(
                kind=EntityMigrationConflictKind.ENTITY_STATE_CONFLICT,
                subject_ref=entity_ref,
                option_ids=(*options, "defer"),
                evidence=[item.candidate_sha256 for item in candidates],
            )
            resolution = resolution_by_id.get(conflict.conflict_id)
            if resolution is None:
                unresolved.append(conflict)
                continue
            if resolution.selected_option_id == "defer":
                return self._not_admitted("entity_state_conflict_deferred")
            winner = next(
                item for item in candidates if item.candidate_id == resolution.selected_option_id
            )
            assert winner.entity_assertion is not None
            state_assertions.append(winner.entity_assertion)

        selected_lineage: list[EntityLineageRequest] = []
        for lineage in sorted(request.lineage_requests, key=lambda item: item.event_ref):
            conflict = self._conflict(
                kind=EntityMigrationConflictKind.LINEAGE_DECISION_REQUIRED,
                subject_ref=lineage.event_ref,
                option_ids=("apply", "defer"),
                evidence=[lineage.request_sha256],
            )
            resolution = resolution_by_id.get(conflict.conflict_id)
            if resolution is None:
                unresolved.append(conflict)
                continue
            if resolution.selected_option_id == "defer":
                return self._not_admitted("entity_lineage_deferred")
            selected_lineage.append(lineage)

        if unresolved:
            plan = self._plan_model(
                request=request,
                revision=revision,
                status=EntityMigrationPlanningStatus.NEEDS_RESOLUTION,
                conflicts=tuple(sorted(unresolved, key=lambda item: item.conflict_id)),
                resolutions=resolutions,
                selected=(),
                assertions=(),
                bindings=(),
                lineages=(),
                reason_codes=("entity_conflict_resolution_required",),
                supersedes_plan_sha256=supersedes_plan_sha256,
            )
            return EntityDomainMigrationPlanningOutcome(
                status=plan.status,
                plan=plan,
                reason_codes=plan.reason_codes,
            )

        selected = sorted(selected, key=lambda item: item.candidate_id)
        bindings = tuple(
            sorted(
                (item.source_binding for item in selected),
                key=lambda item: item.source_identity_ref,
            )
        )
        if len({item.idempotency_key for item in bindings}) != len(bindings):
            return self._not_admitted("source_binding_idempotency_conflict")
        assertions = tuple(
            sorted(
                state_assertions,
                key=lambda item: (item.entity_ref, item.valid_from, item.idempotency_key),
            )
        )
        if len({item.idempotency_key for item in assertions}) != len(assertions):
            return self._not_admitted("entity_assertion_idempotency_conflict")
        plan = self._plan_model(
            request=request,
            revision=revision,
            status=EntityMigrationPlanningStatus.READY,
            conflicts=(),
            resolutions=resolutions,
            selected=tuple(item.candidate_id for item in selected),
            assertions=assertions,
            bindings=bindings,
            lineages=tuple(selected_lineage),
            reason_codes=("entity_domain_migration_admitted",),
            supersedes_plan_sha256=supersedes_plan_sha256,
        )
        return EntityDomainMigrationPlanningOutcome(
            status=plan.status,
            plan=plan,
            reason_codes=plan.reason_codes,
        )

    @staticmethod
    def _automatic_candidate(candidate: EntityMigrationCandidate) -> bool:
        assertion = candidate.entity_assertion
        return (
            candidate.source_binding.resolution_method in _AUTOMATIC_RESOLUTION_METHODS
            and candidate.source_binding.confidence_basis_points == 10_000
            and (assertion is None or assertion.mutation_kind is TemporalMutationKind.INITIAL)
        )

    @staticmethod
    def _corroborated_assertion(
        candidates: list[EntityMigrationCandidate],
    ) -> TemporalEntityAssertionDraft:
        ordered = sorted(candidates, key=lambda item: item.candidate_id)
        representative = ordered[0].entity_assertion
        assert representative is not None
        if len(ordered) == 1:
            return representative
        source_refs = tuple(
            sorted(
                {
                    value
                    for candidate in ordered
                    for value in candidate.entity_assertion.source_version_refs  # type: ignore[union-attr]
                }
            )
        )
        digest = canonical_json_fingerprint(
            {
                "entity_ref": representative.entity_ref,
                "state": _entity_state_fingerprint(representative),
                "candidate_ids": [item.candidate_id for item in ordered],
            }
        )
        return representative.model_copy(
            update={
                "source_version_refs": source_refs,
                "idempotency_key": f"entity.migrate.{digest[:32]}",
                "reason": "migrate corroborated legacy entity state",
            }
        )

    @staticmethod
    def _conflict(
        *,
        kind: EntityMigrationConflictKind,
        subject_ref: str,
        option_ids: tuple[str, ...],
        evidence: list[str],
    ) -> EntityMigrationConflict:
        digest = canonical_json_fingerprint(
            {
                "kind": kind.value,
                "subject_ref": subject_ref,
                "option_ids": option_ids,
                "evidence": sorted(evidence),
            }
        )
        return EntityMigrationConflict(
            conflict_id=f"conflict_{digest[:20]}",
            kind=kind,
            subject_ref=subject_ref,
            option_ids=option_ids,
            evidence_sha256=digest,
        )

    def _plan_model(
        self,
        *,
        request: EntityDomainMigrationRequest,
        revision: int,
        status: EntityMigrationPlanningStatus,
        conflicts: tuple[EntityMigrationConflict, ...],
        resolutions: tuple[EntityMigrationResolution, ...],
        selected: tuple[str, ...],
        assertions: tuple[TemporalEntityAssertionDraft, ...],
        bindings: tuple[EntitySourceBindingDraft, ...],
        lineages: tuple[EntityLineageRequest, ...],
        reason_codes: tuple[str, ...],
        supersedes_plan_sha256: str | None,
    ) -> EntityDomainMigrationPlan:
        values: dict[str, Any] = {
            "request": request,
            "revision": revision,
            "status": status,
            "conflicts": conflicts,
            "resolutions": resolutions,
            "selected_candidate_ids": selected,
            "entity_assertions": assertions,
            "source_bindings": bindings,
            "lineage_requests": lineages,
            "reason_codes": reason_codes,
            "execution_allowed": status is EntityMigrationPlanningStatus.READY,
            "supersedes_plan_sha256": supersedes_plan_sha256,
            "created_at": self._now(),
        }
        return EntityDomainMigrationPlan(
            **values,
            plan_sha256=_fingerprint(
                EntityDomainMigrationPlan.schema_id,
                values,
                "plan_sha256",
            ),
        )

    @staticmethod
    def _not_admitted(reason: str) -> EntityDomainMigrationPlanningOutcome:
        return EntityDomainMigrationPlanningOutcome(
            status=EntityMigrationPlanningStatus.NOT_ADMITTED,
            reason_codes=(reason,),
        )

    def _validate_resolutions(
        self,
        request: EntityDomainMigrationRequest,
        prior: EntityDomainMigrationPlan,
        resolutions: tuple[EntityMigrationResolution, ...],
    ) -> None:
        if (
            prior.request != request
            or prior.status is not EntityMigrationPlanningStatus.NEEDS_RESOLUTION
            or not prior.conflicts
        ):
            raise EntityMigrationResolutionError("prior migration plan is not awaiting resolution")
        expected = {item.conflict_id: item for item in prior.conflicts}
        supplied = {item.conflict_id: item for item in resolutions}
        if len(supplied) != len(resolutions) or set(supplied) != set(expected):
            raise EntityMigrationResolutionError("entity conflict resolution set is incomplete")
        now = _aware_utc(self._now(), "now")
        for conflict_id, resolution in supplied.items():
            conflict = expected[conflict_id]
            if (
                resolution.request_sha256 != request.request_sha256
                or resolution.prior_plan_sha256 != prior.plan_sha256
                or resolution.selected_option_id not in conflict.option_ids
                or resolution.confirmed_at > now
            ):
                raise EntityMigrationResolutionError(
                    "entity conflict resolution binding or option drifted"
                )


class TemporalEntityMigrationAuthority(Protocol):
    def record_batch(
        self,
        drafts: tuple[TemporalEntityAssertionDraft, ...],
        *,
        max_batch_size: int = 500,
    ) -> tuple[TemporalEntityAssertion, ...]: ...


class EntitySourceMigrationAuthority(Protocol):
    def bind_sources_batch(
        self,
        drafts: tuple[EntitySourceBindingDraft, ...],
        *,
        max_batch_size: int = 500,
    ) -> tuple[EntitySourceBinding, ...]: ...


class EntityLineageMigrationAuthority(Protocol):
    def record(self, request: EntityLineageRequest) -> EntityLineageReceipt: ...


class EntityMigrationStageReceipt(_FrozenContract):
    stage: EntityMigrationStage
    status: EntityMigrationStageStatus
    input_sha256: Sha256
    output_sha256: Sha256 | None = None
    attempted_operation_count: int = Field(ge=0)
    completed_operation_count: int = Field(ge=0)
    error_code: ShortName | None = None

    @model_validator(mode="after")
    def _consistent_stage(self) -> EntityMigrationStageReceipt:
        if self.completed_operation_count > self.attempted_operation_count:
            raise ValueError("migration stage completed count exceeds attempted count")
        if self.status is EntityMigrationStageStatus.COMPLETED:
            if self.completed_operation_count != self.attempted_operation_count:
                raise ValueError("completed migration stage has incomplete operations")
            if self.output_sha256 is None or self.error_code is not None:
                raise ValueError("completed migration stage receipt is inconsistent")
        elif self.status is EntityMigrationStageStatus.FAILED:
            if self.error_code is None:
                raise ValueError("failed migration stage requires an error code")
        elif (
            self.attempted_operation_count
            or self.completed_operation_count
            or self.output_sha256 is not None
            or self.error_code is not None
        ):
            raise ValueError("skipped migration stage cannot claim work")
        return self


class EntityDomainMigrationExecutionResult(_FrozenContract):
    schema_id: ClassVar[str] = "gda.entity-domain-migration-result.v1"
    request_sha256: Sha256
    plan_sha256: Sha256
    status: EntityMigrationExecutionStatus
    stage_receipts: tuple[EntityMigrationStageReceipt, ...]
    completed_authority_operations: int = Field(ge=0)
    authority_idempotency_required: bool = True
    cross_stage_atomic: bool = False
    generated_at: datetime
    result_sha256: Sha256

    @field_validator("generated_at")
    @classmethod
    def _valid_generated_at(cls, value: datetime) -> datetime:
        return _aware_utc(value, "generated_at")

    @model_validator(mode="after")
    def _sealed_result(self) -> EntityDomainMigrationExecutionResult:
        failures = tuple(
            item for item in self.stage_receipts if item.status is EntityMigrationStageStatus.FAILED
        )
        if self.status is EntityMigrationExecutionStatus.COMPLETED and failures:
            raise ValueError("completed entity migration contains a failed stage")
        if self.status is EntityMigrationExecutionStatus.RECONCILING and not failures:
            raise ValueError("reconciling entity migration requires a failed stage")
        if self.completed_authority_operations != sum(
            item.completed_operation_count for item in self.stage_receipts
        ):
            raise ValueError("entity migration completed operation count drifted")
        if not self.authority_idempotency_required or self.cross_stage_atomic:
            raise ValueError("entity migration execution boundary is misrepresented")
        expected = _fingerprint(
            self.schema_id,
            self.model_dump(mode="json", exclude={"result_sha256"}),
            "result_sha256",
        )
        if self.result_sha256 != expected:
            raise ValueError("entity migration result fingerprint is invalid")
        return self


class EntityDomainMigrationExecutor:
    """Execute admitted stages; partial completion always becomes reconciliation."""

    def __init__(
        self,
        temporal_authority: TemporalEntityMigrationAuthority,
        source_authority: EntitySourceMigrationAuthority,
        lineage_authority: EntityLineageMigrationAuthority,
        *,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._temporal = temporal_authority
        self._sources = source_authority
        self._lineage = lineage_authority
        self._now = now or (lambda: datetime.now(UTC))

    def execute(
        self,
        plan: EntityDomainMigrationPlan,
    ) -> EntityDomainMigrationExecutionResult:
        if plan.status is not EntityMigrationPlanningStatus.READY or not plan.execution_allowed:
            raise EntityMigrationAdmissionError("entity domain migration plan is not executable")
        receipts: list[EntityMigrationStageReceipt] = []
        failure = self._execute_assertions(plan, receipts)
        if failure is None:
            failure = self._execute_bindings(plan, receipts)
        if failure is None:
            failure = self._execute_lineages(plan, receipts)
        status = (
            EntityMigrationExecutionStatus.RECONCILING
            if failure is not None
            else EntityMigrationExecutionStatus.COMPLETED
        )
        values: dict[str, Any] = {
            "request_sha256": plan.request.request_sha256,
            "plan_sha256": plan.plan_sha256,
            "status": status,
            "stage_receipts": tuple(receipts),
            "completed_authority_operations": sum(
                item.completed_operation_count for item in receipts
            ),
            "authority_idempotency_required": True,
            "cross_stage_atomic": False,
            "generated_at": self._now(),
        }
        return EntityDomainMigrationExecutionResult(
            **values,
            result_sha256=_fingerprint(
                EntityDomainMigrationExecutionResult.schema_id,
                values,
                "result_sha256",
            ),
        )

    def _execute_assertions(
        self,
        plan: EntityDomainMigrationPlan,
        receipts: list[EntityMigrationStageReceipt],
    ) -> Exception | None:
        return self._execute_batched_stage(
            stage=EntityMigrationStage.ENTITY_ASSERTIONS,
            items=plan.entity_assertions,
            batch_size=plan.request.budget.batch_size,
            callback=self._temporal.record_batch,
            receipts=receipts,
        )

    def _execute_bindings(
        self,
        plan: EntityDomainMigrationPlan,
        receipts: list[EntityMigrationStageReceipt],
    ) -> Exception | None:
        return self._execute_batched_stage(
            stage=EntityMigrationStage.SOURCE_BINDINGS,
            items=plan.source_bindings,
            batch_size=plan.request.budget.batch_size,
            callback=self._sources.bind_sources_batch,
            receipts=receipts,
        )

    def _execute_lineages(
        self,
        plan: EntityDomainMigrationPlan,
        receipts: list[EntityMigrationStageReceipt],
    ) -> Exception | None:
        items = plan.lineage_requests
        input_sha256 = canonical_json_fingerprint(_jsonable(items))
        if not items:
            receipts.append(
                EntityMigrationStageReceipt(
                    stage=EntityMigrationStage.LINEAGE_EVENTS,
                    status=EntityMigrationStageStatus.SKIPPED,
                    input_sha256=input_sha256,
                    attempted_operation_count=0,
                    completed_operation_count=0,
                )
            )
            return None
        output: list[Any] = []
        completed = 0
        try:
            for lineage in items:
                output.append(self._lineage.record(lineage))
                completed += 1
        except Exception as exc:
            receipts.append(
                self._failed_stage(
                    stage=EntityMigrationStage.LINEAGE_EVENTS,
                    input_sha256=input_sha256,
                    attempted=len(items),
                    completed=completed,
                    output=output,
                    exc=exc,
                )
            )
            return exc
        receipts.append(
            EntityMigrationStageReceipt(
                stage=EntityMigrationStage.LINEAGE_EVENTS,
                status=EntityMigrationStageStatus.COMPLETED,
                input_sha256=input_sha256,
                output_sha256=canonical_json_fingerprint(_jsonable(output)),
                attempted_operation_count=len(items),
                completed_operation_count=completed,
            )
        )
        return None

    def _execute_batched_stage(
        self,
        *,
        stage: EntityMigrationStage,
        items: tuple[Any, ...],
        batch_size: int,
        callback: Callable[..., tuple[Any, ...]],
        receipts: list[EntityMigrationStageReceipt],
    ) -> Exception | None:
        input_sha256 = canonical_json_fingerprint(_jsonable(items))
        if not items:
            receipts.append(
                EntityMigrationStageReceipt(
                    stage=stage,
                    status=EntityMigrationStageStatus.SKIPPED,
                    input_sha256=input_sha256,
                    attempted_operation_count=0,
                    completed_operation_count=0,
                )
            )
            return None
        output: list[Any] = []
        completed = 0
        try:
            for offset in range(0, len(items), batch_size):
                chunk = items[offset : offset + batch_size]
                result = tuple(callback(chunk, max_batch_size=batch_size))
                if len(result) != len(chunk):
                    raise EntityMigrationError(
                        "entity migration authority returned an incomplete batch"
                    )
                output.extend(result)
                completed += len(result)
        except Exception as exc:
            receipts.append(
                self._failed_stage(
                    stage=stage,
                    input_sha256=input_sha256,
                    attempted=len(items),
                    completed=completed,
                    output=output,
                    exc=exc,
                )
            )
            return exc
        receipts.append(
            EntityMigrationStageReceipt(
                stage=stage,
                status=EntityMigrationStageStatus.COMPLETED,
                input_sha256=input_sha256,
                output_sha256=canonical_json_fingerprint(_jsonable(output)),
                attempted_operation_count=len(items),
                completed_operation_count=completed,
            )
        )
        return None

    @staticmethod
    def _failed_stage(
        *,
        stage: EntityMigrationStage,
        input_sha256: str,
        attempted: int,
        completed: int,
        output: list[Any],
        exc: Exception,
    ) -> EntityMigrationStageReceipt:
        return EntityMigrationStageReceipt(
            stage=stage,
            status=EntityMigrationStageStatus.FAILED,
            input_sha256=input_sha256,
            output_sha256=(canonical_json_fingerprint(_jsonable(output)) if output else None),
            attempted_operation_count=attempted,
            completed_operation_count=completed,
            error_code=type(exc).__name__,
        )


__all__ = [
    "EntityDomainMigrationBudget",
    "EntityDomainMigrationExecutionResult",
    "EntityDomainMigrationExecutor",
    "EntityDomainMigrationPlan",
    "EntityDomainMigrationPlanner",
    "EntityDomainMigrationPlanningOutcome",
    "EntityDomainMigrationRequest",
    "EntityLineageMigrationAuthority",
    "EntityMigrationAdmissionError",
    "EntityMigrationCandidate",
    "EntityMigrationConflict",
    "EntityMigrationConflictKind",
    "EntityMigrationError",
    "EntityMigrationExecutionStatus",
    "EntityMigrationPlanningStatus",
    "EntityMigrationResolution",
    "EntityMigrationResolutionError",
    "EntityMigrationStage",
    "EntityMigrationStageReceipt",
    "EntityMigrationStageStatus",
    "EntitySourceMigrationAuthority",
    "TemporalEntityMigrationAuthority",
    "build_entity_domain_migration_request",
    "build_entity_migration_candidate",
]
