"""Contracts for source identity evidence and bitemporal instance links."""

from __future__ import annotations

import hashlib
import json
import shutil
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import MagicMock
from uuid import UUID

import pytest
from pydantic import ValidationError

from data_agent.chongqing_entity_link_baseline import (
    CUSTOMER_BUNDLE_DIR,
    ONTOLOGY_PACKAGE_DIR,
    ONTOLOGY_PACKAGE_ID,
    ONTOLOGY_PACKAGE_SHA256,
    ChongqingBaselineError,
    build_chongqing_entity_link_baseline,
)
from data_agent.entity_link_authority import (
    GATEWAY_DATABASE_ROLE,
    EntityLinkAuthority,
    EntityLinkHistoryError,
    EntityLinkNotFoundError,
    EntityLinkValidationError,
    EntityResolutionMethod,
    EntitySourceBinding,
    EntitySourceBindingDraft,
    InstanceLinkAssertion,
    InstanceLinkAssertionDraft,
    InstanceLinkKind,
    InstanceLinkLifecycle,
    InstanceLinkMutationKind,
    InstanceLinkQuery,
    InstanceLinkQueryMode,
    InstanceLinkReviewStatus,
    InstanceLinkTypeDraft,
    resolve_instance_link_snapshot,
)

TENANT = "entity-link-contract"
LINK_REF = f"gda://{TENANT}/entity_link/parcel-constraint-001"
LINK_TYPE_REF = f"gda://{TENANT}/link_type/intersects-v1"
SOURCE_ENTITY_REF = f"gda://{TENANT}/entity/parcel-001"
TARGET_ENTITY_REF = f"gda://{TENANT}/entity/constraint-001"
SOURCE_VERSION_REF = f"gda://{TENANT}/resource_version/source-v1"
EVALUATED_AT = datetime(2026, 8, 14, 12, tzinfo=UTC)


def _at(month: int, day: int = 1) -> datetime:
    return datetime(2026, month, day, 10, tzinfo=UTC)


def _binding(**changes) -> EntitySourceBindingDraft:
    values = {
        "tenant_id": TENANT,
        "source_identity_ref": f"gda://{TENANT}/source_identity/parcel-001",
        "source_system_ref": f"gda://{TENANT}/resource/customer-parcels",
        "source_object_type": "natural_resource.land_parcel",
        "source_object_id": "parcel-001",
        "entity_ref": SOURCE_ENTITY_REF,
        "entity_object_type": "natural_resource.land_parcel",
        "ontology_class_uri": "https://example.test/ontology/LandParcel",
        "source_version_ref": SOURCE_VERSION_REF,
        "valid_from": _at(1),
        "resolution_method": EntityResolutionMethod.AUTHORITATIVE_IDENTIFIER,
        "confidence_basis_points": 10_000,
        "evidence": {"identity_field": "parcel_id"},
        "idempotency_key": "source.parcel-001.v1",
        "owner_subject": "team:natural-resource-governance",
        "recorded_by": "agent:entity-link-test",
        "reason": "bind source identity",
    }
    values.update(changes)
    return EntitySourceBindingDraft(**values)


def _stored_binding(
    number: int,
    *,
    recorded_at: datetime,
    **changes,
) -> EntitySourceBinding:
    draft = _binding(**changes)
    return EntitySourceBinding(
        **draft.model_dump(mode="python"),
        binding_id=UUID(f"00000000-0000-4000-8000-{number:012d}"),
        binding_sha256=f"{number:x}" * 64,
        recorded_at=recorded_at,
    )


def _link_type(**changes) -> InstanceLinkTypeDraft:
    values = {
        "tenant_id": TENANT,
        "link_type_ref": LINK_TYPE_REF,
        "predicate_uri": "http://www.opengis.net/ont/geosparql#sfIntersects",
        "link_kind": InstanceLinkKind.SPATIAL,
        "source_object_type": "natural_resource.land_parcel",
        "target_object_type": "natural_resource.constraint_scope",
        "source_ontology_class_uri": "https://example.test/ontology/LandParcel",
        "target_ontology_class_uri": "https://example.test/ontology/ControlBoundary",
        "ontology_package_id": ONTOLOGY_PACKAGE_ID,
        "ontology_package_sha256": ONTOLOGY_PACKAGE_SHA256,
        "ontology_review_status": (
            InstanceLinkReviewStatus.TECHNICAL_BASELINE_UNREVIEWED
        ),
        "directed": True,
        "allow_self": False,
        "max_targets_per_source": 2,
        "max_sources_per_target": 3,
        "owner_subject": "team:natural-resource-governance",
        "created_by": "agent:entity-link-test",
        "reason": "register spatial link type",
    }
    values.update(changes)
    return InstanceLinkTypeDraft(**values)


def _draft(**changes) -> InstanceLinkAssertionDraft:
    values = {
        "tenant_id": TENANT,
        "link_ref": LINK_REF,
        "link_type_ref": LINK_TYPE_REF,
        "source_entity_ref": SOURCE_ENTITY_REF,
        "target_entity_ref": TARGET_ENTITY_REF,
        "lifecycle_state": InstanceLinkLifecycle.ACTIVE,
        "attributes": {"predicate": "sfIntersects"},
        "valid_from": _at(1),
        "source_version_refs": (SOURCE_VERSION_REF,),
        "mutation_kind": InstanceLinkMutationKind.INITIAL,
        "confidence_basis_points": 9_000,
        "evidence": {"method": "customer_overlay"},
        "idempotency_key": "link.parcel-constraint-001.initial",
        "owner_subject": "team:natural-resource-governance",
        "recorded_by": "agent:entity-link-test",
        "reason": "record spatial link",
    }
    values.update(changes)
    return InstanceLinkAssertionDraft(**values)


def _assertion(
    number: int,
    *,
    recorded_at: datetime,
    **changes,
) -> InstanceLinkAssertion:
    draft = _draft(**changes)
    return InstanceLinkAssertion(
        **draft.model_dump(),
        assertion_id=UUID(f"00000000-0000-4000-8000-{number:012d}"),
        assertion_sha256=f"{number:x}" * 64,
        recorded_at=recorded_at,
    )


def _query(mode: InstanceLinkQueryMode, **changes) -> InstanceLinkQuery:
    values = {"tenant_id": TENANT, "link_ref": LINK_REF, "mode": mode}
    values.update(changes)
    return InstanceLinkQuery(**values)


def test_drafts_reject_cross_tenant_invalid_kinds_uri_time_and_sources() -> None:
    with pytest.raises(ValidationError, match="same tenant"):
        _binding(entity_ref="gda://other/entity/parcel-001")
    with pytest.raises(ValidationError, match="kind 'resource'"):
        _binding(source_system_ref=f"gda://{TENANT}/dataset/customer-parcels")
    with pytest.raises(ValidationError, match="kind 'resource_version'"):
        _binding(source_version_ref=f"gda://{TENANT}/resource/source-v1")
    with pytest.raises(ValidationError, match=r"http\(s\) URI"):
        _binding(ontology_class_uri="urn:example:LandParcel")
    with pytest.raises(ValidationError, match="timezone-aware"):
        _binding(valid_from=datetime(2026, 1, 1, 10))
    with pytest.raises(ValidationError, match="this tenant"):
        _link_type(link_type_ref="gda://other/link_type/intersects-v1")
    with pytest.raises(ValidationError, match=r"http\(s\) URI"):
        _link_type(predicate_uri="geosparql:sfIntersects")
    with pytest.raises(ValidationError, match="same tenant"):
        _draft(target_entity_ref="gda://other/entity/constraint-001")
    with pytest.raises(ValidationError, match="sorted and unique"):
        _draft(source_version_refs=(SOURCE_VERSION_REF, SOURCE_VERSION_REF))
    with pytest.raises(ValidationError, match="only corrections require"):
        _draft(
            mutation_kind=InstanceLinkMutationKind.CORRECTION,
            supersedes_assertion_id=None,
        )


@pytest.mark.parametrize(
    ("mode", "parameters"),
    [
        (InstanceLinkQueryMode.CURRENT, {"valid_at": _at(1)}),
        (InstanceLinkQueryMode.VALID_AT, {}),
        (InstanceLinkQueryMode.KNOWN_AT, {}),
        (InstanceLinkQueryMode.AS_OF, {"known_at": _at(1)}),
    ],
)
def test_query_modes_require_exact_time_axes(mode, parameters) -> None:
    with pytest.raises(ValidationError, match="query requires"):
        _query(mode, **parameters)


def test_current_valid_known_and_as_of_support_late_retraction_and_restore() -> None:
    active = _assertion(1, recorded_at=_at(1, 2))
    late_retraction = _assertion(
        2,
        recorded_at=_at(7),
        lifecycle_state=InstanceLinkLifecycle.RETRACTED,
        valid_from=_at(3),
        mutation_kind=InstanceLinkMutationKind.TRANSITION,
        idempotency_key="link.parcel-constraint-001.retracted",
    )
    restore = _assertion(
        3,
        recorded_at=_at(8),
        lifecycle_state=InstanceLinkLifecycle.ACTIVE,
        valid_from=_at(5),
        mutation_kind=InstanceLinkMutationKind.TRANSITION,
        idempotency_key="link.parcel-constraint-001.restored",
    )
    history = (active, late_retraction, restore)

    current = resolve_instance_link_snapshot(
        history,
        _query(InstanceLinkQueryMode.CURRENT),
        evaluated_at=EVALUATED_AT,
    )
    during_retraction = resolve_instance_link_snapshot(
        history,
        _query(InstanceLinkQueryMode.VALID_AT, valid_at=_at(4)),
        evaluated_at=EVALUATED_AT,
    )
    before_late_fact = resolve_instance_link_snapshot(
        history,
        _query(
            InstanceLinkQueryMode.AS_OF,
            valid_at=_at(4),
            known_at=_at(6),
        ),
        evaluated_at=EVALUATED_AT,
    )
    known_before_retraction = resolve_instance_link_snapshot(
        history,
        _query(InstanceLinkQueryMode.KNOWN_AT, known_at=_at(2)),
        evaluated_at=EVALUATED_AT,
    )

    assert current is not None and current.assertion.assertion_id == restore.assertion_id
    assert current.is_retracted is False
    assert during_retraction is not None and during_retraction.is_retracted is True
    assert before_late_fact is not None
    assert before_late_fact.assertion.assertion_id == active.assertion_id
    assert known_before_retraction is not None
    assert known_before_retraction.assertion.assertion_id == active.assertion_id


def test_correction_changes_knowledge_without_changing_link_identity_or_time() -> None:
    original = _assertion(1, recorded_at=_at(1, 2), valid_to=_at(6))
    correction = _assertion(
        2,
        recorded_at=_at(4),
        valid_to=_at(6),
        attributes={"predicate": "sfIntersects", "area_ha": 1.25},
        mutation_kind=InstanceLinkMutationKind.CORRECTION,
        supersedes_assertion_id=original.assertion_id,
        idempotency_key="link.parcel-constraint-001.correction-1",
    )

    before = resolve_instance_link_snapshot(
        (original, correction),
        _query(
            InstanceLinkQueryMode.AS_OF,
            valid_at=_at(2),
            known_at=_at(3),
        ),
        evaluated_at=EVALUATED_AT,
    )
    after = resolve_instance_link_snapshot(
        (original, correction),
        _query(InstanceLinkQueryMode.CURRENT),
        evaluated_at=_at(5),
    )

    assert before is not None and before.assertion.assertion_id == original.assertion_id
    assert after is not None and after.assertion.assertion_id == correction.assertion_id
    assert after.assertion.attributes["area_ha"] == 1.25


def test_history_rejects_identity_drift_duplicate_events_and_invalid_initial_state() -> None:
    initial = _assertion(1, recorded_at=_at(1, 2))
    changed_target = _assertion(
        2,
        recorded_at=_at(2),
        target_entity_ref=f"gda://{TENANT}/entity/constraint-002",
        valid_from=_at(2),
        mutation_kind=InstanceLinkMutationKind.TRANSITION,
        lifecycle_state=InstanceLinkLifecycle.RETRACTED,
        idempotency_key="link.parcel-constraint-001.changed-target",
    )
    with pytest.raises(EntityLinkHistoryError, match="stable identity"):
        resolve_instance_link_snapshot(
            (initial, changed_target),
            _query(InstanceLinkQueryMode.CURRENT),
            evaluated_at=EVALUATED_AT,
        )

    duplicate = _assertion(
        3,
        recorded_at=_at(1, 3),
        mutation_kind=InstanceLinkMutationKind.TRANSITION,
        lifecycle_state=InstanceLinkLifecycle.RETRACTED,
        idempotency_key="link.parcel-constraint-001.duplicate",
    )
    with pytest.raises(EntityLinkHistoryError, match="duplicate base"):
        resolve_instance_link_snapshot(
            (initial, duplicate),
            _query(InstanceLinkQueryMode.CURRENT),
            evaluated_at=EVALUATED_AT,
        )

    invalid_initial = _assertion(
        4,
        recorded_at=_at(1, 2),
        lifecycle_state=InstanceLinkLifecycle.RETRACTED,
    )
    with pytest.raises(EntityLinkHistoryError, match="initial link lifecycle"):
        resolve_instance_link_snapshot(
            (invalid_initial,),
            _query(InstanceLinkQueryMode.CURRENT),
            evaluated_at=EVALUATED_AT,
        )


def test_history_rejects_changed_correction_time_and_competing_corrections() -> None:
    original = _assertion(1, recorded_at=_at(1, 2), valid_to=_at(6))
    changed_time = _assertion(
        2,
        recorded_at=_at(3),
        valid_to=_at(7),
        mutation_kind=InstanceLinkMutationKind.CORRECTION,
        supersedes_assertion_id=original.assertion_id,
        idempotency_key="link.parcel-constraint-001.changed-time",
    )
    with pytest.raises(EntityLinkHistoryError, match="cannot change identity or lifecycle"):
        resolve_instance_link_snapshot(
            (original, changed_time),
            _query(InstanceLinkQueryMode.CURRENT),
            evaluated_at=EVALUATED_AT,
        )

    correction_one = _assertion(
        3,
        recorded_at=_at(3),
        valid_to=_at(6),
        mutation_kind=InstanceLinkMutationKind.CORRECTION,
        supersedes_assertion_id=original.assertion_id,
        idempotency_key="link.parcel-constraint-001.correction-1",
    )
    correction_two = _assertion(
        4,
        recorded_at=_at(4),
        valid_to=_at(6),
        mutation_kind=InstanceLinkMutationKind.CORRECTION,
        supersedes_assertion_id=original.assertion_id,
        idempotency_key="link.parcel-constraint-001.correction-2",
    )
    with pytest.raises(EntityLinkHistoryError, match="competing corrections"):
        resolve_instance_link_snapshot(
            (original, correction_one, correction_two),
            _query(InstanceLinkQueryMode.CURRENT),
            evaluated_at=EVALUATED_AT,
        )


def test_database_transaction_sets_gateway_role_and_local_tenant() -> None:
    engine = MagicMock()
    engine.dialect.name = "postgresql"
    connection = MagicMock()
    engine.connect.return_value.__enter__.return_value = connection
    connection.begin.return_value.__enter__.return_value = MagicMock()
    authority = EntityLinkAuthority(engine=engine)

    with authority._transaction(TENANT) as yielded:
        assert yielded is connection

    connection.exec_driver_sql.assert_called_once_with(
        f'SET LOCAL ROLE "{GATEWAY_DATABASE_ROLE}"'
    )
    tenant_call = connection.execute.call_args_list[0]
    assert "set_config('app.current_tenant'" in str(tenant_call.args[0])
    assert tenant_call.args[1] == {"tenant": TENANT}


def test_source_binding_history_is_tenant_scoped_and_ordered() -> None:
    first = _stored_binding(1, recorded_at=_at(1, 2))
    second = _stored_binding(
        2,
        recorded_at=_at(3, 2),
        source_version_ref=f"gda://{TENANT}/resource_version/source-v2",
        valid_from=_at(3),
        idempotency_key="source.parcel-001.v2",
    )
    engine = MagicMock()
    engine.dialect.name = "postgresql"
    connection = MagicMock()
    engine.connect.return_value.__enter__.return_value = connection
    connection.begin.return_value.__enter__.return_value = MagicMock()
    query_result = MagicMock()
    query_result.mappings.return_value.all.return_value = [
        first.model_dump(mode="python", exclude={"schema_id"}),
        second.model_dump(mode="python", exclude={"schema_id"}),
    ]
    connection.execute.side_effect = [MagicMock(), query_result]
    authority = EntityLinkAuthority(engine=engine)

    history = authority.source_binding_history(
        TENANT,
        first.source_identity_ref,
        known_through=_at(4),
        limit=2,
    )

    assert history == (first, second)
    query_call = connection.execute.call_args_list[1]
    assert "entity_source_binding_evidence" in str(query_call.args[0])
    assert query_call.args[1] == {
        "tenant_id": TENANT,
        "source_identity_ref": first.source_identity_ref,
        "known_through": _at(4),
        "limit": 2,
    }
    with pytest.raises(EntityLinkValidationError, match="invalid source identity"):
        authority.source_binding_history(TENANT, SOURCE_ENTITY_REF)


def test_source_binding_resolution_uses_valid_and_known_time_axes(monkeypatch) -> None:
    first = _stored_binding(1, recorded_at=_at(1, 2))
    second = _stored_binding(
        2,
        recorded_at=_at(4),
        source_version_ref=f"gda://{TENANT}/resource_version/source-v2",
        valid_from=_at(3),
        idempotency_key="source.parcel-001.v2",
    )
    authority = EntityLinkAuthority(engine=MagicMock())
    history = MagicMock(return_value=(first, second))
    monkeypatch.setattr(authority, "source_binding_history", history)

    resolved = authority.resolve_source_binding(
        TENANT,
        first.source_identity_ref,
        valid_at=_at(5),
        known_at=_at(6),
        evaluated_at=_at(7),
    )

    assert resolved == second
    history.assert_called_once_with(
        TENANT,
        first.source_identity_ref,
        known_through=_at(6),
        limit=10_000,
    )
    with pytest.raises(EntityLinkNotFoundError, match="requested time axes"):
        authority.resolve_source_binding(
            TENANT,
            first.source_identity_ref,
            valid_at=datetime(2025, 12, 1, tzinfo=UTC),
            evaluated_at=_at(7),
        )
    with pytest.raises(EntityLinkValidationError, match="cannot be later"):
        authority.resolve_source_binding(
            TENANT,
            first.source_identity_ref,
            valid_at=_at(5),
            known_at=_at(8),
            evaluated_at=_at(7),
        )


def test_migration_is_tenant_scoped_append_only_and_minimum_privilege() -> None:
    sql = (
        Path(__file__).parent / "migrations/161_entity_link_authority.sql"
    ).read_text(encoding="utf-8")

    for marker in (
        "CREATE TABLE IF NOT EXISTS gda_control.entity_source_identity",
        "CREATE TABLE IF NOT EXISTS gda_control.entity_source_binding_evidence",
        "CREATE TABLE IF NOT EXISTS gda_control.entity_link_type",
        "CREATE TABLE IF NOT EXISTS gda_control.entity_link_identity",
        "CREATE TABLE IF NOT EXISTS gda_control.entity_link_assertion",
        "bind_entity_source_identity",
        "register_entity_link_type",
        "record_entity_link_assertion",
        "maximum targets per source would be exceeded",
        "maximum sources per target would be exceeded",
        "link correction cannot change effective time or lifecycle",
        "late link transition invalidates its successor",
        "technical_baseline_unreviewed",
        "FORCE ROW LEVEL SECURITY",
        "FROM PUBLIC, gda_control_gateway",
        "GRANT EXECUTE ON FUNCTION gda_control.record_entity_link_assertion",
    ):
        assert marker in sql
    assert sql.count("FORCE ROW LEVEL SECURITY") == 1
    assert "GRANT INSERT ON TABLE gda_control.entity_link" not in sql
    assert "GRANT UPDATE ON TABLE gda_control.entity_link" not in sql
    assert "GRANT DELETE ON TABLE gda_control.entity_link" not in sql


def test_chongqing_baseline_is_version_locked_deterministic_and_honest() -> None:
    baseline = build_chongqing_entity_link_baseline()
    repeated = build_chongqing_entity_link_baseline()

    assert baseline.schema_id == "gda.chongqing-entity-link-baseline.v2"
    assert baseline.parcel_record_count == 445
    assert baseline.parcel_identity_count == 439
    assert baseline.constraint_feature_count == 16
    assert baseline.constraint_identity_count == 16
    assert baseline.constraint_name_count == 5
    assert baseline.constraint_scope_count == 6
    assert baseline.link_evidence_observation_count == 472
    assert baseline.exact_intersection_observation_count == 492
    assert baseline.excluded_precision_sliver_count == 1
    assert baseline.precision_policy.endswith("1e-15_source_crs_units")
    assert baseline.link_identity_count == 486
    assert len(baseline.temporal_entity_drafts) == 455
    assert len(baseline.source_binding_drafts) == 455
    assert len(baseline.link_assertion_drafts) == 486
    assert baseline.ontology_package_id == ONTOLOGY_PACKAGE_ID
    assert baseline.ontology_package_sha256 == ONTOLOGY_PACKAGE_SHA256
    assert baseline.ontology_review_status == "technical_baseline_unreviewed"
    assert "not_for_production" in baseline.usage_status
    assert "不替代法定审批" in baseline.decision_scope
    assert baseline == repeated
    assert sum(
        draft.attributes["observation_count"]
        for draft in baseline.link_assertion_drafts
    ) == 492
    assert max(
        draft.attributes["observation_count"]
        for draft in baseline.link_assertion_drafts
    ) == 6
    constraint_entities = tuple(
        draft
        for draft in baseline.temporal_entity_drafts
        if draft.object_type == "natural_resource.constraint_feature"
    )
    assert len(constraint_entities) == 16
    assert all(
        draft.attributes["identity_semantics"] == "layer_plus_BSM"
        and len(draft.attributes["geometry_sha256"]) == 64
        for draft in constraint_entities
    )
    assert baseline.link_type_draft.target_object_type == (
        "natural_resource.constraint_feature"
    )
    assert len({draft.target_entity_ref for draft in baseline.link_assertion_drafts}) == 5
    observations = [
        observation
        for draft in baseline.link_assertion_drafts
        for observation in draft.evidence["observations"]
    ]
    assert len(observations) == 492
    customer_observation_keys = {
        (item["parcel_feature_index"], item["hit_index"]) for item in observations
    }
    assert len(customer_observation_keys) == 472
    multi_feature_keys = {
        (item["parcel_feature_index"], item["hit_index"])
        for item in observations
        if item["customer_scope_candidate_count"] == 2
    }
    assert len(multi_feature_keys) == 20
    assert sum(
        item["customer_scope_area_allocation"]
        == "scope_total_not_allocated_per_feature"
        for item in observations
    ) == 40
    assert all(len(item["intersection_geometry_sha256"]) == 64 for item in observations)


def test_chongqing_baseline_rejects_unpinned_ontology_manifest(tmp_path: Path) -> None:
    bundle_dir = tmp_path / "bundle"
    bundle_dir.mkdir()
    for name in (
        "manifest.json",
        "heping_changed_parcels.geojson",
        "heping_constraints.geojson",
    ):
        shutil.copy2(CUSTOMER_BUNDLE_DIR / name, bundle_dir / name)
    manifest_path = bundle_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["ontology"]["sha256"] = "0" * 64
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(ChongqingBaselineError, match="ontology hash changed"):
        build_chongqing_entity_link_baseline(
            bundle_dir=bundle_dir,
            ontology_package_dir=ONTOLOGY_PACKAGE_DIR,
        )


def test_chongqing_baseline_rejects_customer_hits_without_exact_geometry(
    tmp_path: Path,
) -> None:
    bundle_dir = tmp_path / "bundle"
    bundle_dir.mkdir()
    for name in (
        "manifest.json",
        "heping_changed_parcels.geojson",
        "heping_constraints.geojson",
    ):
        shutil.copy2(CUSTOMER_BUNDLE_DIR / name, bundle_dir / name)

    constraints_path = bundle_dir / "heping_constraints.geojson"
    constraints = json.loads(constraints_path.read_text(encoding="utf-8"))
    constraints["features"][2]["geometry"]["coordinates"] = [
        [
            [120.0, 40.0],
            [120.1, 40.0],
            [120.1, 40.1],
            [120.0, 40.1],
            [120.0, 40.0],
        ]
    ]
    constraints_path.write_text(
        json.dumps(constraints, ensure_ascii=False),
        encoding="utf-8",
    )
    manifest_path = bundle_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    for item in manifest["files"]:
        if item["name"] == "heping_constraints.geojson":
            item["size"] = constraints_path.stat().st_size
            item["sha256"] = hashlib.sha256(constraints_path.read_bytes()).hexdigest()
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False),
        encoding="utf-8",
    )

    with pytest.raises(ChongqingBaselineError, match="does not map"):
        build_chongqing_entity_link_baseline(
            bundle_dir=bundle_dir,
            ontology_package_dir=ONTOLOGY_PACKAGE_DIR,
        )
