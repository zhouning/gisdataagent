"""Contracts for append-only entity lineage and Link propagation."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from pydantic import ValidationError

from data_agent.entity_lineage_authority import (
    GATEWAY_DATABASE_ROLE,
    EntityLineageAuthority,
    EntityLineageKind,
    EntityLineageRequest,
    EntityLinkPropagationDraft,
    EntitySourceIdentityRedirectDraft,
    LinkPropagationDisposition,
)

TENANT = "lineage-contract"
EFFECTIVE_AT = datetime(2026, 2, 1, 10, tzinfo=UTC)
SOURCE_A = f"gda://{TENANT}/entity/parcel-a"
SOURCE_B = f"gda://{TENANT}/entity/parcel-b"
TARGET = f"gda://{TENANT}/entity/parcel-merged"
SOURCE_VERSION = f"gda://{TENANT}/resource_version/chongqing-customer-v1"


def _request(**changes) -> EntityLineageRequest:
    values = {
        "tenant_id": TENANT,
        "event_ref": f"gda://{TENANT}/entity_lineage/merge-001",
        "lineage_kind": EntityLineageKind.MERGE,
        "effective_at": EFFECTIVE_AT,
        "source_entity_refs": (SOURCE_A, SOURCE_B),
        "target_entity_refs": (TARGET,),
        "source_version_refs": (SOURCE_VERSION,),
        "link_propagations": (),
        "source_identity_redirects": (),
        "idempotency_key": "lineage.merge.001",
        "owner_subject": "team:natural-resource-governance",
        "recorded_by": "agent:lineage-test",
        "reason": "Merge duplicate Chongqing parcel identities",
    }
    values.update(changes)
    return EntityLineageRequest(**values)


def test_lineage_kind_cardinality_tenant_and_order_are_fail_closed() -> None:
    with pytest.raises(ValidationError, match="N>=2"):
        _request(source_entity_refs=(SOURCE_A,))
    with pytest.raises(ValidationError, match="one source entity and N>=2"):
        _request(
            lineage_kind="split",
            source_entity_refs=(SOURCE_A,),
            target_entity_refs=(TARGET,),
        )
    with pytest.raises(ValidationError, match="one source and one target"):
        _request(lineage_kind="replacement")
    with pytest.raises(ValidationError, match="sorted and unique"):
        _request(source_entity_refs=(SOURCE_B, SOURCE_A))
    with pytest.raises(ValidationError, match="must use tenant"):
        _request(target_entity_refs=("gda://other/entity/parcel-merged",))
    with pytest.raises(ValidationError, match="must be disjoint"):
        _request(target_entity_refs=(SOURCE_A,))
    with pytest.raises(ValidationError, match="timezone-aware"):
        _request(effective_at=datetime(2026, 2, 1, 10))


def test_link_propagation_shapes_require_new_identity_and_explicit_split_target() -> None:
    old_link = f"gda://{TENANT}/entity_link/parcel-a-constraint"
    new_link = f"gda://{TENANT}/entity_link/merged-constraint"
    constraint = f"gda://{TENANT}/entity/constraint-001"

    with pytest.raises(ValidationError, match="requires target_link_ref"):
        EntityLinkPropagationDraft(
            source_link_ref=old_link,
            disposition="redirect",
            evidence={},
            reason="redirect",
        )
    with pytest.raises(ValidationError, match="forbids endpoint overrides"):
        EntityLinkPropagationDraft(
            source_link_ref=old_link,
            disposition="deduplicate",
            target_link_ref=new_link,
            target_source_entity_ref=TARGET,
            target_target_entity_ref=constraint,
            evidence={},
            reason="deduplicate",
        )
    with pytest.raises(ValidationError, match="forbids a target link"):
        EntityLinkPropagationDraft(
            source_link_ref=old_link,
            disposition="retract_only",
            target_link_ref=new_link,
            evidence={},
            reason="obsolete relation",
        )

    redirect = EntityLinkPropagationDraft(
        source_link_ref=old_link,
        disposition=LinkPropagationDisposition.REDIRECT,
        target_link_ref=new_link,
        target_source_entity_ref=TARGET,
        target_target_entity_ref=constraint,
        evidence={"allocation": "explicit"},
        reason="redirect source endpoint",
    )
    request = _request(link_propagations=(redirect,))
    assert request.link_propagations[0].target_source_entity_ref == TARGET

    with pytest.raises(ValidationError, match="new stable identity"):
        _request(
            link_propagations=(
                redirect.model_copy(update={"target_link_ref": old_link}),
            )
        )


def test_source_identity_redirects_are_explicit_and_baseline_is_fixed() -> None:
    redirect = EntitySourceIdentityRedirectDraft(
        source_identity_ref=f"gda://{TENANT}/source_identity/parcel-a",
        target_entity_ref=TARGET,
        evidence={"allocation": "merge"},
        reason="redirect source identity",
    )
    request = _request(source_identity_redirects=(redirect,))
    assert request.ontology_package_id.startswith("natural-resource-one-map:2.3.0")
    assert request.ontology_review_status == "technical_baseline_unreviewed"
    assert request.decision_status == (
        "assisted_precheck_not_for_production_decision"
    )
    assert request.request_sha256 == _request(
        source_identity_redirects=(redirect,)
    ).request_sha256

    payload = request.model_dump(mode="json")
    payload["ontology_review_status"] = "domain_approved"
    with pytest.raises(ValidationError, match="technical_baseline_unreviewed"):
        EntityLineageRequest.model_validate(payload)


def test_database_transaction_sets_gateway_role_and_local_tenant() -> None:
    engine = MagicMock()
    engine.dialect.name = "postgresql"
    connection = MagicMock()
    engine.connect.return_value.__enter__.return_value = connection
    connection.begin.return_value.__enter__.return_value = MagicMock()
    authority = EntityLineageAuthority(engine=engine)

    with authority._transaction(TENANT) as yielded:
        assert yielded is connection

    connection.exec_driver_sql.assert_called_once_with(
        f'SET LOCAL ROLE "{GATEWAY_DATABASE_ROLE}"'
    )
    tenant_call = connection.execute.call_args_list[0]
    assert "set_config('app.current_tenant'" in str(tenant_call.args[0])
    assert tenant_call.args[1] == {"tenant": TENANT}


def test_migration_is_atomic_append_only_tenant_scoped_and_minimum_privilege() -> None:
    sql = (
        Path(__file__).parent / "migrations/164_entity_lineage_authority.sql"
    ).read_text(encoding="utf-8")

    for marker in (
        "CREATE TABLE IF NOT EXISTS gda_control.entity_lineage_event",
        "CREATE TABLE IF NOT EXISTS gda_control.entity_lineage_member",
        "CREATE TABLE IF NOT EXISTS gda_control.entity_link_propagation",
        "CREATE TABLE IF NOT EXISTS gda_control.entity_source_identity_redirect",
        "record_entity_lineage_event",
        "resolve_entity_source_identity",
        "all active source Links require one explicit propagation",
        "all effective source identities require one explicit redirect",
        "redirect must replace only source endpoints with targets",
        "technical_baseline_unreviewed",
        "assisted_precheck_not_for_production_decision",
        "SECURITY DEFINER",
        "SET row_security = on",
        "FORCE ROW LEVEL SECURITY",
        "FROM PUBLIC, gda_control_gateway",
        "GRANT EXECUTE ON FUNCTION gda_control.record_entity_lineage_event",
    ):
        assert marker in sql
    assert sql.count("FORCE ROW LEVEL SECURITY") == 1
    assert "GRANT INSERT ON TABLE gda_control.entity_lineage" not in sql
    assert "GRANT UPDATE ON TABLE gda_control.entity_lineage" not in sql
    assert "GRANT DELETE ON TABLE gda_control.entity_lineage" not in sql
