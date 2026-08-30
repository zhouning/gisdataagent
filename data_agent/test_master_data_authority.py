"""Contract tests for the reference-master authority."""

from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path
from unittest.mock import MagicMock, patch
from uuid import UUID

import pytest
from pydantic import ValidationError

from data_agent.master_data_authority import (
    MasterDataAuthority,
    MasterDataDomain,
    MasterDataEvent,
    MasterEntityActivation,
    MasterEntityVersion,
    MasterEntityVersionDraft,
    MasterMatchCandidate,
    MasterMatchDisposition,
    MasterResourceProjection,
    MasterSourceRecord,
    MasterSourceRecordDraft,
)
from data_agent.platform_contracts import ResourceVersion

NOW = datetime(2026, 8, 4, 10, tzinfo=UTC)
TENANT = "master-contract"
SOURCE_REF = f"gda://{TENANT}/master_source_record/11111111111111111111111111111111"
ENTITY_REF = f"gda://{TENANT}/master_entity/administrative-unit-500112"
VERSION_REF = f"{ENTITY_REF}.v1"


def _source_draft(**changes) -> MasterSourceRecordDraft:
    values = {
        "tenant_id": TENANT,
        "source_record_ref": SOURCE_REF,
        "domain": MasterDataDomain.ADMINISTRATIVE_UNIT,
        "source_system_ref": f"gda://{TENANT}/source/national-admin-codes",
        "source_record_id": "500112",
        "source_revision": "2026-01-01",
        "business_key": "500112",
        "display_name": "璧山区",
        "parent_business_key": "500100",
        "attributes": {"level": "county"},
        "observed_by": "workload:master-source-harvester",
        "observed_at": NOW,
    }
    values.update(changes)
    return MasterSourceRecordDraft(**values)


def _source(**changes) -> MasterSourceRecord:
    values = {**_source_draft().model_dump(), "record_fingerprint": "a" * 64}
    values.update(changes)
    return MasterSourceRecord(**values)


def _draft(**changes) -> MasterEntityVersionDraft:
    values = {
        "tenant_id": TENANT,
        "entity_ref": ENTITY_REF,
        "entity_version_ref": VERSION_REF,
        "version": 1,
        "domain": MasterDataDomain.ADMINISTRATIVE_UNIT,
        "business_key": "500112",
        "canonical_name": "璧山区",
        "attributes": {"level": "county"},
        "source_record_refs": (SOURCE_REF,),
        "match_candidate_refs": (),
        "valid_from": date(2026, 1, 1),
        "owner_subject": "team:natural-resource-governance",
        "created_by": "human:master-data-steward",
        "creation_reason": "create the first governed administrative unit",
        "created_at": NOW,
    }
    values.update(changes)
    return MasterEntityVersionDraft(**values)


def _version(**changes) -> MasterEntityVersion:
    values = {**_draft().model_dump(), "entity_fingerprint": "b" * 64}
    values.update(changes)
    return MasterEntityVersion(**values)


def test_source_record_is_strict_tenant_bound_and_frozen() -> None:
    source = _source_draft()

    assert source.domain is MasterDataDomain.ADMINISTRATIVE_UNIT
    with pytest.raises(ValidationError, match="frozen"):
        source.display_name = "other"  # type: ignore[misc]
    with pytest.raises(ValidationError, match="record tenant"):
        _source_draft(
            source_record_ref=(
                "gda://other/master_source_record/11111111111111111111111111111111"
            )
        )
    with pytest.raises(ValidationError, match="timezone-aware"):
        _source_draft(observed_at=datetime(2026, 8, 4, 10))


def test_entity_version_requires_sorted_evidence_and_valid_business_time() -> None:
    match_a = f"gda://{TENANT}/master_match/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    match_b = f"gda://{TENANT}/master_match/bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"

    with pytest.raises(ValidationError, match="unique and sorted"):
        _draft(match_candidate_refs=(match_b, match_a))
    with pytest.raises(ValidationError, match="valid_to"):
        _draft(valid_to=date(2026, 1, 1))
    with pytest.raises(ValidationError, match="own parent"):
        _draft(parent_entity_ref=ENTITY_REF)
    with pytest.raises(ValidationError, match="version reference"):
        _draft(entity_version_ref=f"{ENTITY_REF}.v2")


def test_match_scoring_is_explainable_and_business_key_guarded() -> None:
    score, evidence = MasterDataAuthority._score_candidate(
        _source(),
        _version(),
        candidate_parent_business_key=None,
    )

    assert score == 9000
    assert evidence == {
        "schema": "gda.master_match_evidence.v1",
        "business_key_exact": True,
        "name_similarity_milli": 1000,
        "parent_business_key_exact": False,
        "components_basis_points": {
            "business_key": 6500,
            "canonical_name": 2500,
            "parent_business_key": 0,
        },
    }
    mismatched_score, mismatched = MasterDataAuthority._score_candidate(
        _source(business_key="500113"),
        _version(),
        candidate_parent_business_key=None,
    )
    assert mismatched_score == 2500
    assert mismatched["business_key_exact"] is False

    parent_ref = f"gda://{TENANT}/master_entity/administrative-unit-500100"
    hierarchical_score, hierarchical = MasterDataAuthority._score_candidate(
        _source(),
        _version(parent_entity_ref=parent_ref),
        candidate_parent_business_key="500100",
    )
    assert hierarchical_score == 10000
    assert hierarchical["parent_business_key_exact"] is True
    assert hierarchical["components_basis_points"]["parent_business_key"] == 1000


def test_match_candidate_requires_nonhuman_proposer_and_exact_refs() -> None:
    values = {
        "tenant_id": TENANT,
        "match_candidate_ref": (
            f"gda://{TENANT}/master_match/22222222222222222222222222222222"
        ),
        "source_record_ref": SOURCE_REF,
        "candidate_entity_ref": ENTITY_REF,
        "candidate_version_ref": VERSION_REF,
        "candidate_fingerprint": "b" * 64,
        "confidence_basis_points": 9000,
        "disposition": MasterMatchDisposition.RECOMMENDED,
        "evidence": {"business_key_exact": True},
        "proposal_fingerprint": "c" * 64,
        "proposed_by": "workload:master-data-matcher",
        "proposed_at": NOW,
    }
    candidate = MasterMatchCandidate(**values)
    assert candidate.disposition is MasterMatchDisposition.RECOMMENDED
    with pytest.raises(ValidationError, match="workload or agent"):
        MasterMatchCandidate(**{**values, "proposed_by": "human:reviewer"})


def test_activation_event_is_the_only_event_that_binds_approval() -> None:
    base = {
        "tenant_id": TENANT,
        "master_event_id": UUID("00000000-0000-4000-8000-000000000001"),
        "subject_ref": VERSION_REF,
        "subject_fingerprint": "b" * 64,
        "event_type": "version_staged",
        "actor_subject": "human:master-data-steward",
        "reason": "stage candidate",
        "occurred_at": NOW,
    }
    assert MasterDataEvent(**base).approval_case_ref is None
    with pytest.raises(ValidationError, match="only master activation"):
        MasterDataEvent(
            **base,
            approval_case_ref=f"gda://{TENANT}/approval_case/master-v1",
        )


def test_version_list_is_bounded_and_detects_next_page() -> None:
    newest = _version(
        entity_version_ref=f"{ENTITY_REF}.v2",
        version=2,
        entity_fingerprint="c" * 64,
    )
    oldest = _version()

    def database_row(value: MasterEntityVersion) -> dict:
        row = value.model_dump(mode="python")
        row.pop("schema_id")
        row["source_record_refs"] = list(row["source_record_refs"])
        row["match_candidate_refs"] = list(row["match_candidate_refs"])
        return row

    result = MagicMock()
    result.mappings.return_value.all.return_value = [
        database_row(newest),
        database_row(oldest),
    ]
    connection = MagicMock()
    connection.execute.return_value = result
    transaction = MagicMock()
    transaction.__enter__.return_value = connection
    transaction.__exit__.return_value = False
    authority = MasterDataAuthority()

    with patch.object(authority, "_transaction", return_value=transaction):
        page = authority.list_versions(TENANT, ENTITY_REF, limit=1, offset=2)

    assert page.items == (newest,)
    assert page.offset == 2
    assert page.limit == 1
    assert page.has_more is True
    assert connection.execute.call_args.args[1] == {
        "tenant_id": TENANT,
        "entity_ref": ENTITY_REF,
        "row_limit": 2,
        "offset": 2,
    }


def test_activation_contract_is_typed() -> None:
    activation = MasterEntityActivation(
        tenant_id=TENANT,
        entity_ref=ENTITY_REF,
        domain=MasterDataDomain.ADMINISTRATIVE_UNIT,
        business_key="500112",
        active_version_ref=VERSION_REF,
        active_fingerprint="b" * 64,
        approval_case_ref=f"gda://{TENANT}/approval_case/master-v1",
        activation_version=1,
        activated_by="workload:master-data-controller",
        activation_reason="activate approved golden record",
        activated_at=NOW,
    )
    assert activation.activation_version == 1


def test_master_resource_projection_binds_exact_generic_version() -> None:
    resource_version = ResourceVersion(
        tenant_id=TENANT,
        resource_urn=ENTITY_REF,
        resource_version_id=UUID("00000000-0000-5000-8000-000000000001"),
        version_key="v1",
        content_sha256="b" * 64,
        authority_version_ref={
            "authority_system": "gda_control.master_data",
            "entity_version_ref": VERSION_REF,
            "entity_fingerprint": "b" * 64,
        },
        created_by="human:master-data-steward",
        created_at=NOW,
    )
    projection = MasterResourceProjection(
        tenant_id=TENANT,
        entity_ref=ENTITY_REF,
        entity_version_ref=VERSION_REF,
        entity_fingerprint="b" * 64,
        activation_version=1,
        resource_version=resource_version,
        approval_case_ref=f"gda://{TENANT}/approval_case/master-v1",
        projected_at=NOW,
    )

    assert projection.resource_version == resource_version
    with pytest.raises(ValidationError, match="exact entity version"):
        MasterResourceProjection(
            **{
                **projection.model_dump(),
                "resource_version": ResourceVersion(
                    **{
                        **resource_version.model_dump(),
                        "content_sha256": "c" * 64,
                    }
                ),
            }
        )


def test_resource_projection_list_is_bounded_and_typed() -> None:
    resource_version_id = UUID("00000000-0000-5000-8000-000000000001")
    row = {
        "tenant_id": TENANT,
        "entity_ref": ENTITY_REF,
        "entity_version_ref": VERSION_REF,
        "entity_fingerprint": "b" * 64,
        "activation_version": 1,
        "resource_version_id": resource_version_id,
        "previous_resource_version_id": None,
        "approval_case_ref": f"gda://{TENANT}/approval_case/master-v1",
        "projected_at": NOW,
        "resource_version_key": "v1",
        "resource_predecessor_version_id": None,
        "resource_authority_version_ref": {
            "authority_system": "gda_control.master_data",
            "entity_version_ref": VERSION_REF,
            "entity_fingerprint": "b" * 64,
        },
        "resource_created_by": "human:master-data-steward",
        "resource_created_at": NOW,
    }
    result = MagicMock()
    result.mappings.return_value.all.return_value = [row, row]
    connection = MagicMock()
    connection.execute.return_value = result
    transaction = MagicMock()
    transaction.__enter__.return_value = connection
    transaction.__exit__.return_value = False
    authority = MasterDataAuthority()

    with patch.object(authority, "_transaction", return_value=transaction):
        page = authority.resource_projections(TENANT, ENTITY_REF, limit=1, offset=2)

    assert len(page.items) == 1
    assert page.items[0].resource_version.resource_version_id == resource_version_id
    assert page.offset == 2
    assert page.limit == 1
    assert page.has_more is True
    assert connection.execute.call_args.args[1] == {
        "tenant_id": TENANT,
        "entity_ref": ENTITY_REF,
        "row_limit": 2,
        "offset": 2,
    }


def test_migration_enforces_immutable_rls_approval_and_least_privilege() -> None:
    sql = (
        Path(__file__).parent
        / "migrations/124_reference_master_data_authority.sql"
    ).read_text(encoding="utf-8")

    for marker in (
        "CREATE TABLE IF NOT EXISTS gda_control.master_source_record",
        "CREATE TABLE IF NOT EXISTS gda_control.master_match_candidate",
        "CREATE TABLE IF NOT EXISTS gda_control.master_entity_version",
        "CREATE TABLE IF NOT EXISTS gda_control.master_entity_activation",
        "observe_master_source_record",
        "propose_master_match_candidate",
        "stage_master_entity_version",
        "activate_master_entity_version",
        "master_data.entity.activate",
        "ApprovalCase does not authorize this master activation",
        "master entity hierarchy cycle detected",
        "uq_gda_master_active_business_key",
        "FORCE ROW LEVEL SECURITY",
        "reject_immutable_mutation",
        "GRANT SELECT ON gda_control.master_entity_version",
    ):
        assert marker in sql
    assert "GRANT INSERT ON gda_control.master_source_record" not in sql
    assert "GRANT UPDATE ON gda_control.master_entity_activation" not in sql
    assert "GRANT INSERT ON gda_control.master_data_event" not in sql


def test_resource_projection_migration_is_atomic_immutable_and_read_only() -> None:
    sql = (
        Path(__file__).parent
        / "migrations/125_master_data_resource_projection.sql"
    ).read_text(encoding="utf-8")

    for marker in (
        "CREATE TABLE IF NOT EXISTS gda_control.master_resource_projection",
        "master_resource_version_id",
        "project_master_activation_to_resource",
        "trg_gda_master_activation_resource_projection",
        "master Resource identity already has different evidence",
        "master ResourceVersion identity already has different evidence",
        "FORCE ROW LEVEL SECURITY",
        "trg_gda_master_resource_projection_immutable",
        "GRANT SELECT ON TABLE gda_control.master_resource_projection",
    ):
        assert marker in sql
    assert "GRANT INSERT ON TABLE gda_control.master_resource_projection" not in sql
    assert "GRANT UPDATE ON TABLE gda_control.master_resource_projection" not in sql
    assert "GRANT DELETE ON TABLE gda_control.master_resource_projection" not in sql


def test_master_metadata_outbox_is_transactional_leased_and_read_only() -> None:
    sql = (
        Path(__file__).parent
        / "migrations/126_master_metadata_projection_outbox.sql"
    ).read_text(encoding="utf-8")

    for marker in (
        "CREATE TABLE IF NOT EXISTS gda_control.master_metadata_projection_outbox",
        "fk_gda_master_metadata_projection_source",
        "enqueue_master_metadata_projection",
        "trg_gda_master_metadata_projection_enqueue",
        "FOR UPDATE SKIP LOCKED",
        "claim_master_metadata_projections",
        "complete_master_metadata_projection",
        "fail_master_metadata_projection",
        "FORCE ROW LEVEL SECURITY",
        "GRANT SELECT ON TABLE gda_control.master_metadata_projection_outbox",
    ):
        assert marker in sql
    assert (
        "GRANT INSERT ON TABLE gda_control.master_metadata_projection_outbox"
        not in sql
    )
    assert (
        "GRANT UPDATE ON TABLE gda_control.master_metadata_projection_outbox"
        not in sql
    )
    assert (
        "GRANT DELETE ON TABLE gda_control.master_metadata_projection_outbox"
        not in sql
    )
