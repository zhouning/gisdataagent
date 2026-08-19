"""PostgreSQL acceptance for the complete Chongqing authority load and replay."""

from __future__ import annotations

import asyncio
import json
import os
from collections import Counter
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from data_agent.api import platform_gateway_routes as routes
from data_agent.capability_registry import (
    CHONGQING_DATA_PACKAGE_RECONCILE,
    ENTITY_AUTHORITY_BATCH_INGEST,
)
from data_agent.chongqing_data_package_reconciliation_service import (
    ChongqingDataPackageReconciliationRequest,
    execute_chongqing_data_package_reconciliation,
)
from data_agent.chongqing_entity_link_baseline import (
    build_chongqing_entity_link_baseline,
)
from data_agent.chongqing_entity_link_loader import (
    load_chongqing_entity_link_baseline,
)
from data_agent.chongqing_entity_link_reconciliation import (
    reconcile_chongqing_entity_links,
)
from data_agent.entity_authority_batch import (
    EntityAuthorityBatchRequest,
    execute_entity_authority_batch,
)
from data_agent.entity_link_authority import EntityLinkAuthority
from data_agent.mcp_tool_registry import (
    _mcp_ingest_entity_authority_batch,
    _mcp_reconcile_entity_data_package,
)
from data_agent.temporal_entity_authority import (
    TemporalEntityAuthority,
    TemporalEntityConflictError,
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
        "166_chongqing_data_package_reconciliation.sql",
    )
)


def _route_request(body: dict) -> MagicMock:
    request = MagicMock()

    async def read_json() -> dict:
        return body

    request.json.side_effect = read_json
    request.headers = {
        "x-request-id": "postgres-route-replay",
        "X-GDA-Capability-Fingerprint": ENTITY_AUTHORITY_BATCH_INGEST.fingerprint,
        "idempotency-key": body["idempotency_key"],
    }
    request.path_params = {}
    request.query_params = {}
    return request


def _reconciliation_route_request(body: dict) -> MagicMock:
    request = MagicMock()

    async def read_json() -> dict:
        return body

    request.json.side_effect = read_json
    request.headers = {
        "x-request-id": "postgres-reconciliation-replay",
        "X-GDA-Capability-Fingerprint": (
            CHONGQING_DATA_PACKAGE_RECONCILE.fingerprint
        ),
        "idempotency-key": body["idempotency_key"],
    }
    request.path_params = {}
    request.query_params = {}
    return request


@pytest.mark.skipif(not DATABASE_URL, reason="DATABASE_URL is not configured")
def test_postgres_loads_and_replays_the_complete_chongqing_baseline(
    isolated_postgres_url: str,
) -> None:
    assert DATABASE_URL is not None
    admin_engine = create_engine(isolated_postgres_url)
    suffix = uuid4().hex[:12]
    tenant_id = f"cq-loader-{suffix}"
    rollback_tenant = f"{tenant_id}-rollback"
    runtime_role = f"gda_cq_loader_{suffix}"
    runtime_password = f"cq{uuid4().hex}"
    runtime_engine = None
    role_created = False

    try:
        with admin_engine.begin() as connection:
            if not connection.exec_driver_sql(
                "SELECT rolsuper FROM pg_roles WHERE rolname = current_user"
            ).scalar_one():
                pytest.skip("Chongqing loader migration test requires a superuser")
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

        runtime_url = make_url(isolated_postgres_url).set(
            username=runtime_role,
            password=runtime_password,
        )
        runtime_engine = create_engine(runtime_url)
        rollback_baseline = build_chongqing_entity_link_baseline(
            tenant_id=rollback_tenant
        )
        first = rollback_baseline.temporal_entity_drafts[0]
        conflicting_second = rollback_baseline.temporal_entity_drafts[1].model_copy(
            update={"entity_ref": first.entity_ref}
        )
        with pytest.raises(TemporalEntityConflictError):
            TemporalEntityAuthority(runtime_engine).record_batch(
                (first, conflicting_second)
            )
        with admin_engine.connect() as connection:
            rollback_count = connection.execute(
                text(
                    """
                    SELECT count(*)
                    FROM gda_control.temporal_entity_assertion
                    WHERE tenant_id = :tenant_id
                    """
                ),
                {"tenant_id": rollback_tenant},
            ).scalar_one()
        assert rollback_count == 0

        receipt = load_chongqing_entity_link_baseline(
            tenant_id=tenant_id,
            engine=runtime_engine,
            verify_replay=True,
        )

        assert receipt.replay_verification == "passed"
        assert receipt.schema_id == "gda.chongqing-entity-link-load-receipt.v2"
        assert receipt.constraint_feature_count == 16
        assert receipt.constraint_identity_count == 16
        assert receipt.entity_count == 455
        assert receipt.binding_count == 455
        assert receipt.link_assertion_count == 486
        assert receipt.customer_scope_observation_count == 472
        assert receipt.exact_intersection_observation_count == 492
        assert receipt.evidence_observation_count == 492
        assert receipt.excluded_precision_sliver_count == 1
        assert receipt.precision_policy == (
            "positive_intersection_area_gt_1e-15_source_crs_units"
        )
        assert receipt.authority_operation_count == 1_397
        assert receipt.idempotency_key_count == 1_396
        assert receipt.batch_size == 250
        assert receipt.authority_batch_count == 7
        assert receipt.replayed_batch_count == 7

        with admin_engine.connect() as connection:
            counts = connection.execute(
                text(
                    """
                    SELECT
                        (SELECT count(*) FROM gda_control.temporal_entity_identity
                         WHERE tenant_id = :tenant_id) AS entity_identities,
                        (SELECT count(*) FROM gda_control.temporal_entity_assertion
                         WHERE tenant_id = :tenant_id) AS entity_assertions,
                        (SELECT count(*) FROM gda_control.entity_source_identity
                         WHERE tenant_id = :tenant_id) AS source_identities,
                        (SELECT count(*) FROM gda_control.entity_source_binding_evidence
                         WHERE tenant_id = :tenant_id) AS source_bindings,
                        (SELECT count(*) FROM gda_control.entity_link_type
                         WHERE tenant_id = :tenant_id) AS link_types,
                        (SELECT count(*) FROM gda_control.entity_link_identity
                         WHERE tenant_id = :tenant_id) AS link_identities,
                        (SELECT count(*) FROM gda_control.entity_link_assertion
                         WHERE tenant_id = :tenant_id) AS link_assertions
                    """
                ),
                {"tenant_id": tenant_id},
            ).mappings().one()
        assert dict(counts) == {
            "entity_identities": 455,
            "entity_assertions": 455,
            "source_identities": 455,
            "source_bindings": 455,
            "link_types": 1,
            "link_identities": 486,
            "link_assertions": 486,
        }

        baseline = build_chongqing_entity_link_baseline(tenant_id=tenant_id)
        temporal_authority = TemporalEntityAuthority(runtime_engine)
        link_authority = EntityLinkAuthority(runtime_engine)
        principal = SimpleNamespace(
            identifier="chongqing-baseline-builder",
            metadata={
                "role": "platform_operator",
                "tenant_id": tenant_id,
                "subject_type": "agent",
            },
        )
        route_cases = (
            (
                "temporal_entity_assertions",
                (baseline.temporal_entity_drafts[0],),
            ),
            (
                "source_identity_bindings",
                (baseline.source_binding_drafts[0],),
            ),
            ("link_types", (baseline.link_type_draft,)),
            ("link_assertions", (baseline.link_assertion_drafts[0],)),
        )

        def execute_with_runtime(request: EntityAuthorityBatchRequest):
            return execute_entity_authority_batch(
                request,
                temporal_authority=temporal_authority,
                link_authority=link_authority,
            )

        with (
            patch.object(routes, "_get_user_from_request", return_value=principal),
            patch.object(
                routes,
                "execute_entity_authority_batch",
                side_effect=execute_with_runtime,
            ),
        ):
            for batch_type, items in route_cases:
                request = EntityAuthorityBatchRequest(
                    batch_type=batch_type,
                    tenant_id=tenant_id,
                    idempotency_key=f"cq.postgres.route.{batch_type}",
                    items=items,
                )
                body = request.model_dump(mode="json")
                first = asyncio.run(
                    routes.ingest_entity_authority_batch(_route_request(body))
                )
                replay = asyncio.run(
                    routes.ingest_entity_authority_batch(_route_request(body))
                )
                assert first.status_code == 200
                assert replay.status_code == 200
                first_data = json.loads(first.body)["data"]
                replay_data = json.loads(replay.body)["data"]
                assert first_data["state_fingerprint"] == replay_data[
                    "state_fingerprint"
                ]
                assert first_data["technical_baseline_status"] == (
                    "technical_baseline_unreviewed"
                )

        tenant_token = current_tenant_id.set(tenant_id)
        user_token = current_user_id.set("chongqing-baseline-builder")
        role_token = current_user_role.set("platform_operator")
        try:
            with patch(
                "data_agent.entity_authority_batch.execute_entity_authority_batch",
                side_effect=execute_with_runtime,
            ):
                for batch_type, items in route_cases:
                    arguments = {
                        "batch_type": batch_type,
                        "tenant_id": tenant_id,
                        "idempotency_key": f"cq.postgres.mcp.{batch_type}",
                        "items": [item.model_dump(mode="json") for item in items],
                    }
                    first = json.loads(
                        _mcp_ingest_entity_authority_batch(**arguments)
                    )
                    replay = json.loads(
                        _mcp_ingest_entity_authority_batch(**arguments)
                    )
                    assert first["state_fingerprint"] == replay[
                        "state_fingerprint"
                    ]
                    assert first["technical_baseline_status"] == (
                        "technical_baseline_unreviewed"
                    )
        finally:
            current_user_role.reset(role_token)
            current_user_id.reset(user_token)
            current_tenant_id.reset(tenant_token)

        effective_at = baseline.link_assertion_drafts[0].valid_from + timedelta(days=1)
        corrected_first = baseline.link_assertion_drafts[0].model_copy(
            update={
                "evidence": {
                    **baseline.link_assertion_drafts[0].evidence,
                    "recompute_revision": "postgres-feature-overlay-v3",
                }
            }
        )
        reduced_links = (
            corrected_first,
            *baseline.link_assertion_drafts[2:],
        )
        reduced = baseline.model_copy(
            update={
                "customer_bundle_version": "postgres-incremental-v2",
                "link_identity_count": len(reduced_links),
                "link_assertion_drafts": reduced_links,
            }
        )
        first_plan, first_receipt = reconcile_chongqing_entity_links(
            previous_baseline=baseline,
            desired_baseline=reduced,
            effective_at=effective_at,
            link_authority=link_authority,
            verify_replay=True,
        )
        assert first_plan.operation_count == 2
        assert len(first_plan.correction_drafts) == 1
        assert len(first_plan.retraction_drafts) == 1
        assert first_receipt.replay_verification == "passed"
        assert first_receipt.unchanged_count == 484

        restored_links = (
            corrected_first,
            baseline.link_assertion_drafts[1],
            *baseline.link_assertion_drafts[2:],
        )
        restored = baseline.model_copy(
            update={
                "customer_bundle_version": "postgres-incremental-v3",
                "link_identity_count": len(restored_links),
                "link_assertion_drafts": restored_links,
            }
        )
        restore_plan, restore_receipt = reconcile_chongqing_entity_links(
            previous_baseline=reduced,
            desired_baseline=restored,
            effective_at=effective_at + timedelta(hours=1),
            link_authority=link_authority,
            verify_replay=True,
        )
        assert restore_plan.operation_count == 1
        assert len(restore_plan.restoration_drafts) == 1
        assert restore_receipt.replay_verification == "passed"
        assert restore_receipt.unchanged_count == 485

        corrected_history = link_authority.history(
            tenant_id,
            baseline.link_assertion_drafts[0].link_ref,
        )
        restored_history = link_authority.history(
            tenant_id,
            baseline.link_assertion_drafts[1].link_ref,
        )
        assert len(corrected_history) == 2
        assert corrected_history[-1].evidence["recompute_revision"] == (
            "postgres-feature-overlay-v3"
        )
        assert len(restored_history) == 3
        assert [item.lifecycle_state.value for item in restored_history] == [
            "active",
            "retracted",
            "active",
        ]

        with admin_engine.connect() as connection:
            incremental_counts = connection.execute(
                text(
                    """
                    SELECT
                        (SELECT count(*) FROM gda_control.entity_link_identity
                         WHERE tenant_id = :tenant_id) AS link_identities,
                        (SELECT count(*) FROM gda_control.entity_link_assertion
                         WHERE tenant_id = :tenant_id) AS link_assertions
                    """
                ),
                {"tenant_id": tenant_id},
            ).mappings().one()
        assert dict(incremental_counts) == {
            "link_identities": 486,
            "link_assertions": 489,
        }

        link_counts = Counter(
            draft.source_entity_ref for draft in restored.link_assertion_drafts
        )
        retired_entity_ref = next(
            entity_ref for entity_ref, count in link_counts.items() if count == 1
        )
        retired_link = next(
            draft
            for draft in restored.link_assertion_drafts
            if draft.source_entity_ref == retired_entity_ref
        )
        corrected_entity = next(
            draft
            for draft in restored.temporal_entity_drafts
            if draft.object_type == "natural_resource.land_parcel"
            and draft.entity_ref != retired_entity_ref
        )
        source_by_entity = {
            draft.entity_ref: draft for draft in restored.source_binding_drafts
        }
        corrected_source = source_by_entity[corrected_entity.entity_ref]
        retired_source = source_by_entity[retired_entity_ref]
        package_source_version = (
            f"gda://{tenant_id}/resource_version/customer-parcels-package-v2"
        )
        desired_corrected_entity = corrected_entity.model_copy(
            update={
                "attributes": {
                    **corrected_entity.attributes,
                    "package_recompute_revision": 2,
                },
                "source_version_refs": (package_source_version,),
            }
        )
        desired_corrected_source = corrected_source.model_copy(
            update={
                "source_version_ref": package_source_version,
                "evidence": {
                    **corrected_source.evidence,
                    "package_recompute_revision": 2,
                },
            }
        )
        new_entity_ref = f"gda://{tenant_id}/entity/postgres-package-added-parcel"
        new_source_ref = (
            f"gda://{tenant_id}/source_identity/postgres-package-added-parcel"
        )
        new_entity = corrected_entity.model_copy(
            update={
                "entity_ref": new_entity_ref,
                "attributes": {
                    **corrected_entity.attributes,
                    "parcel_id": "postgres-package-added-parcel",
                    "package_recompute_revision": 2,
                },
                "source_version_refs": (package_source_version,),
                "idempotency_key": "cq.postgres.package-added-parcel.initial",
            }
        )
        new_source = corrected_source.model_copy(
            update={
                "source_identity_ref": new_source_ref,
                "source_object_id": "postgres-package-added-parcel",
                "entity_ref": new_entity_ref,
                "source_version_ref": package_source_version,
                "evidence": {
                    **corrected_source.evidence,
                    "package_recompute_revision": 2,
                },
                "idempotency_key": "cq.postgres.source.package-added-parcel.v1",
            }
        )
        target_source = source_by_entity[retired_link.target_entity_ref]
        new_link_ref = f"gda://{tenant_id}/entity_link/postgres-package-added-link"
        new_link = retired_link.model_copy(
            update={
                "link_ref": new_link_ref,
                "source_entity_ref": new_entity_ref,
                "attributes": {**retired_link.attributes, "package_added": True},
                "source_version_refs": tuple(
                    sorted(
                        (
                            package_source_version,
                            target_source.source_version_ref,
                        )
                    )
                ),
                "idempotency_key": "cq.postgres.link.package-added-link.initial",
            }
        )
        desired_entities = tuple(
            desired_corrected_entity
            if draft.entity_ref == corrected_entity.entity_ref
            else draft
            for draft in restored.temporal_entity_drafts
            if draft.entity_ref != retired_entity_ref
        ) + (new_entity,)
        desired_sources = tuple(
            desired_corrected_source
            if draft.source_identity_ref == corrected_source.source_identity_ref
            else draft
            for draft in restored.source_binding_drafts
            if draft.source_identity_ref != retired_source.source_identity_ref
        ) + (new_source,)
        desired_links = tuple(
            draft
            for draft in restored.link_assertion_drafts
            if draft.link_ref != retired_link.link_ref
        ) + (new_link,)
        package_desired = restored.model_copy(
            update={
                "customer_bundle_version": "postgres-package-incremental-v4",
                "temporal_entity_drafts": desired_entities,
                "source_binding_drafts": desired_sources,
                "link_identity_count": len(desired_links),
                "link_assertion_drafts": desired_links,
            }
        )
        package_request = ChongqingDataPackageReconciliationRequest(
            tenant_id=tenant_id,
            previous_baseline=restored,
            desired_baseline=package_desired,
            effective_at=effective_at + timedelta(hours=2),
            evaluated_at=datetime.now(UTC),
            batch_size=250,
            verify_replay=True,
            idempotency_key="cq.postgres.package-reconciliation.v4",
            recorded_by="agent:chongqing-baseline-builder",
        )

        def execute_reconciliation_with_runtime(request):
            return execute_chongqing_data_package_reconciliation(
                request,
                engine=runtime_engine,
                temporal_authority=temporal_authority,
                link_authority=link_authority,
            )

        package_body = package_request.model_dump(mode="json")
        with (
            patch.object(routes, "_get_user_from_request", return_value=principal),
            patch.object(
                routes,
                "execute_chongqing_data_package_reconciliation",
                side_effect=execute_reconciliation_with_runtime,
            ),
        ):
            route_result = asyncio.run(
                routes.reconcile_entity_data_package(
                    _reconciliation_route_request(package_body)
                )
            )
        assert route_result.status_code == 200
        package_response = json.loads(route_result.body)["data"]

        tenant_token = current_tenant_id.set(tenant_id)
        user_token = current_user_id.set("chongqing-baseline-builder")
        role_token = current_user_role.set("platform_operator")
        try:
            with patch(
                "data_agent.chongqing_data_package_reconciliation_service."
                "execute_chongqing_data_package_reconciliation",
                side_effect=execute_reconciliation_with_runtime,
            ):
                mcp_response = json.loads(
                    _mcp_reconcile_entity_data_package(
                        tenant_id=tenant_id,
                        previous_baseline=package_body["previous_baseline"],
                        desired_baseline=package_body["desired_baseline"],
                        effective_at=package_body["effective_at"],
                        evaluated_at=package_body["evaluated_at"],
                        idempotency_key=package_request.idempotency_key,
                        recorded_by=package_request.recorded_by,
                        batch_size=package_request.batch_size,
                        verify_replay=package_request.verify_replay,
                    )
                )
        finally:
            current_user_role.reset(role_token)
            current_user_id.reset(user_token)
            current_tenant_id.reset(tenant_token)

        assert package_response["plan_sha256"] == mcp_response["plan_sha256"]
        assert package_response["receipt_sha256"] == mcp_response["receipt_sha256"]
        assert package_response["authority_state_sha256"] == (
            mcp_response["authority_state_sha256"]
        )
        assert package_response["operation_count"] == 7
        assert package_response["entity_correction_count"] == 1
        assert package_response["entity_addition_count"] == 1
        assert package_response["entity_retirement_count"] == 1
        assert package_response["source_binding_count"] == 2
        assert package_response["link_retraction_count"] == 1
        assert package_response["link_addition_count"] == 1
        assert package_response["replay_verification"] == "passed"
        assert package_response["batch_count"] == 6
        assert package_response["unchanged_entity_count"] == 453
        assert package_response["unchanged_source_count"] == 453
        assert package_response["retained_retired_source_count"] == 1
        assert package_response["idempotency_status"] == (
            "durable_sealed_plan_replay_enforced"
        )

        corrected_entity_history = temporal_authority.history(
            tenant_id,
            corrected_entity.entity_ref,
        )
        retired_entity_history = temporal_authority.history(
            tenant_id,
            retired_entity_ref,
        )
        new_entity_history = temporal_authority.history(tenant_id, new_entity_ref)
        corrected_source_history = link_authority.source_binding_history(
            tenant_id,
            corrected_source.source_identity_ref,
        )
        new_source_history = link_authority.source_binding_history(
            tenant_id,
            new_source_ref,
        )
        retired_link_history = link_authority.history(
            tenant_id,
            retired_link.link_ref,
        )
        new_link_history = link_authority.history(tenant_id, new_link_ref)
        assert len(corrected_entity_history) == 2
        assert corrected_entity_history[-1].attributes[
            "package_recompute_revision"
        ] == 2
        assert len(retired_entity_history) == 2
        assert retired_entity_history[-1].lifecycle_state.value == "retired"
        assert len(new_entity_history) == 1
        assert len(corrected_source_history) == 2
        assert corrected_source_history[-1].source_version_ref == package_source_version
        assert len(new_source_history) == 1
        assert [item.lifecycle_state.value for item in retired_link_history] == [
            "active",
            "retracted",
        ]
        assert len(new_link_history) == 1

        with admin_engine.connect() as connection:
            package_counts = connection.execute(
                text(
                    """
                    SELECT
                        (SELECT count(*) FROM gda_control.temporal_entity_identity
                         WHERE tenant_id = :tenant_id) AS entity_identities,
                        (SELECT count(*) FROM gda_control.temporal_entity_assertion
                         WHERE tenant_id = :tenant_id) AS entity_assertions,
                        (SELECT count(*) FROM gda_control.entity_source_identity
                         WHERE tenant_id = :tenant_id) AS source_identities,
                        (SELECT count(*) FROM gda_control.entity_source_binding_evidence
                         WHERE tenant_id = :tenant_id) AS source_bindings,
                        (SELECT count(*) FROM gda_control.entity_link_identity
                         WHERE tenant_id = :tenant_id) AS link_identities,
                        (SELECT count(*) FROM gda_control.entity_link_assertion
                         WHERE tenant_id = :tenant_id) AS link_assertions,
                        (SELECT count(*)
                         FROM gda_control.chongqing_data_package_reconciliation
                         WHERE tenant_id = :tenant_id
                           AND status = 'completed') AS reconciliations
                    """
                ),
                {"tenant_id": tenant_id},
            ).mappings().one()
        assert dict(package_counts) == {
            "entity_identities": 456,
            "entity_assertions": 458,
            "source_identities": 456,
            "source_bindings": 457,
            "link_identities": 487,
            "link_assertions": 491,
            "reconciliations": 1,
        }
    finally:
        if runtime_engine is not None:
            runtime_engine.dispose()
        with admin_engine.begin() as connection:
            authority_tables = (
                "entity_link_assertion",
                "entity_link_identity",
                "entity_source_binding_evidence",
                "entity_source_identity",
                "temporal_entity_assertion",
                "temporal_entity_identity",
                "entity_link_type",
            )
            for table_name in authority_tables:
                connection.exec_driver_sql(
                    f"ALTER TABLE gda_control.{table_name} DISABLE TRIGGER USER"
                )
            for table_name in (
                "chongqing_data_package_reconciliation",
                *authority_tables,
            ):
                if connection.execute(
                    text("SELECT to_regclass(:table_name)"),
                    {"table_name": f"gda_control.{table_name}"},
                ).scalar_one() is not None:
                    connection.execute(
                        text(
                            f"DELETE FROM gda_control.{table_name} "
                            "WHERE tenant_id IN (:tenant_id, :rollback_tenant)"
                        ),
                        {
                            "tenant_id": tenant_id,
                            "rollback_tenant": rollback_tenant,
                        },
                    )
            for table_name in authority_tables:
                connection.exec_driver_sql(
                    f"ALTER TABLE gda_control.{table_name} ENABLE TRIGGER USER"
                )
        if role_created:
            with admin_engine.begin() as connection:
                connection.exec_driver_sql(f'DROP ROLE IF EXISTS "{runtime_role}"')
        admin_engine.dispose()
