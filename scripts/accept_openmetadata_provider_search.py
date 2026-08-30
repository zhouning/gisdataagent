#!/usr/bin/env python3
"""Real-provider acceptance for the bounded OpenMetadata search/read bridge."""

from __future__ import annotations

import argparse
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import httpx

from data_agent.metadata_fabric import (
    MetadataFabricBinding,
    MetadataFabricSystem,
    metadata_fabric_binding_fingerprint,
)
from data_agent.metadata_provider_health import check_metadata_provider
from data_agent.metadata_provider_metrics import metadata_provider_operations
from data_agent.metadata_provider_read import (
    MetadataProviderReadService,
    OpenMetadataProviderReadClient,
    ProviderReadStatus,
)
from data_agent.metadata_provider_search import (
    MetadataProviderSearchService,
    OpenMetadataMetadataProviderSearchClient,
)
from data_agent.platform_contracts import canonical_json_fingerprint


class AcceptanceError(RuntimeError):
    """A required real-provider acceptance assertion failed."""


def _require_success(response: httpx.Response, operation: str) -> dict[str, Any]:
    if not 200 <= response.status_code < 300:
        body = response.text[:500].replace("\n", " ")
        raise AcceptanceError(f"{operation} failed with HTTP {response.status_code}: {body}")
    try:
        payload = response.json()
    except ValueError as exc:
        raise AcceptanceError(f"{operation} returned invalid JSON") from exc
    if not isinstance(payload, dict):
        raise AcceptanceError(f"{operation} returned an invalid document")
    return payload


def _discover_table(
    client: httpx.Client,
    *,
    query: str,
    service_prefix: str,
) -> tuple[str, str, str]:
    payload = _require_success(
        client.get(
            "/api/v1/search/query",
            params={"q": query, "index": "table_search_index", "from": 0, "size": 100},
        ),
        "OpenMetadata table search discovery",
    )
    hits = payload.get("hits")
    if not isinstance(hits, dict) or not isinstance(hits.get("hits"), list):
        raise AcceptanceError("OpenMetadata table search discovery returned no hits")
    for hit in hits["hits"]:
        if not isinstance(hit, dict) or not isinstance(hit.get("_source"), dict):
            continue
        source = hit["_source"]
        if source.get("name") != query:
            continue
        raw_id = source.get("id") or hit.get("_id")
        fqn = source.get("fullyQualifiedName")
        if not isinstance(raw_id, str) or not isinstance(fqn, str):
            continue
        try:
            object_id = str(UUID(raw_id))
        except ValueError:
            continue
        service = source.get("service")
        service_name = None
        if isinstance(service, dict):
            candidate = service.get("name") or service.get("fullyQualifiedName")
            if isinstance(candidate, str):
                service_name = candidate
        if service_name is None:
            service_name = fqn.split(".", 1)[0]
        if service_name.startswith(service_prefix):
            return object_id, f"service:{service_name}", fqn
    raise AcceptanceError(
        f"OpenMetadata search did not discover a {query!r} table in {service_prefix!r}"
    )


def run_acceptance(args: argparse.Namespace) -> dict[str, Any]:
    if not args.token_file.is_absolute():
        raise AcceptanceError("--token-file must be absolute")
    token = args.token_file.read_text(encoding="utf-8").strip()
    if not token or any(character.isspace() for character in token):
        raise AcceptanceError("token file must contain one non-empty token")
    headers = {"Authorization": f"Bearer {token}"}
    with httpx.Client(
        base_url=args.openmetadata_url.rstrip("/"),
        timeout=args.timeout_seconds,
        follow_redirects=False,
        headers=headers,
    ) as provider:
        object_id, provider_namespace, fqn = _discover_table(
            provider,
            query=args.query,
            service_prefix=args.service_prefix,
        )
    tenant_id = f"om-search-acceptance-{uuid4().hex[:12]}"
    os.environ["GDA_OPENMETADATA_URL"] = args.openmetadata_url
    if args.source_only:
        os.environ.pop("GDA_OPENMETADATA_BEARER_TOKEN_FILE", None)
        os.environ["GDA_OPENMETADATA_BEARER_TOKEN_SOURCE"] = str(args.token_file)
    else:
        os.environ["GDA_OPENMETADATA_BEARER_TOKEN_FILE"] = str(args.token_file)
        os.environ.pop("GDA_OPENMETADATA_BEARER_TOKEN_SOURCE", None)
    provider_health = check_metadata_provider(MetadataFabricSystem.OPENMETADATA)
    if provider_health["status"] != "ok":
        raise AcceptanceError(
            f"OpenMetadata provider health probe failed: {provider_health['status']}"
        )
    if args.source_only:
        with MetadataProviderSearchService.from_env() as search_service:
            page = search_service.search(
                tenant_id,
                system="openmetadata",
                provider_namespace=provider_namespace,
                object_type="table",
                query=args.query,
                limit=100,
                offset=0,
            )
    else:
        search_client = OpenMetadataMetadataProviderSearchClient(
            args.openmetadata_url,
            bearer_token_file=args.token_file,
            timeout_seconds=args.timeout_seconds,
        )
        try:
            page = search_client.search(
                tenant_id,
                provider_namespace=provider_namespace,
                object_type="table",
                query=args.query,
                limit=100,
                offset=0,
            )
        finally:
            search_client.close()
    matching = [item for item in page.items if item.external_object_id == object_id]
    if len(matching) != 1:
        raise AcceptanceError(
            f"bounded provider search returned {len(matching)} exact candidates for {object_id}"
        )
    candidate = matching[0]
    expected_candidate_fingerprint = canonical_json_fingerprint(
        {
            "schema": "gda.metadata_provider_search.v1",
            "tenant_id": tenant_id,
            "system": "openmetadata",
            "provider_namespace": provider_namespace,
            "external_object_id": object_id,
            "external_object_type": "table",
        }
    )
    if candidate.candidate_sha256 != expected_candidate_fingerprint:
        raise AcceptanceError("provider-search candidate fingerprint did not remain stable")

    binding_values = {
        "tenant_id": tenant_id,
        "binding_id": uuid4(),
        "resource_urn": f"gda://{tenant_id}/dataset/{args.query}",
        "system": "openmetadata",
        "binding_kind": "governance_entity",
        "external_namespace": provider_namespace,
        "external_object_id": object_id,
        "external_object_type": "table",
        "external_version_ref": "1.13.1",
        "created_by": "workload:openmetadata-search-acceptance",
        "created_at": datetime.now(UTC),
    }
    binding_values["binding_sha256"] = metadata_fabric_binding_fingerprint(
        **{
            key: binding_values[key]
            for key in (
                "tenant_id",
                "resource_urn",
                "system",
                "binding_kind",
                "external_namespace",
                "external_object_id",
                "external_object_type",
                "external_version_ref",
            )
        }
    )
    binding = MetadataFabricBinding(**binding_values)
    if args.source_only:
        with MetadataProviderReadService.from_env() as read_service:
            read_result = read_service.read(binding)
    else:
        with OpenMetadataProviderReadClient(
            args.openmetadata_url,
            bearer_token_file=args.token_file,
            timeout_seconds=args.timeout_seconds,
        ) as read_client:
            read_result = read_client.read(binding)
    if read_result.status is not ProviderReadStatus.PRESENT:
        raise AcceptanceError("UUID provider read did not confirm the searched table")
    if read_result.evidence.get("fullyQualifiedName") != fqn:
        raise AcceptanceError("UUID provider read returned a different table FQN")
    provider_metrics_observed = any(
        sample.labels.get("operation") in {"read", "search"}
        for metric in metadata_provider_operations.collect()
        for sample in metric.samples
    )
    return {
        "schema": "gda.openmetadata_provider_search_acceptance.v1",
        "status": "passed",
        "verified_at": datetime.now(UTC).isoformat(),
        "provider": {"product": "OpenMetadata", "version": "1.13.1"},
        "credential_source": "GDA_OPENMETADATA_BEARER_TOKEN_SOURCE"
        if args.source_only
        else "explicit_token_file",
        "observability": {
            "provider_operation_metrics_observed": provider_metrics_observed,
        },
        "health": {
            "status": provider_health["status"],
            "endpoint": provider_health["endpoint"],
            "status_code": provider_health["status_code"],
            "retryable": provider_health["retryable"],
            "code": provider_health["code"],
        },
        "search": {
            "tenant_id": tenant_id,
            "provider_namespace": provider_namespace,
            "query": args.query,
            "candidate": candidate.model_dump(mode="json"),
            "page_count": page.count,
        },
        "read_after_search": {
            "status": read_result.status.value,
            "provider_revision": read_result.provider_revision,
            "provider_fingerprint": read_result.provider_fingerprint,
            "fully_qualified_name": fqn,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--openmetadata-url", default="http://127.0.0.1:18585")
    parser.add_argument("--token-file", type=Path, required=True)
    parser.add_argument("--query", default="source_parcels")
    parser.add_argument("--service-prefix", default="gda_acceptance_")
    parser.add_argument("--timeout-seconds", type=float, default=20.0)
    parser.add_argument(
        "--source-only",
        action="store_true",
        help="exercise provider bridges through GDA_OPENMETADATA_BEARER_TOKEN_SOURCE",
    )
    parser.add_argument("--evidence-file", type=Path)
    args = parser.parse_args()
    evidence = run_acceptance(args)
    rendered = json.dumps(evidence, indent=2, sort_keys=True)
    if args.evidence_file is not None:
        args.evidence_file.parent.mkdir(parents=True, exist_ok=True)
        args.evidence_file.write_text(f"{rendered}\n", encoding="utf-8")
    print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
