#!/usr/bin/env python3
"""Certify local PostgreSQL, MinIO, and STAC connector capabilities."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.request import urlopen

from dotenv import dotenv_values

from data_agent.source_connector_governance import (
    CapabilityStatus,
    CredentialAuthType,
    CredentialReference,
    MappingCredentialResolver,
    SourceConnectorKind,
    SourceDefinition,
    certify_source_connector,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REPORT = REPO_ROOT / ".tmp/source-connector-certification/acceptance-report.json"
OSM_COLLECTION = "chongqing-osm-roads"
OSM_ITEM_KEY = "catalog/stac/data-products/chongqing-osm-roads/items/v1.2.0.json"


class _StacHandler(BaseHTTPRequestHandler):
    item: dict[str, Any] = {}

    def do_GET(self) -> None:  # noqa: N802
        if self.path.rstrip("/") == "":
            self._json(
                {
                    "type": "Catalog",
                    "id": "gda-local-governed-stac-api",
                    "stac_version": "1.0.0",
                    "description": "Local STAC API over the governed Chongqing OSM item",
                    "conformsTo": [
                        "https://api.stacspec.org/v1.0.0/core",
                        "https://api.stacspec.org/v1.0.0/item-search",
                    ],
                    "links": [],
                }
            )
            return
        if self.path.rstrip("/") == "/collections":
            self._json(
                {
                    "collections": [
                        {
                            "id": OSM_COLLECTION,
                            "title": "Chongqing OSM Roads",
                            "description": "Governed real-data product collection",
                        }
                    ],
                    "links": [],
                }
            )
            return
        self.send_error(404)

    def do_POST(self) -> None:  # noqa: N802
        if self.path.rstrip("/") != "/search":
            self.send_error(404)
            return
        length = int(self.headers.get("Content-Length", "0"))
        request = json.loads(self.rfile.read(length) or b"{}")
        collections = request.get("collections") or []
        features = [] if collections and OSM_COLLECTION not in collections else [self.item]
        self._json(
            {
                "type": "FeatureCollection",
                "features": features[: int(request.get("limit", 10))],
                "links": [],
            },
            content_type="application/geo+json",
        )

    def log_message(self, format: str, *args: object) -> None:
        return

    def _json(self, value: dict[str, Any], *, content_type: str = "application/json") -> None:
        payload = json.dumps(value, ensure_ascii=False, sort_keys=True).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


@contextmanager
def _local_stac_api(item: dict[str, Any]) -> Iterator[str]:
    handler = type("GovernedStacHandler", (_StacHandler,), {"item": item})
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()


def _settings() -> dict[str, str]:
    values = {
        key: str(value)
        for key, value in dotenv_values(REPO_ROOT / ".env").items()
        if value is not None
    }
    return {**values, **os.environ}


def _credential(
    credential_id: str,
    auth_type: CredentialAuthType,
    provider: str,
) -> CredentialReference:
    return CredentialReference(
        credential_id=credential_id,
        version=1,
        auth_type=auth_type,
        provider=provider,
    )


async def _certify(args: argparse.Namespace) -> dict[str, Any]:
    settings = _settings()
    postgres_reference = _credential(
        "credential:local-postgres-certification",
        CredentialAuthType.BASIC,
        "compose-runtime-secret",
    )
    minio_reference = _credential(
        "credential:local-minio-certification",
        CredentialAuthType.AWS_SIGV4,
        "compose-runtime-secret",
    )
    anonymous_reference = _credential(
        "credential:local-stac-anonymous",
        CredentialAuthType.NONE,
        "anonymous",
    )
    credentials = {
        (postgres_reference.credential_id, 1): {
            "type": "basic",
            "username": settings.get("POSTGRES_USER", "postgres"),
            "password": settings.get(
                "POSTGRES_ADMIN_PASSWORD",
                settings.get("POSTGRES_PASSWORD", "postgres"),
            ),
        },
        (minio_reference.credential_id, 1): {
            "type": "aws_sigv4",
            "access_key_id": settings.get("MINIO_ROOT_USER", "minio_admin"),
            "secret_access_key": settings.get("MINIO_ROOT_PASSWORD", "local_dev_minio_secret"),
            "region_name": settings.get("AWS_REGION", "us-east-1"),
        },
        (anonymous_reference.credential_id, 1): {"type": "none"},
    }
    resolver = MappingCredentialResolver(credentials)
    with urlopen(args.osm_stac_item_url, timeout=10) as response:
        real_osm_item = json.load(response)
    if real_osm_item.get("id") != "chongqing-osm-roads-v1.2.0":
        raise RuntimeError("governed OSM STAC v1.2.0 item is not active")

    now = datetime.now(UTC)
    with _local_stac_api(real_osm_item) as stac_endpoint:
        definitions = (
            SourceDefinition(
                source_id="local-postgis-control-ledger",
                version="1.0.0",
                source_kind=SourceConnectorKind.DATABASE,
                endpoint_url=args.postgres_url,
                owner_ref="team:data-platform",
                credential_reference=postgres_reference,
                connector_version="1.0.0",
                query_config={"table": "gda_control.resource"},
            ),
            SourceDefinition(
                source_id="local-minio-osm-stac-item",
                version="1.0.0",
                source_kind=SourceConnectorKind.OBJECT_STORAGE,
                endpoint_url=args.minio_url,
                owner_ref="team:data-platform",
                credential_reference=minio_reference,
                connector_version="1.0.0",
                query_config={
                    "bucket": "gis-agent-lakehouse",
                    "key": OSM_ITEM_KEY,
                    "format": "geojson",
                    "discovery_limit": 10,
                },
            ),
            SourceDefinition(
                source_id="local-http-stac-osm",
                version="1.0.0",
                source_kind=SourceConnectorKind.STAC,
                endpoint_url=stac_endpoint,
                owner_ref="team:data-platform",
                credential_reference=anonymous_reference,
                connector_version="1.0.0",
                query_config={"collection_id": OSM_COLLECTION},
            ),
        )
        reports = [
            await certify_source_connector(
                definition,
                resolver,
                certified_at=now,
            )
            for definition in definitions
        ]
        replays = [
            await certify_source_connector(
                definition,
                resolver,
                certified_at=now,
            )
            for definition in definitions
        ]

        bad_credentials = dict(credentials)
        bad_credentials[(postgres_reference.credential_id, 1)] = {
            "type": "basic",
            "username": "invalid-user",
            "password": "certification-secret-must-not-leak",
        }
        bad_database = await certify_source_connector(
            definitions[0],
            MappingCredentialResolver(bad_credentials),
            certified_at=now,
        )
        bad_credentials = dict(credentials)
        bad_credentials[(minio_reference.credential_id, 1)] = {
            "type": "aws_sigv4",
            "access_key_id": "invalid-access-key",
            "secret_access_key": "certification-secret-must-not-leak",
            "region_name": "us-east-1",
        }
        bad_object_storage = await certify_source_connector(
            definitions[1],
            MappingCredentialResolver(bad_credentials),
            certified_at=now,
        )
        interrupted_stac = definitions[2].model_copy(update={"endpoint_url": "http://127.0.0.1:1"})
        network_interruption = await certify_source_connector(
            interrupted_stac,
            resolver,
            certified_at=now,
        )

    replay_stable = all(
        first.discovery is not None
        and second.discovery is not None
        and first.profile is not None
        and second.profile is not None
        and first.discovery.fingerprint == second.discovery.fingerprint
        and first.profile.fingerprint == second.profile.fingerprint
        for first, second in zip(reports, replays, strict=True)
    )
    negative_controls = {
        "database_bad_credentials_failed": bad_database.status.value == "failed",
        "object_storage_bad_credentials_failed": bad_object_storage.status.value == "failed",
        "stac_network_interruption_failed": network_interruption.status.value == "failed",
        "credential_secret_redacted": "certification-secret-must-not-leak"
        not in json.dumps(
            [
                bad_database.model_dump(mode="json"),
                bad_object_storage.model_dump(mode="json"),
            ]
        ),
    }
    all_passed = all(report.status.value == "passed" for report in reports)
    all_capabilities_passed = all(
        capability.status is CapabilityStatus.PASSED
        for report in reports
        for capability in report.capabilities
    )
    return {
        "schema": "gda.source_connector_certification.acceptance.v1",
        "generated_at": now.isoformat(),
        "status": (
            "passed"
            if all_passed
            and all_capabilities_passed
            and replay_stable
            and all(negative_controls.values())
            else "failed"
        ),
        "scope": {
            "operations": ["connect", "discover", "preview", "profile"],
            "read_only": True,
            "real_input": "governed Chongqing OSM roads STAC item v1.2.0",
            "not_claimed": [
                "provider credential rotation",
                "live provider schema mutation",
                "full or incremental ingestion",
                "CDC",
            ],
        },
        "source_definitions": [definition.model_dump(mode="json") for definition in definitions],
        "certifications": [report.model_dump(mode="json") for report in reports],
        "replay": {
            "stable": replay_stable,
            "discovery_fingerprints": [
                report.discovery.fingerprint if report.discovery else None for report in replays
            ],
            "profile_fingerprints": [
                report.profile.fingerprint if report.profile else None for report in replays
            ],
        },
        "negative_controls": negative_controls,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--postgres-url",
        default="postgresql://127.0.0.1:5433/gis_agent",
    )
    parser.add_argument("--minio-url", default="http://127.0.0.1:9000")
    parser.add_argument(
        "--osm-stac-item-url",
        default="http://127.0.0.1:8000/api/data-products/chongqing-osm-roads/stac",
    )
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    args = parser.parse_args()
    report = asyncio.run(_certify(args))
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "status": report["status"],
                "report": str(args.report),
                "sources": len(report["certifications"]),
                "capabilities": sum(
                    len(certification["capabilities"]) for certification in report["certifications"]
                ),
            },
            sort_keys=True,
        )
    )
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
