"""Contract tests for governed DataProductVersion publication."""

from __future__ import annotations

import asyncio
import hashlib
import json
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from starlette.applications import Starlette
from starlette.testclient import TestClient

from data_agent.api import data_product_routes
from data_agent.api.data_product_routes import (
    _bbox,
    _file_distribution,
    get_data_product_routes,
)
from data_agent.api.platform_gateway_routes import GatewayPrincipal
from data_agent.data_product_registry import (
    DATA_PRODUCT_ROLLBACK_APPROVAL_ACTION,
    DATA_PRODUCT_ROLLBACK_SCHEMA,
    DataProductPromotionImpactError,
    DataProductRegistry,
    DataProductSpec,
    DataProductVersionSpec,
    _build_promotion_impact,
    data_product_manifest_fingerprint,
    data_product_rollback_fingerprint,
)
from data_agent.data_products.chongqing_osm_roads import (
    EXPECTED_MAPPING,
    STANDARD_VERSION_REF,
    TARGET_TABLE,
    _standard_elements,
)
from data_agent.platform_contracts import SubjectType
from data_agent.standards_platform.application.contracts import (
    SourceFieldProfile,
    propose_standard_mapping,
)


def _version_payload() -> dict:
    payload = {
        "tenant_id": "local-dev",
        "data_product_version_id": uuid4(),
        "product_urn": "gda://local-dev/data_product/test-roads",
        "version_key": "v1.0.0",
        "predecessor_version_id": None,
        "source_resource_version_id": uuid4(),
        "output_resource_version_id": uuid4(),
        "standard_version_ref": "standard:test:v1",
        "mapping_contract": {"mapping": {"source": "target"}},
        "quality_contract": {"verdict": "passed", "checks": []},
        "quality_evidence_artifact_id": uuid4(),
        "distribution_manifest": {"formats": []},
        "published_by": "workload:test",
        "published_at": datetime(2026, 8, 1, tzinfo=UTC),
    }
    payload["manifest_sha256"] = data_product_manifest_fingerprint(payload)
    return payload


def test_data_product_requires_complete_governance() -> None:
    with pytest.raises(ValueError, match="governance_ref"):
        DataProductSpec(
            tenant_id="local-dev",
            product_urn="gda://local-dev/data_product/test-roads",
            product_slug="test-roads",
            title="Test roads",
            description="A test product",
            domain="transportation",
            owner_ref="team:test",
            governance_ref={"classification": "public"},
            created_at=datetime(2026, 8, 1, tzinfo=UTC),
        )


def test_only_passed_quality_can_create_product_version() -> None:
    payload = _version_payload()
    payload["quality_contract"] = {"verdict": "failed", "checks": []}
    payload["manifest_sha256"] = data_product_manifest_fingerprint(payload)
    with pytest.raises(ValueError, match="only a passed quality contract"):
        DataProductVersionSpec.model_validate(payload)


def test_product_version_manifest_is_tamper_evident() -> None:
    payload = _version_payload()
    version = DataProductVersionSpec.model_validate(payload)
    assert data_product_manifest_fingerprint(version) == version.manifest_sha256
    payload["standard_version_ref"] = "standard:test:v2"
    with pytest.raises(ValueError, match="manifest_sha256"):
        DataProductVersionSpec.model_validate(payload)


def test_product_version_rejects_self_predecessor() -> None:
    payload = _version_payload()
    payload["predecessor_version_id"] = payload["data_product_version_id"]
    payload["manifest_sha256"] = data_product_manifest_fingerprint(payload)
    with pytest.raises(ValueError, match="own predecessor"):
        DataProductVersionSpec.model_validate(payload)


def test_rollback_fingerprint_is_exact_and_approval_constants_are_typed() -> None:
    source_id = uuid4()
    target_id = uuid4()
    fingerprint = data_product_rollback_fingerprint(
        tenant_id="planning",
        product_urn="gda://planning/data_product/districts",
        from_version_id=source_id,
        to_version_id=target_id,
    )
    assert len(fingerprint) == 64
    assert DATA_PRODUCT_ROLLBACK_APPROVAL_ACTION == "data_product.rollback"
    assert DATA_PRODUCT_ROLLBACK_SCHEMA == "gda.data_product.rollback.v1"
    assert fingerprint == data_product_rollback_fingerprint(
        tenant_id="planning",
        product_urn="gda://planning/data_product/districts",
        from_version_id=source_id,
        to_version_id=target_id,
    )
    assert fingerprint != data_product_rollback_fingerprint(
        tenant_id="planning",
        product_urn="gda://planning/data_product/districts",
        from_version_id=target_id,
        to_version_id=source_id,
    )


def test_osm_standard_profile_maps_every_real_source_field_unambiguously() -> None:
    source_fields = tuple(
        SourceFieldProfile(name=name, dtype=dtype)
        for name, dtype in (
            ("osm_id", "str:10"),
            ("code", "int:4"),
            ("fclass", "str:28"),
            ("name", "str:100"),
            ("ref", "str:20"),
            ("oneway", "str:1"),
            ("maxspeed", "int:3"),
            ("layer", "int:12"),
            ("bridge", "str:1"),
            ("tunnel", "str:1"),
        )
    )
    proposal = propose_standard_mapping(
        source_fields=source_fields,
        standard_version_id=STANDARD_VERSION_REF,
        elements=_standard_elements(),
        target_table=TARGET_TABLE,
    )
    assert proposal["mapping"] == EXPECTED_MAPPING
    assert proposal["summary"] == {
        "source_fields": 10,
        "standard_elements": 10,
        "recommended": 10,
        "review_required": 0,
        "unmatched": 0,
        "conflicts": 0,
    }


def test_data_product_routes_expose_complete_read_surface() -> None:
    routes = get_data_product_routes()
    paths = {(route.path, tuple(sorted(route.methods or ()))) for route in routes}
    assert ("/api/data-products", ("GET", "HEAD")) in paths
    assert ("/api/data-products/{product_slug}/features", ("GET", "HEAD")) in paths
    assert ("/api/data-products/{product_slug}/download", ("GET", "HEAD")) in paths
    assert ("/api/data-products/{product_slug}/lineage", ("GET", "HEAD")) in paths
    assert ("/api/data-products/{product_slug}/stac", ("GET", "HEAD")) in paths
    assert ("/api/data-products/{product_slug}/rollback", ("POST",)) in paths
    assert ("/api/data-products/{product_slug}/promote", ("POST",)) in paths
    assert (
        "/api/data-products/{product_slug}/promotion-impact",
        ("GET", "HEAD"),
    ) in paths
    assert ("/data-products/{product_slug}", ("GET", "HEAD")) in paths


def test_bbox_validation_is_fail_closed() -> None:
    assert _bbox("105,28,111,33") == (105.0, 28.0, 111.0, 33.0)
    with pytest.raises(ValueError, match="xmin"):
        _bbox("111,28,105,33")


def test_promotion_impact_is_stable_and_summarizes_active_consumers() -> None:
    current_id = uuid4()
    target_id = uuid4()
    product = {
        "tenant_id": "planning",
        "product_urn": "gda://planning/data_product/districts",
        "current_version_id": str(current_id),
        "current_version_key": "v1.0.0",
    }
    target = {
        "data_product_version_id": str(target_id),
        "version_key": "v2.0.0",
    }
    rows = [
        {
            "request_id": 8,
            "requester": "planner-b",
            "asset_id": 42,
            "locked_version_key": "v1.0.0",
            "expires_at": datetime(2026, 9, 1),
            "granted_package_quota": 5,
            "packages_created": 2,
            "packages_remaining": 3,
        },
        {
            "request_id": 7,
            "requester": "planner-a",
            "asset_id": 42,
            "locked_version_key": "v1.0.0",
            "expires_at": datetime(2026, 8, 20),
            "granted_package_quota": 3,
            "packages_created": 2,
            "packages_remaining": 1,
        },
    ]

    impact = _build_promotion_impact(product, target, rows)
    replay = _build_promotion_impact(product, target, list(reversed(rows)))

    assert impact["active_grant_count"] == 2
    assert impact["impacted_consumer_count"] == 2
    assert impact["remaining_package_quota"] == 4
    assert impact["impacted_consumers"] == ["planner-a", "planner-b"]
    assert impact["acknowledgement_required"] is True
    assert impact["promotion_ready"] is False
    assert impact["impact_fingerprint"] == replay["impact_fingerprint"]


def test_promotion_impact_without_consumers_is_ready() -> None:
    impact = _build_promotion_impact(
        {
            "tenant_id": "planning",
            "product_urn": "gda://planning/data_product/districts",
            "current_version_id": str(uuid4()),
            "current_version_key": "v1.0.0",
        },
        {
            "data_product_version_id": str(uuid4()),
            "version_key": "v1.1.0",
        },
        [],
    )

    assert impact["active_grant_count"] == 0
    assert impact["acknowledgement_required"] is False
    assert impact["promotion_ready"] is True


def test_staged_publication_replay_returns_recorded_impact() -> None:
    current_id = uuid4()
    target_id = uuid4()
    impact_id = uuid4()
    product = DataProductSpec(
        tenant_id="local-dev",
        product_urn="gda://local-dev/data_product/test-roads",
        product_slug="test-roads",
        title="Test roads",
        description="A test product",
        domain="transportation",
        owner_ref="team:test",
        governance_ref={
            "classification": "internal",
            "visibility": "private",
            "license_id": "internal",
            "attribution": "test",
        },
        created_at=datetime(2026, 8, 1, tzinfo=UTC),
    )
    payload = _version_payload()
    payload.update(
        {
            "data_product_version_id": target_id,
            "version_key": "v2.0.0",
            "predecessor_version_id": current_id,
        }
    )
    payload["manifest_sha256"] = data_product_manifest_fingerprint(payload)
    version = DataProductVersionSpec.model_validate(payload)
    stored_product = {
        **product.model_dump(mode="json"),
        "current_version_id": str(current_id),
        "current_version_key": "v1.0.0",
    }
    stored_version = version.model_dump(mode="json")
    recorded_impact = {
        "impact_fingerprint": "a" * 64,
        "active_grant_count": 1,
    }
    connection = MagicMock()
    insert_product = MagicMock()
    insert_product.first.return_value = None
    insert_version = MagicMock()
    insert_version.first.return_value = None
    staged_event = MagicMock()
    staged_event.mappings.return_value.one_or_none.return_value = {
        "event_id": uuid4(),
        "event_type": "staged",
        "from_version_id": current_id,
        "to_version_id": target_id,
        "promotion_impact_id": impact_id,
    }
    connection.execute.side_effect = [insert_product, insert_version, staged_event]
    registry = DataProductRegistry(engine=MagicMock())
    transaction = MagicMock()
    transaction.return_value.__enter__.return_value = connection

    with (
        patch.object(registry, "_transaction", transaction),
        patch.object(registry, "_lock_promotion_scope"),
        patch.object(registry, "_load_product", return_value=stored_product),
        patch.object(registry, "_load_version", return_value=stored_version),
        patch.object(
            registry,
            "_load_recorded_promotion_impact",
            return_value=recorded_impact,
        ) as load_impact,
        patch.object(registry, "_promotion_impact") as calculate_impact,
        patch.object(registry, "_record_promotion_impact") as record_impact,
    ):
        result = registry.publish(
            product,
            version,
            idempotency_key="publish-v2",
            reason="retry staged publication",
        )

    assert result["idempotent_replay"] is True
    assert result["promotion_deferred"] is True
    assert result["promotion_impact"] == recorded_impact
    load_impact.assert_called_once_with(connection, "local-dev", impact_id)
    calculate_impact.assert_not_called()
    record_impact.assert_not_called()


def test_promotion_impact_preview_route_returns_operator_view() -> None:
    request = MagicMock()
    request.path_params = {"product_slug": "districts"}
    request.query_params = {"target_version": "v2.0.0"}
    principal = GatewayPrincipal(
        tenant_id="planning",
        subject_id="admin",
        subject_type=SubjectType.HUMAN,
        role="platform_operator",
    )
    registry = MagicMock()
    registry.preview_promotion_impact.return_value = {
        "impact_fingerprint": "a" * 64,
        "active_grant_count": 2,
    }

    with (
        patch.object(data_product_routes, "_principal", return_value=principal),
        patch.object(data_product_routes, "_registry", return_value=registry),
    ):
        response = asyncio.run(
            data_product_routes.preview_data_product_promotion_impact(request)
        )

    assert response.status_code == 200
    assert json.loads(response.body)["data"]["active_grant_count"] == 2
    registry.preview_promotion_impact.assert_called_once_with(
        "planning",
        "districts",
        "v2.0.0",
    )


def test_promotion_route_returns_latest_impact_when_acknowledgement_is_stale() -> None:
    request = MagicMock()
    request.path_params = {"product_slug": "districts"}
    request.json = AsyncMock(
        return_value={
            "target_version": "v2.0.0",
            "reason": "publish new districts",
            "idempotency_key": "promotion-17",
            "impact_acknowledgement": "stale-fingerprint",
        }
    )
    principal = GatewayPrincipal(
        tenant_id="planning",
        subject_id="admin",
        subject_type=SubjectType.HUMAN,
        role="platform_operator",
    )
    impact = {
        "impact_fingerprint": "b" * 64,
        "active_grant_count": 3,
        "acknowledgement_required": True,
    }
    registry = MagicMock()
    registry.promote.side_effect = DataProductPromotionImpactError(impact)

    with (
        patch.object(data_product_routes, "_principal", return_value=principal),
        patch.object(data_product_routes, "_registry", return_value=registry),
    ):
        response = asyncio.run(data_product_routes.promote_data_product(request))

    body = json.loads(response.body)
    assert response.status_code == 409
    assert body["error"]["code"] == "promotion_impact_acknowledgement_required"
    assert body["data"]["impact_fingerprint"] == "b" * 64


def test_rollback_route_forwards_exact_authority_binding() -> None:
    request = MagicMock()
    request.path_params = {"product_slug": "districts"}
    incident_id = uuid4()
    request.json = AsyncMock(
        return_value={
            "target_version": "v1.0.0",
            "reason": "restore data after active quality incident",
            "idempotency_key": "rollback-17",
            "incident_id": str(incident_id),
        }
    )
    principal = GatewayPrincipal(
        tenant_id="planning",
        subject_id="operator",
        subject_type=SubjectType.HUMAN,
        role="platform_operator",
    )
    registry = MagicMock()
    registry.rollback.return_value = {"pointer_changed": True}

    with (
        patch.object(data_product_routes, "_principal", return_value=principal),
        patch.object(data_product_routes, "_registry", return_value=registry),
    ):
        response = asyncio.run(data_product_routes.rollback_data_product(request))

    assert response.status_code == 200
    registry.rollback.assert_called_once_with(
        "planning",
        "districts",
        "v1.0.0",
        actor_subject="human:operator",
        reason="restore data after active quality incident",
        idempotency_key="rollback-17",
        incident_id=incident_id,
        rollback_approval_case_ref=None,
    )


def test_download_prefers_governed_s3_distribution() -> None:
    local_artifact_id = uuid4()
    s3_artifact_id = uuid4()
    distribution = _file_distribution(
        {
            "formats": [
                {"kind": "GeoJSON", "artifact_id": str(local_artifact_id)},
                {"kind": "S3GeoJSON", "artifact_id": str(s3_artifact_id)},
            ]
        }
    )
    assert distribution["artifact_id"] == str(s3_artifact_id)
    assert _file_distribution(
        {"formats": [{"kind": "GeoJSON", "artifact_id": str(local_artifact_id)}]}
    )["artifact_id"] == str(local_artifact_id)


def test_s3_download_verifies_ledger_metadata_size_and_payload(monkeypatch) -> None:
    payload = b'{"type":"FeatureCollection","features":[]}'
    content_sha256 = hashlib.sha256(payload).hexdigest()
    artifact_id = uuid4()
    artifact = SimpleNamespace(
        storage_uri="s3://gis-agent-lakehouse/products/test-roads.geojson",
        media_type="application/geo+json",
        content_sha256=content_sha256,
        size_bytes=len(payload),
    )
    distribution = {
        "kind": "S3GeoJSON",
        "artifact_id": str(artifact_id),
        "content_sha256": content_sha256,
        "size_bytes": len(payload),
    }

    class FakeRegistry:
        def get_version(self, tenant_id, product_slug):
            assert tenant_id == "local-dev"
            assert product_slug == "test-roads"
            return {"version_key": "v1.2.0", "distribution_manifest": {"formats": [distribution]}}

    class FakeGateway:
        def get_artifact(self, tenant_id, requested_artifact_id):
            assert tenant_id == "local-dev"
            assert requested_artifact_id == artifact_id
            return artifact

    class FakeS3Client:
        def get_object(self, *, Bucket, Key):
            assert Bucket == "gis-agent-lakehouse"
            assert Key == "products/test-roads.geojson"
            return {
                "Body": BytesIO(payload),
                "ContentLength": len(payload),
                "Metadata": {"sha256": content_sha256},
            }

    monkeypatch.setattr(data_product_routes, "_registry", lambda: FakeRegistry())
    monkeypatch.setattr(data_product_routes, "PlatformGateway", FakeGateway)
    monkeypatch.setattr(data_product_routes, "_s3_client", lambda: FakeS3Client())

    client = TestClient(Starlette(routes=get_data_product_routes()))
    response = client.get("/api/data-products/test-roads/download")

    assert response.status_code == 200
    assert response.content == payload
    assert response.headers["content-type"] == "application/geo+json"
    assert response.headers["content-length"] == str(len(payload))
    assert response.headers["content-disposition"] == (
        'attachment; filename="test-roads-v1.2.0.geojson"'
    )


def test_s3_download_fails_closed_on_object_metadata_mismatch(monkeypatch) -> None:
    payload = b"trusted bytes"
    content_sha256 = hashlib.sha256(payload).hexdigest()
    artifact_id = uuid4()
    artifact = SimpleNamespace(
        storage_uri="s3://gis-agent-lakehouse/products/test-roads.geojson",
        media_type="application/geo+json",
        content_sha256=content_sha256,
        size_bytes=len(payload),
    )

    class FakeRegistry:
        def get_version(self, tenant_id, product_slug):
            return {
                "version_key": "v1.2.0",
                "distribution_manifest": {
                    "formats": [
                        {
                            "kind": "S3GeoJSON",
                            "artifact_id": str(artifact_id),
                            "content_sha256": content_sha256,
                            "size_bytes": len(payload),
                        }
                    ]
                },
            }

    class FakeGateway:
        def get_artifact(self, tenant_id, requested_artifact_id):
            return artifact

    class FakeS3Client:
        def get_object(self, **kwargs):
            return {
                "Body": BytesIO(payload),
                "ContentLength": len(payload),
                "Metadata": {"sha256": "0" * 64},
            }

    monkeypatch.setattr(data_product_routes, "_registry", lambda: FakeRegistry())
    monkeypatch.setattr(data_product_routes, "PlatformGateway", FakeGateway)
    monkeypatch.setattr(data_product_routes, "_s3_client", lambda: FakeS3Client())

    client = TestClient(Starlette(routes=get_data_product_routes()))
    response = client.get("/api/data-products/test-roads/download")

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "data_product_download_unavailable"


def test_migration_enforces_append_only_versions_and_pointer_events() -> None:
    migration = (
        Path(__file__).parent / "migrations/100_data_product_registry.sql"
    ).read_text(encoding="utf-8")
    assert "CREATE TABLE gda_control.data_product_version" in migration
    assert "quality_verdict = 'passed'" in migration
    assert "trg_gda_data_product_version_immutable" in migration
    assert "trg_gda_data_product_event_immutable" in migration
    assert migration.count("FORCE ROW LEVEL SECURITY") == 3


def test_promotion_migration_adds_audited_forward_activation() -> None:
    migration = (
        Path(__file__).parent / "migrations/101_data_product_promotion.sql"
    ).read_text(encoding="utf-8")
    assert "'promoted'" in migration


def test_promotion_impact_migration_is_tenant_scoped_and_audited() -> None:
    migration = (
        Path(__file__).parent
        / "migrations/108_data_product_promotion_impact.sql"
    ).read_text(encoding="utf-8")

    assert "data_product_promotion_impact" in migration
    assert "active_distribution_grant_impact" in migration
    assert "SECURITY DEFINER" in migration
    assert "p_tenant_id = gda_control.current_tenant()" in migration
    assert "promotion_impact_id" in migration
    assert "'staged'" in migration
    assert "REVOKE ALL ON FUNCTION" in migration
    assert "ck_gda_data_product_event_type" in migration


def test_rollback_migration_requires_incident_or_approved_case_authority() -> None:
    migration = (
        Path(__file__).parent
        / "migrations/151_data_product_rollback_authority.sql"
    ).read_text(encoding="utf-8")
    assert "rollback_authority_kind" in migration
    assert "data_product.rollback" in migration
    assert "data_incident" in migration
    assert "approval_case" in migration
    assert "gda.data_product_rollback_event_allowed" in migration
    assert "SECURITY DEFINER" in migration
    assert (
        "FOR EACH ROW EXECUTE FUNCTION "
        "gda_control.guard_data_product_rollback_event"
    ) in migration
    # Existing deployments may contain legacy rollback facts.  The migration
    # must preserve those rows while enforcing authority on every new write.
    assert ") NOT VALID;" in migration
