#!/usr/bin/env python3
"""Certify the JQDLTB-to-GIS serving bridge on disposable PostgreSQL.

The fixture is synthetic and disposable.  It proves the authority chain and
Gateway behavior; it is not a Chongqing business release or a production SLO.
"""

from __future__ import annotations

import argparse
import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

from certify_gis_service_control_plane import (
    _definition,
    _deployment,
    _endpoint,
    _release_bundle,
    _seed_authorities,
    _service_policy,
)
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.exc import DBAPIError

from data_agent.approval_case_authority import ApprovalCaseAuthority
from data_agent.gis_service_control_plane import GISServiceSLOBinding
from data_agent.jqdltb_serving_release import (
    JqdltbServingReleaseBinding,
    build_jqdltb_serving_release_binding,
)
from data_agent.migration_runner import discover_migrations
from data_agent.platform_contracts import (
    ApprovalAvailabilityStatus,
    ApprovalCase,
    ApprovalCaseStatus,
    ApprovalPrincipalStatus,
    ApprovalPrincipalType,
    Artifact,
    ArtifactRole,
    FrameworkAttemptObservation,
    LineageEvent,
    LineageEventType,
    QualityResult,
    RunSuccessEvidence,
    canonical_json_fingerprint,
    quality_result_fingerprint,
    run_success_evidence_fingerprint,
)
from data_agent.platform_gateway import (
    GatewayConflictError,
    GatewayNotFoundError,
    GatewayValidationError,
    PlatformGateway,
)
from data_agent.slo_authority import (
    SLOBurnRateWindow,
    SLODefinitionAuthority,
    SLODefinitionDraft,
    SLOEventRatioIndicator,
)

MIGRATION_NAMES = (
    "092_platform_control_ledger.sql",
    "094_platform_control_gateway.sql",
    "096_platform_success_verdict.sql",
    "100_data_product_registry.sql",
    "101_data_product_promotion.sql",
    "102_source_schema_drift_ledger.sql",
    "103_unified_approval_case_authority.sql",
    "105_asset_distribution_grant.sql",
    "106_version_locked_distribution_grant.sql",
    "107_distribution_grant_package_quota.sql",
    "108_data_product_promotion_impact.sql",
    "110_immutable_security_event_ledger.sql",
    "120_approval_case_assignment_authority.sql",
    "121_approval_principal_directory.sql",
    "122_slo_definition_authority.sql",
    "149_consumer_binding.sql",
    "153_gis_service_control_plane.sql",
    "154_gis_service_release_binding.sql",
    "203_gis_service_cache_policy_authority.sql",
    "204_gis_service_policy_binding.sql",
    "205_gis_mvt_serving_projection.sql",
    "206_gis_mvt_serving_projection_hardening.sql",
    "207_gis_service_deployment_observation_hardening.sql",
    "208_gis_service_endpoint_readiness_binding.sql",
    "209_gis_service_gateway_privilege_repair.sql",
    "210_gis_mvt_postgis_function_schema.sql",
    "211_gis_mvt_postgis_operator_schema.sql",
    "212_gis_service_consumer_binding.sql",
    "213_gis_service_consumer_binding_approval.sql",
    "214_gis_service_consumer_binding_revocation.sql",
    "215_gis_service_consumer_binding_renewal.sql",
    "216_gis_service_consumer_binding_renewal_decision_guard.sql",
    "223_gis_service_slo_binding.sql",
    "235_jqdltb_serving_release_binding.sql",
    "236_jqdltb_serving_endpoint_promotion_gate.sql",
    "237_mvt_serving_relation_attestation.sql",
)
MIGRATIONS = tuple(
    next(
        migration
        for migration in discover_migrations()
        if migration.filename == name
    )
    for name in MIGRATION_NAMES
)
NOW = datetime(2026, 8, 26, 12, 0, tzinfo=UTC)
TENANT = "planning"
SLO_REF = f"gda://{TENANT}/slo_definition/district-features-availability"
SLO_VERSION = f"{SLO_REF}.v1"
SLO_APPROVAL_REF = f"gda://{TENANT}/approval_case/district-slo-v1"
SLO_ACTOR = "workload:gis-slo-controller"
SLO_APPROVER = "human:gis-service-owner"


def _sql_file(path: Path) -> str:
    return path.read_text(encoding="utf-8").replace("%", "%%")


def _bootstrap(engine: Engine, login_role: str) -> None:
    with engine.begin() as connection:
        connection.exec_driver_sql(
            "DO $$ BEGIN "
            "IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'agent_user') "
            "THEN CREATE ROLE agent_user NOLOGIN; END IF; END $$"
        )
        connection.exec_driver_sql(
            "CREATE TABLE agent_data_assets ("
            "id SERIAL PRIMARY KEY, asset_name TEXT NOT NULL, "
            "operational_metadata JSONB NOT NULL DEFAULT '{}'::jsonb)"
        )
        connection.exec_driver_sql(
            "CREATE TABLE agent_data_requests ("
            "id SERIAL PRIMARY KEY, asset_id INTEGER NOT NULL "
            "REFERENCES agent_data_assets(id), requester VARCHAR(100) NOT NULL, "
            "status VARCHAR(30) NOT NULL DEFAULT 'pending', approver VARCHAR(100), "
            "approved_at TIMESTAMP, created_at TIMESTAMP NOT NULL DEFAULT NOW())"
        )
        for migration in MIGRATIONS:
            connection.exec_driver_sql(_sql_file(migration.path))
        connection.exec_driver_sql(f'GRANT gda_control_gateway TO "{login_role}"')


def _slo_draft(created_at: datetime) -> SLODefinitionDraft:
    return SLODefinitionDraft(
        tenant_id=TENANT,
        slo_definition_ref=SLO_REF,
        slo_version_ref=SLO_VERSION,
        version=1,
        service_resource_urn="gda://planning/gis_service/district-features",
        indicator=SLOEventRatioIndicator(
            metric_name="gda_gis_service_requests_total",
            good_outcomes=("success",),
            bad_outcomes=("error",),
            match_labels={"service": "district-features"},
        ),
        objective_basis_points=9900,
        objective_window_seconds=86400,
        owner_subject="team:geo-platform",
        oncall_ref="oncall:geo-platform",
        burn_rate_windows=(
            SLOBurnRateWindow(
                name="fast",
                short_window_seconds=300,
                long_window_seconds=3600,
                burn_rate_milli=14400,
                minimum_events=20,
                for_seconds=120,
                severity="critical",
            ),
        ),
        created_by=SLO_ACTOR,
        creation_reason="synthetic JQDLTB serving bridge certification",
        created_at=created_at,
    )


def _sqlstate(exc: BaseException) -> str | None:
    current: BaseException | None = exc
    seen: set[int] = set()
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        original = getattr(current, "orig", None)
        state = getattr(original, "sqlstate", None) or getattr(original, "pgcode", None)
        if state:
            return state
        current = current.__cause__ or current.__context__
    return None


def _expect_db_rejection(callback) -> str:
    try:
        callback()
    except (DBAPIError, GatewayConflictError, GatewayValidationError) as exc:
        return _sqlstate(exc) or "gateway-error"
    raise AssertionError("database operation unexpectedly succeeded")


def _record_raw(
    engine: Engine,
    binding: JqdltbServingReleaseBinding,
    **overrides,
) -> None:
    values = {
        "tenant_id": str(binding.tenant_id),
        "data_product_version_id": binding.data_product_version_id,
        "product_urn": binding.product_urn,
        "manifest_sha256": binding.manifest_sha256,
        "output_resource_version_id": binding.output_resource_version_id,
        "service_urn": binding.service.service_urn,
        "service_definition_version_id": (
            binding.service.service_definition_version_id
        ),
        "layer_definition_version_id": binding.layer.layer_definition_version_id,
        "mvt_serving_projection_version_id": (
            binding.projection.mvt_serving_projection_version_id
        ),
        "service_release_binding_id": binding.release.service_release_binding_id,
        "slo_binding_id": binding.slo.binding_id,
        "serving_release_binding_sha256": binding.binding_sha256,
        "bound_by": binding.bound_by,
        "bound_at": binding.bound_at,
    }
    values.update(overrides)
    with engine.begin() as connection:
        connection.exec_driver_sql('SET LOCAL ROLE "gda_control_gateway"')
        connection.execute(
            text("SELECT set_config('app.current_tenant', :tenant_id, true)"),
            values,
        )
        connection.execute(
            text(
                """
                SELECT gda_control.record_jqdltb_serving_release_binding(
                    :tenant_id, :data_product_version_id, :product_urn,
                    :manifest_sha256, :output_resource_version_id,
                    :service_urn, :service_definition_version_id,
                    :layer_definition_version_id,
                    :mvt_serving_projection_version_id,
                    :service_release_binding_id, :slo_binding_id,
                    :serving_release_binding_sha256, :bound_by, :bound_at
                )
                """
            ),
            values,
        )


def _create_slo_activation(engine: Engine) -> tuple[str, str, int]:
    effective_now = datetime.now(UTC).replace(microsecond=0)
    slo = SLODefinitionAuthority(engine)
    staged = slo.stage(_slo_draft(effective_now))
    approvals = ApprovalCaseAuthority(engine)
    approvals.upsert_principal(
        tenant_id=TENANT,
        principal_subject=SLO_APPROVER,
        expected_directory_version=0,
        principal_type=ApprovalPrincipalType.HUMAN,
        display_name="Synthetic GIS service owner",
        status=ApprovalPrincipalStatus.ACTIVE,
        approval_eligible=True,
        availability_status=ApprovalAvailabilityStatus.AVAILABLE,
        valid_from=effective_now - timedelta(minutes=1),
        valid_until=effective_now + timedelta(hours=4),
        actor_subject="human:platform-admin",
        reason="register synthetic SLO certification approver",
    )
    case = ApprovalCase(
        tenant_id=TENANT,
        approval_case_ref=SLO_APPROVAL_REF,
        target_resource_urn=SLO_VERSION,
        target_fingerprint=staged.definition_fingerprint,
        action="slo_definition.activate",
        requester_subject=SLO_ACTOR,
        request_reason="approve synthetic GIS ServiceSLO objective",
        request_context={"schema": "gda.slo_definition_activation.v1"},
        requested_at=effective_now,
        expires_at=effective_now + timedelta(hours=4),
    )
    approvals.create(case, owner_ref="team:geo-platform")
    decided = approvals.decide(
        tenant_id=TENANT,
        approval_case_ref=SLO_APPROVAL_REF,
        expected_state_version=0,
        verdict=ApprovalCaseStatus.APPROVED,
        actor_subject=SLO_APPROVER,
        reason="approved synthetic serving SLO authority",
    )
    activation = slo.activate(
        tenant_id=TENANT,
        slo_version_ref=SLO_VERSION,
        definition_fingerprint=staged.definition_fingerprint,
        approval_case_ref=decided.approval_case_ref,
        expected_activation_version=0,
        actor_subject=SLO_ACTOR,
        reason="activate synthetic serving SLO authority",
    )
    return (
        staged.definition_fingerprint,
        decided.approval_case_ref,
        activation.activation_version,
    )


def _security_contract(engine: Engine) -> dict[str, bool]:
    with engine.connect() as connection:
        row = connection.execute(
            text(
                """
                SELECT c.relrowsecurity, c.relforcerowsecurity,
                       has_table_privilege(
                           'gda_control_gateway',
                           'gda_control.jqdltb_serving_release_binding', 'SELECT'
                       ),
                       has_table_privilege(
                           'gda_control_gateway',
                           'gda_control.jqdltb_serving_release_binding', 'INSERT'
                       ),
                       has_table_privilege(
                           'gda_control_gateway',
                           'gda_control.jqdltb_serving_release_binding', 'UPDATE'
                       ),
                       has_table_privilege(
                           'gda_control_gateway',
                           'gda_control.jqdltb_serving_release_binding', 'DELETE'
                       )
                  FROM pg_class c
                  JOIN pg_namespace n ON n.oid = c.relnamespace
                 WHERE n.nspname = 'gda_control'
                   AND c.relname = 'jqdltb_serving_release_binding'
                """
            )
        ).one()
    return {
        "rls_enabled": bool(row[0]),
        "rls_forced": bool(row[1]),
        "gateway_select": bool(row[2]),
        "gateway_insert": bool(row[3]),
        "gateway_update": bool(row[4]),
        "gateway_delete": bool(row[5]),
    }


def certify(database_url: str) -> dict[str, object]:
    source_url = make_url(database_url)
    admin = create_engine(source_url.set(database="postgres"), isolation_level="AUTOCOMMIT")
    temp_name = f"gda_jqdltb_serving_cert_{uuid4().hex[:10]}"
    login_role = f"gda_jqdltb_serving_login_{uuid4().hex[:10]}"
    password = uuid4().hex
    with admin.connect() as connection:
        connection.execute(
            text(f'CREATE ROLE "{login_role}" LOGIN PASSWORD :password'),
            {"password": password},
        )
        connection.execute(text(f'CREATE DATABASE "{temp_name}"'))
    temp_url = source_url.set(database=temp_name)
    login_url = source_url.set(
        username=login_role,
        password=password,
        database=temp_name,
    )
    engine = create_engine(temp_url)
    login_engine = create_engine(login_url)
    try:
        _bootstrap(engine, login_role)
        seed = _seed_authorities(
            engine,
            NOW,
            mapping_contract={
                "schema": "gda.jqdltb_mapping_binding.v1",
                "mapping": {"district_id": "district_id"},
            },
        )
        with engine.begin() as connection:
            connection.exec_driver_sql("CREATE EXTENSION IF NOT EXISTS postgis")
            connection.exec_driver_sql("CREATE SCHEMA serving")
            connection.exec_driver_sql(
                """
                CREATE TABLE serving.districts_v1 (
                    district_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    geom geometry(Polygon, 4326) NOT NULL
                )
                """
            )
            connection.exec_driver_sql(
                """
                INSERT INTO serving.districts_v1
                    (district_id, name, geom)
                VALUES (
                    'district-001', 'Synthetic district',
                    ST_GeomFromText(
                        'POLYGON((121 31,121.2 31,121.2 31.2,121 31.2,121 31))',
                        4326
                    )
                )
                """
            )
        definition = _definition(seed, NOW)
        gateway = PlatformGateway(login_engine)
        gateway.register_gis_service_definition_version(definition)
        layer, style, tile_matrix, cache_policy, projection, release = _release_bundle(
            seed, definition, NOW
        )
        gateway.register_layer_definition_version(layer)
        gateway.register_style_definition_version(style)
        gateway.register_tile_matrix_set_definition_version(tile_matrix)
        gateway.register_mvt_serving_projection_version(projection)
        gateway.register_cache_policy_version(cache_policy)
        gateway.register_service_release_binding(release)
        gateway.register_service_policy_binding(_service_policy(seed, definition, release, NOW))

        deployment = _deployment(seed, definition, release, NOW)
        run_id = deployment.run_id
        gateway.transition_run(
            TENANT,
            run_id,
            0,
            "dispatching",
            "workload:service-controller",
            "synthetic provider dispatch accepted",
        )
        gateway.transition_run(
            TENANT,
            run_id,
            1,
            "running",
            "workload:service-controller",
            "synthetic provider deployment running",
        )
        gateway.register_service_deployment_revision(deployment)
        gateway.transition_service_deployment_revision(
            TENANT,
            deployment.deployment_revision_id,
            expected_state_version=0,
            to_state="deploying",
            provider_observation_id=None,
            actor_subject="workload:serving-controller",
            reason="start synthetic JQDLTB provider deployment",
            idempotency_key="jqdltb-deploying",
            occurred_at=NOW + timedelta(seconds=4),
        )
        orchestration_evidence = {
            "schema": "gda.dolphinscheduler_observation.v1",
            "provider_state": "SUCCESS",
        }
        orchestration_observation = FrameworkAttemptObservation(
            tenant_id=TENANT,
            observation_id=uuid4(),
            run_id=run_id,
            attempt_no=1,
            framework_kind="dolphinscheduler",
            external_namespace="planning-jqdltb",
            external_run_id="district-features",
            external_attempt_id="deployment:17",
            observed_state="success",
            observation_sha256=canonical_json_fingerprint(orchestration_evidence),
            evidence=orchestration_evidence,
            observed_at=NOW + timedelta(seconds=5),
        )
        gateway.record_attempt(orchestration_observation)
        output_artifact = Artifact(
            tenant_id=TENANT,
            artifact_id=uuid4(),
            artifact_key="district-features-mvt",
            artifact_role=ArtifactRole.OUTPUT,
            storage_uri="s3://synthetic-gis/district-features-mvt.pmtiles",
            media_type="application/vnd.pmtiles",
            content_sha256="2" * 64,
            size_bytes=1024,
            run_id=run_id,
            resource_version_id=seed["output_id"],
            manifest={"tile_count": 3},
            created_by="workload:serving-controller",
            created_at=NOW + timedelta(seconds=5),
        )
        quality_evidence_artifact = Artifact(
            tenant_id=TENANT,
            artifact_id=uuid4(),
            artifact_key="district-features-quality",
            artifact_role=ArtifactRole.EVIDENCE,
            storage_uri="s3://synthetic-gis/district-features-quality.json",
            media_type="application/json",
            content_sha256="7" * 64,
            size_bytes=128,
            run_id=run_id,
            resource_version_id=seed["output_id"],
            manifest={"checks": ["schema", "crs", "tile_count"]},
            created_by="workload:quality-controller",
            created_at=NOW + timedelta(seconds=5),
        )
        gateway.record_artifact(output_artifact)
        gateway.record_artifact(quality_evidence_artifact)
        quality_values = {
            "tenant_id": TENANT,
            "quality_result_id": uuid4(),
            "run_id": run_id,
            "resource_version_id": seed["output_id"],
            "rule_version_ref": "gis-service-release:v1",
            "verdict": "passed",
            "metrics": {"invalid_geometry_count": 0, "tile_count": 3},
            "evidence_artifact_id": quality_evidence_artifact.artifact_id,
            "evaluated_by": "workload:quality-controller",
            "evaluated_at": NOW + timedelta(seconds=6),
        }
        quality = QualityResult(
            **quality_values,
            result_sha256=quality_result_fingerprint(
                **{
                    key: value
                    for key, value in quality_values.items()
                    if key != "quality_result_id"
                }
            ),
        )
        gateway.record_quality_result(quality)
        lineage_facets = {
            "schema": "gda.gis_service_projection_lineage.v1",
            "data_product_version_id": str(seed["product_version_id"]),
        }
        lineage = LineageEvent(
            tenant_id=TENANT,
            lineage_event_id=uuid4(),
            event_type=LineageEventType.PUBLISH,
            source_resource_version_id=seed["source_id"],
            target_resource_version_id=seed["output_id"],
            producer="workload:service-controller",
            event_sha256=canonical_json_fingerprint(lineage_facets),
            run_id=run_id,
            definition_version_id=seed["platform_definition_id"],
            artifact_id=output_artifact.artifact_id,
            facets=lineage_facets,
            occurred_at=NOW + timedelta(seconds=6),
        )
        gateway.record_lineage(lineage)
        success_values = {
            "tenant_id": TENANT,
            "run_id": run_id,
            "attempt_observation_id": orchestration_observation.observation_id,
            "output_artifact_id": output_artifact.artifact_id,
            "quality_result_id": quality.quality_result_id,
            "lineage_event_id": lineage.lineage_event_id,
        }
        gateway.finalize_run_success(
            RunSuccessEvidence(
                **success_values,
                evidence_sha256=run_success_evidence_fingerprint(**success_values),
            ),
            expected_state_version=2,
            actor_subject="workload:service-controller",
            reason="synthetic JQDLTB provider success",
        )
        endpoint_uri = "https://geo.example.test/tiles/districts-jqdltb"
        observation_evidence = {
            "schema": "gda.gis_service_deployment_observation.v2",
            "deployment_revision_id": str(deployment.deployment_revision_id),
            "service_definition_version_id": str(
                deployment.service_definition_version_id
            ),
            "service_release_binding_id": str(
                deployment.service_release_binding_id
            ),
            "provider_system": deployment.provider_system,
            "provider_version": "synthetic-1.0.0",
            "provider_namespace": deployment.provider_namespace,
            "provider_deployment_id": deployment.provider_deployment_id,
            "provider_revision_ref": deployment.provider_revision_ref,
            "config_sha256": deployment.config_sha256,
            "endpoint_uri": endpoint_uri,
            "health_evidence_sha256": "9" * 64,
            "provider_receipt": {"health_status": 200},
        }
        observation = FrameworkAttemptObservation(
            tenant_id=TENANT,
            observation_id=uuid4(),
            run_id=deployment.run_id,
            attempt_no=1,
            framework_kind="cloud",
            external_namespace=deployment.provider_namespace,
            external_run_id=deployment.provider_deployment_id,
            external_attempt_id=deployment.provider_revision_ref,
            observed_state="ready",
            observation_sha256=canonical_json_fingerprint(observation_evidence),
            evidence=observation_evidence,
            observed_at=NOW + timedelta(seconds=5),
        )
        ready_deployment = gateway.settle_gis_service_deployment_terminal(
            deployment.deployment_revision_id,
            observation,
            expected_state_version=1,
            actor_subject="workload:serving-controller",
            reason="settle synthetic JQDLTB provider deployment ready",
            idempotency_key="jqdltb-ready",
            occurred_at=NOW + timedelta(seconds=6),
        ).deployment
        endpoint = _endpoint(
            seed,
            ready_deployment,
            projection,
            NOW + timedelta(seconds=7),
            suffix="jqdltb",
            endpoint_uri=endpoint_uri,
        )
        gateway.register_endpoint_revision(endpoint)

        activation_without_binding_sqlstate = _expect_db_rejection(
            lambda: gateway.activate_gis_service_endpoint(
                TENANT,
                str(seed["service_urn"]),
                endpoint.endpoint_revision_id,
                expected_state_version=0,
                actor_subject="workload:serving-controller",
                reason="reject JQDLTB activation without serving bridge",
                idempotency_key="jqdltb-activation-without-binding",
                occurred_at=NOW + timedelta(seconds=8),
            )
        )

        fingerprint, approval_ref, activation_version = _create_slo_activation(login_engine)
        slo = GISServiceSLOBinding(
            tenant_id=TENANT,
            binding_id=uuid4(),
            service_urn=str(seed["service_urn"]),
            slo_definition_ref=SLO_REF,
            active_version_ref=SLO_VERSION,
            definition_fingerprint=fingerprint,
            approval_case_ref=approval_ref,
            activation_version=activation_version,
            bound_by=SLO_ACTOR,
            binding_reason="bind exact synthetic serving SLO",
            bound_at=NOW + timedelta(minutes=1),
        )
        gateway.bind_gis_service_slo(slo)
        binding = build_jqdltb_serving_release_binding(
            tenant_id=TENANT,
            product_urn=str(seed["product_urn"]),
            data_product_version_id=seed["product_version_id"],
            manifest_sha256=str(seed["product_manifest_sha256"]),
            output_resource_version_id=seed["output_id"],
            service=definition,
            layer=layer,
            projection=projection,
            release=release,
            slo=slo,
            bound_by="workload:serving-controller",
            bound_at=NOW + timedelta(minutes=2),
        )
        first = gateway.register_jqdltb_serving_release_binding(binding)
        replay = gateway.register_jqdltb_serving_release_binding(binding)
        activation_without_relation_attestation_sqlstate = _expect_db_rejection(
            lambda: gateway.activate_gis_service_endpoint(
                TENANT,
                str(seed["service_urn"]),
                endpoint.endpoint_revision_id,
                expected_state_version=0,
                actor_subject="workload:serving-controller",
                reason="reject JQDLTB activation without relation attestation",
                idempotency_key="jqdltb-activation-without-relation-attestation",
                occurred_at=NOW + timedelta(minutes=2, seconds=1),
            )
        )
        relation_attestation = gateway.record_mvt_serving_relation_attestation(
            projection,
            attested_by="workload:serving-controller",
            attested_at=NOW + timedelta(minutes=2, seconds=2),
        )
        relation_attestation_replay = gateway.record_mvt_serving_relation_attestation(
            projection,
            attested_by="workload:serving-controller",
            attested_at=NOW + timedelta(minutes=2, seconds=2),
        )
        activated = gateway.activate_gis_service_endpoint(
            TENANT,
            str(seed["service_urn"]),
            endpoint.endpoint_revision_id,
            expected_state_version=0,
            actor_subject="workload:serving-controller",
            reason="activate exact JQDLTB serving bridge",
            idempotency_key="jqdltb-activation-with-binding",
            occurred_at=NOW + timedelta(minutes=3),
        )
        with engine.begin() as connection:
            connection.exec_driver_sql(
                "ALTER TABLE serving.districts_v1 RENAME COLUMN name TO name_drift"
            )
        relation_drift_sqlstate = _expect_db_rejection(
            lambda: gateway.activate_gis_service_endpoint(
                TENANT,
                str(seed["service_urn"]),
                endpoint.endpoint_revision_id,
                expected_state_version=1,
                actor_subject="workload:serving-controller",
                reason="reject activation after serving relation drift",
                idempotency_key="jqdltb-activation-after-relation-drift",
                occurred_at=NOW + timedelta(minutes=3, seconds=1),
            )
        )
        stored = gateway.get_jqdltb_serving_release_binding(
            TENANT, seed["product_version_id"]
        )

        manifest_drift_sqlstate = _expect_db_rejection(
            lambda: _record_raw(
                login_engine,
                binding,
                manifest_sha256="f" * 64,
            )
        )
        output_drift_sqlstate = _expect_db_rejection(
            lambda: _record_raw(
                login_engine,
                binding,
                output_resource_version_id=uuid4(),
            )
        )
        slo_drift_sqlstate = _expect_db_rejection(
            lambda: _record_raw(
                login_engine,
                binding,
                slo_binding_id=uuid4(),
            )
        )

        cross_tenant_rows = 0
        try:
            gateway.get_jqdltb_serving_release_binding("other", seed["product_version_id"])
        except GatewayNotFoundError:
            cross_tenant_rows = 0
        else:
            cross_tenant_rows = 1

        direct_update_sqlstate = _expect_db_rejection(
            lambda: _direct_update(login_engine, seed["product_version_id"])
        )
        direct_delete_sqlstate = _expect_db_rejection(
            lambda: _direct_delete(login_engine, seed["product_version_id"])
        )
        security = _security_contract(engine)
        with engine.connect() as connection:
            count = int(
                connection.execute(
                    text(
                        "SELECT count(*) "
                        "FROM gda_control.jqdltb_serving_release_binding"
                    )
                ).scalar_one()
            )
        report = {
            "schema": "gda.jqdltb_serving_release_binding_certification.v3",
            "status": "passed",
            "evidence_class": "synthetic_disposable",
            "database": temp_name,
            "migrations": [migration.migration_id for migration in MIGRATIONS],
            "product_version_id": str(seed["product_version_id"]),
            "binding_id": str(binding.data_product_version_id),
            "first_created": first.created,
            "replay_created": replay.created,
            "replay_same_identity": first.value == replay.value,
            "stored_identity_matches": stored["serving_release_binding_sha256"]
            == binding.binding_sha256,
            "relation_attestation_created": relation_attestation.created,
            "relation_attestation_replay_created": relation_attestation_replay.created,
            "relation_attestation_schema_sha256": (
                relation_attestation.value.relation_schema_sha256
            ),
            "activation_without_relation_attestation_sqlstate": (
                activation_without_relation_attestation_sqlstate
            ),
            "relation_drift_sqlstate": relation_drift_sqlstate,
            "activation_without_binding_sqlstate": activation_without_binding_sqlstate,
            "activation_after_binding_state_version": activated.endpoint_state_version,
            "cross_tenant_rows": cross_tenant_rows,
            "manifest_drift_sqlstate": manifest_drift_sqlstate,
            "output_drift_sqlstate": output_drift_sqlstate,
            "slo_drift_sqlstate": slo_drift_sqlstate,
            "direct_update_sqlstate": direct_update_sqlstate,
            "direct_delete_sqlstate": direct_delete_sqlstate,
            "row_count": count,
            "security": security,
        }
        if (
            not first.created
            or replay.created
            or first.value != replay.value
            or not report["stored_identity_matches"]
            or not report["relation_attestation_created"]
            or report["relation_attestation_replay_created"]
            or activation_without_relation_attestation_sqlstate != "23514"
            or relation_drift_sqlstate != "23514"
            or activation_without_binding_sqlstate != "23514"
            or activated.endpoint_state_version != 1
            or cross_tenant_rows != 0
            or manifest_drift_sqlstate != "23514"
            or output_drift_sqlstate != "23514"
            or slo_drift_sqlstate != "23514"
            or direct_update_sqlstate != "42501"
            or direct_delete_sqlstate != "42501"
            or count != 1
            or security != {
                "rls_enabled": True,
                "rls_forced": True,
                "gateway_select": True,
                "gateway_insert": False,
                "gateway_update": False,
                "gateway_delete": False,
            }
        ):
            report["status"] = "failed"
            raise RuntimeError(json.dumps(report, indent=2, sort_keys=True))
        return report
    finally:
        engine.dispose()
        login_engine.dispose()
        with admin.connect() as connection:
            connection.execute(text(f'DROP DATABASE IF EXISTS "{temp_name}" WITH (FORCE)'))
            connection.execute(text(f'DROP ROLE IF EXISTS "{login_role}"'))
        admin.dispose()


def _direct_update(engine: Engine, product_version_id) -> None:
    with engine.begin() as connection:
        connection.exec_driver_sql('SET LOCAL ROLE "gda_control_gateway"')
        connection.execute(
            text("SELECT set_config('app.current_tenant', :tenant, true)"),
            {"tenant": TENANT},
        )
        connection.execute(
            text(
                "UPDATE gda_control.jqdltb_serving_release_binding "
                "SET bound_by = 'workload:mutated' "
                "WHERE tenant_id = :tenant AND data_product_version_id = :version_id"
            ),
            {"tenant": TENANT, "version_id": product_version_id},
        )


def _direct_delete(engine: Engine, product_version_id) -> None:
    with engine.begin() as connection:
        connection.exec_driver_sql('SET LOCAL ROLE "gda_control_gateway"')
        connection.execute(
            text("SELECT set_config('app.current_tenant', :tenant, true)"),
            {"tenant": TENANT},
        )
        connection.execute(
            text(
                "DELETE FROM gda_control.jqdltb_serving_release_binding "
                "WHERE tenant_id = :tenant AND data_product_version_id = :version_id"
            ),
            {"tenant": TENANT, "version_id": product_version_id},
        )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--database-url",
        default=os.environ.get(
            "GDA_CERT_DATABASE_URL",
            "postgresql+psycopg2://postgres:postgres@127.0.0.1:5433/gis_agent",
        ),
    )
    args = parser.parse_args()
    print(json.dumps(certify(args.database_url), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
