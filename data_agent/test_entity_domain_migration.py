"""Contract tests for conflict-safe migration into entity authorities."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

import pytest
from pydantic import ValidationError

from data_agent.entity_domain_migration import (
    EntityDomainMigrationExecutor,
    EntityDomainMigrationPlanner,
    EntityMigrationAdmissionError,
    EntityMigrationCandidate,
    EntityMigrationConflictKind,
    EntityMigrationExecutionStatus,
    EntityMigrationPlanningStatus,
    EntityMigrationResolution,
    EntityMigrationResolutionError,
    EntityMigrationStage,
    EntityMigrationStageStatus,
    build_entity_domain_migration_request,
    build_entity_migration_candidate,
)
from data_agent.entity_lineage_authority import (
    EntityLineageKind,
    EntityLineageRequest,
)
from data_agent.entity_link_authority import (
    EntityResolutionMethod,
    EntitySourceBindingDraft,
)
from data_agent.temporal_entity_authority import (
    TemporalEntityAssertionDraft,
    TemporalLifecycleState,
    TemporalMutationKind,
)

TENANT = "entity-migration"
NOW = datetime(2026, 8, 19, 15, tzinfo=UTC)
EFFECTIVE_AT = datetime(2026, 7, 1, 10, tzinfo=UTC)
SOURCE_DOMAIN = f"gda://{TENANT}/resource/legacy-parcel-domain"
SOURCE_SYSTEM = f"gda://{TENANT}/resource/legacy-parcel-system"
SOURCE_SNAPSHOT = f"gda://{TENANT}/resource_version/legacy-parcels-v1"
OTHER_SNAPSHOT = f"gda://{TENANT}/resource_version/legacy-parcels-v2"
MAPPING_CONTRACT = f"gda://{TENANT}/resource_version/legacy-mapping-v1"
ENTITY_A = f"gda://{TENANT}/entity/parcel-a"
ENTITY_B = f"gda://{TENANT}/entity/parcel-b"
ENTITY_MERGED = f"gda://{TENANT}/entity/parcel-merged"
SOURCE_IDENTITY_A = f"gda://{TENANT}/source_identity/legacy-a"
SOURCE_IDENTITY_B = f"gda://{TENANT}/source_identity/legacy-b"


def _binding(
    *,
    source_identity_ref: str = SOURCE_IDENTITY_A,
    entity_ref: str = ENTITY_A,
    source_object_id: str = "legacy-a",
    source_version_ref: str = SOURCE_SNAPSHOT,
    resolution_method: EntityResolutionMethod = (EntityResolutionMethod.AUTHORITATIVE_IDENTIFIER),
    confidence_basis_points: int = 10_000,
    idempotency_key: str | None = None,
) -> EntitySourceBindingDraft:
    return EntitySourceBindingDraft(
        tenant_id=TENANT,
        source_identity_ref=source_identity_ref,
        source_system_ref=SOURCE_SYSTEM,
        source_object_type="legacy.parcel",
        source_object_id=source_object_id,
        entity_ref=entity_ref,
        entity_object_type="natural_resource.parcel",
        ontology_class_uri="https://example.test/ontology/Parcel",
        source_version_ref=source_version_ref,
        valid_from=EFFECTIVE_AT,
        resolution_method=resolution_method,
        confidence_basis_points=confidence_basis_points,
        evidence={"source_object_id": source_object_id},
        idempotency_key=(
            idempotency_key or f"binding.{source_object_id}.{entity_ref.rsplit('/', 1)[-1]}"
        ),
        owner_subject="team:natural-resource-governance",
        recorded_by="workload:legacy-domain-migrator",
        reason="bind legacy source identity to governed entity",
    )


def _assertion(
    *,
    entity_ref: str = ENTITY_A,
    name: str = "parcel A",
    idempotency_key: str | None = None,
    mutation_kind: TemporalMutationKind = TemporalMutationKind.INITIAL,
    supersedes_assertion_id: UUID | None = None,
) -> TemporalEntityAssertionDraft:
    return TemporalEntityAssertionDraft(
        tenant_id=TENANT,
        entity_ref=entity_ref,
        object_type="natural_resource.parcel",
        lifecycle_state=TemporalLifecycleState.ACTIVE,
        attributes={"name": name, "geometry_sha256": "a" * 64},
        valid_from=EFFECTIVE_AT,
        source_version_refs=(SOURCE_SNAPSHOT,),
        mutation_kind=mutation_kind,
        supersedes_assertion_id=supersedes_assertion_id,
        idempotency_key=(
            idempotency_key or f"assertion.{entity_ref.rsplit('/', 1)[-1]}.{name.replace(' ', '-')}"
        ),
        owner_subject="team:natural-resource-governance",
        recorded_by="workload:legacy-domain-migrator",
        reason="migrate legacy entity state without overwriting history",
    )


def _candidate(
    candidate_id: str = "candidate_a",
    *,
    source_identity_ref: str = SOURCE_IDENTITY_A,
    entity_ref: str = ENTITY_A,
    source_object_id: str = "legacy-a",
    name: str = "parcel A",
    resolution_method: EntityResolutionMethod = (EntityResolutionMethod.AUTHORITATIVE_IDENTIFIER),
    confidence_basis_points: int = 10_000,
    assertion: TemporalEntityAssertionDraft | None | bool = True,
):
    binding = _binding(
        source_identity_ref=source_identity_ref,
        entity_ref=entity_ref,
        source_object_id=source_object_id,
        resolution_method=resolution_method,
        confidence_basis_points=confidence_basis_points,
        idempotency_key=f"binding.{candidate_id}",
    )
    entity_assertion = (
        _assertion(
            entity_ref=entity_ref,
            name=name,
            idempotency_key=f"assertion.{candidate_id}",
        )
        if assertion is True
        else assertion
    )
    return build_entity_migration_candidate(
        tenant_id=TENANT,
        candidate_id=candidate_id,
        source_identity_ref=source_identity_ref,
        entity_ref=entity_ref,
        entity_assertion=entity_assertion,
        source_binding=binding,
        evidence_refs=(SOURCE_SNAPSHOT,),
    )


def _lineage() -> EntityLineageRequest:
    return EntityLineageRequest(
        tenant_id=TENANT,
        event_ref=f"gda://{TENANT}/entity_lineage/merge-a-b",
        lineage_kind=EntityLineageKind.MERGE,
        effective_at=EFFECTIVE_AT,
        source_entity_refs=(ENTITY_A, ENTITY_B),
        target_entity_refs=(ENTITY_MERGED,),
        source_version_refs=(SOURCE_SNAPSHOT,),
        link_propagations=(),
        source_identity_redirects=(),
        idempotency_key="lineage.merge-a-b",
        owner_subject="team:natural-resource-governance",
        recorded_by="agent:entity-resolution-planner",
        reason="merge duplicate legacy parcel identities after review",
    )


def _request(*candidates, lineage_requests=()):
    return build_entity_domain_migration_request(
        tenant_id=TENANT,
        migration_id="legacy-parcels-v1",
        source_domain_ref=SOURCE_DOMAIN,
        source_snapshot_refs=(SOURCE_SNAPSHOT,),
        mapping_contract_ref=MAPPING_CONTRACT,
        mapping_contract_sha256="b" * 64,
        effective_at=EFFECTIVE_AT,
        candidates=tuple(candidates or (_candidate(),)),
        lineage_requests=tuple(lineage_requests),
        requested_by="workload:legacy-domain-migrator",
    )


def _resolutions(plan, selections=None):
    selections = selections or {}
    return tuple(
        EntityMigrationResolution(
            request_sha256=plan.request.request_sha256,
            prior_plan_sha256=plan.plan_sha256,
            conflict_id=conflict.conflict_id,
            selected_option_id=selections.get(
                conflict.conflict_id,
                next(value for value in conflict.option_ids if value != "defer"),
            ),
            confirmed_by="human:data-steward",
            confirmed_at=NOW,
        )
        for conflict in plan.conflicts
    )


def test_candidate_and_request_are_tenant_version_and_fingerprint_bound() -> None:
    candidate = _candidate()
    payload = candidate.model_dump(mode="json")
    payload["candidate_sha256"] = "c" * 64
    with pytest.raises(ValidationError, match="fingerprint is invalid"):
        EntityMigrationCandidate.model_validate(payload)

    mismatched_binding = _binding(entity_ref=ENTITY_B)
    with pytest.raises(ValidationError, match="binding identity differ"):
        build_entity_migration_candidate(
            tenant_id=TENANT,
            candidate_id="candidate_mismatch",
            source_identity_ref=SOURCE_IDENTITY_A,
            entity_ref=ENTITY_A,
            entity_assertion=_assertion(),
            source_binding=mismatched_binding,
            evidence_refs=(SOURCE_SNAPSHOT,),
        )

    unpinned = build_entity_migration_candidate(
        tenant_id=TENANT,
        candidate_id="candidate_unpinned",
        source_identity_ref=SOURCE_IDENTITY_A,
        entity_ref=ENTITY_A,
        source_binding=_binding(source_version_ref=OTHER_SNAPSHOT),
        evidence_refs=(OTHER_SNAPSHOT,),
    )
    with pytest.raises(ValidationError, match="unpinned"):
        _request(unpinned)


def test_exact_authoritative_candidates_compile_to_existing_authority_contracts() -> None:
    candidate_a = _candidate()
    candidate_b = _candidate(
        "candidate_b",
        source_identity_ref=SOURCE_IDENTITY_B,
        entity_ref=ENTITY_B,
        source_object_id="legacy-b",
        name="parcel B",
    )

    outcome = EntityDomainMigrationPlanner(now=lambda: NOW).plan(_request(candidate_a, candidate_b))

    assert outcome.status is EntityMigrationPlanningStatus.READY
    assert outcome.plan.execution_allowed is True
    assert outcome.plan.selected_candidate_ids == ("candidate_a", "candidate_b")
    assert len(outcome.plan.entity_assertions) == 2
    assert len(outcome.plan.source_bindings) == 2
    assert outcome.plan.lineage_requests == ()


def test_non_authoritative_or_low_confidence_match_requires_human_resolution() -> None:
    candidate = _candidate(
        resolution_method=EntityResolutionMethod.SPATIAL_OVERLAY,
        confidence_basis_points=9_000,
    )
    planner = EntityDomainMigrationPlanner(now=lambda: NOW)
    first = planner.plan(_request(candidate))

    assert first.status is EntityMigrationPlanningStatus.NEEDS_RESOLUTION
    assert first.plan.conflicts[0].kind is EntityMigrationConflictKind.REVIEW_REQUIRED
    assert first.plan.execution_allowed is False
    assert first.plan.entity_assertions == ()
    assert first.plan.source_bindings == ()

    second = planner.replan(first.plan.request, first.plan, _resolutions(first.plan))
    assert second.status is EntityMigrationPlanningStatus.READY
    assert second.plan.revision == 1
    assert second.plan.supersedes_plan_sha256 == first.plan.plan_sha256


def test_historical_correction_requires_review_and_preserves_supersedes() -> None:
    superseded = UUID("00000000-0000-4000-8000-000000000001")
    correction = _assertion(
        name="corrected historical parcel",
        mutation_kind=TemporalMutationKind.CORRECTION,
        supersedes_assertion_id=superseded,
    )
    candidate = _candidate(assertion=correction)
    planner = EntityDomainMigrationPlanner(now=lambda: NOW)

    first = planner.plan(_request(candidate))
    second = planner.replan(first.plan.request, first.plan, _resolutions(first.plan))

    assert first.plan.conflicts[0].kind is EntityMigrationConflictKind.REVIEW_REQUIRED
    assert second.status is EntityMigrationPlanningStatus.READY
    assert second.plan.entity_assertions[0].mutation_kind is TemporalMutationKind.CORRECTION
    assert second.plan.entity_assertions[0].supersedes_assertion_id == superseded


def test_ambiguous_identity_is_not_silently_selected_and_defer_stops_plan() -> None:
    candidate_a = _candidate("candidate_a")
    candidate_b = _candidate("candidate_b", entity_ref=ENTITY_B, name="parcel B")
    planner = EntityDomainMigrationPlanner(now=lambda: NOW)
    first = planner.plan(_request(candidate_a, candidate_b))

    assert first.status is EntityMigrationPlanningStatus.NEEDS_RESOLUTION
    conflict = first.plan.conflicts[0]
    assert conflict.kind is EntityMigrationConflictKind.AMBIGUOUS_SOURCE_IDENTITY
    assert set(conflict.option_ids) == {"candidate_a", "candidate_b", "defer"}

    deferred = planner.replan(
        first.plan.request,
        first.plan,
        _resolutions(first.plan, {conflict.conflict_id: "defer"}),
    )
    assert deferred.status is EntityMigrationPlanningStatus.NOT_ADMITTED
    assert deferred.reason_codes == ("entity_conflict_deferred",)


def test_resolution_is_human_bound_complete_and_cannot_replay_on_stale_plan() -> None:
    planner = EntityDomainMigrationPlanner(now=lambda: NOW)
    first = planner.plan(
        _request(
            _candidate("candidate_a"),
            _candidate("candidate_b", entity_ref=ENTITY_B, name="parcel B"),
        )
    )
    conflict = first.plan.conflicts[0]

    with pytest.raises(ValidationError, match="human confirmer"):
        EntityMigrationResolution(
            request_sha256=first.plan.request.request_sha256,
            prior_plan_sha256=first.plan.plan_sha256,
            conflict_id=conflict.conflict_id,
            selected_option_id="candidate_a",
            confirmed_by="agent:matcher",
            confirmed_at=NOW,
        )
    with pytest.raises(EntityMigrationResolutionError, match="incomplete"):
        planner.replan(first.plan.request, first.plan, ())

    resolution = _resolutions(first.plan)[0]
    drifted = resolution.model_copy(update={"prior_plan_sha256": "d" * 64})
    with pytest.raises(EntityMigrationResolutionError, match="drifted"):
        planner.replan(first.plan.request, first.plan, (drifted,))


def test_new_state_conflict_can_require_a_second_bound_resolution_round() -> None:
    ambiguous_a = _candidate(
        "candidate_a_shared",
        entity_ref=ENTITY_MERGED,
        name="state from source A",
    )
    ambiguous_other = _candidate(
        "candidate_a_other",
        entity_ref=ENTITY_A,
        name="separate entity A",
    )
    automatic_b = _candidate(
        "candidate_b_shared",
        source_identity_ref=SOURCE_IDENTITY_B,
        entity_ref=ENTITY_MERGED,
        source_object_id="legacy-b",
        name="state from source B",
    )
    planner = EntityDomainMigrationPlanner(now=lambda: NOW)
    first = planner.plan(_request(ambiguous_a, ambiguous_other, automatic_b))
    source_conflict = first.plan.conflicts[0]

    second = planner.replan(
        first.plan.request,
        first.plan,
        _resolutions(
            first.plan,
            {source_conflict.conflict_id: "candidate_a_shared"},
        ),
    )

    assert second.status is EntityMigrationPlanningStatus.NEEDS_RESOLUTION
    assert second.plan.revision == 1
    assert len(second.plan.resolutions) == 1
    state_conflict = second.plan.conflicts[0]
    assert state_conflict.kind is EntityMigrationConflictKind.ENTITY_STATE_CONFLICT

    third = planner.replan(
        second.plan.request,
        second.plan,
        _resolutions(
            second.plan,
            {state_conflict.conflict_id: "candidate_b_shared"},
        ),
    )

    assert third.status is EntityMigrationPlanningStatus.READY
    assert third.plan.revision == 2
    assert len(third.plan.resolutions) == 2
    assert len(third.plan.source_bindings) == 2
    assert len(third.plan.entity_assertions) == 1
    assert third.plan.entity_assertions[0].attributes["name"] == "state from source B"


def test_corroborating_sources_share_one_state_without_losing_source_bindings() -> None:
    candidate_a = _candidate("candidate_a", entity_ref=ENTITY_MERGED, name="same")
    candidate_b = _candidate(
        "candidate_b",
        source_identity_ref=SOURCE_IDENTITY_B,
        entity_ref=ENTITY_MERGED,
        source_object_id="legacy-b",
        name="same",
    )

    outcome = EntityDomainMigrationPlanner(now=lambda: NOW).plan(_request(candidate_a, candidate_b))

    assert outcome.status is EntityMigrationPlanningStatus.READY
    assert len(outcome.plan.source_bindings) == 2
    assert len(outcome.plan.entity_assertions) == 1
    assert outcome.plan.entity_assertions[0].idempotency_key.startswith("entity.migrate.")


def test_merge_split_or_replacement_is_always_an_explicit_human_decision() -> None:
    request = _request(
        _candidate(entity_ref=ENTITY_MERGED),
        lineage_requests=(_lineage(),),
    )
    planner = EntityDomainMigrationPlanner(now=lambda: NOW)
    first = planner.plan(request)

    lineage_conflict = next(
        item
        for item in first.plan.conflicts
        if item.kind is EntityMigrationConflictKind.LINEAGE_DECISION_REQUIRED
    )
    assert lineage_conflict.option_ids == ("apply", "defer")

    second = planner.replan(request, first.plan, _resolutions(first.plan))
    assert second.status is EntityMigrationPlanningStatus.READY
    assert second.plan.lineage_requests == (_lineage(),)


class _TemporalAuthority:
    def __init__(self, *, fail: bool = False):
        self.fail = fail
        self.calls = []

    def record_batch(self, drafts, *, max_batch_size=500):
        self.calls.append((tuple(drafts), max_batch_size))
        if self.fail:
            raise RuntimeError("temporal write failed")
        return tuple(drafts)


class _SourceAuthority:
    def __init__(self, *, fail: bool = False):
        self.fail = fail
        self.calls = []

    def bind_sources_batch(self, drafts, *, max_batch_size=500):
        self.calls.append((tuple(drafts), max_batch_size))
        if self.fail:
            raise RuntimeError("source binding failed")
        return tuple(drafts)


class _LineageAuthority:
    def __init__(self, *, fail: bool = False):
        self.fail = fail
        self.calls = []

    def record(self, request):
        self.calls.append(request)
        if self.fail:
            raise RuntimeError("lineage write failed")
        return request


def _executor(temporal=None, sources=None, lineage=None):
    return EntityDomainMigrationExecutor(
        temporal or _TemporalAuthority(),
        sources or _SourceAuthority(),
        lineage or _LineageAuthority(),
        now=lambda: NOW,
    )


def test_unresolved_plan_performs_zero_authority_calls() -> None:
    outcome = EntityDomainMigrationPlanner(now=lambda: NOW).plan(
        _request(
            _candidate("candidate_a"),
            _candidate("candidate_b", entity_ref=ENTITY_B, name="parcel B"),
        )
    )
    temporal = _TemporalAuthority()
    sources = _SourceAuthority()
    lineage = _LineageAuthority()

    with pytest.raises(EntityMigrationAdmissionError, match="not executable"):
        _executor(temporal, sources, lineage).execute(outcome.plan)

    assert temporal.calls == []
    assert sources.calls == []
    assert lineage.calls == []


def test_ready_plan_executes_existing_authorities_and_replays_exact_intent() -> None:
    plan = EntityDomainMigrationPlanner(now=lambda: NOW).plan(_request(_candidate())).plan
    temporal = _TemporalAuthority()
    sources = _SourceAuthority()
    lineage = _LineageAuthority()
    executor = _executor(temporal, sources, lineage)

    first = executor.execute(plan)
    second = executor.execute(plan)

    assert first.status is EntityMigrationExecutionStatus.COMPLETED
    assert second.result_sha256 == first.result_sha256
    assert [item.status for item in first.stage_receipts] == [
        EntityMigrationStageStatus.COMPLETED,
        EntityMigrationStageStatus.COMPLETED,
        EntityMigrationStageStatus.SKIPPED,
    ]
    assert first.completed_authority_operations == 2
    assert first.cross_stage_atomic is False
    assert len(temporal.calls) == 2
    assert len(sources.calls) == 2
    assert temporal.calls[0] == temporal.calls[1]
    assert sources.calls[0] == sources.calls[1]


def test_human_applied_lineage_reaches_existing_lineage_authority() -> None:
    request = _request(_candidate(entity_ref=ENTITY_MERGED), lineage_requests=(_lineage(),))
    planner = EntityDomainMigrationPlanner(now=lambda: NOW)
    first = planner.plan(request)
    ready = planner.replan(request, first.plan, _resolutions(first.plan)).plan
    lineage = _LineageAuthority()

    result = _executor(lineage=lineage).execute(ready)

    assert result.status is EntityMigrationExecutionStatus.COMPLETED
    assert result.completed_authority_operations == 3
    assert lineage.calls == [_lineage()]
    assert result.stage_receipts[-1].stage is EntityMigrationStage.LINEAGE_EVENTS
    assert result.stage_receipts[-1].status is EntityMigrationStageStatus.COMPLETED


def test_partial_stage_failure_enters_reconciliation_and_stops_later_writes() -> None:
    request = _request(_candidate(), lineage_requests=(_lineage(),))
    planner = EntityDomainMigrationPlanner(now=lambda: NOW)
    first = planner.plan(request)
    ready = planner.replan(request, first.plan, _resolutions(first.plan)).plan
    temporal = _TemporalAuthority()
    sources = _SourceAuthority(fail=True)
    lineage = _LineageAuthority()

    result = _executor(temporal, sources, lineage).execute(ready)

    assert result.status is EntityMigrationExecutionStatus.RECONCILING
    assert result.completed_authority_operations == 1
    assert result.stage_receipts[-1].stage is EntityMigrationStage.SOURCE_BINDINGS
    assert result.stage_receipts[-1].status is EntityMigrationStageStatus.FAILED
    assert result.stage_receipts[-1].error_code == "RuntimeError"
    assert len(temporal.calls) == 1
    assert len(sources.calls) == 1
    assert lineage.calls == []


def test_incomplete_authority_batch_is_not_reported_as_success() -> None:
    class _IncompleteTemporal(_TemporalAuthority):
        def record_batch(self, drafts, *, max_batch_size=500):
            self.calls.append((tuple(drafts), max_batch_size))
            return ()

    plan = EntityDomainMigrationPlanner(now=lambda: NOW).plan(_request(_candidate())).plan
    result = _executor(_IncompleteTemporal()).execute(plan)

    assert result.status is EntityMigrationExecutionStatus.RECONCILING
    assert result.completed_authority_operations == 0
    assert result.stage_receipts[0].error_code == "EntityMigrationError"
