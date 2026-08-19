"""Real PostgreSQL acceptance for atomic entity lineage propagation."""

from __future__ import annotations

import asyncio
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from data_agent.api import platform_gateway_routes as routes
from data_agent.capability_registry import ENTITY_LINEAGE_RECORD
from data_agent.chongqing_entity_link_baseline import (
    ONTOLOGY_PACKAGE_ID,
    ONTOLOGY_PACKAGE_SHA256,
)
from data_agent.entity_lineage_authority import (
    EntityLineageAuthority,
    EntityLineageConflictError,
    EntityLineageRequest,
    EntityLineageValidationError,
    EntityLinkPropagationDraft,
    EntitySourceIdentityRedirectDraft,
)
from data_agent.entity_link_authority import (
    EntityLinkAuthority,
    EntityResolutionMethod,
    EntitySourceBindingDraft,
    InstanceLinkAssertionDraft,
    InstanceLinkKind,
    InstanceLinkLifecycle,
    InstanceLinkMutationKind,
    InstanceLinkReviewStatus,
    InstanceLinkTypeDraft,
)
from data_agent.mcp_tool_registry import _mcp_record_entity_lineage_event
from data_agent.temporal_entity_authority import (
    TemporalEntityAssertionDraft,
    TemporalEntityAuthority,
)
from data_agent.user_context import (
    current_tenant_id,
    current_user_id,
    current_user_role,
)

DATABASE_URL = os.environ.get("DATABASE_URL")
MIGRATIONS = tuple(
    Path(__file__).resolve().parent / "migrations" / filename
    for filename in (
        "092_platform_control_ledger.sql",
        "094_platform_control_gateway.sql",
        "160_bitemporal_entity_authority.sql",
        "161_entity_link_authority.sql",
        "162_entity_authority_batch_ingest.sql",
        "164_entity_lineage_authority.sql",
    )
)
OWNER = "team:natural-resource-governance"
ACTOR = "agent:lineage-postgres-test"
INITIAL_AT = datetime(2026, 1, 1, 10, tzinfo=UTC)
EFFECTIVE_AT = datetime(2026, 2, 1, 10, tzinfo=UTC)


def _route_request(body: dict) -> MagicMock:
    request = MagicMock()

    async def read_json() -> dict:
        return body

    request.json.side_effect = read_json
    request.headers = {
        "x-request-id": "lineage-postgres-replay",
        "X-GDA-Capability-Fingerprint": ENTITY_LINEAGE_RECORD.fingerprint,
        "idempotency-key": body["idempotency_key"],
    }
    request.path_params = {}
    request.query_params = {}
    return request


def _entity(tenant_id: str, slug: str, object_type: str) -> TemporalEntityAssertionDraft:
    return TemporalEntityAssertionDraft(
        tenant_id=tenant_id,
        entity_ref=f"gda://{tenant_id}/entity/{slug}",
        object_type=object_type,
        lifecycle_state="active",
        attributes={"slug": slug},
        valid_from=INITIAL_AT,
        source_version_refs=(
            f"gda://{tenant_id}/resource_version/chongqing-customer-v1",
        ),
        mutation_kind="initial",
        idempotency_key=f"entity.{slug}.initial",
        owner_subject=OWNER,
        recorded_by=ACTOR,
        reason="Seed entity lineage acceptance data",
    )


def _binding(tenant_id: str, slug: str) -> EntitySourceBindingDraft:
    return EntitySourceBindingDraft(
        tenant_id=tenant_id,
        source_identity_ref=f"gda://{tenant_id}/source_identity/{slug}",
        source_system_ref=f"gda://{tenant_id}/resource/chongqing-customer",
        source_object_type="natural_resource.land_parcel",
        source_object_id=slug,
        entity_ref=f"gda://{tenant_id}/entity/{slug}",
        entity_object_type="natural_resource.land_parcel",
        ontology_class_uri=(
            "https://ontology.gis-data-agent.local/natural-resource/one-map/"
            "LandParcel"
        ),
        source_version_ref=(
            f"gda://{tenant_id}/resource_version/chongqing-customer-v1"
        ),
        valid_from=INITIAL_AT,
        resolution_method=EntityResolutionMethod.AUTHORITATIVE_IDENTIFIER,
        confidence_basis_points=10_000,
        evidence={"customer_dataset": "chongqing"},
        idempotency_key=f"binding.{slug}.initial",
        owner_subject=OWNER,
        recorded_by=ACTOR,
        reason="Bind Chongqing customer source identity",
    )


def _link_type(tenant_id: str) -> InstanceLinkTypeDraft:
    return InstanceLinkTypeDraft(
        tenant_id=tenant_id,
        link_type_ref=f"gda://{tenant_id}/link_type/parcel-intersects-constraint",
        predicate_uri="http://www.opengis.net/ont/geosparql#sfIntersects",
        link_kind=InstanceLinkKind.SPATIAL,
        source_object_type="natural_resource.land_parcel",
        target_object_type="natural_resource.constraint_scope",
        source_ontology_class_uri=(
            "https://ontology.gis-data-agent.local/natural-resource/one-map/"
            "LandParcel"
        ),
        target_ontology_class_uri=(
            "https://ontology.gis-data-agent.local/natural-resource/one-map/"
            "ConstraintScope"
        ),
        ontology_package_id=ONTOLOGY_PACKAGE_ID,
        ontology_package_sha256=ONTOLOGY_PACKAGE_SHA256,
        ontology_review_status=(
            InstanceLinkReviewStatus.TECHNICAL_BASELINE_UNREVIEWED
        ),
        directed=True,
        allow_self=False,
        max_targets_per_source=10,
        max_sources_per_target=10,
        owner_subject=OWNER,
        created_by=ACTOR,
        reason="Register lineage acceptance Link type",
    )


def _link(tenant_id: str, source_slug: str) -> InstanceLinkAssertionDraft:
    return InstanceLinkAssertionDraft(
        tenant_id=tenant_id,
        link_ref=f"gda://{tenant_id}/entity_link/{source_slug}-constraint",
        link_type_ref=f"gda://{tenant_id}/link_type/parcel-intersects-constraint",
        source_entity_ref=f"gda://{tenant_id}/entity/{source_slug}",
        target_entity_ref=f"gda://{tenant_id}/entity/constraint-001",
        lifecycle_state=InstanceLinkLifecycle.ACTIVE,
        attributes={"predicate": "sfIntersects"},
        valid_from=INITIAL_AT,
        source_version_refs=(
            f"gda://{tenant_id}/resource_version/chongqing-customer-v1",
        ),
        mutation_kind=InstanceLinkMutationKind.INITIAL,
        confidence_basis_points=9_000,
        evidence={"method": "customer_overlay"},
        idempotency_key=f"link.{source_slug}.constraint.initial",
        owner_subject=OWNER,
        recorded_by=ACTOR,
        reason="Seed active source Link",
    )


def _seed(
    temporal: TemporalEntityAuthority,
    links: EntityLinkAuthority,
    tenant_id: str,
    *,
    source_slugs: tuple[str, ...],
    target_slugs: tuple[str, ...],
) -> None:
    temporal.record_batch(
        tuple(
            _entity(tenant_id, slug, "natural_resource.land_parcel")
            for slug in (*source_slugs, *target_slugs)
        )
        + (_entity(tenant_id, "constraint-001", "natural_resource.constraint_scope"),)
    )
    links.register_link_type(_link_type(tenant_id))
    links.bind_sources_batch(tuple(_binding(tenant_id, slug) for slug in source_slugs))
    links.record_links_batch(tuple(_link(tenant_id, slug) for slug in source_slugs))


@pytest.mark.skipif(not DATABASE_URL, reason="DATABASE_URL is not configured")
def test_postgres_merge_replays_and_ambiguous_split_rolls_back_atomically(
    isolated_postgres_url: str,
) -> None:
    assert DATABASE_URL is not None
    admin_engine = create_engine(isolated_postgres_url)
    suffix = uuid4().hex[:12]
    runtime_role = f"gda_lineage_{suffix}"
    runtime_password = f"lineage{uuid4().hex}"
    runtime_engine = None
    role_created = False

    try:
        with admin_engine.begin() as connection:
            if not connection.exec_driver_sql(
                "SELECT rolsuper FROM pg_roles WHERE rolname = current_user"
            ).scalar_one():
                pytest.skip("entity lineage acceptance requires a superuser")
            for migration in MIGRATIONS:
                connection.execute(text(migration.read_text(encoding="utf-8")))
            connection.exec_driver_sql(
                f'CREATE ROLE "{runtime_role}" LOGIN PASSWORD \'{runtime_password}\' '
                "NOINHERIT NOSUPERUSER NOBYPASSRLS"
            )
            role_created = True
            connection.exec_driver_sql(
                f'GRANT gda_control_gateway TO "{runtime_role}"'
            )

        runtime_engine = create_engine(
            make_url(isolated_postgres_url).set(
                username=runtime_role,
                password=runtime_password,
            )
        )
        temporal = TemporalEntityAuthority(runtime_engine)
        links = EntityLinkAuthority(runtime_engine)
        lineage = EntityLineageAuthority(runtime_engine)

        tenant_id = f"lineage-merge-{suffix}"
        _seed(
            temporal,
            links,
            tenant_id,
            source_slugs=("parcel-a", "parcel-b"),
            target_slugs=("parcel-merged",),
        )
        source_a = f"gda://{tenant_id}/entity/parcel-a"
        source_b = f"gda://{tenant_id}/entity/parcel-b"
        target = f"gda://{tenant_id}/entity/parcel-merged"
        constraint = f"gda://{tenant_id}/entity/constraint-001"
        old_link_a = f"gda://{tenant_id}/entity_link/parcel-a-constraint"
        old_link_b = f"gda://{tenant_id}/entity_link/parcel-b-constraint"
        new_link = f"gda://{tenant_id}/entity_link/parcel-merged-constraint"
        request = EntityLineageRequest(
            tenant_id=tenant_id,
            event_ref=f"gda://{tenant_id}/entity_lineage/merge-001",
            lineage_kind="merge",
            effective_at=EFFECTIVE_AT,
            source_entity_refs=(source_a, source_b),
            target_entity_refs=(target,),
            source_version_refs=(
                f"gda://{tenant_id}/resource_version/chongqing-customer-v1",
            ),
            link_propagations=(
                EntityLinkPropagationDraft(
                    source_link_ref=old_link_a,
                    disposition="redirect",
                    target_link_ref=new_link,
                    target_source_entity_ref=target,
                    target_target_entity_ref=constraint,
                    evidence={"allocation": "deterministic_merge"},
                    reason="Redirect first source Link to merged entity",
                ),
                EntityLinkPropagationDraft(
                    source_link_ref=old_link_b,
                    disposition="deduplicate",
                    target_link_ref=new_link,
                    evidence={"allocation": "deduplicate_equivalent_link"},
                    reason="Deduplicate the equivalent propagated Link",
                ),
            ),
            source_identity_redirects=(
                EntitySourceIdentityRedirectDraft(
                    source_identity_ref=(
                        f"gda://{tenant_id}/source_identity/parcel-a"
                    ),
                    target_entity_ref=target,
                    evidence={"allocation": "merge"},
                    reason="Redirect parcel-a source identity",
                ),
                EntitySourceIdentityRedirectDraft(
                    source_identity_ref=(
                        f"gda://{tenant_id}/source_identity/parcel-b"
                    ),
                    target_entity_ref=target,
                    evidence={"allocation": "merge"},
                    reason="Redirect parcel-b source identity",
                ),
            ),
            idempotency_key="lineage.merge.001",
            owner_subject=OWNER,
            recorded_by=ACTOR,
            reason="Merge duplicate Chongqing parcel identities",
        )

        first = lineage.record(request)
        replay = lineage.record(request)
        assert first == replay
        assert first.retired_source_count == 2
        assert first.link_retraction_count == 2
        assert first.link_creation_count == 1
        assert first.link_deduplication_count == 1
        assert first.source_identity_redirect_count == 2
        assert lineage.resolve_source_identity(
            tenant_id,
            f"gda://{tenant_id}/source_identity/parcel-a",
            valid_at=EFFECTIVE_AT,
        ).resolved_entity_ref == target

        body = request.model_dump(mode="json")
        principal = SimpleNamespace(
            identifier="lineage-postgres-test",
            metadata={
                "role": "platform_operator",
                "tenant_id": tenant_id,
                "subject_type": "agent",
            },
        )
        with (
            patch.object(routes, "_get_user_from_request", return_value=principal),
            patch.object(routes, "EntityLineageAuthority", return_value=lineage),
        ):
            route_first = asyncio.run(
                routes.record_entity_lineage_event(_route_request(body))
            )
            route_replay = asyncio.run(
                routes.record_entity_lineage_event(_route_request(body))
            )
        assert route_first.status_code == 200
        assert route_replay.status_code == 200
        assert json.loads(route_first.body)["data"] == json.loads(
            route_replay.body
        )["data"]

        tenant_token = current_tenant_id.set(tenant_id)
        user_token = current_user_id.set("lineage-postgres-test")
        role_token = current_user_role.set("platform_operator")
        try:
            with patch(
                "data_agent.entity_lineage_authority.EntityLineageAuthority",
                return_value=lineage,
            ):
                mcp_arguments = {
                    "tenant_id": tenant_id,
                    "event_ref": request.event_ref,
                    "lineage_kind": request.lineage_kind.value,
                    "effective_at": request.effective_at.isoformat(),
                    "source_entity_refs": list(request.source_entity_refs),
                    "target_entity_refs": list(request.target_entity_refs),
                    "source_version_refs": list(request.source_version_refs),
                    "link_propagations": [
                        item.model_dump(mode="json")
                        for item in request.link_propagations
                    ],
                    "source_identity_redirects": [
                        item.model_dump(mode="json")
                        for item in request.source_identity_redirects
                    ],
                    "idempotency_key": request.idempotency_key,
                    "owner_subject": request.owner_subject,
                    "recorded_by": request.recorded_by,
                    "reason": request.reason,
                }
                mcp_first = json.loads(
                    _mcp_record_entity_lineage_event(**mcp_arguments)
                )
                mcp_replay = json.loads(
                    _mcp_record_entity_lineage_event(**mcp_arguments)
                )
            assert mcp_first == mcp_replay
            assert mcp_first["event_sha256"] == first.event_sha256
        finally:
            current_user_role.reset(role_token)
            current_user_id.reset(user_token)
            current_tenant_id.reset(tenant_token)

        with admin_engine.connect() as connection:
            counts = connection.execute(
                text(
                    """
                    SELECT
                        (SELECT count(*) FROM gda_control.entity_lineage_event
                         WHERE tenant_id = :tenant_id) AS events,
                        (SELECT count(*) FROM gda_control.entity_lineage_member
                         WHERE tenant_id = :tenant_id) AS members,
                        (SELECT count(*) FROM gda_control.entity_link_propagation
                         WHERE tenant_id = :tenant_id) AS propagations,
                        (SELECT count(*)
                         FROM gda_control.entity_source_identity_redirect
                         WHERE tenant_id = :tenant_id) AS redirects,
                        (SELECT count(*) FROM gda_control.entity_link_identity
                         WHERE tenant_id = :tenant_id) AS link_identities,
                        (SELECT count(*) FROM gda_control.entity_link_assertion
                         WHERE tenant_id = :tenant_id) AS link_assertions
                    """
                ),
                {"tenant_id": tenant_id},
            ).mappings().one()
        assert dict(counts) == {
            "events": 1,
            "members": 3,
            "propagations": 2,
            "redirects": 2,
            "link_identities": 3,
            "link_assertions": 5,
        }

        rollback_tenant = f"lineage-split-{suffix}"
        _seed(
            temporal,
            links,
            rollback_tenant,
            source_slugs=("parcel-source",),
            target_slugs=("parcel-left", "parcel-right"),
        )
        ambiguous = EntityLineageRequest(
            tenant_id=rollback_tenant,
            event_ref=f"gda://{rollback_tenant}/entity_lineage/split-001",
            lineage_kind="split",
            effective_at=EFFECTIVE_AT,
            source_entity_refs=(
                f"gda://{rollback_tenant}/entity/parcel-source",
            ),
            target_entity_refs=(
                f"gda://{rollback_tenant}/entity/parcel-left",
                f"gda://{rollback_tenant}/entity/parcel-right",
            ),
            source_version_refs=(
                f"gda://{rollback_tenant}/resource_version/chongqing-customer-v1",
            ),
            link_propagations=(),
            source_identity_redirects=(
                EntitySourceIdentityRedirectDraft(
                    source_identity_ref=(
                        f"gda://{rollback_tenant}/source_identity/parcel-source"
                    ),
                    target_entity_ref=(
                        f"gda://{rollback_tenant}/entity/parcel-left"
                    ),
                    evidence={"allocation": "explicit_split"},
                    reason="Allocate source identity to left parcel",
                ),
            ),
            idempotency_key="lineage.split.001",
            owner_subject=OWNER,
            recorded_by=ACTOR,
            reason="Split parcel with intentionally omitted Link allocation",
        )
        with pytest.raises(EntityLineageValidationError):
            lineage.record(ambiguous)

        with admin_engine.connect() as connection:
            rollback_state = connection.execute(
                text(
                    """
                    SELECT
                        (SELECT count(*) FROM gda_control.entity_lineage_event
                         WHERE tenant_id = :tenant_id) AS events,
                        (SELECT count(*) FROM gda_control.temporal_entity_assertion
                         WHERE tenant_id = :tenant_id
                           AND entity_ref = :source_ref) AS source_assertions
                    """
                ),
                {
                    "tenant_id": rollback_tenant,
                    "source_ref": (
                        f"gda://{rollback_tenant}/entity/parcel-source"
                    ),
                },
            ).one()
        assert rollback_state == (0, 1)

        split_target = f"gda://{rollback_tenant}/entity/parcel-left"
        split_request = ambiguous.model_copy(
            update={
                "link_propagations": (
                    EntityLinkPropagationDraft(
                        source_link_ref=(
                            f"gda://{rollback_tenant}/entity_link/"
                            "parcel-source-constraint"
                        ),
                        disposition="redirect",
                        target_link_ref=(
                            f"gda://{rollback_tenant}/entity_link/"
                            "parcel-left-constraint"
                        ),
                        target_source_entity_ref=split_target,
                        target_target_entity_ref=(
                            f"gda://{rollback_tenant}/entity/constraint-001"
                        ),
                        evidence={"allocation": "left_only"},
                        reason="Assign the old Link only to the left parcel",
                    ),
                ),
                "reason": "Split parcel with an explicit per-Link allocation",
            }
        )
        split_receipt = lineage.record(split_request)
        assert split_receipt.lineage_kind.value == "split"
        assert split_receipt.source_count == 1
        assert split_receipt.target_count == 2
        assert split_receipt.link_creation_count == 1
        assert lineage.resolve_source_identity(
            rollback_tenant,
            f"gda://{rollback_tenant}/source_identity/parcel-source",
            valid_at=EFFECTIVE_AT,
        ).resolved_entity_ref == split_target
        with admin_engine.connect() as connection:
            right_link_count = connection.execute(
                text(
                    """
                    SELECT count(*)
                    FROM gda_control.entity_link_identity
                    WHERE tenant_id = :tenant_id
                      AND source_entity_ref = :right_ref
                    """
                ),
                {
                    "tenant_id": rollback_tenant,
                    "right_ref": (
                        f"gda://{rollback_tenant}/entity/parcel-right"
                    ),
                },
            ).scalar_one()
        assert right_link_count == 0

        replacement_tenant = f"lineage-replacement-{suffix}"
        _seed(
            temporal,
            links,
            replacement_tenant,
            source_slugs=("parcel-old",),
            target_slugs=("parcel-new",),
        )
        replacement_target = (
            f"gda://{replacement_tenant}/entity/parcel-new"
        )
        replacement = EntityLineageRequest(
            tenant_id=replacement_tenant,
            event_ref=(
                f"gda://{replacement_tenant}/entity_lineage/replacement-001"
            ),
            lineage_kind="replacement",
            effective_at=EFFECTIVE_AT,
            source_entity_refs=(
                f"gda://{replacement_tenant}/entity/parcel-old",
            ),
            target_entity_refs=(replacement_target,),
            source_version_refs=(
                f"gda://{replacement_tenant}/resource_version/"
                "chongqing-customer-v1",
            ),
            link_propagations=(
                EntityLinkPropagationDraft(
                    source_link_ref=(
                        f"gda://{replacement_tenant}/entity_link/"
                        "parcel-old-constraint"
                    ),
                    disposition="redirect",
                    target_link_ref=(
                        f"gda://{replacement_tenant}/entity_link/"
                        "parcel-new-constraint"
                    ),
                    target_source_entity_ref=replacement_target,
                    target_target_entity_ref=(
                        f"gda://{replacement_tenant}/entity/constraint-001"
                    ),
                    evidence={"allocation": "deterministic_replacement"},
                    reason="Redirect Link to replacement entity",
                ),
            ),
            source_identity_redirects=(
                EntitySourceIdentityRedirectDraft(
                    source_identity_ref=(
                        f"gda://{replacement_tenant}/source_identity/parcel-old"
                    ),
                    target_entity_ref=replacement_target,
                    evidence={"allocation": "replacement"},
                    reason="Redirect source identity to replacement entity",
                ),
            ),
            idempotency_key="lineage.replacement.001",
            owner_subject=OWNER,
            recorded_by=ACTOR,
            reason="Replace the prior parcel identity",
        )
        replacement_receipt = lineage.record(replacement)
        assert replacement_receipt.lineage_kind.value == "replacement"
        assert replacement_receipt.retired_source_count == 1
        assert replacement_receipt.link_retraction_count == 1
        assert replacement_receipt.link_creation_count == 1
        assert replacement_receipt.source_identity_redirect_count == 1

        conflict_tenant = f"lineage-conflict-{suffix}"
        _seed(
            temporal,
            links,
            conflict_tenant,
            source_slugs=("parcel-a", "parcel-b"),
            target_slugs=("parcel-merged",),
        )
        conflict_target = f"gda://{conflict_tenant}/entity/parcel-merged"
        duplicate_redirect = EntityLineageRequest(
            tenant_id=conflict_tenant,
            event_ref=f"gda://{conflict_tenant}/entity_lineage/merge-duplicate",
            lineage_kind="merge",
            effective_at=EFFECTIVE_AT,
            source_entity_refs=(
                f"gda://{conflict_tenant}/entity/parcel-a",
                f"gda://{conflict_tenant}/entity/parcel-b",
            ),
            target_entity_refs=(conflict_target,),
            source_version_refs=(
                f"gda://{conflict_tenant}/resource_version/"
                "chongqing-customer-v1",
            ),
            link_propagations=(
                EntityLinkPropagationDraft(
                    source_link_ref=(
                        f"gda://{conflict_tenant}/entity_link/"
                        "parcel-a-constraint"
                    ),
                    disposition="redirect",
                    target_link_ref=(
                        f"gda://{conflict_tenant}/entity_link/"
                        "merged-constraint-a"
                    ),
                    target_source_entity_ref=conflict_target,
                    target_target_entity_ref=(
                        f"gda://{conflict_tenant}/entity/constraint-001"
                    ),
                    evidence={"allocation": "incorrect_duplicate"},
                    reason="First duplicate redirect",
                ),
                EntityLinkPropagationDraft(
                    source_link_ref=(
                        f"gda://{conflict_tenant}/entity_link/"
                        "parcel-b-constraint"
                    ),
                    disposition="redirect",
                    target_link_ref=(
                        f"gda://{conflict_tenant}/entity_link/"
                        "merged-constraint-b"
                    ),
                    target_source_entity_ref=conflict_target,
                    target_target_entity_ref=(
                        f"gda://{conflict_tenant}/entity/constraint-001"
                    ),
                    evidence={"allocation": "incorrect_duplicate"},
                    reason="Second duplicate redirect",
                ),
            ),
            source_identity_redirects=(
                EntitySourceIdentityRedirectDraft(
                    source_identity_ref=(
                        f"gda://{conflict_tenant}/source_identity/parcel-a"
                    ),
                    target_entity_ref=conflict_target,
                    evidence={"allocation": "merge"},
                    reason="Redirect parcel-a source identity",
                ),
                EntitySourceIdentityRedirectDraft(
                    source_identity_ref=(
                        f"gda://{conflict_tenant}/source_identity/parcel-b"
                    ),
                    target_entity_ref=conflict_target,
                    evidence={"allocation": "merge"},
                    reason="Redirect parcel-b source identity",
                ),
            ),
            idempotency_key="lineage.merge.duplicate",
            owner_subject=OWNER,
            recorded_by=ACTOR,
            reason="Prove rollback after a duplicate propagated Link conflict",
        )
        with pytest.raises(EntityLineageConflictError):
            lineage.record(duplicate_redirect)
        with admin_engine.connect() as connection:
            conflict_state = connection.execute(
                text(
                    """
                    SELECT
                        (SELECT count(*) FROM gda_control.entity_lineage_event
                         WHERE tenant_id = :tenant_id) AS events,
                        (SELECT count(*) FROM gda_control.temporal_entity_assertion
                         WHERE tenant_id = :tenant_id
                           AND entity_ref IN (:source_a, :source_b))
                            AS source_assertions,
                        (SELECT count(*) FROM gda_control.entity_link_identity
                         WHERE tenant_id = :tenant_id) AS link_identities,
                        (SELECT count(*) FROM gda_control.entity_link_assertion
                         WHERE tenant_id = :tenant_id) AS link_assertions
                    """
                ),
                {
                    "tenant_id": conflict_tenant,
                    "source_a": f"gda://{conflict_tenant}/entity/parcel-a",
                    "source_b": f"gda://{conflict_tenant}/entity/parcel-b",
                },
            ).one()
        assert conflict_state == (0, 2, 2, 2)
    finally:
        if runtime_engine is not None:
            runtime_engine.dispose()
        if role_created:
            with admin_engine.begin() as connection:
                connection.exec_driver_sql(f'DROP ROLE IF EXISTS "{runtime_role}"')
        admin_engine.dispose()
