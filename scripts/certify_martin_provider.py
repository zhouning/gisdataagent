#!/usr/bin/env python3
"""Certify the governed Martin MVT provider against an active GIS release.

Discovery mode validates only a live Martin health/catalog surface. Read
conformance additionally loads the active GIS Service Control Projection through
the existing PostgreSQL Gateway and probes its exact serving projection. The
script never creates services, deployments, endpoints, publications, or a
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
    GISProviderRuntimeError,
    MartinMVTWarmupSample,
    MartinVectorTileProvider,
    MVTProviderReleaseContext,
    martin_provider_manifest,
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
) -> tuple[MVTProviderReleaseContext, dict[str, object]]:
    """Load the one active, release-bound Martin MVT target from the authority."""
    projection = gateway.get_gis_service_control_projection(tenant_id, service_urn)
    release = projection.active_release_binding
    tile_matrix_set = projection.active_tile_matrix_set_definition_version
    serving_projection = projection.active_mvt_serving_projection_version
    definition = projection.active_service_definition_version
    deployment = projection.active_deployment_revision
    endpoint = projection.active_endpoint_revision
    if any(
        component is None
        for component in (
            release,
            tile_matrix_set,
            serving_projection,
            definition,
            deployment,
            endpoint,
        )
    ):
        raise GISProviderContractError(
            "active GIS service does not expose a complete MVT release projection"
        )
    if definition.service_type is not GISServiceType.VECTOR_TILE:
        raise GISProviderContractError("active GIS service is not a vector-tile service")
    if deployment.provider_system != "martin":
        raise GISProviderContractError("active GIS service does not use Martin")
    if deployment.state is not ServiceDeploymentState.READY:
        raise GISProviderContractError("active Martin deployment is not ready")
    if endpoint.endpoint_protocol is not EndpointProtocol.MVT:
        raise GISProviderContractError("active GIS endpoint is not MVT")
    endpoint_contract = endpoint.endpoint_contract
    expected_query = {
        "serving_projection_version_id": str(
            serving_projection.mvt_serving_projection_version_id
        )
    }
    if (
        endpoint_contract.get("schema") != "gda.mvt_endpoint.v1"
        or endpoint_contract.get("provider_layer_ref")
        != "gda_mvt_serving_projection"
        or endpoint_contract.get("provider_query") != expected_query
    ):
        raise GISProviderContractError(
            "active MVT endpoint does not bind its serving projection exactly"
        )
    context = MVTProviderReleaseContext.from_release(
        release,
        tile_matrix_set,
        serving_projection,
        service_type=definition.service_type,
        provider_layer_ref="gda_mvt_serving_projection",
        provider_query=expected_query,
    )
    return context, {
        "tenant_id": context.tenant_id,
        "service_urn": service_urn,
        "endpoint_state_version": projection.endpoint_state_version,
        "endpoint_revision_id": str(endpoint.endpoint_revision_id),
        "consumer_endpoint_uri": endpoint.endpoint_uri,
        "deployment_revision_id": str(deployment.deployment_revision_id),
        "service_release_binding_id": str(context.service_release_binding_id),
        "mvt_serving_projection_version_id": str(
            context.mvt_serving_projection_version_id
        ),
    }


async def _certify_discovery(endpoint: str) -> dict[str, object]:
    provider = MartinVectorTileProvider(endpoint, manifest=martin_provider_manifest())
    health = await provider.health()
    catalog = await provider.discover_capabilities()
    return {
        "schema": "gda.gis_martin_provider_certification.v2",
        "status": "discovery_only",
        "provider_endpoint": provider.endpoint_uri,
        "manifest": provider.manifest.model_dump(mode="json"),
        "health": health.model_dump(mode="json"),
        "catalog_sha256": canonical_json_fingerprint(catalog),
        "control_target": None,
        "conformance_receipt": None,
    }


async def _certify_active_release(
    endpoint: str,
    context: MVTProviderReleaseContext,
    control_target: dict[str, object],
    *,
    z: int,
    x: int,
    y: int,
    warmup_target=None,
    warmup_samples: tuple[MartinMVTWarmupSample, ...] = (),
) -> dict[str, object]:
    provider = MartinVectorTileProvider(endpoint, manifest=martin_provider_manifest())
    receipt = await provider.conform_mvt_read(context, z, x, y)
    warmup_receipt = None
    if warmup_samples:
        if warmup_target is None:
            raise GISProviderContractError(
                "Martin warmup certification requires its control-plane target"
            )
        release, deployment, consumer_endpoint, cache_policy = warmup_target
        warmup_receipt = await provider.warmup_mvt_tiles(
            context,
            release,
            deployment,
            consumer_endpoint,
            cache_policy,
            warmup_samples,
        )
    return {
        "schema": "gda.gis_martin_provider_certification.v2",
        "status": (
            "active_release_warmup_certified"
            if warmup_receipt is not None
            else "active_release_read_certified"
        ),
        "provider_endpoint": provider.endpoint_uri,
        "manifest": provider.manifest.model_dump(mode="json"),
        "health": receipt.health.model_dump(mode="json"),
        "catalog_sha256": receipt.catalog_sha256,
        "control_target": control_target,
        "conformance_receipt": receipt.model_dump(mode="json", by_alias=True),
        "warmup_receipt": (
            warmup_receipt.model_dump(mode="json", by_alias=True)
            if warmup_receipt is not None
            else None
        ),
    }


def _write_report(report: dict[str, object], report_path: Path | None) -> None:
    if report_path is None:
        return
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def certify(
    endpoint: str,
    *,
    database_url: str | None = None,
    tenant_id: str | None = None,
    service_urn: str | None = None,
    z: int = 0,
    x: int = 0,
    y: int = 0,
    warmup_samples: tuple[MartinMVTWarmupSample, ...] = (),
    report_path: Path | None = None,
) -> dict[str, object]:
    read_mode = (database_url is not None, tenant_id is not None, service_urn is not None)
    if any(read_mode) and not all(read_mode):
        raise GISProviderContractError(
            "active release certification requires database_url, tenant_id, and service_urn"
        )
    if not all(read_mode):
        report = asyncio.run(_certify_discovery(endpoint))
    else:
        engine = create_engine(database_url)
        try:
            gateway = PlatformGateway(engine)
            context, control_target = _active_release_context(
                gateway,
                tenant_id=tenant_id,
                service_urn=service_urn,
            )
            warmup_target = None
            if warmup_samples:
                projection = gateway.get_gis_service_control_projection(
                    tenant_id, service_urn
                )
                warmup_target = (
                    projection.active_release_binding,
                    projection.active_deployment_revision,
                    projection.active_endpoint_revision,
                    projection.active_cache_policy_version,
                )
                if any(item is None for item in warmup_target):
                    raise GISProviderContractError(
                        "active GIS service lacks a complete warmup target"
                    )
            report = asyncio.run(
                _certify_active_release(
                    endpoint,
                    context,
                    control_target,
                    z=z,
                    x=x,
                    y=y,
                    warmup_target=warmup_target,
                    warmup_samples=warmup_samples,
                )
            )
        finally:
            engine.dispose()
    _write_report(report, report_path)
    return report


def _parse_warmup_sample(value: str) -> MartinMVTWarmupSample:
    try:
        z, x, y = (int(item) for item in value.split("/"))
        return MartinMVTWarmupSample(z=z, x=x, y=y)
    except (TypeError, ValueError) as exc:
        raise argparse.ArgumentTypeError(
            "warmup sample must use z/x/y integer coordinates"
        ) from exc


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--endpoint", default="http://127.0.0.1:3000")
    parser.add_argument("--database-url")
    parser.add_argument("--tenant")
    parser.add_argument("--service-urn")
    parser.add_argument("--z", type=int, default=0)
    parser.add_argument("--x", type=int, default=0)
    parser.add_argument("--y", type=int, default=0)
    parser.add_argument(
        "--warmup-sample",
        action="append",
        type=_parse_warmup_sample,
        default=[],
        help="repeat z/x/y to certify a bounded Martin origin warmup set",
    )
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    try:
        report = certify(
            args.endpoint,
            database_url=args.database_url,
            tenant_id=args.tenant,
            service_urn=args.service_urn,
            z=args.z,
            x=args.x,
            y=args.y,
            warmup_samples=tuple(args.warmup_sample),
            report_path=args.report,
        )
    except GISProviderRuntimeError as exc:
        raise SystemExit(f"Martin provider certification failed: {exc}") from exc
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
