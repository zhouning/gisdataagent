#!/usr/bin/env python3
"""Certify the governed Martin MVT provider boundary.

The default run certifies live health and catalog discovery. Supplying
``--publication-id`` additionally performs a real tile read and upgrades the
report from discovery-only to read-certified. The script does not create a
service, deployment, or provider-side catalog.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from data_agent.gis_provider_runtime import (
    GISProviderRuntimeError,
    MartinVectorTileProvider,
    MVTProviderReleaseContext,
    martin_provider_manifest,
)
from data_agent.gis_service_control_plane import (
    GISServiceType,
    ServiceReleaseBinding,
    TileMatrixSetDefinitionVersion,
    service_release_binding_fingerprint,
    tile_matrix_set_definition_fingerprint,
)
from data_agent.platform_contracts import canonical_json_fingerprint


def _context(provider_layer_ref: str, publication_id: str | None) -> MVTProviderReleaseContext:
    service_definition_id = uuid4()
    layer_id = uuid4()
    tms_values = {
        "tenant_id": "certification",
        "tile_matrix_set_definition_version_id": uuid4(),
        "service_definition_version_id": service_definition_id,
        "layer_definition_version_id": layer_id,
        "tile_matrix_set_key": "webmercatorquad",
        "version_key": "v1.0.0",
        "crs_uri": "http://www.opengis.net/def/crs/EPSG/0/3857",
        "tile_width": 256,
        "tile_height": 256,
        "min_zoom": 0,
        "max_zoom": 30,
        "scale_denominators": tuple(
            559082264.029 / (2**zoom) for zoom in range(31)
        ),
        "spatial_extent": (-20037508.0, -20037508.0, 20037508.0, 20037508.0),
        "created_by": "workload:gis-provider-certifier",
        "created_at": datetime.now(UTC),
    }
    tms = TileMatrixSetDefinitionVersion(
        **tms_values,
        definition_sha256=tile_matrix_set_definition_fingerprint(tms_values),
    )
    release_values = {
        "tenant_id": "certification",
        "service_release_binding_id": uuid4(),
        "service_definition_version_id": service_definition_id,
        "layer_definition_version_id": layer_id,
        "style_definition_version_id": uuid4(),
        "tile_matrix_set_definition_version_id": (
            tms.tile_matrix_set_definition_version_id
        ),
        "release_key": "v1.0.0",
        "created_by": "workload:gis-provider-certifier",
        "created_at": tms.created_at,
    }
    release = ServiceReleaseBinding(
        **release_values,
        binding_sha256=service_release_binding_fingerprint(release_values),
    )
    return MVTProviderReleaseContext.from_release(
        release,
        tms,
        service_type=GISServiceType.VECTOR_TILE,
        provider_layer_ref=provider_layer_ref,
        provider_query=(
            {"publication_id": publication_id} if publication_id is not None else None
        ),
    )


async def _certify(
    endpoint: str,
    provider_layer_ref: str,
    publication_id: str | None,
    z: int,
    x: int,
    y: int,
) -> dict[str, object]:
    provider = MartinVectorTileProvider(endpoint, manifest=martin_provider_manifest())
    health = await provider.health()
    catalog = await provider.discover_capabilities()
    tiles = catalog.get("tiles", {})
    if provider_layer_ref not in tiles:
        raise GISProviderRuntimeError(
            f"Martin catalog does not advertise tile source {provider_layer_ref!r}"
        )
    tile_report: dict[str, object] = {"performed": False}
    release_report: dict[str, object] | None = None
    if publication_id is not None:
        context = _context(provider_layer_ref, publication_id)
        tile = await provider.fetch_tile(context, z, x, y)
        if not tile.content:
            raise GISProviderRuntimeError(
                "Martin tile read returned an empty body; certification requires "
                "a non-empty fixture tile"
            )
        release_report = {
            "tenant_id": context.tenant_id,
            "service_type": context.service_type.value,
            "service_release_binding_id": str(context.service_release_binding_id),
            "service_definition_version_id": str(
                context.service_definition_version_id
            ),
            "layer_definition_version_id": str(context.layer_definition_version_id),
            "style_definition_version_id": str(context.style_definition_version_id),
            "tile_matrix_set_definition_version_id": str(
                context.tile_matrix_set_definition_version_id
            ),
            "tile_matrix_set_crs_uri": context.tile_matrix_set_crs_uri,
            "min_zoom": context.min_zoom,
            "max_zoom": context.max_zoom,
            "provider_layer_ref": context.provider_layer_ref,
        }
        tile_report = {
            "performed": True,
            "publication_id": publication_id,
            "z": z,
            "x": x,
            "y": y,
            "status_code": tile.status_code,
            "media_type": tile.media_type,
            "content_bytes": len(tile.content),
            "content_sha256": hashlib.sha256(tile.content).hexdigest(),
            "etag": tile.etag,
        }
    return {
        "schema": "gda.gis_martin_provider_certification.v1",
        "status": "read_certified" if publication_id is not None else "discovery_only",
        "endpoint": endpoint.rstrip("/"),
        "manifest": {
            "provider_system": provider.manifest.provider_system,
            "provider_version": provider.manifest.provider_version,
            "manifest_sha256": provider.manifest.manifest_sha256,
        },
        "health": {
            "state": health.state.value,
            "status_code": health.status_code,
            "evidence_sha256": health.evidence_sha256,
        },
        "catalog_sha256": canonical_json_fingerprint(catalog),
        "release_context": release_report,
        "tile": tile_report,
    }


def certify(
    endpoint: str,
    *,
    provider_layer_ref: str = "map_publication",
    publication_id: str | None = None,
    z: int = 0,
    x: int = 0,
    y: int = 0,
    report_path: Path | None = None,
) -> dict[str, object]:
    report = asyncio.run(
        _certify(endpoint, provider_layer_ref, publication_id, z, x, y)
    )
    if report_path is not None:
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(
            json.dumps(report, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--endpoint", default="http://127.0.0.1:3000")
    parser.add_argument("--provider-layer", default="map_publication")
    parser.add_argument("--publication-id")
    parser.add_argument("--z", type=int, default=0)
    parser.add_argument("--x", type=int, default=0)
    parser.add_argument("--y", type=int, default=0)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    try:
        report = certify(
            args.endpoint,
            provider_layer_ref=args.provider_layer,
            publication_id=args.publication_id,
            z=args.z,
            x=args.x,
            y=args.y,
            report_path=args.report,
        )
    except GISProviderRuntimeError as exc:
        raise SystemExit(f"Martin provider certification failed: {exc}") from exc
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
