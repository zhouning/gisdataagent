#!/usr/bin/env python3
"""Certify the minimal GIS Service Control Plane on disposable PostgreSQL."""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.exc import DBAPIError

from data_agent.approval_case_authority import ApprovalCaseAuthority
from data_agent.gis_service_control_plane import (
    CachePolicyVersion,
    EndpointRevision,
    GISServiceDefinitionVersion,
    LayerDefinitionVersion,
    MVTServingProjectionVersion,
    ServiceDeploymentRevision,
    ServicePolicyBinding,
    ServiceReleaseBinding,
    StyleDefinitionVersion,
    TileMatrixSetDefinitionVersion,
    cache_policy_version_fingerprint,
    endpoint_revision_fingerprint,
    gis_service_definition_fingerprint,
    layer_definition_fingerprint,
    mvt_serving_projection_fingerprint,
    service_deployment_fingerprint,
    service_policy_binding_fingerprint,
    service_release_binding_fingerprint,
    style_definition_fingerprint,
    tile_matrix_set_definition_fingerprint,
)
from data_agent.migration_runner import catalog_fingerprint, discover_migrations
from data_agent.platform_contracts import (
    ApprovalAvailabilityStatus,
    ApprovalCaseStatus,
    ApprovalPrincipalStatus,
    ApprovalPrincipalType,
    Artifact,
    FrameworkAttemptObservation,
    LineageEvent,
    QualityResult,
    RunSuccessEvidence,
    canonical_json_fingerprint,
    quality_result_fingerprint,
    run_success_evidence_fingerprint,
)
from data_agent.platform_gateway import (
    GatewayConflictError,
    GatewayForbiddenError,
    GatewayNotFoundError,
    GatewayValidationError,
    PlatformGateway,
)
from data_agent.service_consumer_binding import (
    ServiceConsumerBinding,
    service_consumer_binding_fingerprint,
)
from data_agent.service_consumer_binding_grant import (
    ServiceConsumerBindingGrantService,
    build_service_consumer_binding_grant_plan,
)
from data_agent.service_consumer_binding_renewal import (
    ServiceConsumerBindingRenewal,
    ServiceConsumerBindingRenewalService,
    build_service_consumer_binding_renewal_plan,
)
from data_agent.service_consumer_binding_revocation import (
    ServiceConsumerBindingRevocation,
    ServiceConsumerBindingRevocationService,
    build_service_consumer_binding_revoke_plan,
)

MIGRATIONS = (
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
    "238_ogc_api_features_endpoint_contract.sql",
    "239_gis_ogc_api_features_read_authorization.sql",
)


def _sql_file(filename: str) -> str:
    path = Path(__file__).resolve().parents[1] / "data_agent/migrations" / filename
    return path.read_text(encoding="utf-8").replace("%", "%%")


def _bootstrap(engine: Engine, login_role: str) -> None:
    with engine.begin() as connection:
        # The promotion-impact migrations retain these legacy catalog tables as
        # a compatibility path.  The disposable control-plane fixture creates
        # only their schema; it does not exercise the legacy delivery flow.
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
        for filename in MIGRATIONS:
            connection.exec_driver_sql(_sql_file(filename))
        connection.exec_driver_sql(f'GRANT gda_control_gateway TO "{login_role}"')


def _seed_authorities(
    engine: Engine,
    now: datetime,
    *,
    output_content_sha256: str = "2" * 64,
    mapping_contract: dict[str, object] | None = None,
) -> dict[str, object]:
    tenant = "planning"
    service_urn = "gda://planning/gis_service/district-features"
    product_urn = "gda://planning/data_product/districts"
    source_urn = "gda://planning/dataset/district-source"
    output_urn = "gda://planning/dataset/district-output"
    definition_urn = "gda://planning/definition/district-service-deploy"
    source_id = uuid4()
    output_id = uuid4()
    product_version_id = uuid4()
    quality_artifact_id = uuid4()
    platform_definition_id = uuid4()
    run_id = uuid4()
    product_manifest_sha256 = "4" * 64
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO gda_control.resource (
                    tenant_id, resource_urn, resource_kind, authority_system,
                    authority_locator, owner_ref, governance_ref, technical_refs
                ) VALUES
                    (:tenant, :service_urn, 'gis_service', 'gda',
                     'service/district-features', 'team:geo-platform',
                     '{}'::jsonb, '[]'::jsonb),
                    (:tenant, :source_urn, 'dataset', 'certifier',
                     'dataset/district-source', 'team:data-platform',
                     '{}'::jsonb, '[]'::jsonb),
                    (:tenant, :output_urn, 'dataset', 'certifier',
                     'dataset/district-output', 'team:data-platform',
                     '{}'::jsonb, '[]'::jsonb),
                    (:tenant, :definition_urn, 'definition', 'gda',
                     'definition/district-service-deploy', 'team:geo-platform',
                     '{}'::jsonb, '[]'::jsonb)
                """
            ),
            {
                "tenant": tenant,
                "service_urn": service_urn,
                "source_urn": source_urn,
                "output_urn": output_urn,
                "definition_urn": definition_urn,
            },
        )
        connection.execute(
            text(
                """
                INSERT INTO gda_control.resource_version (
                    tenant_id, resource_version_id, resource_urn, version_key,
                    predecessor_version_id, content_sha256,
                    authority_version_ref, created_by, created_at
                ) VALUES
                    (:tenant, :source_id, :source_urn, 'snapshot-1', NULL,
                     :source_sha, '{}'::jsonb, 'workload:certifier', :now),
                    (:tenant, :output_id, :output_urn, 'snapshot-1', NULL,
                     :output_sha, '{}'::jsonb, 'workload:certifier', :now),
                    (:tenant, :definition_id, :definition_urn, 'v1', NULL,
                     :definition_sha, '{}'::jsonb,
                     'workload:service-controller', :now)
                """
            ),
            {
                "tenant": tenant,
                "source_id": source_id,
                "source_urn": source_urn,
                "source_sha": "1" * 64,
                "output_id": output_id,
                "output_urn": output_urn,
                "output_sha": output_content_sha256,
                "definition_id": platform_definition_id,
                "definition_urn": definition_urn,
                "definition_sha": "3" * 64,
                "now": now,
            },
        )
        connection.execute(
            text(
                """
                INSERT INTO gda_control.platform_definition_version (
                    tenant_id, definition_version_id, definition_urn,
                    orchestration_class, capability_id, portability_class,
                    definition_document, input_contract, output_contract,
                    definition_sha256
                ) VALUES (
                    :tenant, :definition_id, :definition_urn, 'dataops',
                    'gis-service-deploy', 'engine_family',
                    '{"schema":"gda.gis_service_deploy.v1"}'::jsonb,
                    '{"source":"data_product_output"}'::jsonb,
                    '{"deployment":"provider_revision"}'::jsonb,
                    :definition_sha
                )
                """
            ),
            {
                "tenant": tenant,
                "definition_id": platform_definition_id,
                "definition_urn": definition_urn,
                "definition_sha": "3" * 64,
            },
        )
        connection.execute(
            text(
                """
                INSERT INTO gda_control.artifact (
                    tenant_id, artifact_id, artifact_key, artifact_role,
                    storage_uri, media_type, content_sha256, size_bytes,
                    manifest, created_by, created_at
                ) VALUES (
                    :tenant, :artifact_id, 'quality.json', 'evidence',
                    'file:///quality.json', 'application/json', :artifact_sha,
                    1, '{}'::jsonb, 'workload:quality-controller', :now
                )
                """
            ),
            {
                "tenant": tenant,
                "artifact_id": quality_artifact_id,
                "artifact_sha": "5" * 64,
                "now": now,
            },
        )
        connection.execute(
            text(
                """
                INSERT INTO gda_control.data_product (
                    tenant_id, product_urn, product_slug, title, description,
                    domain, owner_ref, governance_ref, created_at, updated_at
                ) VALUES (
                    :tenant, :product_urn, 'districts', 'Districts',
                    'Governed district product', 'planning',
                    'team:data-platform', CAST(:governance_ref AS jsonb),
                    :now, :now
                )
                """
            ),
            {
                "tenant": tenant,
                "product_urn": product_urn,
                "governance_ref": json.dumps(
                    {
                        "classification": "internal",
                        "visibility": "private",
                        "license_id": "internal",
                        "attribution": "planning authority",
                    }
                ),
                "now": now,
            },
        )
        connection.execute(
            text(
                """
                INSERT INTO gda_control.data_product_version (
                    tenant_id, data_product_version_id, product_urn,
                    version_key, predecessor_version_id,
                    source_resource_version_id, output_resource_version_id,
                    standard_version_ref, mapping_contract, quality_contract,
                    quality_verdict, quality_evidence_artifact_id,
                    distribution_manifest, manifest_sha256,
                    published_by, published_at
                ) VALUES (
                    :tenant, :product_version_id, :product_urn, 'v1.0.0', NULL,
                    :source_id, :output_id, 'standard:district-v1',
                    CAST(:mapping_contract AS jsonb),
                    '{"verdict":"passed"}'::jsonb, 'passed', :artifact_id,
                    '{"formats":["geoparquet"]}'::jsonb, :manifest_sha,
                    'workload:product-publisher', :now
                )
                """
            ),
            {
                "tenant": tenant,
                "product_version_id": product_version_id,
                "product_urn": product_urn,
                "source_id": source_id,
                "output_id": output_id,
                "artifact_id": quality_artifact_id,
                "manifest_sha": product_manifest_sha256,
                "mapping_contract": json.dumps(
                    mapping_contract
                    or {"mapping": {"district_id": "district_id"}}
                ),
                "now": now,
            },
        )
        connection.execute(
            text(
                """
                UPDATE gda_control.data_product
                   SET current_version_id = :product_version_id,
                       updated_at = :updated_at
                 WHERE tenant_id = :tenant AND product_urn = :product_urn
                """
            ),
            {
                "product_version_id": product_version_id,
                "updated_at": now + timedelta(seconds=1),
                "tenant": tenant,
                "product_urn": product_urn,
            },
        )
        connection.execute(
            text(
                """
                INSERT INTO gda_control.data_product_event (
                    tenant_id, event_id, product_urn, event_type,
                    from_version_id, to_version_id, actor_subject,
                    reason, idempotency_key, occurred_at
                ) VALUES (
                    :tenant, :event_id, :product_urn, 'published', NULL,
                    :product_version_id, 'workload:product-publisher',
                    'initial governed publication', 'publish-v1', :occurred_at
                )
                """
            ),
            {
                "tenant": tenant,
                "event_id": uuid4(),
                "product_urn": product_urn,
                "product_version_id": product_version_id,
                "occurred_at": now + timedelta(seconds=1),
            },
        )
        connection.execute(
            text(
                """
                INSERT INTO gda_control.platform_run (
                    tenant_id, run_id, definition_version_id,
                    orchestration_class, subject_context, idempotency_key,
                    policy_refs, status, state_version,
                    submitted_by, submitted_at, updated_at
                ) VALUES (
                    :tenant, :run_id, :definition_id, 'dataops',
                    CAST(:subject_context AS jsonb), 'deploy-district-v1',
                    '{}'::jsonb, 'accepted', 0,
                    'workload:service-controller', :submitted_at, :submitted_at
                )
                """
            ),
            {
                "tenant": tenant,
                "run_id": run_id,
                "definition_id": platform_definition_id,
                "subject_context": json.dumps(
                    {
                        "tenant_id": tenant,
                        "subject_type": "workload",
                        "subject_id": "service-controller",
                        "roles": ["service_operator"],
                        "purpose": "deploy governed GIS service",
                    }
                ),
                "submitted_at": now + timedelta(seconds=2),
            },
        )
        connection.execute(
            text(
                """
                INSERT INTO gda_control.platform_run_input_binding (
                    tenant_id, run_id, binding_name,
                    resource_version_id, semantic_type
                ) VALUES
                    (:tenant, :run_id, 'source_dataset', :source_id,
                     'gda.data_product.source'),
                    (:tenant, :run_id, 'source_product', :output_id,
                     'gda.data_product.output')
                """
            ),
            {
                "tenant": tenant,
                "run_id": run_id,
                "source_id": source_id,
                "output_id": output_id,
            },
        )
    return {
        "tenant": tenant,
        "service_urn": service_urn,
        "product_urn": product_urn,
        "source_id": source_id,
        "output_id": output_id,
        "product_version_id": product_version_id,
        "product_manifest_sha256": product_manifest_sha256,
        "output_content_sha256": output_content_sha256,
        "quality_artifact_id": quality_artifact_id,
        "platform_definition_id": platform_definition_id,
        "run_id": run_id,
    }


def _definition(seed: dict[str, object], now: datetime) -> GISServiceDefinitionVersion:
    values = {
        "tenant_id": seed["tenant"],
        "service_definition_version_id": uuid4(),
        "service_urn": seed["service_urn"],
        "version_key": "v1.0.0",
        "platform_definition_version_id": seed["platform_definition_id"],
        "source_product_urn": seed["product_urn"],
        "source_data_product_version_id": seed["product_version_id"],
        "source_manifest_sha256": seed["product_manifest_sha256"],
        "service_type": "vector_tile",
        "service_contract": {
            "schema": "gda.gis_service_definition.v1",
            "operations": ["tiles"],
            "crs": ["EPSG:3857"],
        },
        "created_by": "workload:service-controller",
        "created_at": now + timedelta(seconds=3),
    }
    return GISServiceDefinitionVersion(
        **values,
        definition_sha256=gis_service_definition_fingerprint(values),
    )


def _release_bundle(
    seed: dict[str, object],
    definition: GISServiceDefinitionVersion,
    now: datetime,
    *,
    layer_key: str = "districts",
) -> tuple[
    LayerDefinitionVersion,
    StyleDefinitionVersion,
    TileMatrixSetDefinitionVersion,
    CachePolicyVersion,
    MVTServingProjectionVersion,
    ServiceReleaseBinding,
]:
    layer_values = {
        "tenant_id": seed["tenant"],
        "layer_definition_version_id": uuid4(),
        "service_definition_version_id": definition.service_definition_version_id,
        "layer_key": layer_key,
        "version_key": "v1.0.0",
        "source_output_resource_version_id": seed["output_id"],
        "geometry_type": "multipolygon",
        "geometry_column": "geom",
        "schema_contract": {
            "schema": "gda.layer_schema.v1",
            "properties": {
                "district_id": {"type": "string"},
                "name": {"type": "string"},
            },
        },
        "crs_uri": "http://www.opengis.net/def/crs/OGC/1.3/CRS84",
        "spatial_extent": (120.8, 30.6, 122.2, 31.9),
        "created_by": "workload:service-controller",
        "created_at": now + timedelta(seconds=4),
    }
    layer = LayerDefinitionVersion(
        **layer_values,
        definition_sha256=layer_definition_fingerprint(layer_values),
    )
    style_values = {
        "tenant_id": seed["tenant"],
        "style_definition_version_id": uuid4(),
        "service_definition_version_id": definition.service_definition_version_id,
        "layer_definition_version_id": layer.layer_definition_version_id,
        "style_key": "default",
        "version_key": "v1.0.0",
        "style_format": "mapbox_style",
        "style_document": {
            "version": 8,
            "layers": [{"id": layer_key, "type": "fill"}],
        },
        "created_by": "workload:service-controller",
        "created_at": now + timedelta(seconds=4),
    }
    style = StyleDefinitionVersion(
        **style_values,
        style_sha256=style_definition_fingerprint(style_values),
    )
    tile_values = {
        "tenant_id": seed["tenant"],
        "tile_matrix_set_definition_version_id": uuid4(),
        "service_definition_version_id": definition.service_definition_version_id,
        "layer_definition_version_id": layer.layer_definition_version_id,
        "tile_matrix_set_key": f"webmercatorquad-{layer_key}",
        "version_key": "v1.0.0",
        "crs_uri": "http://www.opengis.net/def/crs/EPSG/0/3857",
        "tile_width": 256,
        "tile_height": 256,
        "min_zoom": 0,
        "max_zoom": 2,
        "scale_denominators": (559082264.029, 279541132.015, 139770566.007),
        "spatial_extent": (
            -20037508.3428,
            -20037508.3428,
            20037508.3428,
            20037508.3428,
        ),
        "created_by": "workload:service-controller",
        "created_at": now + timedelta(seconds=4),
    }
    tile_matrix = TileMatrixSetDefinitionVersion(
        **tile_values,
        definition_sha256=tile_matrix_set_definition_fingerprint(tile_values),
    )
    cache_policy_values = {
        "tenant_id": seed["tenant"],
        "cache_policy_version_id": uuid4(),
        "service_definition_version_id": definition.service_definition_version_id,
        "cache_policy_key": "mvt-private",
        "version_key": "v1.0.0",
        "cache_namespace": "district-features",
        "cache_max_age_seconds": 60,
        "cache_key_dimensions": (
            "tenant",
            "service_release",
            "principal",
            "tile",
        ),
        "created_by": "workload:service-controller",
        "created_at": now + timedelta(seconds=4),
    }
    cache_policy = CachePolicyVersion(
        **cache_policy_values,
        policy_sha256=cache_policy_version_fingerprint(cache_policy_values),
    )
    serving_projection_values = {
        "tenant_id": seed["tenant"],
        "mvt_serving_projection_version_id": uuid4(),
        "service_definition_version_id": definition.service_definition_version_id,
        "layer_definition_version_id": layer.layer_definition_version_id,
        "projection_key": f"{layer_key}-serving",
        "version_key": "v1.0.0",
        "source_output_resource_version_id": seed["output_id"],
        "source_schema": "serving",
        "source_table": f"{layer_key.replace('-', '_')}_v1",
        "geometry_column": layer.geometry_column,
        "geometry_srid": 4326,
        "feature_id_column": "district_id",
        "property_allowlist": ("name",),
        "allowed_spatial_extent": (120.8, 30.6, 122.2, 31.9),
        "max_features_per_tile": 10_000,
        "source_content_sha256": seed["output_content_sha256"],
        "created_by": "workload:service-controller",
        "created_at": now + timedelta(seconds=4),
    }
    serving_projection = MVTServingProjectionVersion(
        **serving_projection_values,
        projection_sha256=mvt_serving_projection_fingerprint(
            serving_projection_values
        ),
    )
    release_values = {
        "tenant_id": seed["tenant"],
        "service_release_binding_id": uuid4(),
        "service_definition_version_id": definition.service_definition_version_id,
        "layer_definition_version_id": layer.layer_definition_version_id,
        "style_definition_version_id": style.style_definition_version_id,
        "tile_matrix_set_definition_version_id": (
            tile_matrix.tile_matrix_set_definition_version_id
        ),
        "cache_policy_version_id": cache_policy.cache_policy_version_id,
        "mvt_serving_projection_version_id": (
            serving_projection.mvt_serving_projection_version_id
        ),
        "release_key": "v1.0.0",
        "created_by": "workload:service-controller",
        "created_at": now + timedelta(seconds=4),
    }
    release = ServiceReleaseBinding(
        **release_values,
        binding_sha256=service_release_binding_fingerprint(release_values),
    )
    return layer, style, tile_matrix, cache_policy, serving_projection, release


def _service_policy(
    seed: dict[str, object],
    definition: GISServiceDefinitionVersion,
    release: ServiceReleaseBinding,
    now: datetime,
) -> ServicePolicyBinding:
    values = {
        "tenant_id": seed["tenant"],
        "service_policy_binding_id": uuid4(),
        "service_definition_version_id": definition.service_definition_version_id,
        "service_release_binding_id": release.service_release_binding_id,
        "policy_key": "mvt-gateway-read",
        "version_key": "v1.0.0",
        "allowed_roles": (
            "admin",
            "platform_operator",
            "viewer",
            "analyst",
            "standard_editor",
            "standard_reviewer",
        ),
        "consumer_binding_required_roles": (
            "viewer",
            "analyst",
            "standard_editor",
            "standard_reviewer",
        ),
        "created_by": "workload:service-controller",
        "created_at": now + timedelta(seconds=4),
    }
    return ServicePolicyBinding(
        **values,
        policy_sha256=service_policy_binding_fingerprint(values),
    )


def _deployment(
    seed: dict[str, object],
    definition: GISServiceDefinitionVersion,
    release: ServiceReleaseBinding,
    now: datetime,
    *,
    revision_key: str = "r1",
    provider_system: str = "pygeoapi",
    provider_namespace: str = "planning-prod",
    provider_deployment_id: str = "district-features",
    provider_revision_ref: str = "deployment:17",
    config_sha256: str = "6" * 64,
) -> ServiceDeploymentRevision:
    values = {
        "tenant_id": seed["tenant"],
        "deployment_revision_id": uuid4(),
        "service_definition_version_id": definition.service_definition_version_id,
        "service_release_binding_id": release.service_release_binding_id,
        "run_id": seed["run_id"],
        "revision_key": revision_key,
        "provider_system": provider_system,
        "provider_namespace": provider_namespace,
        "provider_deployment_id": provider_deployment_id,
        "provider_revision_ref": provider_revision_ref,
        "config_sha256": config_sha256,
        "created_by": "workload:service-controller",
        "created_at": now + timedelta(seconds=4),
    }
    return ServiceDeploymentRevision(
        **values,
        deployment_sha256=service_deployment_fingerprint(values),
        updated_at=values["created_at"],
    )


def _endpoint(
    seed: dict[str, object],
    deployment: ServiceDeploymentRevision,
    serving_projection: MVTServingProjectionVersion,
    now: datetime,
    *,
    suffix: str,
    endpoint_uri: str | None = None,
) -> EndpointRevision:
    values = {
        "tenant_id": seed["tenant"],
        "endpoint_revision_id": uuid4(),
        "service_urn": seed["service_urn"],
        "deployment_revision_id": deployment.deployment_revision_id,
        "endpoint_protocol": "mvt",
        "endpoint_uri": endpoint_uri
        or f"https://geo.example.test/tiles/districts-{suffix}",
        "endpoint_contract": {
            "schema": "gda.mvt_endpoint.v1",
            "provider_layer_ref": "gda_mvt_serving_projection",
            "provider_query": {
                "serving_projection_version_id": str(
                    serving_projection.mvt_serving_projection_version_id
                )
            },
        },
        "created_by": "workload:service-controller",
        "created_at": now,
    }
    return EndpointRevision(
        **values,
        endpoint_sha256=endpoint_revision_fingerprint(values),
    )


def _sqlstate(exc: DBAPIError) -> str | None:
    original = getattr(exc, "orig", None)
    return getattr(original, "sqlstate", None) or getattr(original, "pgcode", None)


def certify(database_url: str, *, report_path: Path | None = None) -> dict[str, object]:
    source_url = make_url(database_url)
    admin_url = source_url.set(database="postgres")
    admin = create_engine(admin_url, isolation_level="AUTOCOMMIT")
    temp_name = f"gda_gis_service_cert_{uuid4().hex[:10]}"
    login_role = f"gda_gis_service_login_{uuid4().hex[:10]}"
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
    now = datetime(2026, 8, 7, 12, 0, tzinfo=UTC)
    try:
        _bootstrap(engine, login_role)
        seed = _seed_authorities(engine, now)
        tenant = str(seed["tenant"])
        gateway = PlatformGateway(login_engine)

        definition = _definition(seed, now)
        definition_write = gateway.register_gis_service_definition_version(definition)
        definition_replay = gateway.register_gis_service_definition_version(definition)
        empty_projection = gateway.get_gis_service_control_projection(
            tenant, str(seed["service_urn"])
        )

        layer, style, tile_matrix, cache_policy, serving_projection, release = _release_bundle(
            seed, definition, now
        )
        layer_write = gateway.register_layer_definition_version(layer)
        layer_replay = gateway.register_layer_definition_version(layer)
        style_write = gateway.register_style_definition_version(style)
        tile_matrix_write = gateway.register_tile_matrix_set_definition_version(
            tile_matrix
        )
        invalid_projection_values = {
            **serving_projection.model_dump(mode="python", exclude={"projection_sha256"}),
            "mvt_serving_projection_version_id": uuid4(),
            "projection_key": "districts-serving-invalid-hash",
            "version_key": "v0.9.0",
            "source_content_sha256": "0" * 64,
        }
        invalid_projection = MVTServingProjectionVersion(
            **invalid_projection_values,
            projection_sha256=mvt_serving_projection_fingerprint(
                invalid_projection_values
            ),
        )
        mismatched_source_hash_rejected = False
        try:
            gateway.register_mvt_serving_projection_version(invalid_projection)
        except GatewayValidationError:
            mismatched_source_hash_rejected = True
        serving_projection_write = gateway.register_mvt_serving_projection_version(
            serving_projection
        )
        serving_projection_replay = gateway.register_mvt_serving_projection_version(
            serving_projection
        )
        cache_policy_write = gateway.register_cache_policy_version(cache_policy)
        cache_policy_replay = gateway.register_cache_policy_version(cache_policy)
        uncached_values = {
            **release.model_dump(
                mode="python",
                exclude={"binding_sha256", "cache_policy_version_id"},
            ),
            "service_release_binding_id": uuid4(),
            "release_key": "v0.9.0",
        }
        uncached_release = ServiceReleaseBinding(
            **uncached_values,
            binding_sha256=service_release_binding_fingerprint(uncached_values),
        )
        vector_tile_without_cache_rejected = False
        try:
            gateway.register_service_release_binding(uncached_release)
        except GatewayValidationError:
            vector_tile_without_cache_rejected = True
        unprojected_values = {
            **release.model_dump(
                mode="python",
                exclude={"binding_sha256", "mvt_serving_projection_version_id"},
            ),
            "service_release_binding_id": uuid4(),
            "release_key": "v0.9.1",
        }
        unprojected_release = ServiceReleaseBinding(
            **unprojected_values,
            binding_sha256=service_release_binding_fingerprint(unprojected_values),
        )
        vector_tile_without_serving_projection_rejected = False
        try:
            gateway.register_service_release_binding(unprojected_release)
        except GatewayValidationError:
            vector_tile_without_serving_projection_rejected = True
        release_write = gateway.register_service_release_binding(release)
        release_replay = gateway.register_service_release_binding(release)
        service_policy = _service_policy(seed, definition, release, now)
        service_policy_write = gateway.register_service_policy_binding(service_policy)
        service_policy_replay = gateway.register_service_policy_binding(service_policy)

        grant_now = datetime.now(UTC).replace(microsecond=0)
        binding_values = {
            "tenant_id": tenant,
            "service_consumer_binding_id": uuid4(),
            "service_urn": str(seed["service_urn"]),
            "service_definition_version_id": definition.service_definition_version_id,
            "service_release_binding_id": release.service_release_binding_id,
            "consumer_ref": "human:district-analyst",
            "action": "mvt.read",
            "purpose": "gis_mvt_read",
            "scope": {"operations": ["read"]},
            "credential_ref": "credential:district-analyst-mvt",
            "expires_at": grant_now + timedelta(hours=2),
            "compatibility_fingerprint": "a" * 64,
            "compatibility_evidence": {
                "schema": "gda.gis_service_consumer_binding_compatibility.v1",
                "service_release_binding_id": str(release.service_release_binding_id),
            },
            "created_by": "workload:service-controller",
            "created_at": grant_now,
        }
        proposed_binding = ServiceConsumerBinding(
            **binding_values,
            binding_sha256=service_consumer_binding_fingerprint(binding_values),
        )
        unapproved_grant_rejected = False
        try:
            gateway.register_service_consumer_binding(proposed_binding)
        except GatewayValidationError:
            unapproved_grant_rejected = True

        approvals = ApprovalCaseAuthority(login_engine)
        approvals.upsert_principal(
            tenant_id=tenant,
            principal_subject="human:service-owner",
            expected_directory_version=0,
            principal_type=ApprovalPrincipalType.HUMAN,
            display_name="Service Owner",
            status=ApprovalPrincipalStatus.ACTIVE,
            approval_eligible=True,
            availability_status=ApprovalAvailabilityStatus.AVAILABLE,
            valid_from=grant_now - timedelta(minutes=1),
            valid_until=None,
            actor_subject="human:service-owner",
            reason="register service binding grant approver",
        )
        grant_service = ServiceConsumerBindingGrantService(gateway, approvals)
        grant_plan = build_service_consumer_binding_grant_plan(proposed_binding)
        grant_request = grant_service.request_grant(
            grant_plan,
            requester_subject="workload:service-controller",
            request_reason="authorize district analyst MVT consumption",
            owner_ref="team:spatial-data",
            requested_at=grant_now,
            expires_at=grant_now + timedelta(minutes=30),
        )
        pending_grant_rejected = False
        try:
            grant_service.issue(
                grant_plan,
                approval_case_ref=grant_request.approval_case.approval_case_ref,
            )
        except GatewayValidationError:
            pending_grant_rejected = True
        approved_grant_case = approvals.decide(
            tenant_id=tenant,
            approval_case_ref=grant_request.approval_case.approval_case_ref,
            expected_state_version=0,
            verdict=ApprovalCaseStatus.APPROVED,
            actor_subject="human:service-owner",
            reason="reviewed exact MVT consumer binding grant",
        )
        grant_write = grant_service.issue(
            grant_plan,
            approval_case_ref=approved_grant_case.approval_case_ref,
        )
        grant_replay = grant_service.issue(
            grant_plan,
            approval_case_ref=approved_grant_case.approval_case_ref,
        )
        active_before_renewal = gateway.get_active_service_consumer_binding_for_release(
            tenant,
            proposed_binding.service_urn,
            proposed_binding.service_definition_version_id,
            proposed_binding.service_release_binding_id,
            proposed_binding.consumer_ref,
        )
        issued_binding = grant_write.value
        renewal_values = issued_binding.model_dump(
            mode="python",
            exclude={
                "binding_sha256",
                "approval_case_ref",
                "grant_plan_sha256",
                "renewal_of_binding_id",
                "renewal_approval_case_ref",
                "renewal_plan_sha256",
            },
        )
        renewal_values.update(
            {
                "service_consumer_binding_id": uuid4(),
                "credential_ref": "credential:district-analyst-mvt-v2",
                "expires_at": grant_now + timedelta(hours=6),
                "created_at": grant_now + timedelta(seconds=1),
            }
        )
        renewal_values["binding_sha256"] = service_consumer_binding_fingerprint(
            renewal_values
        )
        renewal_target = ServiceConsumerBinding.model_validate(renewal_values)
        renewal_plan = build_service_consumer_binding_renewal_plan(
            issued_binding,
            renewal_target,
            renewal_id=uuid4(),
        )
        renewal_service = ServiceConsumerBindingRenewalService(gateway, approvals)
        renewal_request = renewal_service.request_renewal(
            renewal_plan,
            requester_subject="workload:service-controller",
            request_reason="extend the exact MVT consumer binding",
            owner_ref="team:spatial-data",
            requested_at=grant_now,
            expires_at=grant_now + timedelta(minutes=30),
        )
        pending_renewal_rejected = False
        try:
            renewal_service.renew(
                renewal_plan,
                approval_case_ref=renewal_request.approval_case.approval_case_ref,
            )
        except GatewayValidationError:
            pending_renewal_rejected = True
        approved_renewal_case = approvals.decide(
            tenant_id=tenant,
            approval_case_ref=renewal_request.approval_case.approval_case_ref,
            expected_state_version=0,
            verdict=ApprovalCaseStatus.APPROVED,
            actor_subject="human:service-owner",
            reason="reviewed exact MVT consumer binding renewal",
        )
        renewal_write = renewal_service.renew(
            renewal_plan,
            approval_case_ref=approved_renewal_case.approval_case_ref,
        )
        renewal_replay = renewal_service.renew(
            renewal_plan,
            approval_case_ref=approved_renewal_case.approval_case_ref,
        )
        tampered_renewal = ServiceConsumerBindingRenewal(
            tenant_id=tenant,
            service_consumer_binding_renewal_id=(
                renewal_plan.service_consumer_binding_renewal_id
            ),
            source_binding_id=renewal_plan.source_binding_id,
            source_binding_sha256=renewal_plan.source_binding_sha256,
            target_binding_id=renewal_plan.service_consumer_binding.service_consumer_binding_id,
            target_binding_sha256=renewal_plan.service_consumer_binding.binding_sha256,
            approval_case_ref=approved_renewal_case.approval_case_ref,
            renewal_plan_sha256=renewal_plan.plan_sha256,
            renewed_by="human:another-reviewer",
            renewed_at=approved_renewal_case.decided_at,
        )
        renewal_decision_identity_rejected = False
        try:
            gateway.register_service_consumer_binding_renewal(
                renewal_write.binding.value,
                tampered_renewal,
            )
        except GatewayValidationError:
            renewal_decision_identity_rejected = True
        active_after_renewal = gateway.get_active_service_consumer_binding_for_release(
            tenant,
            proposed_binding.service_urn,
            proposed_binding.service_definition_version_id,
            proposed_binding.service_release_binding_id,
            proposed_binding.consumer_ref,
        )
        active_before_revoke = active_after_renewal
        revoke_plan = build_service_consumer_binding_revoke_plan(
            renewal_target,
            reason="credential owner requested immediate removal",
            context={"ticket": "SEC-214", "source": "gis-service-certifier"},
            revocation_id=uuid4(),
        )
        revoke_service = ServiceConsumerBindingRevocationService(gateway, approvals)
        revoke_request = revoke_service.request_revoke(
            revoke_plan,
            requester_subject="workload:service-controller",
            request_reason="remove the exact MVT consumer binding",
            owner_ref="team:spatial-data",
            requested_at=grant_now,
            expires_at=grant_now + timedelta(minutes=30),
        )
        pending_revoke_rejected = False
        try:
            revoke_service.revoke(
                revoke_plan,
                approval_case_ref=revoke_request.approval_case.approval_case_ref,
            )
        except GatewayValidationError:
            pending_revoke_rejected = True
        approved_revoke_case = approvals.decide(
            tenant_id=tenant,
            approval_case_ref=revoke_request.approval_case.approval_case_ref,
            expected_state_version=0,
            verdict=ApprovalCaseStatus.APPROVED,
            actor_subject="human:service-owner",
            reason="confirmed immediate consumer binding removal",
        )
        revoke_write = revoke_service.revoke(
            revoke_plan,
            approval_case_ref=approved_revoke_case.approval_case_ref,
        )
        revoke_replay = revoke_service.revoke(
            revoke_plan,
            approval_case_ref=approved_revoke_case.approval_case_ref,
        )
        tampered_revoke_values = revoke_write.revocation.value.model_dump(mode="python")
        tampered_revoke_values["reason"] = "different reason after approval"
        tampered_revoke = ServiceConsumerBindingRevocation(**tampered_revoke_values)
        revoke_payload_mismatch_rejected = False
        try:
            gateway.register_service_consumer_binding_revocation(tampered_revoke)
        except GatewayValidationError:
            revoke_payload_mismatch_rejected = True
        active_after_revoke = gateway.get_active_service_consumer_binding_for_release(
            tenant,
            proposed_binding.service_urn,
            proposed_binding.service_definition_version_id,
            proposed_binding.service_release_binding_id,
            proposed_binding.consumer_ref,
        )
        tampered_values = proposed_binding.model_dump(
            mode="python",
            exclude={"binding_sha256", "compatibility_evidence"},
        )
        tampered_values["compatibility_evidence"] = {
            "schema": "gda.gis_service_consumer_binding_compatibility.v1",
            "service_release_binding_id": str(release.service_release_binding_id),
            "tampered": True,
        }
        tampered_values["approval_case_ref"] = approved_grant_case.approval_case_ref
        tampered_values["grant_plan_sha256"] = grant_plan.plan_sha256
        tampered_binding = ServiceConsumerBinding(
            **tampered_values,
            binding_sha256=service_consumer_binding_fingerprint(tampered_values),
        )
        approval_payload_mismatch_rejected = False
        try:
            gateway.register_service_consumer_binding(tampered_binding)
        except GatewayValidationError:
            approval_payload_mismatch_rejected = True

        other_layer, other_style, _, _, _, _ = _release_bundle(
            seed,
            definition,
            now,
            layer_key="districts-alt",
        )
        gateway.register_layer_definition_version(other_layer)
        gateway.register_style_definition_version(other_style)
        mixed_values = {
            **release.model_dump(mode="python", exclude={"binding_sha256"}),
            "service_release_binding_id": uuid4(),
            "style_definition_version_id": other_style.style_definition_version_id,
            "release_key": "v1.1.0",
        }
        mixed_release = ServiceReleaseBinding(
            **mixed_values,
            binding_sha256=service_release_binding_fingerprint(mixed_values),
        )
        mixed_layer_style_rejected = False
        try:
            gateway.register_service_release_binding(mixed_release)
        except GatewayValidationError:
            mixed_layer_style_rejected = True

        deployment = _deployment(seed, definition, release, now)
        legacy_deployment_values = {
            **deployment.model_dump(
                mode="python",
                exclude={"deployment_sha256", "service_release_binding_id"},
            ),
            "deployment_revision_id": uuid4(),
            "service_release_binding_id": None,
            "revision_key": "r2",
            "provider_revision_ref": "deployment:legacy",
        }
        deployment_without_release = ServiceDeploymentRevision(
            **legacy_deployment_values,
            deployment_sha256=service_deployment_fingerprint(
                legacy_deployment_values
            ),
        )
        deployment_without_release_rejected = False
        try:
            gateway.register_service_deployment_revision(
                deployment_without_release
            )
        except GatewayValidationError:
            deployment_without_release_rejected = True
        deployment_write = gateway.register_service_deployment_revision(deployment)
        deployment_replay = gateway.register_service_deployment_revision(deployment)
        canary_deployment = _deployment(
            seed,
            definition,
            release,
            now,
            revision_key="r2",
            provider_deployment_id="district-features-canary",
            provider_revision_ref="deployment:18",
            config_sha256="c" * 64,
        )
        canary_deployment_write = gateway.register_service_deployment_revision(
            canary_deployment
        )
        early_endpoint = _endpoint(
            seed,
            deployment,
            serving_projection,
            now + timedelta(seconds=8),
            suffix="early",
        )
        endpoint_before_ready_rejected = False
        try:
            gateway.register_endpoint_revision(early_endpoint)
        except GatewayValidationError:
            endpoint_before_ready_rejected = True

        gateway.transition_run(
            tenant,
            UUID(str(seed["run_id"])),
            0,
            "dispatching",
            "workload:service-controller",
            "provider dispatch accepted",
        )
        deploying = gateway.transition_service_deployment_revision(
            tenant,
            deployment.deployment_revision_id,
            expected_state_version=0,
            to_state="deploying",
            provider_observation_id=None,
            actor_subject="workload:service-controller",
            reason="provider deployment started",
            idempotency_key="deploying-r1",
            occurred_at=now + timedelta(seconds=5),
        )
        canary_deploying = gateway.transition_service_deployment_revision(
            tenant,
            canary_deployment.deployment_revision_id,
            expected_state_version=0,
            to_state="deploying",
            provider_observation_id=None,
            actor_subject="workload:service-controller",
            reason="canary provider deployment started",
            idempotency_key="deploying-r2",
            occurred_at=now + timedelta(seconds=5),
        )
        gateway.transition_run(
            tenant,
            UUID(str(seed["run_id"])),
            1,
            "running",
            "workload:service-controller",
            "provider deployment running",
        )

        run_id = UUID(str(seed["run_id"]))
        orchestration_evidence = {
            "schema": "gda.dolphinscheduler_observation.v1",
            "provider_state": "SUCCESS",
        }
        orchestration_observation = FrameworkAttemptObservation(
            tenant_id=tenant,
            observation_id=uuid4(),
            run_id=run_id,
            attempt_no=1,
            framework_kind="dolphinscheduler",
            external_namespace="planning-service-deploy",
            external_run_id="process-instance-17",
            external_attempt_id="task-instance-23",
            observed_state="success",
            observation_sha256=canonical_json_fingerprint(
                orchestration_evidence
            ),
            evidence=orchestration_evidence,
            observed_at=now + timedelta(seconds=6),
        )
        gateway.record_attempt(orchestration_observation)
        output_artifact = Artifact(
            tenant_id=tenant,
            artifact_id=uuid4(),
            artifact_key="district-service-projection",
            artifact_role="output",
            storage_uri="s3://gis-service-cert/district-service-projection.parquet",
            media_type="application/vnd.apache.parquet",
            content_sha256="2" * 64,
            size_bytes=1024,
            run_id=run_id,
            resource_version_id=UUID(str(seed["output_id"])),
            manifest={"row_count": 3},
            created_by="workload:service-controller",
            created_at=now + timedelta(seconds=6),
        )
        quality_evidence_artifact = Artifact(
            tenant_id=tenant,
            artifact_id=uuid4(),
            artifact_key="district-service-quality",
            artifact_role="evidence",
            storage_uri="s3://gis-service-cert/district-service-quality.json",
            media_type="application/json",
            content_sha256="7" * 64,
            size_bytes=128,
            run_id=run_id,
            resource_version_id=UUID(str(seed["output_id"])),
            manifest={"checks": ["schema", "crs", "row_count"]},
            created_by="workload:quality-controller",
            created_at=now + timedelta(seconds=6),
        )
        gateway.record_artifact(output_artifact)
        gateway.record_artifact(quality_evidence_artifact)
        quality_values = {
            "tenant_id": tenant,
            "quality_result_id": uuid4(),
            "run_id": run_id,
            "resource_version_id": UUID(str(seed["output_id"])),
            "rule_version_ref": "gis-service-release:v1",
            "verdict": "passed",
            "metrics": {"invalid_geometry_count": 0, "crs_match": True},
            "evidence_artifact_id": quality_evidence_artifact.artifact_id,
            "evaluated_by": "workload:quality-controller",
            "evaluated_at": now + timedelta(seconds=7),
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
            tenant_id=tenant,
            lineage_event_id=uuid4(),
            event_type="publish",
            source_resource_version_id=UUID(str(seed["source_id"])),
            target_resource_version_id=UUID(str(seed["output_id"])),
            producer="workload:service-controller",
            event_sha256=canonical_json_fingerprint(lineage_facets),
            run_id=run_id,
            definition_version_id=UUID(str(seed["platform_definition_id"])),
            artifact_id=output_artifact.artifact_id,
            facets=lineage_facets,
            occurred_at=now + timedelta(seconds=7),
        )
        gateway.record_lineage(lineage)
        success_values = {
            "tenant_id": tenant,
            "run_id": run_id,
            "attempt_observation_id": orchestration_observation.observation_id,
            "output_artifact_id": output_artifact.artifact_id,
            "quality_result_id": quality.quality_result_id,
            "lineage_event_id": lineage.lineage_event_id,
        }
        success_evidence = RunSuccessEvidence(
            **success_values,
            evidence_sha256=run_success_evidence_fingerprint(**success_values),
        )
        succeeded_run = gateway.finalize_run_success(
            success_evidence,
            expected_state_version=2,
            actor_subject="workload:service-controller",
            reason="certified provider success",
        )

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
            "provider_version": "1.0.0",
            "provider_namespace": deployment.provider_namespace,
            "provider_deployment_id": deployment.provider_deployment_id,
            "provider_revision_ref": deployment.provider_revision_ref,
            "config_sha256": deployment.config_sha256,
            "endpoint_uri": "https://geo.example.test/tiles/district-features",
            "health_evidence_sha256": "9" * 64,
            "provider_receipt": {
                "catalog": "verified",
                "health_status": 200,
            },
        }
        observation = FrameworkAttemptObservation(
            tenant_id=tenant,
            observation_id=uuid4(),
            run_id=run_id,
            attempt_no=2,
            framework_kind="cloud",
            external_namespace=deployment.provider_namespace,
            external_run_id=deployment.provider_deployment_id,
            external_attempt_id=deployment.provider_revision_ref,
            observed_state="ready",
            observation_sha256=canonical_json_fingerprint(observation_evidence),
            evidence=observation_evidence,
            observed_at=now + timedelta(seconds=8),
        )
        generic_deployment_observation_rejected = False
        try:
            gateway.record_attempt(observation)
        except GatewayForbiddenError:
            generic_deployment_observation_rejected = True

        legacy_observation_evidence = {
            "schema": "gda.gis_service_deployment_observation.v1",
            "deployment_revision_id": str(deployment.deployment_revision_id),
            "provider_deployment_id": deployment.provider_deployment_id,
            "provider_revision_ref": deployment.provider_revision_ref,
        }
        legacy_observation = FrameworkAttemptObservation(
            tenant_id=tenant,
            observation_id=uuid4(),
            run_id=run_id,
            attempt_no=2,
            framework_kind="cloud",
            external_namespace=deployment.provider_namespace,
            external_run_id=deployment.provider_deployment_id,
            external_attempt_id=deployment.provider_revision_ref,
            observed_state="ready",
            observation_sha256=canonical_json_fingerprint(legacy_observation_evidence),
            evidence=legacy_observation_evidence,
            observed_at=now + timedelta(seconds=8),
        )
        gateway.record_attempt(legacy_observation)
        legacy_observation_rejected_for_ready = False
        try:
            gateway.transition_service_deployment_revision(
                tenant,
                deployment.deployment_revision_id,
                expected_state_version=1,
                to_state="ready",
                provider_observation_id=legacy_observation.observation_id,
                actor_subject="workload:service-controller",
                reason="legacy provider evidence must not activate deployment",
                idempotency_key="ready-legacy-observation",
                occurred_at=now + timedelta(seconds=9),
            )
        except GatewayValidationError:
            legacy_observation_rejected_for_ready = True

        failed_observation_evidence = {
            **observation_evidence,
            "health_evidence_sha256": "8" * 64,
            "provider_receipt": {"health_status": 503, "failure": "unavailable"},
        }
        failed_observation = FrameworkAttemptObservation(
            tenant_id=tenant,
            observation_id=uuid4(),
            run_id=run_id,
            attempt_no=3,
            framework_kind="cloud",
            external_namespace=deployment.provider_namespace,
            external_run_id=deployment.provider_deployment_id,
            external_attempt_id=deployment.provider_revision_ref,
            observed_state="failed",
            observation_sha256=canonical_json_fingerprint(failed_observation_evidence),
            evidence=failed_observation_evidence,
            observed_at=now + timedelta(seconds=8),
        )
        failed_settlement_rolled_back = False
        try:
            gateway.settle_gis_service_deployment_terminal(
                deployment.deployment_revision_id,
                failed_observation,
                expected_state_version=1,
                actor_subject="workload:service-controller",
                reason="provider reported failed after a succeeded Run",
                idempotency_key="failed-after-success",
                occurred_at=now + timedelta(seconds=9),
            )
        except GatewayValidationError:
            try:
                gateway.get_attempt_observation(tenant, failed_observation.observation_id)
            except GatewayNotFoundError:
                failed_settlement_rolled_back = True

        deployment_settlement_write = gateway.settle_gis_service_deployment_terminal(
            deployment.deployment_revision_id,
            observation,
            expected_state_version=1,
            actor_subject="workload:service-controller",
            reason="provider revision reconciled ready",
            idempotency_key="ready-r1",
            occurred_at=now + timedelta(seconds=9),
        )
        deployment_settlement_replay = gateway.settle_gis_service_deployment_terminal(
            deployment.deployment_revision_id,
            observation,
            expected_state_version=1,
            actor_subject="workload:service-controller",
            reason="provider revision reconciled ready",
            idempotency_key="ready-r1",
            occurred_at=now + timedelta(seconds=9),
        )
        ready = deployment_settlement_write.deployment
        ready_replay = deployment_settlement_replay.deployment

        canary_observation_evidence = {
            **observation_evidence,
            "deployment_revision_id": str(canary_deployment.deployment_revision_id),
            "provider_deployment_id": canary_deployment.provider_deployment_id,
            "provider_revision_ref": canary_deployment.provider_revision_ref,
            "config_sha256": canary_deployment.config_sha256,
            "endpoint_uri": "https://geo.example.test/tiles/district-features-canary",
            "health_evidence_sha256": "a" * 64,
            "provider_receipt": {"catalog": "verified", "health_status": 200},
        }
        canary_observation = FrameworkAttemptObservation(
            tenant_id=tenant,
            observation_id=uuid4(),
            run_id=run_id,
            attempt_no=4,
            framework_kind="cloud",
            external_namespace=canary_deployment.provider_namespace,
            external_run_id=canary_deployment.provider_deployment_id,
            external_attempt_id=canary_deployment.provider_revision_ref,
            observed_state="ready",
            observation_sha256=canonical_json_fingerprint(canary_observation_evidence),
            evidence=canary_observation_evidence,
            observed_at=now + timedelta(seconds=9),
        )
        canary_settlement = gateway.settle_gis_service_deployment_terminal(
            canary_deployment.deployment_revision_id,
            canary_observation,
            expected_state_version=1,
            actor_subject="workload:service-controller",
            reason="canary provider revision reconciled ready",
            idempotency_key="ready-r2",
            occurred_at=now + timedelta(seconds=10),
        )
        canary_ready = canary_settlement.deployment

        endpoint_uri_mismatch_rejected = False
        try:
            gateway.register_endpoint_revision(
                _endpoint(
                    seed,
                    ready,
                    serving_projection,
                    now + timedelta(seconds=10),
                    suffix="unverified",
                )
            )
        except GatewayValidationError:
            endpoint_uri_mismatch_rejected = True
        endpoint_one = _endpoint(
            seed,
            ready,
            serving_projection,
            now + timedelta(seconds=10),
            suffix="r1",
            endpoint_uri=observation_evidence["endpoint_uri"],
        )
        endpoint_two = _endpoint(
            seed,
            canary_ready,
            serving_projection,
            now + timedelta(seconds=11),
            suffix="r1-canary",
            endpoint_uri=canary_observation_evidence["endpoint_uri"],
        )
        endpoint_one_write = gateway.register_endpoint_revision(endpoint_one)
        endpoint_two_write = gateway.register_endpoint_revision(endpoint_two)
        active_one = gateway.activate_gis_service_endpoint(
            tenant,
            str(seed["service_urn"]),
            endpoint_one.endpoint_revision_id,
            expected_state_version=0,
            actor_subject="workload:service-controller",
            reason="activate certified endpoint",
            idempotency_key="activate-r1",
            occurred_at=now + timedelta(seconds=12),
        )
        stale_cas_rejected = False
        try:
            gateway.activate_gis_service_endpoint(
                tenant,
                str(seed["service_urn"]),
                endpoint_two.endpoint_revision_id,
                expected_state_version=0,
                actor_subject="workload:service-controller",
                reason="stale canary activation",
                idempotency_key="activate-canary-stale",
                occurred_at=now + timedelta(seconds=13),
            )
        except GatewayConflictError:
            stale_cas_rejected = True
        active_two = gateway.activate_gis_service_endpoint(
            tenant,
            str(seed["service_urn"]),
            endpoint_two.endpoint_revision_id,
            expected_state_version=1,
            actor_subject="workload:service-controller",
            reason="promote canary endpoint",
            idempotency_key="activate-canary",
            occurred_at=now + timedelta(seconds=14),
        )
        rolled_back = gateway.activate_gis_service_endpoint(
            tenant,
            str(seed["service_urn"]),
            endpoint_one.endpoint_revision_id,
            expected_state_version=2,
            actor_subject="workload:service-controller",
            reason="rollback to prior endpoint revision",
            idempotency_key="rollback-r1",
            occurred_at=now + timedelta(seconds=15),
        )

        successor_product_version_id = uuid4()
        with engine.begin() as connection:
            connection.execute(
                text(
                    """
                    INSERT INTO gda_control.data_product_version (
                        tenant_id, data_product_version_id, product_urn,
                        version_key, predecessor_version_id,
                        source_resource_version_id, output_resource_version_id,
                        standard_version_ref, mapping_contract, quality_contract,
                        quality_verdict, quality_evidence_artifact_id,
                        distribution_manifest, manifest_sha256,
                        published_by, published_at
                    ) VALUES (
                        :tenant, :version_id, :product_urn, 'v1.1.0',
                        :predecessor_id, :source_id, :output_id,
                        'standard:district-v1',
                        '{"mapping":{"district_id":"district_id"}}'::jsonb,
                        '{"verdict":"passed"}'::jsonb, 'passed', :artifact_id,
                        '{"formats":["geoparquet"]}'::jsonb, :manifest_sha,
                        'workload:product-publisher', :published_at
                    )
                    """
                ),
                {
                    "tenant": tenant,
                    "version_id": successor_product_version_id,
                    "product_urn": seed["product_urn"],
                    "predecessor_id": seed["product_version_id"],
                    "source_id": seed["source_id"],
                    "output_id": seed["output_id"],
                    "artifact_id": seed["quality_artifact_id"],
                    "manifest_sha": "9" * 64,
                    "published_at": now + timedelta(seconds=16),
                },
            )
            connection.execute(
                text(
                    """
                    UPDATE gda_control.data_product
                       SET current_version_id = :version_id,
                           updated_at = :updated_at
                     WHERE tenant_id = :tenant AND product_urn = :product_urn
                    """
                ),
                {
                    "version_id": successor_product_version_id,
                    "updated_at": now + timedelta(seconds=16),
                    "tenant": tenant,
                    "product_urn": seed["product_urn"],
                },
            )
            connection.execute(
                text(
                    """
                    INSERT INTO gda_control.data_product_event (
                        tenant_id, event_id, product_urn, event_type,
                        from_version_id, to_version_id, actor_subject,
                        reason, idempotency_key, occurred_at
                    ) VALUES (
                        :tenant, :event_id, :product_urn, 'advanced',
                        :from_version_id, :to_version_id,
                        'workload:product-publisher',
                        'advance source product', 'advance-v1.1', :occurred_at
                    )
                    """
                ),
                {
                    "tenant": tenant,
                    "event_id": uuid4(),
                    "product_urn": seed["product_urn"],
                    "from_version_id": seed["product_version_id"],
                    "to_version_id": successor_product_version_id,
                    "occurred_at": now + timedelta(seconds=16),
                },
            )
        stale_source_values = {
            **definition.model_dump(
                mode="python",
                exclude={"definition_sha256"},
            ),
            "service_definition_version_id": uuid4(),
            "version_key": "v1.1.0",
            "predecessor_version_id": definition.service_definition_version_id,
            "created_at": now + timedelta(seconds=17),
        }
        stale_source_definition = GISServiceDefinitionVersion(
            **stale_source_values,
            definition_sha256=gis_service_definition_fingerprint(
                stale_source_values
            ),
        )
        inactive_product_source_rejected = False
        try:
            gateway.register_gis_service_definition_version(
                stale_source_definition
            )
        except GatewayValidationError:
            inactive_product_source_rejected = True

        direct_release_insert_sqlstate = None
        direct_endpoint_insert_sqlstate = None
        direct_pointer_update_sqlstate = None
        with login_engine.connect() as connection:
            with connection.begin():
                connection.exec_driver_sql('SET LOCAL ROLE "gda_control_gateway"')
                connection.execute(
                    text("SELECT set_config('app.current_tenant', :tenant, true)"),
                    {"tenant": tenant},
                )
                try:
                    with connection.begin_nested():
                        connection.execute(
                            text(
                                """
                                INSERT INTO gda_control.service_release_binding (
                                    tenant_id, service_release_binding_id,
                                    service_definition_version_id,
                                    layer_definition_version_id,
                                    style_definition_version_id,
                                    tile_matrix_set_definition_version_id,
                                    release_key, binding_sha256,
                                    created_by, created_at
                                ) VALUES (
                                    :tenant, :release_id, :definition_id,
                                    :layer_id, :style_id, :tile_matrix_id,
                                    'v9.9.9', :sha, 'workload:attacker', :created_at
                                )
                                """
                            ),
                            {
                                "tenant": tenant,
                                "release_id": uuid4(),
                                "definition_id": (
                                    definition.service_definition_version_id
                                ),
                                "layer_id": layer.layer_definition_version_id,
                                "style_id": style.style_definition_version_id,
                                "tile_matrix_id": (
                                    tile_matrix.tile_matrix_set_definition_version_id
                                ),
                                "sha": "8" * 64,
                                "created_at": now + timedelta(seconds=18),
                            },
                        )
                except DBAPIError as exc:
                    direct_release_insert_sqlstate = _sqlstate(exc)
                try:
                    with connection.begin_nested():
                        connection.execute(
                            text(
                                """
                                INSERT INTO gda_control.endpoint_revision (
                                    tenant_id, endpoint_revision_id, service_urn,
                                    deployment_revision_id, endpoint_protocol,
                                    endpoint_uri, endpoint_contract,
                                    endpoint_sha256, created_by, created_at
                                ) VALUES (
                                    :tenant, :endpoint_id, :service_urn,
                                    :deployment_id, 'ogc_api_features',
                                    'https://attacker.example.test/endpoint',
                                    '{}'::jsonb, :sha,
                                    'workload:attacker', :created_at
                                )
                                """
                            ),
                            {
                                "tenant": tenant,
                                "endpoint_id": uuid4(),
                                "service_urn": seed["service_urn"],
                                "deployment_id": deployment.deployment_revision_id,
                                "sha": "8" * 64,
                                "created_at": now + timedelta(seconds=18),
                            },
                        )
                except DBAPIError as exc:
                    direct_endpoint_insert_sqlstate = _sqlstate(exc)
                try:
                    with connection.begin_nested():
                        connection.execute(
                            text(
                                """
                                UPDATE gda_control.gis_service
                                   SET active_endpoint_revision_id = :endpoint_id,
                                       endpoint_state_version = 99,
                                       updated_at = :updated_at
                                 WHERE tenant_id = :tenant
                                   AND service_urn = :service_urn
                                """
                            ),
                            {
                                "endpoint_id": endpoint_two.endpoint_revision_id,
                                "updated_at": now + timedelta(seconds=18),
                                "tenant": tenant,
                                "service_urn": seed["service_urn"],
                            },
                        )
                except DBAPIError as exc:
                    direct_pointer_update_sqlstate = _sqlstate(exc)

        immutable_endpoint_sqlstate = None
        with engine.connect() as connection:
            with connection.begin():
                try:
                    with connection.begin_nested():
                        connection.execute(
                            text(
                                """
                                UPDATE gda_control.endpoint_revision
                                   SET endpoint_uri = 'https://tampered.example.test'
                                 WHERE tenant_id = :tenant
                                   AND endpoint_revision_id = :endpoint_id
                                """
                            ),
                            {
                                "tenant": tenant,
                                "endpoint_id": endpoint_one.endpoint_revision_id,
                            },
                        )
                except DBAPIError as exc:
                    immutable_endpoint_sqlstate = _sqlstate(exc)

        with login_engine.begin() as connection:
            connection.exec_driver_sql('SET LOCAL ROLE "gda_control_gateway"')
            connection.execute(
                text("SELECT set_config('app.current_tenant', 'other', true)")
            )
            cross_tenant_rows = connection.execute(
                text("SELECT count(*) FROM gda_control.gis_service")
            ).scalar_one()

        catalog = discover_migrations()
        with engine.begin() as connection:
            rls_enforced = connection.execute(
                text(
                    """
                    SELECT bool_and(relrowsecurity AND relforcerowsecurity)
                      FROM pg_class
                     WHERE oid IN (
                        'gda_control.gis_service'::regclass,
                        'gda_control.gis_service_definition_version'::regclass,
                        'gda_control.service_deployment_revision'::regclass,
                        'gda_control.service_deployment_event'::regclass,
                        'gda_control.endpoint_revision'::regclass,
                        'gda_control.gis_service_endpoint_activation_event'::regclass,
                        'gda_control.layer_definition_version'::regclass,
                        'gda_control.style_definition_version'::regclass,
                        'gda_control.tile_matrix_set_definition_version'::regclass,
                        'gda_control.cache_policy_version'::regclass,
                        'gda_control.service_policy_binding'::regclass,
                        'gda_control.mvt_serving_projection_version'::regclass,
                        'gda_control.service_release_binding'::regclass,
                        'gda_control.service_consumer_binding'::regclass
                     )
                    """
                )
            ).scalar_one()
            gateway_privileges = connection.execute(
                text(
                    """
                    SELECT
                        has_table_privilege(
                            'gda_control_gateway',
                            'gda_control.endpoint_revision', 'SELECT'
                        ),
                        has_table_privilege(
                            'gda_control_gateway',
                            'gda_control.endpoint_revision', 'INSERT'
                        ),
                        has_table_privilege(
                            'gda_control_gateway',
                            'gda_control.gis_service', 'UPDATE'
                        ),
                        has_function_privilege(
                            'gda_control_gateway',
                            'gda_control.activate_gis_service_endpoint(text,text,uuid,integer,text,text,text,timestamptz)',
                            'EXECUTE'
                        ),
                        has_table_privilege(
                            'gda_control_gateway',
                            'gda_control.cache_policy_version', 'SELECT'
                        ),
                        has_table_privilege(
                            'gda_control_gateway',
                            'gda_control.cache_policy_version', 'INSERT'
                        ),
                        has_function_privilege(
                            'gda_control_gateway',
                            'gda_control.record_cache_policy_version(text,uuid,uuid,text,text,uuid,text,integer,text[],text,text,timestamptz)',
                            'EXECUTE'
                        ),
                        has_table_privilege(
                            'gda_control_gateway',
                            'gda_control.service_policy_binding', 'SELECT'
                        ),
                        has_table_privilege(
                            'gda_control_gateway',
                            'gda_control.service_policy_binding', 'INSERT'
                        ),
                        has_function_privilege(
                            'gda_control_gateway',
                            'gda_control.record_service_policy_binding(text,uuid,uuid,uuid,text,text,uuid,text,text,text[],text[],text,text,text,timestamptz)',
                            'EXECUTE'
                        ),
                        has_table_privilege(
                            'gda_control_gateway',
                            'gda_control.service_release_binding', 'SELECT'
                        ),
                        has_table_privilege(
                            'gda_control_gateway',
                            'gda_control.service_release_binding', 'INSERT'
                        ),
                        has_function_privilege(
                            'gda_control_gateway',
                            'gda_control.record_service_release_binding(text,uuid,uuid,uuid,uuid,uuid,uuid,uuid,text,text,text,timestamptz)',
                            'EXECUTE'
                        ),
                        has_table_privilege(
                            'gda_control_gateway',
                            'gda_control.mvt_serving_projection_version', 'SELECT'
                        ),
                        has_table_privilege(
                            'gda_control_gateway',
                            'gda_control.mvt_serving_projection_version', 'INSERT'
                        ),
                        has_function_privilege(
                            'gda_control_gateway',
                            'gda_control.record_mvt_serving_projection_version('
                            'text,uuid,uuid,uuid,text,text,uuid,uuid,text,text,'
                            'text,integer,text,text[],double precision[],integer,'
                            'text,text,text,timestamptz)',
                            'EXECUTE'
                        ),
                        has_function_privilege(
                            'gda_control_gateway',
                            'gda_control.record_service_deployment_revision(text,uuid,uuid,uuid,text,text,text,text,text,text,text,text,timestamptz)',
                            'EXECUTE'
                        ),
                        has_function_privilege(
                            'gda_control_gateway',
                            'gda_control.record_service_deployment_revision(text,uuid,uuid,uuid,uuid,text,text,text,text,text,text,text,text,timestamptz)',
                            'EXECUTE'
                        )
                    """
                )
            ).one()
            gateway_control_projection_privileges = connection.execute(
                text(
                    """
                    SELECT
                        has_table_privilege(
                            'gda_control_gateway',
                            'gda_control.gis_service', 'SELECT'
                        ),
                        has_table_privilege(
                            'gda_control_gateway',
                            'gda_control.gis_service_definition_version', 'SELECT'
                        ),
                        has_table_privilege(
                            'gda_control_gateway',
                            'gda_control.layer_definition_version', 'SELECT'
                        ),
                        has_table_privilege(
                            'gda_control_gateway',
                            'gda_control.style_definition_version', 'SELECT'
                        ),
                        has_table_privilege(
                            'gda_control_gateway',
                            'gda_control.tile_matrix_set_definition_version', 'SELECT'
                        ),
                        has_table_privilege(
                            'gda_control_gateway',
                            'gda_control.cache_policy_version', 'SELECT'
                        ),
                        has_table_privilege(
                            'gda_control_gateway',
                            'gda_control.service_policy_binding', 'SELECT'
                        ),
                        has_table_privilege(
                            'gda_control_gateway',
                            'gda_control.mvt_serving_projection_version', 'SELECT'
                        ),
                        has_table_privilege(
                            'gda_control_gateway',
                            'gda_control.service_release_binding', 'SELECT'
                        ),
                        has_table_privilege(
                            'gda_control_gateway',
                            'gda_control.service_deployment_revision', 'SELECT'
                        ),
                        has_table_privilege(
                            'gda_control_gateway',
                            'gda_control.service_deployment_event', 'SELECT'
                        ),
                        has_table_privilege(
                            'gda_control_gateway',
                            'gda_control.endpoint_revision', 'SELECT'
                        ),
                        has_table_privilege(
                            'gda_control_gateway',
                            'gda_control.gis_service_endpoint_activation_event', 'SELECT'
                        ),
                        has_table_privilege(
                            'gda_control_gateway',
                            'gda_control.framework_attempt_observation', 'SELECT'
                        ),
                        has_table_privilege(
                            'gda_control_gateway',
                            'gda_control.framework_attempt_observation', 'INSERT'
                        )
                    """
                )
            ).one()
            service_consumer_binding_privileges = connection.execute(
                text(
                    """
                    SELECT
                        has_table_privilege(
                            'gda_control_gateway',
                            'gda_control.service_consumer_binding', 'SELECT'
                        ),
                        has_table_privilege(
                            'gda_control_gateway',
                            'gda_control.service_consumer_binding', 'INSERT'
                        ),
                        has_function_privilege(
                            'gda_control_gateway',
                            'gda_control.record_service_consumer_binding('
                            'text,uuid,text,uuid,uuid,text,text,text,jsonb,text,'
                            'timestamptz,char(64),jsonb,char(64),text,timestamptz)',
                            'EXECUTE'
                        ),
                        has_function_privilege(
                            'gda_control_gateway',
                            'gda_control.record_service_consumer_binding('
                            'text,uuid,text,char(64),text,uuid,uuid,text,text,text,'
                            'jsonb,text,timestamptz,char(64),jsonb,char(64),'
                            'text,timestamptz)',
                            'EXECUTE'
                        )
                    """
                )
                ).one()
            service_consumer_binding_revocation_privileges = connection.execute(
                text(
                    """
                    SELECT
                        has_table_privilege(
                            'gda_control_gateway',
                            'gda_control.service_consumer_binding_revocation', 'SELECT'
                        ),
                        has_table_privilege(
                            'gda_control_gateway',
                            'gda_control.service_consumer_binding_revocation', 'INSERT'
                        ),
                        has_function_privilege(
                            'gda_control_gateway',
                            'gda_control.record_service_consumer_binding_revocation('
                            'text,uuid,uuid,char(64),text,char(64),text,text,timestamptz)',
                            'EXECUTE'
                        )
                    """
                )
            ).one()
            service_consumer_binding_renewal_privileges = connection.execute(
                text(
                    """
                    SELECT
                        has_table_privilege(
                            'gda_control_gateway',
                            'gda_control.service_consumer_binding_renewal', 'SELECT'
                        ),
                        has_table_privilege(
                            'gda_control_gateway',
                            'gda_control.service_consumer_binding_renewal', 'INSERT'
                        ),
                        has_function_privilege(
                            'gda_control_gateway',
                            'gda_control.record_service_consumer_binding_renewal('
                            'text,uuid,uuid,char(64),uuid,text,uuid,uuid,text,text, text,'
                            'jsonb,text,timestamptz,char(64),jsonb,char(64),text,timestamptz,'
                            'text,char(64),text,timestamptz)',
                            'EXECUTE'
                        )
                    """
                )
            ).one()
            counts = connection.execute(
                text(
                    """
                    SELECT
                        (SELECT count(*) FROM gda_control.gis_service_definition_version),
                        (SELECT count(*) FROM gda_control.layer_definition_version),
                        (SELECT count(*) FROM gda_control.style_definition_version),
                        (SELECT count(*) FROM gda_control.tile_matrix_set_definition_version),
                        (SELECT count(*) FROM gda_control.cache_policy_version),
                        (SELECT count(*) FROM gda_control.service_policy_binding),
                        (SELECT count(*) FROM gda_control.mvt_serving_projection_version),
                        (SELECT count(*) FROM gda_control.service_release_binding),
                        (SELECT count(*) FROM gda_control.service_deployment_revision),
                        (SELECT count(*) FROM gda_control.service_deployment_event),
                        (SELECT count(*) FROM gda_control.endpoint_revision),
                        (SELECT count(*) FROM gda_control.gis_service_endpoint_activation_event),
                        (SELECT count(*) FROM gda_control.service_consumer_binding),
                        (SELECT count(*) FROM gda_control.service_consumer_binding_revocation),
                        (SELECT count(*) FROM gda_control.service_consumer_binding_renewal)
                    """
                )
            ).one()

        report = {
                "schema": "gda.gis_service_control_plane.certification.v13",
            "status": "passed",
            "database": {"temporary_database": temp_name, "migrations": list(MIGRATIONS)},
            "authority": {
                "definition_created": definition_write.created,
                "definition_replay_created": definition_replay.created,
                "empty_active_pointer": empty_projection.active_endpoint_revision is None,
                "layer_created": layer_write.created,
                "layer_replay_created": layer_replay.created,
                "style_created": style_write.created,
                "tile_matrix_set_created": tile_matrix_write.created,
                "cache_policy_created": cache_policy_write.created,
                "cache_policy_replay_created": cache_policy_replay.created,
                "serving_projection_created": serving_projection_write.created,
                "serving_projection_replay_created": serving_projection_replay.created,
                "mismatched_source_hash_rejected": mismatched_source_hash_rejected,
                "service_policy_created": service_policy_write.created,
                "service_policy_replay_created": service_policy_replay.created,
                "unapproved_service_consumer_grant_rejected": unapproved_grant_rejected,
                "pending_service_consumer_grant_rejected": pending_grant_rejected,
                "approved_service_consumer_grant_created": grant_write.created,
                "service_consumer_grant_replay_created": grant_replay.created,
                "service_consumer_approval_payload_mismatch_rejected": (
                    approval_payload_mismatch_rejected
                ),
                "active_binding_before_renewal": active_before_renewal is not None,
                "pending_service_consumer_renewal_rejected": pending_renewal_rejected,
                "approved_service_consumer_renewal_created": renewal_write.binding.created,
                "service_consumer_renewal_replay_created": renewal_replay.binding.created,
                "renewal_decision_identity_rejected": renewal_decision_identity_rejected,
                "active_binding_after_renewal_is_target": (
                    active_after_renewal is not None
                    and active_after_renewal.service_consumer_binding_id
                    == renewal_target.service_consumer_binding_id
                ),
                "active_binding_before_revoke": active_before_revoke is not None,
                "pending_service_consumer_revoke_rejected": pending_revoke_rejected,
                "approved_service_consumer_revoke_created": revoke_write.revocation.created,
                "service_consumer_revoke_replay_created": revoke_replay.revocation.created,
                "service_consumer_revoke_payload_mismatch_rejected": (
                    revoke_payload_mismatch_rejected
                ),
                "active_binding_after_revoke": active_after_revoke is not None,
                "vector_tile_without_cache_rejected": (
                    vector_tile_without_cache_rejected
                ),
                "vector_tile_without_serving_projection_rejected": (
                    vector_tile_without_serving_projection_rejected
                ),
                "release_created": release_write.created,
                "release_replay_created": release_replay.created,
                "mixed_layer_style_rejected": mixed_layer_style_rejected,
                "deployment_without_release_rejected": (
                    deployment_without_release_rejected
                ),
                "deployment_created": deployment_write.created,
                "deployment_replay_created": deployment_replay.created,
                "canary_deployment_created": canary_deployment_write.created,
                "deploying_state_version": deploying.state_version,
                "canary_deploying_state_version": canary_deploying.state_version,
                "ready_state_version": ready.state_version,
                "ready_replay_state_version": ready_replay.state_version,
                "generic_deployment_observation_rejected": (
                    generic_deployment_observation_rejected
                ),
                "legacy_observation_rejected_for_ready": (
                    legacy_observation_rejected_for_ready
                ),
                "failed_settlement_rolled_back": failed_settlement_rolled_back,
                "deployment_settlement_created": (
                    deployment_settlement_write.observation_created
                ),
                "deployment_settlement_replay_created": (
                    deployment_settlement_replay.observation_created
                ),
                "canary_settlement_created": canary_settlement.observation_created,
                "succeeded_run_state_version": succeeded_run.state_version,
                "endpoint_before_ready_rejected": endpoint_before_ready_rejected,
                "endpoint_uri_mismatch_rejected": endpoint_uri_mismatch_rejected,
                "endpoint_one_created": endpoint_one_write.created,
                "endpoint_two_created": endpoint_two_write.created,
                "active_pointer_versions": [
                    active_one.endpoint_state_version,
                    active_two.endpoint_state_version,
                    rolled_back.endpoint_state_version,
                ],
                "active_endpoint_revision_id": str(
                    rolled_back.active_endpoint_revision.endpoint_revision_id
                ),
                "rollback_target_revision_id": str(endpoint_one.endpoint_revision_id),
                "active_release_binding_id": str(
                    rolled_back.active_release_binding.service_release_binding_id
                ),
                "active_service_policy_binding_id": str(
                    rolled_back.active_service_policy_binding.service_policy_binding_id
                ),
                "active_mvt_serving_projection_version_id": str(
                    rolled_back.active_mvt_serving_projection_version
                    .mvt_serving_projection_version_id
                ),
                "stale_cas_rejected": stale_cas_rejected,
                "inactive_product_source_rejected": (
                    inactive_product_source_rejected
                ),
            },
            "security": {
                "rls_enforced": bool(rls_enforced),
                "cross_tenant_rows": int(cross_tenant_rows),
                "direct_release_insert_sqlstate": direct_release_insert_sqlstate,
                "direct_endpoint_insert_sqlstate": direct_endpoint_insert_sqlstate,
                "direct_pointer_update_sqlstate": direct_pointer_update_sqlstate,
                "immutable_endpoint_sqlstate": immutable_endpoint_sqlstate,
                "gateway_privileges": list(gateway_privileges),
                "gateway_control_projection_privileges": list(
                    gateway_control_projection_privileges
                ),
                "service_consumer_binding_privileges": list(
                    service_consumer_binding_privileges
                ),
                "service_consumer_binding_revocation_privileges": list(
                    service_consumer_binding_revocation_privileges
                ),
                "service_consumer_binding_renewal_privileges": list(
                    service_consumer_binding_renewal_privileges
                ),
            },
            "counts": {
                "definitions": int(counts[0]),
                "layers": int(counts[1]),
                "styles": int(counts[2]),
                "tile_matrix_sets": int(counts[3]),
                "cache_policies": int(counts[4]),
                "service_policies": int(counts[5]),
                "serving_projections": int(counts[6]),
                "release_bindings": int(counts[7]),
                "deployments": int(counts[8]),
                "deployment_events": int(counts[9]),
                "endpoints": int(counts[10]),
                "activation_events": int(counts[11]),
                "service_consumer_bindings": int(counts[12]),
                "service_consumer_binding_revocations": int(counts[13]),
                "service_consumer_binding_renewals": int(counts[14]),
            },
            "migration_catalog": {
                "count": len(catalog),
                "latest": catalog[-1].migration_id,
                "fingerprint": catalog_fingerprint(catalog),
            },
        }
        if (
            not definition_write.created
            or definition_replay.created
            or empty_projection.active_endpoint_revision is not None
            or not layer_write.created
            or layer_replay.created
            or not style_write.created
            or not tile_matrix_write.created
            or not cache_policy_write.created
            or cache_policy_replay.created
            or not serving_projection_write.created
            or serving_projection_replay.created
            or not mismatched_source_hash_rejected
            or not service_policy_write.created
            or service_policy_replay.created
            or not unapproved_grant_rejected
            or not pending_grant_rejected
            or not grant_write.created
            or grant_replay.created
            or not approval_payload_mismatch_rejected
            or not active_before_renewal
            or not pending_renewal_rejected
            or not renewal_write.binding.created
            or renewal_replay.binding.created
            or not renewal_decision_identity_rejected
            or active_after_renewal is None
            or active_after_renewal.service_consumer_binding_id
            != renewal_target.service_consumer_binding_id
            or not active_before_revoke
            or not pending_revoke_rejected
            or not revoke_write.revocation.created
            or revoke_replay.revocation.created
            or not revoke_payload_mismatch_rejected
            or active_after_revoke is not None
            or not vector_tile_without_cache_rejected
            or not vector_tile_without_serving_projection_rejected
            or not release_write.created
            or release_replay.created
            or not mixed_layer_style_rejected
            or not deployment_without_release_rejected
            or not deployment_write.created
            or deployment_replay.created
            or not canary_deployment_write.created
            or deploying.state_version != 1
            or canary_deploying.state_version != 1
            or ready.state_version != 2
            or ready_replay.state_version != 2
            or not generic_deployment_observation_rejected
            or not legacy_observation_rejected_for_ready
            or not failed_settlement_rolled_back
            or not deployment_settlement_write.observation_created
            or deployment_settlement_replay.observation_created
            or not canary_settlement.observation_created
            or succeeded_run.state_version != 3
            or not endpoint_before_ready_rejected
            or not endpoint_uri_mismatch_rejected
            or not endpoint_one_write.created
            or not endpoint_two_write.created
            or [
                active_one.endpoint_state_version,
                active_two.endpoint_state_version,
                rolled_back.endpoint_state_version,
            ]
            != [1, 2, 3]
            or rolled_back.active_endpoint_revision.endpoint_revision_id
            != endpoint_one.endpoint_revision_id
            or rolled_back.active_release_binding.service_release_binding_id
            != release.service_release_binding_id
            or rolled_back.active_service_policy_binding.service_policy_binding_id
            != service_policy.service_policy_binding_id
            or (
                rolled_back.active_mvt_serving_projection_version
                .mvt_serving_projection_version_id
                != serving_projection.mvt_serving_projection_version_id
            )
            or not stale_cas_rejected
            or not inactive_product_source_rejected
            or not rls_enforced
            or int(cross_tenant_rows) != 0
            or direct_release_insert_sqlstate != "42501"
            or direct_endpoint_insert_sqlstate != "42501"
            or direct_pointer_update_sqlstate != "42501"
            or immutable_endpoint_sqlstate != "55000"
            or tuple(gateway_privileges)
            != (
                True,
                False,
                False,
                True,
                True,
                False,
                True,
                True,
                False,
                True,
                True,
                False,
                True,
                True,
                False,
                True,
                False,
                True,
            )
            or tuple(gateway_control_projection_privileges) != (True,) * 15
            or tuple(service_consumer_binding_privileges)
            != (True, False, False, True)
            or tuple(service_consumer_binding_revocation_privileges)
            != (True, False, True)
            or tuple(service_consumer_binding_renewal_privileges)
            != (True, False, True)
            or tuple(int(value) for value in counts)
            != (1, 2, 2, 1, 1, 1, 1, 1, 2, 6, 2, 3, 2, 1, 1)
            or catalog[-1].migration_id
            != "239_gis_ogc_api_features_read_authorization"
        ):
            report["status"] = "failed"
            raise RuntimeError(f"GIS service control-plane certification failed: {report}")
        if report_path is not None:
            report_path.parent.mkdir(parents=True, exist_ok=True)
            report_path.write_text(
                json.dumps(report, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
        return report
    finally:
        engine.dispose()
        login_engine.dispose()
        with admin.connect() as connection:
            connection.execute(text(f'DROP DATABASE IF EXISTS "{temp_name}" WITH (FORCE)'))
            connection.execute(text(f'DROP ROLE IF EXISTS "{login_role}"'))
        admin.dispose()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--database-url",
        default="postgresql://postgres:postgres@127.0.0.1:5433/gis_agent",
    )
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    print(
        json.dumps(
            certify(args.database_url, report_path=args.report),
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
