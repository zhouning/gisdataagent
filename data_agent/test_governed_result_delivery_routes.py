from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, Mock
from uuid import UUID

import httpx
from starlette.requests import Request

from data_agent.api import (
    data_product_routes,
    distribution_routes,
    map_publication_routes,
    quality_routes,
)
from data_agent.governed_query_policy_authority import (
    InMemoryGovernedQueryPolicyAuthority,
    build_policy_version,
    build_purpose_registration,
)
from data_agent.governed_query_result_delivery import (
    GovernedQueryResultDeliveryService,
)
from data_agent.governed_query_security import (
    GovernedQuerySecurityConfigurationError,
)
from data_agent.platform_contracts import SubjectType
from data_agent.user_context import current_tenant_id

TENANT = "local-dev"
NOW = datetime(2026, 8, 19, 12, 30, tzinfo=UTC)
PUBLICATION_ID = UUID("00000000-0000-4000-8000-000000000601")
PACKAGE_ID = UUID("00000000-0000-4000-8000-000000000602")


class _User:
    identifier = "analyst-a"
    metadata = {"tenant_id": TENANT, "role": "analyst"}


def _deny_reader() -> InMemoryGovernedQueryPolicyAuthority:
    return InMemoryGovernedQueryPolicyAuthority(TENANT, clock=lambda: NOW)


def _allow_map_reader(adapter_id: str) -> InMemoryGovernedQueryPolicyAuthority:
    authority = InMemoryGovernedQueryPolicyAuthority(TENANT, clock=lambda: NOW)
    authority.register_purpose(
        build_purpose_registration(
            tenant_id=TENANT,
            purpose_code="query_result_access",
            description="Read governed map results",
            registered_by="human:policy-admin",
            registered_at=NOW - timedelta(minutes=2),
        )
    )
    authority.register_policy(
        build_policy_version(
            tenant_id=TENANT,
            policy_ref="policy:map-result",
            policy_version="v1",
            purpose_code="query_result_access",
            subject_types=(SubjectType.HUMAN,),
            required_roles=("analyst",),
            channels=("map_result",),
            adapter_ids=(adapter_id,),
            resource_prefixes=(f"gda://{TENANT}/map_publication/",),
            valid_from=NOW - timedelta(minutes=1),
            expires_at=NOW + timedelta(days=1),
            published_at=NOW - timedelta(seconds=1),
            published_by="human:policy-admin",
        )
    )
    return authority


def _delivery() -> GovernedQueryResultDeliveryService:
    return GovernedQueryResultDeliveryService(ledger=Mock(), now=lambda: NOW)


def _request(
    path: str,
    *,
    method: str = "GET",
    path_params: dict | None = None,
    body: bytes = b"",
) -> Request:
    delivered = False

    async def receive():
        nonlocal delivered
        if delivered:
            return {"type": "http.disconnect"}
        delivered = True
        return {"type": "http.request", "body": body, "more_body": False}

    return Request(
        {
            "type": "http",
            "method": method,
            "path": path,
            "headers": [(b"content-type", b"application/json")],
            "query_string": b"",
            "path_params": path_params or {},
        },
        receive,
    )


def test_map_tile_policy_deny_never_calls_martin(monkeypatch) -> None:
    service = MagicMock()
    service.get.return_value = {
        "tenant_id": TENANT,
        "status": "ready",
        "min_zoom": 0,
        "max_zoom": 20,
    }
    martin = AsyncMock()
    monkeypatch.setattr(map_publication_routes, "_service", lambda: service)
    monkeypatch.setattr(map_publication_routes, "_result_delivery", _delivery)
    monkeypatch.setattr(
        map_publication_routes,
        "resolve_governed_query_security_ports",
        lambda tenant_id: (_deny_reader(), Mock()),
    )
    monkeypatch.setattr(
        map_publication_routes, "_get_user_from_request", lambda request: _User()
    )
    monkeypatch.setattr(map_publication_routes, "_set_user_context", lambda user: None)
    monkeypatch.setattr(map_publication_routes, "_fetch_martin_tile", martin)

    response = asyncio.run(
        map_publication_routes.map_publication_tile(
            _request(
                f"/api/map-publications/{PUBLICATION_ID}/tiles/3/4/2.pbf",
                path_params={
                    "publication_id": PUBLICATION_ID,
                    "z": 3,
                    "x": 4,
                    "y": 2,
                },
            )
        )
    )

    assert response.status_code == 403
    martin.assert_not_called()


def test_map_feature_policy_deny_never_queries_feature_projection(monkeypatch) -> None:
    service = MagicMock()
    service.get.return_value = {"tenant_id": TENANT, "status": "ready"}
    monkeypatch.setattr(map_publication_routes, "_service", lambda: service)
    monkeypatch.setattr(map_publication_routes, "_result_delivery", _delivery)
    monkeypatch.setattr(
        map_publication_routes,
        "resolve_governed_query_security_ports",
        lambda tenant_id: (_deny_reader(), Mock()),
    )
    monkeypatch.setattr(
        map_publication_routes, "_get_user_from_request", lambda request: _User()
    )
    monkeypatch.setattr(map_publication_routes, "_set_user_context", lambda user: None)

    response = asyncio.run(
        map_publication_routes.map_publication_feature(
            _request(
                f"/api/map-publications/{PUBLICATION_ID}/features/road-7",
                path_params={
                    "publication_id": PUBLICATION_ID,
                    "feature_id": "road-7",
                },
            )
        )
    )

    assert response.status_code == 403
    service.feature.assert_not_called()


def test_map_tile_provider_rejection_records_failure_outcome(monkeypatch) -> None:
    service = MagicMock()
    service.get.return_value = {
        "tenant_id": TENANT,
        "status": "ready",
        "min_zoom": 0,
        "max_zoom": 20,
    }
    ledger = Mock()
    delivery = GovernedQueryResultDeliveryService(ledger=ledger, now=lambda: NOW)
    monkeypatch.setattr(map_publication_routes, "_service", lambda: service)
    monkeypatch.setattr(map_publication_routes, "_result_delivery", lambda: delivery)
    monkeypatch.setattr(
        map_publication_routes,
        "resolve_governed_query_security_ports",
        lambda tenant_id: (
            _allow_map_reader("gda.map-publication.tile.v1"),
            Mock(),
        ),
    )
    monkeypatch.setattr(
        map_publication_routes, "_get_user_from_request", lambda request: _User()
    )
    monkeypatch.setattr(map_publication_routes, "_set_user_context", lambda user: None)
    monkeypatch.setattr(
        map_publication_routes,
        "_fetch_martin_tile",
        AsyncMock(return_value=httpx.Response(503)),
    )

    response = asyncio.run(
        map_publication_routes.map_publication_tile(
            _request(
                f"/api/map-publications/{PUBLICATION_ID}/tiles/3/4/2.pbf",
                path_params={
                    "publication_id": PUBLICATION_ID,
                    "z": 3,
                    "x": 4,
                    "y": 2,
                },
            )
        )
    )

    assert response.status_code == 503
    assert [call.kwargs["phase"] for call in ledger.append.call_args_list] == [
        "admitted",
        "outcome",
    ]
    assert ledger.append.call_args.kwargs["outcome"] == "failure"


def test_data_product_download_policy_deny_precedes_artifact_and_s3(monkeypatch) -> None:
    artifact_gateway = MagicMock()
    s3_client = MagicMock()
    artifact_id = UUID("00000000-0000-4000-8000-000000000603")
    registry = MagicMock()
    registry.get_version.return_value = {
        "version_key": "v1",
        "distribution_manifest": {
            "formats": [
                {
                    "kind": "S3GeoJSON",
                    "artifact_id": str(artifact_id),
                }
            ]
        },
    }
    monkeypatch.setattr(data_product_routes, "_registry", lambda: registry)
    monkeypatch.setattr(data_product_routes, "_result_delivery", _delivery)
    monkeypatch.setattr(
        data_product_routes,
        "resolve_governed_query_security_ports",
        lambda tenant_id: (_deny_reader(), Mock()),
    )
    monkeypatch.setattr(
        data_product_routes, "PlatformGateway", lambda: artifact_gateway
    )
    monkeypatch.setattr(data_product_routes, "_s3_client", lambda: s3_client)

    response = asyncio.run(
        data_product_routes.download_data_product(
            _request(
                "/api/data-products/test-roads/download",
                path_params={"product_slug": "test-roads"},
            )
        )
    )

    assert response.status_code == 403
    artifact_gateway.get_artifact.assert_not_called()
    s3_client.get_object.assert_not_called()


def test_data_product_map_policy_deny_precedes_postgis_projection(monkeypatch) -> None:
    registry = MagicMock()
    registry.get_version.return_value = {
        "version_key": "v1",
        "distribution_manifest": {
            "formats": [
                {"kind": "PostGIS", "schema": "public", "table": "roads"}
            ],
        },
    }
    projection_reader = Mock()
    monkeypatch.setattr(data_product_routes, "_registry", lambda: registry)
    monkeypatch.setattr(data_product_routes, "_result_delivery", _delivery)
    monkeypatch.setattr(
        data_product_routes,
        "resolve_governed_query_security_ports",
        lambda tenant_id: (_deny_reader(), Mock()),
    )
    monkeypatch.setattr(data_product_routes, "_read_features", projection_reader)

    response = asyncio.run(
        data_product_routes.get_data_product_features(
            _request(
                "/api/data-products/test-roads/features",
                path_params={"product_slug": "test-roads"},
            )
        )
    )

    assert response.status_code == 403
    projection_reader.assert_not_called()


def test_distribution_policy_deny_never_resolves_or_reads_zip(monkeypatch) -> None:
    package_resolver = Mock()
    monkeypatch.setattr(
        distribution_routes, "_get_user_from_request", lambda request: _User()
    )

    def set_context(user):
        current_tenant_id.set(TENANT)
        return user.identifier, user.metadata["role"]

    monkeypatch.setattr(distribution_routes, "_set_user_context", set_context)
    monkeypatch.setattr(distribution_routes, "_result_delivery", _delivery)
    monkeypatch.setattr(
        distribution_routes,
        "resolve_governed_query_security_ports",
        lambda tenant_id: (_deny_reader(), Mock()),
    )
    monkeypatch.setattr(
        "data_agent.data_distribution.get_distribution_package", package_resolver
    )

    response = asyncio.run(
        distribution_routes.distribution_package_download(
            _request(
                f"/api/distribution-packages/{PACKAGE_ID}/download",
                path_params={"package_id": str(PACKAGE_ID)},
            )
        )
    )

    assert response.status_code == 403
    package_resolver.assert_not_called()


def test_report_policy_deny_never_invokes_generator(monkeypatch) -> None:
    generator = Mock()
    monkeypatch.setattr(quality_routes, "_get_user_from_request", lambda request: _User())

    def set_context(user):
        current_tenant_id.set(TENANT)
        return user.identifier, user.metadata["role"]

    monkeypatch.setattr(quality_routes, "_set_user_context", set_context)
    monkeypatch.setattr(quality_routes, "_result_delivery", _delivery)
    monkeypatch.setattr(
        quality_routes,
        "resolve_governed_query_security_ports",
        lambda tenant_id: (_deny_reader(), Mock()),
    )
    monkeypatch.setattr("data_agent.report_generator.generate_qc_report", generator)

    response = asyncio.run(
        quality_routes.qc_report_generate(
            _request(
                "/api/reports/generate",
                method="POST",
                body=b'{"section_data":{"summary":"private"}}',
            )
        )
    )

    assert response.status_code == 403
    generator.assert_not_called()


def test_required_security_resolution_failure_precedes_data_product_provider(
    monkeypatch,
) -> None:
    artifact_gateway = MagicMock()
    registry = MagicMock()
    registry.get_version.return_value = {
        "version_key": "v1",
        "distribution_manifest": {
            "formats": [
                {
                    "kind": "S3GeoJSON",
                    "artifact_id": "00000000-0000-4000-8000-000000000604",
                }
            ]
        },
    }
    monkeypatch.setattr(data_product_routes, "_registry", lambda: registry)
    monkeypatch.setattr(
        data_product_routes,
        "resolve_governed_query_security_ports",
        Mock(side_effect=GovernedQuerySecurityConfigurationError("resolver missing")),
    )
    monkeypatch.setattr(
        data_product_routes, "PlatformGateway", lambda: artifact_gateway
    )

    response = asyncio.run(
        data_product_routes.download_data_product(
            _request(
                "/api/data-products/test-roads/download",
                path_params={"product_slug": "test-roads"},
            )
        )
    )

    assert response.status_code == 503
    assert json.loads(response.body)["error"]["code"] == (
        "data_product_download_security_unavailable"
    )
    artifact_gateway.get_artifact.assert_not_called()
