#!/usr/bin/env python3
"""Certify a governed OGC API Features provider against an active GIS release.

Discovery mode probes a live provider origin. Active-release mode first reads
the existing PlatformGateway projection and only then performs an exact
collection read. The script never creates a service, deployment, endpoint, or
provider-side catalog.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from sqlalchemy import create_engine

from data_agent.gis_provider_runtime import (
    GISProviderContractError,
    OGCAPIFeaturesProvider,
    OGCAPIFeaturesReleaseContext,
    pygeoapi_provider_manifest,
)
from data_agent.gis_service_control_plane import (
    EndpointProtocol,
    GISServiceType,
    ServiceDeploymentState,
)
from data_agent.platform_contracts import canonical_json_fingerprint
from data_agent.platform_gateway import PlatformGateway


def _active_release_context(
    gateway: PlatformGateway,
    *,
    tenant_id: str,
    service_urn: str,
) -> tuple[OGCAPIFeaturesReleaseContext, dict[str, object]]:
    """Load one exact feature collection target from the Service Control Plane."""
    projection = gateway.get_gis_service_control_projection(tenant_id, service_urn)
    release = projection.active_release_binding
    definition = projection.active_service_definition_version
    layer = projection.active_layer_definition_version
    deployment = projection.active_deployment_revision
    endpoint = projection.active_endpoint_revision
    if any(item is None for item in (release, definition, layer, deployment, endpoint)):
        raise GISProviderContractError(
            "active GIS service does not expose a complete OGC API Features projection"
        )
    if definition.service_type is not GISServiceType.FEATURE:
        raise GISProviderContractError("active GIS service is not a feature service")
    if deployment.provider_system != "pygeoapi":
        raise GISProviderContractError("active feature deployment does not use pygeoapi")
    if deployment.state is not ServiceDeploymentState.READY:
        raise GISProviderContractError("active pygeoapi deployment is not ready")
    if endpoint.endpoint_protocol is not EndpointProtocol.OGC_API_FEATURES:
        raise GISProviderContractError("active GIS endpoint is not OGC API Features")
    contract = endpoint.endpoint_contract
    if contract.get("schema") != "gda.ogc_api_features_endpoint.v1":
        raise GISProviderContractError(
            "active OGC API Features endpoint has an unsupported contract schema"
        )
    if set(contract) != {"schema", "collection_id"}:
        raise GISProviderContractError(
            "active OGC API Features endpoint must bind collection_id exactly"
        )
    collection_id = contract.get("collection_id")
    if not isinstance(collection_id, str):
        raise GISProviderContractError(
            "active OGC API Features endpoint must bind collection_id"
        )
    context = OGCAPIFeaturesReleaseContext.from_release(
        release,
        definition,
        layer,
        collection_id=collection_id,
    )
    return context, {
        "tenant_id": context.tenant_id,
        "service_urn": service_urn,
        "endpoint_state_version": projection.endpoint_state_version,
        "endpoint_revision_id": str(endpoint.endpoint_revision_id),
        "consumer_endpoint_uri": endpoint.endpoint_uri,
        "deployment_revision_id": str(deployment.deployment_revision_id),
        "service_release_binding_id": str(context.service_release_binding_id),
        "service_definition_version_id": str(context.service_definition_version_id),
        "layer_definition_version_id": str(context.layer_definition_version_id),
        "collection_id": context.collection_id,
    }


async def _certify_discovery(
    endpoint: str,
    *,
    limit: int,
    provider_version: str | None,
) -> dict[str, object]:
    provider = OGCAPIFeaturesProvider(
        endpoint,
        manifest=pygeoapi_provider_manifest(provider_version or "0.21.0"),
    )
    health = await provider.health()
    conformance = await provider.discover_conformance()
    catalog = await provider.discover_capabilities()
    return {
        "schema": "gda.gis_ogc_api_features_provider_certification.v1",
        "status": "discovery_only",
        "provider_endpoint": provider.endpoint_uri,
        "manifest": provider.manifest.model_dump(mode="json"),
        "health": health.model_dump(mode="json"),
        "conformance_sha256": canonical_json_fingerprint(conformance),
        "catalog_sha256": canonical_json_fingerprint(catalog),
        "control_target": None,
        "conformance_receipt": None,
        "requested_limit": limit,
    }


async def _certify_active_release(
    endpoint: str,
    context: OGCAPIFeaturesReleaseContext,
    control_target: dict[str, object],
    *,
    limit: int,
    bbox: tuple[float, float, float, float] | None,
    provider_version: str | None,
) -> dict[str, object]:
    provider = OGCAPIFeaturesProvider(
        endpoint,
        manifest=pygeoapi_provider_manifest(provider_version or "0.21.0"),
    )
    receipt = await provider.conform_features_read(context, limit=limit, bbox=bbox)
    return {
        "schema": "gda.gis_ogc_api_features_provider_certification.v1",
        "status": "active_release_read_certified",
        "provider_endpoint": provider.endpoint_uri,
        "manifest": provider.manifest.model_dump(mode="json"),
        "health": receipt.health.model_dump(mode="json"),
        "conformance_sha256": receipt.conformance_sha256,
        "catalog_sha256": receipt.catalog_sha256,
        "control_target": control_target,
        "conformance_receipt": receipt.model_dump(mode="json", by_alias=True),
    }


def certify(
    endpoint: str,
    *,
    database_url: str | None = None,
    tenant_id: str | None = None,
    service_urn: str | None = None,
    limit: int = 100,
    bbox: tuple[float, float, float, float] | None = None,
    provider_version: str | None = None,
    report_path: Path | None = None,
) -> dict[str, object]:
    read_mode = (database_url is not None, tenant_id is not None, service_urn is not None)
    if any(read_mode) and not all(read_mode):
        raise GISProviderContractError(
            "active release certification requires database_url, tenant_id, and service_urn"
        )
    if not all(read_mode):
        report = asyncio.run(
            _certify_discovery(
                endpoint,
                limit=limit,
                provider_version=provider_version,
            )
        )
    else:
        engine = create_engine(database_url)
        try:
            gateway = PlatformGateway(engine)
            context, target = _active_release_context(
                gateway,
                tenant_id=tenant_id,
                service_urn=service_urn,
            )
            report = asyncio.run(
                _certify_active_release(
                    endpoint,
                    context,
                    target,
                    limit=limit,
                    bbox=bbox,
                    provider_version=provider_version,
                )
            )
        finally:
            engine.dispose()
    if report_path is not None:
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(
            json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
    return report


def _parse_bbox(value: str) -> tuple[float, float, float, float]:
    try:
        values = tuple(float(item) for item in value.split(","))
    except ValueError as exc:
        raise argparse.ArgumentTypeError("bbox must be minx,miny,maxx,maxy") from exc
    if len(values) != 4:
        raise argparse.ArgumentTypeError("bbox must be minx,miny,maxx,maxy")
    return values  # type: ignore[return-value]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--endpoint", default="http://127.0.0.1:5000")
    parser.add_argument("--database-url")
    parser.add_argument("--tenant")
    parser.add_argument("--service-urn")
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--bbox", type=_parse_bbox)
    parser.add_argument(
        "--provider-version",
        help="provider version to bind in the manifest; required when it differs from 0.21.0",
    )
    parser.add_argument("--report")
    args = parser.parse_args()
    report = certify(
        args.endpoint,
        database_url=args.database_url,
        tenant_id=args.tenant,
        service_urn=args.service_urn,
        limit=args.limit,
        bbox=args.bbox,
        provider_version=args.provider_version,
        report_path=Path(args.report) if args.report else None,
    )
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
