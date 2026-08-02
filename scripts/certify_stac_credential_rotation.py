#!/usr/bin/env python3
"""Certify bearer credential rotation against an authenticated STAC transport."""

from __future__ import annotations

import argparse
import asyncio
import copy
import hmac
import json
import secrets
import threading
from collections import Counter
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.request import urlopen

from data_agent.source_connector_governance import (
    CertificationStatus,
    CredentialAuthType,
    CredentialReference,
    MappingCredentialResolver,
    SourceConnectorKind,
    SourceDefinition,
    certify_source_connector,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REPORT = REPO_ROOT / ".tmp/source-connector-certification/stac-rotation-report.json"
OSM_COLLECTION = "chongqing-osm-roads"


class _CredentialState:
    """Hold the active provider credential without retaining it in observations."""

    def __init__(self, token: str) -> None:
        self._token = token
        self._revision = 1
        self._observations: list[dict[str, Any]] = []
        self._lock = threading.Lock()

    def authorize(self, method: str, path: str, authorization: str) -> bool:
        with self._lock:
            authorized = hmac.compare_digest(authorization, f"Bearer {self._token}")
            self._observations.append(
                {
                    "method": method,
                    "path": path,
                    "accepted_revision": self._revision,
                    "authorized": authorized,
                }
            )
            return authorized

    def rotate(self, token: str) -> None:
        with self._lock:
            self._token = token
            self._revision += 1

    def evidence(self) -> dict[str, Any]:
        with self._lock:
            path_counts = Counter(f"{item['method']} {item['path']}" for item in self._observations)
            return {
                "active_revision": self._revision,
                "authorized_requests": sum(bool(item["authorized"]) for item in self._observations),
                "unauthorized_requests": sum(
                    not bool(item["authorized"]) for item in self._observations
                ),
                "request_counts": dict(sorted(path_counts.items())),
                "stores_authorization_header": False,
            }


class _AuthenticatedStacHandler(BaseHTTPRequestHandler):
    item: dict[str, Any] = {}
    credentials: _CredentialState

    def do_GET(self) -> None:  # noqa: N802
        if not self._authorized():
            return
        if self.path.rstrip("/") == "":
            self._json(
                {
                    "type": "Catalog",
                    "id": "gda-authenticated-stac-transport",
                    "stac_version": "1.0.0",
                    "description": "Authenticated transport over a governed GDA STAC item",
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
        if not self._authorized():
            return
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

    def _authorized(self) -> bool:
        authorized = self.credentials.authorize(
            self.command,
            self.path,
            self.headers.get("Authorization", ""),
        )
        if not authorized:
            self._json(
                {"code": "Unauthorized", "description": "Bearer credential rejected"},
                status=401,
            )
        return authorized

    def _json(
        self,
        value: dict[str, Any],
        *,
        status: int = 200,
        content_type: str = "application/json",
    ) -> None:
        payload = json.dumps(value, ensure_ascii=False, sort_keys=True).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


class _AuthenticatedStacTransport:
    def __init__(self, item: dict[str, Any], credentials: _CredentialState) -> None:
        handler = type(
            "GovernedAuthenticatedStacHandler",
            (_AuthenticatedStacHandler,),
            {"item": item, "credentials": credentials},
        )
        self._handler = handler
        self._server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)

    @property
    def endpoint_url(self) -> str:
        return f"http://127.0.0.1:{self._server.server_port}"

    def start(self) -> None:
        self._thread.start()

    def replace_item(self, item: dict[str, Any]) -> None:
        """Atomically replace the isolated provider's current item document."""

        self._handler.item = copy.deepcopy(item)

    def stop(self) -> dict[str, bool]:
        self._server.shutdown()
        self._thread.join(timeout=5)
        self._server.server_close()
        return {
            "server_closed": self._server.socket.fileno() == -1,
            "thread_stopped": not self._thread.is_alive(),
        }


def _credential(version: int) -> CredentialReference:
    return CredentialReference(
        credential_id="credential:stac-rotation-certification",
        version=version,
        auth_type=CredentialAuthType.BEARER,
        provider="ephemeral-authenticated-stac-transport",
    )


def _definition(endpoint_url: str, credential: CredentialReference) -> SourceDefinition:
    return SourceDefinition(
        source_id="authenticated-stac-rotation-certification",
        version=f"1.0.{credential.version - 1}",
        source_kind=SourceConnectorKind.STAC,
        endpoint_url=endpoint_url,
        owner_ref="team:data-platform",
        credential_reference=credential,
        connector_version="1.0.0",
        query_config={"collection_id": OSM_COLLECTION},
    )


def _resolver(reference: CredentialReference, token: str) -> MappingCredentialResolver:
    return MappingCredentialResolver(
        {
            (reference.credential_id, reference.version): {
                "type": "bearer",
                "token": token,
            }
        }
    )


async def _certify(
    endpoint_url: str,
    credentials: _CredentialState,
    token_v1: str,
    token_v2: str,
) -> dict[str, Any]:
    reference_v1 = _credential(1)
    reference_v2 = _credential(2)
    definition_v1 = _definition(endpoint_url, reference_v1)
    definition_v2 = _definition(endpoint_url, reference_v2)
    now = datetime.now(UTC)

    initial = await certify_source_connector(
        definition_v1,
        _resolver(reference_v1, token_v1),
        certified_at=now,
    )
    wrong_token = secrets.token_urlsafe(32)
    wrong_credential = await certify_source_connector(
        definition_v1,
        _resolver(reference_v1, wrong_token),
        certified_at=now,
    )
    credentials.rotate(token_v2)
    stale = await certify_source_connector(
        definition_v1,
        _resolver(reference_v1, token_v1),
        certified_at=now,
    )
    rotated = await certify_source_connector(
        definition_v2,
        _resolver(reference_v2, token_v2),
        certified_at=now,
    )
    replay = await certify_source_connector(
        definition_v2,
        _resolver(reference_v2, token_v2),
        certified_at=now,
    )
    interrupted_definition = _definition("http://127.0.0.1:1", reference_v2)
    network_interruption = await certify_source_connector(
        interrupted_definition,
        _resolver(reference_v2, token_v2),
        certified_at=now,
    )

    reports = [
        initial,
        wrong_credential,
        stale,
        rotated,
        replay,
        network_interruption,
    ]
    secret_free_payload = json.dumps(
        [report.model_dump(mode="json") for report in reports],
        sort_keys=True,
    )
    provider_auth = credentials.evidence()
    checks = {
        "initial_credential_passed": initial.status is CertificationStatus.PASSED,
        "wrong_credential_failed": wrong_credential.status is CertificationStatus.FAILED,
        "stale_credential_failed_after_rotation": stale.status is CertificationStatus.FAILED,
        "rotated_credential_passed": rotated.status is CertificationStatus.PASSED,
        "credential_reference_changed": (
            reference_v1.fingerprint != reference_v2.fingerprint
            and definition_v1.fingerprint != definition_v2.fingerprint
        ),
        "rotation_preserved_catalog": (
            initial.discovery is not None
            and rotated.discovery is not None
            and initial.discovery.fingerprint == rotated.discovery.fingerprint
            and initial.profile is not None
            and rotated.profile is not None
            and initial.profile.fingerprint == rotated.profile.fingerprint
        ),
        "replay_fingerprints_stable": (
            rotated.discovery is not None
            and replay.discovery is not None
            and rotated.discovery.fingerprint == replay.discovery.fingerprint
            and rotated.profile is not None
            and replay.profile is not None
            and rotated.profile.fingerprint == replay.profile.fingerprint
            and rotated.fingerprint == replay.fingerprint
        ),
        "network_interruption_failed": (network_interruption.status is CertificationStatus.FAILED),
        "provider_observed_authorization": (
            provider_auth["active_revision"] == 2
            and provider_auth["authorized_requests"] >= 12
            and provider_auth["unauthorized_requests"] >= 2
            and not provider_auth["stores_authorization_header"]
        ),
        "credential_secrets_redacted": all(
            token not in secret_free_payload for token in (token_v1, token_v2, wrong_token)
        ),
    }
    return {
        "schema": "gda.stac_credential_rotation.acceptance.v1",
        "generated_at": now.isoformat(),
        "status": "passed" if all(checks.values()) else "failed",
        "provider": {
            "name": initial.provider,
            "version": initial.provider_version,
            "production_provider_certified": False,
        },
        "real_input": "governed Chongqing OSM roads STAC item v1.2.0",
        "checks": checks,
        "provider_authorization": provider_auth,
        "credential_rotation": {
            "before_reference_fingerprint": reference_v1.fingerprint,
            "after_reference_fingerprint": reference_v2.fingerprint,
            "before_definition_fingerprint": definition_v1.fingerprint,
            "after_definition_fingerprint": definition_v2.fingerprint,
            "stale_credential_status": stale.status.value,
            "rotated_credential_status": rotated.status.value,
            "discovery_and_profile_fingerprints_stable": checks["rotation_preserved_catalog"],
        },
        "certifications": {
            "initial": initial.model_dump(mode="json"),
            "wrong_credential": wrong_credential.model_dump(mode="json"),
            "stale": stale.model_dump(mode="json"),
            "rotated": rotated.model_dump(mode="json"),
            "replay": replay.model_dump(mode="json"),
            "network_interruption": network_interruption.model_dump(mode="json"),
        },
        "not_claimed": [
            "production stac-fastapi or pgSTAC provider certification",
            "STAC schema mutation or SchemaDriftEvent persistence",
            "full or incremental ingestion",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--osm-stac-item-url",
        default="http://127.0.0.1:8000/api/data-products/chongqing-osm-roads/stac",
    )
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    args = parser.parse_args()
    with urlopen(args.osm_stac_item_url, timeout=10) as response:
        real_osm_item = json.load(response)
    if real_osm_item.get("id") != "chongqing-osm-roads-v1.2.0":
        raise RuntimeError("governed OSM STAC v1.2.0 item is not active")

    token_v1 = secrets.token_urlsafe(32)
    token_v2 = secrets.token_urlsafe(32)
    credentials = _CredentialState(token_v1)
    transport = _AuthenticatedStacTransport(real_osm_item, credentials)
    report: dict[str, Any] | None = None
    cleanup: dict[str, bool] = {}
    try:
        transport.start()
        report = asyncio.run(
            _certify(
                transport.endpoint_url,
                credentials,
                token_v1,
                token_v2,
            )
        )
    finally:
        cleanup = transport.stop()
    if report is None:
        raise RuntimeError("STAC certification did not produce a report")
    report["cleanup"] = cleanup
    if not all(cleanup.values()):
        report["status"] = "failed"
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
                "checks": report["checks"],
                "cleanup": cleanup,
            },
            sort_keys=True,
        )
    )
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
